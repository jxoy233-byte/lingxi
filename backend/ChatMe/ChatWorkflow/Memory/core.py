import os
import json
import re
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from langchain_core.messages import SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.ChatWorkflow.config.models import MemoryUpdateFormat
from ChatMe.ChatWorkflow.helpers import filter_thinking_content
from ChatMe.paths import get_chatme_dir

# ⚠️ _filter_thinking_content 已合并到 ChatMe.ChatWorkflow.helpers.filter_thinking_content
# （CLAUDE.md 第 7.1 条要求两处 filter 保持一致）。Memory 这里只保留 async 包装 + tool_calls
# 字段透传（helpers 的版本会从 getattr 取 tool_calls，但 M3 在 memory update LLM 响应里通常不
# 带 tool_calls，所以这里显式传 None 即可，行为不变）。
async def _filter_thinking_content(ai_response: AIMessage) -> AIMessage:
    """过滤 AI 回复中的思考标签 + M3 伪 tool_call 块。
    委托 helpers.filter_thinking_content，详见该函数的 docstring 与 _FILTER_PATTERNS 注释。
    """
    return filter_thinking_content(ai_response)

class MemoryManager:
    """
    记忆管理器：统一管理所有对话记忆，按 thread_id 隔离存储
    """

    def __init__(
        self,
        llm_config: Dict[str, Any],
        memory_prompt: str,
        memory_dir: str = None
    ):
        """
        初始化记忆管理器

        Args:
            llm_config: LLM 配置字典
            memory_prompt: 记忆更新 prompt 模板字符串，包含占位符：{existing_memory}, {user_message},
                          {ai_response}, {tool_calls_str}, {tool_results_str}, {timestamp}
            memory_dir: 记忆文件存储目录，默认使用 .chatme/memory/
        """
        self.logger = get_logger(__class__.__name__)

        # LLM 配置
        self.llm = ChatOpenAI(**llm_config)

        # 记忆更新 prompt 模板
        self._memory_prompt = memory_prompt

        # 记忆文件存储目录
        if memory_dir is None:
            # 统一走 ChatMe.paths.get_chatme_dir()（local .chatme 优先），
            # 不再直接拼接 Path.cwd() + ".chatme" + "memory"。
            memory_dir = str(get_chatme_dir() / "memory")
        self._memory_dir = memory_dir
        self._thread_locks: Dict[str, asyncio.Lock] = {}

        # 确保目录存在
        Path(self._memory_dir).mkdir(parents=True, exist_ok=True)

    def _get_thread_lock(self, thread_id: str) -> asyncio.Lock:
        lock = self._thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_locks[thread_id] = lock
        return lock

    @staticmethod
    def _atomic_write_text(file_path: str, content: str) -> None:
        tmp_path = f"{file_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)

    def _get_memory_path_with_thread(self, thread_id: str) -> Path:
        """
        获取指定 thread_id 对应的记忆文件路径

        Args:
            thread_id: 对话线程 ID

        Returns:
            特定thread_id的记忆文件存放路径
        """
        # 清理 thread_id 中的非法字符
        safe_thread_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in thread_id)
        path_with_thread = Path(self._memory_dir) / f"{safe_thread_id}"
        os.makedirs(path_with_thread, exist_ok=True)
        return path_with_thread

    def _get_memory_file_path(self, thread_id: str) -> str:
        """
        获取指定 thread_id 对应的记忆文件路径

        Args:
            thread_id: 对话线程 ID

        Returns:
            特定thread_id的记忆文件核心路径
        """
        path_with_thread = self._get_memory_path_with_thread(thread_id)
        return os.path.join(path_with_thread, "current.md")


    def read_memory(self, thread_id: str) -> str:
        """
        读取指定 thread_id 的记忆文件

        Args:
            thread_id: 对话线程 ID

        Returns:
            记忆文件内容
        """
        memory_file_path = self._get_memory_file_path(thread_id)
        if not os.path.exists(memory_file_path):
            return self._get_empty_memory_template(thread_id)

        try:
            with open(memory_file_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip():
                    return self._get_empty_memory_template(thread_id)
                return content.strip()
        except Exception as e:
            self.logger.error(f"读取记忆文件失败: {e}")
            return self._get_empty_memory_template(thread_id)

    def write_memory(self, thread_id: str, checkpoint_id: str, content: str, timestamp: str) -> bool:
        """
        写入指定 thread_id 的记忆核心文件
        以及检查点备份文件

        Args:
            thread_id: 对话线程 ID
            checkpoint_id: 检查点 ID
            content: 记忆内容

        Returns:
            写入是否成功
        """
        path_with_thread = self._get_memory_path_with_thread(thread_id)
        memory_file_with_checkpoint = os.path.join(
            path_with_thread,
            f"{timestamp}_{checkpoint_id}.md"
        )

        memory_file_path = self._get_memory_file_path(thread_id)
        try:
            self._atomic_write_text(memory_file_with_checkpoint, content)
            self._atomic_write_text(memory_file_path, content)
            self.logger.info(f"记忆文件已更新: {memory_file_path}")
            return True
        except Exception as e:
            self.logger.error(f"写入记忆文件失败: {e}")
            return False

    async def update_memory(
        self,
        thread_id: str,
        checkpoint_id: str,
        memory_data: MemoryUpdateFormat
    ) -> bool:
        """
        根据新对话更新指定 thread_id 的记忆

        Args:
            thread_id: 对话线程 ID
            checkpoint_id: 检查点 ID
            memory_data: 记忆更新数据

        Returns:
            更新是否成功
        """
        async with self._get_thread_lock(thread_id):
            existing_memory = self.read_memory(thread_id)

            # 获取当前时间
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 构建 prompt
            prompt = self._memory_prompt.format(
                existing_memory=existing_memory,
                user_message=memory_data.user_message,
                ai_response=memory_data.ai_response,
                tool_calls_str=self._format_tool_calls(memory_data.tool_calls),
                tool_results_str=self._format_tool_results(memory_data.tool_results),
                timestamp=timestamp,
                session_id=thread_id
            )

            try:
                # 调用 LLM 生成更新后的记忆
                response = await self.llm.ainvoke(prompt)

                response = await _filter_thinking_content(response)

                new_memory = response.content.strip()

                # 检查是否有实际更新
                if "无更新" in new_memory:
                    self.logger.warning("无重要更新，跳过记忆写入")
                    return True

                # 写入新记忆
                return self.write_memory(thread_id, checkpoint_id, new_memory, timestamp)

            except Exception as e:
                self.logger.error(f"更新记忆失败: {e}")
                return False

    def get_relevant_memory(self, thread_id: str, query: str = None) -> SystemMessage:
        """
        获取指定 thread_id 的记忆内容，包装为 SystemMessage

        Args:
            thread_id: 对话线程 ID
            query: 可选的查询关键词（目前直接返回全部）

        Returns:
            包装为 SystemMessage 的记忆内容
        """
        memory_content = self.read_memory(thread_id)
        return SystemMessage(content=f"【历史记忆】\n{memory_content}")

    # ====================================================================
    # 分层上下文（current.md + facts.md + preference.md + global/*）
    # ====================================================================

    def _thread_memory_file(self, thread_id: str, category: str) -> str:
        """facts.md / preference.md 路径。"""
        return os.path.join(self._memory_dir, thread_id, f"{category}.md")

    def _global_memory_file(self, category: str) -> str:
        """global/facts.md / global/preference.md 路径。"""
        return os.path.join(self._memory_dir, "global", f"{category}.md")

    def _read_optional(self, file_path: str) -> str:
        """读取可选文件 —— 不存在或读失败返回 ''。不会抛异常。"""
        if not os.path.exists(file_path):
            return ""
        try:
            return open(file_path, "r", encoding="utf-8").read().strip()
        except Exception as e:
            self.logger.warning(f"读取 {file_path} 失败: {e}")
            return ""

    def read_layered_context(self, thread_id: str) -> SystemMessage:
        """合并 current.md + thread facts/preference + global facts/preference
        为单一 SystemMessage，由 context_assembly_node 注入到每轮开头。

        5 段结构（每段独立 heading，缺失显示「（空）」）：

            【本会话记忆】     current.md  —— LLM 维护的叙事性总结
            【本会话事实】     facts.md    —— remember category="facts" scope="thread"
            【本会话偏好】     preference.md —— remember category="preference" scope="thread"
            【全局事实】      global/facts.md —— remember scope="global" category="facts"
            【全局偏好】      global/preference.md —— remember scope="global" category="preference"

        写入路径见 skills/memory/__init__.py 的 _memory_file_path。
        """
        current = self.read_memory(thread_id)
        thread_facts = self._read_optional(self._thread_memory_file(thread_id, "facts"))
        thread_pref = self._read_optional(self._thread_memory_file(thread_id, "preference"))
        global_facts = self._read_optional(self._global_memory_file("facts"))
        global_pref = self._read_optional(self._global_memory_file("preference"))

        sections = [
            f"【本会话记忆】\n{current}",
            f"【本会话事实】\n{thread_facts or '（空）'}",
            f"【本会话偏好】\n{thread_pref or '（空）'}",
            f"【全局事实】\n{global_facts or '（空）'}",
            f"【全局偏好】\n{global_pref or '（空）'}",
        ]

        return SystemMessage(content="\n\n".join(sections))

    def clear_memory(self, thread_id: str) -> bool:
        """
        清空指定 thread_id 的记忆

        Args:
            thread_id: 对话线程 ID

        Returns:
            清空是否成功
        """

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self.write_memory(
            thread_id,
            "clear",
            self._get_empty_memory_template(thread_id),
            timestamp,
        )

    def list_threads(self) -> List[str]:
        """
        列出所有有记忆文件的 thread_id

        Returns:
            thread_id 列表
        """
        if not os.path.exists(self._memory_dir):
            return []
        try:
            entries = os.listdir(self._memory_dir)
            # 返回目录名（即 thread_id），而非 .md 文件
            return [f for f in entries if os.path.isdir(os.path.join(self._memory_dir, f))]
        except Exception as e:
            self.logger.error(f"列出记忆线程失败: {e}")
            return []

    async def delete_memory(self, thread_id: str) -> bool:
        """
        删除指定 thread_id 的记忆文件（包括该目录下的所有文件）

        Args:
            thread_id: 对话线程 ID

        Returns:
            删除是否成功
        """
        async with self._get_thread_lock(thread_id):
            try:
                path_with_thread = self._get_memory_path_with_thread(thread_id)

                if not os.path.exists(path_with_thread):
                    self.logger.warning(f"记忆目录不存在: {path_with_thread}")
                    return True

                # 删除目录下的所有文件
                for filename in os.listdir(path_with_thread):
                    file_path = os.path.join(path_with_thread, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            self.logger.info(f"删除记忆文件: {file_path}")
                    except Exception as e:
                        self.logger.error(f"删除文件失败 {file_path}: {e}")

                os.rmdir(path_with_thread)

                return True
            except Exception as e:
                self.logger.error(f"删除记忆目录失败: {e}")
                return False

    async def backtrack_memory(self, thread_id: str, checkpoint_id: str) -> bool:
        """
        回溯指定 thread_id 的记忆到指定检查点

        逻辑：
        1. 找到对应 checkpoint_id 的记忆文件
        2. 删除该时间点之后的所有记忆文件（时间戳更大的文件）
        3. 将该 checkpoint 的内容恢复到 current.md

        Args:
            thread_id: 对话线程 ID
            checkpoint_id: 回溯目标的检查点 ID

        Returns:
            回溯是否成功
        """
        async with self._get_thread_lock(thread_id):
            try:
                path_with_thread = self._get_memory_path_with_thread(thread_id)

                if not os.path.exists(path_with_thread):
                    self.logger.warning(f"记忆目录不存在: {path_with_thread}")
                    return False

                # 获取目录下所有 .md 文件
                all_files = [f for f in os.listdir(path_with_thread) if f.endswith('.md')]

                # 查找目标 checkpoint 文件
                target_file = None
                target_timestamp = None

                for filename in all_files:
                    # 跳过 current.md
                    if filename == 'current.md':
                        continue

                    # 文件名格式：{timestamp}_{checkpoint_id}.md
                    # timestamp 格式为 YYYY-MM-DD HH:MM:SS，左边是 timestamp，右边是 checkpoint_id
                    if '_' in filename and filename.endswith('.md'):
                        parts = filename.rsplit('_', 1)  # 从右边分割最后一个下划线
                        if len(parts) == 2:
                            checkpoint_part = parts[1][:-3] # 去掉 ".md"
                            timestamp_part = parts[0]

                            if checkpoint_part == checkpoint_id:
                                target_file = filename
                                target_timestamp = timestamp_part
                                break

                if not target_file:
                    self.logger.warning(f"未找到 checkpoint 文件: {checkpoint_id}")
                    return False

                # 读取目标 checkpoint 的内容
                target_file_path = os.path.join(path_with_thread, target_file)
                with open(target_file_path, 'r', encoding='utf-8') as f:
                    target_content = f.read()

                self.logger.info(f"找到目标 checkpoint 文件: {target_file}, 时间戳: {target_timestamp}")

                # 找出所有时间戳大于目标时间戳的文件并删除
                files_to_delete = []
                for filename in all_files:
                    if filename == 'current.md' or filename == target_file:
                        continue

                    # 解析文件名中的时间戳
                    # 文件名格式：{timestamp}_{checkpoint_id}.md
                    if '_' in filename and filename.endswith('.md'):
                        parts = filename.split('_', 1)  # 从左边分割第一个下划线
                        if len(parts) == 2:
                            file_timestamp = parts[0]  # 时间戳在左边

                            # 比较时间戳（字符串比较即可，因为格式是 YYYY-MM-DD HH:MM:SS）
                            if file_timestamp > target_timestamp:
                                files_to_delete.append(filename)

                # 删除时间戳更大的文件
                for filename in files_to_delete:
                    file_path = os.path.join(path_with_thread, filename)
                    try:
                        os.remove(file_path)
                        self.logger.info(f"删除过期记忆文件: {filename}")
                    except Exception as e:
                        self.logger.error(f"删除文件失败 {filename}: {e}")

                # 不再重命名 target_file —— 让文件名里的 cid 保持最初触发写入的 round cid，
                # 后续多次回溯到同一 cid 都能命中这个文件（之前用 aupdate_state 会产生 artifact cid_E，
                # 再回溯到原 cid_A 时文件已被改名成 cid_E，导致「未找到 checkpoint 文件」bug）。
                # 同时保留 target_file 的 cid 语义一致：filename cid ↔ state_saver user_saved cid。

                # 将目标 checkpoint 内容写入 current.md
                current_file_path = self._get_memory_file_path(thread_id)
                self._atomic_write_text(current_file_path, target_content)

                self.logger.info(f"记忆回溯成功: thread_id={thread_id}, checkpoint_id={checkpoint_id}, "
                                 f"删除了 {len(files_to_delete)} 个过期文件")
                return True

            except Exception as e:
                self.logger.error(f"记忆回溯失败: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                return False

    def _format_tool_calls(self, tool_calls: Optional[List[Dict]]) -> str:
        """格式化工具调用列表"""
        if not tool_calls:
            return "无"
        return "\n".join([
            f"- {tc.get('name', 'unknown')}: {tc.get('args', {})}"
            for tc in tool_calls
        ])

    def _format_tool_results(self, tool_results: Optional[List[str]]) -> str:
        """格式化工具结果列表"""
        if not tool_results:
            return "无"
        return "\n".join([
            f"- {result[:200]}..." if len(result) > 200 else f"- {result}"
            for result in tool_results
        ])

    def _get_empty_memory_template(self, thread_id: str = "") -> str:
        """获取空记忆模板"""
        return f"""# 对话记忆
> 最后更新：暂无

## 核心摘要
暂无

## 关键事实
暂无

## 待办事项
无

## 技术要点
暂无

## 缓存文件目录
- cached/{thread_id}
"""


    async def delete_latest_memory(self, thread_id: str) -> bool:
        """
        删除指定 thread_id 下最新的记忆备份文件（但不删除 current.md）
        """
        async with self._get_thread_lock(thread_id):
            try:
                path_with_thread = self._get_memory_path_with_thread(thread_id)

                if not os.path.exists(path_with_thread):
                    self.logger.warning(f"记忆目录不存在: {path_with_thread}")
                    return False

                all_files = [f for f in os.listdir(path_with_thread) if f.endswith('.md') and f != 'current.md']

                # 收集备份文件及其时间戳
                backup_files = []
                for filename in all_files:
                    if '_' in filename:
                        parts = filename.split('_', 1)  # 格式：{timestamp}_{checkpoint_id}.md
                        if len(parts) == 2:
                            try:
                                timestamp = datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
                                backup_files.append({"filename": filename, "timestamp": timestamp})
                            except ValueError:
                                continue

                if not backup_files:
                    return False

                # 按时间戳降序，删最新的
                backup_files.sort(key=lambda x: x["timestamp"], reverse=True)
                latest = backup_files[0]
                os.remove(os.path.join(path_with_thread, latest["filename"]))
                self.logger.info(f"删除最新记忆备份: {latest['filename']}")
                return True

            except Exception as e:
                self.logger.error(f"删除最新记忆失败: {e}")
                return False
