"""
消息队列 REST API（会话忙碌时排队发送）

Redis 存储（db1，state_saver 同库）：
- LIST `queue:{sid}`
  - 元素：JSON `{"message": str, "quote": str|null, "queued_at": float}`
  - 顺序：FIFO（LPUSH 入队、RPOP 弹下一条）
  - 边界：max 100 条 / 单条 message ≤ 4000 字符（与 input 与后端 message_stream 一致）

端点：
- POST   /chat/{sid}/queue                 入队（append 到队尾）
- GET    /chat/{sid}/queue                 列出全部（FIFO 顺序）
- DELETE /chat/{sid}/queue[?idx=N]         删单条（idx=0 是最先入队的）
                                            ；无 idx=清空全部

为什么后端不主动 drain：SSE 已经在前端持有 per-session 的 stream 状态机，
让前端在 `done` 事件末尾弹下一条再 sendMessage 是最直观的语义。后端只承担
"持久化 + 列表 + 删除" 三件套，多 tab / F5 刷新靠 Redis 兜底。

为什么只存 message + quote：file 是 File 对象无法序列化、且 file 状态
本就在前端 selectedFiles 里，强行序列化等于把 Redis 当 blob 存。文件场景
让用户等流式结束再发，按 input 最大 200 字 + file 不可入队的约定。
"""

from __future__ import annotations

import json
import time
from typing import List, Optional

import redis
from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field

from ChatMe.ChatMeConfig import get_redis_state_saver_url
from ChatMe.LoggingManager.logging_config import get_logger


logger = get_logger("MessageQueueAPI")

router = APIRouter(prefix="/chat", tags=["message_queue"])


# Redis 与 config（与 RedisStateSaver 同模式：db1 持久化）
_redis_url = get_redis_state_saver_url()
_redis_client = redis.from_url(_redis_url)


# Lua：用 LINDEX 读 + LREM(>=1, 元素) 删 保证"按 idx 删"原子。
# 不用事务 / pipeline 是因为 queue 操作极少并发（前端单 tab 串行调用）；
# 真要严格原子可走 WATCH/MULTI，但 LREM by value 本身够用。
_DEL_ITEM_LUA = """
local key = KEYS[1]
local target = ARGV[1]
local idx = tonumber(ARGV[2])
if idx < 0 or idx >= redis.call('LLEN', key) then
    return 0
end
local cur = redis.call('LINDEX', key, idx)
if cur == target then
    redis.call('LSET', key, idx, '__TOMBSTONE__')
    redis.call('LREM', key, 1, '__TOMBSTONE__')
    return 1
end
return 0
"""


# =========================================================================
# Config
# =========================================================================

QUEUE_KEY_PREFIX = "queue:"
MAX_QUEUE_SIZE = 20          # 单会话最多排队 100 条
MAX_MESSAGE_LEN = 4000        # 单条 message ≤ 4000 字符（与 ChatRequest 内部限制对齐）


def _queue_key(session_id: str) -> str:
    return QUEUE_KEY_PREFIX + session_id


# =========================================================================
# Pydantic models
# =========================================================================


class QueueItemIn(BaseModel):
    """POST /chat/{sid}/queue 的入参"""
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN, description="排队消息文本")
    quote: Optional[str] = Field(default=None, description="可选引用块原文（与 input 顶部 quote 一致）")


# =========================================================================
# 端点
# =========================================================================


@router.post("/{session_id}/queue", summary="把消息追加到会话排队队列（FIFO 队尾）")
async def enqueue_message(
    session_id: str = Path(..., description="会话ID"),
    body: QueueItemIn = Body(...),
):
    """把一条消息加入队列尾部。

    返回:
        {"ok": true, "index": 新位置 idx, "total": 当前队列长度}
    """
    r = _redis_client
    key = _queue_key(session_id)
    # 容量护栏
    cur_len = r.llen(key)
    if cur_len >= MAX_QUEUE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"队列已满（{MAX_QUEUE_SIZE} 条）。请先清空或等队列消耗。",
        )
    payload = json.dumps(
        {
            "message": body.message,
            "quote": body.quote,
            "queued_at": time.time(),
        },
        ensure_ascii=False,
    )
    new_idx = r.rpush(key, payload)
    if new_idx is None or new_idx <= 0:
        # redis-py 4.x LPUSH/RPUSH in some pipelines returns None on edge; rare
        raise HTTPException(status_code=500, detail="写入队列失败")
    logger.info(f"[queue] session={session_id[:8]} enqueue idx={new_idx - 1} len={new_idx}")
    return {"ok": True, "index": new_idx - 1, "total": new_idx}


@router.get("/{session_id}/queue", summary="取会话的全部排队消息（FIFO 顺序）")
async def list_queue(
    session_id: str = Path(..., description="会话ID"),
):
    """返回 FIFO 顺序的全部队列项。

    返回:
        {"items": [{"message": str, "quote": str|null, "queued_at": float}, ...]}
    """
    r = _redis_client
    key = _queue_key(session_id)
    raw_list: List[bytes] = r.lrange(key, 0, -1)
    items = []
    for raw in raw_list:
        try:
            items.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            # 外部脏数据：跳过不让整个列表挂
            logger.warning(f"[queue] session={session_id[:8]} 跳过损坏的队列项")
            continue
    return {"items": items, "total": len(items)}


@router.delete("/{session_id}/queue", summary="删单条 或 清空队列")
async def delete_queue_item(
    session_id: str = Path(..., description="会话ID"),
    idx: Optional[int] = Query(
        default=None,
        ge=0,
        description="要删的 idx（FIFO 顺序：0 = 最先入队）。不传=清空全部。",
    ),
):
    """idx 缺省 → 清空全部；idx 指定 → 按 idx 删一条（按 LINDEX 校验 + LSET tombstone + LREM 删）。"""
    r = _redis_client
    key = _queue_key(session_id)

    if idx is None:
        # 清空全部
        deleted = r.delete(key)
        logger.info(f"[queue] session={session_id[:8]} clear all (deleted={deleted})")
        return {"ok": True, "deleted_all": True, "removed": int(deleted)}

    # 单条删除：LINDEX 读 → LSET 占位 → LREM 真删（避免 LREM by value 在重复 message 场景下误删）
    cur = r.lindex(key, idx)
    if cur is None:
        raise HTTPException(status_code=404, detail=f"队列 idx {idx} 不存在")
    target = cur if isinstance(cur, str) else cur.decode()
    try:
        removed = int(r.eval(_DEL_ITEM_LUA, 1, key, target, idx))
    except redis.exceptions.RedisError as e:
        # Lua 不可用（罕见）→ 退化到 LREM by value（接受重复 message 误删风险）
        logger.warning(f"[queue] session={session_id[:8]} Lua eval 失败，fallback LREM: {e}")
        removed = int(r.lrem(key, 1, target))
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"队列 idx {idx} 不存在或已被并发删除")
    logger.info(f"[queue] session={session_id[:8]} delete idx={idx}")
    return {"ok": True, "deleted_idx": idx, "remaining": r.llen(key)}
