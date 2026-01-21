import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator, Set, List

from langchain_core.messages import HumanMessage, AIMessage
from langgraph_sdk.auth.exceptions import HTTPException
from redisvl.query import FilterQuery
from langgraph.checkpoint.redis.util import from_storage_safe_id

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


    async def message_stream(
        self,
        message: str,
        session_id: str = None
    ) -> AsyncGenerator[str, None]:
        """
        流式响应用户信息

        Args:
            message: 用户信息
            session_id: 会话id

        Yields:
            基于流式传输的 JSON 字符串
        """

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
            async for chunk in self.chat_workflow.astream(messages=[HumanMessage(content=message)], config=input_config):
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
                    elif isinstance(msg, AIMessage):
                        role = MessageRole.AI

                    messages_list.append(Message(
                        role=role,
                        content=msg.content
                    ))

        created_at = state.created_at if hasattr(state, "created_at") else datetime.now()
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




