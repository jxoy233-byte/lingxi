"""
消息队列 REST API 测试

覆盖：
- POST /chat/{sid}/queue 入队（FIFO 顺序、index 正确）
- GET  /chat/{sid}/queue 列出（FIFO 顺序、损坏元素跳过）
- DELETE /chat/{sid}/queue 单条（idx 校验、超过 LLEN 返 404）
- DELETE /chat/{sid}/queue 全部（删除 key）
- 边界：超过 MAX_QUEUE_SIZE 返 400 / 单条 message 超长 → 400

测试方式：用 mock redis 替代 _redis_client，避免真打 db1。
"""

import json
import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# =========================================================================
# Mock redis 客户端（最简 in-memory 实现，覆盖 LPUSH/RPUSH/LRANGE/LLEN/LINDEX/LSET/LREM/DEL/EVAL）
# =========================================================================


class _FakeRedis:
    """用 dict 模拟 Redis LIST + EVAL。

    与真实消息队列 API 一样，key 是 queue:{sid}，value 是 LIST[str]。
    """

    def __init__(self):
        self.store: dict[str, list[str]] = {}
        self._eval_handler = None

    # ---- 简单 LIST 命令 ----

    def rpush(self, key, value):
        self.store.setdefault(key, [])
        self.store[key].append(value)
        return len(self.store[key])

    def lrange(self, key, start, end):
        lst = self.store.get(key, [])
        if not lst:
            return []
        # 模拟 redis 行为：end=-1 表示末尾
        if end == -1:
            end = len(lst) - 1
        if start < 0:
            start = max(0, len(lst) + start)
        return lst[start:end + 1]

    def llen(self, key):
        return len(self.store.get(key, []))

    def lindex(self, key, idx):
        lst = self.store.get(key, [])
        if idx < 0 or idx >= len(lst):
            return None
        return lst[idx]

    def lset(self, key, idx, value):
        lst = self.store.setdefault(key, [])
        if idx < 0 or idx >= len(lst):
            return 0
        lst[idx] = value
        return 1

    def lrem(self, key, count, value):
        lst = self.store.get(key, [])
        removed = 0
        if count >= 0:
            new_lst = []
            for x in lst:
                if x == value and (count == 0 or removed < count):
                    removed += 1
                else:
                    new_lst.append(x)
        else:
            # 从右边开始删
            new_lst = list(reversed(lst))
            new_rev = []
            for x in new_lst:
                if x == value and (count == 0 or removed < abs(count)):
                    removed += 1
                else:
                    new_rev.append(x)
            new_lst = list(reversed(new_rev))
        self.store[key] = new_lst
        return removed

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0

    def eval(self, script, numkeys, *args):
        # 委托外部 handler
        if self._eval_handler is None:
            raise RuntimeError("eval called but no _eval_handler set")
        return self._eval_handler(script, numkeys, args)


@pytest.fixture
def fake_redis():
    fake = _FakeRedis()

    # 模拟真实 Lua 行为：LSET tombstone + LREM 1
    def _eval_handler(script, numkeys, args):
        # args: (key, target, idx)
        key, target, idx = args[0], args[1], int(args[2])
        lst = fake.store.get(key, [])
        if idx < 0 or idx >= len(lst):
            return 0
        if lst[idx] == target:
            lst[idx] = '__TOMBSTONE__'
            fake.store[key] = [x for x in lst if x != '__TOMBSTONE__']
            return 1
        return 0

    fake._eval_handler = _eval_handler
    return fake


# =========================================================================
# fixture: 替换 APIRouter.message_queue 里 _redis_client 为 fake
# =========================================================================


@pytest.fixture
def client(fake_redis, monkeypatch):
    from ChatMe.APIRouter import message_queue

    monkeypatch.setattr(message_queue, "_redis_client", fake_redis)

    app = FastAPI()
    app.include_router(message_queue.router)
    return TestClient(app)


# =========================================================================
# 1. POST  入队
# =========================================================================


