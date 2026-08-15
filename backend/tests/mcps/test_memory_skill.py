"""
Tests for skills/Memory — focus on concurrency invariants.

Why this matters: remember() is a fire-and-forget side-effect tool that
the prompt explicitly tells the agent can "run in parallel with main
task". To make that safe with multiple remember() calls in one batch
(or concurrent calls from concurrent LLM tool dispatches), the
read-modify-write cycle must be serialized per file. Without the lock,
two threads calling remember() with different keys would both read the
empty file, both append their own key, and last writer wins — losing
the other entry.

These tests pin the invariant: under N concurrent remember() calls
with distinct keys, all N entries must be persisted.
"""
import threading
from pathlib import Path

import pytest

from skills import Memory
from skills.Memory import _file_locks, remember


@pytest.fixture(autouse=True)
def isolated_memory_dir(tmp_path, monkeypatch):
    """Redirect memory writes to a tmp directory so we don't pollute the
    real .chatme/memory/ on disk."""
    monkeypatch.setattr(Memory, "_THREAD_MEMORY_DIR", tmp_path)
    monkeypatch.setattr(Memory, "_GLOBAL_MEMORY_DIR", tmp_path / "global")
    # Reset per-file lock registry so test paths don't collide with
    # leftover locks from earlier tests.
    _file_locks.clear()
    yield
    _file_locks.clear()


def test_concurrent_remember_persists_all_keys(tmp_path):
    """N threads each call remember() with a distinct key. After all
    threads complete, every entry must be on disk — no lost writes.
    """
    n_threads = 20
    thread_id = "abc123"
    errors: list[Exception] = []
    barrier = threading.Barrier(n_threads)

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=5)
            remember(
                key=f"key-{i:03d}",
                value=f"value-{i:03d}",
                thread_id=thread_id,
                category="facts",
                scope="thread",
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"worker errors: {errors}"

    facts = (tmp_path / thread_id / "facts.md").read_text(encoding="utf-8")
    missing = [f"key-{i:03d}" for i in range(n_threads) if f"key-{i:03d}" not in facts]
    assert not missing, f"lost writes under concurrency: {missing}"


def test_concurrent_remember_same_key_converges(tmp_path):
    """N threads each call remember() with the SAME key but different
    values. Lock must serialize RMW so the final file has exactly one
    entry for that key, and the file is structurally valid (no torn
    entries, no duplicate - key: lines).
    """
    n_threads = 20
    thread_id = "abc123"
    barrier = threading.Barrier(n_threads)

    def worker(i: int) -> None:
        barrier.wait(timeout=5)
        remember(
            key="shared",
            value=f"value-{i:03d}",
            thread_id=thread_id,
            category="facts",
            scope="thread",
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    facts = (tmp_path / thread_id / "facts.md").read_text(encoding="utf-8")
    # Same key → 应只剩 1 条（upsert 语义）
    assert facts.count("- shared:") == 1, f"expected exactly 1 entry, got:\n{facts}"
    # 写入内容应是某个 worker 的 value，不应被半截
    assert "value-" in facts


def test_concurrent_writes_to_different_files_dont_block_each_other(tmp_path):
    """不同文件（thread facts / preference / global facts / preference）
    各自有独立锁，并发写互不阻塞 —— 4 个不同文件可同时落盘。
    """
    file_count = 4
    barrier = threading.Barrier(file_count)
    errors: list[Exception] = []

    def worker(i: int, scope: str, category: str) -> None:
        try:
            barrier.wait(timeout=5)
            remember(
                key=f"key-{i}",
                value=f"value-{i}",
                thread_id="t1",
                category=category,
                scope=scope,
            )
        except Exception as e:
            errors.append(e)

    cfgs = [
        ("thread", "facts"),
        ("thread", "preference"),
        ("global", "facts"),
        ("global", "preference"),
    ]
    threads = [threading.Thread(target=worker, args=(i, s, c)) for i, (s, c) in enumerate(cfgs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"worker errors: {errors}"

    # Each path should have its single entry
    assert (tmp_path / "t1" / "facts.md").exists()
    assert (tmp_path / "t1" / "preference.md").exists()
    assert (tmp_path / "global" / "facts.md").exists()
    assert (tmp_path / "global" / "preference.md").exists()
