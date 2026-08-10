"""
Windows 平台 adapter

shell 走 cmd.exe（与 PowerShell / WSL 默认行为显式区分）。
白名单采用 Windows 原生命令（dir / type / findstr / copy / move / del 等）。
"""

from __future__ import annotations

import platform as _platform
import subprocess
import tempfile
from pathlib import Path

from .base import PlatformAdapter


class WindowsAdapter(PlatformAdapter):
    """Windows 平台 adapter"""

    _DANGEROUS_PATTERNS = {
        # 通用
        'mkfs': '创建文件系统（可能破坏数据）',
        'dd if=/dev/zero': '用零覆盖数据',
        'dd if=/dev/random': '用随机数据覆盖',
        'kill -9 -1': '终止所有进程',
        'pip uninstall -y': '卸载 Python 包',
        'npm uninstall -g': '卸载全局 npm 包',
        # Windows 专属
        'del /s /q': '静默删除文件',
        'rmdir /s /q': '静默删除目录',
        'fsutil': '文件系统工具（可能破坏数据）',
        'diskpart': '磁盘分区工具',
        'bcdedit /delete': '删除启动配置',
        'sfc /scannow': '系统文件检查（可能影响系统）',
        'cipher /w': '擦除空闲空间',
        'shutdown /s /t 0': '立即关机',
        'shutdown /r /t 0': '立即重启',
        'deltree': 'Windows 删除目录树',
        'C:\\Windows\\System32': 'Windows 系统目录',
        'HKEY_LOCAL_MACHINE': 'Windows 注册表',
        'reg delete HKLM': '删除注册表项',
        '> \\\\.\\PhysicalDrive': 'Windows 物理磁盘写入',
        'icacls * /grant everyone:F': 'Windows 完全控制权限',
        'netsh advfirewall reset': 'Windows 重置防火墙',
        'taskkill /F /IM *': 'Windows 终止所有进程',
    }

    _ALLOWED_COMMANDS = {
        "dir", "cd",
        "type", "more", "findstr", "fc",
        "copy", "move", "mkdir", "del", "rmdir",
        "sort",
        "curl",
        "where",       # which 的等价
        "tar",         # Windows 10+ 内置
    }

    def __init__(self):
        try:
            win_ver = _platform.win32_ver()  # (release, version, csd, ptype)
            release = win_ver[0] or "Windows"
            version = win_ver[1] or ""
            system_name = f"{release} {version}".strip()
        except Exception:
            system_name = "Windows"

        super().__init__(
            name="windows",
            system_name=system_name,
            shell_path="cmd.exe",
            shell_flag="/c",
            allowed_commands=self._ALLOWED_COMMANDS,
            dangerous_patterns=self._DANGEROUS_PATTERNS,
        )

    @property
    def cmd_tool_prompt_block(self) -> str:
        return """### cmd — Shell Execution
Default: Linux sandbox (local=False). Local fallback (Windows): cmd.exe with native commands (dir/type/findstr/copy/move/del/rmdir/where) — NO Unix commands in local fallback. To run scripts (python/node/etc), prefer the `code` tool.

Set `local=True` to run on host.

Parameters: command (required, string), local (default: False)"""

    @property
    def code_tool_prompt_block(self) -> str:
        return """### code — Inline Code
Default: Linux sandbox (local=False). Local fallback (Windows): .venv\\Scripts\\python.exe, temp under %TEMP% (not /tmp).

Set `local=True` to run on host.

Parameters: code (required, string), language (default: "python"), local (default: False)"""

    @property
    def system_info_block(self) -> str:
        return (
            f"**Runtime Environment**: {self.system_name} / cmd.exe / "
            f"sandbox: chatme-python-sandbox (Linux container) | "
            f"native fallback: local venv (.venv\\Scripts\\python.exe)"
        )

    def local_venv_bin(self) -> Path:
        project_root = Path.cwd()
        candidates = [
            project_root / ".venv" / "Scripts",
            project_root / "venv" / "Scripts",
            project_root.parent / ".venv" / "Scripts",
            project_root.parent / "venv" / "Scripts",
        ]
        for p in candidates:
            if p.exists() and (p / "python.exe").exists():
                return p
        return candidates[0]

    def local_temp_dir(self) -> Path:
        return Path(tempfile.gettempdir())

    def _build_local_env(self) -> dict:
        """Windows override：PATH 分隔符是 `;`，venv 是 Scripts/，python.exe 可执行。"""
        env = super()._build_local_env()
        # Windows 下 subprocess.run 找 `python` 找不到，必须用 `python.exe`
        # 但 base.py 的 venv_python 检测已经走 (venv_bin / "python.exe").exists()，
        # 所以这里不动。只确保 PATHEXT 含 .EXE（默认就有，但兜底）。
        env.setdefault("PATHEXT", ".COM;.EXE;.BAT;.CMD;.VBS;.JS;.WS;.MSC")
        return env
