"""
平台 adapter 抽象基类

每个具体平台（Linux / Darwin / Windows）继承 PlatformAdapter，
提供：白名单 / 危险模式 / cmd 工具 prompt 片段 / code 工具 prompt 片段 /
运行时信息块 / 路径探测（venv / temp dir）/ 本地执行实现。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from shutil import which
from typing import Optional, Set, Tuple, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ChatMe.ChatWorkflow.mcps.CodeSandboxPool import SandboxPool


# 通用脚本执行检测（跨平台一致）
_SCRIPT_PATTERNS = [
    ("Python", [
        r'^python(\d+(\.\d+)?)?\s+',
        r'^pypy3?\s+',
        r'python(\d+(\.\d+)?)?\s+-c\s+',
        r'python(\d+(\.\d+)?)?\s+-m\s+',
        r'python(\d+(\.\d+)?)?\s+<<',
    ]),
    ("Node.js", [
        r'^node(\d+(\.\d+)?)?\s+',
        r'^node(\d+(\.\d+)?)?\s+-e\s+',
        r'^node(\d+(\.\d+)?)?\s+-p\s+',
        r'^node(\d+(\.\d+)?)?\s+-pe\s+',
        r'^node(\d+(\.\d+)?)?\s+<<',
    ]),
    ("Ruby", [r'^ruby\s+', r'^ruby\s+-e\s+']),
    ("PHP", [r'^php\s+', r'^php\s+-r\s+']),
    ("Perl", [r'^perl\s+', r'^perl\s+-e\s+']),
]

# 通用危险检测：设备重定向 + format 盘符 + sudo 提升
_DEVICE_REDIRECT_PATTERNS = [
    r'>\s*/dev/[hs]d[a-z]',
    r'>\s*/dev/sd[a-z]',
    r'>\s*\\\\\.\\PhysicalDrive',
    r'\s+\|\s*tee\s+/dev/',
]


class PlatformAdapter(ABC):
    """平台 adapter 抽象基类

    子类通过 __init__ 传入 name / system_name / shell_path / shell_flag /
    allowed_commands / dangerous_patterns，base 类负责把它们存为实例属性
    + 提供 is_dangerous / is_allowed / is_script 等通用检查。

    cmd_tool_prompt_block / code_tool_prompt_block / ctime_tool_prompt_block /
    system_info_block 必须由子类实现（每个平台自己写 Allowed Commands 表格
    和执行说明）。
    """

    def __init__(
        self,
        name: str,
        system_name: str,
        shell_path: str,
        shell_flag: str,
        allowed_commands: Set[str],
        dangerous_patterns: Dict[str, str],
    ):
        self.name = name
        self.system_name = system_name
        self.shell_path = shell_path
        self.shell_flag = shell_flag
        self.allowed_commands = set(allowed_commands)
        self.dangerous_patterns = dict(dangerous_patterns)

    # =========================================================================
    # 必填：每个平台自己写
    # =========================================================================

    @property
    @abstractmethod
    def cmd_tool_prompt_block(self) -> str:
        """整个 `### cmd` 章节的 prompt 片段（含 Allowed Commands 表格）。"""

    @property
    @abstractmethod
    def code_tool_prompt_block(self) -> str:
        """整个 `### code` 章节的 prompt 片段（sandbox + 本地 fallback 行为说明）。"""

    @property
    @abstractmethod
    def system_info_block(self) -> str:
        """**Runtime Environment**: <os> / <shell> / sandbox: <name> | <local-fallback>"""

    @abstractmethod
    def local_venv_bin(self) -> Path:
        """本地 venv 的 bin/Scripts 目录（用于本地 fallback 跑 python / node）。

        Unix: backend/.venv/bin
        Windows: backend/.venv/Scripts
        """

    @abstractmethod
    def local_temp_dir(self) -> Path:
        """本地执行时临时代码文件落盘目录。

        Unix: /tmp
        Windows: %TEMP% (Path(tempfile.gettempdir()))
        """

    # =========================================================================
    # 通用：跨平台一致
    # =========================================================================

    @property
    def ctime_tool_prompt_block(self) -> str:
        """### ctime 章节——跨平台一致，放 base 复用。"""
        return """### ctime — Time Reference
Use when: Task involves any time reference including "today", "tomorrow", "now", "this week", "current date/time", "what time is it", etc.
Must call this FIRST before any other time-related operations.
Parameters: none"""

    # =========================================================================
    # 检查：危险 / 白名单 / 脚本（mix 子类数据 + 通用逻辑）
    # =========================================================================

    def is_script(self, command: str) -> Tuple[bool, str]:
        """检测命令是否为脚本执行（Python / Node.js / Ruby / PHP / Perl）。"""
        for lang, patterns in _SCRIPT_PATTERNS:
            if any(re.search(p, command) for p in patterns):
                return True, lang
        return False, ""

    def is_dangerous(self, command: str) -> Tuple[bool, str]:
        """检测命令是否危险。

        流程：子类 dangerous_patterns（模式 → 原因）→ 设备重定向 regex →
        format 盘符 → sudo 提升组合。
        """
        command_lower = command.lower()

        # 子类传入的特定模式
        for pattern, reason in self.dangerous_patterns.items():
            if pattern.lower() in command_lower:
                return True, f"Dangerous command detected: {pattern} ({reason})"

        # 设备重定向（跨平台统一）
        for pattern in _DEVICE_REDIRECT_PATTERNS:
            if re.search(pattern, command):
                return True, "Redirecting to device file detected"

        # format 磁盘格式化（仅当作为独立命令 + 跟设备路径时才拦截）
        if re.search(r'(?:^|[\s;&|])format\s+(?:/dev/|[a-zA-Z]:|--?\w+)', command):
            return True, "Dangerous command detected: format (disk format)"

        # sudo 提升组合
        if 'sudo' in command_lower and any(
            x in command_lower for x in ['rm', 'dd', 'mkfs', 'chmod', 'chown']
        ):
            return True, "sudo executing dangerous operation detected"

        return False, ""

    def is_allowed(self, command: str) -> Tuple[bool, str]:
        """检测命令是否在当前平台白名单中。"""
        first_token = command.strip().split()[0].strip('"\'|;$<>')
        main_cmd = first_token.split("/")[-1]
        if main_cmd in self.allowed_commands:
            return True, ""
        return False, (
            f"Command \"{main_cmd}\" is not in the whitelist. "
            f"Use a whitelisted command. "
            f"Allowed on {self.name}: {', '.join(sorted(self.allowed_commands))}"
        )

    # =========================================================================
    # 执行：cmd 工具（sandbox + 本地 fallback）
    # =========================================================================

    def execute_command(self, command: str, sandbox_pool: Optional["SandboxPool"] = None, cmd_timeout: int = 120) -> str:
        """执行 shell 命令。优先 sandbox，否则走本地（平台特定 shell）。"""
        # 沙盒执行
        if sandbox_pool is not None:
            try:
                return sandbox_pool.execute_command(command)
            except subprocess.TimeoutExpired:
                return (
                    f"Error: Command execution timed out ({cmd_timeout}s limit), "
                    "please optimize the command or split it into smaller steps"
                )

        # 本地 fallback
        return self._execute_command_local(command, cmd_timeout)

    def _execute_command_local(self, command: str, timeout: int) -> str:
        """本地 shell 执行（override 可换 shell 路径）。"""
        env = self._build_local_env()
        try:
            # Windows 走 cmd.exe 显式 executable；Unix 走默认 sh
            kwargs = dict(
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if self.name == "windows":
                # 显式走 cmd.exe，避免 PowerShell / WSL 干扰
                kwargs["executable"] = self.shell_path
            else:
                # Unix 下 shell=True 默认 /bin/sh -c；显式传更可控
                kwargs["executable"] = self.shell_path

            project_root = Path.cwd()
            result = subprocess.run(command, cwd=str(project_root), **kwargs)
            return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
        except subprocess.TimeoutExpired:
            return f"Error: Command execution timed out ({timeout} seconds limit)"
        except Exception as e:
            return f"Error: {str(e)}"

    def _build_local_env(self) -> dict:
        """构造本地执行环境：PATH 优先 venv bin/Scripts、PYTHONPATH 包含 backend + skills。"""
        env = {}
        for k, v in __import__("os").environ.items():
            env[k] = v

        project_root = Path.cwd()
        skills_dir = project_root / "skills"
        venv_bin = self.local_venv_bin()

        # PATH 优先 venv bin/Scripts
        if venv_bin.exists():
            current_path = env.get("PATH", "")
            venv_bin_str = str(venv_bin)
            if not current_path.startswith(venv_bin_str):
                # Windows 用 ; 分隔 PATH；Unix 用 :
                sep = ";" if self.name == "windows" else ":"
                env["PATH"] = f"{venv_bin_str}{sep}{current_path}"

        # PYTHONPATH 包含 backend + skills
        backend_dir = str(project_root)
        skills_abs = str(skills_dir) if skills_dir.exists() else ""
        existing_pythonpath = env.get("PYTHONPATH", "")
        new_parts = [p for p in (backend_dir, skills_abs, existing_pythonpath) if p]
        # 去重保序
        seen, merged = set(), []
        sep = ";" if self.name == "windows" else ":"
        for p in new_parts:
            if p not in seen:
                seen.add(p)
                merged.append(p)
        env["PYTHONPATH"] = sep.join(merged)
        return env

    # =========================================================================
    # 执行：code 工具（sandbox + 本地 fallback）
    # =========================================================================

    def execute_code_local(self, code: str, language: str, code_timeout: int = 300) -> str:
        """本地 venv 执行 Python / JS 代码。"""
        project_root = Path.cwd()
        skills_dir = project_root / "skills"
        venv_bin = self.local_venv_bin()

        # 找 venv python
        venv_python = None
        if venv_bin.exists():
            if (venv_bin / "python").exists():
                venv_python = str(venv_bin / "python")
            elif (venv_bin / "python.exe").exists():
                venv_python = str(venv_bin / "python.exe")
        if not venv_python:
            venv_python = sys.executable

        env = self._build_local_env()

        suffix = ".py" if language == "python" else ".js"

        # 用 NamedTemporaryFile 写代码到 local_temp_dir()，执行完清理
        # Windows 下 NamedTemporaryFile 默认 delete=True + close 后删除，subprocess 还持有 fd 会失败
        # 所以用 delete=False + finally 清理
        fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=str(self.local_temp_dir()))
        try:
            with __import__("os").fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)

            if language == "python":
                result = subprocess.run(
                    [venv_python, temp_path],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    timeout=code_timeout,
                    env=env,
                )
            else:
                node_cmd = which("node")
                if not node_cmd:
                    return "Error: Node.js not found"
                result = subprocess.run(
                    [node_cmd, temp_path],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    timeout=code_timeout,
                    env=env,
                )

            return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
        except subprocess.TimeoutExpired:
            return (
                f"Error: code execution timed out ({code_timeout}s limit), "
                "please optimize the script or split the task into smaller steps"
            )
        finally:
            try:
                __import__("os").unlink(temp_path)
            except FileNotFoundError:
                pass
