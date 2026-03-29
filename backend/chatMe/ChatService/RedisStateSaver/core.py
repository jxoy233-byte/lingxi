from typing import Any, Dict, List
from datetime import datetime

import json
import redis.asyncio as redis

from chatMe.ChatService.RedisStateSaver.config import REDIS_URL


class RedisStateSaver:
    """
    管理保存Message状态，通过读写redis的数据
    """

    def __init__(self):
        self.redis_client = redis.from_url(REDIS_URL)
        self.redis_prefix = "threads"

    async def connect(self):
        """建立连接"""
        await self.redis_client.ping()

    async def close(self):
        """关闭连接"""
        await self.redis_client.close()

    def _build_key(self, thread_id: str) ->str:
        """
        构建redis key
        :param thread_id: 会话id
        :return: redis key 字符串
        """
        return f"{self.redis_prefix}:{thread_id}:checkpoints"

    async def write_checkpoint(self, thread_id: str, checkpoint_id: str):
        """
        写入 checkpoint 检查点到指定 thread_id 下
        :param thread_id: 会话id
        :param checkpoint_id: 检查点id
        :param metadata: 检查点元数据
        :return: 写入状态
        """
        key = self._build_key(thread_id)

        ts = datetime.now().isoformat()
        value_data = {
            "ts": ts,
            "checkpoint_id": checkpoint_id,
        }

        value = json.dumps(value_data, ensure_ascii=False, default= str)

        await self.redis_client.hset(key, checkpoint_id, value)

    async def get_checkpoints(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        获取指定thread_id下的每轮对话checkpoint_id
        :param thread_id:
        :return:
        """
        key = self._build_key(thread_id)

        hash_data = await self.redis_client.hgetall(key)
        if not hash_data:
            return []

        checkpoints = []

        for checkpoint_id ,value_str in hash_data.items():
            try:
                value_data = json.loads(value_str)
                checkpoints.append(value_data)
            except json.JSONDecodeError as e:
                checkpoints.append({
                    "checkpoint_id": checkpoint_id,
                    "ts": None,
                })

        checkpoints.sort(key=lambda x: x.get("ts","") or "")

        return checkpoints

    async def delete_checkpoint(self, thread_id: str, checkpoint_id: str) -> bool:
        """
        删除指定thread_id下的指定checkpoint_id
        :param thread_id:
        :param checkpoint_id:
        :return: 状态
        """
        key = self._build_key(thread_id)

        await self.redis_client.hdel(key, checkpoint_id)

        return True


    async def delete_thread(self, thread_id: str) -> bool:
        """
        删除指定thread_id下的所有checkpoint_id
        :param thread_id:
        :return: 状态
        """
        key = self._build_key(thread_id)

        await self.redis_client.delete(key)

        return True
