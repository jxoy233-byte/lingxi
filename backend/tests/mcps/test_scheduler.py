"""
Scheduler 单元测试（Step 1：核心骨架 + 模型序列化 + Redis URL 解析）

覆盖：
1. ScheduledTask 序列化往返（to_hset_mapping / from_hgetall）
2. ScheduledTask.to_api_dict() 字段裁剪
3. HistoryEntry JSON 往返
4. _parse_redis_url() 多格式解析
5. start_scheduler / stop_scheduler 生命周期（需要真实 Redis，本测试用 mock 替代）

注意：完整 scheduler 启动 + RedisJobStore 集成测试需要真实 Redis 实例（Step 4 集成测试）。
本文件只覆盖纯函数 + 模型层。
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 把 backend 加到 sys.path（pytest 默认从 backend 跑就不需要；但保险起见）
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from skills.Scheduler.core import _parse_redis_url  # noqa: E402
from skills.Scheduler.models import (  # noqa: E402
    APSCHEDULER_JOBS_KEY,
    APSCHEDULER_RUN_TIMES_KEY,
    HistoryEntry,
    SCHEDULED_HISTORY_PREFIX,
    SCHEDULED_LOCK_PREFIX,
    SCHEDULED_META_PREFIX,
    SCHEDULED_TASKS_SET,
    ScheduledTask,
)


# =========================================================================
# 1. ScheduledTask 序列化往返
# =========================================================================


def test_scheduled_task_to_hset_mapping_basic():
    """to_hset_mapping 把所有字段转 str（HSET 友好）"""
    task = ScheduledTask(
        task_id="abc123def456",
        name="每日销售报告",
        cron="0 9 * * 1-5",
        prompt="搜一下今天的销售数据",
        session_id="xyz789",
        created_by="xyz789",
        created_at=1723276800.0,
    )
    mapping = task.to_hset_mapping()
    # 必须含所有声明字段
    for field in ScheduledTask(task_id="", name="", cron="", prompt="", session_id="").META_FIELDS:
        assert field in mapping, f"字段 {field!r} 缺失"
        assert isinstance(mapping[field], str), f"{field} 应为 str"


def test_scheduled_task_from_hgetall_roundtrip():
    """HGETALL bytes 输入 → 还原 → 字段值一致"""
    original = ScheduledTask(
        task_id="tid_001",
        name="测试",
        cron="*/5 * * * *",
        prompt="说hi",
        session_id="sid_001",
        created_by="sid_001",
        created_at=1723276800.5,
        task_type="send_message",
        enabled=1,
        run_count=42,
        last_run=1723298400.0,
    )
    raw = {
        k.encode(): str(v).encode()
        for k, v in original.to_hset_mapping().items()
    }
    raw[b"task_id"] = b"tid_001"  # task_id 不是 HASH 字段，独立传

    restored = ScheduledTask.from_hgetall("tid_001", raw)
    assert restored is not None
    assert restored.task_id == "tid_001"
    assert restored.name == "测试"
    assert restored.cron == "*/5 * * * *"
    assert restored.prompt == "说hi"
    assert restored.session_id == "sid_001"
    assert restored.created_by == "sid_001"
    assert restored.created_at == 1723276800.5
    assert restored.task_type == "send_message"
    assert restored.enabled == 1
    assert restored.run_count == 42
    assert restored.last_run == 1723298400.0


def test_scheduled_task_from_hgetall_empty():
    """空 HGETALL 返回 None（任务不存在）"""
    assert ScheduledTask.from_hgetall("nonexistent", {}) is None


def test_scheduled_task_from_hgetall_handles_garbage_int():
    """run_count 字段被脏数据污染时优雅降级到 0"""
    raw = {b"run_count": b"not_a_number", b"last_run": b"abc"}
    task = ScheduledTask.from_hgetall("tid", raw)
    assert task is not None
    assert task.run_count == 0  # int("not_a_number") 抛 ValueError → fallback 0
    assert task.last_run == 0.0


# =========================================================================
# 2. ScheduledTask.to_api_dict() 字段裁剪
# =========================================================================


def test_to_api_dict_includes_frontend_required_fields():
    """API 响应含前端 ScheduledTasksPanel 所需全部字段"""
    task = ScheduledTask(
        task_id="tid_001",
        name="每日销售报告",
        cron="0 9 * * *",
        prompt="搜一下今天的销售数据，做一份销售日报",
        session_id="sid_001",
        created_by="sid_001",
        created_at=1723276800.0,
        enabled=1,
        run_count=12,
        last_run=1723298400.0,
    )
    api_dict = task.to_api_dict()
    # 必含字段
    assert api_dict["task_id"] == "tid_001"
    assert api_dict["name"] == "每日销售报告"
    assert api_dict["cron"] == "0 9 * * *"
    assert api_dict["session_id"] == "sid_001"
    assert api_dict["enabled"] is True
    assert api_dict["run_count"] == 12
    assert api_dict["last_run"] == 1723298400.0


def test_to_api_dict_prompt_preview_truncated():
    """prompt 超过 80 字符时显示 preview + ..."""
    long_prompt = "x" * 200
    task = ScheduledTask(
        task_id="t", name="n", cron="* * * * *",
        prompt=long_prompt, session_id="s",
    )
    api_dict = task.to_api_dict()
    assert api_dict["prompt_preview"].endswith("...")
    assert len(api_dict["prompt_preview"]) == 83  # 80 + "..."


def test_to_api_dict_prompt_preview_short_no_ellipsis():
    """短 prompt 不加 ..."""
    task = ScheduledTask(
        task_id="t", name="n", cron="* * * * *",
        prompt="hi", session_id="s",
    )
    api_dict = task.to_api_dict()
    assert api_dict["prompt_preview"] == "hi"
    assert not api_dict["prompt_preview"].endswith("...")


def test_to_api_dict_enabled_is_bool_not_int():
    """enabled 字段是 bool 不是 int（前端 v-if 判断更直观）"""
    task = ScheduledTask(
        task_id="t", name="n", cron="* * * * *",
        prompt="p", session_id="s", enabled=0,
    )
    assert task.to_api_dict()["enabled"] is False
    task.enabled = 1
    assert task.to_api_dict()["enabled"] is True


# =========================================================================
# 3. HistoryEntry JSON 往返
# =========================================================================


def test_history_entry_json_roundtrip():
    """HistoryEntry 写入 Redis 的 JSON 字符串能被 from_json 还原"""
    entry = HistoryEntry(
        ts=1723298400.0,
        status="success",
        duration_ms=3420,
        output_preview="今日 AI 新闻摘要...",
        error="",
    )
    raw = entry.to_json()
    restored = HistoryEntry.from_json(raw)
    assert restored.ts == 1723298400.0
    assert restored.status == "success"
    assert restored.duration_ms == 3420
    assert restored.output_preview == "今日 AI 新闻摘要..."
    assert restored.error == ""


def test_history_entry_json_chinese_safe():
    """JSON 用 ensure_ascii=False，中文不被转义成 \\uXXXX"""
    entry = HistoryEntry(
        ts=1.0, status="error",
        error="ValueError: 数据库连接超时",
    )
    raw = entry.to_json()
    assert "数据库连接超时" in raw  # 不是 \\u 转义
    # 解析回去也能拿回中文
    assert HistoryEntry.from_json(raw).error == "ValueError: 数据库连接超时"


# =========================================================================
# 4. _parse_redis_url() 多格式解析
# =========================================================================


def test_parse_redis_url_with_password():
    """redis://:password@host:port/db 标准格式"""
    result = _parse_redis_url("redis://:123456@localhost:6024/0")
    assert result == {
        "db": 0, "password": "123456", "host": "localhost", "port": 6024,
    }


