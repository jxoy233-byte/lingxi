"""
平台 adapter 模块

公开 API：
- get_platform()        懒加载拿当前平台 adapter
- init_platform()       启动时调一次，缓存单例
- reset_platform_cache() 测试用，重置缓存

典型用法：
    from ChatMe.ChatWorkflow.mcps.platforms import get_platform, init_platform

    # main() 启动时
    init_platform()  # 打 log 标识当前平台

    # 业务代码（cmd 工具 / agent_node / prompt 拼装）
    p = get_platform()
    if p.is_dangerous(cmd): return ...
    p.execute_command(cmd, sandbox_pool=pool)
"""

from .base import PlatformAdapter
from .linux import LinuxAdapter
from .darwin import DarwinAdapter
from .windows import WindowsAdapter
from .registry import get_platform, init_platform, reset_platform_cache

__all__ = [
    "PlatformAdapter",
    "LinuxAdapter",
    "DarwinAdapter",
    "WindowsAdapter",
    "get_platform",
    "init_platform",
    "reset_platform_cache",
]
