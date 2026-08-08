"""
Linux 平台 adapter

适用：原生 Linux + WSL（WSL 内部 platform.system() 也是 Linux，
行为与原生 Linux 一致；路径差异在 adapter 之外处理）。
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path

from .base import PlatformAdapter


class LinuxAdapter(PlatformAdapter):
    """Linux / WSL 平台 adapter"""

    # 通用 + Linux/Darwin 危险模式（来自 server.py 原 is_dangerous_command 通用 + unix_dangerous 段）
    _DANGEROUS_PATTERNS = {
        # 通用
        'rm -rf /': '删除根目录',
        'rm -rf /*': '删除所有文件',
        'mkfs': '创建文件系统（可能破坏数据）',
        'newfs': '创建新文件系统',
        'dd if=/dev/zero': '用零覆盖数据',
        'dd if=/dev/random': '用随机数据覆盖',
        'chmod -R 777 /': '开放所有权限到根目录',
        ':(){ :|:& };:': 'Bash fork 炸弹',
        'iptables -F': '清空防火墙规则',
        'kill -9 -1': '终止所有进程',
        '/etc/passwd': 'Linux 用户配置文件',
        '/etc/shadow': 'Linux 密码文件',
        'apt-get remove --purge': '彻底删除包',
        'yum erase': '删除包',
        'dnf remove': '删除包',
        'pacman -Rns': 'Arch 删除包',
        'pip uninstall -y': '卸载 Python 包',
        'npm uninstall -g': '卸载全局 npm 包',
        # Unix 专属
        'sudo su -': '获取 root shell',
        'passwd -d': '删除用户密码',
        'userdel -r': '删除用户及家目录',
        'vigr': '编辑组文件',
        'vipw': 'edit password file',
        'update-rc.d': 'modify startup services',
        'systemctl disable': 'disable system service',
        'mount -o remount,ro /': 'remount as read-only',
        'umount /': 'unmount root directory',
    }

    _ALLOWED_COMMANDS = {
        "ls", "cd", "pwd", "which",
        "cat", "head", "tail", "grep", "wc",
        "cp", "mv", "mkdir", "rm", "find", "sed",
        "awk", "sort", "echo", "touch", "diff", "tar", "gzip",
        "curl",
    }

    def __init__(self):
        # system_name 含 kernel + distro（如果能拿到）
        try:
            kernel = _platform.release()
            distro = ""
            try:
                # /etc/os-release 优先（systemd 标准化）
                os_release = Path("/etc/os-release")
                if os_release.exists():
                    for line in os_release.read_text().splitlines():
                        if line.startswith("PRETTY_NAME="):
                            distro = line.split("=", 1)[1].strip('"')
                            break
            except Exception:
                pass
            system_name = f"Linux {kernel}" + (f" / {distro}" if distro else "")
        except Exception:
            system_name = "Linux"

        super().__init__(
            name="linux",
            system_name=system_name,
            shell_path="/bin/sh",
            shell_flag="-c",
            allowed_commands=self._ALLOWED_COMMANDS,
            dangerous_patterns=self._DANGEROUS_PATTERNS,
        )

    # =========================================================================
    # 必填：平台特定
    # =========================================================================

    @property
    def cmd_tool_prompt_block(self) -> str:
        return """### cmd — Environment Exploring & File Operations
Parameters: command (required, string), use_sandbox(default, True)
**Allowed Commands**:
| Scenario | Commands |
|----------|----------|
| Browse directories | `ls`, `cd`, `pwd`, `which` |
| Read files | `cat`, `head`, `tail`, `grep`, `wc`, `awk` |
| File operations | `cp`, `mv`, `mkdir`, `rm`, `find`, `sed`, `sort`, `echo`, `touch`, `diff` |
| Network probe | `curl` (only as last resort when no suitable skills available) |

Note: This environment is Linux/WSL. Commands listed above are available."""

    @property
    def code_tool_prompt_block(self) -> str:
        return """### code — Code Execution & Skill Usage & Data Analysis & other codes required scenes
Use when: Writing or running code to solve problems, invoke skills, process data, or perform actions that require code execution.
Parameters: code (required, string), language (default: "python"), use_sandbox(default, True)

Important for cmd && code:
- Always remember to print final key results you need to pass to the next step.
- Default use_sandbox=True(sandbox, isolated execution with /skills ro + /cached rw).
- Don't add comments in your codes
- If you want to write some scripts files, you must write under 'cached/' dir"""

    @property
    def system_info_block(self) -> str:
        return (
            f"**Runtime Environment**: {self.system_name} / bash (sh) / "
            f"sandbox: chatme-python-sandbox (Linux container) | "
            f"native fallback: local venv (.venv/bin)"
        )

    def local_venv_bin(self) -> Path:
        project_root = Path.cwd()
        candidates = [
            project_root / ".venv" / "bin",
            project_root / "venv" / "bin",
            project_root.parent / ".venv" / "bin",
            project_root.parent / "venv" / "bin",
        ]
        for p in candidates:
            if p.exists() and (p / "python").exists():
                return p
        return candidates[0]  # 兜底返回第一个，调用方会再校验

    def local_temp_dir(self) -> Path:
        return Path("/tmp")