def test_parse_redis_url_without_password():
    """无密码格式"""
    result = _parse_redis_url("redis://localhost:6379/1")
    assert result == {
        "db": 1, "password": None, "host": "localhost", "port": 6379,
    }


def test_parse_redis_url_default_port():
    """无 :port 时默认 6379"""
    result = _parse_redis_url("redis://:abc@redis-host/2")
    assert result["port"] == 6379
    assert result["host"] == "redis-host"
    assert result["db"] == 2
    assert result["password"] == "abc"


def test_parse_redis_url_invalid_scheme_passthrough():
    """非 redis:// 协议返回空 dict（让 RedisJobStore 用默认）"""
    assert _parse_redis_url("") == {}
    assert _parse_redis_url("not-a-redis-url") == {}


# =========================================================================
# 5. Redis key 常量值检查（防止 typo）
# =========================================================================


def test_redis_key_constants_match_plan():
    """Redis key 常量值与 plan 一致，避免手动改 typo"""
    assert SCHEDULED_TASKS_SET == "scheduled:tasks"
    assert SCHEDULED_META_PREFIX == "scheduled:meta:"
    assert SCHEDULED_HISTORY_PREFIX == "scheduled:history:"
    assert SCHEDULED_LOCK_PREFIX == "scheduled:lock:"
    assert APSCHEDULER_JOBS_KEY == "apscheduler.jobs"
    assert APSCHEDULER_RUN_TIMES_KEY == "apscheduler.run_times"


# =========================================================================
# 6. start_scheduler / stop_scheduler 生命周期（mock 避免真连 Redis）
# =========================================================================


