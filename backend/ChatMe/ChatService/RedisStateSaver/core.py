import json
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional

import redis.asyncio as redis

from ChatMe.ChatService.RedisStateSaver.config import REDIS_URL
from ChatMe.LoggingManager.logging_config import get_logger


class RedisStateSaver:
    """
    管理保存Message状态，通过读写redis的数据
    """

    def __init__(self):
        self.logger = get_logger(__class__.__name__)
        self.redis_client = redis.from_url(REDIS_URL)
        self.redis_prefix = "threads"

    async def connect(self):
        """建立连接"""
        await self.redis_client.ping()

    async def close(self):
        """关闭连接"""
        await self.redis_client.close()

    def _build_key(self, thread_id: str) -> str:
        """
        构建redis key
        :param thread_id: 会话id
        :return: redis key 字符串
        """
        return f"{self.redis_prefix}:{thread_id}:checkpoints"

    async def write_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        *,
        elapsed_ms: Optional[int] = None,
        token_usage: Optional[Dict[str, Any]] = None,
        status: str = "completed",
    ) -> bool:
        """
        写入 checkpoint 检查点到指定 thread_id 下

        :param thread_id: 会话id
        :param checkpoint_id: 检查点id
        :param elapsed_ms: 本轮耗时（毫秒）。可选，正常完成时为整轮时长，中断时为已耗时（部分）。
        :param token_usage: 本轮 token 用量统计。可选，dict 形如 {"prompt": N, "completion": N, "total": N}。
        :param status: 本轮收尾状态。"completed" = 正常完成；"interrupted" = 用户中断。
                       通过 status 区分两类条目，便于排查 / 前端展示。
        :return: 写入状态
        """
        key = self._build_key(thread_id)
        ts = datetime.now().isoformat()
        value_data = {
            "ts": ts,
            "checkpoint_id": checkpoint_id,
            "status": status,
        }
        # 仅写入非空字段，避免老数据 / 调用方不传时被 None 污染（前端 cp_meta.get(...) 会拿到 None）
        if elapsed_ms is not None:
            value_data["elapsed_ms"] = elapsed_ms
        if token_usage is not None:
            value_data["token_usage"] = token_usage

        value = json.dumps(value_data, ensure_ascii=False, default=str)

        try:
            await self.redis_client.hset(key, checkpoint_id, value)
            self.logger.debug(
                f"写入checkpoint成功(thread_id={thread_id}, checkpoint_id={checkpoint_id}, "
                f"status={status}, elapsed_ms={elapsed_ms})"
            )
            return True
        except Exception as e:
            self.logger.error(f"写入checkpoint失败(thread_id={thread_id}): {e}\n{traceback.format_exc()}")
            return False

    async def get_checkpoints(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        获取指定thread_id下的每轮对话checkpoint_id
        :param thread_id:
        :return:
        """
        key = self._build_key(thread_id)

        try:
            hash_data = await self.redis_client.hgetall(key)
            if not hash_data:
                self.logger.debug(f"无checkpoints(thread_id={thread_id})")
                return []

            checkpoints = []
            for checkpoint_id, value_str in hash_data.items():
                try:
                    value_data = json.loads(value_str)
                    checkpoints.append(value_data)
                except json.JSONDecodeError:
                    checkpoints.append({"checkpoint_id": checkpoint_id, "ts": None})

            checkpoints.sort(key=lambda x: x.get("ts", "") or "")
            self.logger.debug(f"获取checkpoints成功(thread_id={thread_id}, count={len(checkpoints)})")
            return checkpoints

        except Exception as e:
            self.logger.error(f"获取checkpoints失败(thread_id={thread_id}): {e}\n{traceback.format_exc()}")
            return []

    async def delete_checkpoint(self, thread_id: str, checkpoint_id: str) -> bool:
        """
        删除指定thread_id下的指定checkpoint_id
        :param thread_id:
        :param checkpoint_id:
        :return: 状态
        """
        key = self._build_key(thread_id)

        try:
            await self.redis_client.hdel(key, checkpoint_id)
            self.logger.debug(f"删除checkpoint成功(thread_id={thread_id}, checkpoint_id={checkpoint_id})")
            return True
        except Exception as e:
            self.logger.error(f"删除checkpoint失败(thread_id={thread_id}, checkpoint_id={checkpoint_id}): {e}")
            return False

    async def delete_thread(self, thread_id: str) -> bool:
        """
        删除指定thread_id下的所有checkpoint_id
        :param thread_id:
        :return: 状态
        """
        key = self._build_key(thread_id)

        try:
            await self.redis_client.delete(key)
            self.logger.info(f"删除会话所有checkpoints(thread_id={thread_id})")
            return True
        except Exception as e:
            self.logger.error(f"删除会话失败(thread_id={thread_id}): {e}")
            return False

    async def delete_latest_checkpoint(self, thread_id: str):
        """                                                                                                               
        删除指定thread_id下最新的checkpoint                                                                               
        """
        try:
            checkpoints = await self.get_checkpoints(thread_id)
            if not checkpoints:
                return False

            # checkpoints 按 ts 升序排列，最后一个就是最新的
            latest = checkpoints[-1]
            checkpoint_id = latest["checkpoint_id"]

            key = self._build_key(thread_id)
            await self.redis_client.hdel(key, checkpoint_id)

            self.logger.debug(f"删除最新checkpoint成功(thread_id={thread_id}, checkpoint_id={checkpoint_id})")
            return True
        except Exception as e:
            self.logger.error(f"删除最新checkpoint失败(thread_id={thread_id}): {e}")
            return False
