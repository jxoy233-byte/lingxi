import logging
from http.client import HTTPException
from typing import Optional, Dict, Any, AsyncGenerator

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver
from pyexpat.errors import messages

from chatMe.ChatWorkflow import get_graph_config, ChatState, get_judge_search_node_config, SearchDecision, ChatState3


class ChatWorkflow:
    """
    ChatMe工作流对象：
    实现自定义langgraph工作流
    """

    def __init__(self):
        self.llm = None
        self.graph = None
        self.checkpointer = None
        self.tavily_search = TavilySearch(
            tavily_api_key="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",
            max_results = 5,
        )

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

    async def _create_graph3(self):
        """
        自定义工作流对象，带有搜索引擎
        """
        workflow = StateGraph(ChatState3)

        async def judge_search_node(state: ChatState3):
            total_messages: str = ""
            for msg in state["messages"]:
                print(msg)
                if isinstance(msg, HumanMessage):
                    for content in msg.content:
                        if content.get("type") == "text":
                            total_messages += ("Human: " + content.get("text"))
                if isinstance(msg, AIMessage):
                    total_messages += ("AI: " + msg.content)

            judge_llm_config, judge_search_prompt = get_judge_search_node_config()

            judge_llm = ChatOpenAI(**judge_llm_config)

            judge_llm = judge_search_prompt | judge_llm.with_structured_output(SearchDecision)

            judge_decision = await judge_llm.ainvoke({"messages": total_messages})

            return {
                "search_decision": judge_decision
            }

        async def search_node(state: ChatState3):
            should_search = state["search_decision"].should_search
            query = state["search_decision"].query
            messages = list(state["messages"])

            search_message = ""
            try:
                if should_search:
                    search_results = await self.tavily_search.ainvoke(query)
                    print(search_results)
                    results = search_results.get("results", [])
                    for result in results:
                        search_message += (result + '\n')
            except HTTPException as e:
                logging.error(f"搜索引擎搜索失败：{e}")
                search_message = "搜索服务暂时不可用，请稍后再试。"

            messages.append(
                SystemMessage(
                    content=f"以下是搜索结果：\n{search_message}"
                )
            )

            return {
                "messages": messages
            }

        async def final_node(state: ChatState3):
            input_msg = list(state["messages"])
            response = await self.llm.ainvoke({"messages": input_msg})

            return {
                "messages": [response]
            }

        workflow.add_node("judge_search_node", judge_search_node)
        workflow.add_node("search_node", search_node)
        workflow.add_node("final_node", final_node)

        def route_decision(state: ChatState3) -> str:
            """根据 search_judge 决定下一步路径"""
            search_or_not = state["search_decision"].should_search
            if search_or_not:
                return "search_node"
            else:
                return "final_node"

        workflow.add_conditional_edges(
            "judge_search_node",
            route_decision,
            {
                "search_node": "search_node",
                "final_node": "final_node"
            }
        )
        workflow.add_edge("search_node", "final_node")
        workflow.set_entry_point("judge_search_node")
        workflow.add_edge("final_node",END)

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