def test_enqueue_returns_index_and_total(client, fake_redis):
    """完整 payload → 200 + index=0 + total=1。"""
    r = client.post("/chat/sid_001/queue", json={"message": "hello", "quote": None})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["index"] == 0
    assert data["total"] == 1


def test_enqueue_fifo_order(client, fake_redis):
    """连续入队 3 条 → FIFO 顺序，idx 0/1/2 递增。"""
    msgs = ["first", "second", "third"]
    for i, m in enumerate(msgs):
        r = client.post("/chat/sid_002/queue", json={"message": m})
        assert r.status_code == 200
        data = r.json()
        assert data["index"] == i
        assert data["total"] == i + 1

    # Redis LIST 内容应按推送顺序
    assert len(fake_redis.store["queue:sid_002"]) == 3
    payloads = [json.loads(s) for s in fake_redis.store["queue:sid_002"]]
    assert [p["message"] for p in payloads] == msgs


def test_enqueue_with_quote(client):
    """quote 字段透传存到 Redis payload。"""
    r = client.post("/chat/sid_003/queue", json={
        "message": "看到上条提到的内容",
        "quote": "这是上一条引用的文本",
    })
    assert r.status_code == 200

    items = client.get("/chat/sid_003/queue").json()["items"]
    assert len(items) == 1
    assert items[0]["message"] == "看到上条提到的内容"
    assert items[0]["quote"] == "这是上一条引用的文本"


def test_enqueue_separate_sessions_isolated(client, fake_redis):
    """不同 sid 的队列互不干扰。"""
    client.post("/chat/sid_A/queue", json={"message": "A1"})
    client.post("/chat/sid_A/queue", json={"message": "A2"})
    client.post("/chat/sid_B/queue", json={"message": "B1"})

    a = client.get("/chat/sid_A/queue").json()
    b = client.get("/chat/sid_B/queue").json()
    assert a["total"] == 2
    assert b["total"] == 1


def test_enqueue_empty_message_returns_422(client):
    """message 空 → pydantic Field min_length=1 校验 → 422。"""
    r = client.post("/chat/sid_x/queue", json={"message": ""})
    assert r.status_code == 422


def test_enqueue_message_too_long_returns_422(client):
    """message > MAX_MESSAGE_LEN → 422。"""
    r = client.post("/chat/sid_x/queue", json={"message": "x" * 4001})
    assert r.status_code == 422


def test_enqueue_queue_full_returns_400(client, fake_redis, monkeypatch):
    """队列满 MAX_QUEUE_SIZE → 400。"""
    from ChatMe.APIRouter import message_queue

    # 写满 100 条
    for i in range(100):
        client.post("/chat/sid_full/queue", json={"message": f"m{i}"})

    # 第 101 条应 400
    r = client.post("/chat/sid_full/queue", json={"message": "m100"})
    assert r.status_code == 400
    assert "full" in r.json()["detail"].lower() or "已满" in r.json()["detail"]


# =========================================================================
# 2. GET  列表
# =========================================================================