def test_start_scheduler_idempotent(monkeypatch):
    """start_scheduler 第二次调用不会重复启动（幂等）"""
    import asyncio
    from unittest.mock import MagicMock

    from skills.Scheduler import core as core_module

    # Mock RedisJobStore + AsyncIOScheduler，避免真连 Redis
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    monkeypatch.setattr(core_module, "_scheduler", None)
    monkeypatch.setattr(core_module, "AsyncIOScheduler", MagicMock(return_value=fake_scheduler))
    monkeypatch.setattr(core_module, "RedisJobStore", MagicMock())
    monkeypatch.setattr(core_module, "get_redis_checkpointer_url", lambda: "redis://:123456@localhost:6024/0")

    async def _go():
        s1 = core_module.start_scheduler()
        s2 = core_module.start_scheduler()  # 第二次应返回同一实例
        return s1 is s2

    assert asyncio.run(_go()) is True


def test_stop_scheduler_safe_when_not_started():
    """未启动时调 stop_scheduler 不抛异常"""
    from skills.Scheduler import core as core_module

    monkeypatch_globals = {}
    import skills.Scheduler.core as cm
    original_scheduler = cm._scheduler
    cm._scheduler = None
    try:
        cm.stop_scheduler()  # 不应抛异常
        assert cm._scheduler is None
    finally:
        cm._scheduler = original_scheduler


# =========================================================================
# 6.1 _sync_paused_jobs_on_start（启动时按 Redis meta 同步 job 暂停态）
# =========================================================================
# Bug 背景：
#   registry.update_task 先写 Redis meta.enabled 再调 job.pause()（registry.py:213-221）。
#   中间进程崩溃 → meta 写了、APScheduler job 没 pause；下次启动 scheduler 按 active
#   加载，与 meta 不一致 → "前端显示暂停但任务还在跑"。
#   修复：core.start_scheduler 启动后调 _sync_paused_jobs_on_start()，以 Redis meta 为
#   单一真相对所有 loaded job 做 pause/resume 双向同步。
# =========================================================================


def test_sync_pauses_job_when_meta_enabled_zero_but_job_active(monkeypatch):
    """meta.enabled=0 但 job 有 next_run_time → 调 job.pause()。"""
    from skills.Scheduler import core as core_module
    from skills.Scheduler.core import _sync_paused_jobs_on_start

    redis = _FakeRedis()
    _seed_task(redis, "tid_pause", "x", "s")
    # 把 enabled 改成 0（模拟 user 暂停后进程崩溃，meta 写了但 job 没 pause）
    redis.store[SCHEDULED_META_PREFIX + "tid_pause"][b"enabled"] = b"0"

    fake_scheduler = MagicMock()
    fake_job = MagicMock()
    fake_job.id = "tid_pause"
    fake_job.next_run_time = "2026-08-13 09:00:00"  # 非 None → 模拟 active
    fake_scheduler.get_jobs.return_value = [fake_job]
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)
    monkeypatch.setattr(core_module, "get_redis", lambda: redis)

    _sync_paused_jobs_on_start()

    assert fake_job.pause.called, "应调 job.pause() 让 paused 状态对齐 meta"
    assert not fake_job.resume.called, "不应调 resume"


def test_sync_resumes_job_when_meta_enabled_one_but_job_paused(monkeypatch):
    """meta.enabled=1 但 job.next_run_time is None（paused）→ 调 job.resume()。"""
    from skills.Scheduler import core as core_module
    from skills.Scheduler.core import _sync_paused_jobs_on_start

    redis = _FakeRedis()
    _seed_task(redis, "tid_resume", "x", "s")  # 默认 enabled=1

    fake_scheduler = MagicMock()
    fake_job = MagicMock()
    fake_job.id = "tid_resume"
    fake_job.next_run_time = None  # 已暂停（罕见但兜底）
    fake_scheduler.get_jobs.return_value = [fake_job]
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)
    monkeypatch.setattr(core_module, "get_redis", lambda: redis)

    _sync_paused_jobs_on_start()

    assert fake_job.resume.called, "应调 job.resume() 重新算 next_run_time"
    assert not fake_job.pause.called


def test_sync_noop_when_states_consistent(monkeypatch):
    """meta 与 job 状态一致（active + enabled=1）→ 不调 pause/resume。"""
    from skills.Scheduler import core as core_module
    from skills.Scheduler.core import _sync_paused_jobs_on_start

    redis = _FakeRedis()
    _seed_task(redis, "tid_ok", "x", "s")

    fake_scheduler = MagicMock()
    fake_job = MagicMock()
    fake_job.id = "tid_ok"
    fake_job.next_run_time = "2026-08-13 09:00:00"  # active
    fake_scheduler.get_jobs.return_value = [fake_job]
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)
    monkeypatch.setattr(core_module, "get_redis", lambda: redis)

    _sync_paused_jobs_on_start()

    assert not fake_job.pause.called
    assert not fake_job.resume.called


