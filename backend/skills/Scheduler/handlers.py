"""
定时任务执行 handler

当前只实现 send_message 模式：
- 触发时把 prompt 当用户消息注入到 session（按 session_id 字段解析）
- 跑 ChatService.message_stream（完整 LangGraph agent 流程）
- 从 SSE chunks 提取 final_response 作 output_preview
- finally 写 history + 更新 last_run/run_count + 释放锁

触发时机：APScheduler 到点触发，args=[task_id] 与 registry.add_job 注入方式一致。

为什么延迟 import chat_service:
- chat_service 是模块级 Optional[ChatService]，在 lifespan 启动后才有值
- handlers 不能假设 chat_service 已加载（避免循环 + 解决绑定时机问题）
"""

from __future__ import annotations

import json
import time
from typing import Tuple

from ChatMe.LoggingManager.logging_config import get_logger

from .core import get_redis
from .models import (
    SCHEDULED_HISTORY_PREFIX,
    SCHEDULED_LOCK_PREFIX,
    SCHEDULED_META_PREFIX,
    HistoryEntry,
    ScheduledTask,
)

logger = get_logger("SchedulerHandlers")

# 锁 TTL：1 小时（覆盖单次任务最长执行时间，含 LLM + 工具调用 + 网络 IO）
_LOCK_TTL_SECONDS = 3600

# 历史保留条数（与 plan 一致）
_HISTORY_MAX_ENTRIES = 50

# output_preview 截断长度
_OUTPUT_PREVIEW_MAX = 300


def _extract_final_response(chunks: list[str]) -> Tuple[str, str, str]:
    """
    从 message_stream 的 SSE chunks 提取 (output_preview, status, error_msg)

    chunks 是 message_stream yield 的 JSON 字符串列表（每条以 \n\n 结尾）。

    终态事件类型：
    - done:        正常完成 → full_response 是最终完整内容
    - error:       agent 异常 → error 字段是异常描述
    - interrupt:   permission 中断 → 该 session 等用户审批，scheduler 后台无人接管

    无 done 时 fallback 到累积 content（极端情况：generator 在 done 之前被关）
    """
    accumulated: list[str] = []
    final_response = ""
    status = "success"
    error_msg = ""

    for raw in chunks:
        try:
            evt = json.loads(raw.strip() if isinstance(raw, str) else raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        evt_type = evt.get("type")
        if evt_type == "done":
            final_response = evt.get("full_response", "") or final_response
            break  # done 之后 stream 必然结束，无新内容
        if evt_type == "error":
            error_msg = (evt.get("error") or evt.get("message") or "unknown error")[:200]
            status = "error"
        elif evt_type == "interrupt":
            tool = evt.get("tool_name") or evt.get("tool") or "unknown"
            error_msg = f"interrupted (permission required: {tool})"
            status = "interrupted"
        elif evt_type == "content":
            accumulated.append(str(evt.get("content", "")))

    # done.full_response 是最权威；缺失时 fallback 累积 content（防 stream 在 done 前被关）
    preview = final_response or "".join(accumulated)
    return preview[:_OUTPUT_PREVIEW_MAX], status, error_msg


async def handle_send_message(task_id: str) -> None:
    """
    send_message handler：把 prompt 当用户消息注入 session 跑 LangGraph agent

    APScheduler 触发时调用，task_id 是 job id（与 scheduled:meta:{tid} 一致）。
    meta 从 Redis HASH 读（避免与 registry 循环 import）。

    流程：
    1) SET scheduled:lock:{tid} NX EX 3600    —— 防重入
    2) 读 scheduled:meta:{tid}                —— 拿 prompt / session_id
    3) 延迟 import chat_service               —— 解决模块级绑定时机
    4) async for message_stream(...)          —— 跑 LangGraph agent
    5) finally: 写 history(LTRIM 50) + last_run/run_count + DEL lock

    异常路径：所有异常被 try/except 捕获，记录为 history status="error"，
    last_run 仍更新（下次 cron 仍可触发；否则永久卡住）。
    """
    redis = get_redis()
    lock_key = SCHEDULED_LOCK_PREFIX + task_id
    meta_key = SCHEDULED_META_PREFIX + task_id
    history_key = SCHEDULED_HISTORY_PREFIX + task_id

    # 1) 防重入锁：上一轮没跑完（或异常被吞没），本次直接跳过
    if not redis.set(lock_key, str(time.time()), nx=True, ex=_LOCK_TTL_SECONDS):
        logger.warning(
            f"[scheduler] task={task_id[:8]} 上轮未完（锁未释放），跳过本次触发"
        )
        return

    started_at = time.time()
    status = "success"
    error_msg = ""
    output_preview = ""
    target_sid = ""  # 默认空串（finally log 时不能 UnboundLocalError）

    try:
        # 2) 读 meta（直接读 HASH 而非调 registry.get_task，避免循环 import）
        raw = redis.hgetall(meta_key)
        if not raw:
            raise RuntimeError(f"task {task_id} 不存在（meta 已删）")
        task = ScheduledTask.from_hgetall(task_id, raw)
        if task is None:
            raise RuntimeError(f"task {task_id} meta 反序列化失败")
        prompt = task.prompt
        target_sid = task.session_id  # 空串 → message_stream 自动新建 session
        if not prompt:
            raise RuntimeError(f"task {task_id} prompt 为空")

        # 3) 延迟导入 chat_service（lifespan 启动后才赋值）
        from ChatMe.APIRouter.main import chat_service
        if chat_service is None:
            raise RuntimeError("chat_service 未初始化（lifespan 异常或 scheduler_lifespan 嵌套顺序错）")

        # 4) 跑 message_stream（async generator，全部消费完）
        chunks: list[str] = []
        async for chunk in chat_service.message_stream(
            message=prompt,
            session_id=target_sid or None,  # 空 → message_stream 内部 uuid.uuid4().hex[:12]
        ):
            chunks.append(chunk)

        # 5) 提取最终回复 + 状态
        output_preview, status, error_msg = _extract_final_response(chunks)

    except Exception as e:
        status = "error"
        error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        logger.exception(f"[scheduler] task={task_id[:8]} 执行失败")
    finally:
        # 6) 写 history（LTRIM 保留 50 条；用 pipeline 减少 round-trip）
        duration_ms = int((time.time() - started_at) * 1000)
        entry = HistoryEntry(
            ts=started_at,
            status=status,
            duration_ms=duration_ms,
            output_preview=output_preview,
            error=error_msg,
        )
        try:
            pipe = redis.pipeline(transaction=False)
            pipe.lpush(history_key, entry.to_json())
            pipe.ltrim(history_key, 0, _HISTORY_MAX_ENTRIES - 1)
            pipe.hincrby(meta_key, "run_count", 1)
            pipe.hset(meta_key, "last_run", str(started_at))
            pipe.execute()
        except Exception as e:
            logger.warning(f"[scheduler] 写 history / 更新 last_run 失败: {e}")

        # 7) 释放锁（必须最后；即使上面写失败也要放锁，否则永久卡住）
        try:
            redis.delete(lock_key)
        except Exception as e:
            logger.warning(f"[scheduler] 释放 lock 失败: {e}")

        logger.info(
            f"[scheduler] task={task_id[:8]} done: status={status}, "
            f"duration_ms={duration_ms}, output_len={len(output_preview)}, "
            f"target_sid={target_sid[:8] if target_sid else '<new>'}"
        )