import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator, List

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.prebuilt import ToolNode

from chatMe.ChatWorkflow import ChatStateCore, get_imp_ipt_config, get_agent_node_config, get_graph_final_node_config, \
    AIMessageType, get_history_summary_node_config
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
        self.summary_llm = None
        self.llm_imp_ipt = None

        self.graph = None
        self.checkpointer = None
        self.mcp_client = None
        self.files_cached_dir = None

    async def init_mcps(self):
        core_mcp_config = {
            'url': 'http://127.0.0.1:18080/streamable',
            'transport': 'streamable_http'
        }
        self.mcp_client = MultiServerMCPClient(
            {
                'core_mcp': core_mcp_config
            }
        )

    async def init_llm(self):
        # 最终节点配置
        llm_config, system_prompt = get_graph_final_node_config()

        self.llm_core = ChatOpenAI(**llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt),("human", "{messages}")])
        self.llm_core = prompt | self.llm_core

        # agent_node配置
        agent_node_config ,agent_prompt = get_agent_node_config()

        self.agent_llm = ChatOpenAI(**agent_node_config)
        prompt = ChatPromptTemplate.from_messages([("system", agent_prompt), ("human", "{messages}")])
        self.agent_llm = prompt | self.agent_llm

        # 历史对话总结节点配置
        summary_llm_config, summary_llm_prompt = get_history_summary_node_config()

        self.summary_llm = ChatOpenAI(**summary_llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", summary_llm_prompt), ("human", "{messages}")])
        self.summary_llm = prompt | self.summary_llm

        # 输入优化大模型配置
        imp_ipt_llm_config, imp_ipt_llm_prompt = get_imp_ipt_config()

        self.llm_imp_ipt = ChatOpenAI(**imp_ipt_llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", imp_ipt_llm_prompt), ("human", "{messages}")])
        self.llm_imp_ipt = prompt | self.llm_imp_ipt


    async def ainit(self):
        """
        初始化mcp，初始化redis-stack，初始化llm和配置工作流：
        """
        self.files_cached_dir = str(Path.cwd()) + "/cached"

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
        if matches:
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

    async def _get_validate_history_message(self, history_messages: List[BaseMessage])-> List[BaseMessage]:
        """获取历史有效的聊天消息，包含文件缓存路径"""
        input_msg = []
        files_cached_message = SystemMessage(content=f"文件缓存路径：{self.files_cached_dir}")
        input_msg.append(files_cached_message)
        for msg in history_messages:
            if isinstance(msg, HumanMessage):
                if not msg.additional_kwargs.get("is_file", False):
                    input_msg.append(msg)
            if isinstance(msg, AIMessage):
                if msg.additional_kwargs.get("type") == AIMessageType.SUMMARY.value:
                    input_msg.append(msg)

        return input_msg

    async def _get_current_round_conversation(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
            获取本轮对话

            Args:
                messages: langgraph状态消息

            Return:
                本轮对话消息
        """
        input_msg = []
        for msg in reversed(messages): # 首轮对话也兼容，无之前对话的summary就遍历完
            if isinstance(msg, AIMessage):
                if "type" in msg.additional_kwargs and msg.additional_kwargs.get("type") == AIMessageType.SUMMARY.value:
                    break
            input_msg.append(msg)

        return input_msg

    async def _get_current_round_conversation_except_files(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
            获取本轮对话除了文件传入部分

            Args:
                messages: langgraph状态消息

            Return:
                本轮对话消息除了文件传入部分
        """
        input_msg = []
        for msg in reversed(messages): # 首轮对话也兼容，无之前对话的summary就遍历完
            if isinstance(msg, HumanMessage):
                if "is_file" in msg.additional_kwargs and msg.additional_kwargs.get("is_file"):
                    break
            input_msg.append(msg)

        return input_msg

    async def _create_graph_core(self):
        """
        自定义工作流对象，可以调用工具实现agent-skills获取
        """

        tools = await self.mcp_client.get_tools()

        agent_node_llm = self.agent_llm.bind(tools=tools)

        workflow = StateGraph(ChatStateCore)

        async def history_summary_node(state: ChatStateCore):
            """历史消息节点，处理用户消息并返回历史消息"""
            messages = state["messages"]

            if not messages or len(messages) < 2:
                return {
                    "history_messages": None,
                    "summary_or_not": False,
                    "has_file_or_not_cur": False,
                    "tool_call_times": 0,
                }
            last_message = messages[-1]
            second_last_message = messages[-2]
            has_file = (
                isinstance(last_message, HumanMessage) and
                not last_message.additional_kwargs.get("is_file", False) and
                isinstance(second_last_message, HumanMessage) and
                second_last_message.additional_kwargs.get("is_file", False)
            )

            if has_file:
                history_messages = messages[:-2]
                input_msg = await self._get_validate_history_message(history_messages)
            else:
                history_messages = messages[:-1]
                input_msg = await self._get_validate_history_message(history_messages)

            if len(input_msg) > 20:
                summary_or_not = True

                # 添加当轮对话用户消息，更好针对性总结历史对话
                history_messages.append(state["messages"][-1])
                history_summary = await self.summary_llm.ainvoke({"messages": input_msg})
            else:
                summary_or_not = False

                history_summary = None

            return {
                "history_summary": history_summary,
                "summary_or_not": summary_or_not,
                "has_file_or_not_cur": has_file,
                "tool_call_times": 0,
            }

        async def agent_node(state: ChatStateCore):
            """AI 代理节点，处理用户消息并决定是否调用工具"""
            messages = list(state["messages"])
            # todo 现在的提示词优化导致每次一段对话如果要使用工具都要调用一次overview，长对话可能还好，但是短对话可能就不太好了
            tool_call_times = state["tool_call_times"] if "tool_call_times" in state else 0
            has_file = state["has_file_or_not_cur"]
            current_msg = await self._get_current_round_conversation(state["messages"])

            if not state["summary_or_not"]:
                if has_file:
                    history_messages = messages[:-2]
                    input_msg = await self._get_validate_history_message(history_messages)
                    # 有文件的话要确保文件只识别一次
                    if tool_call_times < 1:
                        input_msg.extend(current_msg)
                    else:
                        input_msg.extend(await self._get_current_round_conversation_except_files(state["messages"]))
                else:
                    history_messages = await self._get_validate_history_message( messages)
                    input_msg = await self._get_validate_history_message(history_messages)
                    input_msg.extend(current_msg)
            else:
                input_msg = []
                history_messages = await self._get_validate_history_message( messages)
                input_msg.extend(history_messages)
                if has_file:
                    if tool_call_times < 1:
                        input_msg.extend(current_msg)
                    else:
                        input_msg.extend(await self._get_current_round_conversation_except_files(state["messages"]))
                else:
                    input_msg.extend(current_msg)

            if tool_call_times >= 20:
                interrupt_message = SystemMessage(content=f"当前工具调用次数过多，请整理好存在信息，合理结束本节点对话(响应中提示工具调用提前结束)")
                input_msg.append(interrupt_message)

            response = await agent_node_llm.ainvoke({"messages": input_msg})
            tool_call_times += 1

            # 符合ToolNode节点的AIMessage(REASONING)
            format_response = self._parse_content_to_tool_calls(response)

            return {
                "messages": [format_response],
                "tool_call_times": tool_call_times,
            }

        tool_execution_node = ToolNode(tools=tools)  # 使用langgraph官方工具节点

        async def final_node(state: ChatStateCore):
            # input_msg = list(state["messages"])
            messages = list(state["messages"])

            if state["has_file_or_not_cur"]:
                input_msg = await self._get_current_round_conversation_except_files(messages)
            else:
                input_msg = await self._get_current_round_conversation(messages)

            response = await self.llm_core.ainvoke({"messages": input_msg})
            # AIMessage字段支持解包复制
            response_dict = dict(response)
            response_dict["additional_kwargs"] = {**response.additional_kwargs, "type": AIMessageType.SUMMARY.value}

            response_better = AIMessage(**response_dict)

            return {
                "messages": [response_better]
            }

        workflow.add_node("history_summary_node", history_summary_node)
        workflow.add_node("agent_node", agent_node)
        workflow.add_node("tool_execution_node", tool_execution_node)
        workflow.add_node("final_node", final_node)

        def route_agent_output(state: ChatStateCore) -> str:
            """根据代理输出决定下一步"""
            last_message = state["messages"][-1]
            if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls") and last_message.tool_calls and state["tool_call_times"]<=20:
                return "tool_execution_node"
            return "final_node"

        workflow.set_entry_point("history_summary_node")
        workflow.add_edge("history_summary_node", "agent_node")

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