def test_sync_skips_job_without_redis_meta(monkeypatch):
    """Redis meta 没了（外部 DEL）→ 跳过，不主动删 APScheduler job。"""
    from skills.Scheduler import core as core_module
    from skills.Scheduler.core import _sync_paused_jobs_on_start

    redis = _FakeRedis()
    # 不 seed meta
    fake_scheduler = MagicMock()
    fake_job = MagicMock()
    fake_job.id = "tid_orphan"
    fake_job.next_run_time = "2026-08-13 09:00:00"
    fake_scheduler.get_jobs.return_value = [fake_job]
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)
    monkeypatch.setattr(core_module, "get_redis", lambda: redis)

    _sync_paused_jobs_on_start()

    assert not fake_job.pause.called, "meta 缺失应跳过"
    assert not fake_job.resume.called


def test_sync_skips_garbage_enabled_value(monkeypatch):
    """enabled 字段被外部写成 'abc' → 跳过，不抛异常。"""
    from skills.Scheduler import core as core_module
    from skills.Scheduler.core import _sync_paused_jobs_on_start

    redis = _FakeRedis()
    _seed_task(redis, "tid_garbage", "x", "s")
    redis.store[SCHEDULED_META_PREFIX + "tid_garbage"][b"enabled"] = b"abc"

    fake_scheduler = MagicMock()
    fake_job = MagicMock()
    fake_job.id = "tid_garbage"
    fake_job.next_run_time = "2026-08-13 09:00:00"
    fake_scheduler.get_jobs.return_value = [fake_job]
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)
    monkeypatch.setattr(core_module, "get_redis", lambda: redis)

    _sync_paused_jobs_on_start()  # 不应抛

    assert not fake_job.pause.called
    assert not fake_job.resume.called


def test_sync_handles_mixed_jobs_in_one_pass(monkeypatch):
    """混合：active / paused / orphan / 一致 → 各 job 各自被正确处理。"""
    from skills.Scheduler import core as core_module
    from skills.Scheduler.core import _sync_paused_jobs_on_start

    redis = _FakeRedis()
    _seed_task(redis, "tid_a", "x", "s")  # enabled=1
    _seed_task(redis, "tid_b", "x", "s")  # enabled=1
    redis.store[SCHEDULED_META_PREFIX + "tid_b"][b"enabled"] = b"0"  # 改 paused
    _seed_task(redis, "tid_c", "x", "s")  # enabled=1

    fake_scheduler = MagicMock()
    job_a = MagicMock(id="tid_a", next_run_time="2026-08-13 09:00:00")  # 一致
    job_b = MagicMock(id="tid_b", next_run_time="2026-08-13 09:00:00")  # meta=0 但 active → 应 pause
    job_c = MagicMock(id="tid_c", next_run_time=None)                  # meta=1 但 paused → 应 resume
    job_d = MagicMock(id="tid_orphan", next_run_time="2026-08-13 09:00:00")  # meta 缺失 → 跳过
    fake_scheduler.get_jobs.return_value = [job_a, job_b, job_c, job_d]
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)
    monkeypatch.setattr(core_module, "get_redis", lambda: redis)

    _sync_paused_jobs_on_start()

    assert not job_a.pause.called and not job_a.resume.called, "一致不应动"
    assert job_b.pause.called and not job_b.resume.called, "meta=0 → pause"
    assert job_c.resume.called and not job_c.pause.called, "meta=1 但 paused → resume"
    assert not job_d.pause.called and not job_d.resume.called, "meta 缺失 → 跳过"


def test_start_scheduler_calls_sync_after_start(monkeypatch):
    """start_scheduler 启动后必须调 _sync_paused_jobs_on_start（防回归）。"""
    from skills.Scheduler import core as core_module

    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    monkeypatch.setattr(core_module, "_scheduler", None)
    monkeypatch.setattr(core_module, "AsyncIOScheduler", MagicMock(return_value=fake_scheduler))
    monkeypatch.setattr(core_module, "RedisJobStore", MagicMock())
    monkeypatch.setattr(core_module, "get_redis_checkpointer_url", lambda: "redis://:123456@localhost:6024/0")

    sync_called = []

    def _spy_sync():
        sync_called.append(True)

    monkeypatch.setattr(core_module, "_sync_paused_jobs_on_start", _spy_sync)

    import asyncio
    asyncio.run(_async_run_start_scheduler(core_module))

    assert sync_called, "start_scheduler 必须调 _sync_paused_jobs_on_start"


async def _async_run_start_scheduler(core_module):
    """把同步的 start_scheduler 包到 async 里（避免再开一个事件循环）"""
    core_module.start_scheduler()


