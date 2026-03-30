import json
import re
from typing import Optional, Dict, Any, AsyncGenerator

from langchain_core.messages import BaseMessage, AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.prebuilt import ToolNode

from chatMe.ChatWorkflow import ChatStateCore, get_imp_ipt_config, get_agent_node_config, get_graph_final_node_config, AIMessageType
from chatMe.logging_config import get_logger


class ChatWorkflow:
    """
    ChatMe工作流对象：
    实现自定义langgraph工作流
    """

    def __init__(self):
        self.logger = get_logger(__class__.__name__)
        self.llm_core = None
        self.agent_llm = None
        self.llm_imp_ipt = None
        self.judge_llm = None
        self.graph = None
        self.checkpointer = None
        self.mcp_client = None

    async def init_mcps(self):
        agent_reach_mcp_config = {
            'url': 'http://127.0.0.1:18080/streamable',
            'transport': 'streamable_http'
        }
        self.mcp_client = MultiServerMCPClient(
            {
                'agent_reach_mcp': agent_reach_mcp_config
            }
        )

    async def init_llm(self):
        # 核心大模型配置
        llm_config, system_prompt = get_graph_final_node_config()

        self.llm_core = ChatOpenAI(**llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt),("placeholder", "{messages}")])
        self.llm_core = prompt | self.llm_core

        # 工具执行前节点agent_node配置
        agent_node_config ,agent_prompt = get_agent_node_config()

        self.agent_llm = ChatOpenAI(**agent_node_config)
        prompt = ChatPromptTemplate.from_messages([("system", agent_prompt), ("human", "{messages}")])
        self.agent_llm = prompt | self.agent_llm

        # 输入优化大模型配置
        imp_ipt_llm_config, imp_ipt_llm_prompt = get_imp_ipt_config()

        self.llm_imp_ipt = ChatOpenAI(**imp_ipt_llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", imp_ipt_llm_prompt), ("human", "{messages}")])
        self.llm_imp_ipt = prompt | self.llm_imp_ipt


    async def ainit(self):
        """
        初始化mcp，初始化redis-stack，初始化llm和配置工作流：
        """

        await self.init_mcps()

        # 短期存储(redis)
        redis_url_checkpoint = "redis://:123456@localhost:6379/0"
        self.checkpointer = AsyncRedisSaver(redis_url=redis_url_checkpoint)
        await self.checkpointer.setup()

        # 初始化所有llm
        await self.init_llm()

        self.graph = await self._create_graph_core()

    def _parse_content_to_tool_calls(self, ai_message: AIMessage):
        """
        从 AIMessage 的 content 中提取 tool_calls 并填充到 tool_calls 字段
        某些模型（如 Grok）将 tool_calls 以 JSON 字符串形式放在 content 中，
        需要手动解析并转换为标准格式
        """
        if not ai_message.content:
            return ai_message

        content = str(ai_message.content)

        tool_call_pattern = r'<tool_calls>\s*(\{.*?\})\s*</tool_calls>'
        matches = re.findall(tool_call_pattern,content,re.DOTALL)
        if not matches:
            return ai_message
        tool_calls = []
        for i, match in enumerate(matches):
            try:
                tool_call_data = json.loads(match)
                tool_call = {
                    "name": tool_call_data.get("name"),
                    "args": tool_call_data.get("args",{}),
                    "id": tool_call_data.get("id", "") or f"call_{i+1}",
                    "type": "tool_call"
                }
                if tool_call["name"]:
                    tool_calls.append(tool_call)
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON 解析错误: {e}")
                continue

        if tool_calls:
            ai_message.tool_calls = tool_calls
            # 清理 content 中的工具调用标记
            clean_content = re.sub(r'\n*<tool_calls>.*?</tool_calls>\n*', '', content, flags=re.DOTALL).strip()
            ai_message.content = clean_content if clean_content else ""

        ai_message.additional_kwargs = {"type": AIMessageType.REASONING.value}
        return ai_message

    async def _create_graph_core(self):
        """
        自定义工作流对象，可以调用工具实现agent-skills获取
        """

        tools = await self.mcp_client.get_tools()

        agent_node_llm = self.agent_llm.bind(tools=tools)

        workflow = StateGraph(ChatStateCore)

        async def agent_node(state: ChatStateCore):
            """AI 代理节点，处理用户消息并决定是否调用工具"""
            input_msg = list(state["messages"])
            response = await agent_node_llm.ainvoke({"messages": input_msg})

            # 符合ToolNode节点的AIMessage(REASONING)
            format_response = self._parse_content_to_tool_calls(response)

            return {
                "messages": [format_response]
            }


        tool_execution_node = ToolNode(tools=tools)  # 使用langgraph官方工具节点

        async def final_node(state: ChatStateCore):
            input_msg = list(state["messages"])
            response = await self.llm_core.ainvoke({"messages": input_msg})
            # AIMessage字段支持解包复制
            response_dict = dict(response)
            response_dict["additional_kwargs"] = {**response.additional_kwargs, "type": AIMessageType.SUMMARY.value}

            response_better = AIMessage(**response_dict)

            return {
                "messages": [response_better]
            }

        workflow.add_node("agent_node", agent_node)
        workflow.add_node("tool_execution_node", tool_execution_node)
        workflow.add_node("final_node", final_node)

        def route_agent_output(state: ChatStateCore) -> str:
            """根据代理输出决定下一步"""
            last_message = state["messages"][-1]
            if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tool_execution_node"
            return "final_node"

        workflow.set_entry_point("agent_node")

        workflow.add_conditional_edges("agent_node",
            route_agent_output,
            {
                "tool_execution_node": "tool_execution_node",
                "final_node": "final_node"
            }
        )
        workflow.add_edge("tool_execution_node", "agent_node")
        workflow.add_edge("final_node", END)

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