def test_list_empty_returns_empty_items(client):
    """空队列 → items=[] / total=0。"""
    r = client.get("/chat/sid_empty/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_list_returns_fifo_payloads(client):
    """GET 返回的 items 是 FIFO 顺序，message/quote/queued_at 字段完整。"""
    client.post("/chat/sid_l/queue", json={"message": "m1", "quote": "q1"})
    client.post("/chat/sid_l/queue", json={"message": "m2"})  # 无 quote
    client.post("/chat/sid_l/queue", json={"message": "m3", "quote": "q3"})

    r = client.get("/chat/sid_l/queue")
    data = r.json()
    assert data["total"] == 3
    assert [it["message"] for it in data["items"]] == ["m1", "m2", "m3"]
    assert [it["quote"] for it in data["items"]] == ["q1", None, "q3"]
    for it in data["items"]:
        assert isinstance(it["queued_at"], float)


def test_list_skips_corrupted_items(client, fake_redis):
    """损坏 JSON 元素跳过不让列表挂。"""
    fake_redis.store["queue:sid_corr"] = [
        "not json",
        json.dumps({"message": "good", "quote": None, "queued_at": 1.0}),
        "also bad",
        json.dumps({"message": "also good", "quote": None, "queued_at": 2.0}),
    ]
    r = client.get("/chat/sid_corr/queue")
    data = r.json()
    # 损坏的 2 条被跳过，剩 2 条
    assert data["total"] == 2
    assert [it["message"] for it in data["items"]] == ["good", "also good"]


# =========================================================================
# 3. DELETE  单条 / 全部
# =========================================================================


def test_delete_specific_idx_removes_target(client, fake_redis):
    """删 idx=1 → 剩 2 条，message 顺序保持。"""
    client.post("/chat/sid_d1/queue", json={"message": "m1"})
    client.post("/chat/sid_d1/queue", json={"message": "m2"})
    client.post("/chat/sid_d1/queue", json={"message": "m3"})

    r = client.delete("/chat/sid_d1/queue?idx=1")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["deleted_idx"] == 1
    assert data["remaining"] == 2

    # 校验剩 m1 / m3
    items = client.get("/chat/sid_d1/queue").json()["items"]
    assert [it["message"] for it in items] == ["m1", "m3"]


def test_delete_idx_out_of_range_returns_404(client):
    """idx >= LLEN → 404。"""
    client.post("/chat/sid_d2/queue", json={"message": "m1"})
    r = client.delete("/chat/sid_d2/queue?idx=5")
    assert r.status_code == 404


def test_delete_negative_idx_returns_422(client):
    """idx < 0 → 422（Query ge=0 校验）。"""
    r = client.delete("/chat/sid_d3/queue?idx=-1")
    assert r.status_code == 422


def test_delete_all_clears_queue(client, fake_redis):
    """无 idx → 清空全部。"""
    for i in range(3):
        client.post("/chat/sid_d4/queue", json={"message": f"m{i}"})

    r = client.delete("/chat/sid_d4/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["deleted_all"] is True
    assert data["removed"] == 1  # DEL 返回 1（key 存在）

    # 紧接着 GET 应为空
    items = client.get("/chat/sid_d4/queue").json()
    assert items["total"] == 0


def test_delete_all_when_empty_is_noop(client, fake_redis):
    """空队列调 DELETE 无 idx → 200 + removed=0（DEL 不存在 key）。"""
    r = client.delete("/chat/sid_empty2/queue")
    assert r.status_code == 200
    assert r.json()["removed"] == 0


def test_delete_index_with_duplicate_messages_removes_correct_one(client, fake_redis):
    """重复 message 的场景：按 idx 删而不是按 value（避免误删前一条）。"""
    client.post("/chat/sid_dup/queue", json={"message": "same"})
    client.post("/chat/sid_dup/queue", json={"message": "same"})
    client.post("/chat/sid_dup/queue", json={"message": "diff"})

    r = client.delete("/chat/sid_dup/queue?idx=0")  # 第一条
    assert r.status_code == 200

    items = client.get("/chat/sid_dup/queue").json()["items"]
    assert [it["message"] for it in items] == ["same", "diff"]  # 第二条 same 保留


# =========================================================================
# 4. Lua eval 失败时的 fallback
# =========================================================================


def test_delete_fallback_to_lrem_when_lua_eval_fails(client, fake_redis, monkeypatch):
    """Lua 抛异常 → 退化到 LREM by value（确保删除仍能完成）。"""
    from ChatMe.APIRouter import message_queue

    client.post("/chat/sid_fb/queue", json={"message": "m1"})
    client.post("/chat/sid_fb/queue", json={"message": "m2"})

    # 让 fake_redis.eval 抛 RedisError
    def _raise(*args, **kwargs):
        import redis as _r
        raise _r.exceptions.RedisError("Lua disabled")

    monkeypatch.setattr(fake_redis, "eval", _raise)

    r = client.delete("/chat/sid_fb/queue?idx=1")
    assert r.status_code == 200
    items = client.get("/chat/sid_fb/queue").json()["items"]
    assert [it["message"] for it in items] == ["m1"]  # m2 被删
