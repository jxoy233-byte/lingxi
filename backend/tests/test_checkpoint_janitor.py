"""
CheckpointJanitor 单测（v0.1.7 fork LATEST_POINTER / orphan zset 清理）

覆盖：
1. prune_thread 清 fork LATEST_POINTER（普通 fork LATEST_POINTER 指向非 user_saved 的 cid 时清）
2. prune_thread 保留指向 user_saved cid 的 fork LATEST_POINTER
3. prune_thread 保留主图 __empty__ LATEST_POINTER（LangGraph 主图恢复用）
4. prune_thread 清 orphan write_keys_zset（对应 checkpoint doc 不存在的 zset）
5. prune_thread 保留「对应 checkpoint doc 仍存在」的 write_keys_zset
6. retarget_to 覆写主图 LATEST_POINTER + 清 fork LATEST_POINTER + 清 orphan zset
7. retarget_to 保留指向 user_saved 的 fork LATEST_POINTER
8. all_checkpoints 为空时 early return 兼容（字段都在）
9. dry_run 路径返回字段结构兼容（old fields + new fields 都在）

设计：
- 用 FakeRedis 注入，不连真实 Redis（避免污染真数据）
- 测试不依赖 pytest-asyncio，用 _run(asyncio_run) 包装（与现有测试一致）
"""

import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ChatMe.ChatWorkflow.CheckpointJanitor import CheckpointJanitor  # noqa: E402


# ===== 异步运行辅助 =====


def _run(coro):
    """asyncio.run 包装, 替代 @pytest.mark.asyncio（项目没装 pytest-asyncio）。"""
    import asyncio
    return asyncio.run(coro)


# ===== FakeRedis =====


class FakeRedis:
    """最小可用的 fake redis：支持 scan_iter / get / exists / set / delete。

    数据：
      - checkpoint_keys: set of full checkpoint:* keys
      - write_zset_keys: set of full write_keys_zset:* keys
      - latest_pointer_values: {LATEST_POINTER_KEY: VALUE_STRING}
      - deleted: list of deleted keys（测试可检查）
      - set_calls: list of (key, value)（测试可检查 retarget_to 覆写行为）
    """

    TID = "abc123def456"

    def __init__(
        self,
        *,
        checkpoints: List[Tuple[str, str]],  # [(cid, ns_safe), ...]
        latest_pointer_values: Dict[str, str],  # {full LATEST_POINTER_KEY: VALUE}
        write_keys_zsets: List[Tuple[str, str]],  # [(ns_safe, cid), ...]
    ):
        self._tid = self.TID
        self.checkpoint_keys: Set[str] = set()
        for cid, ns_safe in checkpoints:
            self.checkpoint_keys.add(f"checkpoint:{self._tid}:{ns_safe}:{cid}")

        self.latest_pointer_values: Dict[str, str] = dict(latest_pointer_values)

        self.write_zset_keys: Set[str] = set()
        for ns_safe, cid in write_keys_zsets:
            self.write_zset_keys.add(f"write_keys_zset:{self._tid}:{ns_safe}:{cid}")

        self.deleted: List[str] = []
        self.set_calls: List[Tuple[str, str]] = []

    async def scan_iter(self, match: str, count: int = 200):
        if match.startswith(f"checkpoint:{self._tid}:"):
            for k in sorted(self.checkpoint_keys):
                yield k.encode()
        elif match.startswith(f"write_keys_zset:{self._tid}:"):
            for k in sorted(self.write_zset_keys):
                yield k.encode()
        elif match.startswith(f"checkpoint_latest:{self._tid}:"):
            for k in sorted(self.latest_pointer_values):
                yield k.encode()
        elif match.startswith(f"checkpoint_write:{self._tid}:"):
            return  # 测试场景里不写

    async def get(self, key):
        ks = key.decode() if isinstance(key, bytes) else key
        v = self.latest_pointer_values.get(ks)
        return v.encode() if v else None

    async def exists(self, key):
        ks = key.decode() if isinstance(key, bytes) else key
        return int(ks in self.checkpoint_keys or ks in self.write_zset_keys)

    async def set(self, key, value):
        ks = key.decode() if isinstance(key, bytes) else key
        vs = value.decode() if isinstance(value, bytes) else value
        self.set_calls.append((ks, vs))
        self.latest_pointer_values[ks] = vs
        return True

    async def delete(self, *keys):
        n = 0
        for k in keys:
            ks = k.decode() if isinstance(k, bytes) else k
            self.deleted.append(ks)
            self.checkpoint_keys.discard(ks)
            self.write_zset_keys.discard(ks)
            self.latest_pointer_values.pop(ks, None)
            n += 1
        return n

    def json(self):
        return _FakeJson()


