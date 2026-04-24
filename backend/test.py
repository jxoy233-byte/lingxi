import asyncio
import platform
import sys
from pathlib import Path
import os

from enum import Enum
from shutil import which

import redis
from anyio.lowlevel import checkpoint
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from backend.ChatMe.ChatWorkflow.core import ChatWorkflow


async def test2():
    chatworkflow = ChatWorkflow()
    await chatworkflow.ainit()

    redis_client = chatworkflow.checkpointer._redis
    print(redis_client)

    # HSET "threads:d82812cb2da54e15b749f6e2ad56d65b:checkpoints" "1f13fbef-1cfb-6b50-801f-69ebc3969ff0" "{\"ts\": \"2026-04-24T17:21:15.875006\", \"checkpoint_id\": \"1f13fbef-1cfb-6b50-801f-69ebc3969ff0\"}"
    backtrack_config = {"configurable": {"thread_id": "a746fe1d236a4fb98f22f1ba68d88c75","checkpoint_id":"1f13fc48-0de6-604e-801c-a1125e1f1363"}}
    config = {"configurable": {"thread_id": "a746fe1d236a4fb98f22f1ba68d88c75"}}
    state = await chatworkflow.graph.aget_state(config=config)
    print(state)
    print("-------"*15)

    # backtrack_state = await chatworkflow.graph.aget_state(config=backtrack_config)
    # print(backtrack_state)
    # print("-------"*15)
    # await chatworkflow.graph.aupdate_state(config=config, values=backtrack_state.values)
    #
    # state = await chatworkflow.graph.aget_state(config=config)
    # print(state)

if __name__ == "__main__":
    asyncio.run(test2())
