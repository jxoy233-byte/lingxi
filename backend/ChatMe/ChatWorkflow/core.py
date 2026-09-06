import asyncio
import json
import operator
import re
import time
from collections import defaultdict
from datetime import datetime
from functools import reduce
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator, List

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.types import Send, interrupt

from .config.graph_config import get_agent_node_config, get_graph_final_node_config, \
    get_imp_ipt_config, get_history_summary_node_config, get_llm_memory_config, get_model_vl_config, \
    get_should_end_node_config, get_react_compact_config, get_agent_node_improved_config
from .config.models import ChatStateCore2, AIMessageType, FileParseState
from .Memory.core import MemoryManager
from .mcps.session import init_mcp, shutdown_mcp, get_mcp_tools
from .mcps.permissions.core import (
    PermissionedToolNode,
    init_permissions,
)
from .helpers import get_message_content_string, filter_thinking_content, format_thinking_chain
from ..LoggingManager.logging_config import (
    get_logger,
    get_thinking_chain_logger,
    get_pending_thinking_dir,
    sweep_pending_thinking_files,
)
from .decorators import node_guard
from .CheckpointJanitor import CheckpointJanitor
from ..paths import CACHED_DIR


async def _inject_session_header(request, handler):
    """
    MCP tool call interceptor:从 LangGraph runtime.config 拿 thread_id,
    注入到 args["__session_id"]。server 端 middleware 从 arguments pop 后塞 ContextVar。
    """
    sid = ""
    runtime = getattr(request, "runtime", None)
    if runtime is not None:
        cfg = getattr(runtime, "config", None)
        if cfg:
            configurable = cfg.get("configurable", {}) if isinstance(cfg, dict) else {}
            sid = configurable.get("thread_id") or configurable.get("session_id") or ""

    if sid:
        new_args = dict(request.args or {})
        new_args["__session_id"] = sid
        request = request.override(args=new_args)
    return await handler(request)


# MCP session 生命周期管理移到了 mcps/session.py
# core.py 只持有 interceptor + 在 init_mcps 里调 init_mcp(...)