class _FakeJson:
    async def get(self, key, path):
        # 测试不需要 parent_checkpoint_id 解析
        return [None]


def make_state_saver(user_saved_cids: List[str]) -> MagicMock:
    """构造 RedisStateSaver mock：get_checkpoints 返回 user_saved cid 列表。"""
    ss = MagicMock()
    ss.get_checkpoints = AsyncMock(
        return_value=[{"checkpoint_id": cid} for cid in user_saved_cids]
    )
    return ss


# ===== 共享常量 =====


TID = FakeRedis.TID
FORK_NS = "input_parse_node:uuid-1"


# ===== prune_thread 测试 =====


def test_prune_clears_fork_latest_pointer():
    """场景 1：fork LATEST_POINTER 指向非 user_saved cid 时清 key + 删指向的 cid。"""
    cid_fork = "cid-fork-1"
    cid_main = "cid-main-latest"

    fake = FakeRedis(
        checkpoints=[
            (cid_main, "__empty__"),           # 主图 LATEST_POINTER 指向
            ("cid-user-saved", "__empty__"),   # user_saved 保留
            (cid_fork, FORK_NS),               # fork LATEST_POINTER 指向 → 要清
        ],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:{cid_main}",
            f"checkpoint_latest:{TID}:{FORK_NS}": f"checkpoint:{TID}:{FORK_NS}:{cid_fork}",
        },
        write_keys_zsets=[],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver(["cid-user-saved"]))

    result = _run(janitor.prune_thread(TID, dry_run=False))

    # fork LATEST_POINTER key 被删
    assert f"checkpoint_latest:{TID}:{FORK_NS}" in fake.deleted
    # fork LATEST_POINTER 指向的 checkpoint doc 被删
    assert f"checkpoint:{TID}:{FORK_NS}:{cid_fork}" in fake.deleted
    # 主图 LATEST_POINTER 没被删
    assert f"checkpoint_latest:{TID}:__empty__" not in fake.deleted
    # 主图 LATEST_POINTER 指向的 cid 没被删
    assert f"checkpoint:{TID}:__empty__:{cid_main}" not in fake.deleted
    # user_saved cid 没被删
    assert f"checkpoint:{TID}:__empty__:cid-user-saved" not in fake.deleted

    # 统计字段正确
    assert result["fork_latest_cleared"] == 1
    assert result["deleted"] == 1  # 只删了 fork cid


def test_prune_keeps_fork_latest_pointer_pointing_to_user_saved():
    """场景 2：fork LATEST_POINTER 指向 user_saved cid 时保留 key + 保留 cid。"""
    cid_fork_user_saved = "cid-fork-user-saved"

    fake = FakeRedis(
        checkpoints=[
            (cid_fork_user_saved, FORK_NS),
        ],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:{FORK_NS}": f"checkpoint:{TID}:{FORK_NS}:{cid_fork_user_saved}",
        },
        write_keys_zsets=[],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver([cid_fork_user_saved]))

    result = _run(janitor.prune_thread(TID, dry_run=False))

    # 指向 user_saved 的 fork LATEST_POINTER 不进删除列表
    assert f"checkpoint_latest:{TID}:{FORK_NS}" not in fake.deleted
    assert f"checkpoint:{TID}:{FORK_NS}:{cid_fork_user_saved}" not in fake.deleted
    assert result["fork_latest_cleared"] == 0
    assert result["deleted"] == 0


def test_prune_keeps_main_latest_pointer():
    """场景 3：主图 __empty__ LATEST_POINTER 永远保留，指向的 cid 永远保留。"""
    cid_main = "cid-main-latest"

    fake = FakeRedis(
        checkpoints=[
            (cid_main, "__empty__"),
            ("cid-other-workflow", "__empty__"),  # 中间 workflow cid，应被删
        ],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:{cid_main}",
        },
        write_keys_zsets=[],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver([]))

    result = _run(janitor.prune_thread(TID, dry_run=False))

    # 主图 LATEST_POINTER 没被删
    assert f"checkpoint_latest:{TID}:__empty__" not in fake.deleted
    assert f"checkpoint:{TID}:__empty__:{cid_main}" not in fake.deleted
    # 中间 workflow cid 被删
    assert f"checkpoint:{TID}:__empty__:cid-other-workflow" in fake.deleted
    assert result["fork_latest_cleared"] == 0


