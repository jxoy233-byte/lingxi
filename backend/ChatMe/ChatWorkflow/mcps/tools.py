"""
额外的本地 tool 工具（不通过 MCP 暴露）

DEPRECATED：本文件目前仅承载 sub_agent 一个工具，该工具已废弃。
- prompt（PROMPT_MAIN_FLOW）已不再向 LLM 暴露 sub_agent
- session.py 里 tools.append(sub_agent) 仍保留注册以兼容潜在遗留调用，但不会再被新 prompt 触发
- 这里仅保留实现 + deprecation 标记，后续清理时可整体删除

用于 agent 工作流中需要特殊处理的工具，如 sub-agent 调度
"""
import asyncio
import re
import os
from typing import Annotated, List

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from ChatMe.ChatWorkflow.decorators import node_guard
from ChatMe.LoggingManager.logging_config import get_logger

logger = get_logger("sub_agent_tools")


def _generate_tool_param_warning(tool_name: str, missing_params: list) -> str:
    """生成工具参数缺失的警告信息"""
    param_list = ", ".join(missing_params)
    logger.warning(f"工具 {tool_name} 缺少参数: {missing_params}")
    return f"[Tool param error] {tool_name} missing required param(s): {param_list}. Check format and retry."


# =============================================================================
# 工具函数
# =============================================================================


def _get_llm_config():
    """获取 LLM 配置"""
    try:
        from ChatMe.ChatMeConfig import get_active_llm_config, get_backup_llm_config
        active = get_active_llm_config()
        if active and active.get("model_name"):
            return active
        backup = get_backup_llm_config()
        if backup and backup.get("model_name"):
            return backup
    except Exception:
        pass

    return {
        "model_name": os.getenv("OPENAI_MODEL_NAME"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL"),
    }


def _get_sub_agent_tools():
    """DEPRECATED: sub_agent 已废弃。获取 sub-agent 可用的工具列表(不含 interrupt)。

    复用 mcps.session 模块级共享 MCP client(同一连接 + 同一 interceptor)。
    """
    try:
        from ChatMe.ChatWorkflow.mcps.session import get_mcp_tools

        try:
            all_tools = get_mcp_tools()
        except RuntimeError:
            logger.warning("MCP 共享 client 未初始化,sub-agent 暂无可用工具")
            return []

        # 过滤掉 interrupt(主 agent 才有权中断)
        tools = [t for t in all_tools if getattr(t, 'name', None) != 'interrupt']
        return tools
    except Exception as e:
        logger.error(f"无法从 MCP server 获取工具列表: {e}")
        return []


# =============================================================================
# Sub-Agent ReAct 工作流
# =============================================================================


def _create_sub_agent_graph(prompt):
    """DEPRECATED: sub_agent 已废弃。创建 sub-agent 的 ReAct 工作流图"""
    from operator import add
    from typing import TypedDict, Annotated

    class SubAgentState(TypedDict):
        messages: Annotated[List, add]

    tools = _get_sub_agent_tools()
    tool_node = ToolNode(tools=tools)

    # 构建 LLM
    llm_config = _get_llm_config()
    model_name = llm_config.get("model_name", "")
    extra_body = {}
    try:
        from ChatMe.ChatWorkflow.config.graph_config import distinguish_extra_body
        extra_body = distinguish_extra_body(model_name)
    except Exception:
        pass
    sub_llm = ChatOpenAI(
        model=model_name,
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("base_url"),
        temperature=0.2,
        max_tokens=16384,
        extra_body=extra_body,
    )
    # 通过 ChatPromptTemplate 注入 system prompt，与主工作流一致
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", prompt),
        MessagesPlaceholder("messages")
    ])
    sub_llm_with_prompt = prompt_template | sub_llm.bind_tools(tools)


    @node_guard("sub_agent.agent_node", logger=logger)
    def agent_node(state :SubAgentState, config):
        from langchain_core.messages import HumanMessage
        session_id = config["configurable"].get("session_id") or ""

        # 首次调用时 messages 为空，需要一个初始 user message 触发对话
        messages = state["messages"]
        if not messages:
            messages = [HumanMessage(content="Please execute the task step by step using the available tools.")]

        response = sub_llm_with_prompt.invoke({"messages": messages})
        response_text = response.content if hasattr(response, "content") else str(response)

        # 清除 MiniMax-M3 生成的 expanded 格式标签，避免泄漏到输出
        cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', response_text, flags=re.DOTALL)
        cleaned = re.sub(r'\]<]minimax\[[>]', '', cleaned)
        cleaned = re.sub(r'\[<invoke \w+>\]\[<(\w+)>(.*?)</\1>\]', r'\2', cleaned)
        response.content = cleaned
        response_text = cleaned

        # 解析 tool_calls：不再手动注入 session_id（走 interceptor → X-Session-Id header）
        tool_calls = _parse_tool_calls(response_text)
        if tool_calls:
            for tc in tool_calls:
                # code 必须有 code 参数
                if tc["name"] == "code" and "code" not in tc["args"]:
                    warning = _generate_tool_param_warning("code", ["code"])
                    tc["args"]["code"] = warning
                    logger.warning(f"会话 {session_id} code 缺少 code 参数: {tc['args']}")
                # cmd 必须有 command 参数
                if tc["name"] == "cmd" and "command" not in tc["args"]:
                    warning = _generate_tool_param_warning("cmd", ["command"])
                    tc["args"]["command"] = warning
                    logger.warning(f"会话 {session_id} cmd 缺少 command 参数: {tc['args']}")
            response.tool_calls = tool_calls

        return {"messages": [response]}

    def should_continue(state):
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and hasattr(last, "tool_calls") and last.tool_calls:
            return "tool_node"
        return END

    workflow = StateGraph(SubAgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tool_node", tool_node)

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"tool_node": "tool_node", END: END}
    )
    workflow.add_edge("tool_node", "agent")

    return workflow.compile()


