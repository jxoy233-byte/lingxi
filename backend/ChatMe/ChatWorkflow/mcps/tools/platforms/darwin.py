"""
macOS 平台 adapter

macOS 自带 BSD 系 ls / cat / cp / rm / sed 等，与 Linux GNU 行为基本兼容
（少数 flag 差异不在 cmd 工具白名单内，足够用）。
shell 走 /bin/zsh（macOS Catalina 起的默认登录 shell）。
"""

from __future__ import annotations

import platform as _platform
import subprocess
from pathlib import Path

from .base import PlatformAdapter
from .linux import LinuxAdapter


class DarwinAdapter(PlatformAdapter):
    """macOS (Darwin) 平台 adapter

    危险模式 / 白名单继承自 LinuxAdapter（与 Linux 95% 相同）；
    差异点：system_name 含 Darwin + macOS 版本、shell 走 /bin/zsh。
    """

    def __init__(self):
        try:
            mac_ver = _platform.mac_ver()[0]  # e.g. "14.5"
            darwin_ver = _platform.release()  # e.g. "23.5.0"
            system_name = f"Darwin {darwin_ver} / macOS {mac_ver}" if mac_ver else f"Darwin {darwin_ver}"
        except Exception:
            system_name = "Darwin"

        # Darwin 危险模式与 Linux 几乎一致，但 macOS 没有 apt/yum/dnf/pacman
        # → 复用 LinuxAdapter 的危险模式，剔除 Linux 包管理器关键词
        dangerous = {
            k: v for k, v in LinuxAdapter._DANGEROUS_PATTERNS.items()
            if k not in {"apt-get remove --purge", "yum erase", "dnf remove", "pacman -Rns", "update-rc.d", "systemctl disable"}
        }
        # macOS 特有
        dangerous.update({
            'diskutil eraseDisk': '擦除磁盘',
            'diskutil partitionDisk': '重新分区磁盘',
            'softwareupdate --erase': 'erase-install macOS',
        })

        super().__init__(
            name="darwin",
            system_name=system_name,
            shell_path="/bin/zsh",
            shell_flag="-c",
            allowed_commands=LinuxAdapter._ALLOWED_COMMANDS,
            dangerous_patterns=dangerous,
        )

    @property
    def system_info_block(self) -> str:
        return (
            "**Runtime Environment**: sandbox (Linux container) | local=macOS "
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
        return candidates[0]

    def local_temp_dir(self) -> Path:
        return Path("/tmp")
