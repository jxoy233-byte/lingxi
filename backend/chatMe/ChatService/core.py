import json
import uuid
from datetime import datetime
from typing import AsyncGenerator, Set, List, Any

from fastapi import UploadFile
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph_sdk.auth.exceptions import HTTPException
from redisvl.query import FilterQuery
from langgraph.checkpoint.redis.util import from_storage_safe_id

from chatMe.ChatService import FILE_MAX_LENGTH, FILE_ALLOWED_TYPES
from chatMe.ChatService.config.models import MessageRole, Message, Conversation
from chatMe.ChatService.FilesLoaders.core import FilesLoaders
from chatMe.ChatWorkflow import ChatWorkflow, AIMessageType
from chatMe.logging_config import get_logger


class ChatService:
    """
    ChatMe服务对象：
    实现自定义langgraph服务
    """

    def __init__(self, workflow: ChatWorkflow):
        self.logger = get_logger(__class__.__name__)
        self.chat_workflow = workflow
        self.checkpointer = self.chat_workflow.checkpointer
        self.graph = self.chat_workflow.graph

    @property
    async def aget_conversation_ids(self) -> List[str]:
        """
        获取Redis中所有不重复的thread_id列表(基于alist方法为启发)
        :return: 所有不重复的thread_id列表
        """
        # 构造Redis Search查询
        query = FilterQuery(
            filter_expression="*",
            return_fields=["thread_id"],
            num_results=10000,
            sort_by=None,
        )

        try:
            # 执行查询
            search_results = await self.checkpointer.checkpoints_index.search(query)

            # 风险点1：处理search_results为None的情况
            if search_results is None:
                self.logger.info("Redis搜索结果为空（search_results为None）")
                return []

            # 风险点2：确保docs是可遍历的列表
            docs = getattr(search_results, "docs", [])
            if not isinstance(docs, list):
                self.logger.warning(f"Redis搜索结果docs格式异常，非列表类型：{type(docs)}")
                return []

            thread_ids: Set[str] = set()
            for doc in docs:
                # 风险点3：安全获取thread_id，避免属性不存在
                safe_thread_id = getattr(doc, "thread_id", None)
                if not safe_thread_id:  # 跳过空的safe_id
                    continue

                try:
                    # 风险点4：捕获ID转换函数的异常
                    raw_thread_id = from_storage_safe_id(safe_thread_id)
                    if raw_thread_id:  # 跳过转换后为空的ID
                        thread_ids.add(raw_thread_id)
                except Exception as e:
                    self.logger.warning(f"转换safe_id失败：{safe_thread_id}，错误：{e}")
                    continue

            # 排序并返回（空集合会返回空列表）
            return sorted(list(thread_ids))

        # 风险点5：捕获所有异常，而非仅HTTPException
        except HTTPException as e:
            self.logger.warning(f"Redis查询触发HTTP异常（无历史数据）：{e}")
            return []
        except Exception as e:
            # 兜底捕获所有其他异常（如连接错误、序列化错误等）
            self.logger.warning(f"获取conversation_ids失败：{type(e).__name__}: {e}")
            return []

    async def _process_files(self, files: List[UploadFile]):
        """
        创建FilesLoaders类实例,调用loading_files防擦，处理传入文件信息，返回处理好的分类文件内容
        :param files:
        :return: images_content（含图片信息列表）, text_content（含文本信息列表）, doc_content(文档信息列表), 额外参数files_list
        """

        fl = FilesLoaders(files)
        (images_content, text_content, doc_content) = await fl.loading_files()
        file_list = await fl.create_files_additional_kwargs()
        await fl.cleanup()

        return images_content, text_content, doc_content, file_list

    async def _save_round_checkpoint(self, session_id: str):
        """
        获取指定会话的所有 checkpoint_id 列表
        :param session_id: 会话 ID (thread_id)

        更新状态使得带有对应的checkpoint_id在最后一条SUMMARY的AI消息

        :return 修改成功的状态:True/False
        """
        try:
            config = {"configurable": {"thread_id": session_id}}

            state = await self.graph.aget_state(config=config)

            checkpoint_id = state.config["configurable"]["checkpoint_id"]

            if isinstance(state.values["messages"][-1], AIMessage):
                last_ai_message = list(state.values["messages"])[-1]
                last_ai_message.additional_kwargs["checkpoint_id"] = checkpoint_id

                state.values["messages"][-1] = last_ai_message
                await self.graph.aupdate_state(
                    config=config,
                    values=state.values,  # 把修改后的完整state值更新回去
                )
                return True

        except Exception as e:
            self.logger.error(f"保存检查点失败(session_id:{session_id}): {str(e)}")
            return False

    async def message_stream(
        self,
        message: str,
        session_id: str = None,
        files: list[UploadFile] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式响应用户信息

        Args:
            message: 用户信息
            session_id: 会话id

        Yields:
            基于流式传输的 JSON 字符串
        """

        (images_content, text_content, doc_content, file_list) = await self._process_files(files)

        message_content = [{"type": "text", "text": message, "text_file": False},]
        if text_content or images_content or doc_content:
            if images_content:
                for img in images_content:
                    message_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img["file_content"]}"}, "detail": "auto"})
            if text_content:
                message_content.append({"type": "text", "text": "接收到的文本文件:\n", "text_file": True})
                for text in text_content:
                    message_content.append({"type": "text", "text": text["file_content"], "text_file": True})
            if doc_content:
                for doc in doc_content:
                    if doc["file_type"] == ".pptx":
                        message_content.append({"type": "text", "text": "--用户传入的pptx--:\n", "text_file": True})
                        for img in doc["file_content"]["images"]:
                            message_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}, "detail": "auto"})
                    elif doc["file_type"] == ".docx":
                        message_content.append({"type": "text", "text": "--用户传入的docx--:\n", "text_file": True})
                        message_content.append({"type": "text", "text": "文本：\n" + doc["file_content"]["text"] + "\n", "text_file": True})
                        message_content.append({"type": "text", "text": "图片：\n", "text_file": True})
                        for img in doc["file_content"]["images"]:
                            message_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}, "detail": "auto"})
                    elif doc["file_type"] == ".pdf":
                        message_content.append({"type": "text", "text": "--用户传入的pdf--:\n", "text_file": True})
                        for img in doc["file_content"]["images"]:
                            message_content.append(
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"},
                                 "detail": "auto"})
                    elif doc["file_type"] == ".xlsx":
                        message_content.append({"type": "text", "text": "--用户传入的xlsx--:\n", "text_file": True})
                        message_content.append({"type": "text", "text": doc["file_content"]["text"], "text_file": True})


        session_ids = await self.aget_conversation_ids

        # 会话ID处理：无则新建，有则校验是否存在
        if session_id == "" or session_id is None:
            session_id = str(uuid.uuid4().hex)
        elif session_id not in session_ids:
            # 会话ID不存在，返回错误信息

            yield json.dumps(
                {"type": "error", "error": f"会话ID {session_id} 不存在，请检查后重试"},
                ensure_ascii=False
            ) + "\n\n"
            return

        input_config = {
            "configurable" :{
                "thread_id" : session_id,
            }
        }

        additional_kwargs ={
            "updated_at": datetime.now(),
            "file_list": file_list,
        }

        full_response = ""
        try:
            # todo: 前段要适配返回的响应，让用户可以实时看见ai动态响应
            async for chunk in self.chat_workflow.astream(messages=[HumanMessage(content=message_content,additional_kwargs=additional_kwargs)], config=input_config):
                if chunk['event'] == 'on_chat_model_stream':
                    # 最终返回的chunk
                    if chunk['metadata']['langgraph_node'] and chunk['metadata']['langgraph_node'] == 'final_node':
                        content = chunk['data']['chunk'].content
                        full_response += content
                        yield json.dumps(
                            {"type": "content", "content": content},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
                    elif chunk['metadata']['langgraph_node'] and chunk['metadata']['langgraph_node'] == 'agent_node':
                        content = chunk['data']['chunk'].content
                        yield json.dumps(
                            {"type": "reasoning", "content": content},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
                    else:
                        continue
                elif chunk['event'] == 'on_tool_start':
                    tool_call_args = chunk['data'].get('input',{})
                    tool_call_name = chunk['name']
                    yield json.dumps(
                        {"type": "tool_call_name", "content": {'args': tool_call_args, 'name': tool_call_name}},
                        ensure_ascii=False,
                        default=str
                    ) + "\n\n"
                elif chunk['event'] == 'on_tool_end':
                    if output := chunk['data']['output'].content:
                        for op in output:
                            if op['type'] == "text":
                                tool_call_result = op['text']
                                yield json.dumps(
                                    {"type": "tool_call_result", "content": tool_call_result},
                                    ensure_ascii=False,
                                    default=str
                                ) + "\n\n"

        except Exception as e:
            import traceback
            error_detail = f"{str(e)}\n{traceback.format_exc()}"
            self.logger.error(f"流式响应异常(session_id:{session_id}): {error_detail}")
            # 异常返回错误信息 + 双换行符 + 不执行return，避免生成器强制关闭
            yield json.dumps(
                {"type": "error", "error": str(e)},
                ensure_ascii=False,
                default=str
            ) + "\n\n"
        finally:
            status = await self._save_round_checkpoint(session_id)
            if status:
                self.logger.info("保存检查点成功")
            else:
                self.logger.error("保存检查点失败")

        # 返回最终完整结果
        yield json.dumps({
            "type": "done",
            "full_response": full_response,
            "session_id": session_id
        }) + "\n\n"


    async def get_conversation(self, session_id: str) ->Conversation:
        """
        获取会话内容
        Args:
            session_id: 会话id
        Returns:
            会话内容
        """
        config = {"configurable": {"thread_id": session_id}}

        try:
            state = await self.graph.aget_state(config=config)
            print(state)
        except HTTPException as e:
            self.logger.error(f"获取会话状态异常(session_id:{session_id})：{str(e)}")
            return Conversation(session_id=session_id)

        messages_list = []
        if "messages" in state.values and state.values["messages"]:
            for msg in state.values["messages"]:
                if isinstance(msg, HumanMessage):
                    role = MessageRole.USER
                    human_message = ""
                    files = []
                    files_input = False
                    for content in msg.content:
                        if content.get("type") == "text" and content.get("text_file", False) == False:
                            human_message += content.get("text", "")
                            human_message += '\n'
                        if content.get("type") == "image_url" or content.get("text_file") == True:
                            files_input = True
                        if files_input:
                            files = msg.additional_kwargs.get("files",[])
                            break
                    messages_list.append(Message(
                        role=role,
                        content=human_message,
                        files=files,
                        additional_kwargs=None
                    ))

                elif isinstance(msg, AIMessage):
                    role = MessageRole.AI
                    messages_list.append(Message(
                        role=role,
                        content=msg.content,
                        files=None,
                        additional_kwargs={**msg.additional_kwargs} # 包含了AIMessage信息分类
                    ))# todo 新增checkpoint检查点，存放在前端

                elif isinstance(msg, ToolMessage):
                    role = MessageRole.AI
                    tool_resp = Any
                    for content in msg.content:
                        if content.get("type") == "text":
                            tool_resp = content.get("text",{})
                    messages_list.append(Message(
                        role=role,
                        content=f"name: {msg.name}\ncontent:{tool_resp}",
                        files=None,
                        additional_kwargs={"type": AIMessageType.REASONING.value,"isTool": True} # 与调用工具的AIMessage进行区分
                    ))

        created_at = state.created_at if hasattr(state, "created_at") else datetime.now()
        updated_at = None
        if "messages" in state.values and state.values["messages"]:
            for msg in reversed(state.values["messages"]):
                if isinstance(msg, HumanMessage):
                    updated_at = msg.additional_kwargs.get("updated_at")
                    break

        title = state.values["messages"][1].additional_kwargs.get("title","新对话")  # 读取你之前更新的真实标题

        return Conversation(
            session_id=session_id,
            messages=messages_list,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def get_conversation_list(self, limit: int = 10) -> List[Conversation]:
        """
        获取会话列表，返回最新的N条会话
        :param limit: 返回条数，默认10
        :return: 按更新时间倒序的会话列表，自动过滤空会话
        """
        try:
            session_ids = await self.aget_conversation_ids
            conversation_list = []
            for sid in session_ids:
                conv = await self.get_conversation(sid)
                # 过滤空会话：无消息的会话不展示
                if conv and len(conv.messages) > 0:
                    conversation_list.append(conv)
            # 按更新时间倒序，最新对话在最前面
            conversation_list.sort(key=lambda x: x.updated_at, reverse=True)
            # 只返回前N条
            return conversation_list[:limit]
        except HTTPException as e:
            self.logger.error(f"获取会话列表异常：{str(e)}")
            return []

    async def delete_conversation(self, session_id: str) -> bool:
        """
        langgraph新版本 删除会话 adelete_thread
        彻底删除Redis中的会话数据：包含检查点+历史状态+索引
        """
        try:

            # langgraph新版本 删除会话 adelete_thread
            await self.checkpointer.adelete_thread(
                thread_id=session_id,
            )
            self.logger.info(f"会话删除成功(session_id:{session_id})")
            return True

        # 捕获异常
        except HTTPException as e:
            error_detail = f"删除会话失败(session_id:{session_id})：{str(e)}"
            self.logger.error(error_detail)
            return False

    async def update_conversation_title(self, session_id: str, new_title: str) -> bool:
        """ 修改会话标题，存入会话元数据"""
        try:
            config = {"configurable": {"thread_id": session_id}}
            state = await self.graph.aget_state(config=config)

            # 面对langgraph对更新state的限制所制作的*神秘代码*
            new_msg = None
            if state.values["messages"][1]:
                for msg in state.values["messages"]:
                    if isinstance(msg, AIMessage):
                        msg.additional_kwargs["title"] = new_title.strip()
                        new_msg = AIMessage(
                            content=msg.content,
                            additional_kwargs=msg.additional_kwargs,
                            response_metadata=msg.response_metadata,
                            id=msg.id,
                            usage_metadata = msg.usage_metadata
                        )
                        break

                state.values["messages"][1] = new_msg
                # 调用aupdate_state：只传config和values
                await self.graph.aupdate_state(
                    config=config,
                    values=state.values,  # 把修改后的完整state值更新回去
                )

                self.logger.info(f"会话标题修改成功(session_id:{session_id})：{new_title}")
                return True
            else:
                self.logger.error(f"会话不存在(session_id:{session_id})")
                return False
        except HTTPException as e:
            self.logger.error(f"修改标题失败(session_id:{session_id}): {str(e)}")
            return False

    async def backtrack_state(self, session_id :str, checkpoint_id :str) -> bool:
        """
        返回到当前对话的特定的检查点状态
        :param
            session_id: 会话id
            checkpoint_id: 检查点id
        :return
            已回溯到某个检查点状态的对话信息
        """
        backtrack_config = {"configurable": {"thread_id": session_id, "checkpoint_id":checkpoint_id}}

        try:
            backtrack_state = await self.graph.aget_state(config=backtrack_config)
            await self.graph.aupdate_state(config=backtrack_config, values=backtrack_state.values)

            return True

        except Exception as e:
            self.logger.error(f"会话回溯失败(session_id:{session_id}, checkpoint_id:{checkpoint_id}): {str(e)}")
            return False


    async def get_imp_usr_ipt(self, input_text:str):
        """
        优化用户需求函数，使后续ai更好理解用户需求
        返回两个参数: 优化后的输入,状态码
        """
        improved_text =input_text
        try:
            resp = await self.chat_workflow.llm_imp_ipt.ainvoke(input_text)
            improved_text = resp.content

        except Exception as e:
            self.logger.error(f"优化用户输入失败: {str(e)},采用回原输出")
        finally:
            return improved_text

    async def get_file_config(self):
        return {
            "maxFileSize": FILE_MAX_LENGTH,
            "imageTypes": {
                "suffixes": list(FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_SUFFIX"]),
                "mimeTypes": list(FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_MIME"])
            },
            "textTypes": {
                "suffixes": list(FILE_ALLOWED_TYPES["TEXT"]["TEXT_SUFFIX"]),
                "mimeTypes": list(FILE_ALLOWED_TYPES["TEXT"]["TEXT_MIME"])
            },
            "documentTypes": {
                "suffixes": list(FILE_ALLOWED_TYPES["DOCUMENT"]["DOCUMENT_SUFFIX"]),
                "mimeTypes": list(FILE_ALLOWED_TYPES["DOCUMENT"]["DOCUMENT_MIME"])
            }
        }


