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
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
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
        if file.stat().st_mtime < cutoff:
            size = file.stat().st_size
            file.unlink()
            removed += 1
            freed_size += size

    return removed, freed_size


def clean_logs(days: int = 3) -> tuple[int, float]:
    """清理日志目录中过期的日志文件"""
    log_dir = get_log_dir()
    if not log_dir.exists():
        return 0, 0

    removed = 0
    freed_size = 0
    today = datetime.now().date()
    cutoff = today - timedelta(days=days)

    for file in log_dir.iterdir():
        if not file.is_file():
            continue
        try:
            file_date = datetime.strptime(file.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            size = file.stat().st_size
            file.unlink()
            removed += 1
            freed_size += size

    return removed, freed_size


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

    if cache_removed == 0 and log_removed == 0:
        logger.debug("无文件需要清理")


def _start_scheduler():
    """启动调度器"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _cleanup_task,
        trigger=CronTrigger(hour=0, minute=0),
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
    logger.info("清理调度器已启动（每天凌晨 3 点执行）")

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

    return {
        "cache_dir": str(cache_dir),
        "cache_files": cache_count,
        "log_dir": str(log_dir),
        "log_files": log_count,
        "scheduler_running": _scheduler is not None and _scheduler.running,
    }
