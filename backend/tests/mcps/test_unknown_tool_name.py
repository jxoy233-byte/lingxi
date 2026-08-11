"""
未知工具名兜底测试

CLAUDE.md 偏好 11 / 26 强调：
- 工具异常必须走兜底变成 ToolMessage，不能让工作流崩
- GraphBubbleUp (GraphInterrupt) 必须透传不能吞

本测试验证：LLM 调了一个不在 self.tools_by_name 里的工具名时，
不会让 PermissionedToolNode / 整个图崩掉，而是返回
ToolMessage(content=INVALID_TOOL_NAME_ERROR_TEMPLATE)，LLM 看到错误后可重试。

LangGraph ToolNode 0.x 自带 _validate_tool_call 兜底（行 1070-1075）：
    if tool is None:
        if invalid_tool_message := self._validate_tool_call(call):
            return invalid_tool_message
本测试固定这个行为，避免 LangGraph 升级后悄悄回归。
"""

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langchain_core.messages import AIMessage, ToolCall, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from ChatMe.ChatWorkflow.mcps.permissions.core import PermissionedToolNode  # noqa: E402


# =========================================================================
# fixture
# =========================================================================


@pytest.fixture
def known_tool_node():
    """构造一个 PermissionedToolNode，里面只有一个真实工具 my_cmd。"""

    @tool
    def my_cmd(command: str) -> str:
        """执行命令（mock 工具，永远不会真跑，因为测试不会调它）"""
        return f"executed: {command}"

    return PermissionedToolNode(tools=[my_cmd])


def _make_tool_call(name: str, call_id: str = "call_test_001") -> ToolCall:
    return {
        "name": name,
        "args": {"command": "ls"},
        "id": call_id,
        "type": "tool_call",
    }


def _make_tool_runtime():
    """构造一个最简 ToolRuntime（只填 state / config）。"""
    from langchain_core.runnables import RunnableConfig
    from langgraph.prebuilt.tool_node import ToolRuntime

    return ToolRuntime(
        state={"messages": [AIMessage(content="", tool_calls=[])]},
        config=RunnableConfig(),
        context=None,
        stream_writer=lambda _x: None,
        tool_call_id=None,
        store=None,
    )


def _make_tool_request(call):
    """构造一个最简 ToolCallRequest。"""
    from langgraph.prebuilt.tool_node import ToolCallRequest

    return ToolCallRequest(
        tool_call=call,
        tool=None,  # 故意 None，让 ToolNode 自己走 _validate_tool_call
        state={"messages": [AIMessage(content="", tool_calls=[call])]},
        runtime=_make_tool_runtime(),
    )


def _run(coro):
    """pytest-asyncio not installed in this project; use asyncio.run wrapper."""
    return asyncio.run(coro)


# =========================================================================
# 1. 未知工具名：走 ToolNode._validate_tool_call 兜底
# =========================================================================


def test_unknown_tool_name_returns_error_tool_message(known_tool_node):
    """LLM 调一个不存在的工具名 → 返 ToolMessage(error=...)，不抛错。

    PermissionedToolNode._permission_wrap 把 execute() 返的 ToolMessage
    透明透传（不包装），所以 LLM 看到的是 LangGraph 自带的
    INVALID_TOOL_NAME_ERROR_TEMPLATE（含 available_tools 列表，方便 LLM 重试）。
    """
    fake_call = _make_tool_call(name="does_not_exist_tool")
    result = _run(
        known_tool_node._arun_one(
            call=fake_call,
            input_type="tool_calls",
            tool_runtime=_make_tool_runtime(),
        )
    )

    # 不抛错 + 返 ToolMessage
    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "call_test_001"
    assert result.status == "error"
    # 错误信息应明确指出工具名 + 列出可用工具
    content = result.content if isinstance(result.content, str) else str(result.content)
    assert "does_not_exist_tool" in content
    assert "my_cmd" in content  # available_tools 列表里


# =========================================================================
# 2. 已知工具名：正常走 _permission_wrap hook 三层 gate
# =========================================================================


def test_known_tool_name_passes_through_permission_wrap(known_tool_node):
    """已知工具名走 awrap_tool_call（即 _permission_wrap）三层 gate。

    不在白名单 → 返 ToolMessage（pre-check gate 2 拦），不抛错。
    """
    fake_call = _make_tool_call(name="my_cmd", call_id="call_known_001")
    result = _run(
        known_tool_node._arun_one(
            call=fake_call,
            input_type="tool_calls",
            tool_runtime=_make_tool_runtime(),
        )
    )
    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "call_known_001"


# =========================================================================
# 3. GraphBubbleUp 不能被未知工具兜底吞掉（interrupt 仍要穿透）
# =========================================================================


def test_unknown_tool_with_interrupt_does_not_swallow_bubble_up(known_tool_node):
    """GraphBubbleUp 必须原样 raise，不能被"未知工具兜底"吃掉。

    让 execute(request) 抛 GraphInterrupt（继承 GraphBubbleUp），
    _permission_wrap 应原样 raise，让 LangGraph runtime 走 interrupt pause 流程。
    """
    from langgraph.errors import GraphInterrupt

    fake_call = _make_tool_call(name="my_cmd", call_id="call_intr_001")

    async def fake_execute(_request):
        raise GraphInterrupt([{"value": "test interrupt"}])

    # _permission_wrap 直接调，不走 _arun_one 内部 dispatch
    with pytest.raises(GraphInterrupt):
        _run(
            known_tool_node._permission_wrap(
                request=_make_tool_request(fake_call),
                execute=fake_execute,
            )
        )