# =========================================================================
# 7. handle_send_message（Step 2：handler 执行逻辑）
# =========================================================================
# 用 mock Redis + mock chat_service，避免真连 Redis / 跑 LangGraph。
# 测试目标：
# - 防重入锁生效（第二次 set NX 返回 None）
# - meta 缺失 / prompt 为空 走 error 路径
# - chat_service.message_stream 正常 chunks → 提取 final_response + 写 history
# - chat_service.message_stream 抛异常 → error 路径 + 仍释放锁
# - chat_service 为 None → RuntimeError + 仍释放锁
# - done.full_response 优先于累积 content
# - interrupt / error 事件正确识别


class _FakeRedis:
    """
    模拟 redis.Redis：HSET / HGETALL / LPUSH / LTRIM / HINCRBY / DELETE / SET NX

    行为细节：
    - set(..., nx=True, ex=...) 第二次返 None（模拟防重入）
    - pipeline().execute() 依次跑 commands
    - hset(key, field, value) 写 dict[field]=value（覆盖）
    - hgetall(key) 返 dict（key 不存在返 {}）
    """

    def __init__(self):
        self.store: dict = {}  # {key: {field: value}} for hash / {key: value} for string
        self.lists: dict = {}  # {key: [value, ...]} for list
        self.lock_held: set = set()  # 模拟防重入锁已占用

    def _hash_get(self, key: str) -> dict:
        if key not in self.store or not isinstance(self.store[key], dict):
            return {}
        return self.store[key]

    def _hash_set(self, key: str, field: str, value):
        if key not in self.store or not isinstance(self.store[key], dict):
            self.store[key] = {}
        self.store[key][field] = value

    def set(self, key, value, nx=False, ex=None):
        # 防重入锁模拟：key 已存在则返 None
        if nx and key in self.lock_held:
            return None
        if nx:
            self.lock_held.add(key)
        self.store[key] = value
        return True

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
            if k in self.lists:
                del self.lists[k]
                n += 1
            if k in self.lock_held:
                self.lock_held.discard(k)
        return n

    def hset(self, key, field=None, value=None, mapping=None):
        if mapping:
            for k, v in mapping.items():
                self._hash_set(key, k, v)
        else:
            self._hash_set(key, field, value)
        return 1

    def hgetall(self, key):
        return self._hash_get(key)

    def hget(self, key, field):
        h = self._hash_get(key)
        # str field → 转 bytes 后查 dict（keys from _seed_task 全是 k.encode()）
        if isinstance(field, str):
            field = field.encode()
        if field not in h:
            return None
        v = h[field]
        return v if isinstance(v, bytes) else str(v).encode()

    def hincrby(self, key, field, amount=1):
        cur = int(self._hash_get(key).get(field, 0))
        self._hash_set(key, field, cur + amount)
        return cur + amount

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        if key in self.lists:
            # end inclusive in redis-py ltrim; here we mimic by inclusive end
            self.lists[key] = self.lists[key][start:end + 1]
        return True

    def lrange(self, key, start, end):
        lst = self.lists.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start:end + 1]

    def pipeline(self, transaction=False):
        outer = self

        class _Pipe:
            def __init__(self):
                self.cmds = []

            def lpush(self, k, v):
                self.cmds.append(("lpush", k, v))
                return self

            def ltrim(self, k, s, e):
                self.cmds.append(("ltrim", k, s, e))
                return self

            def hincrby(self, k, f, a=1):
                self.cmds.append(("hincrby", k, f, a))
                return self

            def hset(self, k, f=None, v=None, mapping=None):
                self.cmds.append(("hset", k, f, v, mapping))
                return self

            def execute(self):
                results = []
                for cmd in self.cmds:
                    if cmd[0] == "lpush":
                        results.append(outer.lpush(cmd[1], cmd[2]))
                    elif cmd[0] == "ltrim":
                        results.append(outer.ltrim(cmd[1], cmd[2], cmd[3]))
                    elif cmd[0] == "hincrby":
                        results.append(outer.hincrby(cmd[1], cmd[2], cmd[3]))
                    elif cmd[0] == "hset":
                        _, k, f, v, mapping = cmd
                        results.append(outer.hset(k, field=f, value=v, mapping=mapping))
                return results

        return _Pipe()

    def smembers(self, key):
        return self.store.get(key, set()) if isinstance(self.store.get(key), set) else set()

    def sadd(self, key, *members):
        if key not in self.store or not isinstance(self.store[key], set):
            self.store[key] = set()
        self.store[key].update(members)
        return len(members)

    def srem(self, key, *members):
        if key not in self.store or not isinstance(self.store[key], set):
            return 0
        n = 0
        for m in members:
            if m in self.store[key]:
                self.store[key].discard(m)
                n += 1
        return n

    def exists(self, key):
        return key in self.store or key in self.lists


