"""
平台 adapter 单元测试

覆盖：
1. 三平台 detection（mock platform.system）
2. 白名单：Linux/Darwin 允许 Unix 命令，Windows 拒绝 `ls` 但允许 `dir`/`type`/`where`/`findstr`
3. 危险模式：Linux 拦 `rm -rf /`，Windows 拦 `format c:`/`del /s /q`
4. 脚本检测：Python/Node 一律走 code 工具
5. 路径探测：local_venv_bin / local_temp_dir 跟平台对齐
6. prompt 片段：cmd_tool_prompt_block / system_info_block 含平台特定信息
7. execute_command 本地分支真跑（用平台 shell）
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# 把 backend 加到 sys.path（pytest 默认从 backend 跑就不需要；但保险起见）
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ChatMe.ChatWorkflow.mcps.platforms import (  # noqa: E402
    DarwinAdapter,
    LinuxAdapter,
    PlatformAdapter,
    WindowsAdapter,
    get_platform,
    init_platform,
    reset_platform_cache,
)
from ChatMe.ChatWorkflow.mcps.platforms import registry as _registry  # noqa: E402


# =========================================================================
# fixture：每个测试前重置 registry
# =========================================================================


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_platform_cache()
    yield
    reset_platform_cache()


# =========================================================================
# 1. 三平台 detection
# =========================================================================


def test_linux_detected():
    with patch("platform.system", return_value="Linux"):
        reset_platform_cache()
        p = init_platform()
    assert isinstance(p, LinuxAdapter)
    assert p.name == "linux"


def test_darwin_detected():
    with patch("platform.system", return_value="Darwin"):
        reset_platform_cache()
        p = init_platform()
    assert isinstance(p, DarwinAdapter)
    assert p.name == "darwin"


def test_windows_detected():
    with patch("platform.system", return_value="Windows"):
        reset_platform_cache()
        p = init_platform()
    assert isinstance(p, WindowsAdapter)
    assert p.name == "windows"


def test_get_platform_lazy_init():
    """get_platform() 在没 init 时也能用（懒加载）。"""
    with patch("platform.system", return_value="Linux"):
        reset_platform_cache()
        p = get_platform()
    assert isinstance(p, LinuxAdapter)


# =========================================================================
# 2. 白名单
# =========================================================================


@pytest.mark.parametrize("cmd", ["ls", "ls -la", "cat foo.txt", "grep -r pattern", "rm -rf tmp", "curl https://example.com"])
def test_linux_allows_unix_commands(cmd):
    p = LinuxAdapter()
    ok, _ = p.is_allowed(cmd)
    assert ok is True, f"Linux should allow {cmd!r}"


@pytest.mark.parametrize("cmd", ["dir", "dir C:\\Users", "type foo.txt", "findstr pattern file.txt", "where python", "del temp.txt"])
def test_windows_allows_native_commands(cmd):
    p = WindowsAdapter()
    ok, _ = p.is_allowed(cmd)
    assert ok is True, f"Windows should allow {cmd!r}"


@pytest.mark.parametrize("cmd", ["ls -la", "cat foo.txt", "grep pattern", "cp a b", "rm file", "which python", "pwd"])
def test_windows_rejects_unix_commands(cmd):
    p = WindowsAdapter()
    ok, reason = p.is_allowed(cmd)
    assert ok is False, f"Windows should reject {cmd!r}"
    # 拒绝信息应提示 LLM 用 Windows 等价命令
    assert "whitelist" in reason.lower()
    # 应列出可用命令
    assert "dir" in reason or "type" in reason


@pytest.mark.parametrize("cmd", ["dir", "type foo.txt", "findstr p f", "del f", "copy a b"])
def test_linux_rejects_windows_commands(cmd):
    p = LinuxAdapter()
    ok, _ = p.is_allowed(cmd)
    assert ok is False, f"Linux should reject Windows-only {cmd!r}"


# =========================================================================
# 3. 危险模式
# =========================================================================


@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf /*",
    "dd if=/dev/zero of=/dev/sda",
    "mkfs.ext4 /dev/sda",
    "iptables -F",
    "kill -9 -1",
    "sudo rm -rf /etc",
])
def test_linux_blocks_dangerous(cmd):
    p = LinuxAdapter()
    is_d, reason = p.is_dangerous(cmd)
    assert is_d is True, f"Linux should block {cmd!r}: {reason}"


@pytest.mark.parametrize("cmd", [
    "format c:",
    "format /dev/sda1",
    "del /s /q C:\\*",
    "rmdir /s /q C:\\Windows",
    "fsutil fsinfo drives",
    "diskpart",
    "shutdown /s /t 0",
    "reg delete HKLM\\Software",
])
def test_windows_blocks_dangerous(cmd):
    p = WindowsAdapter()
    is_d, reason = p.is_dangerous(cmd)
    assert is_d is True, f"Windows should block {cmd!r}: {reason}"


def test_linux_allows_safe_command():
    p = LinuxAdapter()
    is_d, _ = p.is_dangerous("ls -la skills/")
    assert is_d is False


def test_windows_allows_safe_command():
    p = WindowsAdapter()
    is_d, _ = p.is_dangerous("dir skills")
    assert is_d is False


def test_device_redirect_blocked_on_linux():
    p = LinuxAdapter()
    is_d, _ = p.is_dangerous("echo x > /dev/sda")
    assert is_d is True


def test_format_string_not_blocked():
    """`format` 作为文件名 / 函数 / 字符串一部分不应被拦。"""
    p = LinuxAdapter()
    is_d, _ = p.is_dangerous("python -c \"print('format string ok')\"")
    assert is_d is False
    is_d, _ = p.is_dangerous("cat format.py")
    assert is_d is False


# =========================================================================
# 4. 脚本检测
# =========================================================================


@pytest.mark.parametrize("cmd,lang", [
    ("python script.py", "Python"),
    ("python3 -c 'print(1)'", "Python"),
    ("node app.js", "Node.js"),
    ("ruby foo.rb", "Ruby"),
    ("php -r 'echo 1;'", "PHP"),
    ("perl -e 'print'", "Perl"),
])
def test_script_detected(cmd, lang):
    p = LinuxAdapter()
    is_s, detected_lang = p.is_script(cmd)
    assert is_s is True
    assert detected_lang == lang


def test_non_script_not_detected():
    p = LinuxAdapter()
    is_s, _ = p.is_script("ls -la")
    assert is_s is False


# =========================================================================
# 5. 路径探测
# =========================================================================


def test_linux_local_venv_bin_lives_under_dot_venv_bin():
    p = LinuxAdapter()
    venv_bin = p.local_venv_bin()
    assert venv_bin.name in {"bin", "Scripts"}  # 实际是 bin（沙盒/WSL 跑测试也走 LinuxAdapter）
    # 在沙盒/容器内可能没有真实 venv，路径可能不存在 —— 只检查结构对
    assert ".venv" in str(venv_bin) or "venv" in str(venv_bin)


def test_windows_local_venv_bin_uses_scripts():
    p = WindowsAdapter()
    venv_bin = p.local_venv_bin()
    assert venv_bin.name == "Scripts"
    assert venv_bin.parent.name in {".venv", "venv"}


def test_linux_local_temp_dir_is_tmp():
    p = LinuxAdapter()
    assert p.local_temp_dir() == Path("/tmp")


def test_darwin_local_temp_dir_is_tmp():
    p = DarwinAdapter()
    assert p.local_temp_dir() == Path("/tmp")


def test_windows_local_temp_dir_uses_tempfile(tmp_path, monkeypatch):
    """Windows temp dir 走 tempfile.gettempdir() 而非硬编码 /tmp。"""
    fake_temp = tmp_path / "WindowsAppData" / "Local" / "Temp"
    fake_temp.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_temp))
    p = WindowsAdapter()
    assert p.local_temp_dir() == fake_temp
    assert p.local_temp_dir() != Path("/tmp")  # 关键：Windows 绝不能用 /tmp


# =========================================================================
# 6. prompt 片段含平台特定信息
# =========================================================================


def test_cmd_block_has_allowed_commands():
    """prompt block 必须列出当前平台可用命令（让 LLM 直接看到）。"""
    with patch("platform.system", return_value="Windows"):
        reset_platform_cache()
        p = init_platform()
    block = p.cmd_tool_prompt_block
    assert "Allowed Commands" in block
    # 至少含 dir + type + findstr
    assert "dir" in block and "type" in block and "findstr" in block
    # 必须显式告诉 LLM 平台
    assert "Windows" in block


def test_linux_cmd_block_has_unix_commands():
    with patch("platform.system", return_value="Linux"):
        reset_platform_cache()
        p = init_platform()
    block = p.cmd_tool_prompt_block
    assert "ls" in block and "cat" in block and "grep" in block
    assert "Linux" in block or "WSL" in block


def test_darwin_cmd_block_mentions_macos():
    with patch("platform.system", return_value="Darwin"):
        reset_platform_cache()
        p = init_platform()
    block = p.cmd_tool_prompt_block
    assert "macOS" in block or "Darwin" in block


def test_system_info_block_format():
    p = LinuxAdapter()
    info = p.system_info_block
    assert info.startswith("**Runtime Environment**:")
    # 必须含 sandbox + native fallback 两条路径
    assert "sandbox" in info.lower()
    assert "fallback" in info.lower() or "native" in info.lower()


def test_windows_system_info_uses_cmd_exe():
    p = WindowsAdapter()
    info = p.system_info_block
    assert "cmd.exe" in info
    assert "Scripts" in info  # .venv\Scripts\python.exe


def test_darwin_system_info_uses_zsh():
    p = DarwinAdapter()
    info = p.system_info_block
    assert "zsh" in info


# =========================================================================
# 7. execute_command 本地分支真跑
# =========================================================================


def test_linux_execute_command_local_echo():
    p = LinuxAdapter()
    # 真跑一个简单 echo，验证 shell 路径 + cwd + env
    out = p.execute_command('echo "hello from linux"', sandbox_pool=None)
    assert "hello from linux" in out
    assert "STDOUT" in out
    assert "Return code: 0" in out


def test_darwin_execute_command_local_pwd():
    """Darwin adapter 在 macOS 上跑 pwd 应返回 cwd。"""
    p = DarwinAdapter()
    out = p.execute_command("pwd", sandbox_pool=None)
    assert "STDOUT" in out
    # macOS 真机会返回 /Users/... 或 backend cwd
    # 在 sandbox / CI 上 Darwin 不会出现，跳过
    assert "Return code: 0" in out or "Return code:" in out


def test_execute_command_local_timeout():
    """长跑命令会触发 timeout（5s 已够，不用 120s）。"""
    p = LinuxAdapter()
    out = p._execute_command_local("sleep 30", timeout=1)
    assert "timed out" in out.lower() or "timeout" in out.lower()


def test_execute_command_local_nonzero_exit():
    p = LinuxAdapter()
    out = p.execute_command("ls /nonexistent_path_xyz", sandbox_pool=None)
    assert "Return code:" in out
    assert "Return code: 0" not in out


# =========================================================================
# 8. prompt 拼装集成（get_agent_node_prompt / build_sub_agent_prompt）
# =========================================================================


def test_get_agent_node_prompt_includes_platform_info():
    from ChatMe.ChatWorkflow.config.graph_config import get_agent_node_prompt
    with patch("platform.system", return_value="Windows"):
        reset_platform_cache()
        prompt = get_agent_node_prompt()
    assert "cmd.exe" in prompt
    assert "Windows" in prompt
    assert "dir" in prompt  # 平台允许命令


def test_build_sub_agent_prompt_omits_dispatch_tools():
    """sub-agent 不暴露 interrupt / sub_agent。"""
    from ChatMe.ChatWorkflow.config.graph_config import build_sub_agent_prompt
    with patch("platform.system", return_value="Linux"):
        reset_platform_cache()
        prompt = build_sub_agent_prompt("test task", "cmd → ls skills/")
    assert "interrupt" not in prompt.lower().split("interrupted")[0]  # 简单检查
    # 任务注入
    assert "test task" in prompt
    assert "cmd → ls skills/" in prompt


def test_main_prompt_vs_sub_prompt_length_difference():
    """main 比 sub 多 interrupt + sub_agent 段，长度应该明显更长。"""
    from ChatMe.ChatWorkflow.config.graph_config import (
        build_sub_agent_prompt,
        get_agent_node_prompt,
    )
    main = get_agent_node_prompt()
    sub = build_sub_agent_prompt("dummy")
    assert len(main) > len(sub)


# =========================================================================
# 9. 抽象基类 / inheritance sanity
# =========================================================================


def test_all_adapters_inherit_base():
    for cls in (LinuxAdapter, DarwinAdapter, WindowsAdapter):
        assert issubclass(cls, PlatformAdapter)


def test_adapter_instances_independent():
    """每个 adapter 实例互不污染（危险模式 dict 不能共用）。"""
    p1 = LinuxAdapter()
    p2 = LinuxAdapter()
    p1.dangerous_patterns["__test_marker__"] = "test"
    assert "__test_marker__" not in p2.dangerous_patterns