class ChatWorkflow:
    """
    ChatMe工作流对象：
    实现自定义langgraph工作流
    """

    def __init__(self):
        self.logger = get_logger(__class__.__name__)
        # AI 思维链专用 logger（写独立 thinking_chain-YYYY-MM-DD.log）
        self.thinking_logger = get_thinking_chain_logger()

        # 启动 sweep：merge 上次进程崩溃残留的 thinking_chain 临时文件 → 主文件后清理
        swept = sweep_pending_thinking_files()
        if swept:
            self.logger.info(f"[启动 sweep] 已 merge {swept} 个残留 thinking_chain 临时文件")

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
        self.checkpoint_janitor: Optional[CheckpointJanitor] = None
        self.memory_manager = None
        self.files_cached_dir = None

        # ReAct 压缩后台任务管理（per-thread）
        self._background_compaction_tasks: Dict[str, asyncio.Task] = {}
        self._background_compaction_results: Dict[str, Optional[str]] = {}

    def _write_thinking(self, sid: str, message: str) -> None:
        """
        思维链日志写入 per-session 临时文件（流式期间缓冲）。

        为什么走临时文件而不是直接写主 thinking_chain 日志：
        多会话并发时主文件会物理交错，同一会话的 9 个节点写入会跟其他会话混在一起。
        临时文件按 sid 隔离 → 流式收尾（done / interrupt / error）由 ChatService 调
        flush_pending_thinking_for_session(sid) merge 进当天主文件并清理临时。
        """
        if not sid:
            return
        try:
            pending_file = get_pending_thinking_dir() / f"{sid}.log"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"{timestamp} - ChatMe.thinking_chain - INFO - {message}\n"
            with pending_file.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            # 兜底：临时文件写入失败不能影响流式主流程
            self.logger.warning(f"[thinking_chain] 写入 {sid} 失败: {e}")

    def _generate_tool_param_warning(self, tool_name: str, missing_params: List[str]) -> str:
        """生成工具参数缺失的警告信息"""
        param_list = ", ".join(missing_params)
        self.logger.warning(f"工具 {tool_name} 缺少参数: {missing_params}")
        return f"[工具参数错误] {tool_name} 缺少必需参数: {param_list}，请检查格式后重试"

    async def init_mcps(self):
        # 走模块级共享 singleton（sub_agent 也复用同一 client / tools）
        await init_mcp(tool_interceptors=[_inject_session_header])
        # 老 graph（_create_graph_core2）用的工具集：不暴露 done
        self.tools = get_mcp_tools(include_done=False)
        # 新 graph（_create_graph_improved）用的工具集：含 done tool
        self.tools_with_done = get_mcp_tools(include_done=True)

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

        # 新 graph（_create_graph_improved）专用 agent_llm：
        # bind_tools 含 done tool，prompt 用优化版（教 AI 用 done tool 而不是 'output Done 单词'）
        agent_node_improved_config, agent_improved_prompt = get_agent_node_improved_config()
        self.agent_llm_with_done = ChatOpenAI(**agent_node_improved_config).bind_tools(self.tools_with_done)
        improved_prompt = ChatPromptTemplate.from_messages([("system", agent_improved_prompt), MessagesPlaceholder("messages")])
        self.agent_llm_with_done = improved_prompt | self.agent_llm_with_done

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
        import asyncio
        self.files_cached_dir = str(CACHED_DIR)

        await self.init_mcps()

        # 权限审批单例（cmd/code 审批在 tool_execution_node 里做，所以在主进程加载）
        perms = init_permissions()
        self.logger.info(
            f"权限审批: policy={perms.policy.value}, "
            f"approved={len(perms.approved)}, denied={len(perms.denied)}"
        )

        await self.init_memory_manager()

        # 短期存储(redis)
        try:
            from ChatMe.ChatMeConfig import get_redis_checkpointer_url
            redis_url_checkpoint = get_redis_checkpointer_url()
        except Exception as e:
            self.logger.error(f"初始化Redis Checkpointer失败: {e}")
            raise e

        self.checkpointer = AsyncRedisSaver(redis_url=redis_url_checkpoint)
        # dump.rdb 较大时 Redis 启动会撞 LOADING： 启动时轮询redis状态
        for attempt in range(1, 31):
            try:
                await self.checkpointer.setup()
                break
            except Exception as e:
                msg = str(e)
                if "LOADING" in msg or "loading" in msg:
                    self.logger.warning(
                        f"Redis 还在加载 dump.rdb（第 {attempt}/30 次，1s 后重试）"
                    )
                    await asyncio.sleep(1.0)
                else:
                    raise
        else:
            raise RuntimeError("Redis 30s 内仍在 LOADING（dump.rdb 过大？）")

        self.redis_client = self.checkpointer._redis

        # LangGraph checkpoint 静默清理器：实例化即可，实际触发在
        # ChatService._save_round_checkpoint 每轮 round 完成时调 prune_thread
        self.checkpoint_janitor = CheckpointJanitor(self.redis_client)

        # 初始化所有llm
        await self.init_llms()

        self.graph = await self._create_graph_improved()
        # self.graph = await self._create_graph_core2()
        self.graph_process_files = await self._create_graph_process_files()

    def _parse_content_to_tool_calls(self, ai_message: AIMessage):
        """
        从 AIMessage 的 content 中提取 tool_calls 并填充到 tool_calls 字段
        某些模型（如 Grok）将 tool_calls 以 JSON 字符串形式放在 content 中，
        需要手动解析并转换为标准格式

        优先级：function_calling 已识别的 tool_calls 优先；content 嵌入的 <tool_calls>
        只在 function_calling 没结果时作为 fallback。两路并存时不去重、不合并，避免冲突。
        末尾统一按 MAX_PARALLEL_TOOL_CALLS 截断，防止 "AI 发疯" 时并发过多。
        """
        ai_message.additional_kwargs = {"type": AIMessageType.REASONING.value}

        # function_calling 已识别出 tool_calls → 直接信任，不解析 content
        existing_tool_calls = getattr(ai_message, "tool_calls", None) or []
        if existing_tool_calls:
            MAX_PARALLEL_TOOL_CALLS = 3
            if len(existing_tool_calls) > MAX_PARALLEL_TOOL_CALLS:
                ai_message.tool_calls = existing_tool_calls[:MAX_PARALLEL_TOOL_CALLS]
            return ai_message

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
            MAX_PARALLEL_TOOL_CALLS = 3
            ai_message.tool_calls = tool_calls[:MAX_PARALLEL_TOOL_CALLS]
            # parse 后主动清掉 <tool_calls>...</tool_calls> 文本块：避免残留 <invoke>...</invoke> /
            # JSON 数组等伪 tool_call 内容污染 final_node input（filter 第 5 条会保留含 <invoke> 的块
            # 给 parse 兜底，但 parse 完已不需要这段文本）。
            cleaned_content = re.sub(
                r'<tool_calls?>.*?\[?</?tool_calls?>\]?',
                '',
                content,
                flags=re.DOTALL,
            )
            ai_message.content = cleaned_content

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

    async def check_and_trigger_interrupt(self, session_id):
        """
        检查当前session_id下的对话是否被中断
        如果Redis中存在中断标记，返回interrupt事件

        优化点：先 HEXISTS 预检（~0.5ms），无中断时跳过 HGETALL（~1-2ms）；
        astream 中段每 N chunks 调一次，避免每 token 都打 Redis。
        """
        interrupt_key = f"interrupt:{session_id}"
        # Fast guard：仅检查 reason 字段存在性，避免每次 HGETALL
        if not await self.redis_client.hexists(interrupt_key, "reason"):
            return None
        key_value = await self.redis_client.hgetall(interrupt_key)
        if key_value:
            return interrupt(value=key_value)

        return None

    @staticmethod
    def _merge_chunks(chunks: List[Any]) -> AIMessage:
        """
        把 astream 累积的 AIMessageChunk 列表合并成单个 AIMessage。

        为什么必须用 reduce(operator.add) 而不是 chunks[-1]：
        OpenAI streaming 最后一帧是 usage_metadata（content 通常为空），直接拿最后 chunk
        会丢主体内容。reduce 触发 AIMessageChunk.__add__，逐 chunk 累加 content /
        tool_calls / tool_call_chunks，最后取 id / response_metadata / usage_metadata
        跟 ainvoke 等价的完整 AIMessage。
        """
        if not chunks:
            return AIMessage(content="")
        merged = reduce(operator.add, chunks)
        # AIMessageChunk → AIMessage 升级（保留 tool_calls / id / usage）
        return AIMessage(
            content=merged.content,
            tool_calls=merged.tool_calls,
            id=merged.id,
            usage_metadata=merged.usage_metadata,
            response_metadata=merged.response_metadata,
        )

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
    def _should_detect_compact(
        tool_call_times: int,
        last_compact_at: int,
        has_pending_compaction: bool,
        recent_chars: int,
        min_chars: int,
        detection_min_rounds: int,
        complete_loop_count: int,
    ) -> bool:
        """
        阶段 1 检测判断（4 阶段循环的入口）：
        - (tool_call_times - last_compact_at) >= detection_min_rounds（默认 4）：
          cool-down 机制——距上次压缩至少 4 轮才再次触发，避免短时间反复压缩；
          首次压缩时 last_compact_at=0，等价于 tool_call_times >= 4
        - has_pending_compaction is False：已有 pending 时不重复触发（一次只跑一个
          压缩周期，避免堆积）
        - recent_chars >= min_chars（默认 10000）：最近 4 轮的字符数是主驱动信号；
          字符太少压缩等于把没多少字符再压一次，丢信息且浪费 LLM 调用
        - complete_loop_count >= 1（软底）：必须有完整 loop 才值得摘要，否则压缩
          无可摘要内容，徒增 LLM 调用

        返回 True 表示进入阶段 2（触发后台 LLM 压缩）。
        """
        return (
            (tool_call_times - last_compact_at) >= detection_min_rounds
            and not has_pending_compaction
            and recent_chars >= min_chars
            and complete_loop_count >= 1
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

    def _build_clean_compact_input(self, context: List[BaseMessage]) -> Optional[List[BaseMessage]]:
        """
        重组 context 为"尽量压缩 AIMessage"喂给 react_compact_llm：

        - Header 原文保留（imp_ipt 之前所有内容：含 memory_sys）
        - SystemMessage 原文保留（旧【ReAct 摘要】 / [Warning] / 中断原因等）
        - ToolMessage 原文保留（多段连续，不合并）
        - AIMessage **必须保留**（M3 API 校验 ToolMessage.tool_call_id 必须配对
          AIMessage.tool_calls.id，缺 AIMessage 直接 400 BadRequest），但**清空 content**
          （去掉 AI 的思考过程 / 描述性文本，节省字符 + 削弱 M3 模仿"AI 想干什么"的描述性文本）。
          保留 `tool_calls` 字段（API 必需）+ `additional_kwargs` + `id`。
        - 找不到 imp_ipt 时返回 None

        为什么不能全剥离 AIMessage：实测 MiniMax-M3 和 gpt-5.1（OpenAI 兼容）API 在请求层
        严格校验 tool_call_id 配对，缺 AIMessage 直接 400。所以只能"清空 content + 保留
        tool_calls 字段"做最大化压缩。
        """
        imp_ipt_idx = self._find_imp_ipt_idx(context)
        if imp_ipt_idx is None:
            return None

        cleaned: List[BaseMessage] = []
        for i, msg in enumerate(context):
            if i <= imp_ipt_idx:
                cleaned.append(msg)                       # 头部原文保留
            elif isinstance(msg, (SystemMessage, ToolMessage)):
                cleaned.append(msg)                       # 元 SystemMessage / 多段 ToolMessage 原文保留
            elif isinstance(msg, AIMessage):
                # 清空 content（去掉 AI 思考过程 / 描述性文本），但保留 tool_calls（API 必需）
                cleaned.append(AIMessage(
                    content="",
                    tool_calls=msg.tool_calls or [],
                    additional_kwargs=msg.additional_kwargs,
                    id=msg.id,
                ))

        return cleaned

    async def _try_compact_react(self, context: List[BaseMessage], thread_id: str = "") -> Optional[str]:
        """
        把 context 重组为"尽量压缩 AIMessage"格式后喂给 react_compact_llm，
        让它从用户意图 + 工具调用历史 + 元 SystemMessage 中产出 ≤4096 tokens 中文摘要。

        整体覆盖式：返回新摘要后由 context_assembly_node 替换 context[imp_ipt+1] 位置
        （旧 summary + 中间 ReAct 历史一次性覆盖）。
        失败 / 输出异常一律返回 None，调用方保持 context 不变。

        清空 AIMessage.content 是为了压缩字符 + 削弱 模仿"AI 想干什么"的描述性文本。

        为什么末尾追加 HumanMessage("Compact thinking chain")：
        LLM（M3 / agent_llm 共用 weights）看到 input 里的 tool_calls 字段会模仿输出 tool_call 块，
        即使 prompt 已禁 + filter 兜底，仍可能输出"半截"内容把字符预算花在 tool_call JSON 上，
        导致压缩出来的摘要字符数远低于目标（"无效压缩"）。
        末尾追加 HumanMessage 用最简形式触发 LLM 回忆起 system prompt 的完整指令
        （≤4096 tokens 中文 markdown 摘要 / 禁止 tool_call 块等），让 prompt 真正生效，
        强化压缩执行效果。
        """
        if self.react_compact_llm is None:
            return None
        if len(context) < 4:
            return None

        # 重组为干净输入（AIMessage.content 清空，tool_calls 保留）
        clean_input = self._build_clean_compact_input(context)
        if clean_input is None:
            return None

        # 末尾追加 HumanMessage 触发 LLM 回忆起 system prompt 的指令（强化执行效果）
        clean_input_with_hint = list(clean_input) + [
            HumanMessage(content="Compact thinking chain")
        ]

        timeout_sec = 45
        try:
            resp = await asyncio.wait_for(
                self.react_compact_llm.ainvoke({"messages": clean_input_with_hint}),
                timeout=timeout_sec,
            )
            resp = filter_thinking_content(resp)
            text = get_message_content_string(resp).strip()

            # 打印 LLM 原始输出（filter 之后）+ 字符数 + 长度区间判定结果
            # ——肉眼检查压缩摘要质量：是不是真把 ReAct 流程压成 markdown 摘要，
            #   还是被 tool_call 残留污染 / 没理解 prompt 输出半截 / 短于 250 字符等
            if thread_id:
                self._write_thinking(
                    thread_id,
                    f"[react_compact_output]: chars={len(text)}, "
                    f"in_range={bool(text and 250 <= len(text) <= 4096)}\n"
                    f"{text}"
                )

            # 长度兜底：[250, 4096] 字符范围。下限 250 是有效压缩的最低门槛——
            # 低于这个值说明 LLM 没有充分压缩（要么是 prompt 没理解，要么是输出被 tool_call 残留污染），
            # 这种"无效压缩"应该跳过本轮而不是写进 context_assembly（保留原 context 等下次重试）
            if not text or len(text) < 250 or len(text) > 4096:
                self.logger.warning(f"ReAct 压缩结果长度异常: {len(text)}")
                return None
            # 残留标签兜底：filter 漏网时（边缘格式），防止半截 tool_call 块被当摘要
            if re.search(r"<tool[_-]calls?>|<invoke", text):
                self.logger.warning(f"ReAct 压缩结果含残留 tool_call 标签: {repr(text[:80])}")
                return None
            return text
        except Exception as e:
            self.logger.warning(f"ReAct 压缩失败: {e}")
            return None

    async def _background_compact_react(
        self,
        thread_id: str,
        compact_context: List[BaseMessage],
    ) -> None:
        """
        后台静默推进 ReAct 压缩 LLM 调用，**不阻塞主工作流**。

        阶段 2 由 context_assembly_node 用 asyncio.create_task 触发本方法；本方法
        同步 await LLM（5-10s），完成后把结果写入
        `self._background_compaction_results[thread_id]`（可能是 None）。

        下次 context_assembly_node 进入阶段 1+2 时会读取这个 result 并写 state。

        finally 清掉 _background_compaction_tasks[thread_id] 引用，防止泄漏。
        异常被 catch 后写 None，下次检测看到 None 会跳过（不写 pending，保持原 context）。
        """
        try:
            s_new = await self._try_compact_react(compact_context, thread_id=thread_id)
            self._background_compaction_results[thread_id] = s_new
            if s_new:
                # 阶段 2 完成后立即把 summary 内容写到 thinking_chain，
                # 便于排查 LLM 实际产出的摘要质量（不依赖阶段 4 是否触发）
                self._write_thinking(
                    thread_id,
                    f"[react_compact_summary]: chars={len(s_new)}\n{s_new}"
                )
        except Exception as e:
            self.logger.warning(f"[后台 ReAct 压缩] {thread_id} 失败: {e}")
            self._background_compaction_results[thread_id] = None
        finally:
            self._background_compaction_tasks.pop(thread_id, None)

    async def _create_graph_process_files(self):
        """
        处理文件图工作流
        """
        workflow = StateGraph(FileParseState)

        @node_guard("split_files_node", logger=self.logger)
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

        @node_guard("file_process_node", logger=self.logger)
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

            has_image = any(
                isinstance(item, dict) and item.get("type") == "image_url"
                for item in file
            )
            if not has_image:
                # 文本 和 文档（默认不传文档内图片，仅保留占位符）
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

            resp_str = get_message_content_string(resp)

            return {"parsed_results": [resp_str]}

        @node_guard("aggregator_node", logger=self.logger)
        async def aggregator_node(state: FileParseState):
            """
            文件处理结果聚合节点
            """
            parsed_results = state["parsed_results"]

            combined_content = "\n".join(parsed_results) if parsed_results else ""
            if not combined_content.strip():
                combined_content = ""

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


    async def _create_graph_core2(self):
        """
        工程化图工作流对象:
        usr_input -> input_parse -> context_assembly
        -> agent_node -> tool_node --↗
                   ↘--> final_node
        """
        TOOL_CALL_TIMES = 50
        RETRY_TIMES = 3

        # ReAct 流程压缩节拍：4 阶段循环
        #   阶段 1 检测：tool_call_times >= DETECTION_MIN_ROUNDS（默认 4）且
        #     最近 4 轮的 chars >= MIN_CHARS（默认 10000）
        #   阶段 2 压缩：同步 await LLM，结果存 state（不立即替换）
        #   阶段 3 等待：等 REPLACE_AFTER（默认 2）轮 tool_calls，
        #     agent 继续用旧 context 推进（不打断工作流）
        #   阶段 4 替换：tool_call_times 达到 replace_at 时重组 context =
        #     memory + imp_ipt + summary + 最近 KEEP_LOOPS（默认 2）轮原文；
        #     清 pending 字段后回到阶段 1 重新检测（循环）
        REACT_KEEP_LOOPS = 2
        REACT_COMPACT_DETECTION_MIN_ROUNDS = 5
        # 10000 → ≤4096 tokens
        REACT_COMPACT_MIN_CHARS = 10000


        workflow = StateGraph(ChatStateCore2)

        @node_guard("input_parse_node", logger=self.logger)
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
            history_memory: SystemMessage = self.memory_manager.read_layered_context(thread_id)

            # 如果在这里中断时，续接时注入的中断原因 SystemMessage 需要加到 input_msg 最前面，否则 LLM 看不到
            for msg in messages:
                if isinstance(msg, SystemMessage) and "中断" in msg.content:
                    input_msg.insert(0, msg)
                    break

            input_msg.append(history_memory)
            # input_msg.extend(history_messages)
            input_msg.append(files_input)
            input_msg.extend(user_input)
            self.logger.debug(f"会话 {thread_id} 文件输入:{files_input}")
            self.logger.debug(f"会话 {thread_id} 用户输入:{user_input}")

            imp_ipt_chunks = []
            interrupt_check_interval = 4
            interrupt_check_counter = 0
            async for chunk in self.llm_imp_ipt.astream({"messages": input_msg}):
                imp_ipt_chunks.append(chunk)
                interrupt_check_counter += 1
                if interrupt_check_counter >= interrupt_check_interval:
                    interrupt_check_counter = 0
                    await self.check_and_trigger_interrupt(thread_id)
            imp_ipt = self._merge_chunks(imp_ipt_chunks)

            imp_ipt = filter_thinking_content(imp_ipt)

            imp_ipt_content = imp_ipt.content
            imp_ipt_additional_kwargs = imp_ipt.additional_kwargs
            imp_ipt_id = imp_ipt.id
            imp_ipt_response_metadata = imp_ipt.response_metadata

            imp_ipt = HumanMessage(
                content=imp_ipt_content,
                additional_kwargs={
                    **imp_ipt_additional_kwargs,
                    "imp_ipt": True,
                },
                id=imp_ipt_id,
                response_metadata=imp_ipt_response_metadata,
            )

            self._write_thinking(thread_id, f"--------------------------------------------")
            # 思维链日志：imp_ipt 单独输出（input_parse_node 优化后的本轮用户意图）
            self._write_thinking(thread_id, f"[imp_ipt]:\n{format_thinking_chain([imp_ipt])}")

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

        @node_guard("context_assembly_node", logger=self.logger)
        async def context_assembly_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]

            context = []
            tool_results = state["memory_tool_results"] if state["memory_tool_results"] else []

            if not state["context"]:
                # 新会话：组装 memory + imp_ipt，逐条打印（不一次性 dump 整段 context）
                memory_message :SystemMessage = self.memory_manager.read_layered_context(thread_id)
                context.append(memory_message)
                self._write_thinking(thread_id, f"[react_context] +memory:\n{format_thinking_chain([memory_message])}")

                imp_ipt_msg: HumanMessage = state["imp_ipt"]
                context.append(imp_ipt_msg)
                self._write_thinking(thread_id, f"[react_context] +imp_ipt:\n{format_thinking_chain([imp_ipt_msg])}")
            else:
                # 续接：state["context"] 已存在（之前已逐条打印过），只打印新增的 cycle_msg
                context = state["context"]

                cycle_msg = await self._get_current_round_conversation_cycling(state["messages"])
                for msg in cycle_msg:
                    context.append(msg)
                    # 逐条打印：随着 context 更新，每条 AIMessage / ToolMessage / HumanMessage 单独写入一行
                    self._write_thinking(thread_id, f"[react_context] +msg:\n{format_thinking_chain([msg])}")

                    if isinstance(msg, ToolMessage):
                        content_string = get_message_content_string(msg)
                        tool_results.append(content_string)

            # 不再一次性 dump 整个 context（已逐条打印）

            # ✨ ReAct 流程压缩（4 阶段循环）：
            #   阶段 4：替换 pending 的压缩摘要 → 清 pending → 更新 last_compact_at
            #   阶段 1+2：检测 → 同步 LLM 压缩 → 存 pending（不立即替换）
            #   阶段 3：什么都不做（agent 继续用旧 context 推进，x 轮不打扰）
            # 阶段 4 完成后回到阶段 1 重启循环
            tool_call_times = state.get("tool_call_times", 0)
            last_compact_at = state.get("last_compact_at_tool_calls", 0)
            pending_summary = state.get("pending_compaction_summary")
            pending_replace_at = state.get("pending_compaction_replace_at")

            updates: Dict[str, Any] = {
                "context": context,
                "memory_tool_results": tool_results,
            }

            # ============ 阶段 4：替换 pending 压缩 ============
            # ⚠️ 触发条件用「当前完整 loop 数 ≥ pending_replace_at」,不依赖 tool_call_times:
            # 并行调 1-3 个工具会让 tool_call_times 一次 +1~3,导致 "+2" 不稳定等价于"等 2 轮"。
            # loop 数版本无论并行多少次都稳定:等 N 个新完整 AIMessage+ToolMessages pair 才替换。
            if (
                pending_summary is not None
                and pending_replace_at is not None
            ):
                current_complete_loops = self._find_complete_tool_loops(context)
                if len(current_complete_loops) >= pending_replace_at:
                    complete_loops = current_complete_loops
                    keep_loops = (
                        complete_loops[-REACT_KEEP_LOOPS:]
                        if len(complete_loops) >= REACT_KEEP_LOOPS
                        else complete_loops
                    )
                    new_context = self._build_compaction_draft(context, pending_summary, keep_loops)
                    if new_context is not None:
                        self._write_thinking(
                            thread_id,
                            f"[react_context_after_compact]: "
                            f"compact_loops={len(complete_loops) - len(keep_loops)}, "
                            f"keep_loops={len(keep_loops)}, "
                            f"replace_after={REACT_KEEP_LOOPS}\n"
                            f"{format_thinking_chain(new_context)}"
                        )
                        updates["context"] = new_context
                        updates["last_compact_at_tool_calls"] = tool_call_times
                        updates["last_compacted_loops_count"] = len(complete_loops) - len(keep_loops)
                        updates["pending_compaction_summary"] = None
                        updates["pending_compaction_replace_at"] = None
                        updates["context_summary_text"] = pending_summary
                        # 更新 last_compact_at 后重新计算上下文，供阶段 1 使用
                        last_compact_at = tool_call_times
                        context = new_context

            # ============ 阶段 1+2：检测 + 触发后台 LLM 压缩 ============
            # 仅在无 pending 时触发（一次只跑一个压缩周期，避免堆积）
            # 后台 LLM 调用的 5-10s 不阻塞主工作流推进（asyncio.create_task）
            if updates.get("pending_compaction_summary") is None and pending_summary is None:
                # 优先消费已完成的后台任务结果（之前 iteration 触发的后台压缩）
                if thread_id in self._background_compaction_results:
                    s_new = self._background_compaction_results.pop(thread_id)
                    if s_new is not None:
                        updates["pending_compaction_summary"] = s_new
                        # ⚠️ 替换阈值用当前完整 loop 数 + REACT_KEEP_LOOPS,
                        # 不基于 tool_call_times (并行调用会一次 +1~3 不稳定)
                        current_complete_loops_for_replace = self._find_complete_tool_loops(context)
                        updates["pending_compaction_replace_at"] = (
                            len(current_complete_loops_for_replace) + REACT_KEEP_LOOPS
                        )
                elif thread_id not in self._background_compaction_tasks:
                    # 无 running 任务 → 阶段 1 检测
                    complete_loops = self._find_complete_tool_loops(context)
                    if len(complete_loops) >= REACT_COMPACT_DETECTION_MIN_ROUNDS:
                        recent_n = complete_loops[-REACT_COMPACT_DETECTION_MIN_ROUNDS:]
                        recent_n_indices = {idx for loop in recent_n for idx in loop}
                        recent_n_msgs = [m for i, m in enumerate(context) if i in recent_n_indices]
                        recent_chars = self._content_chars(recent_n_msgs)
                    else:
                        recent_chars = 0

                    if self._should_detect_compact(
                        tool_call_times=tool_call_times,
                        last_compact_at=last_compact_at,
                        has_pending_compaction=False,
                        recent_chars=recent_chars,
                        min_chars=REACT_COMPACT_MIN_CHARS,
                        detection_min_rounds=REACT_COMPACT_DETECTION_MIN_ROUNDS,
                        complete_loop_count=len(complete_loops),
                    ):
                        keep_loops = (
                            complete_loops[-REACT_KEEP_LOOPS:]
                            if len(complete_loops) >= REACT_KEEP_LOOPS
                            else complete_loops
                        )
                        keep_indices = {idx for loop in keep_loops for idx in loop}
                        compact_context = [
                            msg for i, msg in enumerate(context)
                            if i not in keep_indices
                        ]

                        # 阶段 2：触发后台 LLM 压缩（asyncio.create_task 不阻塞当前 iteration）
                        task = asyncio.create_task(
                            self._background_compact_react(thread_id, compact_context)
                        )
                        self._background_compaction_tasks[thread_id] = task

            return updates

        @node_guard("agent_node", logger=self.logger)
        async def agent_node(state: ChatStateCore2, config: RunnableConfig):
            """AI 代理节点，处理用户消息并决定是否调用工具"""
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            input_msg = state["context"]

            if state["memory_tool_calls"]:
                tool_calls = state["memory_tool_calls"]
            else:
                tool_calls = []

            tool_call_times = state["tool_call_times"]

            if tool_call_times >= TOOL_CALL_TIMES:
                interrupt_msg = SystemMessage(content=f"已超过{TOOL_CALL_TIMES}次调用工具次数，请停止工具调用提前结束对话")
                input_msg.append(interrupt_msg)

            response_chunks = []
            # agent_node 输出可能含 tool_calls，中段 interrupt 检查不能打断正常 tool 决策：
            # 8 chunks 间隔对应 ~160 tokens，对 agent 决策流（通常 200-500 tokens 总长）
            # 足够在 1-2s 内感知中断，又不会在单次决策里反复打断。
            interrupt_check_interval = 4
            interrupt_check_counter = 0
            async for chunk in self.agent_llm.astream({"messages": input_msg}):
                response_chunks.append(chunk)
                interrupt_check_counter += 1
                if interrupt_check_counter >= interrupt_check_interval:
                    interrupt_check_counter = 0
                    await self.check_and_trigger_interrupt(thread_id)
            response = self._merge_chunks(response_chunks)

            # 符合ToolNode节点的AIMessage(REASONING)
            # ⚠️ 必须先 parse 再 filter：M3 偶发只把 tool_call 序列化到 content、不填结构化 tool_calls 字段
            # （如 `<tool_calls>[{"name":"done","args":{}}]</tool_calls>`），filter 第 5 条会把整段剥掉
            # → parse 拿空 content → 走 `if not raw_content: return ai_message` 兜底 → tool_calls=[] →
            # agent_no_tool_call_retries 注入 SysMsg，最多 3 次后才强制 final_node（实测「你好」轻量对话
            # 也会触发 2 次空转，浪费 4-6s）。调换顺序后：parse 拿完整 content 提取 tool_calls + 清掉
            # <tool_calls> 文本块 → filter 后 content 干净（清思考标签 / 孤立 debris / 方括号包装）。
            format_response = self._parse_content_to_tool_calls(response)
            format_response = filter_thinking_content(format_response)

            # 思维链日志：agent_node 输出（带 tool_calls 的 AIMessage）
            self._write_thinking(thread_id, f"[agent_node_out]:\n{format_thinking_chain([format_response])}")

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

                # ctime 保底：ctime 不接受任何参数。
                if tool_name == "ctime":
                    extra = dict(args)
                    if extra:
                        self.logger.warning(f"ctime 不应有任何参数，已清空: extra={extra}")
                        tool_call["args"] = {}

                # 不再注入 session_id 到 args（sid 走 X-Session-Id header 透传；
                # 注入 args 会污染 tool_call 历史，让 LLM 误以为 cmd/code 接受 session_id）
                tool_calls.append(tool_call)

                counts += 1

            tool_call_times += counts

            return {
                "messages": [format_response],
                "tool_call_times": tool_call_times,
                "memory_tool_calls": tool_calls,
            }

        tool_execution_node = PermissionedToolNode(tools=self.tools)  # 官方 ToolNode 子类，权限审批走 awrap_tool_call hook

        @node_guard("should_end_node", logger=self.logger)
        async def should_end_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            context = state["context"]

            last_message = state["messages"][-1]
            response = await self.should_end_llm.ainvoke({"messages": [last_message]})
            content = str(response.content)

            # 思维链日志：should_end 单独输出（决策点）
            self._write_thinking(thread_id, f"[should_end_in]:\n{format_thinking_chain([last_message])}")

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

        @node_guard("final_node", logger=self.logger)
        async def final_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]

            self.logger.debug(f"会话 {thread_id} 思维链打回重试次数 {state["should_end_retry_times"]}")

            await self.check_and_trigger_interrupt(thread_id)

            # imp_ipt 在 system 层独占最高注意力位；{imp_ipt} 占位由 _final_system_template.format() 注入。
            context = list(state["context"])

            # 思维链日志：final_node 输入 context（imp_ipt 被 pop 之前的完整 context）
            self._write_thinking(thread_id, f"[final_node_in_context]:\n{format_thinking_chain(context)}")

            imp_ipt_idx = self._find_imp_ipt_idx(context)
            if imp_ipt_idx is not None:
                context.pop(imp_ipt_idx)

            imp_ipt_msg: HumanMessage = state["imp_ipt"]
            # 防止占位符出错
            escaped_imp_ipt = imp_ipt_msg.content.replace("{", "{{").replace("}", "}}")
            system_prompt = self._final_system_template.format(imp_ipt=escaped_imp_ipt)

            response_chunks = []
            interrupt_check_interval = 8
            interrupt_check_counter = 0
            final_messages = [
                SystemMessage(content=system_prompt),
                *context,
                HumanMessage(content="请生成回复"),
            ]
            async for chunk in self.llm_core.astream(final_messages):
                response_chunks.append(chunk)
                interrupt_check_counter += 1
                if interrupt_check_counter >= interrupt_check_interval:
                    interrupt_check_counter = 0
                    await self.check_and_trigger_interrupt(thread_id)
            response = self._merge_chunks(response_chunks)

            response = filter_thinking_content( response)

            # 思维链日志：final_node 输出（最终回复）
            self._write_thinking(thread_id, f"[final_node_out]:\n{format_thinking_chain([response])}")
            self._write_thinking(thread_id, f"--------------------------------------------")

            self.logger.debug(f"会话 {thread_id} 最终回复: {response}")

            # AIMessage字段支持解包复制
            response_dict = dict(response)
            response_dict["additional_kwargs"] = {**response.additional_kwargs, "type": AIMessageType.SUMMARY.value}

            response_better = AIMessage(**response_dict)

            # 提取AI回复内容用于memory
            memory_ai_response = get_message_content_string(response_better)

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
            has_tool_calls = (
                isinstance(last_message, AIMessage)
                and hasattr(last_message, "tool_calls")
                and bool(last_message.tool_calls)
            )
            decision = "tool_execution_node" if has_tool_calls else "should_end_node"
            return decision

        def route_should_end(state: ChatStateCore2) -> str:
            """should_end_node 返回 end 则去 final_node，返回 retry 则回 context_assembly_node"""
            decision = state.get("should_end_decision", "end")
            next_node = "context_assembly_node" if decision == "retry" else "final_node"
            return next_node

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
    
    async def _create_graph_improved(self):
        """
        改进版图工作流对象（vs _create_graph_core2）：
        - 去掉了 should_end_node（agent 无 tool_calls → 直进 final_node）
        - 后续会加 done tool + final_quality_check_node（占位）

        工程化图工作流对象:
        usr_input -> input_parse -> context_assembly
        -> agent_node -> tool_node --↗
                   ↘--> final_node
        """
        TOOL_CALL_TIMES = 50
        RETRY_TIMES = 3  # agent 无 tool_calls 连续失败的最大重试次数（超 3 次强制 final_node）

        # ReAct 流程压缩节拍：4 阶段循环
        #   阶段 1 检测：tool_call_times >= DETECTION_MIN_ROUNDS（默认 4）且
        #     最近 4 轮的 chars >= MIN_CHARS（默认 10000）
        #   阶段 2 压缩：同步 await LLM，结果存 state（不立即替换）
        #   阶段 3 等待：等 REPLACE_AFTER（默认 2）轮 tool_calls，
        #     agent 继续用旧 context 推进（不打断工作流）
        #   阶段 4 替换：tool_call_times 达到 replace_at 时重组 context =
        #     memory + imp_ipt + summary + 最近 KEEP_LOOPS（默认 2）轮原文；
        #     清 pending 字段后回到阶段 1 重新检测（循环）
        REACT_KEEP_LOOPS = 2
        REACT_COMPACT_DETECTION_MIN_ROUNDS = 5
        # 10000 → ≤4096 tokens
        REACT_COMPACT_MIN_CHARS = 10000


        workflow = StateGraph(ChatStateCore2)

        @node_guard("input_parse_node", logger=self.logger)
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
            history_memory: SystemMessage = self.memory_manager.read_layered_context(thread_id)

            # 如果在这里中断时，续接时注入的中断原因 SystemMessage 需要加到 input_msg 最前面，否则 LLM 看不到
            for msg in messages:
                if isinstance(msg, SystemMessage) and "中断" in msg.content:
                    input_msg.insert(0, msg)
                    break

            input_msg.append(history_memory)
            # input_msg.extend(history_messages)
            input_msg.append(files_input)
            input_msg.extend(user_input)
            self.logger.debug(f"会话 {thread_id} 文件输入:{files_input}")
            self.logger.debug(f"会话 {thread_id} 用户输入:{user_input}")

            imp_ipt_chunks = []
            interrupt_check_interval = 4
            interrupt_check_counter = 0
            async for chunk in self.llm_imp_ipt.astream({"messages": input_msg}):
                imp_ipt_chunks.append(chunk)
                interrupt_check_counter += 1
                if interrupt_check_counter >= interrupt_check_interval:
                    interrupt_check_counter = 0
                    await self.check_and_trigger_interrupt(thread_id)
            imp_ipt = self._merge_chunks(imp_ipt_chunks)

            imp_ipt = filter_thinking_content(imp_ipt)

            imp_ipt_content = imp_ipt.content
            imp_ipt_additional_kwargs = imp_ipt.additional_kwargs
            imp_ipt_id = imp_ipt.id
            imp_ipt_response_metadata = imp_ipt.response_metadata

            imp_ipt = HumanMessage(
                content=imp_ipt_content,
                additional_kwargs={
                    **imp_ipt_additional_kwargs,
                    "imp_ipt": True,
                },
                id=imp_ipt_id,
                response_metadata=imp_ipt_response_metadata,
            )

            self._write_thinking(thread_id, f"--------------------------------------------")
            # 思维链日志：imp_ipt 单独输出（input_parse_node 优化后的本轮用户意图）
            self._write_thinking(thread_id, f"[imp_ipt]:\n{format_thinking_chain([imp_ipt])}")

            return {
                "imp_ipt": imp_ipt,
                "context": [],
                "memory_user_message": imp_ipt_content,
                "memory_tool_results": [],
                "memory_tool_calls": [],
                "memory_ai_response": None,
                "tool_call_times": 0,
                "context_summary_text": "",
                "last_compact_at_tool_calls": 0,
                "agent_no_tool_call_retries": 0,  # 跨轮对话清零,避免上一轮残留 retry 计数撞上限
                "done_cycle_detected": False,  # 新一轮对话清零 done 标志
            }

        @node_guard("context_assembly_node", logger=self.logger)
        async def context_assembly_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]

            context = []
            tool_results = state["memory_tool_results"] if state["memory_tool_results"] else []
            cycle_msg: List[BaseMessage] = []
            is_done_cycle = False

            updates: Dict[str, Any] = {}

            if not state["context"]:
                # 新会话：组装 memory + imp_ipt，逐条打印（不一次性 dump 整段 context）
                memory_message :SystemMessage = self.memory_manager.read_layered_context(thread_id)
                context.append(memory_message)
                self._write_thinking(thread_id, f"[react_context] +memory:\n{format_thinking_chain([memory_message])}")

                imp_ipt_msg: HumanMessage = state["imp_ipt"]
                context.append(imp_ipt_msg)
                self._write_thinking(thread_id, f"[react_context] +imp_ipt:\n{format_thinking_chain([imp_ipt_msg])}")

                updates["context"] = context
            else:
                # context 只打印新增的 cycle_msg
                context = list(state["context"])

                cycle_msg = await self._get_current_round_conversation_cycling(state["messages"])

                # ✨ done 信号检测:agent 调 done 后,本轮 cycle(AIMessage + 全部 ToolMessages)不进 context
                # —— done 是结束标志,没有信息价值;若一起留在 context 会污染后续轮次 LLM 输入
                last_ai_in_cycle = next(
                    (m for m in reversed(cycle_msg) if isinstance(m, AIMessage)), None
                )
                is_done_cycle = (
                    last_ai_in_cycle is not None
                    and any(
                        tc.get("name") == "done"
                        for tc in (getattr(last_ai_in_cycle, "tool_calls", None) or [])
                    )
                )

                if is_done_cycle:
                    self._write_thinking(
                        thread_id,
                        f"[react_context] done-signal cycle: skip {len(cycle_msg)} msgs from context "
                        f"(AIMessage with done tool_call): {cycle_msg}"
                    )
                else:
                    for msg in cycle_msg:
                        context.append(msg)
                        # 逐条打印：随着 context 更新，每条 AIMessage / ToolMessage / HumanMessage 单独写入一行
                        self._write_thinking(thread_id, f"[react_context] +msg:\n{format_thinking_chain([msg])}")

                        if isinstance(msg, ToolMessage):
                            content_string = get_message_content_string(msg)
                            tool_results.append(content_string)

                    updates["context"] = context
                    updates["memory_tool_results"] = tool_results

                    # ReAct 压缩用 state 字段（cycle_msg 整个迭代过程值不变，提到循环外算一次）
                    # ✨ ReAct 流程压缩（4 阶段循环）：
                    #   阶段 4：替换 pending 的压缩摘要 → 清 pending → 更新 last_compact_at
                    #   阶段 1+2：检测 → 同步 LLM 压缩 → 存 pending（不立即替换）
                    #   阶段 3：什么都不做（agent 继续用旧 context 推进，x 轮不打扰）
                    #   阶段 4 完成后回到阶段 1 重启循环
                    #
                    # ⚠️ done cycle 已检测到 → 跳过整个 ReAct 压缩段：
                    #   1) 阶段 4 替换会把"用于 ongoing 循环"的摘要灌给 final_node,丢信息影响回复质量
                    #   2) 阶段 2 后台 asyncio 任务无人消费(graph 直接退出),会泄漏到 _background_compaction_results
                    #   3) final_node 只需一次性用 context 生成 user-facing reply,不需要为后续循环做压缩
                    # （本分支 is_done_cycle=False 时才进入,守卫隐式生效）
                    tool_call_times = state.get("tool_call_times", 0)
                    last_compact_at = state.get("last_compact_at_tool_calls", 0)
                    pending_summary = state.get("pending_compaction_summary")
                    pending_replace_at = state.get("pending_compaction_replace_at")
                    # 阶段 4 在本轮循环里只能跑一次：成功后 pending_summary 必须本地置 None,
                    # 防止 iteration 2+ 重复调 _build_compaction_draft 在已压缩 context 上再压一次
                    # 阶段 1+2 同理:首次消费结果/触发后台任务后,后续 iteration 不再重复跑(避免重复调 _find_complete_tool_loops 等)
                    compression_handled_this_round = False

                    # ============ 阶段 4：替换 pending 压缩 ============
                    # ⚠️ 触发条件用「当前完整 loop 数 ≥ pending_replace_at」,不依赖 tool_call_times:
                    # 并行调 1-3 个工具会让 tool_call_times 一次 +1~3,导致 "+2" 不稳定等价于"等 2 轮"。
                    # loop 数版本无论并行多少次都稳定:等 N 个新完整 AIMessage+ToolMessages pair 才替换。
                    if (
                        not compression_handled_this_round
                        and pending_summary is not None
                        and pending_replace_at is not None
                    ):
                        # 当前完整 loop 数（context 在 for 循环里逐 iteration 累加，每次 append 后重算一次）
                        current_complete_loops = self._find_complete_tool_loops(context)
                        if len(current_complete_loops) >= pending_replace_at:
                            complete_loops = current_complete_loops
                            keep_loops = (
                                complete_loops[-REACT_KEEP_LOOPS:]
                                if len(complete_loops) >= REACT_KEEP_LOOPS
                                else complete_loops
                            )
                            new_context = self._build_compaction_draft(context, pending_summary, keep_loops)
                            if new_context is not None:
                                self._write_thinking(
                                    thread_id,
                                    f"[react_context_after_compact]: "
                                    f"compact_loops={len(complete_loops) - len(keep_loops)}, "
                                    f"keep_loops={len(keep_loops)}, "
                                    f"replace_after={REACT_KEEP_LOOPS}\n"
                                    f"{format_thinking_chain(new_context)}"
                                )
                                updates["context"] = new_context
                                updates["last_compact_at_tool_calls"] = tool_call_times
                                updates["last_compacted_loops_count"] = len(complete_loops) - len(keep_loops)
                                updates["pending_compaction_summary"] = None
                                updates["pending_compaction_replace_at"] = None
                                updates["context_summary_text"] = pending_summary
                                # 更新 last_compact_at 后重新计算上下文，供阶段 1 使用
                                last_compact_at = tool_call_times
                                context = new_context
                                # 关键:本地 pending_summary 也清掉,iteration 2+ 不再触发重复压缩
                                pending_summary = None
                                pending_replace_at = None
                                compression_handled_this_round = True

                    # ============ 阶段 1+2：检测 + 触发后台 LLM 压缩 ============
                    # 仅在无 pending 时触发（一次只跑一个压缩周期，避免堆积）
                    # 后台 LLM 调用的 5-10s 不阻塞主工作流推进（asyncio.create_task）
                    # 同样只在本轮循环里跑一次：消费已完成结果/触发后台任务后,iteration 2+ 不再重复跑
                    if (
                        not compression_handled_this_round
                        and updates.get("pending_compaction_summary") is None
                        and pending_summary is None
                    ):
                        # 优先消费已完成的后台任务结果（之前 iteration 触发的后台压缩）
                        if thread_id in self._background_compaction_results:
                            s_new = self._background_compaction_results.pop(thread_id)
                            if s_new is not None:
                                updates["pending_compaction_summary"] = s_new
                                # ⚠️ 替换阈值用当前完整 loop 数 + REACT_KEEP_LOOPS,
                                # 不基于 tool_call_times (并行调用会一次 +1~3 不稳定)
                                current_complete_loops_for_replace = self._find_complete_tool_loops(context)
                                updates["pending_compaction_replace_at"] = (
                                    len(current_complete_loops_for_replace) + REACT_KEEP_LOOPS
                                )
                                compression_handled_this_round = True
                        elif thread_id not in self._background_compaction_tasks:
                            # 无 running 任务 → 阶段 1 检测
                            complete_loops = self._find_complete_tool_loops(context)
                            if len(complete_loops) >= REACT_COMPACT_DETECTION_MIN_ROUNDS:
                                recent_n = complete_loops[-REACT_COMPACT_DETECTION_MIN_ROUNDS:]
                                recent_n_indices = {idx for loop in recent_n for idx in loop}
                                recent_n_msgs = [m for i, m in enumerate(context) if i in recent_n_indices]
                                recent_chars = self._content_chars(recent_n_msgs)
                            else:
                                recent_chars = 0

                            if self._should_detect_compact(
                                tool_call_times=tool_call_times,
                                last_compact_at=last_compact_at,
                                has_pending_compaction=False,
                                recent_chars=recent_chars,
                                min_chars=REACT_COMPACT_MIN_CHARS,
                                detection_min_rounds=REACT_COMPACT_DETECTION_MIN_ROUNDS,
                                complete_loop_count=len(complete_loops),
                            ):
                                keep_loops = (
                                    complete_loops[-REACT_KEEP_LOOPS:]
                                    if len(complete_loops) >= REACT_KEEP_LOOPS
                                    else complete_loops
                                )
                                keep_indices = {idx for loop in keep_loops for idx in loop}
                                compact_context = [
                                    msg for i, msg in enumerate(context)
                                    if i not in keep_indices
                                ]

                                # 阶段 2：触发后台 LLM 压缩（asyncio.create_task 不阻塞当前 iteration）
                                task = asyncio.create_task(
                                    self._background_compact_react(thread_id, compact_context)
                                )
                                self._background_compaction_tasks[thread_id] = task
                                # 后台任务已注册,后续 iteration 自然走 elif 分支,这里置标志保险
                                compression_handled_this_round = True

            # done cycle 处理:从 state["messages"] 删除(前端 refresh 拿不到 done tool_call)
            # —— context 跳过的同时,也不保留在消息历史里;前端无需改 refresh 逻辑
            # 同步置 done_cycle_detected = True,让 route_after_context_assembly 走 final_node
            # (因为 RemoveMessage 后 AIMessage(done) 已不在 messages,route 必须看 flag)
            if is_done_cycle and cycle_msg:
                # 区分单 done vs 并发调度(done 跟其他 tool 并存同一 AIMessage):
                #   - 单 done:tool_calls=[done] → 整轮清理(AIMessage + TM(done_result) 都没信息)
                #   - 并发调度:tool_calls=[search, done] → 只删 TM(done_result),
                #     AIMessage(其他 tool_calls 还在)和其他 TM(search_result) 保留
                #     —— F5 刷新后还能看到"搜了 XXX 拿到 YYY"的上下文
                # (前端 mergeToolCallStart 已过滤 done 显示,所以保留 AIMessage 不会污染 UI)
                tool_calls_in_ai = getattr(last_ai_in_cycle, "tool_calls", None) or []
                is_done_only = (
                    len(tool_calls_in_ai) == 1
                    and tool_calls_in_ai[0].get("name") == "done"
                )

                if is_done_only:
                    # 单 done:整轮清理
                    updates["messages"] = [
                        RemoveMessage(id=m.id) for m in cycle_msg if m.id
                    ]
                else:
                    # 并发调度:只删匹配 done tool_call_id 的 ToolMessage,
                    # AIMessage(含其他 tool_calls)和其他 TM 全部保留
                    done_call_id = next(
                        (tc.get("id") for tc in tool_calls_in_ai if tc.get("name") == "done"),
                        None,
                    )
                    updates["messages"] = [
                        RemoveMessage(id=m.id) for m in cycle_msg
                        if m.id
                        and isinstance(m, ToolMessage)
                        and m.tool_call_id == done_call_id
                    ]
                updates["done_cycle_detected"] = True
            else:
                # 非 done cycle 显式置 False,避免上一轮 done 残留误判
                updates["done_cycle_detected"] = False

            return updates

        @node_guard("agent_node", logger=self.logger)
        async def agent_node(state: ChatStateCore2, config: RunnableConfig):
            """AI 代理节点（_create_graph_improved）：用 done tool 替代 'output Done 单词' 收尾 + 走 agent_llm_with_done（bind 了 done tool）"""
            thread_id = config["configurable"]["thread_id"]
            await self.check_and_trigger_interrupt(thread_id)

            input_msg = state["context"]

            if state["memory_tool_calls"]:
                tool_calls = state["memory_tool_calls"]
            else:
                tool_calls = []

            tool_call_times = state["tool_call_times"]

            if tool_call_times >= TOOL_CALL_TIMES:
                interrupt_msg = SystemMessage(content=f"已超过{TOOL_CALL_TIMES}次调用工具次数，请停止工具调用提前结束对话")
                input_msg.append(interrupt_msg)

            response_chunks = []
            # agent_node 输出可能含 tool_calls，中段 interrupt 检查不能打断正常 tool 决策：
            # 8 chunks 间隔对应 ~160 tokens，对 agent 决策流（通常 200-500 tokens 总长）
            # 足够在 1-2s 内感知中断，又不会在单次决策里反复打断。
            interrupt_check_interval = 4
            interrupt_check_counter = 0
            async for chunk in self.agent_llm_with_done.astream({"messages": input_msg}):
                response_chunks.append(chunk)
                interrupt_check_counter += 1
                if interrupt_check_counter >= interrupt_check_interval:
                    interrupt_check_counter = 0
                    await self.check_and_trigger_interrupt(thread_id)
            response = self._merge_chunks(response_chunks)

            # 符合ToolNode节点的AIMessage(REASONING)
            # ⚠️ 必须先 parse 再 filter：M3 偶发只把 tool_call 序列化到 content、不填结构化 tool_calls 字段
            # （如 `<tool_calls>[{"name":"done","args":{}}]</tool_calls>`），filter 第 5 条会把整段剥掉
            # → parse 拿空 content → 走 `if not raw_content: return ai_message` 兜底 → tool_calls=[] →
            # agent_no_tool_call_retries 注入 SysMsg，最多 3 次后才强制 final_node（实测「你好」轻量对话
            # 也会触发 2 次空转，浪费 4-6s）。调换顺序后：parse 拿完整 content 提取 tool_calls + 清掉
            # <tool_calls> 文本块 → filter 后 content 干净（清思考标签 / 孤立 debris / 方括号包装）。
            format_response = self._parse_content_to_tool_calls(response)
            format_response = filter_thinking_content(format_response)

            # 思维链日志：agent_node 输出（带 tool_calls 的 AIMessage）
            self._write_thinking(thread_id, f"[agent_node_out]:\n{format_thinking_chain([format_response])}")

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

                # ctime 保底：ctime 不接受任何参数。
                if tool_name == "ctime":
                    extra = dict(args)
                    if extra:
                        self.logger.warning(f"ctime 不应有任何参数，已清空: extra={extra}")
                        tool_call["args"] = {}

                if tool_name == "done":
                    extra = dict(args)
                    if extra:
                        self.logger.warning(f"done 不应有任何参数，已清空: extra={extra}")
                        tool_call["args"] = {}

                # 不再注入 session_id 到 args（sid 走 X-Session-Id header 透传；
                # 注入 args 会污染 tool_call 历史，让 LLM 误以为 cmd/code 接受 session_id）
                tool_calls.append(tool_call)

                counts += 1

            tool_call_times += counts

            # 兜底 retry：agent 输出的 AIMessage 没有 tool_calls（LLM 漏调 / 参数格式问题 /
            # 选了 done 但 args 被吃掉），不直接 final_node——注入英文 SysMsg 提示 agent 必须调工具，
            # 走 context_assembly_node → agent_node 重试；连续 RETRY_TIMES 次失败则放弃。
            # 成功调出 tool_calls 时清零（连续失败语义：一次成功即打断失败链）。
            retry_times = state.get("agent_no_tool_call_retries", 0) or 0
            prev_retry = retry_times
            retry_warning_msg = None
            if not format_response.tool_calls:
                retry_times += 1
                if retry_times < RETRY_TIMES:
                    # 业务日志 + 思维链日志：注入 SysMsg 强制重试
                    self.logger.debug(
                        f"会话 {thread_id} agent_node retry {retry_times}/{RETRY_TIMES}: "
                        f"AIMessage 无 tool_calls, 注入英文 SysMsg 强制重试 (prev={prev_retry})"
                    )
                    self._write_thinking(
                        thread_id,
                        f"[agent_node_retry]: {retry_times}/{RETRY_TIMES}, "
                        f"has_tool_calls=False, prev={prev_retry}, action=inject_warning"
                    )
                    retry_warning_msg = SystemMessage(
                        content=(
                            "[Warning] Your previous response did not contain a valid tool call. "
                            "You must invoke at least one tool — either an action tool "
                            "(e.g. cmd, code, find_skill, ctime) or the `done` tool when reasoning is complete. "
                            "Retry now."
                        )
                    )
                else:
                    # 业务 warning + 思维链：达上限, 由 route_agent_output 强制 final_node
                    self.logger.warning(
                        f"会话 {thread_id} agent_node retry 达上限 {RETRY_TIMES}: "
                        f"AIMessage 连续无 tool_calls, 由 route_agent_output 强制 final_node (prev={prev_retry})"
                    )
                    self._write_thinking(
                        thread_id,
                        f"[agent_node_retry]: {retry_times}/{RETRY_TIMES}, "
                        f"has_tool_calls=False, prev={prev_retry}, action=give_up_to_final"
                    )
            else:
                # 成功调出 tool_calls → 清零（一次成功打断连续失败链，给 agent 完整重试预算）
                retry_times = 0
                if prev_retry > 0:
                    # 仅当确实从非零状态清零时才记日志（清零有意义的事件）
                    self.logger.debug(
                        f"会话 {thread_id} agent_node retry 清零: "
                        f"成功调出 tool_calls, 失败链被打破 (prev={prev_retry})"
                    )
                    self._write_thinking(
                        thread_id,
                        f"[agent_node_retry_reset]: prev={prev_retry}, "
                        f"has_tool_calls=True, action=clear_retry_counter"
                    )

            result_messages = (
                [format_response, retry_warning_msg]
                if retry_warning_msg is not None
                else [format_response]
            )

            return {
                "messages": result_messages,
                "tool_call_times": tool_call_times,
                "memory_tool_calls": tool_calls,
                "agent_no_tool_call_retries": retry_times,
            }

        tool_execution_node = PermissionedToolNode(tools=self.tools_with_done)  # 新 graph：含 done tool（用 tool_call name="done" 标记结束）

        @node_guard("final_node", logger=self.logger)
        async def final_node(state: ChatStateCore2, config: RunnableConfig):
            thread_id = config["configurable"]["thread_id"]

            await self.check_and_trigger_interrupt(thread_id)

            # imp_ipt 在 system 层独占最高注意力位；{imp_ipt} 占位由 _final_system_template.format() 注入。
            context = list(state["context"])

            # 思维链日志：final_node 输入 context（imp_ipt 被 pop 之前的完整 context）
            self._write_thinking(thread_id, f"[final_node_in_context]:\n{format_thinking_chain(context)}")

            imp_ipt_idx = self._find_imp_ipt_idx(context)
            if imp_ipt_idx is not None:
                context.pop(imp_ipt_idx)

            imp_ipt_msg: HumanMessage = state["imp_ipt"]
            # 防止占位符出错
            escaped_imp_ipt = imp_ipt_msg.content.replace("{", "{{").replace("}", "}}")
            system_prompt = self._final_system_template.format(imp_ipt=escaped_imp_ipt)

            response_chunks = []
            interrupt_check_interval = 8
            interrupt_check_counter = 0
            final_messages = [
                SystemMessage(content=system_prompt),
                *context,
                HumanMessage(content="请生成回复"),
            ]
            async for chunk in self.llm_core.astream(final_messages):
                response_chunks.append(chunk)
                interrupt_check_counter += 1
                if interrupt_check_counter >= interrupt_check_interval:
                    interrupt_check_counter = 0
                    await self.check_and_trigger_interrupt(thread_id)
            response = self._merge_chunks(response_chunks)

            response = filter_thinking_content( response)

            # 思维链日志：final_node 输出（最终回复）
            self._write_thinking(thread_id, f"[final_node_out]:\n{format_thinking_chain([response])}")
            self._write_thinking(thread_id, f"--------------------------------------------")

            self.logger.debug(f"会话 {thread_id} 最终回复: {response}")

            # AIMessage字段支持解包复制
            response_dict = dict(response)
            response_dict["additional_kwargs"] = {**response.additional_kwargs, "type": AIMessageType.SUMMARY.value}

            response_better = AIMessage(**response_dict)

            # 提取AI回复内容用于memory
            memory_ai_response = get_message_content_string(response_better)

            return {
                "messages": [response_better],
                "memory_ai_response": memory_ai_response,
            }

        workflow.add_node("input_parse_node", input_parse_node)
        workflow.add_node("context_assembly_node", context_assembly_node)
        workflow.add_node("agent_node", agent_node)
        workflow.add_node("tool_execution_node", tool_execution_node)
        workflow.add_node("final_node", final_node)

        def _find_last_agent_ai_message(messages):
            """从 messages 末尾倒序找最近一条 agent 输出的 AIMessage
            (跳过可能被 append 在后面的 SysMsg warning)
            """
            for msg in reversed(messages or []):
                if isinstance(msg, AIMessage):
                    return msg
            return None

        def route_agent_output(state: ChatStateCore2) -> str:
            """根据代理输出决定下一步:
            - AIMessage 含 tool_calls → tool_execution_node
            - AIMessage 无 tool_calls 且 agent_no_tool_call_retries >= RETRY_TIMES → final_node(放弃)
            - AIMessage 无 tool_calls 且 retry < RETRY_TIMES → context_assembly_node(注入英文 SysMsg 重试)
            """
            last_ai = _find_last_agent_ai_message(state.get("messages", []))
            if last_ai is None:
                return "final_node"
            has_tool_calls = bool(getattr(last_ai, "tool_calls", None))
            if has_tool_calls:
                return "tool_execution_node"
            retry_times = state.get("agent_no_tool_call_retries", 0) or 0
            if retry_times >= RETRY_TIMES:
                return "final_node"
            return "context_assembly_node"

        def route_after_context_assembly(state: ChatStateCore2) -> str:
            """新 graph:tool_execution_node / agent_node(retry) → context_assembly_node → 此处决策
            - done_cycle_detected=True(context_assembly 已 RemoveMessage,AIMessage(done) 消失)→ final_node
            - 其他 → agent_node
            """
            # done cycle 已被 RemoveMessage,AIMessage(done) 在 messages 里消失,
            # 必须靠 state 标志位才能识别;flag 由 context_assembly_node 与 is_done_cycle 同源设置
            if state.get("done_cycle_detected"):
                return "final_node"
            return "agent_node"

        workflow.set_entry_point("input_parse_node")
        workflow.add_edge("input_parse_node", "context_assembly_node")

        workflow.add_conditional_edges("context_assembly_node",
            route_after_context_assembly,
            {
                "agent_node": "agent_node",
                "final_node": "final_node",
            }
        )

        workflow.add_conditional_edges("agent_node",
            route_agent_output,
            {
                "tool_execution_node": "tool_execution_node",
                "context_assembly_node": "context_assembly_node",
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

    async def astream(
        self,
        messages: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Any, None]:
        """
        Stream workflow execution.

        Args:
            messages: 三种类型都支持：
                - list[BaseMessage] / BaseMessage：包成 {"messages": ...} 喂给 graph（新对话入口）
                - dict：已是 state update 格式，直接喂给 graph
                  （如 {"messages": [...]} / {"context": [...]} 等任意字段更新）
                - Command：透传给底层 graph（中断续接 / 跨节点跳转等场景用）
            config: Optional configuration

        Yields:
            Workflow execution chunks

        为什么不能强制包成 {"messages": ...}：
        Command 会被 add_messages reducer 当 message 处理，触发
        _convert_to_message(Command) → NotImplementedError。
        """
        from langgraph.types import Command as _Command

        config = {
            **config,
            "recursion_limit": 1000,
        }

        if isinstance(messages, _Command):
            # Command 直接透传，langgraph 内部会按 update/resume/goto 等指令处理
            payload = messages
        elif isinstance(messages, dict):
            # 已是 state update dict，直接传；不重复包成 {"messages": ...}
            payload = messages
        elif messages is None:
            payload = None
        else:
            # BaseMessage list / 单个 message，包成 messages 字段
            payload = {"messages": messages}

        async for e in self.graph.astream_events(payload, config=config):
            yield e