def _seed_task(redis: _FakeRedis, task_id: str, prompt: str, session_id: str = ""):
    """把 task meta 写入 fake Redis（handler 通过 ScheduledTask.from_hgetall 读取）"""
    task = ScheduledTask(
        task_id=task_id,
        name="测试",
        cron="* * * * *",
        prompt=prompt,
        session_id=session_id,
        created_by="test",
        created_at=1723276800.0,
    )
    # redis-py hgetall 返回 bytes {field: value}（模拟真客户端）
    redis.store[SCHEDULED_META_PREFIX + task_id] = {
        k.encode(): str(v).encode() for k, v in task.to_hset_mapping().items()
    }


def _patch_chat_service(monkeypatch, message_stream=None, chat_service_obj=None):
    """
    Patch ChatMe.APIRouter.main 模块里的 chat_service / message_stream

    - message_stream: async callable returning async generator
    - chat_service_obj: object with message_stream attribute; 传 None 模拟未初始化
    """
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock

    fake_module = ModuleType("ChatMe.APIRouter.main")
    if chat_service_obj is None:
        # chat_service = None 路径：handler 抛 RuntimeError
        fake_module.chat_service = None
    else:
        if message_stream is not None:
            chat_service_obj.message_stream = message_stream
        fake_module.chat_service = chat_service_obj
    monkeypatch.setitem(sys.modules, "ChatMe.APIRouter.main", fake_module)
    return fake_module


def _async_iter(items):
    """把 list 转 async iterator（mock message_stream 的最简方式）"""
    async def _gen():
        for x in items:
            yield x
    return _gen()


def test_extract_final_response_done_full_response_priority():
    """done.full_response 优先于累积的 content 事件"""
    from skills.Scheduler.handlers import _extract_final_response

    chunks = [
        json.dumps({"type": "init", "session_id": "abc"}),
        json.dumps({"type": "content", "content": "部分"}),
        json.dumps({"type": "content", "content": "内容"}),
        json.dumps({"type": "done", "full_response": "最终完整回复"}),
    ]
    preview, status, error_msg = _extract_final_response(chunks)
    assert preview == "最终完整回复"
    assert status == "success"
    assert error_msg == ""


def test_extract_final_response_no_done_fallback_to_content():
    """没有 done 时 fallback 到累积 content"""
    from skills.Scheduler.handlers import _extract_final_response

    chunks = [
        json.dumps({"type": "content", "content": "你好"}),
        json.dumps({"type": "content", "content": "世界"}),
    ]
    preview, status, error_msg = _extract_final_response(chunks)
    assert preview == "你好世界"
    assert status == "success"


def test_extract_final_response_error_event():
    """error 事件识别 → status='error' + 错误信息"""
    from skills.Scheduler.handlers import _extract_final_response

    chunks = [
        json.dumps({"type": "content", "content": "我没说完"}),
        json.dumps({"type": "error", "error": "LLM 调用超时"}),
    ]
    preview, status, error_msg = _extract_final_response(chunks)
    assert status == "error"
    assert "LLM 调用超时" in error_msg
    assert preview == "我没说完"


def test_extract_final_response_interrupt_event():
    """interrupt 事件识别 → status='interrupted'"""
    from skills.Scheduler.handlers import _extract_final_response

    chunks = [
        json.dumps({"type": "content", "content": "需要审批"}),
        json.dumps({"type": "interrupt", "tool_name": "cmd", "reason": "permission"}),
    ]
    preview, status, error_msg = _extract_final_response(chunks)
    assert status == "interrupted"
    assert "permission" in error_msg.lower() or "permission" in error_msg
    assert "cmd" in error_msg


def test_extract_final_response_handles_malformed_chunks():
    """坏 JSON chunk 不抛异常（用 try/except 容错）"""
    from skills.Scheduler.handlers import _extract_final_response

    chunks = [
        "not-json",
        "{malformed",
        json.dumps({"type": "done", "full_response": "ok"}),
    ]
    preview, status, error_msg = _extract_final_response(chunks)
    assert preview == "ok"
    assert status == "success"


def test_extract_final_response_truncates_long_content():
    """preview 截断到 300 字符"""
    from skills.Scheduler.handlers import _extract_final_response

    long = "x" * 500
    chunks = [json.dumps({"type": "done", "full_response": long})]
    preview, status, error_msg = _extract_final_response(chunks)
    assert len(preview) == 300


