"""
平台 adapter 注册中心

启动时（mcps/server.py main()）调 init_platform() 一次，结果缓存到模块级单例。
后续 agent_node / cmd 工具通过 get_platform() 读——避免每次调用都做平台检测。
"""

from __future__ import annotations

import platform as _platform
from typing import Optional

from .base import PlatformAdapter
from .linux import LinuxAdapter
from .darwin import DarwinAdapter
from .windows import WindowsAdapter

_cached: Optional[PlatformAdapter] = None


def _detect() -> PlatformAdapter:
    """根据 platform.system() 选 adapter。WSL 内部 platform.system() 返回 Linux → LinuxAdapter。"""
    sys_name = _platform.system().lower()
    if sys_name == "windows":
        return WindowsAdapter()
    if sys_name == "darwin":
        return DarwinAdapter()
    # Linux / WSL / 其他 Unix-like
    return LinuxAdapter()


def init_platform() -> PlatformAdapter:
    """启动时调一次，缓存到模块级。"""
    global _cached
    if _cached is None:
        _cached = _detect()
    return _cached


def get_platform() -> PlatformAdapter:
    """懒加载：第一次调 init_platform()。

    用法：在业务代码中 from ChatMe.ChatWorkflow.mcps.tools.platforms import get_platform; p = get_platform()。
    如果想保证启动时就检测（比如想 fail-fast 报 platform 错误），在 main() 调 init_platform()。
    """
    if _cached is None:
        init_platform()
    return _cached


def reset_platform_cache() -> None:
    """测试用：清空单例，下一次 get_platform() 重新检测。

    注意：仅用于单元测试（mock platform.system 后需要重新触发检测）。
    生产代码不要调。
    """
    global _cached
    _cached = None
