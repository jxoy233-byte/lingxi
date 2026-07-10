import inspect
import functools

from langgraph.errors import GraphBubbleUp

from ChatMe.LoggingManager.logging_config import get_logger


def node_guard(name: str, logger=None):
    """
    包装普通 graph node：记录异常并继续抛出，让 SSE 外层统一返回 error。

    作为模块级装饰器，可被 ChatWorkflow 节点、sub_agent 工具等任意 sync / async 函数直接复用。

    关键：
    - LangGraph 控制流异常（GraphInterrupt / ParentCommand 等 GraphBubbleUp 子类）
      必须原样上抛，不能当作业务异常包装成 RuntimeError：
      interrupt() 触发的主动中断、Command 透传都依赖这类异常穿透各层到达 runtime。
    - 用 functools.wraps 保留原函数的 __wrapped__，
      让 inspect.signature(wrapper) 沿链回到原函数 (state, config)，
      LangGraph 才能正确把 config 作为第二参数传入。
    """
    if logger is None:
        logger = get_logger("node_guard")

    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except GraphBubbleUp:
                    # LangGraph 控制流异常，原样上抛给 runtime 处理
                    raise
                except Exception as e:
                    logger.error(f"[{name}] 执行失败: {e}", exc_info=True)
                    raise RuntimeError(f"{name} 执行失败: {e}") from e
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except GraphBubbleUp:
                # LangGraph 控制流异常，原样上抛给 runtime 处理
                raise
            except Exception as e:
                logger.error(f"[{name}] 执行失败: {e}", exc_info=True)
                raise RuntimeError(f"{name} 执行失败: {e}") from e
        return sync_wrapper
    return decorator