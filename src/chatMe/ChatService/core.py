import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator, Set, List, Dict

from fastapi import UploadFile
from langchain_core.messages import HumanMessage, AIMessage
from langgraph_sdk.auth.exceptions import HTTPException
from redisvl.query import FilterQuery
from langgraph.checkpoint.redis.util import from_storage_safe_id

from chatMe.ChatService.config.models import MessageRole, Message, Conversation
from .FilesLoaders.core import FilesLoaders
from ..ChatWorkflow import ChatWorkflow


class ChatService:
    """
    ChatMe服务对象：
    实现自定义langgraph服务
    """

    def __init__(self, workflow: ChatWorkflow):
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
                logging.info("Redis搜索结果为空（search_results为None）")
                return []

            # 风险点2：确保docs是可遍历的列表
            docs = getattr(search_results, "docs", [])
            if not isinstance(docs, list):
                logging.warning(f"Redis搜索结果docs格式异常，非列表类型：{type(docs)}")
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
                    logging.warning(f"转换safe_id失败：{safe_thread_id}，错误：{e}")
                    continue

            # 排序并返回（空集合会返回空列表）
            return sorted(list(thread_ids))

        # 风险点5：捕获所有异常，而非仅HTTPException
        except HTTPException as e:
            logging.warning(f"Redis查询触发HTTP异常（无历史数据）：{e}")
            return []
        except Exception as e:
            # 兜底捕获所有其他异常（如连接错误、序列化错误等）
            logging.warning(f"获取conversation_ids失败：{type(e).__name__}: {e}")
            return []

    async def _process_files(self, files: List[UploadFile]):
        """
        创建FilesLoaders类实例,调用loading_files防擦，处理传入文件信息，返回处理好的分类文件内容
        :param files:
        :return: images_content（含图片信息列表）, text_content（含文本信息列表）, doc_content(文档信息列表), 额外参数files_list
        """

        fl = FilesLoaders(files)
        images_content, text_content, doc_content = await fl.loading_files()
        files_list = await fl.create_files_additional_kwargs()

        await fl.cleanup()

        return images_content, text_content, doc_content, files_list

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

        images_content, text_content, files_list = await self._process_files(files)

        message_content = [
            {"type": "text", "text": message, "text_file": False},
        ]
        if text_content or images_content:
            if images_content:
                for img in images_content:
                    message_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img["file_content"]}"}, "detail": "auto"})
            if text_content:
                message_content.append({"type": "text", "text": "以下为传入用户文件\n:", "text_file": True})
                for text in text_content:
                    message_content.append({"type": "text", "text": text["file_content"], "text_file": True})

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
                "thread_id" : session_id
            }
        }

        additional_kwargs ={
            "updated_at": datetime.now(),
            "files": files_list, # 列表字典
        }

        full_response = ""
        try:
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
                    else:
                        continue
                elif chunk['event'] == 'on_tool_end':
                    if 'output' in chunk['data']:
                        if search_results := chunk['data']['output'].get('results',[]):
                            yield json.dumps(
                                {"type": "search_result", "content": search_results},
                                ensure_ascii=False,
                                default=str
                            ) + "\n\n"
                        else:
                            continue
        except HTTPException as e:
            import traceback
            error_detail = f"{str(e)}\n{traceback.format_exc()}"
            logging.error(f"流式响应异常(session_id:{session_id}): {error_detail}")
            # 异常返回错误信息 + 双换行符 + 不执行return，避免生成器强制关闭
            yield json.dumps(
                {"type": "error", "error": str(e)},
                ensure_ascii=False,
                default=str
            ) + "\n\n"

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
            print( state)
        except HTTPException as e:
            logging.error(f"获取会话状态异常(session_id:{session_id})：{str(e)}")
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
                        if content.get("type") == "text":
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
                        search_results=None
                    ))

                elif isinstance(msg, AIMessage):
                    role = MessageRole.AI
                    messages_list.append(Message(
                        role=role,
                        content=msg.content,
                        files=None,
                        search_results=msg.additional_kwargs.get("search_results",[])
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
            logging.info(f"会话删除成功(session_id:{session_id})")
            return True

        # 捕获异常
        except HTTPException as e:
            error_detail = f"删除会话失败(session_id:{session_id})：{str(e)}"
            logging.error(error_detail)
            return False

    async def update_conversation_title(self, session_id: str, new_title: str) -> bool:
        """ 修改会话标题，存入会话元数据"""
        try:
            config = {"configurable": {"thread_id": session_id}}
            state = await self.graph.aget_state(config=config)

            # 由于langgraph对更新state的限制和BaseMessage修改的要求做出的***史山代码***
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

                logging.info(f"会话标题修改成功(session_id:{session_id})：{new_title}")
                return True
            else:
                logging.error(f"会话不存在(session_id:{session_id})")
                return False
        except HTTPException as e:
            logging.error(f"修改标题失败(session_id:{session_id}): {str(e)}")
            return False

    async def backtrack_state(self, session_id :str, checkpoint_id :str) -> bool:
        """
        返回到当前对话的特定的检查点状态
        :param round_id:
        :return: 是否回溯成功
        """
        pass




