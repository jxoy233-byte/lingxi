"""
Checkpoint prune 管理端点

解决问题
========
LangGraph ``AsyncRedisSaver`` 每跑一个节点就 ``aput()`` 一次，每次多轮对话
会攒几十~几百个 checkpoint，dump.rdb 被吹到 GB 级且启动时 RDB 反序列化
拖慢 chatme_main。本 router 暴露手动"清理冗余 checkpoint"的入口；
后台已在 ``ChatService._save_round_checkpoint`` 每轮 round 收尾时
异步 prune（fire-and-forget，不阻塞主流程）。

端点
====
- POST /admin/checkpoints/prune   触发清理（dry_run 预览 / 实际删）

保留规则（详见 ``ChatWorkflow/CheckpointJanitor.py`` 头注释）
  1. ``checkpoint_latest:{tid}:{ns}`` 指向的最新（LangGraph 自管，不能动）
  2. RedisStateSaver ``threads:{tid}:checkpoints`` HASH 里所有 cid
     —— 每轮对话完成时由 ``ChatService._save_round_checkpoint`` 写入；
     LangGraph 跑 ReAct 产生的 node-level 中间 checkpoint 不在 hash 里，全清

其余 ``checkpoint:{tid}:*`` / ``checkpoint_write:{tid}:*`` /
``write_keys_zset:{tid}:*`` 全删。不动 ``checkpoint_latest`` 指针，
不动 ChatMe 自己的 ``permission`` / ``interrupt`` / ``memory`` 等命名空间。

UI 回溯到 user_saved cid 时 ``aget_tuple(cid)`` 只读该 cid 自己的 JSON，
parent_checkpoint_id 即使指向已删 cid 也不影响该轮消息显示。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ChatMe.LoggingManager.logging_config import get_logger

# 与 APIRouter/main.py 共享全局 chat_service（由 chat_service_lifespan 注入）
from ChatMe.APIRouter.main import chat_service

logger = get_logger("checkpoint_janitor")

router = APIRouter(prefix="/admin", tags=["checkpoint_janitor"])


class PruneRequest(BaseModel):
    """Prune 请求 payload —— 字段全部可选，默认值匹配最常见的 dry_run 预览场景。"""

    session_id: Optional[str] = Field(
        default=None,
        description="指定单个 thread；留空 = 所有 thread",
    )
    dry_run: bool = Field(
        default=True,
        description="True 只统计不删除；False 才真删",
    )
    min_scanned: int = Field(
        default=1,
        ge=1,
        description="跳过 checkpoint 数 < 该阈值的 thread（省 IO）",
    )


@router.post(
    "/checkpoints/prune",
    summary="触发 LangGraph checkpoint 冗余清理（dry_run 预览 / 实际删）",
)
async def admin_prune_checkpoints(req: PruneRequest) -> dict:
    """触发 ``CheckpointJanitor`` 清理冗余 checkpoint。

    行为：
      - 默认 dry_run=True，只返回每个 thread 的 scanned/kept/deleted 统计，前端预览用
      - dry_run=False 才真删；删完后返回 ``keys_deleted`` 总数
      - 保留集 = RedisStateSaver hash 的所有 cid + LangGraph latest 指针指向的 cid

    触发时机：
      - 默认后台已 hook 进 ``_save_round_checkpoint``，每轮 round 收尾时自动 prune
      - 本端点用于手动触发（前端 Settings dialog「立即清理」/ 运维 dump.rdb 前压缩）
    """
    janitor = chat_service.checkpoint_janitor
    if janitor is None:
        raise HTTPException(status_code=503, detail="CheckpointJanitor 未初始化")

    try:
        if req.session_id:
            results = [
                await janitor.prune_thread(
                    req.session_id,
                    dry_run=req.dry_run,
                )
            ]
        else:
            results = await janitor.prune_all_threads(
                dry_run=req.dry_run,
                min_scanned=req.min_scanned,
            )
    except Exception as e:
        logger.error(f"[checkpoint_janitor] prune 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"prune 失败: {e}")

    total_scanned = sum(r["scanned"] for r in results)
    total_deleted = sum(r["deleted"] for r in results)
    total_keys_deleted = sum(r.get("keys_deleted", 0) for r in results)
    total_user_saved = sum(r.get("user_saved_count", 0) for r in results)
    return {
        "ok": True,
        "dry_run": req.dry_run,
        "thread_count": len(results),
        "total_scanned": total_scanned,
        "total_user_saved": total_user_saved,
        "total_deleted": total_deleted,
        "total_keys_deleted": total_keys_deleted,
        "per_thread": results,
    }