def test_prune_clears_orphan_write_keys_zset():
    """场景 4：orphan write_keys_zset（对应 checkpoint doc 不存在）清掉。"""
    fake = FakeRedis(
        checkpoints=[("cid-keep", "__empty__")],  # 只有一个合法 checkpoint
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:cid-keep",
        },
        write_keys_zsets=[
            ("__empty__", "cid-orphan-1"),  # orphan：checkpoint doc 不存在
            ("__empty__", "cid-orphan-2"),  # orphan
        ],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver(["cid-keep"]))

    result = _run(janitor.prune_thread(TID, dry_run=False))

    # orphan zset 被删
    assert f"write_keys_zset:{TID}:__empty__:cid-orphan-1" in fake.deleted
    assert f"write_keys_zset:{TID}:__empty__:cid-orphan-2" in fake.deleted
    assert result["orphan_zsets_cleared"] == 2


def test_prune_keeps_legit_write_keys_zset():
    """场景 5：合法 write_keys_zset（对应 checkpoint doc 仍存在）保留。"""
    cid_kept = "cid-user-saved"

    fake = FakeRedis(
        checkpoints=[(cid_kept, "__empty__")],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:{cid_kept}",
        },
        write_keys_zsets=[
            ("__empty__", cid_kept),  # 合法：checkpoint doc 存在 + 是 user_saved
        ],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver([cid_kept]))

    result = _run(janitor.prune_thread(TID, dry_run=False))

    # 合法 zset 不被删
    assert f"write_keys_zset:{TID}:__empty__:{cid_kept}" not in fake.deleted
    assert result["orphan_zsets_cleared"] == 0


# ===== retarget_to 测试 =====


def test_retarget_keeps_main_latest_pointer_overwrite():
    """场景 6：retarget_to 覆写主图 LATEST_POINTER 到 target_cid，同时清 fork LATEST_POINTER 和 orphan zset。"""
    cid_target = "cid-target-user-saved"
    cid_fork = "cid-fork-orphan"

    fake = FakeRedis(
        checkpoints=[
            (cid_target, "__empty__"),  # target，保留
            ("cid-other-workflow", "__empty__"),  # 中间 workflow，要删
            (cid_fork, FORK_NS),  # fork LATEST_POINTER 指向，要删
        ],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:cid-old-main",
            f"checkpoint_latest:{TID}:{FORK_NS}": f"checkpoint:{TID}:{FORK_NS}:{cid_fork}",
        },
        write_keys_zsets=[
            ("__empty__", "cid-orphan-zset"),  # orphan，要删
        ],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver([cid_target]))

    result = _run(janitor.retarget_to(TID, target_cid=cid_target))

    # 主图 LATEST_POINTER 被覆写到 target_cid
    assert any(
        k == f"checkpoint_latest:{TID}:__empty__"
        and v == f"checkpoint:{TID}:__empty__:{cid_target}"
        for k, v in fake.set_calls
    ), f"retarget_to 应该覆写主图 LATEST_POINTER，set_calls={fake.set_calls}"

    # fork LATEST_POINTER 被清
    assert f"checkpoint_latest:{TID}:{FORK_NS}" in fake.deleted
    # orphan zset 被清
    assert f"write_keys_zset:{TID}:__empty__:cid-orphan-zset" in fake.deleted
    # target_cid 没被删
    assert f"checkpoint:{TID}:__empty__:{cid_target}" not in fake.deleted
    # 中间 workflow 被删
    assert f"checkpoint:{TID}:__empty__:cid-other-workflow" in fake.deleted

    # 字段
    assert result["target_cid"] == cid_target
    assert result["fork_latest_cleared"] == 1
    assert result["orphan_zsets_cleared"] == 1


