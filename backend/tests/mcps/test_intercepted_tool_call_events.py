"""
验证 ChatService._build_intercepted_tool_call_events（pre-check 拦截 SSE 兜底）

背景：
- PermissionedToolNode._permission_wrap 在 pre-check (dangerous/whitelist) 拦截时直接 return ToolMessage
- LangGraph 不发 on_tool_start / on_tool_end
- 但 on_chain_end 会带 data.input (含 AIMessage.tool_calls) + data.output (含 ToolMessage)
- ChatService 需要从 on_chain_end 兜底 emit tool_call_name + tool_call_result SSE 事件
- 正常路径已经通过 on_tool_end emit 过, set 去重避免双发
"""

from __future__ import annotations

import asyncio
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# =========================================================================
# helpers
# =========================================================================


def _make_on_chain_end_chunk(
    tool_call_id: str,
    tool_call_args: dict,
    tool_call_name: str,
    tool_message_content: str,
):
    """模拟 LangGraph on_chain_end 节点为 tool_execution_node 的 chunk 结构。"""
    from langchain_core.messages import AIMessage, ToolMessage

    ai_msg = AIMessage(
        content="",
        tool_calls=[{
            "id": tool_call_id,
            "name": tool_call_name,
            "args": tool_call_args,
            "type": "tool_call",
        }],
    )
    tool_msg = ToolMessage(
        content=tool_message_content,
        tool_call_id=tool_call_id,
        name=tool_call_name,
    )
    return {
        "event": "on_chain_end",
        "name": "tools",
        "metadata": {
            "langgraph_node": "tool_execution_node",
            "langgraph_step": 1,
        },
        "data": {
            "input": {"messages": [ai_msg]},
            "output": {"messages": [tool_msg]},
        },
    }


def _run(coro):
    """asyncio.run 包装, 替代 @pytest.mark.asyncio（项目没装 pytest-asyncio）。"""
    return asyncio.run(coro)


def _make_chat_service():
    """构造一个 ChatService 实例但不调 __init__（避免初始化 workflow / redis 等）。"""
    from ChatMe.ChatService.core import ChatService

    cs = ChatService.__new__(ChatService)
    cs.logger = MagicMock()
    return cs


def _default_token_usage():
    return {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


# =========================================================================
# 测试
# =========================================================================


def test_intercepted_event_emits_both_name_and_result():
    """被拦截的 tool_call 应该 emit tool_call_name + tool_call_result 两条 SSE。"""
    cs = _make_chat_service()

    chunk = _make_on_chain_end_chunk(
        tool_call_id="call_xyz_123",
        tool_call_args={"command": "rm -rf /tmp/foo"},
        tool_call_name="cmd",
        tool_message_content="Auto-blocked by safety system: ...",
    )
    emitted_ids: set = set()

    events = _run(cs._build_intercepted_tool_call_events(
        chunk, emitted_ids, 0, _default_token_usage()
    ))

    assert len(events) == 2, f"应 emit 2 条事件, 实际 {len(events)}"

    name_evt = json.loads(events[0])
    result_evt = json.loads(events[1])

    assert name_evt["type"] == "tool_call_name"
    assert name_evt["id"] == "call_xyz_123"
    assert name_evt["content"]["name"] == "cmd"
    assert name_evt["content"]["args"] == {"command": "rm -rf /tmp/foo"}

    assert result_evt["type"] == "tool_call_result"
    assert result_evt["id"] == "call_xyz_123"
    assert result_evt["content"] == "Auto-blocked by safety system: ..."

    assert "call_xyz_123" in emitted_ids


def test_intercepted_event_skipped_when_already_emitted():
    """正常路径已 on_tool_end emit 过（id 在 set 里）, 兜底分支应跳过避免双发。"""
    cs = _make_chat_service()

    chunk = _make_on_chain_end_chunk(
        tool_call_id="call_xyz_123",
        tool_call_args={"command": "ls -la"},
        tool_call_name="cmd",
        tool_message_content="skylab output...",
    )
    emitted_ids: set = {"call_xyz_123"}

    events = _run(cs._build_intercepted_tool_call_events(
        chunk, emitted_ids, 0, _default_token_usage()
    ))

    assert events == []


def test_intercepted_event_ignores_non_tool_node():
    """非 tool_execution_node 的 on_chain_end（如 agent_node 结束）应忽略。"""
    cs = _make_chat_service()

    chunk = _make_on_chain_end_chunk(
        tool_call_id="call_xyz_123",
        tool_call_args={"command": "ls"},
        tool_call_name="cmd",
        tool_message_content="ok",
    )
    # 改 metadata.langgraph_node 为 agent_node
    chunk["metadata"]["langgraph_node"] = "agent_node"

    emitted_ids: set = set()
    events = _run(cs._build_intercepted_tool_call_events(
        chunk, emitted_ids, 0, _default_token_usage()
    ))
    assert events == []


def test_intercepted_event_handles_empty_output():
    """on_chain_end 没有 ToolMessage (边界 case) → emit 0 条事件。"""
    from langchain_core.messages import AIMessage
    cs = _make_chat_service()

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "cmd", "args": {"command": "ls"}, "type": "tool_call"}],
    )
    chunk = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "tool_execution_node"},
        "data": {
            "input": {"messages": [ai_msg]},
            "output": {"messages": []},
        },
    }

    emitted_ids: set = set()
    events = _run(cs._build_intercepted_tool_call_events(
        chunk, emitted_ids, 0, _default_token_usage()
    ))
    assert events == []