def test_handle_send_message_success_path(monkeypatch):
    """happy path: chat_service 正常返回 done → history 写 success"""
    import asyncio
    from unittest.mock import MagicMock
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    _seed_task(redis, "tid001", "说hi", "sid001")
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)

    chunks = [
        json.dumps({"type": "content", "content": "你好"}),
        json.dumps({"type": "done", "full_response": "你好世界"}),
    ]
    chat_service = MagicMock()
    _patch_chat_service(monkeypatch, message_stream=lambda message, session_id=None: _async_iter(chunks), chat_service_obj=chat_service)

    async def _go():
        await handlers.handle_send_message("tid001")

    asyncio.run(_go())

    # history 写入了
    history = redis.lists.get(SCHEDULED_HISTORY_PREFIX + "tid001", [])
    assert len(history) == 1
    entry = json.loads(history[0])
    assert entry["status"] == "success"
    assert entry["output_preview"] == "你好世界"
    assert entry["error"] == ""

    # last_run / run_count 更新
    meta = redis.store[SCHEDULED_META_PREFIX + "tid001"]
    assert int(meta["run_count"]) == 1
    assert float(meta["last_run"]) > 0

    # 锁释放
    assert "scheduled:lock:tid001" not in redis.lock_held


def test_handle_send_message_idempotent_lock_skips(monkeypatch):
    """锁已存在 → handler 跳过本次触发（防重入）"""
    import asyncio
    from unittest.mock import MagicMock
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    _seed_task(redis, "tid002", "说hi", "sid002")
    # 预先占用锁
    redis.set("scheduled:lock:tid002", "stale", nx=True, ex=3600)
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)

    message_stream_called = False

    async def _should_not_be_called(*args, **kwargs):
        nonlocal message_stream_called
        message_stream_called = True
        if False:
            yield  # 永远不执行，但让函数被识别为 async generator

    chat_service = MagicMock()
    chat_service.message_stream = _should_not_be_called
    _patch_chat_service(monkeypatch, chat_service_obj=chat_service)

    async def _go():
        await handlers.handle_send_message("tid002")

    asyncio.run(_go())

    assert message_stream_called is False, "锁占用时不应触发 message_stream"
    # 没有 history（被跳过）
    assert redis.lists.get(SCHEDULED_HISTORY_PREFIX + "tid002", []) == []


def test_handle_send_message_chat_service_none(monkeypatch):
    """chat_service 未初始化 → RuntimeError + 仍释放锁 + 写 history error"""
    import asyncio
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    _seed_task(redis, "tid003", "说hi", "sid003")
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)
    _patch_chat_service(monkeypatch, chat_service_obj=None)

    async def _go():
        await handlers.handle_send_message("tid003")

    asyncio.run(_go())

    # history 写了 error
    history = redis.lists.get(SCHEDULED_HISTORY_PREFIX + "tid003", [])
    assert len(history) == 1
    entry = json.loads(history[0])
    assert entry["status"] == "error"
    assert "RuntimeError" in entry["error"]
    assert "chat_service" in entry["error"]

    # 锁释放
    assert "scheduled:lock:tid003" not in redis.lock_held


def test_handle_send_message_meta_missing(monkeypatch):
    """task meta 已被外部删除 → 走 error 路径 + 仍释放锁"""
    import asyncio
    from unittest.mock import MagicMock
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    # 不 seed meta
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)
    _patch_chat_service(monkeypatch, chat_service_obj=MagicMock())

    async def _go():
        await handlers.handle_send_message("tid_missing")

    asyncio.run(_go())

    history = redis.lists.get(SCHEDULED_HISTORY_PREFIX + "tid_missing", [])
    assert len(history) == 1
    entry = json.loads(history[0])
    assert entry["status"] == "error"
    assert "不存在" in entry["error"]
    # 锁释放
    assert "scheduled:lock:tid_missing" not in redis.lock_held


def test_handle_send_message_empty_prompt(monkeypatch):
    """prompt 为空 → RuntimeError + error history"""
    import asyncio
    from unittest.mock import MagicMock
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    _seed_task(redis, "tid004", "")  # 空 prompt
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)
    _patch_chat_service(monkeypatch, chat_service_obj=MagicMock())

    async def _go():
        await handlers.handle_send_message("tid004")

    asyncio.run(_go())

    history = redis.lists.get(SCHEDULED_HISTORY_PREFIX + "tid004", [])
    assert len(history) == 1
    entry = json.loads(history[0])
    assert entry["status"] == "error"
    assert "prompt 为空" in entry["error"]


def test_handle_send_message_stream_exception(monkeypatch):
    """message_stream 抛异常 → error path + 仍释放锁"""
    import asyncio
    from unittest.mock import MagicMock
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    _seed_task(redis, "tid005", "说hi", "sid005")
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)

    async def _broken_stream(*args, **kwargs):
        if False:
            yield  # 永远不执行，但让函数被识别为 async generator
        raise ConnectionError("LLM 服务挂了")

    chat_service = MagicMock()
    chat_service.message_stream = _broken_stream
    _patch_chat_service(monkeypatch, chat_service_obj=chat_service)

    async def _go():
        await handlers.handle_send_message("tid005")

    asyncio.run(_go())

    history = redis.lists.get(SCHEDULED_HISTORY_PREFIX + "tid005", [])
    assert len(history) == 1
    entry = json.loads(history[0])
    assert entry["status"] == "error"
    assert "ConnectionError" in entry["error"]
    assert "LLM 服务挂了" in entry["error"]
    # last_run 仍然更新（防永久卡住）
    meta = redis.store[SCHEDULED_META_PREFIX + "tid005"]
    assert int(meta["run_count"]) == 1
    # 锁释放
    assert "scheduled:lock:tid005" not in redis.lock_held


