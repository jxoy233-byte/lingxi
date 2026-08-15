"""
Memory 技能 —— 写入精确事实 / 用户偏好到会话或全局记忆文件

文件布局（与 ChatWorkflow/Memory/core.py 的 _memory_dir 同根）：

    .chatme/memory/
      {thread_id}/
        current.md        # LLM 维护的叙事性总结（ChatService 维护）
        facts.md          # 精确事实（数值 / 路径 / 业务规则）—— 本技能维护
        preference.md     # 用户偏好（语言 / 风格 / 习惯）—— 本技能维护
        {ts}_{cid}.md     # current.md 历史备份
      global/
        facts.md
        preference.md

读写约定：
- 写入：remember(key, value, thread_id, category, scope) — 本文件实现
- 读取：
  - 自动注入：context_assembly_node 调 read_layered_context(thread_id) 把
    current.md + facts.md + preference.md 合并成 SystemMessage 注入到每轮开头
  - 主动读取：recall(thread_id, category, scope)，或 cmd("cat <path>")

写入约束 —— remember 必须 `code(..., local=True)` 调用。.chatme/memory/
在沙盒里以 ro 挂到 /memory（只读），写入必须走主进程。
"""
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal


_THREAD_MEMORY_DIR = Path.cwd() / ".chatme" / "memory"
_GLOBAL_MEMORY_DIR = _THREAD_MEMORY_DIR / "global"


# Per-file lock：同文件并发 read-modify-write 串行化，防止丢失更新。
# 不同文件之间互不阻塞（thread facts / preference + global facts / preference ≤ 4 个文件）。
# 进程级 dict + guard lock 避免 map 自身的竞争。
_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _get_file_lock(file_path: Path) -> threading.Lock:
    """Per-file lock：lazily create one lock per file_path."""
    key = str(file_path)
    with _file_locks_guard:
        lock = _file_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _file_locks[key] = lock
        return lock


def _memory_file_path(scope: str, thread_id: str, category: str) -> Path:
    if scope == "global":
        return _GLOBAL_MEMORY_DIR / f"{category}.md"
    return _THREAD_MEMORY_DIR / thread_id / f"{category}.md"


def _atomic_write_text(file_path: Path, content: str) -> None:
    """写 tmp + fsync + os.replace —— 复刻 MemoryManager 同款。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, file_path)


def _read_entries(content: str) -> list[tuple[str, str]]:
    """解析条目 → [(key, value), ...] 按文件顺序。

    格式约定（每条目）：

        - key: single-line value            (inline)

        - key:
          multi-line
          value                             (block, 缩进 2 空格)

    条目之间空行分隔。同名 key 取最后一次出现的值（去重）。
    """
    entries: list[tuple[str, str]] = []
    current_key: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_lines
        if current_key is not None:
            entries.append((current_key, "\n".join(current_lines).strip()))
            current_key = None
            current_lines = []

    for raw in content.splitlines():
        if raw.startswith("- ") and not raw.startswith("-  "):
            flush()
            m = re.match(r"^- (.+?): (.*)$", raw)
            if m:
                current_key = m.group(1).strip()
                first = m.group(2)
                current_lines = [first] if first else []
            else:
                current_key = None
                current_lines = []
        elif current_key is not None and raw.startswith("  "):
            current_lines.append(raw[2:])
        elif not raw.strip():
            flush()
        else:
            # 异常行（缩进不足的延续行）—— 视作上一条目结束
            flush()

    flush()
    return entries


def _format_entry(key: str, value: str) -> str:
    """单条目 markdown 渲染。含 \\n 或 ≥200 字符自动 block。"""
    is_block = "\n" in value or len(value) >= 200
    if is_block:
        indented = "\n".join(f"  {ln}" if ln else "" for ln in value.splitlines())
        return f"- {key}:\n{indented}"
    return f"- {key}: {value}"


def remember(
    key: str,
    value: str,
    thread_id: str,
    category: Literal["facts", "preference"] = "facts",
    scope: Literal["thread", "global"] = "thread",
) -> str:
    """记住一条精确事实或用户偏好到记忆文件。

    与 MemoryManager.write_memory 不同：本函数只管 facts.md / preference.md
    这两条"精确事实 + 用户偏好"线，写入语义是按 key upsert；current.md
    仍是 LLM 后台自动维护的叙事性总结。

    Args:
        key: 事实标题（短而具体，agent 用此 key 做 dedup）。
              推荐 "主谓宾" 短语：Q2 销售聚合口径 / 用户偏好单位 / DB 端口。
        value: 内容。单行 ≤200 字符自动 inline；含 \\n 或 ≥200 字符自动 block。
        thread_id: 当前会话 ID（agent 从 prompt context 取 12 / 32 位 hex）。
                   即使 scope="global" 也要传（用于审计日志）。
        category: "facts"（精确事实 / 数值 / 路径 / 业务规则）
                  或 "preference"（用户偏好 / 习惯 / 风格）。
        scope: "thread"（仅当前会话）或 "global"（跨会话共享）。

    Returns:
        写入确认文本：
        - `[OK] remembered/updated '{key}' ({N} chars) → {path}`
        - `[BadRequest] ...`  / `[ReadError] ...` / `[WriteError] ...`

    语义：同名 key 替换旧值（updated），新 key 追加（appended）。
    """
    if category not in ("facts", "preference"):
        return f"[BadRequest] category 必须为 'facts' 或 'preference'，收到: {category!r}"
    if scope not in ("thread", "global"):
        return f"[BadRequest] scope 必须为 'thread' 或 'global'，收到: {scope!r}"
    if not key or not key.strip():
        return "[BadRequest] key 不能为空"
    if value is None:
        return "[BadRequest] value 不能为 None"

    file_path = _memory_file_path(scope, thread_id, category)
    lock = _get_file_lock(file_path)

    # 整个 read-modify-write 周期在同文件锁内串行化，防止并发写丢失更新
    with lock:
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                entries = _read_entries(content)
            except Exception as e:
                return f"[ReadError] 读取 {file_path} 失败: {e}"
        else:
            entries = []

        # Upsert：替换同名 key；新 key 追加在末尾
        action = "remembered"
        new_entries: list[tuple[str, str]] = []
        found = False
        for k, v in entries:
            if k == key:
                new_entries.append((key, value))
                found = True
                action = "updated"
            else:
                new_entries.append((k, v))
        if not found:
            new_entries.append((key, value))

        body = "\n\n".join(_format_entry(k, v) for k, v in new_entries)
        if body:
            body += "\n"

        try:
            _atomic_write_text(file_path, body)
        except Exception as e:
            return f"[WriteError] 写入 {file_path} 失败: {e}"

    return f"[OK] {action} '{key}' ({len(value)} chars) → {file_path}"


def recall(
    thread_id: str,
    category: Literal["facts", "preference"] = "facts",
    scope: Literal["thread", "global"] = "thread",
) -> str:
    """回忆事实或偏好文件完整内容。

    与 MemoryManager.read_memory 不同：本函数只读 facts.md / preference.md
    （精确事实 / 用户偏好）；current.md 由 context_assembly_node 自动合并注入，
    不需要主动调本函数。

    Args:
        thread_id: 当前会话 ID。
        category: "facts" / "preference"。
        scope: "thread" / "global"。

    Returns:
        完整文件内容；文件不存在时返回 "（空）"。
    """
    file_path = _memory_file_path(scope, thread_id, category)
    if not file_path.exists():
        return "（空）"
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[ReadError] 读取 {file_path} 失败: {e}"