"""
定时清理任务
- 缓存文件：清理 30 天未访问的文件
- 日志文件：清理 3 天前的日志

使用方式：
    from contextlib import asynccontextmanager
    from ChatMe.APIRouter.timed_clean import cleanup_lifespan

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI):
        async with cleanup_lifespan(app):
            yield

    app = FastAPI(lifespan=combined_lifespan)
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from ..LoggingManager.logging_config import get_logger

# 调度器单例
_scheduler: Optional[AsyncIOScheduler] = None


# ============================================================
# 核心清理函数
# ============================================================

def get_cache_dir() -> Path:
    """获取缓存目录"""
    return Path.cwd() / "cached"


def get_log_dir() -> Path:
    """获取日志目录"""
    return Path.cwd() / ".chatme" / "logs"


def get_memory_dir() -> Path:
    """获取记忆文件目录"""
    return Path.cwd() / ".chatme" / "memory"


def touch_file(path: Path):
    """
    刷新文件时间戳，让文件保持"活跃"状态
    配合清理任务：活跃文件不会被删除
    """
    try:
        os.utime(path, None)
    except OSError:
        pass


def clean_cache(days: int = 30) -> tuple[int, float]:
    """清理缓存目录中长期未访问的文件"""
    cache_dir = get_cache_dir()
    if not cache_dir.exists():
        return 0, 0

    cutoff = time.time() - days * 86400
    removed = 0
    freed_size = 0

    for file in cache_dir.iterdir():
        if not file.is_file():
            continue
        if file.stat().st_mtime <= cutoff:
            size = file.stat().st_size
            file.unlink()
            removed += 1
            freed_size += size

    return removed, freed_size


def clean_logs(days: int = 2) -> tuple[int, float]:
    """清理日志目录中过期的日志文件"""
    log_dir = get_log_dir()
    if not log_dir.exists():
        return 0, 0

    removed = 0
    freed_size = 0
    today = datetime.now().astimezone().date()
    cutoff = today - timedelta(days=days)

    for file in log_dir.iterdir():
        if not file.is_file():
            continue
        try:
            file_date = datetime.strptime(file.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date <= cutoff:
            size = file.stat().st_size
            file.unlink()
            removed += 1
            freed_size += size

    return removed, freed_size


def clean_memory(days: int = 30) -> tuple[int, float]:
    """
    清理记忆目录中长期未访问的 session 记忆文件。
    记忆目录结构: .chatme/memory/{session_id}/
    如果某个 session_id 在 Redis 中已不存在，则删除对应的记忆目录。
    """
    import shutil
    memory_dir = get_memory_dir()
    if not memory_dir.exists():
        return 0, 0

    import redis
    from ChatMe.ChatMeConfig import get_redis_checkpointer_url

    redis_url = get_redis_checkpointer_url()
    r = redis.from_url(redis_url)

    # 从 Redis 中扫描所有 checkpoint key，提取活跃的 session_id
    active_ids: set[str] = set()
    for key in r.scan_iter(match="checkpoint:*", count=1000):
        parts = key.decode().split(":")
        if len(parts) >= 2:
            active_ids.add(parts[1])

    removed = 0
    freed_size = 0
    for item in memory_dir.iterdir():
        if not item.is_dir():
            continue
        # 如果 session_id 不在活跃列表中，删除整个目录
        if item.name not in active_ids:
            size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            shutil.rmtree(item)
            removed += 1
            freed_size += size

    return removed, freed_size


async def clean_orphaned_sessions() -> tuple[int, list[str]]:
    """
    清理 cached 目录下已无对应会话记录的 session 目录，
    以及直接位于 cached/ 下的孤立文件。
    直接扫描 Redis 中的 checkpoint key，提取所有 session_id，
    删除 cached/{session_id} 目录中不在活跃列表中的目录，
    同时删除 cached/ 根目录下不在任何活跃 session 中的孤立文件。
    """
    import redis
    import shutil
    from ChatMe.ChatMeConfig import get_redis_checkpointer_url

    cache_dir = get_cache_dir()
    if not cache_dir.exists():
        return 0, []

    redis_url = get_redis_checkpointer_url()
    r = redis.from_url(redis_url)

    # 从 Redis 中扫描所有 checkpoint 相关的 key，提取 session_id
    # key 格式: checkpoint:{thread_id}:{ns}:{id}
    active_ids: set[str] = set()
    for key in r.scan_iter(match="checkpoint:*", count=1000):
        parts = key.decode().split(":")
        if len(parts) >= 2:
            active_ids.add(parts[1])

    white_id = {}
    removed_names = []
    for item in cache_dir.iterdir():
        if item.is_dir() and item.name not in active_ids:
            shutil.rmtree(item)
            removed_names.append(item.name)
        elif item.is_file() and item.name not in white_id:
            item.unlink()
            removed_names.append(item.name)

    return len(removed_names), removed_names


# ============================================================
# 调度器管理
# ============================================================

async def _cleanup_task():
    """每日清理任务"""
    logger = get_logger("CleanupScheduler")

    cache_removed, cache_freed = clean_cache(days=30)
    if cache_removed > 0:
        logger.info(
            f"缓存清理完成: 删除 {cache_removed} 个文件，"
            f"释放 {cache_freed / 1024 / 1024:.2f} MB"
        )

    log_removed, log_freed = clean_logs(days=3)
    if log_removed > 0:
        logger.info(
            f"日志清理完成: 删除 {log_removed} 个文件，"
            f"释放 {log_freed / 1024 / 1024:.2f} MB"
        )

    memory_removed, memory_freed = clean_memory(days=30)
    if memory_removed > 0:
        logger.info(
            f"记忆清理完成: 删除 {memory_removed} 个会话记忆，"
            f"释放 {memory_freed / 1024 / 1024:.2f} MB"
        )

    orphaned_removed, orphaned_names = await clean_orphaned_sessions()
    if orphaned_removed > 0:
        logger.info(f"孤立会话清理完成: 删除 {orphaned_removed} 个目录 {orphaned_names}")
    else:
        logger.debug("无孤立会话目录需要清理")

    if cache_removed == 0 and log_removed == 0 and memory_removed == 0 and orphaned_removed == 0:
        logger.debug("无文件需要清理")


def _start_scheduler():
    """启动调度器"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop())
    _scheduler.add_job(
        _cleanup_task,
        trigger=CronTrigger(hour=23, minute=30, timezone='Asia/Shanghai'),
        id="daily_cleanup",
        name="每日缓存和日志清理",
        replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def _stop_scheduler():
    """关闭调度器"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None


# ============================================================
# Lifespan（供主 app 组合使用）
# ============================================================

@asynccontextmanager
async def cleanup_lifespan(app: FastAPI):
    """定时清理任务的 lifespan"""
    logger = get_logger("CleanupScheduler")

    _start_scheduler()
    logger.info("清理调度器已启动（每天 23 点 30 点执行）")

    yield

    _stop_scheduler()
    logger.info("清理调度器已关闭")


# ============================================================
# APIRouter（可选的管理接口）
# ============================================================

from fastapi import APIRouter

cleanup_router = APIRouter(prefix="/admin", tags=["管理"])


@cleanup_router.post("/cleanup", summary="手动触发清理任务")
async def trigger_cleanup():
    """手动触发一次清理任务"""
    await _cleanup_task()
    return {"message": "清理任务已执行"}


@cleanup_router.get("/cleanup/status", summary="获取清理状态")
async def get_cleanup_status():
    """获取当前缓存和日志的统计信息"""
    cache_dir = get_cache_dir()
    log_dir = get_log_dir()

    cache_count = sum(1 for f in cache_dir.iterdir() if f.is_file()) if cache_dir.exists() else 0
    log_count = sum(1 for f in log_dir.iterdir() if f.is_file() and f.suffix == ".log") if log_dir.exists() else 0

    # 统计 session 目录数量
    session_count = sum(1 for d in cache_dir.iterdir() if d.is_dir()) if cache_dir.exists() else 0

    return {
        "cache_dir": str(cache_dir),
        "cache_files": cache_count,
        "log_dir": str(log_dir),
        "log_files": log_count,
        "cached_session_dirs": session_count,
        "scheduler_running": _scheduler is not None and _scheduler.running,
    }