def test_intercepted_event_uses_aimessage_tool_call_args():
    """从 AIMessage.tool_calls 反向找 args（ToolMessage 自己没有 args）。"""
    cs = _make_chat_service()

    chunk = _make_on_chain_end_chunk(
        tool_call_id="call_abc",
        tool_call_args={"command": "sysctl hw.memsize", "local": True},
        tool_call_name="cmd",
        tool_message_content="Auto-blocked: command not in whitelist.",
    )
    emitted_ids: set = set()

    events = _run(cs._build_intercepted_tool_call_events(
        chunk, emitted_ids, 100, {"prompt": 10, "completion": 5, "total": 15, "calls": 1}
    ))

    name_evt = json.loads(events[0])
    assert name_evt["content"]["args"] == {"command": "sysctl hw.memsize", "local": True}
    assert name_evt["elapsed_ms"] == 100
    assert name_evt["token_usage"]["total"] == 15


def test_intercepted_event_handles_multiple_tool_messages():
    """一次 on_chain_end 含多个 ToolMessage (并行 tool_call 全被拦截) → 每条都 emit。"""
    from langchain_core.messages import AIMessage, ToolMessage
    cs = _make_chat_service()

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "call_1", "name": "cmd", "args": {"command": "rm -rf /"}, "type": "tool_call"},
            {"id": "call_2", "name": "cmd", "args": {"command": "sysctl hw.memsize"}, "type": "tool_call"},
        ],
    )
    tool_msgs = [
        ToolMessage(content="Auto-blocked: dangerous", tool_call_id="call_1", name="cmd"),
        ToolMessage(content="Auto-blocked: not in whitelist", tool_call_id="call_2", name="cmd"),
    ]
    chunk = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "tool_execution_node"},
        "data": {
            "input": {"messages": [ai_msg]},
            "output": {"messages": tool_msgs},
        },
    }

    emitted_ids: set = set()
    events = _run(cs._build_intercepted_tool_call_events(
        chunk, emitted_ids, 0, _default_token_usage()
    ))

    assert len(events) == 4
    assert emitted_ids == {"call_1", "call_2"}
    name1 = json.loads(events[0])
    assert name1["id"] == "call_1"
    assert name1["content"]["args"]["command"] == "rm -rf /"
    name2 = json.loads(events[2])
    assert name2["id"] == "call_2"
    assert name2["content"]["args"]["command"] == "sysctl hw.memsize"


def test_intercepted_event_orphan_tool_message_skipped():
    """output 里有 ToolMessage 但 input AIMessage.tool_calls 没对应 id (LangGraph 异常) → 跳过。"""
    from langchain_core.messages import AIMessage, ToolMessage
    cs = _make_chat_service()

    ai_msg = AIMessage(content="hi", tool_calls=[])
    orphan_tool_msg = ToolMessage(content="orphan", tool_call_id="orphan_id", name="cmd")
    chunk = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": "tool_execution_node"},
        "data": {
            "input": {"messages": [ai_msg]},
            "output": {"messages": [orphan_tool_msg]},
        },
    }

    emitted_ids: set = set()
    events = _run(cs._build_intercepted_tool_call_events(
        chunk, emitted_ids, 0, _default_token_usage()
    ))
    assert events == []
    assert "orphan_id" not in emitted_ids


# =========================================================================
# 集成测试: LangGraph 真实 astream_events + helper 端到端
# =========================================================================


def _build_precheck_graph():
    """构造一个 LangGraph 图：tool_node 用 _permission_wrap 拦截 BLOCKED 命令。"""
    from langgraph.prebuilt import ToolNode
    from langchain_core.tools import tool
    from langgraph.graph import StateGraph, START, END

    @tool
    def my_cmd(command: str) -> str:
        """执行命令"""
        return f"executed: {command}"

    async def pre_check_wrap(request, execute):
        from langchain_core.messages import ToolMessage
        tc = request.tool_call
        command = tc.get("args", {}).get("command", "")
        if "BLOCKED" in command:
            return ToolMessage(
                content=f"Auto-blocked: {command[:80]}",
                tool_call_id=tc["id"],
                name=tc["name"],
            )
        return await execute(request)

    tool_node = ToolNode(
        tools=[my_cmd], awrap_tool_call=pre_check_wrap, handle_tool_errors=False,
    )

    # 用 dict 代替 TypedDict, 避免 LangGraph get_type_hints 解析失败
    g = StateGraph(dict)
    # 关键: 节点名跟生产 ChatWorkflow 一致
    g.add_node("tool_execution_node", tool_node)
    g.add_edge(START, "tool_execution_node")
    g.add_edge("tool_execution_node", END)
    return g.compile()


