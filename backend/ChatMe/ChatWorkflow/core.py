import asyncio
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator, List

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.prebuilt import ToolNode
from langgraph.types import Send, interrupt

from .config.graph_config import get_agent_node_config, get_graph_final_node_config, \
    get_imp_ipt_config, get_history_summary_node_config, get_llm_memory_config, get_model_vl_config, \
    get_should_end_node_config, get_react_compact_config
from .config.models import ChatStateCore2, AIMessageType, FileParseState
from .Memory.core import MemoryManager
from .mcps.tools import sub_agent
from ..LoggingManager.logging_config import get_logger

class ChatWorkflow:
    """
    ChatMe工作流对象：
    实现自定义langgraph工作流
    """

    def __init__(self):
        self.logger = get_logger(__class__.__name__)

        self._final_system_template = None
        self.llm_core = None
        self.agent_llm = None
        self.summary_llm = None
        self.react_compact_llm = None
        self.llm_imp_ipt = None
        self.llm_imp_ipt_vl = None
        self.should_end_llm = None

        self.tools = None
        self.graph = None
        self.graph_process_files = None
        self.checkpointer = None
        self.redis_client = None
        self.mcp_client = None
        self.memory_manager = None
        self.files_cached_dir = None

    def _generate_tool_param_warning(self, tool_name: str, missing_params: List[str]) -> str:
        """生成工具参数缺失的警告信息"""
        param_list = ", ".join(missing_params)
        self.logger.warning(f"工具 {tool_name} 缺少参数: {missing_params}")
        return f"[工具参数错误] {tool_name} 缺少必需参数: {param_list}，请检查格式后重试"

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

        tools = await self.mcp_client.get_tools()
        tools.append(sub_agent)
        self.tools = tools

    async def init_memory_manager(self):
        llm_memory_config, llm_memory_prompt = get_llm_memory_config()
        self.memory_manager = MemoryManager(llm_config=llm_memory_config, memory_prompt=llm_memory_prompt)

    async def init_llms(self):
        # 最终节点配置
        llm_config, system_prompt = get_graph_final_node_config()

        # final_node 用 dynamic system prompt 注入（imp_ipt 占位段由 final_node.format() 注入），
        self._final_system_template = system_prompt
        self.llm_core = ChatOpenAI(**llm_config)

        # agent_node配置
        agent_node_config ,agent_prompt = get_agent_node_config()

        self.agent_llm = ChatOpenAI(**agent_node_config).bind_tools(self.tools)
        prompt = ChatPromptTemplate.from_messages([("system", agent_prompt), MessagesPlaceholder("messages")])
        self.agent_llm = prompt | self.agent_llm

        # 历史对话总结节点配置
        summary_llm_config, summary_llm_prompt = get_history_summary_node_config()

        self.summary_llm = ChatOpenAI(**summary_llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", summary_llm_prompt), MessagesPlaceholder("messages")])
        self.summary_llm = prompt | self.summary_llm

        # ReAct 流程压缩节点配置
        react_compact_llm_config, react_compact_prompt = get_react_compact_config()

        self.react_compact_llm = ChatOpenAI(**react_compact_llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", react_compact_prompt), MessagesPlaceholder("messages")])
        self.react_compact_llm = prompt | self.react_compact_llm

        # 输入优化大模型配置
        imp_ipt_llm_config, imp_ipt_llm_prompt = get_imp_ipt_config()

        self.llm_imp_ipt = ChatOpenAI(**imp_ipt_llm_config)
        prompt = ChatPromptTemplate.from_messages([("system", imp_ipt_llm_prompt), MessagesPlaceholder("messages")])
        self.llm_imp_ipt = prompt | self.llm_imp_ipt

        # should_end_node 配置
        should_end_llm_config, should_end_prompt_content = get_should_end_node_config()
        self.should_end_llm = ChatOpenAI(**should_end_llm_config)
        should_end_prompt = ChatPromptTemplate.from_messages([("system", should_end_prompt_content), MessagesPlaceholder("messages")])
        self.should_end_llm = should_end_prompt | self.should_end_llm

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
        ai_message.additional_kwargs = {"type": AIMessageType.REASONING.value}

        # 保护 None 值
        raw_content = ai_message.content
        if raw_content is None:
            return ai_message
        if not raw_content:
            return ai_message

        content = str(raw_content)
        tool_calls = []

        # 找到所有 <tool_calls>...</tool_calls> 块并解析
        tag_pattern = r'<tool_calls>(.*?)</tool_calls>'
        for match in re.finditer(tag_pattern, content, re.DOTALL):
            json_str = match.group(1).strip()
            if not json_str:
                continue

            tool_call_data = None
            try:
                tool_call_data = json.loads(json_str)
            except json.JSONDecodeError:
                # 修复 \& 这种非法转义后重试
                fixed = json_str.replace('\\&', '\\\\&')
                try:
                    tool_call_data = json.loads(fixed)
                except json.JSONDecodeError:
                    # 还是失败，尝试修复 JSON 格式后用 json.loads 解析
                    # 常见问题：多余逗号、引号转义等
                    try:
                        # 尝试修复常见的 JSON 格式问题
                        fixed_json = json_str
                        # 移除尾部多余逗号
                        fixed_json = re.sub(r',(\s*[}\]])', r'\1', fixed_json)
                        tool_call_data = json.loads(fixed_json)
                    except json.JSONDecodeError:
                        # 还是失败，正则提取
                        name_match = re.search(r'"name"\s*:\s*"([^"]*)"', json_str)
                        if not name_match:
                            continue
                        name = name_match.group(1)

                        # 使用递归方式提取嵌套的 args 对象
                        args = {}
                        args_start = json_str.find('"args"')
                        if args_start != -1:
                            brace_start = json_str.find('{', args_start)
                            if brace_start != -1:
                                # 找对应的结束括号（处理嵌套）
                                depth = 1
                                i = brace_start + 1
                                while i < len(json_str) and depth > 0:
                                    if json_str[i] == '{':
                                        depth += 1
                                    elif json_str[i] == '}':
                                        depth -= 1
                                    i += 1
                                if depth == 0:
                                    args_str = json_str[brace_start:i]
                                    try:
                                        args = json.loads(args_str)
                                    except:
                                        pass

                        tool_call_data = {"name": name, "args": args}

            if isinstance(tool_call_data, list):
                for j, item in enumerate(tool_call_data):
                    args = item.get("args", {})
                    # 删除 args 中的无效参数，避免传入工具时报错
                    args.pop("id", None)
                    args.pop("name", None)
                    args.pop("Language", None)
                    tc = {
                        "name": item.get("name"),
                        "args": args,
                        "id": item.get("id", "") or f"call_{len(tool_calls)+j+1}",
                    }
                    if tc["name"]:
                        tool_calls.append(tc)
            else:
                args = tool_call_data.get("args", {})
                args.pop("id", None)
                args.pop("name", None)
                args.pop("Language", None)
                tc = {
                    "name": tool_call_data.get("name"),
                    "args": args,
                    "id": tool_call_data.get("id", "") or f"call_{len(tool_calls)+1}",
                }
                if tc["name"]:
                    tool_calls.append(tc)

        if tool_calls:
            # 限制单次并发 tool_calls 数量，取前 3 个
            MAX_PARALLEL_TOOL_CALLS = 3
            ai_message.tool_calls = tool_calls[:MAX_PARALLEL_TOOL_CALLS]
            ai_message.content = content

        return ai_message

    async def _get_validate_history_message(self, history_messages: List[BaseMessage],limit: int)-> List[BaseMessage]:
        """获取历史有效的聊天消息

        注意：只返回上一轮及更早的历史消息，不包含当前轮的 HumanMessage。
        通过排除 messages 列表末尾的 HumanMessage（当前轮输入）来实现。
        """
        input_msg = []
        if not history_messages:
            return input_msg

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

        return input_msg[-limit:] if len(input_msg) >= limit else input_msg

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
            if isinstance(msg, HumanMessage):
                if "is_file" in msg.additional_kwargs:
                    input_msg.append(msg)
            else:
                break

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
            else:
                break
            input_msg.append(msg)

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
            # 清除 MiniMax-M3 生成的 expanded 格式工具调用标签
            r'<tool_call>.*?</tool_call>',
            r'\]<]minimax\[[>]',
            r'\[<invoke \w+>\]\[<(\w+)>(.*?)</\1>\]',
            # M3 在 </tool_calls> 之后多余的左括号，不破坏合法的 <tool_calls> 块本身
            r'(?<=</tool_calls>)\s*\[+',
        ]

        if isinstance(content, str):
            for pattern in patterns:
                content = re.sub(pattern, '', content, flags=re.DOTALL)

        return AIMessage(
            content=content,
            additional_kwargs=ai_response.additional_kwargs,
            response_metadata=ai_response.response_metadata,
            id=ai_response.id,
            usage_metadata=getattr(ai_response, "usage_metadata", None),
            tool_calls=getattr(ai_response, "tool_calls", []) or [],
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

    # =========================================================================
    # ReAct 流程压缩 helper
    # =========================================================================

    @staticmethod
    def _content_chars(messages: List[BaseMessage]) -> int:
        """
        累计 context 中所有消息的字符数（粗略用于触发判断）
        """
        total = 0
        for m in messages:
            content = m.content
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        total += len(item.get("text", "") or item.get("content", "") or "")
                    elif isinstance(item, str):
                        total += len(item)
            total += len(getattr(m, "id", "") or "")
        return total

    @staticmethod
    def _should_compact_react(
        complete_loop_count: int,
        compact_loops: int,
        keep_loops: int,
        tool_call_times: int,
        last_compact_at: int,
        draft_chars: int,
        min_chars: int,
    ) -> bool:
        """
        触发判断：
        - 至少存在 compact_loops + keep_loops 个完整工具 loop
        - 不是同一次压缩内重复触发（tool_call_times != last_compact_at 防 state 恢复）
        - draft_chars 不少于 min_chars（防短 context 空压）
        """
        return (
            complete_loop_count >= compact_loops + keep_loops
            and tool_call_times != last_compact_at
            and draft_chars >= min_chars
        )

    @staticmethod
    def _find_imp_ipt_idx(context: List[BaseMessage]) -> Optional[int]:
        """
        通过 additional_kwargs.imp_ipt == True 来定位本轮用户意图。

        imp_ipt 是 draft 的天然切分锚点：
          - 它之前的内容（含 memory_sys 等）全部保留
          - 它之后的内容要被新摘要整体覆盖
        """
        for i, m in enumerate(context):
            if isinstance(m, HumanMessage) and m.additional_kwargs.get("imp_ipt"):
                return i
        return None

    @staticmethod
    def _find_complete_tool_loops(context: List[BaseMessage]) -> List[List[int]]:
        """
        找 context 中所有完整工具 loop。
        一个 loop = AIMessage(tool_calls=[...]) + 后续所有匹配 tool_call_id 的 ToolMessage。
        只有全部 tool_call_id 都找到对应 ToolMessage 时才算完整。
        返回每个 loop 的消息下标列表：[ai_idx, tool_idx1, tool_idx2, ...]。
        """
        loops: List[List[int]] = []
        pending_ai_idx: Optional[int] = None
        pending_call_ids: set[str] = set()
        pending_tool_indices: List[int] = []

        for i, m in enumerate(context):
            if isinstance(m, AIMessage):
                new_ids = {tc.get("id") for tc in (m.tool_calls or []) if tc.get("id")}
                if new_ids:
                    pending_ai_idx = i
                    pending_call_ids = new_ids
                    pending_tool_indices = []
            elif isinstance(m, ToolMessage):
                if pending_ai_idx is not None and m.tool_call_id in pending_call_ids:
                    pending_tool_indices.append(i)
                    pending_call_ids.remove(m.tool_call_id)
                    if not pending_call_ids:
                        loops.append([pending_ai_idx, *pending_tool_indices])
                        pending_ai_idx = None
                        pending_tool_indices = []

        return loops

    @staticmethod
    def _build_compaction_draft(
        context: List[BaseMessage],
        s_new: str,
        keep_loops: List[List[int]],
    ) -> Optional[List[BaseMessage]]:
        """
        基于 _find_imp_ipt_idx 与完整工具 loop 动态拼装压缩 draft：

          1. imp_ipt 之前的所有内容（含 memory_sys、可能的其他 SystemMessage）→ 整体保留
          2. 在 imp_ipt 之后插入新 SystemMessage（替换原 summary 与被压缩的 ReAct 历史）
          3. 末尾挂最近保留的完整工具 loop 原文（默认最近 2 轮）

        找不到 imp_ipt 时返回 None，调用方应放弃本次压缩。
        """
        imp_ipt_idx = ChatWorkflow._find_imp_ipt_idx(context)
        if imp_ipt_idx is None:
            return None

        draft: List[BaseMessage] = list(context[:imp_ipt_idx + 1])
        draft.append(SystemMessage(content=f"【ReAct 摘要】\n{s_new}"))

        for loop in keep_loops:
            for idx in loop:
                draft.append(context[idx])

        return draft

    async def _try_compact_react(self, context: List[BaseMessage]) -> Optional[str]:
        """
        喂整体 context 给 react_compact_llm，让它从 BaseMessage 类型识别长期记忆 / 用户意图 / ReAct 轨迹并产出 ≤2000 字中文摘要。

        整体覆盖式：返回新摘要后由 context_assembly_node 替换 context[2] 位置（旧 summary + 中间 ReAct 历史一次性覆盖）。
        失败 / 输出异常一律返回 None，调用方保持 context 不变。
        """
        if self.react_compact_llm is None:
            return None
        if len(context) < 4:
            return None

        timeout_sec = 30
        try:
            resp = await asyncio.wait_for(
                self.react_compact_llm.ainvoke({"messages": context}),
                timeout=timeout_sec,
            )
            resp = await self._filter_thinking_content(resp)
            text = self._get_message_content_string(resp).strip()

            # 长度兜底（[80, 2500] 范围）
            if not text or len(text) < 80 or len(text) > 2500:
                self.logger.warning(f"ReAct 压缩结果长度异常: {len(text)}")
                return None
            # 残留标签兜底
            if re.search(r"(\\u|<tool_calls>|<thinking>)", text):
                self.logger.warning("ReAct 压缩结果含残留标签")
                return None
            return text
        except Exception as e:
            self.logger.warning(f"ReAct 压缩失败: {e}")
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

            prompt = """你是图片内容解析助手。请解析输入的图片，输出文字描述。

【解析要求】
- 详细描述图中关键信息：物体、场景、文字内容、图表数据等
- 数据图表（柱状图/折线图/表格截图）：尽量提取具体数值、轴标签、趋势
- 文字截图（聊天记录/文档截图）：尽量识别并输出原文
- 描述简洁精准，避免冗余

【输出格式】
【文件：filename】
【图片描述】ß

其中 filename 用输入中"-- xxx --"形式提供的文件名，不要改写。
"""

            file = state["single_file"]

            # 纯文本/文档：跳过 VL，避免小参数视觉模型处理得慢
            has_image = any(
                isinstance(item, dict) and item.get("type") == "image_url"
                for item in file
            )
            if not has_image:
                text_content = ""
                for item in file:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_content += item.get("text", "")
                return {"parsed_results": [text_content]}

            # 含图片：调 VL 解析
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

    async def _create_graph_core(self):
        """
        工程化图工作流对象:
        usr_input -> input_parse -> context_assembly
        -> agent_node -> tool_node --↗
                   ↘--> final_node
        """
        TOOL_CALL_TIMES = 50

        tools = await self.mcp_client.get_tools()
        tools.append(sub_agent)

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
            history_messages = await self._get_validate_history_message(messages, 4)

            # 续接时注入的中断原因 SystemMessage 需要加到 input_msg 最前面，否则 LLM 看不到
            for msg in messages:
                if isinstance(msg, SystemMessage) and ("中断原因" in msg.content or "中断续接" in msg.content):
                    input_msg.insert(0, msg)
                    break

            input_msg.extend(history_messages)
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

            input_msg = state["context"]

            if isinstance(state["messages"][-1], SystemMessage):
                if "中断" in state["messages"][-1].content:
                    input_msg.append(state["messages"][-1])

            if state["memory_tool_calls"]:
                tool_calls = state["memory_tool_calls"]
            else:
                tool_calls = []

            tool_call_times = state["tool_call_times"]

            if tool_call_times >= TOOL_CALL_TIMES:
                interrupt_msg = SystemMessage(content=f"已超过{TOOL_CALL_TIMES}次调用工具次数，请停止工具调用提前结束对话")
                input_msg.append(interrupt_msg)

            response = await self.agent_llm.ainvoke({"messages": input_msg})

            response = await self._filter_thinking_content(response)

            # 符合ToolNode节点的AIMessage(REASONING)
            format_response = self._parse_content_to_tool_calls(response)

            # 验证工具调用
            for tool_call in format_response.tool_calls:
                tool_name = tool_call.get("name", "")
                args = tool_call.get("args", {})

                # todo
                # if tool_call not in tools:
                #     self.logger.warning(f"没有工具: {tool_call}")

                # code 必须有 code 参数
                if tool_name == "code" and "code" not in args:
                    warning_results = self._generate_tool_param_warning("code", ["code"])
                    tool_call["args"]["code"] = warning_results
                    self.logger.warning(f"code 缺少 code 参数: {args}")

                # cmd 必须有 command 参数
                if tool_name == "cmd" and "command" not in args:
                    warning_results = self._generate_tool_param_warning("cmd", ["command"])
                    tool_call["args"]["command"] = warning_results
                    self.logger.warning(f"cmd 缺少 command 参数: {args}")

                tool_call["args"]["session_id"] = thread_id
                tool_calls.append(tool_call)

            tool_call_times += 1

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
            return "should_end_node"

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

    async def _create_graph_core2(self):
        """
        工程化图工作流对象:
        usr_input -> input_parse -> context_assembly
        -> agent_node -> tool_node --↗
                   ↘--> final_node
        """
        TOOL_CALL_TIMES = 50
        RETRY_TIMES = 3
        REACT_COMPACT_LOOPS = 5
        REACT_KEEP_LOOPS = 2
        REACT_COMPACT_MIN_CHARS = 2000


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
            # history_messages = await self._get_validate_history_message(messages,2)
            history_memory: SystemMessage = self.memory_manager.get_relevant_memory(thread_id)

            # 如果在这里中断时，续接时注入的中断原因 SystemMessage 需要加到 input_msg 最前面，否则 LLM 看不到
            for msg in messages:
                if isinstance(msg, SystemMessage) and "中断" in msg.content:
                    input_msg.insert(0, msg)
                    break

            input_msg.append(history_memory)
            # input_msg.extend(history_messages)
            input_msg.append(files_input)
            input_msg.extend(user_input)

            imp_ipt = await self.llm_imp_ipt.ainvoke({"messages": input_msg})

            imp_ipt = await self._filter_thinking_content(imp_ipt)

            imp_ipt_content = imp_ipt.content
            imp_ipt_additional_kwargs = imp_ipt.additional_kwargs
            imp_ipt_id = imp_ipt.id
            imp_ipt_response_metadata = imp_ipt.response_metadata

            # imp_ipt 标记：业务流各处用 additional_kwargs.imp_ipt == True 来唯一识别本轮意图
            imp_ipt = HumanMessage(
                content=imp_ipt_content,
                additional_kwargs={**imp_ipt_additional_kwargs, "imp_ipt": True},
                id=imp_ipt_id,
                response_metadata=imp_ipt_response_metadata,
            )

            self.logger.info(f"[imp_ipt_llm]:{imp_ipt_content}")

            return {
                "imp_ipt": imp_ipt,
                "context": [],
                "memory_user_message": imp_ipt_content,
                "memory_tool_results": [],
                "memory_tool_calls": [],
                "memory_ai_response": None,
                "tool_call_times": 0,
                "should_end_retry_times": 0,
                "context_summary_text": "",
                "last_compact_at_tool_calls": 0,
            }

        async def context_assembly_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]

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

            # ✨ ReAct 流程压缩：达到 compact + keep 个完整工具 loop 后，压缩前 compact 轮，保留最近 keep 轮原文
            tool_call_times = state.get("tool_call_times", 0)
            last_compact_at = state.get("last_compact_at_tool_calls", 0)
            draft_chars = self._content_chars(context)
            complete_loops = self._find_complete_tool_loops(context)

            if self._should_compact_react(
                len(complete_loops),
                REACT_COMPACT_LOOPS,
                REACT_KEEP_LOOPS,
                tool_call_times,
                last_compact_at,
                draft_chars,
                REACT_COMPACT_MIN_CHARS,
            ):
                keep_loops = complete_loops[-REACT_KEEP_LOOPS:]
                keep_indices = {idx for loop in keep_loops for idx in loop}
                compact_context = [
                    msg for i, msg in enumerate(context)
                    if i not in keep_indices
                ]

                s_new = await self._try_compact_react(compact_context)
                if s_new is not None:
                    # 压缩输入排除最近保留的完整工具 loop，draft 再从原始 context 挂回最近 loop 原文，避免摘要与原文重复。
                    draft = self._build_compaction_draft(context, s_new, keep_loops)
                    if draft is not None:
                        self.logger.debug(f"[react压缩]: compact_loops={len(complete_loops) - len(keep_loops)}, keep_loops={len(keep_loops)}, context={context}")
                        return {
                            "context": draft,
                            "memory_tool_results": tool_results,
                            "context_summary_text": s_new,
                            "last_compact_at_tool_calls": tool_call_times,
                        }
                # 压缩失败 / 定位失败：不改 context，原样返回
            return {
                "context": context,
                "memory_tool_results": tool_results
            }

        async def agent_node(state: ChatStateCore2, config: RunnableConfig):
            """AI 代理节点，处理用户消息并决定是否调用工具"""
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            input_msg = state["context"]

            if isinstance(state["messages"][-1], SystemMessage):
                if "中断" in state["messages"][-1].content:
                    input_msg.append(state["messages"][-1])

            if state["memory_tool_calls"]:
                tool_calls = state["memory_tool_calls"]
            else:
                tool_calls = []

            tool_call_times = state["tool_call_times"]

            if tool_call_times >= TOOL_CALL_TIMES:
                interrupt_msg = SystemMessage(content=f"已超过{TOOL_CALL_TIMES}次调用工具次数，请停止工具调用提前结束对话")
                input_msg.append(interrupt_msg)

            response = await self.agent_llm.ainvoke({"messages": input_msg})

            response = await self._filter_thinking_content(response)

            # 符合ToolNode节点的AIMessage(REASONING)
            format_response = self._parse_content_to_tool_calls(response)

            counts = 0

            # 验证工具调用
            for tool_call in format_response.tool_calls:
                tool_name = tool_call.get("name", "")
                args = tool_call.get("args", {})

                # todo
                # if tool_call not in tools:
                #     self.logger.warning(f"没有工具: {tool_call}")

                # code 必须有 code 参数
                if tool_name == "code" and "code" not in args:
                    warning_results = self._generate_tool_param_warning("code", ["code"])
                    tool_call["args"]["code"] = warning_results
                    self.logger.warning(f"code 缺少 code 参数: {args}")

                # cmd 必须有 command 参数
                if tool_name == "cmd" and "command" not in args:
                    warning_results = self._generate_tool_param_warning("cmd", ["command"])
                    tool_call["args"]["command"] = warning_results
                    self.logger.warning(f"cmd 缺少 command 参数: {args}")

                tool_call["args"]["session_id"] = thread_id
                tool_calls.append(tool_call)

                counts += 1

            tool_call_times += counts


            return {
                "messages": [format_response],
                "tool_call_times": tool_call_times,
                "memory_tool_calls": tool_calls,
            }

        tool_execution_node = ToolNode(tools=self.tools)  # 使用langgraph官方工具节点

        async def should_end_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            context = state["context"]

            last_message = state["messages"][-1]
            response = await self.should_end_llm.ainvoke({"messages": [last_message]})
            content = str(response.content)

            self.logger.debug(f"[should_end] response: {content}")
            decision = "end"
            if "retry" in content or "RETRY" in content:
                decision = "retry"

            retry_times = state.get("should_end_retry_times", 0) or 0

            if decision == "retry":
                retry_times += 1
                if retry_times >= RETRY_TIMES:
                    # 超过3次强制结束，清理验证相关 SystemMessage 后跳 final_node
                    cleaned_context = [msg for msg in context if not (
                        isinstance(msg, SystemMessage) and "[Warning]" in msg.content
                    )]
                    return {"should_end_decision": "end", "should_end_retry_times": retry_times, "context": cleaned_context}
                retry_msg = SystemMessage(content="[Warning] 重新检查一下RE-ACT思维链")
                context.append(retry_msg)
                return {"should_end_decision": decision, "should_end_retry_times": retry_times, "context": context, "messages": [retry_msg]}

            cleaned_context = [msg for msg in context if not (
                isinstance(msg, SystemMessage) and "[Warning]" in msg.content
            )]
            return {"should_end_decision": decision, "should_end_retry_times": 0, "context": cleaned_context}

        async def final_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            # imp_ipt 在 system 层独占最高注意力位；{imp_ipt} 占位由 _final_system_template.format() 注入。
            context = list(state["context"])

            self.logger.debug(f"[final_context]: {context}")

            imp_ipt_idx = self._find_imp_ipt_idx(context)
            if imp_ipt_idx is not None:
                context.pop(imp_ipt_idx)

            imp_ipt_msg: HumanMessage = state["imp_ipt"]
            # 防止占位符出错
            escaped_imp_ipt = imp_ipt_msg.content.replace("{", "{{").replace("}", "}}")
            system_prompt = self._final_system_template.format(imp_ipt=escaped_imp_ipt)

            response = await self.llm_core.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    *context,
                    HumanMessage(content="请生成回复"),
                ]
            )

            response = await self._filter_thinking_content( response)

            self.logger.debug(f"[final_node]: {response}")

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
        workflow.add_node("should_end_node", should_end_node)
        workflow.add_node("final_node", final_node)

        def route_agent_output(state: ChatStateCore2) -> str:
            """根据代理输出决定下一步"""
            last_message = state["messages"][-1]
            if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tool_execution_node"
            return "should_end_node"

        def route_should_end(state: ChatStateCore2) -> str:
            """should_end_node 返回 end 则去 final_node，返回 retry 则回 context_assembly_node"""
            decision = state.get("should_end_decision", "end")
            if decision == "retry":
                return "context_assembly_node"
            return "final_node"

        workflow.set_entry_point("input_parse_node")
        workflow.add_edge("input_parse_node", "context_assembly_node")

        workflow.add_edge("context_assembly_node", "agent_node")

        workflow.add_conditional_edges("agent_node",
            route_agent_output,
            {
                "tool_execution_node": "tool_execution_node",
                "should_end_node": "should_end_node",
            }
        )

        workflow.add_edge("tool_execution_node", "context_assembly_node")

        workflow.add_conditional_edges("should_end_node",
            route_should_end,
            {
                "final_node": "final_node",
                "context_assembly_node": "context_assembly_node",
            }
        )

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
