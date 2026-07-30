"""
MCP stdio session 生命周期管理(chatme_main 侧)

长生命周期 stdio_client subprocess:启动时 fork 子进程,通过永久 asyncio task
持有 context manager 不退出,所有工具调用复用同一 session,避免每次 fork。
"""

import asyncio
import sys
from typing import Any, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

from .tools import sub_agent

_mcp_session: Optional[ClientSession] = None
_mcp_session_task: Optional[asyncio.Task] = None
_mcp_session_ready: Optional[asyncio.Event] = None
_mcp_tools_cache: Optional[List[Any]] = None
_tool_interceptors: list = []


async def _maintain_mcp_session() -> None:
    """永久持有 stdio_client + ClientSession,直到 task 被 cancel"""
    global _mcp_session, _mcp_session_ready
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ChatMe.ChatWorkflow.mcps.server"],
    )
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                _mcp_session = session
                if _mcp_session_ready is not None:
                    _mcp_session_ready.set()
                await asyncio.Event().wait()  # 永久挂起直到 task cancel
    finally:
        _mcp_session = None


async def init_mcp(tool_interceptors: list = None) -> None:
    """启动长生命周期 MCP session + 加载工具列表"""
    global _mcp_session_task, _mcp_session_ready, _mcp_tools_cache, _tool_interceptors
    if _mcp_session_task is not None:
        return

    _tool_interceptors = tool_interceptors or []
    _mcp_session_ready = asyncio.Event()
    _mcp_session_task = asyncio.create_task(_maintain_mcp_session())

    try:
        await asyncio.wait_for(_mcp_session_ready.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        _mcp_session_task.cancel()
        raise RuntimeError("MCP session 启动超时(30s)")

    # 传入已有 session → 工具绑定到长生命周期 session,后续不 fork
    tools = await load_mcp_tools(
        _mcp_session,
        tool_interceptors=_tool_interceptors,
    )
    tools.append(sub_agent)
    _mcp_tools_cache = tools


async def shutdown_mcp() -> None:
    """chatme_main 退出时 cancel task → subprocess 终止"""
    global _mcp_session_task, _mcp_session_ready
    if _mcp_session_task is None:
        return
    _mcp_session_task.cancel()
    try:
        await _mcp_session_task
    except (asyncio.CancelledError, Exception):
        pass
    _mcp_session_task = None
    _mcp_session_ready = None


def get_mcp_tools() -> List[Any]:
    """返回已初始化的 MCP tools 列表(懒加载)"""
    if _mcp_tools_cache is None:
        raise RuntimeError("MCP tools not initialized yet; call init_mcp() first")
    return _mcp_tools_cache