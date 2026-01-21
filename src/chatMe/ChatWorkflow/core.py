from typing import Optional, Dict, Any, AsyncGenerator

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver
# from langchain_community.storage.redis import RedisStore
# from langgraph.checkpoint.memory import InMemorySaver

from chatMe.ChatWorkflow import get_graph_config, ChatState


class ChatWorkflow:
    """
    ChatMe工作流对象：
    实现自定义langgraph工作流
    """

    def __init__(self):
        self.llm = None
        self.graph = None
        self.checkpointer = None

    async def ainit(self):
        """
        初始化llm和配置工作流：
        1.ChatOpenAI+prompt+格式化输出（有必要的话)    langchain链式结构
        2._create_graph()自定义工作流创建workflow对象     langgraph图工作流
        """

        # 短期存储(redis)
        redis_url_checkpoint = "redis://:123456@localhost:6388/0"
        self.checkpointer = AsyncRedisSaver(redis_url=redis_url_checkpoint)
        await self.checkpointer.setup()

        llm_config, system_prompt = get_graph_config()

        # 大模型基础配置
        self.llm = ChatOpenAI(**llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt),("placeholder", "{messages}")])
        self.llm = prompt | self.llm

        self.graph = self._create_graph()


    def _create_graph(self):
        """
        自定义工作流对象
        """

        # 创建流对象
        workflow = StateGraph(ChatState)

        # ========== 同步节点：适配 invoke 同步调用 ==========
        def chat_node(state: ChatState, config:  RunnableConfig | None) -> ChatState:
            """ LLM 同步处理 """
            messages = state["messages"]
            response = self.llm.invoke({"messages": messages})
            return {"messages": [response], }

        # ========== 异步节点：适配 ainvoke/astream 异步调用 ==========
        async def achat_node(state: ChatState, config:  RunnableConfig | None) :
            """ LLM 异步流式处理 """
            messages = state["messages"]
            response = await self.llm.ainvoke({"messages": messages})
            return {
                "messages": [response]
            }


        # 添加节点
        workflow.add_node("achat_node", achat_node)
        # workflow.add_node("chat_node", chat_node)

        # 添加入口节点点, 手动调整异步入口还是同步入口
        workflow.set_entry_point("achat_node")
        # workflow.set_entry_point("chat_node")

        # 添加节点边
        workflow.add_edge("achat_node", END)
        # workflow.add_edge("chat_node", END)

        # # 长期存储 官方无异步适配-舍弃 如果需要则自己开发相应功能
        # redis_url_store = "redis://localhost:6379/8"
        # store = RedisStore(redis_url=redis_url_store)

        # 编译图工作流
        return workflow.compile(checkpointer=self.checkpointer)

    def invoke(self, messages: list[BaseMessage], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute the workflow synchronously

        Args:
            messages: List of messages
            config: Optional configuration

        Returns:
            Workflow execution result
        """
        result = self.graph.invoke({"messages": messages}, config=config)
        return result

    async def ainvoke(self, messages: list[BaseMessage], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute the workflow asynchronously

        Args:
            messages: List of messages
            config: Optional configuration

        Returns:
            Workflow execution result
        """
        result = await self.graph.ainvoke({"messages": messages}, config=config)
        return result

    async def astream(self, messages: list[BaseMessage], config: Optional[Dict[str, Any]] = None) -> AsyncGenerator[Any, None]:
        """
        Stream workflow execution

        Args:
            messages: List of messages
            config: Optional configuration

        Yields:
            Workflow execution chunks
        """
        async for e in self.graph.astream_events({
            "messages": messages},
            config=config
        ):
                yield e

