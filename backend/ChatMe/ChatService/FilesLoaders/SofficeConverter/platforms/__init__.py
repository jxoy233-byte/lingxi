"""
平台注册表 - 自动根据当前系统选择对应平台实现
"""

import platform
from .base import BasePlatform
from .darwin import DarwinPlatform
from .windows import WindowsPlatform
from .linux import LinuxPlatform


_PLATFORMS: dict[str, type[BasePlatform]] = {
    "Darwin": DarwinPlatform,
    "Windows": WindowsPlatform,
    "Linux": LinuxPlatform,
}


def get_current_platform() -> BasePlatform:
    """获取当前系统的平台实现"""
    system = platform.system()
    platform_cls = _PLATFORMS.get(system)
    if platform_cls is None:
        raise RuntimeError(f"不支持的平台: {system}")
    return platform_cls()


__all__ = [
    "BasePlatform",
    "get_current_platform",
]