"""
智能体的底层自带的核心工具能力(FASTMCP 实现,stdio transport 作为 chatme_main 子进程启动)

session_id 由 client 通过 tool_interceptor 注入 args["__session_id"],
middleware 读取后写入 ContextVar,工具函数通过 current_session_id.get() 取值
"""

from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Annotated, Literal, Optional

import redis
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
import subprocess
import sys
import signal

from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.ChatMeConfig import get_redis_checkpointer_url
from ChatMe.ChatWorkflow.mcps.CodeSandboxPool import SandboxPool
from ChatMe.ChatWorkflow.mcps.platforms import get_platform, init_platform

server = FastMCP(name="ChatMe Agent Core Skills")

logger = get_logger("mcp_server")

redis_url = get_redis_checkpointer_url()
_redis_client = redis.from_url(redis_url)

# 沙盒容器池
_sandbox_pool = None

# =========================================================================
# Session 归属：HTTP header → ContextVar → 工具函数
# =========================================================================

# 模块级 ContextVar：每个 MCP 请求在自己的 asyncio task 里独享
# 工具函数通过 current_session_id.get() 拿到 sid（用于日志 / 沙盒 cwd / 等）
current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")


class SessionHeaderMiddleware(Middleware):
    """每个 MCP 工具调用请求进来时，从注入的 __session_id 取 sid 塞进 ContextVar。

    链路：
    - client 端 _inject_session_header 从 LangGraph runtime 拿 thread_id → 注入 args["__session_id"]
    - FastMCP stdio transport 把 call arguments 透传到 server
    - 本中间件读 context.message.arguments["__session_id"] → current_session_id.set(sid)
    - 工具函数 current_session_id.get() 取 sid
    - finally reset token 清理，避免泄漏

    sid 缺失场景（如裸调 / 调试）：session_id 为空串，工具仍可工作但日志无 session 归属。
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        sid = ""
        try:
            # 从 args pop 掉 __session_id,避免 Pydantic 报 unexpected_keyword_argument
            args = getattr(context.message, "arguments", None) or {}
            sid = args.pop("__session_id", "") or ""
        except Exception:
            sid = ""

        token = current_session_id.set(sid)
        try:
            return await call_next(context)
        finally:
            current_session_id.reset(token)


# 注册中间件（FastMCP 3.x add_middleware）
server.add_middleware(SessionHeaderMiddleware())

def _cleanup_existing_containers():
    """清理残留的沙盒容器（不删除 redis）"""
    try:
        result = subprocess.run(["docker", "ps", "-a"], capture_output=True, text=True)
        container_ids = []
        for line in result.stdout.strip().split("\n"):
            if "chatme-python-sandbox" in line and "chatme-redis" not in line:
                cid = line.split()[0]
                container_ids.append(cid)

        for cid in container_ids:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        if container_ids:
            logger.info(f"已清理残留沙盒容器")
    except Exception as e:
        logger.warning(f"清理残留容器失败: {e}")

def _ensure_redis_running():
    """确保 redis 运行（使用 docker-compose）"""
    try:
        # 切换到项目根目录执行 docker-compose
        project_root = Path(__file__).parent.parent.parent.parent
        subprocess.run(
            ["docker-compose", "up", "-d", "redis"],
            cwd=str(project_root),
            capture_output=True
        )
        logger.info("Redis 服务已就绪")
    except Exception as e:
        logger.warning(f"Redis 启动检查失败: {e}")

def _init_sandbox_pool():
    """初始化沙盒容器池"""
    global _sandbox_pool
    try:
        from ChatMe.ChatWorkflow.mcps.CodeSandboxPool import SandboxPool
        _sandbox_pool = SandboxPool()  # 默认 size=1（min_size=1, max_size=3, per_container_concurrency=8）
        logger.info("沙盒容器池初始化成功")
    except Exception as e:
        logger.warning(f"沙盒容器池初始化失败: {e}，将使用本地虚拟环境")
        _sandbox_pool = None

# =========================================================================
# cmd / code 工具：业务逻辑统一走 platform adapter
# =========================================================================
# 危险检测 / 白名单 / 脚本识别 / 本地 fallback / prompt 片段全部在
# ChatMe.ChatWorkflow.mcps.platforms 模块下三套独立 adapter 里：
# - LinuxAdapter: 通用 + Unix 危险模式 + /bin/sh + /tmp
# - DarwinAdapter: macOS 专属 + /bin/zsh
# - WindowsAdapter: Windows 等价命令 + cmd.exe + %TEMP%
# 详见 platforms/base.py 抽象接口。
# 启动时 main() 调 init_platform() 检测 + 缓存，业务代码用 get_platform() 读。
# =========================================================================


@server.tool
def code(
    code: Annotated[str, "Code to execute"],
    language: Annotated[Literal["python", "nodejs", "javascript", "js"], "Code language, default python"] = "python",
    use_sandbox: Annotated[bool, "Whether to execute in sandbox (default True)"] = True,
) -> Optional[str]:
    """
    Execute code (sandbox by default; sandbox exposes /skills (read-only) and /cached (read-write)).
    Falls back to local platform venv if sandbox is unavailable.

    Permission: 审批在主进程的 tool_execution_node 里做（interrupt 需要 LangGraph runtime 上下文），
    MCP 侧只做 platform 硬过滤。
    """
    session_id = current_session_id.get()
    platform = get_platform()

    # 沙盒执行
    if use_sandbox and _sandbox_pool is not None:
        logger.debug(f"会话 {session_id} 使用[沙盒容器]执行代码")
        try:
            return _sandbox_pool.execute(code, language)
        except subprocess.TimeoutExpired:
            logger.warning(f"会话 {session_id} code 沙盒执行超时(300s)")
            return ("Error: code execution timed out (300s limit), "
                    "please optimize the script or split the task into smaller steps")

    # 沙盒池未初始化但 AI 想要沙盒 → 降级到本地
    if use_sandbox and _sandbox_pool is None:
        logger.warning(f"会话 {session_id} 请求沙盒但沙盒池未初始化，降级到 {platform.name} 本地 venv")

    logger.debug(f"会话 {session_id} 使用[{platform.name} 本地环境]执行代码")
    return platform.execute_code_local(code, language, code_timeout=300)


@server.tool
def cmd(
        command: Annotated[str, "System command to execute"],
        use_sandbox: Annotated[bool, "Whether to execute in sandbox (default True)"] = True,
) -> str:
    """Execute a shell command within the whitelist (sandbox by default; only skills/ and cached/ are exposed).

    Whitelist and danger patterns are determined by the platform adapter
    (Linux / Darwin / Windows). Windows uses cmd.exe commands (dir / type / findstr / copy / move / del).

    Permission + 静态前置 gate（dangerous / script / whitelist）都在主进程的 PermissionedToolNode
    里做完；这里只做执行。如果走到这里，说明前置 gate 已经放行。
    """
    session_id = current_session_id.get()
    platform = get_platform()

    # 沙盒执行
    if use_sandbox and _sandbox_pool is not None:
        logger.debug(f"会话 {session_id} 使用[沙盒容器]执行命令")
        try:
            return _sandbox_pool.execute_command(command)
        except subprocess.TimeoutExpired:
            logger.warning(f"会话 {session_id} cmd 沙盒执行超时(120s)")
            return ("Error: Command execution timed out (120s limit), "
                    "please optimize the command or split it into smaller steps")

    # 沙盒池未初始化但 AI 想要沙盒 → 降级到本地
    if use_sandbox and _sandbox_pool is None:
        logger.warning(f"会话 {session_id} 请求沙盒但沙盒池未初始化，降级到 {platform.name} 本地")

    logger.debug(f"会话 {session_id} 使用[{platform.name} 本地环境({platform.shell_path})]执行命令")
    return platform.execute_command(command, sandbox_pool=None, cmd_timeout=120)

@server.tool
def interrupt(
    message: Annotated[str,"Reason for interrupting / message to ask the user"],
):
      """
      Interrupt the current conversation to ask the user for more information.
      """
      session_id = current_session_id.get()
      if not session_id:
          logger.warning(f"interrupt 工具调用缺少 session_id（HTTP header 未带 X-Session-Id）")
          return "Error: missing session_id (X-Session-Id header not set)"

      try:
          _redis_client.hset(f"interrupt:{session_id}", mapping={
              "reason": message,
          })

          logger.debug(f"会话 {session_id} 触发中断: {message}")
          return f"Interrupt triggered, waiting for user input: {message}"
      except Exception as e:
          logger.error(f"会话 {session_id} 中断操作失败")
          return f"Interrupt failed: {str(e)}"


@server.tool
def ctime() -> str:
    """
    Get the current date and time (uses the local timezone).

    Returns:
        JSON with: datetime (formatted time), weekday_en (English weekday name).
    """
    now = datetime.now().astimezone()

    import json
    result = {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday_en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][now.weekday()]
    }

    logger.debug(f"会话{current_session_id.get() or 'unknown'}中获取当前时间成功")
    return json.dumps(result, ensure_ascii=False)

def _stop_redis():
    """停止 redis 容器(使用 docker-compose)"""
    try:
        project_root = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(
            ["docker-compose", "stop", "redis"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("Redis 服务已停止")
        else:
            logger.warning(f"Redis 停止失败 (exit={result.returncode}): {result.stderr.strip()}")
    except Exception as e:
        logger.warning(f"Redis 停止异常: {e}")

def _shutdown_resources() -> None:
    """关闭 sandbox pool + 停 redis,被 signal handler / main finally 复用

    防御:即便 sandbox shutdown 抛异常(比如 print 在 stdout 关闭后写),
    也要保证 _stop_redis() 跑到 —— redis 跟 sandbox 是独立 cleanup。
    """
    if _sandbox_pool:
        try:
            _sandbox_pool.shutdown()
        except Exception as e:
            logger.warning(f"sandbox shutdown 异常: {e}")
    _stop_redis()


def _signal_handler(signum, frame):
    """捕获 Ctrl+C 信号,触发 cleanup 后退出"""
    print("\n收到中断信号，正在关闭沙盒容器...")
    _shutdown_resources()
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 启动时检测平台（permissions 审批已挪到主进程 tool_execution_node，MCP 侧不再加载）
    platform = init_platform()
    logger.info(
        f"[ChatMe MCP] detected platform: {platform.name} "
        f"({platform.system_name}) / shell: {platform.shell_path} {platform.shell_flag} / "
        f"allowed cmds: {len(platform.allowed_commands)}"
    )

    # eager init(chatme_main 启动时随 MCP subprocess 一并就位):
    # redis 通过 docker-compose up -d 启,sandbox 池通过 SandboxPool() 启动。
    # 长生命周期 stdio session 下只有一个 subprocess,无需 lazy。
    _cleanup_existing_containers()
    _ensure_redis_running()
    _init_sandbox_pool()

    try:
        server.run(transport="stdio")
    finally:
        # stdio EOF(chatme_main 关闭)/ signal / exception 都会走这里,确保 sandbox + redis 清理
        _shutdown_resources()

if __name__ == "__main__":
    main()