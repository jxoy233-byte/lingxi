"""
平台 adapter 模块

公开 API：
- get_platform()        懒加载拿当前平台 adapter
- init_platform()       启动时调一次，缓存单例
- reset_platform_cache() 测试用，重置缓存

4 个 adapter 类职责：
- PlatformAdapter       抽象基类：is_allowed / is_dangerous / system_info_block
                        等通用检查 + interrupt_tool_prompt_block（跨平台一致）
- LinuxAdapter           Linux / WSL（WSL 内部 platform.system() 返回 Linux）：
                        bash + POSIX 白名单（ls / cat / grep / rm / curl...）+
                        危险模式（rm -rf /、dd、mkfs、iptables、sudo 提升等）
- DarwinAdapter         macOS：复用 LinuxAdapter 的大多数（POSIX shell），
                        仅微调 local_temp_dir 等少量字段
- WindowsAdapter        Windows：cmd.exe + 原生命令白名单（dir / type / findstr /
                        where / del 等），危险模式（format / del /s /q、diskpart、
                        shutdown /s /t 0 等）

调用关系：
- platforms 内部依赖 SandboxPool 跑 docker exec（sandbox/pool.py）
- agent_node / cmd 工具 / prompt 拼装 都通过 get_platform() 拿单例

典型用法：
    from ChatMe.ChatWorkflow.mcps.tools.platforms import get_platform, init_platform

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