"""LangGraph Redis checkpoint 静默清理器

问题背景
========
LangGraph 的 ``AsyncRedisSaver`` 每跑一个节点（input_parse / context_assembly /
agent / tool / final）就 ``aput()`` 一次，每 ``aput_writes()`` 又落 N 个
``checkpoint_write`` 文档。一次多轮对话会攒几十~几百个 checkpoint，dump.rdb
被吹到 GB 级且启动时 RDB 反序列化拖慢 chatme_main。

保留规则（2 路并集）
===================
1. ``checkpoint_latest:{tid}:{ns}`` 指向的最新 checkpoint —— LangGraph 自己用，
   删了它下次加载 thread 会失败
2. **RedisStateSaver 的 ``threads:{tid}:checkpoints`` HASH 里所有 checkpoint_id**
   —— 每轮用户/AI 对话完成时由 ``ChatService._save_round_checkpoint`` 写入，
   **这就是用户视角的「正常存的 checkpoint_id」**。LangGraph 跑 ReAct 中
   产生的 node-level 中间 checkpoint 不在这个 hash 里，会被全部清理掉。

不保留 parent chain 中间节点 —— UI 回溯到 user_saved cid 时
``aget_tuple(cid)`` 只读该 cid 自己的 JSON 文档，``parent_checkpoint_id``
字段即使指向已删的 cid 也不影响该轮消息显示。

其余 checkpoint + 关联的 ``checkpoint_write:*`` + ``write_keys_zset:*`` 全删。

不动
====
- ``checkpoint_latest`` 指针（LangGraph 自管）
- ChatMe 自己的 ``permission:{sid}`` / ``interrupt:{sid}`` / ``memory:*`` 等其他 key 命名空间
- RedisStateSaver hash 本身（只读不写）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


# LangGraph key 前缀（与 aio.py:33-35 / key_registry.py:19 一致）
CHECKPOINT_PREFIX = "checkpoint"
CHECKPOINT_WRITE_PREFIX = "checkpoint_write"
WRITE_KEYS_ZSET_PREFIX = "write_keys_zset"
LATEST_POINTER_PREFIX = "checkpoint_latest"

# RedisStateSaver 的 key（来自 ChatService/RedisStateSaver/core.py）
REDIS_STATE_SAVER_PREFIX = "threads"
REDIS_STATE_SAVER_SUFFIX = "checkpoints"


class CheckpointJanitor:
    """单 thread 的 checkpoint 清理器。

    保留集合的来源：RedisStateSaver 的 ``threads:{tid}:checkpoints`` HASH
    （每条 field = checkpoint_id，对应"用户视角的一轮对话完成态"）。

    使用方式：
        janitor = CheckpointJanitor(redis_client)
        janitor.bind_state_saver(state_saver)        # 注入 RedisStateSaver
        await janitor.prune_thread(thread_id)        # 实际清理（async fire-and-forget）
    """

    def __init__(
        self,
        redis_client: Redis,
        *,
        default_keep_last: int = 10,
    ) -> None:
        self._redis = redis_client
        self.default_keep_last = max(1, default_keep_last)
        # 延迟注入，ChatService 初始化时绑定
        self._state_saver: Any = None

    def bind_state_saver(self, state_saver: Any) -> None:
        """注入 RedisStateSaver 实例（异步读 ``threads:{tid}:checkpoints``）。

        为什么用 bind 而不是 ``__init__`` 入参：
            ChatWorkflow 创建 CheckpointJanitor 时 RedisStateSaver 还没初始化，
            state_saver 是 ChatService 自己 new 出来的；ChatService 拿到 workflow
            后再 bind，避免循环依赖。
        """
        self._state_saver = state_saver
        logger.info("[CheckpointJanitor] 已绑定 RedisStateSaver，将从 threads:{tid}:checkpoints 读保留 cid")

    # ----- 主入口 -----

    async def prune_thread(
        self,
        thread_id: str,
        *,
        keep_last: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """清理单个 thread 的冗余 checkpoint。

        Args:
            thread_id: 会话 ID（原始，未做 storage safe 转换）
            keep_last: 保留参数（API 兼容，当前保留逻辑不依赖此值）
            dry_run: 只统计不删除

        Returns:
            ``{thread_id, scanned, kept, deleted, deleted_cids, keys_deleted,
               user_saved_count}``
        """
        keep_last = keep_last if keep_last is not None else self.default_keep_last
        keep_last = max(1, keep_last)

        # 1. SCAN 拿该 thread 全部 checkpoint 文档（cid / ns / parent_cid）
        all_checkpoints = await self._scan_checkpoints(thread_id)
        if not all_checkpoints:
            return {
                "thread_id": thread_id,
                "scanned": 0,
                "kept": 0,
                "deleted": 0,
                "deleted_cids": [],
                "keys_deleted": 0,
                "user_saved_count": 0,
            }

        # 2. 每个 namespace 解析 latest 指针
        latest_per_ns: Dict[str, str] = {}
        namespaces: Set[str] = {c["ns"] for c in all_checkpoints}
        for ns in namespaces:
            lk = f"{LATEST_POINTER_PREFIX}:{thread_id}:{self._ns_safe(ns)}"
            latest_key = await self._redis.get(lk)
            if not latest_key:
                continue
            latest_key_str = latest_key.decode() if isinstance(latest_key, bytes) else latest_key
            # latest_key 格式: checkpoint:{tid}:{ns_safe}:{cid_safe}
            parts = latest_key_str.split(":")
            if len(parts) >= 4:
                latest_per_ns[ns] = parts[-1]

        # 3. 拿 RedisStateSaver 里"用户存的"checkpoint_id（每轮对话完成态）
        user_saved: Set[str] = await self._load_user_saved_cids(thread_id)

        # 4. 保留集合（只 2 路）：user_saved (redissaver 里每轮的 cid) + latest 指针
        #    不要 parent chain walk —— 中间 workflow cid 可以删，UI 回溯到 user_saved
        #    时 aget_tuple(cid) 只读该 cid 自己的 JSON，不依赖 parent 是否存在；
        #    parent_checkpoint_id 字段是悬空引用但不影响消息显示。
        #    不要 recent_keep (ULID top N) —— 不是必需，删了更省。
        keep: Set[str] = (
            set(latest_per_ns.values())
            | user_saved
        )

        # 7. 候选删除集合
        to_delete = [c for c in all_checkpoints if c["cid"] not in keep]

        # 8. dry_run 直接返回统计
        if dry_run:
            return {
                "thread_id": thread_id,
                "scanned": len(all_checkpoints),
                "kept": len(keep),
                "deleted": len(to_delete),
                "deleted_cids": [c["cid"] for c in to_delete],
                "keys_deleted": 0,
                "user_saved_count": len(user_saved),
            }

        # 9. 实际删除：主文档 + write_keys_zset + 所有 checkpoint_write 子文档
        keys_to_delete: List[str] = []
        ns_safe_cache: Dict[str, str] = {}

        def ns_safe(ns: str) -> str:
            if ns not in ns_safe_cache:
                # 与 LangGraph util.to_storage_safe_str 保持一致：
                # 空字符串 → "__empty__"，否则原样
                ns_safe_cache[ns] = "__empty__" if ns == "" else ns
            return ns_safe_cache[ns]

        for c in to_delete:
            cid = c["cid"]
            ns = c["ns"]
            keys_to_delete.append(
                f"{CHECKPOINT_PREFIX}:{thread_id}:{ns_safe(ns)}:{cid}"
            )
            keys_to_delete.append(
                f"{WRITE_KEYS_ZSET_PREFIX}:{thread_id}:{ns_safe(ns)}:{cid}"
            )
            # checkpoint_write:{tid}:{ns_safe}:{cid}:{task_id}:{idx}
            pattern = (
                f"{CHECKPOINT_WRITE_PREFIX}:{thread_id}:{ns_safe(ns)}:{cid}:*"
            )
            async for k in self._redis.scan_iter(match=pattern, count=200):
                ks = k.decode() if isinstance(k, bytes) else k
                keys_to_delete.append(ks)

        # 10. 批量删（pipeline 分批 500 避免一次性阻塞 Redis）
        keys_deleted = 0
        if keys_to_delete:
            for i in range(0, len(keys_to_delete), 500):
                batch = keys_to_delete[i:i + 500]
                keys_deleted += await self._redis.delete(*batch)

        if to_delete:
            logger.info(
                f"[CheckpointJanitor] thread={thread_id[:12]}... 扫描={len(all_checkpoints)} "
                f"用户存的={len(user_saved)} 保留={len(keep)} 删除={len(to_delete)} keys={keys_deleted}"
            )

        return {
            "thread_id": thread_id,
            "scanned": len(all_checkpoints),
            "kept": len(keep),
            "deleted": len(to_delete),
            "deleted_cids": [c["cid"] for c in to_delete],
            "keys_deleted": keys_deleted,
            "user_saved_count": len(user_saved),
        }

    async def prune_all_threads(
        self,
        *,
        keep_last: Optional[int] = None,
        dry_run: bool = False,
        min_scanned: int = 1,
    ) -> List[Dict[str, Any]]:
        """对所有 thread 跑清理（scan 所有 checkpoint:* key 抽 thread_id）。

        ``min_scanned`` 控制跳过线程数 < 该阈值的——避免给小会话做无用功。
        """
        thread_ids: Set[str] = set()
        async for key in self._redis.scan_iter(match=f"{CHECKPOINT_PREFIX}:*", count=1000):
            ks = key.decode() if isinstance(key, bytes) else key
            parts = ks.split(":")
            if len(parts) >= 3:
                thread_ids.add(parts[1])  # safe_tid，UUID hex 时与原 tid 等价

        results: List[Dict[str, Any]] = []
        for tid in thread_ids:
            # 跳过过小的 thread（节省 IO；> N 个才触发清理）
            if min_scanned > 1:
                cnt = sum(
                    1 for _ in self._redis.scan_iter(
                        match=f"{CHECKPOINT_PREFIX}:{tid}:*", count=500
                    )
                )
                if cnt < min_scanned:
                    continue
            r = await self.prune_thread(tid, keep_last=keep_last, dry_run=dry_run)
            results.append(r)
        return results

    # ----- 内部工具 -----

    @staticmethod
    def _ns_safe(ns: str) -> str:
        """与 langgraph.checkpoint.redis.util.to_storage_safe_str 行为一致。"""
        return "__empty__" if ns == "" else ns

    async def _load_user_saved_cids(self, thread_id: str) -> Set[str]:
        """从 RedisStateSaver 的 ``threads:{tid}:checkpoints`` HASH 读所有 cid。

        Returns:
            该 thread 用户视角的所有 checkpoint_id 集合（每轮对话完成态）。
            若 state_saver 未绑定，返回空集（不报错但保留集合为 0，
            只会保留 latest，会把所有 user_saved cid 都误删 —— 应避免）。
        """
        if self._state_saver is None:
            logger.warning(
                f"[CheckpointJanitor] state_saver 未绑定，thread={thread_id[:12]}... "
                "将只能保留 latest，所有 user_saved cid 都会被误删 —— 应尽快绑定 state_saver"
            )
            return set()
        try:
            checkpoints = await self._state_saver.get_checkpoints(thread_id)
        except Exception as e:
            logger.error(
                f"[CheckpointJanitor] state_saver.get_checkpoints 失败 thread={thread_id[:12]}...: {e}"
            )
            return set()
        return {cp["checkpoint_id"] for cp in checkpoints if cp.get("checkpoint_id")}

    async def _scan_checkpoints(self, thread_id: str) -> List[Dict[str, str]]:
        """SCAN 该 thread 所有 checkpoint 文档，拿 cid / ns / parent_checkpoint_id。"""
        out: List[Dict[str, str]] = []
        pattern = f"{CHECKPOINT_PREFIX}:{thread_id}:*"
        async for key in self._redis.scan_iter(match=pattern, count=500):
            ks = key.decode() if isinstance(key, bytes) else key
            parts = ks.split(":")
            if len(parts) < 4:
                continue
            cid = parts[-1]
            # ns 在中间：[prefix, tid, ...ns..., cid]
            # ns 自身可能不含 :（LangGraph 也不让它含），所以 [2:-1] join 是安全的
            ns = ":".join(parts[2:-1])

            parent_cid = ""
            try:
                data = await self._redis.json().get(ks, "$.parent_checkpoint_id")
                if isinstance(data, list) and data:
                    val = data[0]
                    parent_cid = val if val else ""
                elif isinstance(data, str):
                    parent_cid = data
            except Exception as e:
                logger.debug(f"scan parent_cid failed for {ks}: {e}")

            out.append({"cid": cid, "ns": ns, "parent_cid": parent_cid})
        return out