import asyncio
import inspect
import os
import time
import functools
from contextvars import ContextVar
from typing import Callable, Optional

from langgraph.errors import GraphBubbleUp

from ChatMe.LoggingManager.logging_config import get_logger


# ---------------------------------------------------------------------------
# 瞬时错误重试（overloaded / 限流 / 网络抖动）
# ---------------------------------------------------------------------------
# 为什么放在 node_guard：7 个节点无一例外都挂了它，这是全链路唯一的必经收口，
# 加一次即全覆盖；散到各 LLM 调用点则新增节点时又得记得包一遍。
#
# 为什么必须按错误类型收窄而不是无差别重试：529/429/5xx/timeout 是「等一会会好」，
# 而 KeyError、配置缺失、解析失败重试 5 遍只是把真 bug 变成 5 倍延迟 + 5 份噪音堆栈。
#
# 为什么 GraphBubbleUp 绝不重试：interrupt() 主动中断 / Command 透传都靠它穿透到
# runtime，重试会把用户的「停」变成「再试五次」。
#
# 为什么是固定 8s 而不是指数退避：529 是集群整体过载，秒级重连基本必然再撞同一堵墙
# （14:15:54 和 14:16:10 两次 529 相隔 16s 就是证据）；固定间隔让 5 次尝试均匀覆盖
# 约 40s 的过载窗口，代价上限也可预期（5 × 8s），不会指数涨到几分钟。

# LLM 服务端过载时的重试次数与固定间隔（秒）
_MAX_RETRIES = int(os.getenv("NODE_GUARD_MAX_RETRIES", "5"))
_RETRY_DELAY = float(os.getenv("NODE_GUARD_RETRY_DELAY", "8.0"))

# 走 openai SDK 异常判定；SDK 不可用时退化为字符串匹配
try:
    from openai import APIConnectionError as _APIConnectionError
    from openai import APIStatusError as _APIStatusError

    _OPENAI_ERRORS = (_APIStatusError, _APIConnectionError)
except ImportError:  # pragma: no cover - openai 是硬依赖，这里只是防御
    _OPENAI_ERRORS = ()

# 非标准 OpenAI 兼容端点（如 MiniMax）可能不抛 SDK 原生异常时的兜底关键字
_TRANSIENT_HINTS = ("overloaded", "rate limit", "too many requests", "529")


class TransientUpstreamError(RuntimeError):
    """
    上游瞬时错误重试耗尽后抛出，取代普通 RuntimeError。

    带上重试元信息（attempts / max_attempts / last_error），由 ChatService 读出来
    塞进 SSE `error` 事件的 payload，前端据此显示「已重试 N 次仍失败」而不是
    一坨 529 堆栈。

    为什么不复用普通 RuntimeError + setattr：类型显式，下游 isinstance 判断直观，
    且不会被 node_guard 外层的 `except Exception` 误当成业务错误重新包一层。
    """

    def __init__(self, node: str, attempts: int, max_attempts: int, last_error: str):
        super().__init__(
            f"{node} 执行失败（上游繁忙，已自动重试 {attempts}/{max_attempts} 次仍失败）: {last_error}"
        )
        self.node = node
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.last_error = last_error
        self.upstream_transient = True


def _is_transient(exc: BaseException, _depth: int = 0) -> bool:
    """
    判断异常是否属于「等一会会好」的瞬时错误。

    沿 __cause__ / __context__ 链向上找：内层 node_guard 已把原始异常包成
    RuntimeError（`from e`），外层 guard 看到的只有 RuntimeError，必须下钻。

    判定两条：
      1. openai SDK 异常 —— status_code ∈ {408,409,429} 或 >= 500；
         APIConnectionError（含 APITimeoutError）无 status_code，一律算瞬时。
      2. 关键字兜底 —— 非标准端点抛出的裸异常里带 overloaded / 529 等字样。
    """
    if _depth > 5:  # 防 __cause__ 环形引用打转
        return False

    if _OPENAI_ERRORS:
        if isinstance(exc, _APIStatusError):
            code = getattr(exc, "status_code", None)
            if code is None:
                return True
            return code in (408, 409, 429) or code >= 500
        if isinstance(exc, _APIConnectionError):
            return True

    msg = str(exc).lower()
    if any(hint in msg for hint in _TRANSIENT_HINTS):
        return True

    for nxt in (exc.__cause__, exc.__context__):
        if isinstance(nxt, BaseException) and _is_transient(nxt, _depth + 1):
            return True
    return False


