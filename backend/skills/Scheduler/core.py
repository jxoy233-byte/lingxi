"""
SchedulerService 生命周期管理

设计要点：
- 模块级 _scheduler 单例（与 timed_clean.py 同款风格）
- APScheduler + RedisJobStore（jobs 持久化到 Redis，进程重启自动恢复）
- scheduler_lifespan(app) 在 chat_service_lifespan 之内启动
- TZ 硬编码 Asia/Shanghai（与 timed_clean.py 一致）
- misfire_grace_time=300 + coalesce=True + max_instances=1 防堆积 + 防并发
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional

import redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from ChatMe.ChatMeConfig import get_redis_checkpointer_url
from ChatMe.LoggingManager.logging_config import get_logger

from .models import (
    APSCHEDULER_JOBS_KEY,
    APSCHEDULER_RUN_TIMES_KEY,
)

logger = get_logger("Scheduler")

# 模块级单例
_scheduler: Optional[AsyncIOScheduler] = None

# Redis 连接（handler / registry 共用）
_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """拿 Redis 客户端（懒初始化）"""
    global _redis_client
    if _redis_client is None:
        url = get_redis_checkpointer_url()
        _redis_client = redis.from_url(url)
    return _redis_client


def _parse_redis_url(url: str) -> dict:
    """
    从 redis://:password@host:port/db 解析出 RedisJobStore 需要的连接参数

    RedisJobStore 用 redis.Redis(db=int(db), password=..., host=..., port=...)
    直接传 redis_url 也可以，但显式传更清晰
    """
    # redis://:123456@localhost:6024/0
    if not url.startswith("redis://"):
        return {}
    rest = url[len("redis://"):]
    # 拆 auth@host:port/db
    if "@" in rest:
        auth, host_part = rest.split("@", 1)
        password = auth[1:] if auth.startswith(":") else auth
    else:
        password = None
        host_part = rest
    if "/" in host_part:
        hp, db_str = host_part.rsplit("/", 1)
        try:
            db = int(db_str)
        except ValueError:
            db = 0
    else:
        hp, db = host_part, 0
    if ":" in hp:
        host, port_str = hp.split(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 6379
    else:
        host, port = hp, 6379
    return {
        "db": db,
        "password": password,
        "host": host,
        "port": port,
    }


def start_scheduler() -> AsyncIOScheduler:
    """启动调度器（幂等：第二次调用返回已启动的单例）"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    url = get_redis_checkpointer_url()
    conn_args = _parse_redis_url(url)

    _scheduler = AsyncIOScheduler(
        event_loop=asyncio.get_running_loop(),
        jobstores={
            "default": RedisJobStore(
                jobs_key=APSCHEDULER_JOBS_KEY,
                run_times_key=APSCHEDULER_RUN_TIMES_KEY,
                **conn_args,
            ),
        },
        job_defaults={
            "coalesce": True,           # 多次错过合并 1 次
            "max_instances": 1,         # 防并发
            "misfire_grace_time": 300,  # 5 分钟内补跑
        },
        timezone="Asia/Shanghai",
    )
    _scheduler.start()
    logger.info(
        f"[scheduler] APScheduler 启动: jobs_key={APSCHEDULER_JOBS_KEY}, "
        f"run_times_key={APSCHEDULER_RUN_TIMES_KEY}, "
        f"redis={conn_args.get('host')}:{conn_args.get('port')}/{conn_args.get('db')}, "
        f"TZ=Asia/Shanghai, misfire_grace=300s, coalesce=True, max_instances=1"
    )
    return _scheduler


def stop_scheduler() -> None:
    """关闭调度器（幂等）"""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception as e:
        logger.warning(f"[scheduler] 关闭异常: {e}")
    finally:
        _scheduler = None
        logger.info("[scheduler] APScheduler 已关闭")


def get_scheduler() -> AsyncIOScheduler:
    """拿调度器实例（未启动时返回 None）"""
    return _scheduler


@asynccontextmanager
async def scheduler_lifespan(app: FastAPI):
    """FastAPI lifespan：启动调度器，yield，关闭调度器

    必须嵌套在 chat_service_lifespan 之内——因为 handler 要用 chat_service.message_stream。
    放在 main.py 的 lifespan 组合里：

        async with chat_service_lifespan(app):
            async with scheduler_lifespan(app):   # ← 这里
                async with cleanup_lifespan(app):
                    yield
    """
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()