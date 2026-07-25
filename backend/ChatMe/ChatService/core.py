import asyncio
import json
import os
import time
import traceback
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import AsyncGenerator, Set, List, Any, Optional, Dict

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.types import StateSnapshot, Command
from langgraph_sdk.auth.exceptions import HTTPException
from redisvl.query import FilterQuery
from langgraph.checkpoint.redis.util import from_storage_safe_id

from ChatMe.ChatService import FILE_MAX_LENGTH, FILE_ALLOWED_TYPES
from ChatMe.ChatService.FilesLoaders import UploadFileWithId
from ChatMe.ChatService.RedisStateSaver.core import RedisStateSaver
from ChatMe.ChatService.config.models import MessageRole, Message, Conversation, ConversationSimple
from ChatMe.ChatService.FilesLoaders.core import FilesLoaders, OutputFormat
from ChatMe.ChatWorkflow import ChatWorkflow, MemoryUpdateFormat
from ChatMe.ChatWorkflow.config.models import AIMessageType
from ChatMe.LoggingManager.logging_config import (
    get_logger,
    flush_pending_thinking_for_session,
)


class ChatService:
    """
    ChatMe服务对象：
    实现自定义langgraph服务
    """

    def __init__(self, workflow: ChatWorkflow):
        self.logger = get_logger(__class__.__name__)
        self.chat_workflow = workflow
        self.checkpointer = self.chat_workflow.checkpointer
        self.graph = self.chat_workflow.graph
        self.state_saver = RedisStateSaver()
        self.redis_client = self.checkpointer._redis
        self._memory_update_tasks: Dict[str, asyncio.Task] = {}

    @property
    async def aget_conversation_ids(self) -> List[str]:
        """
        获取Redis中所有不重复的thread_id列表(基于alist方法为启发)
        :return: 所有不重复的thread_id列表
        """
        # 构造Redis Search查询
        query = FilterQuery(
            filter_expression="*",
            return_fields=["thread_id"],
            num_results=10000,
            sort_by=None,
        )

        try:
            # 执行查询
            search_results = await self.checkpointer.checkpoints_index.search(query)

            # 风险点1：处理search_results为None的情况
            if search_results is None:
                self.logger.debug("Redis搜索结果为空（search_results为None）")
                return []

            # 风险点2：确保docs是可遍历的列表
            docs = getattr(search_results, "docs", [])
            if not isinstance(docs, list):
                self.logger.warning(f"Redis搜索结果docs格式异常，非列表类型：{type(docs)}")
                return []

            thread_ids: Set[str] = set()
            for doc in docs:
                # 风险点3：安全获取thread_id，避免属性不存在
                safe_thread_id = getattr(doc, "thread_id", None)
                if not safe_thread_id:  # 跳过空的safe_id
                    continue

                try:
                    # 风险点4：捕获ID转换函数的异常
                    raw_thread_id = from_storage_safe_id(safe_thread_id)
                    if raw_thread_id:  # 跳过转换后为空的ID
                        thread_ids.add(raw_thread_id)
                except Exception as e:
                    self.logger.warning(f"转换safe_id失败：{safe_thread_id}，错误：{e}")
                    continue

            # 排序并返回（空集合会返回空列表）
            return sorted(list(thread_ids))

        # 风险点5：捕获所有异常，而非仅HTTPException
        except HTTPException as e:
            self.logger.warning(f"Redis查询触发HTTP异常（无历史数据）：{e}")
            return []
        except Exception as e:
            # 兜底捕获所有其他异常（如连接错误、序列化错误等）
            self.logger.warning(f"获取conversation_ids失败：{type(e).__name__}: {e}")
            return []

    @staticmethod
    async def process_files(files: List[UploadFileWithId], session_id: str) -> List[OutputFormat]:
        """
        处理上传的文件，返回处理后的文件内容和额外参数

        Args:
            files: 上传的文件列表
            session_id: 上传的会话id

        Returns:
            处理后的文件
        """
        if not files:
            return []

        fl = FilesLoaders(files,session_id=session_id)
        try:
            outputs = await fl.loading_files()

            return outputs
        finally:
            await fl.cleanup()

    @staticmethod
    async def remove_processed_files(output: OutputFormat):
        """
        删除处理后的文件

        Args:
            output: 需要删除的处理后的输出格式
        """
        file_path = output.file_path
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

    @staticmethod
    def _get_mime_type(suffix: str) -> str:
        """
        获取文件类型对应的MIME类型

        Args:
            suffix: 文件后缀

        Returns:
            str: 文件的MIME类型
        """
        mime_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".ppt": "application/vnd.ms-powerpoint",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
        }
        return mime_type_map.get(suffix, "application/octet-stream")

    async def build_files_content(
            self,
            processed_files: List[OutputFormat],
    ) -> Optional[HumanMessage]:
        """
        构建多模态消息内容

        Args:
            processed_files: 处理后的文件列表

        Returns:
            HumanMessage: 符合 OpenAI 多模态格式的HumanMessage消息内容
        """
        try:
            content = []

            if not processed_files:
                return None

            # 分离不同类型的文件
            images = [f for f in processed_files if f.type == "IMAGE"]
            texts = [f for f in processed_files if f.type == "TEXT"]
            documents = [f for f in processed_files if f.type == "DOCUMENT"]

            id = 0 # 用来区分每单个文件

            # 处理图片
            if images:
                for img in images:
                    if img.image_content:
                        mime_type = img.content_type or self._get_mime_type(img.suffix)
                        content.append({
                            "type": "text",
                            "text": f"-- {img.name} --\n",
                            "index": id
                        })
                        if img.is_oss:
                            image_url = img.image_content
                        else:
                            image_url = f"data:image/{mime_type};base64,{img.image_content}"
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": image_url},
                            "detail": "auto",
                            "index": id
                        })
                        id += 1


            # 处理文本文件
            if texts:
                for text in texts:
                    if text.text_content:
                        content.append({
                            "type": "text",
                            "text": f"-- {text.name} --\n{text.text_content}\n",
                            "index": id
                        })
                        id += 1

            # 处理文档文件
            if documents:
                for doc in documents:
                    if doc.text_content:
                        doc_label = self._get_mime_type(doc.suffix)
                        content.append({
                            "type": "text",
                            "text": f"-- {doc_label}:{doc.name} --\n{doc.text_content}\n",
                            "index": id
                        })
                        # content.append({
                        #     "type": "text",
                        #     "text": f"-- {doc.name} 内的图片 --\n",
                        #     "index": id
                        # })
                        # if doc.is_oss:
                        #     for img_url in doc.image_content:
                        #         content.append({
                        #             "type": "image_url",
                        #             "image_url": {"url": img_url},
                        #             "detail": "auto",
                        #             "index": id
                        #         })
                        # else:
                        #     for base64 in doc.image_content:
                        #         content.append({
                        #             "type": "image_url",
                        #             "image_url": {"url": f"data:image/png;base64,{base64}"},
                        #             "detail": "auto",
                        #             "index": id
                        #         })
                        id += 1

            # 直接存储整个 OutputFormat 列表到 additional_kwargs
            additional_kwargs = {
                "files": [
                    {
                        **asdict(f),
                    }
                    for f in processed_files],  # dataclass 转 dict
                "is_file": True,
            }

            files_content = HumanMessage(content=content, additional_kwargs=additional_kwargs)
        except Exception as e:
            self.logger.warning(f"构建多模态消息内容失败: {e}")
            return None

        return files_content


    async def _save_round_checkpoint(
        self,
        session_id: str,
        metrics: Optional[Dict[str, Any]] = None,
        *,
        status: str = "completed",
    ) -> Optional[str]:
        """
        保存每轮检查点。

        职责：
        - 写 checkpoint 元数据（checkpoint_id / elapsed_ms / token_usage / status）到 RedisStateSaver
          （app 层 Redis hash），**不再**通过 `graph.aupdate_state` 写回 LangGraph runtime state。
        - 调度本轮 memory 后台更新任务。

        为什么去掉 aupdate_state：
        每次 `aupdate_state` 都会在 LangGraph runtime 里生成一个新 checkpoint，把 runtime 指针往前推一格。
        在 interrupt+resume 场景下，这会导致 resume 时 runtime 已经站在"已完成上一轮"的位置，
        续接的 ainvoke 只能从入口重新跑，而不是从中断点继续。把 metadata 全部归 RedisStateSaver
        后，LangGraph state 不再被 metadata 写入污染，resume 就能从中断点继续。

        metrics 可选：传入 {"elapsed_ms": int, "token_usage": dict} 时同步写入 RedisStateSaver。
        get_conversation 时会按 checkpoint_index 顺序回填到对应 SUMMARY AIMessage.additional_kwargs，
        供前端回放展示用。

        status: 本轮收尾状态。"completed" = 正常完成；"interrupted" = 用户中断。
        默认 "completed"，中断分支调用时显式传 "interrupted"。

        :return 保存成功返回对应checkpoint_id
        """
        try:
            config = {"configurable": {"thread_id": session_id}}

            state = await self.graph.aget_state(config=config)

            checkpoint_id = state.config["configurable"]["checkpoint_id"]

            # 仅把非空 metrics 透传给 RedisStateSaver；老数据 / 调用方不传时字段不入 value_data
            elapsed_ms = int(metrics["elapsed_ms"]) if metrics and metrics.get("elapsed_ms") is not None else None
            token_usage = metrics.get("token_usage") if metrics else None

            ok = await self.state_saver.write_checkpoint(
                thread_id=session_id,
                checkpoint_id=checkpoint_id,
                elapsed_ms=elapsed_ms,
                token_usage=token_usage,
                status=status,
            )

            if not ok:
                self.logger.warning(
                    f"写入 checkpoint 失败(session_id={session_id}, cid={checkpoint_id})，跳过本轮 memory 调度"
                )
                return None

            # 更新每轮记忆文件 — 后台静默执行，不阻塞返回
            try:
                self._schedule_memory_update(
                    session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    state=state,
                )
            except Exception as e:
                self.logger.error(f"更新记忆文件失败(thread_id={session_id}): {str(e)}")

            return checkpoint_id

        except Exception as e:
            self.logger.error(f"保存每轮检查点失败(session_id:{session_id}): {str(e)}")
            return None

    def _schedule_memory_update(
        self,
        session_id: str,
        checkpoint_id: str,
        state: StateSnapshot,
    ) -> None:
        """后台调度记忆更新；同一会话按上一轮 task 串行执行。"""
        previous_task = self._memory_update_tasks.get(session_id)

        async def runner() -> bool:
            if previous_task and not previous_task.done():
                try:
                    await asyncio.shield(previous_task)
                except Exception as e:
                    self.logger.error(f"等待上一轮记忆更新失败(thread_id={session_id}): {e}")
            return await self._update_memory_bg(
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                state=state,
            )

        self._memory_update_tasks[session_id] = asyncio.create_task(runner())

    async def _wait_previous_memory_update(self, session_id: str) -> Optional[str]:
        """等待同一会话上一轮后台记忆更新结束，返回 done / failed；无等待则返回 None。"""
        task = self._memory_update_tasks.get(session_id)
        if task is None:
            return None
        if task.done():
            return self._get_memory_update_status(session_id)

        try:
            self.logger.info(f"等待上一轮记忆更新开始(session_id={session_id})")
            success = await asyncio.shield(task)
            status = "done" if success else "failed"
            self.logger.info(f"等待上一轮记忆更新完成(session_id={session_id}, status={status})")
            return status
        except Exception as e:
            self.logger.error(f"等待记忆更新失败(thread_id={session_id}): {e}")
            return "failed"

    def _get_memory_update_status(self, session_id: str) -> str:
        """获取当前会话最近一次后台记忆更新状态。"""
        task = self._memory_update_tasks.get(session_id)
        if task is None:
            return "idle"
        if not task.done():
            return "pending"
        try:
            return "done" if task.result() else "failed"
        except Exception:
            return "failed"

    async def _drop_memory_update_task(self, session_id: str) -> None:
        """移除并消费会话的后台记忆任务，避免遗留已完成/未完成 awaitable。"""
        task = self._memory_update_tasks.pop(session_id, None)
        if task is None:
            return
        try:
            if task.done():
                task.result()
            else:
                await asyncio.shield(task)
        except Exception as e:
            self.logger.error(f"清理记忆更新任务失败(thread_id={session_id}): {e}")

    async def _update_memory_bg(
        self,
        session_id: str,
        checkpoint_id: str,
        state: StateSnapshot
    ) -> bool:
        """后台静默更新记忆，不阻塞主流程"""
        try:
            memory_user_message = state.values.get("memory_user_message")
            memory_ai_response = state.values.get("memory_ai_response")
            memory_tool_calls = state.values.get("memory_tool_calls")
            memory_tool_results = state.values.get("memory_tool_results")

            memory_update_format = MemoryUpdateFormat(
                user_message=memory_user_message,
                ai_response=memory_ai_response,
                tool_calls=memory_tool_calls,
                tool_results=memory_tool_results
            )

            return await self.chat_workflow.memory_manager.update_memory(
                thread_id=session_id,
                checkpoint_id=checkpoint_id,
                memory_data=memory_update_format
            )
        except Exception as e:
            self.logger.error(f"后台更新记忆失败(thread_id={session_id}): {str(e)}")
            return False

    async def _delete_last_round_checkpoint(self, session_id: str):
        """
        删除指定会话的最新一个 checkpoint 都索引以及对应检查点的记忆文件
        """
        try:
            # 获取所有 checkpoints，最新的在最后
            checkpoints = await self.state_saver.get_checkpoints(session_id)
            if not checkpoints:
                self.logger.warning(f"无 checkpoint 可删除(session_id={session_id})")
                return False

            latest_checkpoint_id = checkpoints[-1]["checkpoint_id"]

            # 删除 RedisStateSaver 中的索引记录
            await self.state_saver.delete_checkpoint(session_id, latest_checkpoint_id)

            # 删除对应的记忆备份文件
            await self.chat_workflow.memory_manager.delete_latest_memory(thread_id=session_id)

            self.logger.info(f"删除最新 checkpoint 成功(session_id={session_id}, checkpoint_id={latest_checkpoint_id})")
            return latest_checkpoint_id

        except Exception as e:
            self.logger.error(f"删除最新 checkpoint 失败(session_id={session_id}): {e}")
            return None

    async def _judge_is_interrupted(self, session_id: str) -> bool:
        return await self.redis_client.exists(f"interrupt:{session_id}")

    async def _get_interrupted_info(self, session_id: str) -> Dict[str, Any]:
        key_value = await self.redis_client.hgetall(f"interrupt:{session_id}")
        # Redis 返回 bytes 类型，需要转换
        return {
            k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
            for k, v in key_value.items()
        }

    @staticmethod
    async def _switch_chunk_to_str(chunk_content: Any):
        content = chunk_content
        if isinstance(content, str):
            content = str(content)
        elif isinstance(content, dict):
            if "type" in content and content.get("type") == "text":
                content = str(content.get("text"))
        elif isinstance(content, list):
            tmp = ""
            for c in content:
                if isinstance(c, str):
                    tmp += str(c)
                elif isinstance(c, dict):
                    if "type" in c and c.get("type") == "text":
                        tmp += str(c.get("text"))
            content = tmp
        else:
            content = str(content)
        return content

    _WORKFLOW_TOKEN_NODES = ("input_parse_node", "agent_node", "should_end_node", "final_node")

    @staticmethod
    def _new_workflow_token_usage() -> Dict[str, Any]:
        """每个请求内的 token 聚合对象；不入 Redis，避免 checkpoint 回放重复累计。"""
        empty_bucket = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}
        return {
            "prompt": 0,
            "completion": 0,
            "total": 0,
            "calls": 0,
            "by_node": {name: dict(empty_bucket) for name in ChatService._WORKFLOW_TOKEN_NODES},
        }

    @staticmethod
    def _accumulate_workflow_tokens(usage: Dict[str, Any], node_name: Optional[str], output: Any) -> bool:
        """
        从 on_chat_model_end 投递的 AIMessage 中读取 usage_metadata，按 langgraph_node 入桶。
        只统计 4 个工作流主节点；非工作流 LLM（react_compact_llm / file_process_node / sub-agent）跳过。
        """
        if node_name not in ChatService._WORKFLOW_TOKEN_NODES or output is None:
            return False
        meta = getattr(output, "usage_metadata", None) or {}
        if not isinstance(meta, dict):
            return False
        prompt = int(meta.get("input_tokens", 0) or 0)
        completion = int(meta.get("output_tokens", 0) or 0)
        total = int(meta.get("total_tokens", 0) or 0)
        if not (prompt or completion or total):
            return False
        usage["prompt"] += prompt
        usage["completion"] += completion
        usage["total"] += total
        usage["calls"] += 1
        bucket = usage["by_node"][node_name]
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        bucket["total"] += total
        bucket["calls"] += 1
        return True

    @staticmethod
    def _elapsed_ms_since(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    async def message_stream(
        self,
        message: str,
        session_id: str = None,
        processed_outputs: List[OutputFormat] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式响应用户信息

        Args:
            message: 用户信息
            session_id: 会话id
            processed_outputs: 已处理好的文件内容结果

        Yields:
            基于流式传输的 JSON 字符串
        """
        session_ids = await self.aget_conversation_ids

        # 会话ID处理：无则新建，有则直接使用
        if session_id == "" or session_id is None:
            session_id = str(uuid.uuid4().hex)
            self.logger.info(f"\n------------------------------------------------------------\n  新建会话 session_id={session_id}\n------------------------------------------------------------")
        else:
            self.logger.info(f"\n------------------------------------------------------------\n  进入会话 session_id={session_id}\n------------------------------------------------------------")

        input_config = {
            "configurable" :{
                "thread_id" : session_id,
            }
        }

        # 如果有 processed_outputs（文件），设置 is_file=True
        has_files = processed_outputs and len(processed_outputs) > 0

        messages = []
        if has_files:
            files_content = await self.build_files_content(processed_outputs)
            messages.append(files_content)

        additional_kwargs = {
            "updated_at": datetime.now(),
            "is_file": False,
        }
        message_content = HumanMessage(content=[{"type": "text", "text": message}], additional_kwargs=additional_kwargs)
        messages.append(message_content)

        # 清除中断状态，确保流式响应正常
        if await self._judge_is_interrupted(session_id):
            await self.redis_client.delete(f"interrupt:{session_id}")

        # 后端指标聚合：本回合 start_monotonic + 累计 token_usage；仅覆盖 4 个工作流主节点
        start_mono = time.monotonic()
        token_usage = self._new_workflow_token_usage()
        elapsed_ms = self._elapsed_ms_since(start_mono)
        full_response = ""
        try:
            yield json.dumps(
                {"type": "init", "session_id": session_id, "true_input": messages, "elapsed_ms": elapsed_ms, "token_usage": token_usage},
                ensure_ascii=False,
                default=str
            ) + "\n\n"

            memory_status = self._get_memory_update_status(session_id)
            if memory_status == "pending":
                yield json.dumps(
                    {"type": "memory_wait_start", "session_id": session_id, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                    ensure_ascii=False,
                    default=str
                ) + "\n\n"

                memory_status = await self._wait_previous_memory_update(session_id)

                yield json.dumps(
                    {"type": "memory_wait_done", "session_id": session_id, "status": memory_status or "done", "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                    ensure_ascii=False,
                    default=str
                ) + "\n\n"

            async for chunk in self.chat_workflow.astream(messages=messages, config=input_config):
                if chunk['event'] == 'on_chat_model_stream':
                    # 最终返回的chunk
                    if chunk['metadata']['langgraph_node'] and chunk['metadata']['langgraph_node'] == 'final_node':
                        content = await self._switch_chunk_to_str(chunk['data']['chunk'].content)
                        full_response += content
                        yield json.dumps(
                            {"type": "content", "content": content, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
                    elif chunk['metadata']['langgraph_node'] and chunk['metadata']['langgraph_node'] == 'input_parse_node':
                        content = await self._switch_chunk_to_str(chunk['data']['chunk'].content)
                        yield json.dumps(
                            {"type": "reasoning", "content": content, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
                    elif chunk['metadata']['langgraph_node'] and chunk['metadata']['langgraph_node'] == 'agent_node':
                        content = await self._switch_chunk_to_str(chunk['data']['chunk'].content)
                        yield json.dumps(
                            {"type": "reasoning", "content": content, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
                    else:
                        continue
                elif chunk['event'] == 'on_chat_model_end':
                    # 流末聚合 usage_metadata；只统计 4 个工作流主节点
                    self._accumulate_workflow_tokens(
                        token_usage,
                        (chunk.get('metadata') or {}).get('langgraph_node'),
                        (chunk.get('data') or {}).get('output'),
                    )
                elif chunk['event'] == 'on_tool_start':
                    tool_call_args = chunk['data'].get('input', {})
                    tool_call_name = chunk['name']
                    yield json.dumps(
                        {"type": "tool_call_name", "id": chunk["run_id"], "content": {'args': tool_call_args, 'name': tool_call_name}, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                        ensure_ascii=False,
                        default=str
                    ) + "\n\n"
                elif chunk['event'] == 'on_tool_end':
                    output_content = chunk['data']['output'].content
                    if output_content:
                        content = await self._switch_chunk_to_str(output_content)
                        yield json.dumps(
                            {"type": "tool_call_result", "id": chunk["run_id"], "content": content, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
        except Exception as e:
            error_detail = f"{str(e)}\n{traceback.format_exc()}"
            self.logger.error(f"流式响应异常(session_id:{session_id}): {error_detail}")
            # 异常返回错误信息 + 双换行符。yield 后立即 return，
            yield json.dumps(
                {"type": "error", "error": str(e), "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                ensure_ascii=False,
                default=str
            ) + "\n\n"

            # thinking_chain 收尾：flush per-session 临时文件到主文件（best-effort，失败不抛）
            flush_pending_thinking_for_session(session_id)
            return

        if await self._judge_is_interrupted(session_id):
            key_value = await self._get_interrupted_info(session_id)
            self.logger.debug(f"key_value: {key_value}")
            reason = key_value.get("reason", "user_initiated_interrupt")

            self.logger.info(f"会话{session_id}被中断: {reason}")

            checkpoint_id = await self._save_round_checkpoint(
                session_id,
                metrics={"elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                status="interrupted",
            )

            # 补充checkpoint_id字段进去
            await self.redis_client.hset(
                f"interrupt:{session_id}",
                mapping={
                    "reason": key_value.get("reason", "user_initiated_interrupt"),
                    "checkpoint_id": checkpoint_id,
                    "timestamp": key_value.get("timestamp", "")
                })

            yield json.dumps(
                {
                    "type": "interrupt",
                    "session_id": session_id,
                    "checkpoint_id": checkpoint_id,
                    "memory_status": self._get_memory_update_status(session_id),
                    "reason": reason,
                    "elapsed_ms": self._elapsed_ms_since(start_mono),
                    "token_usage": token_usage,
                },
                ensure_ascii=False,
                default=str
            ) + "\n\n"

            # thinking_chain 收尾：中断路径也 flush（保留中断前的思考过程）
            flush_pending_thinking_for_session(session_id)
            return

        checkpoint_id = await self._save_round_checkpoint(
            session_id,
            metrics={"elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
        )

        self.logger.info(f"会话 {session_id} 对话完成 (checkpoint: {checkpoint_id}) elapsed_ms={self._elapsed_ms_since(start_mono)} token_total={token_usage['total']}")

        # 返回最终完整结果
        yield json.dumps({
            "type": "done",
            "full_response": full_response,
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "memory_status": self._get_memory_update_status(session_id),
            "elapsed_ms": self._elapsed_ms_since(start_mono),
            "token_usage": token_usage,
        }) + "\n\n"

        # thinking_chain 收尾：正常完成路径 flush
        flush_pending_thinking_for_session(session_id)

    async def get_conversation(self, session_id: str) ->Conversation:
        """
        获取会话内容
        Args:
            session_id: 会话id
        Returns:
            会话内容
        """
        self.logger.info(f"\n------------------------------------------------------------\n  获取会话 session_id={session_id}\n------------------------------------------------------------")

        config = {"configurable": {"thread_id": session_id}}

        checkpoints = await self.state_saver.get_checkpoints(session_id)
        checkpoint_index = 0

        try:
            state = await self.graph.aget_state(config=config)
            # print(state)
            interrupted_info = await self._get_interrupted_info(session_id)
        except HTTPException as e:
            self.logger.error(f"获取会话状态异常(session_id:{session_id})：{str(e)}")
            return Conversation(session_id=session_id)

        messages_list = []
        if "messages" in state.values and state.values["messages"]:
            for msg in state.values["messages"]:
                if isinstance(msg, HumanMessage):
                    role = MessageRole.USER
                    files = []
                    is_file = msg.additional_kwargs.get("is_file", False)
                    human_message = (await self._switch_chunk_to_str(msg.content)).strip()

                    if is_file:
                        files = msg.additional_kwargs.get("files", [])
                        # 有文件时，也保留文本内容（content 可能包含文件描述和用户文本）
                        messages_list.append(Message(
                            role=role,
                            content=None,
                            files=files,
                            additional_kwargs={"is_file": True}
                        ))
                    elif human_message:
                        messages_list.append(Message(
                            role=role,
                            content=human_message,
                            files=files,
                            additional_kwargs=None
                        ))

                elif isinstance(msg, AIMessage):
                    role = MessageRole.AI
                    if msg.additional_kwargs.get("type") == AIMessageType.SUMMARY.value:
                        # 添加边界检查，避免数组越界
                        if checkpoint_index < len(checkpoints):
                            cp_meta = checkpoints[checkpoint_index]
                            msg.additional_kwargs["checkpoint_id"] = cp_meta["checkpoint_id"]
                            # 第一个 SUMMARY 消息的 last_checkpoint_id 为空
                            if checkpoint_index > 0:
                                msg.additional_kwargs["last_checkpoint_id"] = checkpoints[checkpoint_index - 1].get("checkpoint_id", "")
                            else:
                                msg.additional_kwargs["last_checkpoint_id"] = ""

                            # 注入计时和tokens消耗
                            if cp_meta.get("elapsed_ms") is not None:
                                msg.additional_kwargs["elapsed_ms"] = int(cp_meta["elapsed_ms"])
                            if cp_meta.get("token_usage"):
                                msg.additional_kwargs["token_usage"] = cp_meta["token_usage"]
                            # status 透出（"completed" / "interrupted"），便于排查 + 前端未来按需展示
                            # if cp_meta.get("status"):
                            #     msg.additional_kwargs["status"] = cp_meta["status"]
                        else:
                            self.logger.warning(f"checkpoint_index({checkpoint_index}) >= len(checkpoints)({len(checkpoints)})")
                            msg.additional_kwargs["checkpoint_id"] = None
                            msg.additional_kwargs["last_checkpoint_id"] = ""
                        messages_list.append(Message(
                            role=role,
                            content=await self._switch_chunk_to_str(msg.content),
                            files=None,
                            additional_kwargs=msg.additional_kwargs
                        ))
                        checkpoint_index += 1
                    elif msg.additional_kwargs.get("type") == AIMessageType.REASONING.value:
                        if msg.tool_calls:
                            additional_kwargs = dict(msg.additional_kwargs)
                            additional_kwargs["tool_calls"] = [
                                {"name": tc.get("name", ""), "args": tc.get("args", {})}
                                for tc in msg.tool_calls
                            ]
                            messages_list.append(Message(
                                role=role,
                                content=await self._switch_chunk_to_str(msg.content),
                                files=None,
                                additional_kwargs=additional_kwargs
                            ))
                        else:
                            messages_list.append(Message(
                                role=role,
                                content=await self._switch_chunk_to_str(msg.content),
                                files=None,
                                additional_kwargs=msg.additional_kwargs
                            ))
                    else:
                        continue

                elif isinstance(msg, ToolMessage):
                    role = MessageRole.AI
                    tool_resp = await self._switch_chunk_to_str(msg.content)
                    messages_list.append(Message(
                        role=role,
                        content=f"name: {msg.name}\ncontent:{tool_resp}",
                        files=None,
                        additional_kwargs={"type": AIMessageType.REASONING.value,"isTool": True, "tool_call_id": msg.tool_call_id} # 与调用工具的AIMessage进行区分
                    ))

        created_at = state.created_at if hasattr(state, "created_at") and state.created_at else datetime.now()
        updated_at = datetime.now()
        title = "新对话"

        if "messages" in state.values and state.values["messages"]:
            # 获取 updated_at
            for msg in reversed(state.values["messages"]):
                if isinstance(msg, HumanMessage):
                    updated_at = msg.additional_kwargs.get("updated_at") or datetime.now()
                    break
            # 获取 title
            if len(state.values["messages"]) > 0:
                last_msg = state.values["messages"][-1]
                if hasattr(last_msg, 'additional_kwargs') and last_msg.additional_kwargs:
                    title = last_msg.additional_kwargs.get("title", "新对话")

        conversations = Conversation(
            session_id=session_id,
            messages=messages_list,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            interrupted_info=interrupted_info if interrupted_info else None
        )

        return conversations

    async def get_conversation_list(self) -> List[ConversationSimple]:
        """
        获取所有会话列表

        :return: 按更新时间倒序的会话列表，自动过滤空会话
        """
        self.logger.info("获取会话列表")
        try:
            session_ids = await self.aget_conversation_ids
            conversation_list = []
            for sid in session_ids:
                conv = await self.get_conversation(sid)
                # 过滤空会话：无消息的会话不展示
                if conv and len(conv.messages) > 0:
                    conversation_list.append(conv)
            # 按更新时间倒序，最新对话在最前面
            conversation_list.sort(key=lambda x: x.updated_at, reverse=True)

            conversations = [
                ConversationSimple(
                    session_id=conv.session_id,
                    title=conv.title,
                    updated_at=conv.updated_at
                )
                for conv in conversation_list
            ]
            return conversations
        except HTTPException as e:
            self.logger.error(f"获取会话列表异常：{str(e)}")
            return []

    async def delete_conversation(self, session_id: str) -> bool:
        """
        langgraph新版本 删除会话 adelete_thread
        彻底删除Redis中的会话数据：包含检查点+历史状态+索引
        """
        try:
            # 清除中断状态，确保流式响应正常
            if await self._judge_is_interrupted(session_id):
                await self.redis_client.delete(f"interrupt:{session_id}")

            await self._wait_previous_memory_update(session_id)

            await self.state_saver.delete_thread(session_id)
            # langgraph新版本 删除会话 adelete_thread
            await self.checkpointer.adelete_thread(
                thread_id=session_id,
            )
            await self.chat_workflow.memory_manager.delete_memory(thread_id=session_id)

            await self._drop_memory_update_task(session_id)

            self.logger.info(f"会话删除成功(session_id:{session_id})")
            return True

        # 捕获异常
        except HTTPException as e:
            error_detail = f"删除会话失败(session_id:{session_id})：{str(e)}"
            self.logger.error(error_detail)
            return False

    async def update_conversation_title(self, session_id: str, new_title: str) -> bool:
        """ 修改会话标题，存入会话元数据"""
        try:
            config = {"configurable": {"thread_id": session_id}}
            state = await self.graph.aget_state(config=config)

            # 面对langgraph对更新state的限制所制作的*神秘代码*
            if msg := state.values["messages"][-1]:
                msg.additional_kwargs["title"] = new_title.strip()
                # 只有 AIMessage 才能直接重建，其他类型（如 ToolMessage）直接替换
                if isinstance(msg, AIMessage):
                    new_msg = AIMessage(
                        content=msg.content,
                        additional_kwargs=msg.additional_kwargs,
                        response_metadata=msg.response_metadata,
                        id=msg.id,
                        usage_metadata = getattr(msg, "usage_metadata", None)
                    )
                    state.values["messages"][-1] = new_msg
                # 其他类型消息已经修改了 additional_kwargs，无需重建
                # 调用aupdate_state：只传config和values
                await self.graph.aupdate_state(
                    config=config,
                    values=state.values,  # 把修改后的完整state值更新回去
                )
                # todo 回溯后无法自动更新对话标题
                self.logger.info(f"会话标题修改成功(session_id:{session_id})：{new_title}")
                return True
            else:
                self.logger.error(f"会话不存在(session_id:{session_id})")
                return False
        except HTTPException as e:
            self.logger.error(f"修改标题失败(session_id:{session_id}): {str(e)}")
            return False

    async def _delete_specific_checkpoint(self, session_id: str, checkpoint_id: str,
                                         checkpoint_ns: str = "__empty__") -> bool:
        """
        删除指定 thread_id 中的特定 checkpoint

        根据 Redis Desktop Manager 实际数据结构:
        1. checkpoint:{thread_id}:{checkpoint_ns}:{checkpoint_id} -> JSON (主checkpoint数据)
        2. checkpoint_latest:{thread_id} -> String (值为完整的checkpoint key路径)
        3. checkpoint_write:{thread_id}:{checkpoint_ns}:{checkpoint_id}:{task_id} -> JSON (pending writes)
        4. write_keys_zset:{thread_id}:{checkpoint_ns} -> ZSET (members为checkpoint_write完整key)

        Args:
            session_id: 会话线程ID
            checkpoint_id: 要删除的检查点ID
            checkpoint_ns: 检查点命名空间，默认为"__empty__"

        Returns:
            bool: 删除成功返回 True，失败返回 False
        """
        if not session_id or not checkpoint_id:
            self.logger.warning("thread_id 或 checkpoint_id 为空，无法删除")
            return False

        try:
            deleted_count = 0

            # 1. 删除主 checkpoint 数据 (JSON类型)
            # Key格式: checkpoint:{session_id}:{checkpoint_ns}:{checkpoint_id}
            checkpoint_key = f"checkpoint:{session_id}:{checkpoint_ns}:{checkpoint_id}"
            if await self.redis_client.exists(checkpoint_key):
                await self.redis_client.delete(checkpoint_key)
                deleted_count += 1

            # 2. 检查并更新 checkpoint_latest (String类型)
            # Key格式: checkpoint_latest:{session_id}
            # 值格式: checkpoint:{session_id}:{checkpoint_ns}:{checkpoint_id}
            checkpoint_latest_key = f"checkpoint_latest:{session_id}"
            if await self.redis_client.exists(checkpoint_latest_key):
                current_latest = await self.redis_client.get(checkpoint_latest_key)
                if current_latest:
                    latest_str = current_latest.decode('utf-8') if isinstance(current_latest, bytes) else current_latest
                    # 如果当前最新的checkpoint正是要删除的那个，需要清理
                    if checkpoint_id in latest_str:
                        await self.redis_client.delete(checkpoint_latest_key)
                        deleted_count += 1

            # 3. 删除所有相关的 checkpoint_write 数据 (JSON类型)
            # Key格式: checkpoint_write:{session_id}:{checkpoint_ns}:{checkpoint_id}:{task_id}
            write_pattern = f"checkpoint_write:{session_id}:{checkpoint_ns}:{checkpoint_id}:*"
            write_keys = []
            async for key in self.redis_client.scan_iter(match=write_pattern):
                write_keys.append(key)

            if write_keys:
                deleted = await self.redis_client.delete(*write_keys)
                deleted_count += deleted

            # 4. 从 write_keys_zset 索引中清理相关的 write keys (ZSet类型)
            # Key格式: write_keys_zset:{session_id}:{checkpoint_ns}
            # Members: checkpoint_write:{session_id}:{checkpoint_ns}:{checkpoint_id}:{task_id}
            write_keys_zset_key = f"write_keys_zset:{session_id}:{checkpoint_ns}"
            if await self.redis_client.exists(write_keys_zset_key):
                # 获取所有 members
                all_members = await self.redis_client.zrange(write_keys_zset_key, 0, -1)
                members_to_remove = []

                for member in all_members:
                    member_str = member.decode('utf-8') if isinstance(member, bytes) else member
                    # 检查 member 是否包含要删除的 checkpoint_id
                    # member 格式: checkpoint_write:{session_id}:{checkpoint_ns}:{checkpoint_id}:{task_id}
                    if f":{checkpoint_id}:" in member_str:
                        members_to_remove.append(member)

                if members_to_remove:
                    removed = await self.redis_client.zrem(write_keys_zset_key, *members_to_remove)
                    deleted_count += removed

            return True

        except Exception as e:
            self.logger.error(
                f"删除特定 checkpoint 失败 (session_id='{session_id}', checkpoint_id='{checkpoint_id}'): {str(e)}"
            )
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")
            return False

    async def backtrack_state(self, session_id :str, checkpoint_id :str) -> bool:
        """
        返回到当前对话的特定的检查点状态
        :param
            session_id: 会话id
            checkpoint_id: 检查点id
        :return
            已回溯到某个检查点状态的对话信息
        """
        backtrack_config = {"configurable": {"thread_id": session_id, "checkpoint_id":checkpoint_id}}

        # 清除中断状态，确保流式响应正常
        if await self._judge_is_interrupted(session_id):
            await self.redis_client.delete(f"interrupt:{session_id}")

        try:
            await self._wait_previous_memory_update(session_id)

            checkpoints = await self.state_saver.get_checkpoints(session_id)

            if not checkpoints:
                self.logger.error(f"会话不存在(session_id:{session_id})")
                return False

            target_index = -1
            checkpoints.reverse()
            # 一般都是回溯到上一个会话，就不用优化算法了
            for i, cp in enumerate(checkpoints):
                if cp["checkpoint_id"] == checkpoint_id:
                    target_index = i
                    break

            # 删除比目标更新的 checkpoints（这些是旧状态，比 backtrack 目标更晚）
            checkpoints_to_del = checkpoints[:target_index] if target_index > 0 else []

            # 获取回溯后的状态
            backtrack_state = await self.graph.aget_state(config=backtrack_config)

            # 更新想要的回溯检查点状态到当前会话状态
            cur_state = await self.graph.aupdate_state(config=backtrack_config, values=backtrack_state.values)
            new_checkpoint = cur_state["configurable"]["checkpoint_id"]

            # 删除比目标更新的旧 checkpoints
            for cp in checkpoints_to_del:
                cp_id_to_del = cp["checkpoint_id"]
                if cp_id_to_del:
                    await self.state_saver.delete_checkpoint(thread_id=session_id, checkpoint_id=cp_id_to_del)
                    await self._delete_specific_checkpoint(session_id, cp_id_to_del)

            await self.chat_workflow.memory_manager.backtrack_memory(thread_id=session_id, checkpoint_id=checkpoint_id, new_checkpoint_id=new_checkpoint)

            # 等待 Redis 状态完全落地，避免前端立即发起的流式请求读到旧数据
            await asyncio.sleep(0.5)

            self.logger.info(f"会话回溯成功(session_id:{session_id}, checkpoint_id:{checkpoint_id})")

            return True

        except Exception as e:
            self.logger.error(f"会话回溯失败(session_id:{session_id}, checkpoint_id:{checkpoint_id}): {str(e)}")
            return False

    async def get_imp_usr_ipt(self, input_text:str):
        """
        优化用户需求函数，使后续ai更好理解用户需求
        返回两个参数: 优化后的输入,状态码
        """
        improved_text = input_text
        try:
            resp = await self.chat_workflow.llm_imp_ipt.ainvoke(input_text)
            improved_text = resp.content

        except Exception as e:
            self.logger.error(f"优化用户输入失败: {str(e)},采用回原输出")
        finally:
            return improved_text

    @staticmethod
    async def get_file_config():
        return {
            "maxFileSize": FILE_MAX_LENGTH,
            "imageTypes": {
                "suffixes": list(FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_SUFFIX"]),
                "mimeTypes": list(FILE_ALLOWED_TYPES["IMAGE"]["IMAGE_MIME"])
            },
            "textTypes": {
                "suffixes": list(FILE_ALLOWED_TYPES["TEXT"]["TEXT_SUFFIX"]),
                "mimeTypes": list(FILE_ALLOWED_TYPES["TEXT"]["TEXT_MIME"])
            },
            "documentTypes": {
                "suffixes": list(FILE_ALLOWED_TYPES["DOCUMENT"]["DOCUMENT_SUFFIX"]),
                "mimeTypes": list(FILE_ALLOWED_TYPES["DOCUMENT"]["DOCUMENT_MIME"])
            }
        }

    async def interrupt_stream(self, session_id, interrupt_reason: str = "user_initiated_interrupt"):
        """
        中断当前session_id下的对话
        """
        self.logger.info(f"中断会话: {session_id}")
        try:
            await self.redis_client.hset(
                f"interrupt:{session_id}",
                mapping={
                    "reason": interrupt_reason,
                    "checkpoint_id": "",
                    "timestamp": str(datetime.now()),
                }
            )

            self.logger.info(f"会话中断成功(session_id:{session_id})")
            return True
        except Exception as e:
            self.logger.error(f"会话中断失败(session_id:{session_id}): {str(e)}")
            return False

    async def invoke_interrupted_stream(self, session_id, message: str = "CONTINUE"):
        """
        重新进行中断了的对话，断点续接
        """
        self.logger.info(f"续接会话: {session_id}")
        try:
            key = f"interrupt:{session_id}"

            if message == "CONTINUE" or not message or message.strip() == "":
                reinvoke_message = [SystemMessage(content="CONTINUE")]
            else:
                key_value = await self._get_interrupted_info(session_id)
                reinvoke_message = [SystemMessage(content=f"中断原因:{key_value['reason']}\n用户进行中断续接,要求为: {message}")]

            # 续接流的指标聚合：与 message_stream 同构
            start_mono = time.monotonic()
            token_usage = self._new_workflow_token_usage()
            elapsed_ms = self._elapsed_ms_since(start_mono)

            yield json.dumps(
                {"type": "init", "session_id": session_id, "elapsed_ms": elapsed_ms, "token_usage": token_usage},
                ensure_ascii=False,
                default=str
            ) + "\n\n"

            memory_status = self._get_memory_update_status(session_id)
            if memory_status == "pending":
                yield json.dumps(
                    {"type": "memory_wait_start", "session_id": session_id, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                    ensure_ascii=False,
                    default=str
                ) + "\n\n"

                memory_status = await self._wait_previous_memory_update(session_id)

                yield json.dumps(
                    {"type": "memory_wait_done", "session_id": session_id, "status": memory_status or "done", "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                    ensure_ascii=False,
                    default=str
                ) + "\n\n"
            # 清除中断时留下的状态
            await self.redis_client.delete(key)
            await self._delete_last_round_checkpoint(session_id)

            # context 续接的时候不是追加逻辑，是覆盖逻辑
            config = {"configurable": {"thread_id": session_id}}
            state = await self.graph.aget_state(config=config)
            pre_context = state.values.get("context",[]) or []
            merged_context = list(pre_context) + list(reinvoke_message)

            async for chunk in self.chat_workflow.astream(
                Command(update={
                    "messages": reinvoke_message,
                    "context": merged_context,
                },
                    resume=True
                ),
                config=config,
            ):
                if chunk['event'] == 'on_chat_model_stream':
                    # 最终返回的chunk
                    if chunk['metadata']['langgraph_node'] and chunk['metadata']['langgraph_node'] == 'final_node':
                        content = await self._switch_chunk_to_str(chunk['data']['chunk'].content)
                        yield json.dumps(
                            {"type": "content", "content": content, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
                    elif chunk['metadata']['langgraph_node'] and chunk['metadata']['langgraph_node'] == 'agent_node':
                        content = await self._switch_chunk_to_str(chunk['data']['chunk'].content)
                        yield json.dumps(
                            {"type": "reasoning", "content": content, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
                    else:
                        continue
                elif chunk['event'] == 'on_chat_model_end':
                    # 续接流也按 4 个主节点聚合
                    self._accumulate_workflow_tokens(
                        token_usage,
                        (chunk.get('metadata') or {}).get('langgraph_node'),
                        (chunk.get('data') or {}).get('output'),
                    )
                elif chunk['event'] == 'on_tool_start':
                    tool_call_args = chunk['data'].get('input', {})
                    tool_call_name = chunk['name']
                    yield json.dumps(
                        {"type": "tool_call_name", "id": chunk["run_id"], "content": {'args': tool_call_args, 'name': tool_call_name}, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                        ensure_ascii=False,
                        default=str
                    ) + "\n\n"
                elif chunk['event'] == 'on_tool_end':
                    output_content = chunk['data']['output'].content
                    if output_content:
                        content = await self._switch_chunk_to_str(output_content)
                        yield json.dumps(
                            {"type": "tool_call_result", "id": chunk["run_id"], "content": content, "elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                            ensure_ascii=False,
                            default=str
                        ) + "\n\n"
        except Exception as e:
            error_detail = f"{str(e)}\n{traceback.format_exc()}"
            self.logger.error(f"流式响应异常(session_id:{session_id}): {error_detail}")
            # 异常返回错误信息 + 双换行符。yield 后立即 return，
            yield json.dumps(
                {"type": "error", "error": str(e), "elapsed_ms": self._elapsed_ms_since(start_mono) if 'start_mono' in locals() else 0, "token_usage": token_usage if 'token_usage' in locals() else self._new_workflow_token_usage()},
                ensure_ascii=False,
                default=str
            ) + "\n\n"

            # thinking_chain 收尾：flush per-session 临时文件到主文件（best-effort，失败不抛）
            flush_pending_thinking_for_session(session_id)
            return

        if await self._judge_is_interrupted(session_id):
            key_value = await self._get_interrupted_info(session_id)
            reason = key_value.get("reason", "user_initiated_interrupt")

            self.logger.info(f"会话{session_id}被中断: {reason}")

            checkpoint_id = await self._save_round_checkpoint(
                session_id,
                metrics={"elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
                status="interrupted",
            )

            # 补充checkpoint_id字段进去
            await self.redis_client.hset(
                f"interrupt:{session_id}",
                mapping={
                    "reason": key_value.get("reason", "user_initiated_interrupt"),
                    "checkpoint_id": checkpoint_id,
                    "timestamp": key_value.get("timestamp", "")
                })

            yield json.dumps(
                {
                    "type": "interrupt",
                    "session_id": session_id,
                    "checkpoint_id": checkpoint_id,
                    "memory_status": self._get_memory_update_status(session_id),
                    "reason": reason,
                    "elapsed_ms": self._elapsed_ms_since(start_mono),
                    "token_usage": token_usage,
                },
                ensure_ascii=False,
                default=str
            ) + "\n\n"

            # thinking_chain 收尾：中断路径也 flush（保留中断前的思考过程）
            flush_pending_thinking_for_session(session_id)
            return

        checkpoint_id = await self._save_round_checkpoint(
            session_id,
            metrics={"elapsed_ms": self._elapsed_ms_since(start_mono), "token_usage": token_usage},
        )

        self.logger.info(f"会话 {session_id} 续接对话完成 (checkpoint: {checkpoint_id}) elapsed_ms={self._elapsed_ms_since(start_mono)} token_total={token_usage['total']}")

        # 返回最终完整结果
        yield json.dumps({
            "type": "done",
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "memory_status": self._get_memory_update_status(session_id),
            "interrupted_before": True,
            "elapsed_ms": self._elapsed_ms_since(start_mono),
            "token_usage": token_usage,
        }) + "\n\n"

        # thinking_chain 收尾：续接完成路径 flush
        flush_pending_thinking_for_session(session_id)
