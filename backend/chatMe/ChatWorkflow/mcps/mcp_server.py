from shutil import which
from typing import Any, Annotated, Literal, Optional

from fastmcp import FastMCP
import subprocess
import tempfile
import os
import platform
import re
import sys

from chatMe.logging_config import get_logger

server = FastMCP(name="ChatMe Agent Skills", )

logger = get_logger("mcp_server")

def is_dangerous_command(command: Annotated[ str, "系统执行命令"]) -> tuple[bool, str]:
    """
    检测命令是否危险
    返回：(是否危险，危险原因)
    """
    system = platform.system().lower()
    command_lower = command.lower()

    # 通用
    dangerous_patterns = {
        'rm -rf /': '删除根目录',
        'rm -rf /*': '删除所有文件',
        'rm -rf \\': 'Windows 删除操作',
        'deltree': 'Windows 删除目录树',
        'format': '格式化磁盘',
        'mkfs': '创建文件系统（可能破坏数据）',
        'newfs': '创建新文件系统',

        'dd if=/dev/zero': '用零覆盖数据',
        'dd if=/dev/random': '用随机数据覆盖',
        '> /dev/sda': '直接写入磁盘设备',
        '> \\\\.\\PhysicalDrive': 'Windows 物理磁盘写入',
        'cat /dev/null >': '清空文件内容',

        'chmod -R 777 /': '开放所有权限到根目录',
        'chmod -R 777 \\': 'Windows 开放所有权限',
        'chown -R': '递归修改所有者（可能破坏系统）',
        'icacls * /grant everyone:F': 'Windows 完全控制权限',

        ':(){ :|:& };:': 'Bash fork 炸弹',
        '${fork bomb variants}': '各种 fork 炸弹变体',

        'iptables -F': '清空防火墙规则',
        'netsh advfirewall reset': 'Windows 重置防火墙',
        'tcpkill': '阻断网络连接',

        'kill -9 -1': '终止所有进程',
        'taskkill /F /IM *': 'Windows 终止所有进程',

        '/etc/passwd': 'Linux 用户配置文件',
        '/etc/shadow': 'Linux 密码文件',
        'C:\\Windows\\System32': 'Windows 系统目录',
        'HKEY_LOCAL_MACHINE': 'Windows 注册表',
        'reg delete HKLM': '删除注册表项',

        'apt-get remove --purge': '彻底删除包',
        'yum erase': '删除包',
        'dnf remove': '删除包',
        'pacman -Rns': 'Arch 删除包',
        'pip uninstall -y': '卸载 Python 包',
        'npm uninstall -g': '卸载全局 npm 包',
    }

    # windows
    if system == 'windows':
        windows_dangerous = {
            'del /s /q': '静默删除文件',
            'rmdir /s /q': '静默删除目录',
            'fsutil': '文件系统工具（可能破坏数据）',
            'diskpart': '磁盘分区工具',
            'bcdedit /delete': '删除启动配置',
            'sfc /scannow': '系统文件检查（可能影响系统）',
            'cipher /w': '擦除空闲空间',
            'shutdown /s /t 0': '立即关机',
            'shutdown /r /t 0': '立即重启',
        }
        dangerous_patterns.update(windows_dangerous)

    # linux/mac
    elif system in ['linux', 'darwin']:
        unix_dangerous = {
            'sudo su -': '获取 root shell',
            'passwd -d': '删除用户密码',
            'userdel -r': '删除用户及家目录',
            'vigr': '编辑组文件',
            'vipw': '编辑密码文件',
            'update-rc.d': '修改启动服务',
            'systemctl disable': '禁用系统服务',
            'mount -o remount,ro /': '重新挂载为只读',
            'umount /': '卸载根目录',
        }
        dangerous_patterns.update(unix_dangerous)

    # 检查是否包含危险模式
    for pattern, reason in dangerous_patterns.items():
        if pattern.lower() in command_lower:
            return True, f"检测到危险命令：{pattern}（{reason}）"

    # 检查是否有重定向到设备文件
    device_patterns = [
        r'>\s*/dev/[hs]d[a-z]',
        r'>\s*/dev/sd[a-z]',
        r'>\s*\\\\.\\PhysicalDrive',
        r'\s+\|\s*tee\s+/dev/',
    ]
    for pattern in device_patterns:
        if re.search(pattern, command):
            return True, "检测到重定向到设备文件"

    # 检查是否尝试提升权限
    if 'sudo' in command_lower and any(x in command_lower for x in ['rm', 'dd', 'mkfs', 'chmod', 'chown']):
        return True, "检测到 sudo 执行危险操作"

    return False, ""