# 预创建 graph（延迟初始化）
_sub_agent_graph = None


def _get_sub_agent_graph(prompt):
    """DEPRECATED: sub_agent 已废弃。获取或创建 sub-agent graph（单例）"""
    global _sub_agent_graph
    if _sub_agent_graph is None:
        _sub_agent_graph = _create_sub_agent_graph(prompt=prompt)
    return _sub_agent_graph


# =============================================================================
# 辅助函数
# =============================================================================


def _parse_tool_calls(content: str):
    """从 content 字符串中解析 tool_calls，与 core.py 逻辑一致"""
    if not content:
        return None

    ai_msg = AIMessage(content=content)

    if not hasattr(ai_msg, "tool_calls") or not ai_msg.tool_calls:
        import json
        tool_calls = []
        tag_pattern = r'<tool_calls>(.*?)</tool_calls>'
        for match in re.finditer(tag_pattern, content, re.DOTALL):
            json_str = match.group(1).strip()
            if not json_str:
                continue
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                fixed = re.sub(r',(\s*[}\]])', r'\1', json_str)
                try:
                    data = json.loads(fixed)
                except json.JSONDecodeError:
                    continue

            if isinstance(data, list):
                for item in data:
                    args = item.get("args", {})
                    args.pop("id", None)
                    args.pop("name", None)
                    tool_calls.append({
                        "name": item.get("name"),
                        "args": args,
                        "id": item.get("id", f"call_{len(tool_calls)+1}"),
                    })
            elif isinstance(data, dict):
                args = data.get("args", {})
                args.pop("id", None)
                args.pop("name", None)
                tool_calls.append({
                    "name": data.get("name"),
                    "args": args,
                    "id": data.get("id", f"call_{len(tool_calls)+1}"),
                })

        ai_msg.tool_calls = tool_calls if tool_calls else None

    return ai_msg.tool_calls if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls else None


# =============================================================================
# Tool
# =============================================================================

@tool
def sub_agent(
    task: Annotated[str, "Sub-task description (one sub_agent call handles one sub-task)"],
    prompt_addon: Annotated[str, "Execution steps hint, e.g. 'cmd → cat SKILL.md → code'"] = "",
    session_id: Annotated[str, "Session id"] = ""
) -> str:
    """
    DEPRECATED: sub_agent 工具已废弃，prompt（PROMPT_MAIN_FLOW）不再向 LLM 暴露
    该能力。仅保留实现以兼容潜在遗留调用，后续清理时可整体删除。

    Spawn a sub-agent to execute a sub-task (Plan-Execute + ReAct mode; sub-agent runs its own ReAct loop and returns the result text).

    See main agent prompt for detailed usage rules.
    """
    try:
        from ChatMe.ChatWorkflow.config.graph_config import build_sub_agent_prompt

        system_prompt = build_sub_agent_prompt(task, prompt_addon)
        graph = _get_sub_agent_graph(prompt=system_prompt)

        logger.info(f"[sub_agent] 会话 {session_id} task={task[:50]}...")

        # 用 thread_id 统一主 agent / sub_agent 的 session 标识
        # MCP interceptor 优先读 thread_id（与 LangGraph runtime 惯例一致）
        config = {"configurable": {"thread_id": session_id}}
        result = asyncio.run(graph.ainvoke({"messages": []}, config=config))
    except Exception as e:
        error_text = f"{type(e).__name__}: {e}"
        logger.error(f"[sub_agent] 会话 {session_id} 执行失败: {error_text}", exc_info=True)
        return (
            "[sub-agent execution failed]\n"
            f"Error type: {type(e).__name__}\n"
            f"Error message: {e}\n"
            "Note: This sub-task failed. Other sub_agent results are NOT affected."
            "Main agent options: skip this sub-task / retry with a smaller split /"
            " main agent handles it directly via cmd / code / report partial completion to the user."
        )

    # 提取最终回复（兼容多种 result 形态：dict / State 对象 / list）
    if isinstance(result, dict):
        final_messages = result.get("messages", [])
    elif hasattr(result, "messages"):
        final_messages = result.messages
    elif isinstance(result, list):
        final_messages = result
    else:
        final_messages = []

    logger.debug(f"[sub_agent] 会话 {session_id} 思维链: {final_messages}")
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage):
            logger.debug(f"[sub_agent] 会话 {session_id} 最终消息: {msg}")
            content = msg.content if hasattr(msg, "content") else str(msg)
            if content.strip():
                return content

    logger.debug(f"[sub_agent] 会话 {session_id} 结果: [无输出]")
    return "[sub-agent no output]"