def _log_retry(logger, name: str, attempt: int, exc: BaseException, delay: float):
    logger.warning(
        f"[{name}] 瞬时错误，第 {attempt}/{_MAX_RETRIES} 次重试"
        f"（{delay:.0f}s 后）: {type(exc).__name__}: {exc}"
    )


def _with_retry(name: str, logger, func, is_coroutine: bool):
    """
    统一的「执行 + 瞬时错误定间隔重试」骨架。
    重试用尽后原样上抛，交给 node_guard 的 except 分支做日志 + 包装。
    """

    async def _run_async(*args, **kwargs):
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except GraphBubbleUp:
                raise  # 控制流异常，任何情况下都不重试
            except Exception as e:
                if not _is_transient(e):
                    raise
                if attempt >= _MAX_RETRIES:
                    # 重试耗尽 → 抛带元信息的类型，让 ChatService 能告诉前端
                    # 「上游繁忙，已重试 N 次仍失败」而不是一坨 529 堆栈
                    raise TransientUpstreamError(
                        name, attempt, _MAX_RETRIES, f"{type(e).__name__}: {e}"
                    ) from e
                _log_retry(logger, name, attempt, e, _RETRY_DELAY)
                # asyncio.sleep 是取消点：用户中断 / 客户端断连时 CancelledError
                # 立即在此抛出，不会被下一轮重试吞掉
                await asyncio.sleep(_RETRY_DELAY)

    def _run_sync(*args, **kwargs):
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except GraphBubbleUp:
                raise
            except Exception as e:
                if not _is_transient(e):
                    raise
                if attempt >= _MAX_RETRIES:
                    raise TransientUpstreamError(
                        name, attempt, _MAX_RETRIES, f"{type(e).__name__}: {e}"
                    ) from e
                _log_retry(logger, name, attempt, e, _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)

    return _run_async if is_coroutine else _run_sync


def node_guard(name: str, logger=None):
    """
    包装普通 graph node：记录异常并继续抛出，让 SSE 外层统一返回 error。

    作为模块级装饰器，可被 ChatWorkflow 节点等任意 sync / async 函数直接复用。

    关键：
    - LangGraph 控制流异常（GraphInterrupt / ParentCommand 等 GraphBubbleUp 子类）
      必须原样上抛，不能当作业务异常包装成 RuntimeError：
      interrupt() 触发的主动中断、Command 透传都依赖这类异常穿透各层到达 runtime。
    - 瞬时错误（529 过载 / 429 限流 / 5xx / 超时 / 连接抖动）先按指数退避重试
      _MAX_RETRIES 次，全部失败才落到 except 段。重试只覆盖异常，不覆盖正常返回。
    - 用 functools.wraps 保留原函数的 __wrapped__，
      让 inspect.signature(wrapper) 沿链回到原函数 (state, config)，
      LangGraph 才能正确把 config 作为第二参数传入。
    """
    if logger is None:
        logger = get_logger("node_guard")

    def decorator(func):
        runner = _with_retry(name, logger, func, inspect.iscoroutinefunction(func))

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await runner(*args, **kwargs)
                except GraphBubbleUp:
                    # LangGraph 控制流异常，原样上抛给 runtime 处理
                    raise
                except TransientUpstreamError:
                    # 已带重试元信息，原样上抛；再包一层会把元信息埋进 __cause__，
                    # ChatService 就读不到 attempts 了
                    raise
                except Exception as e:
                    logger.error(f"[{name}] 执行失败: {e}", exc_info=True)
                    raise RuntimeError(f"{name} 执行失败: {e}") from e
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return runner(*args, **kwargs)
            except GraphBubbleUp:
                # LangGraph 控制流异常，原样上抛给 runtime 处理
                raise
            except TransientUpstreamError:
                raise
            except Exception as e:
                logger.error(f"[{name}] 执行失败: {e}", exc_info=True)
                raise RuntimeError(f"{name} 执行失败: {e}") from e
        return sync_wrapper
    return decorator