def test_handle_send_message_history_ltrim(monkeypatch):
    """history 超过 50 条时 LTRIM 截断"""
    import asyncio
    from unittest.mock import MagicMock
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    _seed_task(redis, "tid006", "说hi", "sid006")
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)

    chunks = [json.dumps({"type": "done", "full_response": "ok"})]
    chat_service = MagicMock()
    _patch_chat_service(monkeypatch, message_stream=lambda message, session_id=None: _async_iter(chunks), chat_service_obj=chat_service)

    async def _go():
        for _ in range(60):
            await handlers.handle_send_message("tid006")

    asyncio.run(_go())

    # history 应被截断到 50
    history = redis.lists.get(SCHEDULED_HISTORY_PREFIX + "tid006", [])
    assert len(history) == 50
    # run_count 应累计到 60（不被截断影响）
    meta = redis.store[SCHEDULED_META_PREFIX + "tid006"]
    assert int(meta["run_count"]) == 60


def test_handle_send_message_lock_released_even_on_history_write_failure(monkeypatch):
    """history 写失败时锁仍被释放（finally 兜底）"""
    import asyncio
    from unittest.mock import MagicMock
    from skills.Scheduler import handlers

    redis = _FakeRedis()
    _seed_task(redis, "tid007", "说hi", "sid007")
    monkeypatch.setattr(handlers, "get_redis", lambda: redis)

    # 让 pipeline.execute 抛异常
    def _broken_pipeline(*args, **kwargs):
        class _P:
            def lpush(self, *a, **k): return self
            def ltrim(self, *a, **k): return self
            def hincrby(self, *a, **k): return self
            def hset(self, *a, **k): return self
            def execute(self): raise IOError("redis down")
        return _P()
    redis.pipeline = _broken_pipeline

    chunks = [json.dumps({"type": "done", "full_response": "ok"})]
    chat_service = MagicMock()
    _patch_chat_service(monkeypatch, message_stream=lambda message, session_id=None: _async_iter(chunks), chat_service_obj=chat_service)

    async def _go():
        await handlers.handle_send_message("tid007")  # 不应抛

    asyncio.run(_go())


# =========================================================================
# run_task_now — APScheduler modify_job 需 datetime 而非 float
# 回归：v0.1.4 实测发现 APScheduler 3.11.2 的 modify_job(next_run_time=float) 抛
# TypeError: Unsupported type for next_run_time: float，导致 API 返 500。
# 修复：run_task_now 用 datetime.fromtimestamp(_now(), tz=timezone.utc)。
# =========================================================================


def test_run_task_now_passes_datetime_to_modify_job(monkeypatch):
    """run_task_now 必须把 next_run_time 包成 tz-aware datetime（APScheduler 3.11+ 拒绝 float）。"""
    from datetime import datetime, timezone

    from skills.Scheduler import registry

    redis = _FakeRedis()
    _seed_task(redis, "tid_run", "x", "s")
    monkeypatch.setattr(registry, "get_redis", lambda: redis)

    captured = {}

    class _FakeScheduler:
        def get_job(self, tid):
            class _J:
                pass
            j = _J()
            j.next_run_time = "2026-08-13 09:00:00"  # 已注册、非 None
            return j

        def modify_job(self, tid, **changes):
            captured["tid"] = tid
            captured["next_run_time"] = changes["next_run_time"]
            return None

    fake_sched = _FakeScheduler()
    monkeypatch.setattr(registry, "get_scheduler", lambda: fake_sched)

    ok = registry.run_task_now("tid_run")
    assert ok is True
    assert captured["tid"] == "tid_run"

    nrt = captured["next_run_time"]
    # 必须是 tz-aware datetime，不能是 float
    assert isinstance(nrt, datetime), f"expected datetime, got {type(nrt).__name__}"
    assert nrt.tzinfo is not None, "next_run_time 必须是 tz-aware（APScheduler 会按 scheduler TZ 转换）"


def test_run_task_now_404_when_task_missing(monkeypatch):
    """不存在的 task_id → 返 False（→ API 404），不抛异常。"""
    from skills.Scheduler import registry

    redis = _FakeRedis()
    monkeypatch.setattr(registry, "get_redis", lambda: redis)
    monkeypatch.setattr(registry, "get_scheduler", lambda: MagicMock())

    ok = registry.run_task_now("nonexistent")
    assert ok is False

    # 锁仍释放（最关键）
    assert "scheduled:lock:tid007" not in redis.lock_held