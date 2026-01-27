import base64
import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator, Set, List, Optional

from fastapi import UploadFile
from langchain_core.messages import HumanMessage, AIMessage
from langgraph_sdk.auth.exceptions import HTTPException
from redisvl.query import FilterQuery
from langgraph.checkpoint.redis.util import from_storage_safe_id

from . import FILE_ALLOWED_TYPES, FILE_MAX_LENGTH
from .models import MessageRole, Message, Conversation
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
        # 构造Redis Search查询：匹配所有checkpoint，只返回thread_id字段，极致精简
        query = FilterQuery(
            filter_expression="*",  # 匹配所有检查点数据
            return_fields=["thread_id"],  # 只查询thread_id字段，不查任何冗余数据
            num_results=10000,  # 可调整，足够容纳你的所有会话数（比如1万）
            sort_by=None,  # 关闭排序，避免触发排序缺陷
        )
        # 异步执行查询，直接从Redis索引获取数据
        search_results = await self.checkpointer.checkpoints_index.search(query)

        # 去重+还原原始thread_id：从Redis存储的safe_id转回真实的thread_id
        thread_ids: Set[str] = set()
        for doc in search_results.docs:
            # doc.thread_id 是Redis里存储的加密safe_id
            safe_thread_id = doc.thread_id
            # 还原为原始thread_id
            raw_thread_id = from_storage_safe_id(safe_thread_id)
            thread_ids.add(raw_thread_id)

        return sorted(list(thread_ids))

    async def _get_file_suffix(self, filename: Optional[str]) -> str:
        """
        提取文件后缀，处理边界情况：
        1. 无后缀（如"readme"）返回空字符串
        2. 多后缀（如"file.tar.gz"）返回最后一个后缀（.gz）
        3. 后缀转小写（如".PNG"→".png"）
        """
        if not filename or "." not in filename:
            return ""
        return "." + filename.split(".")[-1].lower()

    async def _distinguish_files(self, files: List[UploadFile]):
        """
        划分文件类型
        :param files:
        :return: images, texts (图片类型， 文本类型) | None,None
        """
        if not files:
            logging.warning("未传入任何图片文件，返回空二进制数据")
            return None,None

        images_type = FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_SUFFIX"]
        texts_type = FILE_ALLOWED_TYPES["TEXT"]["TEXT_SUFFIX"]
        images, texts = [], []
        for file in files:
            file_name = file.filename or "不支持文件或位置文件"
            file_suffix = await self._get_file_suffix(file_name)
            if file_suffix in images_type:
                images.append(file)
            elif file_suffix in texts_type:
                texts.append(file)
            else:
                # 宽松处理，防止影响后续文件处理
                logging.warning(f"忽略不支持的文件类型：{file_name}")
                await file.close()  # 单独关闭非法文件，释放资源
                continue  # 跳过当前文件，处理下一个

        # 后续还要进行文件操作，不要关闭文件
        return images, texts

    async def _process_files_img(self, files: List[UploadFile])-> Optional[List[str]]:
        """
        处理传入图片类型文件信息，类型为png，jpg等常见图片类型
        :param files:
        :return:
        """
        # 将多个图片文件处理进入同一份二进制数据
        images_list: Optional[List[str]] = []
        if not files:
            logging.warning("未传入任何图片文件，返回空二进制数据")
            return None

        for img in files:
            image_byte = await img.read()
            if not image_byte: # 过滤为空图片
                logging.warning(f"图片文件{img.filename}为空，跳过")
                await img.close()
                continue

            # 拼接URL时，bytes与str无法直接拼接
            images_list.append(base64.b64encode(image_byte).decode("utf-8"))
            await img.close() # 读取完毕再关文件
            logging.info(f"成功读取图片{img.filename}，大小：{img.size/1024:.2f}KB")


        return images_list

    async def _process_files_text(self, files: List[UploadFile])-> Optional[List[str]]:
        """
        使用langchain的document_loader组件处理传入文件信息，类型为txt，md等常见文本类型
        :param files:
        :return:
        """
        # todo: 使用langchain的document_loader组件处理传入文件信息
        pass

    async def _process_files(self, files: List[UploadFile]):
        """
        处理传入文件信息，返回处理好的二进制文件内容
        :param files:
        :return: images_content（含图片信息列表）, text_content（含文本信息列表）
        """
        Images, Texts = await self._distinguish_files(files)

        images_content :Optional[List[str]] = await self._process_files_img(Images)
        text_content :Optional[List[str]] = await self._process_files_text(Texts)

        return images_content, text_content


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

        images_content, text_content = await self._process_files(files)

        message_content = [
            {"type": "text", "text": message},
        ]
        if text_content or images_content:
            if images_content:
                for img in images_content:
                    message_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}, "detail": "auto"})
            if text_content:
                message_content.append({"type": "text", "text": f"用户传入文本:\n{text_content}"})

        session_ids = await self.aget_conversation_ids

        # 会话ID处理：无则新建，有则校验是否存在
        if session_id == "":
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

        full_response = ""
        try:
            async for chunk in self.chat_workflow.astream(messages=[HumanMessage(content=message_content)], config=input_config):
                if chunk['event'] == 'on_chat_model_stream':
                    content = chunk['data']['chunk'].content
                    full_response += content
                    yield json.dumps(
                        {"type": "content", "content": content},
                        ensure_ascii=False,
                        default=str
                    ) + "\n\n"

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
            "full_response": full_response
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
        except HTTPException as e:
            logging.error(f"获取会话状态异常(session_id:{session_id})：{str(e)}")
            return Conversation(session_id=session_id)


        messages_list = []
        if "messages" in state.values and state.values["messages"]:
            for msg in state.values["messages"]:
                    if isinstance(msg, HumanMessage):
                        role = MessageRole.USER
                        if isinstance(msg.content, str):
                            messages_list.append(Message(
                                role=role,
                                content=msg.content  # 获取用户输入的文本
                            ))
                        else:
                            human_message = ""
                            for content in msg.content:
                                if content.get("type") == "text":
                                    human_message += content.get("text", "")
                                    human_message += '\n'
                                    messages_list.append(Message(
                                        role=role,
                                        content=human_message
                                    ))


                    elif isinstance(msg, AIMessage):
                        role = MessageRole.AI
                        messages_list.append(Message(
                            role=role,
                            content=msg.content
                        ))



        created_at = state.created_at if hasattr(state, "created_at") else datetime.now()

        # todo: state状态里面又created但是没有updated导致每次get_conversation的时候使得updated自动更新，明明也是没有更新
        updated_at = state.updated_at if hasattr(state, "updated_at") else datetime.now()
        title = state.values["messages"][1].additional_kwargs.get("title","新对话")  # 读取你之前更新的真实标题

        return Conversation(
            session_id=session_id,
            messages=messages_list,
            title=title,
            created_at=created_at ,
            updated_at=updated_at,
            is_clicked=True # 前端点击进入对话后置为true，然后点击进入别的对话就将当前对话改为false
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
                        new_msg = AIMessage(
                            content=msg.content,
                            additional_kwargs={"title": new_title.strip()},
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




