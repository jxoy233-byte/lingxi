"""
智能体的底层自带的核心工具能力

FASTMCP 实现

tips:
每个tool函数构建都需要带上session_id参数
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from shutil import which
from typing import Annotated, Literal, Optional

import redis
from fastmcp import FastMCP
import subprocess
import tempfile
import os
import platform
import re
import sys
import signal

from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.ChatMeConfig import get_redis_checkpointer_url
from ChatMe.ChatWorkflow.mcps.CodeSandboxPool import SandboxPool

server = FastMCP(name="ChatMe Agent Core Skills")

logger = get_logger("mcp_server")

redis_url = get_redis_checkpointer_url()
_redis_client = redis.from_url(redis_url)

# 沙盒容器池
_sandbox_pool = None

def _cleanup_existing_containers():
    """清理残留的沙盒容器（不删除 redis）"""
    try:
        result = subprocess.run(["docker", "ps", "-a"], capture_output=True, text=True)
        container_ids = []
        for line in result.stdout.strip().split("\n"):
            if "chatme-python-sandbox" in line and "chatme-redis" not in line:
                cid = line.split()[0]
                container_ids.append(cid)

        for cid in container_ids:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        if container_ids:
            logger.info(f"已清理残留沙盒容器")
    except Exception as e:
        logger.warning(f"清理残留容器失败: {e}")

def _ensure_redis_running():
    """确保 redis 运行（使用 docker-compose）"""
    try:
        # 切换到项目根目录执行 docker-compose
        project_root = Path(__file__).parent.parent.parent.parent
        subprocess.run(
            ["docker-compose", "up", "-d", "redis"],
            cwd=str(project_root),
            capture_output=True
        )
        logger.info("Redis 服务已就绪")
    except Exception as e:
        logger.warning(f"Redis 启动检查失败: {e}")

def _init_sandbox_pool():
    """初始化沙盒容器池"""
    global _sandbox_pool
    try:
        from ChatMe.ChatWorkflow.mcps.CodeSandboxPool import SandboxPool
        _sandbox_pool = SandboxPool(size=2)
        logger.info("沙盒容器池初始化成功")
    except Exception as e:
        logger.warning(f"沙盒容器池初始化失败: {e}，将使用本地虚拟环境")
        _sandbox_pool = None

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

    # 检查 format 磁盘格式化（仅当作为独立命令 + 跟设备路径时才拦截）
    # 拦截: format c:、format /dev/sda1、format -f
    # 不拦截: cat format.py、python format.py、--format=json、format_string
    if re.search(r'(?:^|[\s;&|])format\s+(?:/dev/|[a-zA-Z]:|--?\w+)', command):
        return True, "检测到危险命令：format（格式化磁盘）"

    # 检查是否尝试提升权限
    if 'sudo' in command_lower and any(x in command_lower for x in ['rm', 'dd', 'mkfs', 'chmod', 'chown']):
        return True, "检测到 sudo 执行危险操作"

    return False, ""


def _is_script_command(command: str) -> tuple[bool, str]:
    """
    检测命令是否为脚本执行（Python / Node.js / Ruby / PHP / Perl 等）
    返回：(是否为脚本执行, 脚本语言名称)
    """
    script_patterns = [
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
        ("Ruby", [
            r'^ruby\s+',
            r'^ruby\s+-e\s+',
        ]),
        ("PHP", [
            r'^php\s+',
            r'^php\s+-r\s+',
        ]),
        ("Perl", [
            r'^perl\s+',
            r'^perl\s+-e\s+',
        ]),
    ]

    for lang, patterns in script_patterns:
        if any(re.search(p, command) for p in patterns):
            return True, lang
    return False, ""


_ALLOWED_COMMANDS_UNIX = {
    "ls", "cd", "pwd", "which",
    "cat", "head", "tail", "grep", "wc",
    "cp", "mv", "mkdir", "rm", "find", "sed",
    "awk", "sort", "echo", "touch", "diff", "tar", "gzip",
    "curl",
}

_ALLOWED_COMMANDS_WIN = {
    "dir", "cd",
    "type", "more", "findstr", "fc",
    "copy", "move", "mkdir", "del", "rmdir", "dir",
    "sort",
    "curl",
}


def _is_allowed_command(command: str) -> tuple[bool, str]:
    """
    检测命令是否为当前平台白名单中的命令。
    返回：(是否允许, 不允许的原因)
    """
    system = platform.system().lower()
    allowed = _ALLOWED_COMMANDS_WIN if system == "windows" else _ALLOWED_COMMANDS_UNIX

    first_token = command.strip().split()[0].strip('"\'|;$<>')
    main_cmd = first_token.split("/")[-1]

    if main_cmd in allowed:
        return True, ""

    return False, f"命令「{main_cmd}」不在允许列表中，请使用白名单内的命令"


def _execute_code_in_local(code: str, language: str) -> str:
    """本地虚拟环境执行"""
    project_root = Path.cwd()
    skills_dir = project_root / "skills"

    venv_candidates = [
        project_root / ".venv",
        project_root / "venv",
        project_root.parent / ".venv",
        project_root.parent / "venv",
    ]

    venv_python = None
    for venv in venv_candidates:
        if (venv / "bin" / "python").exists():
            venv_python = str(venv / "bin" / "python")
            break
        elif (venv / "Scripts" / "python.exe").exists():
            venv_python = str(venv / "Scripts" / "python.exe")
            break

    if not venv_python:
        venv_python = sys.executable

    env = os.environ.copy()
    current_path = env.get('PATH', '')
    venv_bin = str(Path(venv_python).parent)
    if not current_path.startswith(venv_bin):
        env['PATH'] = f"{venv_bin}:{current_path}"

    backend_dir = str(project_root)
    current_pythonpath = env.get('PYTHONPATH', '')
    if backend_dir not in current_pythonpath:
        env['PYTHONPATH'] = f"{backend_dir}{os.pathsep}{current_pythonpath}" if current_pythonpath else backend_dir

    suffix = ".py" if language == "python" else ".js"

    with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, dir=skills_dir) as f:
        f.write(code)
        temp_file = f.name

    try:
        if language == "python":
            result = subprocess.run(
                [venv_python, temp_file],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
        else:
            node_cmd = which("node")
            if not node_cmd:
                return "Error: Node.js 未找到"
            result = subprocess.run(
                [node_cmd, temp_file],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )

        return f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
    finally:
        os.unlink(temp_file)

@server.tool
def execute_code(code: str, language: Literal["python", "nodejs", "javascript", "js"] = "python", use_sandbox: bool = False, session_id: str = "") -> Optional[str]:
    """
    执行代码（默认本地 venv，沙盒仅用于不可信代码）

    Args:
        code: 要执行的代码
        language: 语言类型
        use_sandbox: 是否使用沙盒（默认 False）。仅当 AI 判断代码不可信时才设 True
        session_id: 会话 ID
    """
    # AI 判断代码不安全 → 沙盒执行
    if use_sandbox and _sandbox_pool is not None:
        logger.debug(f"会话 {session_id} 使用沙盒容器执行代码")
        return _sandbox_pool.execute(code, language)

    # 沙盒池未初始化但 AI 想要沙盒 → 降级到本地
    if use_sandbox and _sandbox_pool is None:
        logger.warning(f"会话 {session_id} 请求沙盒但沙盒池未初始化，降级到本地 venv")

    # 默认：本地 venv 执行（host 视角，可访问文件系统 + 导入后端模块）
    return _execute_code_in_local(code, language)

@server.tool
def execute_command(command: Annotated[ str, "系统执行命令"], timeout: int = 30, session_id: str="") -> str:
    """在安全的沙盒环境中执行终端命令"""
    is_dangerous, reason = is_dangerous_command(command=command)
    if is_dangerous:
        logger.warning(f"会话{session_id}中危险命令,已安全拦截")
        return f"Error: 安全拦截：{reason}"

    # 检测脚本执行
    is_script, script_lang = _is_script_command(command)
    if is_script:
        logger.warning(f"会话{session_id}尝试用 execute_command 执行{script_lang}")
        return f"Error: execute_command 不能执行{script_lang}脚本，请使用 execute_code 工具"

    # 白名单检查
    is_allowed, allow_reason = _is_allowed_command(command)
    if not is_allowed:
        logger.warning(f"会话{session_id}中非白名单命令: {allow_reason}")
        return f"Error: {allow_reason}"

    # 向上查找项目根目录的虚拟环境
    project_root = Path.cwd()
    venv_candidates = [
        project_root / ".venv",
        project_root / "venv",
        project_root.parent / ".venv",
        project_root.parent / "venv",
    ]

    venv_path = None
    for venv in venv_candidates:
        if venv.exists() and (venv / "bin" / "python").exists():
            venv_path = str(venv / "bin")
            break
        elif venv.exists() and (venv / "Scripts" / "python.exe").exists():
            venv_path = str(venv / "Scripts")
            break

    env = os.environ.copy()
    current_path = env.get('PATH', '')

    # 确保虚拟环境路径在最前面
    if venv_path and not current_path.startswith(venv_path):
        env['PATH'] = f"{venv_path}:{current_path}"

    # 添加 backend 目录到 PYTHONPATH，使 ChatMe 包可以正确导入
    backend_dir = str(project_root)
    current_pythonpath = env.get('PYTHONPATH', '')
    if backend_dir not in current_pythonpath:
        env['PYTHONPATH'] = f"{backend_dir}{os.pathsep}{current_pythonpath}" if current_pythonpath else backend_dir

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(project_root),
            env=env,
        )

        output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}"
        logger.info(f"会话{session_id}中执行终端命令成功")
        return output
    except subprocess.TimeoutExpired:
        logger.error(f"会话{session_id}中终端命令执行超时")
        return f"Error: Command execution timed out ({timeout} seconds limit)"
    except Exception as e:
        logger.error(f"会话{session_id}中错误执行终端命令")
        return f"Error: {str(e)}"

@server.tool
def interrupt(message: str, session_id: str = ""):
      """
      中断当前对话，向用户询问更多的信息

      Args:
          message: 中断原因/要询问用户的信息
          session_id: 额外参数，包含 session_id
      """
      if not session_id:
          logger.warning(f"interrupt 工具调用缺少 session_id 参数")
          return "Error: 缺少 session_id 参数"

      try:
          _redis_client.hset(f"interrupt:{session_id}", mapping={
              "reason": message,
          })

          logger.debug(f"会话 {session_id} 触发中断: {message}")
          return f"已触发中断，等待用户输入: {message}"
      except Exception as e:
          logger.error(f"会话 {session_id} 中断操作失败")
          return f"中断失败: {str(e)}"


@server.tool
def get_current_datetime(session_id: str = "") -> str:
    """
    获取当前的日期和时间（自动使用本机时区）

    Returns:
        JSON 格式：datetime（格式化时间）、weekday（星期几，中英文）
    """
    now = datetime.now().astimezone()

    import json
    result = {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday_en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][now.weekday()]
    }

    logger.debug(f"会话{session_id}中获取当前时间成功")
    return json.dumps(result, ensure_ascii=False)

def _stop_redis():
    """停止 redis 容器（使用 docker-compose）"""
    try:
        project_root = Path(__file__).parent.parent.parent.parent
        subprocess.run(
            ["docker-compose", "stop", "redis"],
            cwd=str(project_root),
            capture_output=True
        )
        logger.info("Redis 服务已停止")
    except Exception as e:
        logger.warning(f"Redis 停止失败: {e}")

def _signal_handler(signum, frame):
    """捕获 Ctrl+C 信号，清理容器后退出"""
    print("\n收到中断信号，正在关闭沙盒容器...")
    if _sandbox_pool:
        _sandbox_pool.shutdown()
    _stop_redis()
    sys.exit(0)

def main():
    # 注册信号处理
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 1. 清理残留沙盒容器
    _cleanup_existing_containers()

    # 2. 确保 redis 运行
    _ensure_redis_running()

    # 3. 初始化沙盒池
    _init_sandbox_pool()

    # 4. 启动 MCP 服务
    server.run(host="127.0.0.1", port=18080, transport="streamable-http", path="/streamable")

if __name__ == "__main__":
    main()