def test_retarget_keeps_fork_latest_pointing_to_user_saved():
    """场景 7：retarget_to 保留指向 user_saved cid 的 fork LATEST_POINTER。"""
    cid_target = "cid-target"
    cid_fork_user_saved = "cid-fork-user-saved"
    fork_ns = "input_parse_node:uuid-2"

    fake = FakeRedis(
        checkpoints=[
            (cid_target, "__empty__"),
            (cid_fork_user_saved, fork_ns),  # 是 user_saved 也要保留
        ],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:cid-old",
            f"checkpoint_latest:{TID}:{fork_ns}": f"checkpoint:{TID}:{fork_ns}:{cid_fork_user_saved}",
        },
        write_keys_zsets=[],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver([cid_target, cid_fork_user_saved]))

    result = _run(janitor.retarget_to(TID, target_cid=cid_target))

    # 指向 user_saved 的 fork LATEST_POINTER 不进删除列表
    assert f"checkpoint_latest:{TID}:{fork_ns}" not in fake.deleted
    assert f"checkpoint:{TID}:{fork_ns}:{cid_fork_user_saved}" not in fake.deleted
    assert result["fork_latest_cleared"] == 0


# ===== 兼容 / 边界测试 =====


def test_prune_dry_run_returns_all_fields():
    """场景 8：dry_run 返回的字典包含所有旧字段 + 新增字段。"""
    fake = FakeRedis(
        checkpoints=[("cid-keep", "__empty__")],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:cid-keep",
        },
        write_keys_zsets=[],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver(["cid-keep"]))

    result = _run(janitor.prune_thread(TID, dry_run=True))

    # 旧字段
    for field in ["scanned", "kept", "deleted", "deleted_cids", "keys_deleted", "user_saved_count"]:
        assert field in result, f"旧字段 {field} 丢失"
    # 新字段（dry_run 命名风格）
    for field in ["fork_latest_to_clear", "orphan_zsets"]:
        assert field in result, f"新字段 {field} 丢失"


def test_prune_real_returns_all_fields():
    """场景 9：真清理（dry_run=False）返回的字典同样兼容。"""
    fake = FakeRedis(
        checkpoints=[("cid-keep", "__empty__")],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:cid-keep",
        },
        write_keys_zsets=[],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver(["cid-keep"]))

    result = _run(janitor.prune_thread(TID, dry_run=False))

    for field in [
        "scanned", "kept", "deleted", "deleted_cids",
        "user_saved_count", "keys_deleted",
        # 新字段（真清理命名风格）
        "fork_latest_cleared", "orphan_zsets_cleared",
    ]:
        assert field in result, f"字段 {field} 丢失"


def test_prune_empty_returns_zero_stats():
    """场景 10：all_checkpoints 为空时 early return，字段全 0。"""
    fake = FakeRedis(checkpoints=[], latest_pointer_values={}, write_keys_zsets=[])
    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver([]))

    result = _run(janitor.prune_thread(TID, dry_run=True))

    assert result["scanned"] == 0
    assert result["kept"] == 0
    assert result["deleted"] == 0
    assert result["deleted_cids"] == []
    assert result["user_saved_count"] == 0
    assert result["fork_latest_to_clear"] == 0
    assert result["orphan_zsets"] == 0


def test_retarget_requires_state_saver():
    """场景 11：retarget_to 必须 state_saver 绑定（未绑定 raise RuntimeError）。"""
    fake = FakeRedis(checkpoints=[], latest_pointer_values={}, write_keys_zsets=[])
    janitor = CheckpointJanitor(fake)
    # 注意：没 bind_state_saver

    with pytest.raises(RuntimeError, match="state_saver 未绑定"):
        _run(janitor.retarget_to(TID, target_cid="cid-x"))


def test_retarget_requires_existing_target():
    """场景 12：retarget_to 必须 target_cid 在 LangGraph storage 存在（否则 raise ValueError）。"""
    fake = FakeRedis(
        checkpoints=[("cid-other", "__empty__")],
        latest_pointer_values={
            f"checkpoint_latest:{TID}:__empty__": f"checkpoint:{TID}:__empty__:cid-other",
        },
        write_keys_zsets=[],
    )

    janitor = CheckpointJanitor(fake)
    janitor.bind_state_saver(make_state_saver([]))

    with pytest.raises(ValueError, match="target_cid.*不存在"):
        _run(janitor.retarget_to(TID, target_cid="cid-not-exist"))