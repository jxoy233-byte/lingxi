import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator, List

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.prebuilt import ToolNode
from langgraph.types import Send, interrupt

from .config.graph_config import get_agent_node_config, get_graph_final_node_config, \
    get_imp_ipt_config, get_history_summary_node_config, get_llm_memory_config, get_model_vl_config
from .config.models import ChatStateCore2, AIMessageType, FileParseState
from .Memory.core import MemoryManager
from ..LoggingManager.logging_config import get_logger


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
        self.llm_imp_ipt_vl = None

        self.graph = None
        self.graph_process_files = None
        self.checkpointer = None
        self.redis_client = None
        self.mcp_client = None
        self.memory_manager = None
        self.files_cached_dir = None

    async def init_mcps(self):
        try:
            from ChatMe.ChatMeConfig import get_mcp_config
            mcp_config = get_mcp_config()
            core_mcp_config = {
                'url': mcp_config.get('url', 'http://127.0.0.1:18080/streamable'),
                'transport': mcp_config.get('transport', 'streamable_http')
            }
        except Exception:
            core_mcp_config = {
                'url': 'http://127.0.0.1:18080/streamable',
                'transport': 'streamable_http'
            }

        self.mcp_client = MultiServerMCPClient(
            {
                'core_mcp': core_mcp_config
            }
        )

    async def init_memory_manager(self):
        llm_memory_config, llm_memory_prompt = get_llm_memory_config()

        self.memory_manager = MemoryManager(llm_config=llm_memory_config, memory_prompt=llm_memory_prompt)

    async def init_llms(self):
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

        # 输入优化视觉模型配置
        imp_ipt_vl_llm_config, imp_ipt_vl_llm_prompt = get_model_vl_config()
        # local=true 时使用本地 VL 模型，否则使用外部 VL 模型
        # 从配置中分离 local 标志，ChatOpenAI 不接受该参数
        vl_local = imp_ipt_vl_llm_config.pop("local", None)
        self.llm_imp_ipt_vl = ChatOpenAI(**imp_ipt_vl_llm_config)
        # prompt = ChatPromptTemplate.from_messages([("system", imp_ipt_vl_llm_prompt), ("human", "{messages}")])
        # self.llm_imp_ipt_vl = prompt | self.llm_imp_ipt_vl

    async def ainit(self):
        """
        初始化mcp，初始化redis-stack，初始化llm和配置工作流：
        """
        self.files_cached_dir = str(Path.cwd()) + "/cached"

        await self.init_mcps()

        await self.init_memory_manager()

        # 短期存储(redis)
        try:
            from ChatMe.ChatMeConfig import get_redis_checkpointer_url
            redis_url_checkpoint = get_redis_checkpointer_url()
        except Exception as e:
            self.logger.error(f"初始化Redis Checkpointer失败: {e}")
            raise e

        self.checkpointer = AsyncRedisSaver(redis_url=redis_url_checkpoint)
        await self.checkpointer.setup()
        self.redis_client = self.checkpointer._redis

        # 初始化所有llm
        await self.init_llms()

        # self.graph = await self._create_graph_core()
        self.graph = await self._create_graph_core2()
        self.graph_process_files = await self._create_graph_process_files()

    def _get_message_content_string(self, message: BaseMessage) -> str:
        """提取消息内容为字符串"""
        content_string = ""

        if not message:
            return content_string

        message_content = message.content

        if isinstance(message_content, str):
            content_string = message_content
        elif isinstance(message_content, list):
            for item in message_content:
                if isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "text":
                        content_string += item.get("text", "")
                elif isinstance(item, str):
                    content_string += item + "\n"
        elif isinstance(message_content, dict):
            msg_type = message_content.get("type")
            if msg_type == "text":
                content_string = message_content.get("text", "")
            elif msg_type == "tool":
                content_string = message_content.get("content", "")

        return content_string


    def _parse_content_to_tool_calls(self, ai_message: AIMessage):
        """
        从 AIMessage 的 content 中提取 tool_calls 并填充到 tool_calls 字段
        某些模型（如 Grok）将 tool_calls 以 JSON 字符串形式放在 content 中，
        需要手动解析并转换为标准格式
        """
        if not ai_message.content:
            return ai_message

        content = str(ai_message.content)
        tool_calls = []

        # 找到所有 <tool_calls>...</tool_calls> 块
        tag_pattern = r'<tool_calls>'
        end_tag = '</tool_calls>'
        start_idx = 0

        while True:
            tag_start = content.find(tag_pattern, start_idx)
            if tag_start == -1:
                break

            # 找到 <tool_calls> 后的第一个 { 或 [
            json_start = tag_start + len(tag_pattern)
            while json_start < len(content) and content[json_start] in ' \t\n\r':
                json_start += 1

            if json_start >= len(content) or content[json_start] not in '{[':
                start_idx = json_start + 1
                continue

            # 尝试逐步扩展 JSON 范围来解析（处理嵌套结构）
            bracket_count = 0
            json_end = json_start
            json_chars = []

            for idx in range(json_start, len(content)):
                ch = content[idx]
                json_chars.append(ch)

                if ch in '{[':
                    bracket_count += 1
                elif ch in '}]':
                    bracket_count -= 1
                    if bracket_count == 0:
                        json_end = idx + 1
                        json_str = ''.join(json_chars)
                        try:
                            tool_call_data = json.loads(json_str)
                            if isinstance(tool_call_data, list):
                                for j, item in enumerate(tool_call_data):
                                    tc = {
                                        "name": item.get("name"),
                                        "args": item.get("args", {}),
                                        "id": item.get("id", "") or f"call_{len(tool_calls)+j+1}",
                                    }
                                    if tc["name"]:
                                        tool_calls.append(tc)
                            else:
                                tc = {
                                    "name": tool_call_data.get("name"),
                                    "args": tool_call_data.get("args", {}),
                                    "id": tool_call_data.get("id", "") or f"call_{len(tool_calls)+1}",
                                }
                                if tc["name"]:
                                    tool_calls.append(tc)
                        except json.JSONDecodeError as e:
                            self.logger.error(f"解析工具调用JSON失败: {e}")

                        start_idx = json_end
                        break
            else:
                # 没找到匹配的结束括号
                start_idx = json_start + 1

        if tool_calls:
            ai_message.tool_calls = tool_calls
            # 清理 content 中的工具调用标记
            clean_content = re.sub(r'\n*<tool_calls>.*?</tool_calls>\n*', '', content, flags=re.DOTALL).strip()
            ai_message.content = clean_content if clean_content else ""

        ai_message.additional_kwargs = {"type": AIMessageType.REASONING.value}
        return ai_message

    async def _get_validate_history_message(self, history_messages: List[BaseMessage])-> List[BaseMessage]:
        """获取历史有效的聊天消息，包含文件缓存路径

        注意：只返回上一轮及更早的历史消息，不包含当前轮的 HumanMessage。
        通过排除 messages 列表末尾的 HumanMessage（当前轮输入）来实现。
        """
        input_msg = []
        if not history_messages:
            return input_msg

        files_cached_message = SystemMessage(content=f"文件缓存路径：{self.files_cached_dir}")
        input_msg.append(files_cached_message)

        # 排除当前轮的非文件用户输入 HumanMessage（位于 messages 末尾）
        msgs_to_process = history_messages
        last_msg = history_messages[-1]
        if isinstance(last_msg, HumanMessage) and not last_msg.additional_kwargs.get("is_file", False):
            msgs_to_process = history_messages[:-1]

        for msg in msgs_to_process:
            if isinstance(msg, HumanMessage):
                if not msg.additional_kwargs.get("is_file", False):
                    input_msg.append(msg)
            elif isinstance(msg, AIMessage):
                if msg.additional_kwargs.get("type") == AIMessageType.SUMMARY.value:
                    input_msg.append(msg)

        return input_msg

    async def _get_current_round_conversation(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
            获取本轮对话

            Args:
                messages: langgraph状态消息

            Return:
                本轮对话消息（按原始顺序）
        """
        input_msg = []
        for msg in reversed(messages):  # 首轮对话也兼容，无之前对话的summary就遍历完
            if isinstance(msg, AIMessage):
                if "type" in msg.additional_kwargs and msg.additional_kwargs.get("type") == AIMessageType.SUMMARY.value:
                    break
            input_msg.append(msg)

        # 反转回来，保持原始顺序
        input_msg.reverse()
        return input_msg

    async def _get_current_round_conversation_except_files(self, messages: List[BaseMessage]):
        """
            获取本轮对话除了文件传入部分

            Args:
                messages: langgraph状态消息

            Return:
                本轮对话消息除了文件传入部分（按原始顺序）
        """
        input_msg = []
        for msg in reversed(messages):  # 首轮对话也兼容，无之前对话的summary就遍历完
            if isinstance(msg, HumanMessage):
                if "is_file" in msg.additional_kwargs and msg.additional_kwargs.get("is_file"):
                    break
            input_msg.append(msg)

        # 反转回来，保持原始顺序
        input_msg.reverse()
        return input_msg

    async def _get_current_round_conversation_cycling(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
            获取本轮对话每次循环部分内容

            Args:
                messages: langgraph状态消息

            Return:
                本轮对话消息除了文件传入部分
        """
        cycle_msg = []
        for msg in reversed(messages): # agent_node每一次循环都会更新一次AIMessage和ToolMessage
            cycle_msg.insert(0, msg)
            if isinstance(msg, AIMessage) and msg.additional_kwargs.get("type") ==AIMessageType.REASONING.value:
                break
        return cycle_msg

    async def _switch_files_content_to_files(self, human_message: HumanMessage)-> List[List[dict]]:
        """
        把build_files_content中构造的HumanMessage笼统的内容，转化为每文件一部分的列表嵌套列表
        """
        files = defaultdict(list)

        files_chunks = human_message.content
        for chunk in files_chunks:
            if (index := chunk.get("index")) is not None:
                files[index].append(chunk)

        return [files[i] for i in sorted(files.keys())]

    async def _filter_thinking_content(self, ai_response: AIMessage) -> AIMessage:
        """
        过滤掉 AI 回复中的思考过程内容
        支持格式:
        - <thinking>...</thinking>
        - <thought>...</thought>
        - 等等
        """
        content = ai_response.content
        if not content:
            return ai_response

        # 过滤标签内的思考内容（通用格式）
        patterns = [
            r'<thinking>.*?</thinking>',
            r'<thought>.*?</thought>',
            r'<reasoning>.*?</reasoning>',
            r'<think>.*?</think>',
        ]

        if isinstance(content, str):
            for pattern in patterns:
                content = re.sub(pattern, '', content, flags=re.DOTALL)

        return AIMessage(
            content=content,
            additional_kwargs=ai_response.additional_kwargs,
            response_metadata=ai_response.response_metadata,
            id=ai_response.id,
            usage_metadata=getattr(ai_response, "usage_metadata", None)
        )


    async def check_and_trigger_interrupt(self, session_id):
        """
        检查当前session_id下的对话是否被中断
        如果Redis中存在中断标记，返回interrupt事件
        """
        interrupt_key = f"interrupt:{session_id}"
        # 检查中断
        key_value = await self.redis_client.hgetall(interrupt_key)
        if key_value:
            return interrupt(value=key_value)

        return None

    async def _create_graph_process_files(self):
        """
        处理文件图工作流
        """
        workflow = StateGraph(FileParseState)

        async def split_files_node(state: FileParseState):
            """拆分文件节点"""

            messages = list(state["messages"])

            current_message = await self._get_current_round_conversation(messages)

            files = []
            for msg in current_message:
                if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("is_file", False):
                    files = await self._switch_files_content_to_files(msg)

            # todo 增加对大文件的处理逻辑，切片

            return {
                "files": files,
            }

        async def file_process_node(state: FileParseState):
            """文件处理节点"""

            prompt = """你是文件解析助手。根据输入的图片进行解析，输出对应格式的结果。

【文件解析规则】
- 解析文档（如PDF、Word等）：返回文本内容 + 图片解析（如有）
- 解析图片（如照片、截图等）：只返回图片内容描述
- 解析文本（如TXT等）：返回解析好的文本内容
- 无文件传入时输出"无文件内容"

【输出格式】
【文件名】
图片内容描述/文本内容/无文件内容"""

            file = state["single_file"]

            file_msg = HumanMessage(content=[
                {"type": "text", "text": prompt},
                *file,
            ])

            resp = await self.llm_imp_ipt_vl.ainvoke([file_msg])

            resp_str = self._get_message_content_string(resp)

            return {"parsed_results": [resp_str]}

        async def aggregator_node(state: FileParseState):
            """
            文件处理结果聚合节点
            """
            parsed_results = state["parsed_results"]

            combined_content = "\n".join(parsed_results) if parsed_results else "无文件传入"
            if not combined_content.strip():
                combined_content = "无文件传入"

            combined_result = HumanMessage(content=combined_content)

            return {"combined_result": combined_result}

        workflow.add_node("split_files_node", split_files_node)
        workflow.add_node("file_process_node", file_process_node)
        workflow.add_node("aggregator_node", aggregator_node)

        def files_fan_out(state: FileParseState):
            files = state.get("files", [])
            if not files or all(not f for f in files):
                return "aggregator_node"
            # 用Send传参别的字段会被舍弃掉，除非用state_schema
            return [Send("file_process_node", {"single_file": f}) for f in files]

        workflow.set_entry_point("split_files_node")
        workflow.add_conditional_edges(
            "split_files_node",
            files_fan_out,
            {
                "file_process_node": "file_process_node",
                "aggregator_node": "aggregator_node"
            }
        )
        workflow.add_edge("file_process_node", "aggregator_node")

        workflow.add_edge("aggregator_node", END)

        return workflow.compile()

    async def _create_graph_core2(self):
        """
        工程化图工作流对象:
        usr_input -> input_parse -> context_assembly
        -> agent_node -> tool_node --↗
                   ↘--> final_node
        """
        TOOL_CALL_TIMES = 20

        tools = await self.mcp_client.get_tools()

        workflow = StateGraph(ChatStateCore2)

        async def input_parse_node(state: ChatStateCore2, config: RunnableConfig):
            """
            输入预处理节点
            """
            thread_id = config["configurable"]["thread_id"]

            input_msg = []
            messages = list(state["messages"])

            processed_files = await self.graph_process_files.ainvoke({"messages": messages})

            files_input: HumanMessage = processed_files["combined_result"]

            user_input: List[HumanMessage] = await self._get_current_round_conversation_except_files( messages)
            history_messages = await self._get_validate_history_message(messages)

            if history_messages and len(history_messages) >= 8: # 四轮对话
                history_invoke = history_messages[-8:]
            else:
                history_invoke = history_messages

            input_msg.extend(history_invoke)
            input_msg.append(files_input)
            input_msg.extend(user_input)

            imp_ipt = await self.llm_imp_ipt.ainvoke({"messages": input_msg})

            imp_ipt = await self._filter_thinking_content(imp_ipt)

            imp_ipt_content = imp_ipt.content
            imp_ipt_additional_kwargs = imp_ipt.additional_kwargs
            imp_ipt_id = imp_ipt.id
            imp_ipt_response_metadata = imp_ipt.response_metadata

            imp_ipt = HumanMessage(content=imp_ipt_content, additional_kwargs=imp_ipt_additional_kwargs, id=imp_ipt_id, response_metadata=imp_ipt_response_metadata)

            return {
                "imp_ipt": imp_ipt,
                "context": [],
                "memory_user_message": imp_ipt_content,
                "memory_tool_results": [],
                "memory_tool_calls": [],
                "memory_ai_response": None,
                "tool_call_times": 0,
            }

        async def context_assembly_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            context = []
            tool_results = state["memory_tool_results"] if state["memory_tool_results"] else []

            if not state["context"]:
                memory_message :SystemMessage = self.memory_manager.get_relevant_memory(thread_id)
                context.append(memory_message)

                imp_ipt_msg: HumanMessage = state["imp_ipt"]
                context.append(imp_ipt_msg)
            else:
                context = state["context"]

                cycle_msg = await self._get_current_round_conversation_cycling(state["messages"])
                context.extend(cycle_msg,)

                for msg in cycle_msg:
                    if isinstance(msg, ToolMessage):
                        content_string = self._get_message_content_string(msg)
                        tool_results.append(content_string)

            return {
                "context": context,
                "memory_tool_results": tool_results
            }

        async def agent_node(state: ChatStateCore2, config: RunnableConfig):
            """AI 代理节点，处理用户消息并决定是否调用工具"""
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            if state["memory_tool_calls"]:
                tool_calls = state["memory_tool_calls"]
            else:
                tool_calls = []

            tool_call_times = state["tool_call_times"]

            input_msg = state["context"]

            if tool_call_times >= TOOL_CALL_TIMES:
                interrupt_msg = SystemMessage(content=f"已超过{TOOL_CALL_TIMES}次调用工具次数，请停止工具调用提前结束对话")
                input_msg.append(interrupt_msg)

            response = await self.agent_llm.ainvoke({"messages": input_msg})

            response = await self._filter_thinking_content(response)

            # 符合ToolNode节点的AIMessage(REASONING)
            format_response = self._parse_content_to_tool_calls(response)

            for tool_call in format_response.tool_calls:
                tool_call["args"]["session_id"] = thread_id

            tool_call_times += 1

            tool_calls.extend(format_response.tool_calls)

            return {
                "messages": [format_response],
                "tool_call_times": tool_call_times,
                "memory_tool_calls": tool_calls,
            }

        tool_execution_node = ToolNode(tools=tools)  # 使用langgraph官方工具节点

        async def final_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            input_msg = state["context"]

            response = await self.llm_core.ainvoke({"messages": input_msg})

            response = await self._filter_thinking_content( response)

            # AIMessage字段支持解包复制
            response_dict = dict(response)
            response_dict["additional_kwargs"] = {**response.additional_kwargs, "type": AIMessageType.SUMMARY.value}

            response_better = AIMessage(**response_dict)

            # 提取AI回复内容用于memory
            memory_ai_response = self._get_message_content_string(response_better)

            return {
                "messages": [response_better],
                "memory_ai_response": memory_ai_response,
            }

        workflow.add_node("input_parse_node", input_parse_node)
        workflow.add_node("context_assembly_node", context_assembly_node)
        workflow.add_node("agent_node", agent_node)
        workflow.add_node("tool_execution_node", tool_execution_node)
        workflow.add_node("final_node", final_node)

        def route_agent_output(state: ChatStateCore2) -> str:
            """根据代理输出决定下一步"""
            last_message = state["messages"][-1]
            if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tool_execution_node"
            return "final_node"

        workflow.set_entry_point("input_parse_node")
        workflow.add_edge("input_parse_node", "context_assembly_node")

        workflow.add_edge("context_assembly_node", "agent_node")

        workflow.add_conditional_edges("agent_node",
            route_agent_output,
            {
                "tool_execution_node": "tool_execution_node",
                "final_node": "final_node",
            }
        )

        workflow.add_edge("tool_execution_node", "context_assembly_node")

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

    async def astream(self, messages: Optional[list[BaseMessage]], config: Optional[Dict[str, Any]] = None) -> AsyncGenerator[Any, None]:
        """
        Stream workflow execution

        Args:
            messages: List of messages
            config: Optional configuration

        Yields:
            Workflow execution chunks
        """
        config = {
            **config,
            "recursion_limit": 1000,
        }

        async for e in self.graph.astream_events({
            "messages": messages},
            config=config,
        ):
                yield e
