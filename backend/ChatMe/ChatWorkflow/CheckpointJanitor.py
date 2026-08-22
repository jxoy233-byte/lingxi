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

LATEST_POINTER 分两类处理
==========================
- **主图 ``__empty__`` LATEST_POINTER**：保留，LangGraph 主图恢复用
- **fork LATEST_POINTER**（如 ``input_parse_node:<uuid>``）：撤回 / 清理后 fork 不再重跑，
  留着只占空间。除非指向的 cid 恰好在 user_saved（极少见），否则 key 自身 + 指向的 cid 都清

orphan write_keys_zset（对应 ``checkpoint:*`` doc 已不存在的 ``write_keys_zset:*``）
=====================================================================================
LangGraph ``aput_writes`` 在 ``aput`` 失败 / 异常中断时可能留下半截 zset，
没有 checkpoint doc 对应的 zset 不影响主图恢复，直接清。

不动
====
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

        # 2. 即使无 checkpoint doc，也跑一次 orphan write_keys_zset 扫描
        #    （如果 thread 之前清过所有 checkpoint，但 orphan zset 还残留）
        #    早期 return 路径会跳过这步 —— 但既然没 checkpoint doc 了，orphan zset 也没意义
        if not all_checkpoints:
            return {
                "thread_id": thread_id,
                "scanned": 0,
                "kept": 0,
                "deleted": 0,
                "deleted_cids": [],
                "fork_latest_to_clear": 0,
                "orphan_zsets": 0,
                "keys_deleted": 0,
                "user_saved_count": 0,
            }

        # 3. 拿 RedisStateSaver 里"用户存的"checkpoint_id（每轮对话完成态）
        user_saved: Set[str] = await self._load_user_saved_cids(thread_id)

        # 4. 每个 namespace 解析 latest 指针
        #    区分主图（__empty__）和 fork（如 input_parse_node:<uuid>）：
        #    - 主图 LATEST_POINTER：LangGraph 主图恢复用，必须保留（指向 keep 集合里的 cid）
        #    - fork LATEST_POINTER：Send fanout 产物，撤回后 fork 不再重跑，主图恢复也用不到，
        #      只在指向 user_saved cid 时保留，其他全部清掉（key 自身 + 指向的 cid 都清）
        #
        #    **关键**：fork LATEST_POINTER 必须独立 scan，不能依赖 _scan_checkpoints 拿到的
        #    namespaces 集合 —— 因为 fork LATEST_POINTER 指向的 checkpoint doc 可能已经在
        #    storage 里被清掉（典型 orphan 场景），那时 _scan_checkpoints 拿不到对应 namespace，
        #    LATEST_POINTER 永远扫不到。
        latest_per_ns: Dict[str, str] = {}      # 主图 __empty__ → cid（必保留）
        fork_pointers_to_clear: List[str] = []  # 要删的 fork LATEST_POINTER key

        # 4.1 主图 LATEST_POINTER（依赖 _scan_checkpoints 拿到的 namespaces，因为主图 doc 一定存在）
        namespaces: Set[str] = {c["ns"] for c in all_checkpoints}
        for ns in namespaces:
            ns_safe_val = self._ns_safe(ns)
            lk = f"{LATEST_POINTER_PREFIX}:{thread_id}:{ns_safe_val}"
            latest_key = await self._redis.get(lk)
            if not latest_key:
                continue
            latest_key_str = latest_key.decode() if isinstance(latest_key, bytes) else latest_key
            parts = latest_key_str.split(":")
            if len(parts) < 4:
                continue
            cid = parts[-1]

            if ns == "__empty__":
                # 主图 LATEST_POINTER —— 保留进 keep
                latest_per_ns[ns] = cid
            else:
                # fork LATEST_POINTER（在 namespaces 集合里 = 对应 checkpoint doc 还在）
                # 指向 user_saved 的保留，其他清
                if cid in user_saved:
                    latest_per_ns[ns] = cid
                else:
                    fork_pointers_to_clear.append(lk)

        # 4.2 独立扫描 fork LATEST_POINTER —— 捕获 namespaces 集合里没有的孤儿 LATEST_POINTER
        #     （指向的 checkpoint doc 已被清掉的 fork LATEST_POINTER）
        async for lk_bytes in self._redis.scan_iter(
            match=f"{LATEST_POINTER_PREFIX}:{thread_id}:*", count=200
        ):
            lk = lk_bytes.decode() if isinstance(lk_bytes, bytes) else lk_bytes
            # 格式: checkpoint_latest:{tid}:{ns_safe} —— ns_safe 可能含 :
            lparts = lk.split(":")
            if len(lparts) < 3:
                continue
            ns_safe_val = ":".join(lparts[2:])
            if ns_safe_val == "__empty__":
                continue  # 主图已在 4.1 处理
            if lk in fork_pointers_to_clear:
                continue  # 已在 4.1 处理
            # 拿指向的 cid
            current_val = await self._redis.get(lk)
            if not current_val:
                continue
            cv = current_val.decode() if isinstance(current_val, bytes) else current_val
            cv_parts = cv.split(":")
            if len(cv_parts) < 4:
                continue
            pointed_cid = cv_parts[-1]
            if pointed_cid in user_saved:
                continue  # 指向 user_saved 保留
            fork_pointers_to_clear.append(lk)

        # 5. 保留集合（只 2 路）：user_saved (redissaver 里每轮的 cid) + 主图 latest 指针
        #    不要 parent chain walk —— 中间 workflow cid 可以删，UI 回溯到 user_saved
        #    时 aget_tuple(cid) 只读该 cid 自己的 JSON，不依赖 parent 是否存在；
        #    parent_checkpoint_id 字段是悬空引用但不影响消息显示。
        #    不要 recent_keep (ULID top N) —— 不是必需，删了更省。
        keep: Set[str] = (
            set(latest_per_ns.values())
            | user_saved
        )

        # 候选删除集合
        to_delete = [c for c in all_checkpoints if c["cid"] not in keep]

        # 6. 扫 orphan write_keys_zset（CheckpointJanitor._scan_checkpoints 只扫 checkpoint:*，
        #    看不到 write_keys_zset:*，所以这里要单独扫一轮）
        #    orphan 判定：对应的 checkpoint:{tid}:{ns}:{cid} 不存在
        #    （LangGraph aput_writes 可能在 aput 失败 / 异常中断后留下半截 zset，
        #     没有 checkpoint doc 对应的 zset 不会影响主图恢复）
        orphan_zsets: List[str] = []
        async for zk in self._redis.scan_iter(
            match=f"{WRITE_KEYS_ZSET_PREFIX}:{thread_id}:*", count=200
        ):
            zks = zk.decode() if isinstance(zk, bytes) else zk
            # 格式: write_keys_zset:{tid}:{ns_safe}:{cid}
            zparts = zks.split(":")
            if len(zparts) < 4:
                continue
            # ns 在中间，cid 在最后
            ck = f"{CHECKPOINT_PREFIX}:{thread_id}:{':'.join(zparts[2:-1])}:{zparts[-1]}"
            exists = await self._redis.exists(ck)
            if not exists:
                orphan_zsets.append(zks)

        # 7. dry_run 直接返回统计
        if dry_run:
            return {
                "thread_id": thread_id,
                "scanned": len(all_checkpoints),
                "kept": len(keep),
                "deleted": len(to_delete),
                "deleted_cids": [c["cid"] for c in to_delete],
                "fork_latest_to_clear": len(fork_pointers_to_clear),
                "orphan_zsets": len(orphan_zsets),
                "keys_deleted": 0,
                "user_saved_count": len(user_saved),
            }

        # 8. 实际删除：主文档 + write_keys_zset + 所有 checkpoint_write 子文档
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

        # 9. 删 fork LATEST_POINTER（不再被 LangGraph 读到，留着只占 Redis 空间）
        keys_to_delete.extend(fork_pointers_to_clear)

        # 10. 删 orphan write_keys_zset（对应 checkpoint doc 已不存在）
        keys_to_delete.extend(orphan_zsets)

        # 11. 批量删（pipeline 分批 500 避免一次性阻塞 Redis）
        keys_deleted = 0
        if keys_to_delete:
            for i in range(0, len(keys_to_delete), 500):
                batch = keys_to_delete[i:i + 500]
                keys_deleted += await self._redis.delete(*batch)

        if to_delete or fork_pointers_to_clear or orphan_zsets:
            logger.info(
                f"[CheckpointJanitor] thread={thread_id[:12]}... 扫描={len(all_checkpoints)} "
                f"用户存的={len(user_saved)} 保留={len(keep)} 删checkpoint={len(to_delete)} "
                f"删fork_pointer={len(fork_pointers_to_clear)} "
                f"删orphan_zset={len(orphan_zsets)} keys={keys_deleted}"
            )

        return {
            "thread_id": thread_id,
            "scanned": len(all_checkpoints),
            "kept": len(keep),
            "deleted": len(to_delete),
            "deleted_cids": [c["cid"] for c in to_delete],
            "fork_latest_cleared": len(fork_pointers_to_clear),
            "orphan_zsets_cleared": len(orphan_zsets),
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

    # ----- 回溯专用：指针覆写 -----

    async def retarget_to(self, thread_id: str, target_cid: str) -> Dict[str, Any]:
        """覆写 ``checkpoint_latest`` 指针到 ``target_cid``，并删除其他 checkpoint 文档。

        用于 backtrack：绕过 ``graph.aupdate_state`` 的 artifact cid 副作用。
        后续 ``message_stream`` 从 ``LATEST_POINTER`` 读取，自然以 ``target_cid`` 启动，
        不再产生新的 artifact checkpoint（cid_E），避免 state_saver / memory 文件名 cid
        三方错位。

        保留集合语义（与 ``prune_thread`` 一致）：
            ``{target_cid} ∪ user_saved``，其中 ``user_saved`` 是 RedisStateSaver 的
            ``threads:{tid}:checkpoints`` HASH 里全部 cid字段（HASH 字段本身不会被本方法动，
            这里是保护其指向的 LangGraph storage 文档不被误删）。中间 parent chain 节点
            （不在 HASH 里、又 ≠ target）才允许删——这些节点的 parent_checkpoint_id 字段
            即使指向已删 cid 也不影响消息显示（``aget_tuple(cid)`` 只读该 cid 自己的 JSON）。

        state_saver 必须已绑定（``bind_state_saver``）：未绑定时空 user_saved 等于「全部 cid 都
        当中间节点删」，会破坏 HASH 索引 → storage 文档的耦合。这种情况直接 raise 让 caller
        决定怎么处理，而不是悄悄破坏一致性。

        Args:
            thread_id: 会话 ID
            target_cid: 目标 cid（必须已存在于 LangGraph storage）

        Returns:
            ``{thread_id, target_cid, scanned, deleted, kept_cids, keys_deleted}``

        Raises:
            RuntimeError: state_saver 未绑定
            ValueError: target_cid 不存在
        """
        # 1. state_saver 必须先绑定：未绑定时空 user_saved 会破坏 HASH → storage 耦合
        if self._state_saver is None:
            raise RuntimeError(
                f"[CheckpointJanitor] retarget_to: state_saver 未绑定 "
                f"(thread={thread_id[:12]}...)，无法保护 HASH 索引指向的 storage 文档，"
                f"拒绝执行以避免破坏 HASH → storage 文档耦合"
            )

        # 2. SCAN 拿全部 checkpoint 文档
        all_checkpoints = await self._scan_checkpoints(thread_id)

        # 3. 找 target_cid 的 ns（cid 可能跨 namespace）
        target_doc = next(
            (c for c in all_checkpoints if c["cid"] == target_cid), None
        )
        if target_doc is None:
            raise ValueError(
                f"[CheckpointJanitor] retarget_to: target_cid={target_cid} 不存在 "
                f"(thread={thread_id}, scanned={len(all_checkpoints)})"
            )

        # 4. 拿 RedisStateSaver 的 user_saved 集合（HASH 里的全部 cid 字段）
        user_saved: Set[str] = await self._load_user_saved_cids(thread_id)

        # 5. 保留集合：target + user_saved（HASH 里全部 cid）
        keep: Set[str] = (
            {target_cid}
            | user_saved
        )

        # 6. 覆写 LATEST_POINTER（值格式与 LangGraph aio.py 的 latest pointer 一致：
        #    ``checkpoint:{tid}:{ns_safe}:{cid}``）
        ns = target_doc["ns"]
        ns_s = self._ns_safe(ns)
        lk = f"{LATEST_POINTER_PREFIX}:{thread_id}:{ns_s}"
        value = f"{CHECKPOINT_PREFIX}:{thread_id}:{ns_s}:{target_cid}"
        await self._redis.set(lk, value)

        # 7. 只删「既不在 HASH 里、又不是 target」的 storage 文档 + 关联 write data
        to_delete = [c for c in all_checkpoints if c["cid"] not in keep]
        keys_to_delete: List[str] = []
        for c in to_delete:
            cid = c["cid"]
            c_ns_s = self._ns_safe(c["ns"])
            keys_to_delete.append(
                f"{CHECKPOINT_PREFIX}:{thread_id}:{c_ns_s}:{cid}"
            )
            keys_to_delete.append(
                f"{WRITE_KEYS_ZSET_PREFIX}:{thread_id}:{c_ns_s}:{cid}"
            )
            pattern = (
                f"{CHECKPOINT_WRITE_PREFIX}:{thread_id}:{c_ns_s}:{cid}:*"
            )
            async for k in self._redis.scan_iter(match=pattern, count=200):
                ks = k.decode() if isinstance(k, bytes) else k
                keys_to_delete.append(ks)

        # 8. 分批 delete（pipeline 500/批，避免阻塞 Redis）
        keys_deleted = 0
        if keys_to_delete:
            for i in range(0, len(keys_to_delete), 500):
                batch = keys_to_delete[i:i + 500]
                keys_deleted += await self._redis.delete(*batch)

        # 9. 清 fork LATEST_POINTER（namespace != "__empty__" 的所有 LATEST_POINTER）
        #    回溯后 fork 不再重跑，主图恢复也用不到，留着只占空间
        #    保留逻辑：必须保留 __empty__ 的 LATEST_POINTER（已在 step 6 覆写到 target_cid）
        fork_pointers_to_clear: List[str] = []
        async for fk in self._redis.scan_iter(
            match=f"{LATEST_POINTER_PREFIX}:{thread_id}:*", count=200
        ):
            fks = fk.decode() if isinstance(fk, bytes) else fk
            fparts = fks.split(":")
            if len(fparts) >= 3 and fparts[2] != "__empty__":
                # 进一步检查：fork LATEST_POINTER 指向的 cid 是否在 user_saved
                # 极少见：用户回溯到的 cid 恰好也是某个 fork 的 LATEST_POINTER 目标
                # 这种情况下 pointer 仍指向有效 cid，保留无害
                current_val = await self._redis.get(fks)
                if current_val:
                    cv = current_val.decode() if isinstance(current_val, bytes) else current_val
                    cv_parts = cv.split(":")
                    if len(cv_parts) >= 4:
                        pointed_cid = cv_parts[-1]
                        if pointed_cid in user_saved:
                            continue  # 跳过，不清
                fork_pointers_to_clear.append(fks)

        # 10. 扫 orphan write_keys_zset（对应 checkpoint doc 已不存在）
        #    与 prune_thread 同源：LangGraph aput_writes 异常时可能留下 zset 但 checkpoint doc 被清
        orphan_zsets: List[str] = []
        async for zk in self._redis.scan_iter(
            match=f"{WRITE_KEYS_ZSET_PREFIX}:{thread_id}:*", count=200
        ):
            zks = zk.decode() if isinstance(zk, bytes) else zk
            zparts = zks.split(":")
            if len(zparts) < 4:
                continue
            ck = f"{CHECKPOINT_PREFIX}:{thread_id}:{':'.join(zparts[2:-1])}:{zparts[-1]}"
            if not await self._redis.exists(ck):
                orphan_zsets.append(zks)

        # 11. 把这两类也并入批量删
        extra_keys = fork_pointers_to_clear + orphan_zsets
        if extra_keys:
            for i in range(0, len(extra_keys), 500):
                batch = extra_keys[i:i + 500]
                keys_deleted += await self._redis.delete(*batch)

        logger.info(
            f"[CheckpointJanitor] retarget_to thread={thread_id[:12]}... "
            f"target={target_cid} 扫描={len(all_checkpoints)} "
            f"保留={len(keep)}(target+user_saved={len(user_saved)}) "
            f"删除={len(to_delete)} 删fork_pointer={len(fork_pointers_to_clear)} "
            f"删orphan_zset={len(orphan_zsets)} keys={keys_deleted}"
        )

        return {
            "thread_id": thread_id,
            "target_cid": target_cid,
            "scanned": len(all_checkpoints),
            "deleted": len(to_delete),
            "kept_cids": sorted(keep),
            "fork_latest_cleared": len(fork_pointers_to_clear),
            "orphan_zsets_cleared": len(orphan_zsets),
            "keys_deleted": keys_deleted,
        }

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