@server.tool
def execute_code(code: str, language: Literal["python", "nodejs", "javascript", "js"] = "python") -> Optional[str]:
    """在沙盒中执行代码"""
    try:
        venv_path = os.path.dirname(sys.executable)
        env = os.environ.copy()
        current_path = env.get('PATH', '')

        # 确保虚拟环境路径在最前面
        if not current_path.startswith(venv_path):
            env['PATH'] = f"{venv_path}:{current_path}"
        skills_dir = os.path.join(os.path.dirname(__file__), 'skills')

        if language == "python":
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False,dir=skills_dir) as f:
                f.write(code)
                temp_file = f.name

            try:
                result = subprocess.run(
                    ["python", temp_file],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )

                logger.info(f"执行{language}代码成功")
                return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
            finally:
                os.unlink(temp_file)

        elif language in ["nodejs", "javascript", "js"]:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, dir=skills_dir) as f:
                f.write(code)
                temp_file = f.name

            try:
                node_cmd = which("node")
                if not node_cmd:
                    logger.error("Error: Node.js 未找到")
                    return "Error: Node.js 未找到"

                result = subprocess.run(
                    [node_cmd, temp_file],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )

                logger.info(f"执行{language}代码成功")
                return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
            finally:
                os.unlink(temp_file)
    except Exception as e:
        logger.error(f"错误执行代码: {str(e)}")
        return f"Error: {str(e)} "


@server.tool
def execute_command(command: Annotated[ str, "系统执行命令"], timeout: int = 30) -> str:
    """在安全的沙盒环境中执行终端命令"""
    is_dangerous, reason = is_dangerous_command(command=command)
    if is_dangerous:
        return f"Error: 安全拦截：{reason}"

    venv_path = os.path.dirname(sys.executable)
    env = os.environ.copy()
    current_path = env.get('PATH', '')

    # 确保虚拟环境路径在最前面
    if not current_path.startswith(venv_path):
        env['PATH'] = f"{venv_path}:{current_path}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),
            env=env,
        )

        return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
    except subprocess.TimeoutExpired:
        return f"Error: Command execution timed out ({timeout} seconds limit)"
    except Exception as e:
        return f"Error: {str(e)}"

@server.tool
def read_skill_file(skill: Annotated[str, "技能文件名称,必须包含文件后缀"]) -> str:
    """
    读取技能文件内容
    ** 如果不确定文件名，请先调用 get_skills_overview 查看完整的文件名列表 **

    Args:
        skill: 技能文件名称，必须包含文件后缀（如: 'Exa.py', 'DateTime.py'）

    """
    skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
    skill_file = os.path.join(skills_dir, skill)
    
    if os.path.exists(skill_file):
        with open(skill_file, 'r', encoding='utf-8') as f:
            logger.info(f"读取技能文件成功: {skill}")
            return f.read()
    else:
        logger.error(f"未找到技能文件: {skill}")
        return f"未找到技能文件: {skill}"


@server.tool
def get_skills_overview() -> str:
    """获取ai可以技能的使用指南概括"""
    skills_md = ["skills", "Skills", "SKILLS"]
    skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
    skill_file = Any
    for name in skills_md:
        skill_file = os.path.join(skills_dir, f"{name}.md")
        break

    if os.path.exists(skill_file):
        with open(skill_file, 'rb') as f:
            import chardet
            raw_data = f.read(10000)
            result = chardet.detect(raw_data)
            detected_encoding = result.get("encoding", "utf-8")

        with open(skill_file, 'r', encoding=detected_encoding) as f:
            return f.read()
    else:
        return f"技能概括文件没有找到"


if __name__ == "__main__":
    server.run(host="127.0.0.1", port=18080, transport="streamable-http", path="/streamable")
