import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.ChatWorkflow.config.models import MemoryUpdateFormat


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
            memory_dir = os.path.join(
                Path.cwd(),
                ".chatme",
                "memory"
            )
        self._memory_dir = memory_dir

        # 确保目录存在
        Path(self._memory_dir).mkdir(parents=True, exist_ok=True)

    def _get_memory_file_path(self, thread_id: str) -> str:
        """
        获取指定 thread_id 对应的记忆文件路径

        Args:
            thread_id: 对话线程 ID

        Returns:
            记忆文件完整路径
        """
        # 清理 thread_id 中的非法字符
        safe_thread_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in thread_id)
        return os.path.join(self._memory_dir, f"{safe_thread_id}.md")

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
            return self._get_empty_memory_template()

        try:
            with open(memory_file_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip():
                    return self._get_empty_memory_template()
                return content.strip()
        except Exception as e:
            self.logger.error(f"读取记忆文件失败: {e}")
            return self._get_empty_memory_template()

    def write_memory(self, thread_id: str, content: str) -> bool:
        """
        写入指定 thread_id 的记忆文件

        Args:
            thread_id: 对话线程 ID
            content: 记忆内容

        Returns:
            写入是否成功
        """
        memory_file_path = self._get_memory_file_path(thread_id)
        try:
            with open(memory_file_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.logger.debug(f"记忆文件已更新: {memory_file_path}")
            return True
        except Exception as e:
            self.logger.error(f"写入记忆文件失败: {e}")
            return False

    async def update_memory(
        self,
        thread_id: str,
        memory_data: MemoryUpdateFormat
    ) -> bool:
        """
        根据新对话更新指定 thread_id 的记忆

        Args:
            thread_id: 对话线程 ID
            memory_data: 记忆更新数据

        Returns:
            更新是否成功
        """
        existing_memory = self.read_memory(thread_id)

        # 获取当前时间
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 构建 prompt
        prompt = self._memory_prompt.format(
            existing_memory=existing_memory,
            user_message=memory_data.user_message,
            ai_response=memory_data.ai_response,
            tool_calls_str=self._format_tool_calls(memory_data.tool_calls),
            tool_results_str=self._format_tool_results(memory_data.tool_results),
            timestamp=timestamp
        )

        try:
            # 调用 LLM 生成更新后的记忆
            response = await self.llm.ainvoke(prompt)
            new_memory = response.content.strip()

            # 检查是否有实际更新
            if "无更新" in new_memory:
                self.logger.debug("无重要更新，跳过记忆写入")
                return True

            # 写入新记忆
            return self.write_memory(thread_id, new_memory)

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

    def clear_memory(self, thread_id: str) -> bool:
        """
        清空指定 thread_id 的记忆

        Args:
            thread_id: 对话线程 ID

        Returns:
            清空是否成功
        """
        return self.write_memory(thread_id, self._get_empty_memory_template())

    def list_threads(self) -> List[str]:
        """
        列出所有有记忆文件的 thread_id

        Returns:
            thread_id 列表
        """
        if not os.path.exists(self._memory_dir):
            return []
        try:
            files = os.listdir(self._memory_dir)
            return [f.replace(".md", "") for f in files if f.endswith(".md")]
        except Exception as e:
            self.logger.error(f"列出记忆线程失败: {e}")
            return []

    def delete_memory(self, thread_id: str) -> bool:
        """
        删除指定 thread_id 的记忆文件

        Args:
            thread_id: 对话线程 ID

        Returns:
            删除是否成功
        """
        memory_file_path = self._get_memory_file_path(thread_id)
        try:
            if os.path.exists(memory_file_path):
                os.remove(memory_file_path)
                self.logger.debug(f"删除记忆文件: {memory_file_path}")
            return True
        except Exception as e:
            self.logger.error(f"删除记忆文件失败: {e}")
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

    def _get_empty_memory_template(self) -> str:
        """获取空记忆模板"""
        return """# 对话记忆 (thread_id: 暂无)

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
- .chatme/cached/
"""
