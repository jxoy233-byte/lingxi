"""
Scheduler 业务 CRUD（registry 层）

唯一权威：所有任务元数据的写入/读取都走这里。
APScheduler 的 JobStore 与 scheduled:* 元数据通过同一个 task_id 保持关联。

CRUD 与 APScheduler 同步策略：
- add_task:    写 scheduled:meta + scheduled:tasks + scheduler.add_job
- delete_task: scheduler.remove_job + DEL scheduled:meta + DEL history + SREM tasks
- update_task: update meta HASH fields + scheduler.reschedule_job (cron 变化) / pause/resume
- get_task/list_tasks: 只读 scheduled:meta（不查 APScheduler pickle）

API 层 + MCP server.py 都调这里。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from apscheduler.triggers.cron import CronTrigger

from ChatMe.LoggingManager.logging_config import get_logger

from .core import get_redis, get_scheduler

# 用 get_scheduler() 而非 `from .core import _scheduler`：后者是值快照，
# lifespan 启动后 core._scheduler 重赋值不会同步过来，add_task 永远 raise 503。
from .models import (
    SCHEDULED_HISTORY_PREFIX,
    SCHEDULED_LOCK_PREFIX,
    SCHEDULED_META_PREFIX,
    SCHEDULED_TASKS_SET,
    ScheduledTask,
)

logger = get_logger("SchedulerRegistry")


def _now() -> float:
    return time.time()


def _new_task_id() -> str:
    """12 位 hex task_id（与 ChatService session_id 同格式）"""
    return uuid.uuid4().hex[:12]


# =========================================================================
# add_task：注册新任务（写元数据 + 注册 APScheduler job）
# =========================================================================


def add_task(
    name: str,
    cron: str,
    prompt: str,
    session_id: str = "",
    created_by: str = "",
    task_type: str = "send_message",
) -> str:
    """
    注册新定时任务

    Args:
        name: 任务可读名
        cron: 5-field cron 表达式（Asia/Shanghai TZ）
        prompt: 触发时注入的"用户消息"
        session_id: 目标 session_id（空=灵活，留给 handler 兜底）
        created_by: 创建者的 session_id（权限边界）
        task_type: 当前固定 send_message；预留扩展

    Returns:
        task_id (12 位 hex)

    Raises:
        RuntimeError: scheduler 未启动 / cron 格式非法
    """
    if get_scheduler() is None:
        raise RuntimeError("scheduler 未启动（lifespan 未就绪）")
    try:
        CronTrigger.from_crontab(cron, timezone="Asia/Shanghai")
    except Exception as e:
        raise ValueError(f"cron 表达式非法 {cron!r}: {e}") from e

    tid = _new_task_id()
    task = ScheduledTask(
        task_id=tid,
        name=name,
        cron=cron,
        prompt=prompt,
        session_id=session_id,
        created_by=created_by,
        created_at=_now(),
        task_type=task_type,
        enabled=1,
    )

    redis = get_redis()
    # 1) 写元数据 HASH
    redis.hset(SCHEDULED_META_PREFIX + tid, mapping=task.to_hset_mapping())
    # 2) 加入 SET
    redis.sadd(SCHEDULED_TASKS_SET, tid)
    # 3) 注册到 APScheduler（延迟 import handlers 避免循环）
    from .handlers import handle_send_message

    get_scheduler().add_job(
        handle_send_message,
        trigger=CronTrigger.from_crontab(cron, timezone="Asia/Shanghai"),
        id=tid,
        args=[tid],                  # handler 第一参数是 task_id
        replace_existing=True,
    )
    logger.info(f"[scheduler] add_task: {name!r} (id={tid[:8]}, cron={cron!r}, sid={session_id[:8] if session_id else '<flex>'})")
    return tid


# =========================================================================
# list_tasks：列任务（支持按 session_id 过滤）
# =========================================================================


def list_tasks(session_id: Optional[str] = None) -> list[dict]:
    """
    列出任务，可按 session_id 过滤

    Returns:
        list of dict（每个 dict 是 ScheduledTask.to_api_dict() 格式）
    """
    redis = get_redis()
    all_tids = redis.smembers(SCHEDULED_TASKS_SET)
    tasks: list[dict] = []
    for tid_bytes in all_tids:
        tid = tid_bytes.decode() if isinstance(tid_bytes, bytes) else tid_bytes
        raw = redis.hgetall(SCHEDULED_META_PREFIX + tid)
        if not raw:
            # 孤儿：set 里有但 meta 已不在（外部 DEL 后遗漏），跳过
            continue
        task = ScheduledTask.from_hgetall(tid, raw)
        if task is None:
            continue
        if session_id and task.session_id != session_id:
            continue
        tasks.append(task.to_api_dict())
    return tasks


# =========================================================================
# get_task：单个任务详情（含 history）
# =========================================================================


def get_task(task_id: str, with_history: bool = False) -> Optional[dict]:
    """
    获取单个任务详情

    Args:
        task_id: 支持前缀匹配（取第一个匹配项，方便 MCP/CLI 使用）
        with_history: True 时附加最近 10 条 history

    Returns:
        {"task": {...}, "history": [...]} 或 None（任务不存在）
    """
    redis = get_redis()
    # 前缀匹配
    tid = _resolve_task_id(task_id)
    if tid is None:
        return None

    raw = redis.hgetall(SCHEDULED_META_PREFIX + tid)
    if not raw:
        return None
    task = ScheduledTask.from_hgetall(tid, raw)
    if task is None:
        return None

    result: dict = {"task": task.to_api_dict()}
    if with_history:
        raw_history = redis.lrange(SCHEDULED_HISTORY_PREFIX + tid, 0, 9)
        result["history"] = [json.loads(h) for h in raw_history]
    return result


# =========================================================================
# update_task：部分更新（enabled / cron）
# =========================================================================


def update_task(task_id: str, enabled: Optional[int] = None, cron: Optional[str] = None) -> bool:
    """
    更新任务字段

    Args:
        task_id: 任务 id
        enabled: 0 / 1（None 表示不修改）
        cron: 新 cron 表达式（None 表示不修改）

    Returns:
        True 成功；False 任务不存在
    """
    if get_scheduler() is None:
        raise RuntimeError("scheduler 未启动")
    tid = _resolve_task_id(task_id)
    if tid is None:
        return False

    redis = get_redis()
    meta_key = SCHEDULED_META_PREFIX + tid
    if not redis.exists(meta_key):
        return False

    if enabled is not None:
        redis.hset(meta_key, "enabled", str(int(enabled)))
        job = get_scheduler().get_job(tid)
        if job is not None:
            if int(enabled) == 0:
                job.pause()
            else:
                job.resume()

    if cron is not None:
        # 校验 cron
        try:
            trigger = CronTrigger.from_crontab(cron, timezone="Asia/Shanghai")
        except Exception as e:
            raise ValueError(f"cron 表达式非法 {cron!r}: {e}") from e
        redis.hset(meta_key, "cron", cron)
        if get_scheduler().get_job(tid) is not None:
            get_scheduler().reschedule_job(tid, trigger=trigger)

    logger.info(f"[scheduler] update_task: id={tid[:8]}, enabled={enabled}, cron={cron}")
    return True


# =========================================================================
# delete_task：删除（清 APScheduler + 元数据 + history + 防重入锁）
# =========================================================================


def delete_task(task_id: str) -> bool:
    """删除任务（清两层：APScheduler + 应用元数据）

    Returns:
        True 成功；False 任务不存在
    """
    if get_scheduler() is None:
        raise RuntimeError("scheduler 未启动")
    tid = _resolve_task_id(task_id)
    if tid is None:
        return False

    redis = get_redis()
    meta_key = SCHEDULED_META_PREFIX + tid
    if not redis.exists(meta_key):
        return False

    # 1) APScheduler 删 job（删 HASH + ZREM ZSET）
    try:
        get_scheduler().remove_job(tid)
    except Exception as e:
        logger.warning(f"[scheduler] remove_job 失败（task={tid[:8]}）: {e}")

    # 2) 应用层删元数据
    redis.delete(meta_key)
    redis.delete(SCHEDULED_HISTORY_PREFIX + tid)
    redis.delete(SCHEDULED_LOCK_PREFIX + tid)
    redis.srem(SCHEDULED_TASKS_SET, tid)

    logger.info(f"[scheduler] delete_task: id={tid[:8]}")
    return True


# =========================================================================
# run_task_now：手动触发一次（不修改 cron）
# =========================================================================


def run_task_now(task_id: str) -> bool:
    """手动触发一次任务（不影响原 cron 调度）"""
    if get_scheduler() is None:
        raise RuntimeError("scheduler 未启动")
    tid = _resolve_task_id(task_id)
    if tid is None:
        return False

    redis = get_redis()
    meta_key = SCHEDULED_META_PREFIX + tid
    if not redis.exists(meta_key):
        return False

    # 复用 APScheduler 自带的"立即触发"机制（modify_next_run_time → now）
    from .handlers import handle_send_message

    job = get_scheduler().get_job(tid)
    if job is None:
        # 元数据存在但 APScheduler 没注册（手动触发 add_job 后被 clear 了？）—— 重新注册
        raw = redis.hgetall(meta_key)
        task = ScheduledTask.from_hgetall(tid, raw)
        if task is None:
            return False
        get_scheduler().add_job(
            handle_send_message,
            trigger=CronTrigger.from_crontab(task.cron, timezone="Asia/Shanghai"),
            id=tid,
            args=[tid],
            replace_existing=True,
        )

    get_scheduler().modify_job(tid, next_run_time=_now())
    logger.info(f"[scheduler] run_task_now: id={tid[:8]}")
    return True


# =========================================================================
# 内部：task_id 前缀匹配
# =========================================================================


def _resolve_task_id(task_id: str) -> Optional[str]:
    """task_id 完整匹配或前缀匹配；返回完整 task_id 或 None"""
    redis = get_redis()
    # 1) 完整匹配优先
    if redis.exists(SCHEDULED_META_PREFIX + task_id):
        return task_id
    # 2) 前缀匹配（取第一个）
    for tid_bytes in redis.smembers(SCHEDULED_TASKS_SET):
        tid = tid_bytes.decode() if isinstance(tid_bytes, bytes) else tid_bytes
        if tid.startswith(task_id):
            return tid
    return None