def test_e2e_precheck_intercept_only():
    """端到端: 单一 tool_call 被 pre-check 拦截 → helper 兜底 emit 完整 SSE 事件对。"""
    from langchain_core.messages import AIMessage

    graph = _build_precheck_graph()
    cs = _make_chat_service()
    msg = AIMessage(
        content="",
        tool_calls=[{"id": "call_block_1", "name": "my_cmd", "args": {"command": "BLOCKED foo"}, "type": "tool_call"}],
    )

    sse_outputs = []
    emitted_ids: set = set()

    async def drive():
        async for ev in graph.astream_events({"messages": [msg]}, version="v2"):
            if ev['event'] == 'on_tool_start':
                sse_outputs.append({"type": "tool_call_name", "id": ev["run_id"]})
            elif ev['event'] == 'on_tool_end':
                output = ev.get('data', {}).get('output')
                if output:
                    tc_id = getattr(output, "tool_call_id", "") or ""
                    if tc_id:
                        emitted_ids.add(tc_id)
                    sse_outputs.append({"type": "tool_call_result", "id": ev["run_id"], "content": output.content})
            elif ev['event'] == 'on_chain_end' and (ev.get('metadata') or {}).get('langgraph_node') == 'tool_execution_node':
                intercepted = await cs._build_intercepted_tool_call_events(
                    ev, emitted_ids, 0, _default_token_usage(),
                )
                for sse_str in intercepted:
                    sse_outputs.append(json.loads(sse_str))

    _run(drive())

    name_evts = [o for o in sse_outputs if o['type'] == 'tool_call_name']
    result_evts = [o for o in sse_outputs if o['type'] == 'tool_call_result']
    assert len(name_evts) == 1, f"应有 1 个 name 事件, 实际 {len(name_evts)} (sse: {sse_outputs})"
    assert len(result_evts) == 1, f"应有 1 个 result 事件, 实际 {len(result_evts)}"
    assert name_evts[0]['id'] == 'call_block_1'
    assert result_evts[0]['id'] == 'call_block_1'
    assert 'Auto-blocked' in result_evts[0]['content']


def test_e2e_mixed_normal_and_intercept_no_duplicate():
    """端到端: 同一 batch 1 个正常 + 1 个拦截 → 4 条事件, 去重避免双发。"""
    from langchain_core.messages import AIMessage

    graph = _build_precheck_graph()
    cs = _make_chat_service()
    msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "call_ok_1", "name": "my_cmd", "args": {"command": "ok"}, "type": "tool_call"},
            {"id": "call_block_2", "name": "my_cmd", "args": {"command": "BLOCKED foo"}, "type": "tool_call"},
        ],
    )

    sse_outputs = []
    emitted_ids: set = set()

    async def drive():
        async for ev in graph.astream_events({"messages": [msg]}, version="v2"):
            if ev['event'] == 'on_tool_start':
                sse_outputs.append({"type": "tool_call_name", "id": ev["run_id"]})
            elif ev['event'] == 'on_tool_end':
                output = ev.get('data', {}).get('output')
                if output:
                    tc_id = getattr(output, "tool_call_id", "") or ""
                    if tc_id:
                        emitted_ids.add(tc_id)
                    sse_outputs.append({"type": "tool_call_result", "id": ev["run_id"], "content": output.content})
            elif ev['event'] == 'on_chain_end' and (ev.get('metadata') or {}).get('langgraph_node') == 'tool_execution_node':
                intercepted = await cs._build_intercepted_tool_call_events(
                    ev, emitted_ids, 0, _default_token_usage(),
                )
                for sse_str in intercepted:
                    sse_outputs.append(json.loads(sse_str))

    _run(drive())

    name_evts = [o for o in sse_outputs if o['type'] == 'tool_call_name']
    result_evts = [o for o in sse_outputs if o['type'] == 'tool_call_result']
    assert len(name_evts) == 2
    assert len(result_evts) == 2

    block_names = [n for n in name_evts if n['id'] == 'call_block_2']
    assert len(block_names) == 1, "BLOCKED 应该被兜底 emit 1 个 name 事件"
    block_results = [r for r in result_evts if r['id'] == 'call_block_2']
    assert len(block_results) == 1
    assert 'Auto-blocked' in block_results[0]['content']

    # 去重: call_ok_1 在 on_tool_end 时写入 set, 兜底不会重复 emit
    ok_id_seen_as_block = any(n['id'] == 'call_ok_1' for n in name_evts)
    assert not ok_id_seen_as_block, "call_ok_1 不应被兜底 emit (已在 set)"

