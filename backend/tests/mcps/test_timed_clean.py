"""Tests for ChatMe.APIRouter.timed_clean — covers clean_logs / clean_thinking_chain_logs / _cleanup_task.

These tests monkeypatch `get_log_dir` to redirect to a tmp_path so they don't
touch the real `.chatme/logs/` directory.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ChatMe.APIRouter import timed_clean


@pytest.fixture
def fake_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect get_log_dir() to tmp_path and seed a few representative files."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(timed_clean, "get_log_dir", lambda: log_dir)
    return log_dir


def _date_offset(days_ago: int) -> str:
    return (datetime.now().astimezone().date() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def test_clean_thinking_chain_logs_keeps_only_newest_when_multiple(fake_log_dir: Path):
    """多个文件时只保留最新的 1 个。"""
    (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").write_text("today")
    (fake_log_dir / f"thinking_chain-{_date_offset(1)}.log").write_text("yesterday")
    (fake_log_dir / f"thinking_chain-{_date_offset(3)}.log").write_text("3 days ago")

    removed, freed = timed_clean.clean_thinking_chain_logs()

    assert removed == 2
    assert (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").exists()
    assert not (fake_log_dir / f"thinking_chain-{_date_offset(1)}.log").exists()
    assert not (fake_log_dir / f"thinking_chain-{_date_offset(3)}.log").exists()
    assert freed > 0


def test_clean_thinking_chain_logs_keeps_only_file_when_singleton(fake_log_dir: Path):
    """只剩 1 个文件时不动（兜底，避免删完没任何日志可看）。"""
    (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").write_text("today")

    removed, freed = timed_clean.clean_thinking_chain_logs()

    assert removed == 0
    assert freed == 0
    assert (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").exists()


def test_clean_thinking_chain_logs_keeps_newest_when_only_old_files(fake_log_dir: Path):
    """即使所有文件都"旧"（没有今天的），也保留日期最新那个。"""
    (fake_log_dir / f"thinking_chain-{_date_offset(2)}.log").write_text("2 days ago")
    (fake_log_dir / f"thinking_chain-{_date_offset(5)}.log").write_text("5 days ago")
    (fake_log_dir / f"thinking_chain-{_date_offset(10)}.log").write_text("10 days ago")

    removed, _ = timed_clean.clean_thinking_chain_logs()

    assert removed == 2
    assert (fake_log_dir / f"thinking_chain-{_date_offset(2)}.log").exists()
    assert not (fake_log_dir / f"thinking_chain-{_date_offset(5)}.log").exists()
    assert not (fake_log_dir / f"thinking_chain-{_date_offset(10)}.log").exists()


def test_clean_thinking_chain_logs_does_not_touch_main_logs(fake_log_dir: Path):
    """thinking_chain 清理不动主 YYYY-MM-DD.log（即使过期了）。"""
    (fake_log_dir / f"{_date_offset(0)}.log").write_text("main today")
    (fake_log_dir / f"{_date_offset(5)}.log").write_text("main 5 days ago")
    (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").write_text("tc today")
    (fake_log_dir / f"thinking_chain-{_date_offset(5)}.log").write_text("tc 5 days ago")

    timed_clean.clean_thinking_chain_logs()

    # 主日志 5 天前的应保留（clean_thinking_chain_logs 不管主日志）
    assert (fake_log_dir / f"{_date_offset(5)}.log").exists()
    # thinking_chain 5 天前的应删（多个文件 → 只留最新）
    assert not (fake_log_dir / f"thinking_chain-{_date_offset(5)}.log").exists()


def test_clean_thinking_chain_logs_ignores_pending_dir(fake_log_dir: Path):
    """thinking_chain-pending/ 是 per-session 临时缓冲目录，必须不被清理。"""
    pending = fake_log_dir / "thinking_chain-pending"
    pending.mkdir()
    (pending / "abc12345.log").write_text("pending")
    (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").write_text("today")
    (fake_log_dir / f"thinking_chain-{_date_offset(3)}.log").write_text("3 days ago")

    removed, _ = timed_clean.clean_thinking_chain_logs()

    assert removed == 1
    assert (pending / "abc12345.log").exists()


def test_clean_thinking_chain_logs_ignores_malformed_stems(fake_log_dir: Path):
    """stem 不匹配 thinking_chain-YYYY-MM-DD 格式的文件不动。"""
    (fake_log_dir / "thinking_chain-foo.log").write_text("bad stem")
    (fake_log_dir / "thinking_chain.log").write_text("no date")
    (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").write_text("today")
    (fake_log_dir / f"thinking_chain-{_date_offset(3)}.log").write_text("3 days ago")

    removed, _ = timed_clean.clean_thinking_chain_logs()

    assert removed == 1
    assert (fake_log_dir / "thinking_chain-foo.log").exists()
    assert (fake_log_dir / "thinking_chain.log").exists()


def test_clean_thinking_chain_logs_returns_zero_when_log_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """log_dir 不存在时返 (0, 0) 不报错。"""
    missing = tmp_path / "nonexistent"
    monkeypatch.setattr(timed_clean, "get_log_dir", lambda: missing)

    assert timed_clean.clean_thinking_chain_logs() == (0, 0)


def test_clean_logs_skips_thinking_chain_files(fake_log_dir: Path):
    """clean_logs 显式跳过 thinking_chain-* 文件（由 clean_thinking_chain_logs 负责）。"""
    (fake_log_dir / f"{_date_offset(0)}.log").write_text("main today")
    (fake_log_dir / f"{_date_offset(10)}.log").write_text("main 10 days")
    (fake_log_dir / f"thinking_chain-{_date_offset(10)}.log").write_text("tc 10 days")

    removed, _ = timed_clean.clean_logs(days=3)

    assert removed == 1  # 主日志 10 天前被删
    assert not (fake_log_dir / f"{_date_offset(10)}.log").exists()
    assert (fake_log_dir / f"thinking_chain-{_date_offset(10)}.log").exists()  # thinking_chain 不动


def test_cleanup_task_runs_thinking_chain_cleanup(fake_log_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """_cleanup_task 应在同一定时任务里同时跑 clean_logs 和 clean_thinking_chain_logs。"""
    # 阻止真实 Redis 连接（clean_memory / clean_orphaned_sessions 会用到）
    monkeypatch.setattr(timed_clean, "clean_memory", lambda days=30: (0, 0))

    async def fake_orphan():
        return 0, []
    monkeypatch.setattr(timed_clean, "clean_orphaned_sessions", fake_orphan)

    (fake_log_dir / f"{_date_offset(5)}.log").write_text("main old")
    (fake_log_dir / f"thinking_chain-{_date_offset(5)}.log").write_text("tc old")
    (fake_log_dir / f"thinking_chain-{_date_offset(10)}.log").write_text("tc older")
    (fake_log_dir / f"{_date_offset(0)}.log").write_text("main today")
    (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").write_text("tc today")

    asyncio.run(timed_clean._cleanup_task())

    # 主日志保留 3 天 → 5 天前的删
    assert not (fake_log_dir / f"{_date_offset(5)}.log").exists()
    # thinking_chain 多个文件 → 保留最新（today），其余删
    assert not (fake_log_dir / f"thinking_chain-{_date_offset(5)}.log").exists()
    assert not (fake_log_dir / f"thinking_chain-{_date_offset(10)}.log").exists()
    # 当天的主日志和 thinking_chain 都保留
    assert (fake_log_dir / f"{_date_offset(0)}.log").exists()
    assert (fake_log_dir / f"thinking_chain-{_date_offset(0)}.log").exists()