"""
Scheduler 定时任务技能

模块分层（业务核心全在 skills/Scheduler/ 内，与 ChatMe/ 耦合解耦）：
- core.py     SchedulerService 单例 + APScheduler lifecycle + lifespan
- models.py   ScheduledTask dataclass + Redis HASH 序列化
- handlers.py 任务触发时的执行回调（调 chat_service.message_stream）
- registry.py 业务 CRUD（add/list/get/update/delete/run_task_now）—— 唯一权威
- __init__.py 本文件：对外暴露 lifespan / 4 个 LLM 顶层函数

LLM 在 `code()` 工具里按需 import 调用（每个调用必须 print 顶层结果）：
    from skills.Scheduler import create_scheduled_task
    print(create_scheduled_task(name="...", cron="0 9 * * *", prompt="..."))

业务核心（APScheduler + RedisJobStore + send_message handler）保留在本包
core / handlers / registry 子模块里，主进程 FastAPI lifespan 通过
`scheduler_lifespan` 启动；本文件下方的 4 个 LLM 顶层函数是 HTTP 薄壳
（沙盒里不能直接 import 业务核心，走 APIRouter 转发）。

⚠️ 本机限定：core 模块强依赖主进程 Redis + APScheduler。
LLM 在沙盒里 `import skills.Scheduler` 时不应触发 core 加载——
下方 `_LAZY_CORE_SYMBOLS` 用 PEP 562 `__getattr__` 延迟到首次访问
`_scheduler` / `scheduler_lifespan` / `start_scheduler` / `stop_scheduler`
时才 import .core。否则沙盒因缺 redis/apscheduler 立即 ModuleNotFoundError。
"""

# 4 个 LLM 顶层函数（HTTP 薄壳）放在本 __init__.py 末尾
# —— 见下方 `_http_*` / `create_scheduled_task` 等定义

__all__ = [
    # 业务核心（lifespan / 内部符号）—— 仅主进程 FastAPI lifespan 访问
    "_scheduler",
    "scheduler_lifespan",
    "start_scheduler",
    "stop_scheduler",
    # LLM 4 个顶层函数 —— 沙盒 LLM 主要 import 这几个
    "create_scheduled_task",
    "list_scheduled_tasks",
    "cancel_scheduled_task",
    "run_scheduled_task_now",
]


# =========================================================================
# 延迟加载 host-only 符号（PEP 562 module __getattr__，Python 3.7+）
# =========================================================================
# 为什么必须延迟：core.py 顶层 `import redis` / `from apscheduler...` /
# `from fastapi import FastAPI` —— 这些包不在 sandbox/requirements.txt，
# 沙盒 LLM `from skills.Scheduler import create_scheduled_task` 时如果
# 在 __init__.py 顶部 eager import .core，会立即 ModuleNotFoundError。
# 4 个 LLM 函数（HTTP 薄壳）只 import os / requests，跟 core 没关系；
# 只有主进程 main.py / scheduled_tasks.py 需要 host-only 符号，
# 让它们走 __getattr__ 触发 core 加载即可。
_LAZY_CORE_SYMBOLS = frozenset({
    "_scheduler",
    "scheduler_lifespan",
    "start_scheduler",
    "stop_scheduler",
})


def __getattr__(name):
    """PEP 562：模块级属性 fallback。仅 host-only 符号走 .core 延迟加载，
    其他未知名抛 AttributeError 让 Python 走默认行为。
    """
    if name in _LAZY_CORE_SYMBOLS:
        from . import core  # 延迟：只在主进程 lifespan / 调试访问时执行
        value = getattr(core, name)
        # 缓存到模块 globals，让后续访问不走 __getattr__（避免每次 .core 属性查找）
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# =========================================================================
# 4 个 LLM 顶层函数（HTTP 薄壳）
# =========================================================================
# 沙盒里不能 import 主进程的 `core` / `registry`（缺 apscheduler / redis），
# 所以 LLM 通过 `code()` 工具调用这些函数时，全部走 HTTP 调主后端 REST
# 端点（与 DataAnalysis `check_static_file` 同款模式，host.docker.internal）。
# =========================================================================

import os
from typing import Optional

import requests


# =========================================================================
# 配置：HOST / PORT 优先级
# =========================================================================
# 沙盒容器内默认走 host.docker.internal（与 DataAnalysis check_static_file 同款）；
# 本机直接调（不在沙盒里）走 127.0.0.1。CHATME_BACKEND_HOST / CHATME_BACKEND_PORT 可覆盖。
# =========================================================================

_DOCKERENV_MARKER = "/.dockerenv"


def _is_sandbox() -> bool:
    """是否运行在沙盒容器内（通过 /.dockerenv 标记判定，与 DataAnalysis 同款）。"""
    return os.path.exists(_DOCKERENV_MARKER)


def _backend_base() -> str:
    """拼出后端 base URL，schema://host:port，无尾斜杠。"""
    host = os.getenv(
        "CHATME_BACKEND_HOST",
        "host.docker.internal" if _is_sandbox() else "127.0.0.1",
    )
    port = os.getenv("CHATME_BACKEND_PORT", "8211")
    return f"http://{host}:{port}"


_TIMEOUT = 10  # create 注册 APScheduler job 较慢，10s 兜底


# =========================================================================
# 错误格式化
# =========================================================================


def _format_error(status_code: int, response_body: dict, task_id: str = "") -> str:
    """HTTP 错误响应 → 统一 `[类型] 描述 | 建议` 字符串（AI-friendly）。"""
    # FastAPI HTTPException 用 `detail` 字段
    detail = response_body.get("detail", "") if isinstance(response_body, dict) else str(response_body)
    if status_code == 400:
        return f"[BadRequest] {detail} | 用 5-field Asia/Shanghai TZ, e.g. \"0 9 * * *\""
    if status_code == 404:
        tid_hint = f"task {task_id} not found" if task_id else "task not found"
        return f"[NotFound] {tid_hint} | 调 list_scheduled_tasks 查 task_id"
    if status_code == 503:
        return f"[ServiceUnavailable] {detail} | 检查后端 lifespan 日志"
    return f"[HTTPError {status_code}] {detail} | 未知错误，检查后端日志"


def _format_network_error(exc: Exception) -> str:
    """requests 抛异常（连接拒绝 / 超时等）→ 统一文本。"""
    exc_name = type(exc).__name__
    exc_msg = str(exc)
    base = _backend_base()
    if "Connection" in exc_name or "refused" in exc_msg.lower():
        return f"[ConnectionError] cannot reach ChatMe backend at {base} | 确认后端服务在 :8211 运行"
    if "timeout" in exc_name.lower() or "timeout" in exc_msg.lower():
        return f"[Timeout] {_TIMEOUT}s 内未响应 | 网络较慢或后端无响应，可稍后重试"
    return f"[NetworkError] {exc_name}: {exc_msg} | 检查网络连接和后端服务状态"


def _safe_json(resp: requests.Response) -> dict:
    """解析响应 JSON，失败时返空 dict。"""
    try:
        return resp.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        return {}


# =========================================================================
# 4 个 LLM 顶层函数
# =========================================================================


def create_scheduled_task(name: str, cron: str, prompt: str, session_id: str = "") -> str:
    """创建定时任务。返回 task_id 与 cron 摘要。

    Args:
        name: 任务名（1-100 字符，用户侧栏显示用）
        cron: 5-field cron，Asia/Shanghai 时区，例如 "0 9 * * *"
        prompt: 触发时注入到 session 的用户消息
        session_id: 目标 session。空=触发时自动新建；非空=复用/创建该 sid

    Returns:
        成功：`Scheduled task 'X' (id=abc123456789, cron='0 9 * * *', session='<auto>')`
        失败：`[类型] 描述 | 建议` 错误文本
    """
    url = f"{_backend_base()}/admin/scheduled-tasks"
    payload = {
        "name": name,
        "cron": cron,
        "prompt": prompt,
        "session_id": session_id,
    }
    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return _format_network_error(e)

    if resp.status_code != 200:
        return _format_error(resp.status_code, _safe_json(resp))

    body = _safe_json(resp)
    tid = body.get("task_id", "")
    session_display = session_id if session_id else "<auto>"
    return f"Scheduled task '{name}' (id={tid}, cron='{cron}', session='{session_display}')"


def list_scheduled_tasks(session_id: str = "") -> str:
    """列出 session 下所有任务（session_id=""=全部）。

    Returns:
        多行文本，格式：
        3 scheduled task(s):
          - 每日销售汇总 (id=abc123456789, cron='0 9 * * *', enabled, session='<auto>')
          ...
        空时：`No scheduled tasks.`
    """
    url = f"{_backend_base()}/admin/scheduled-tasks"
    if session_id:
        url += f"?session_id={session_id}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return _format_network_error(e)

    if resp.status_code != 200:
        return _format_error(resp.status_code, _safe_json(resp))

    tasks = _safe_json(resp).get("tasks", [])
    if not tasks:
        return "No scheduled tasks."

    lines = [f"{len(tasks)} scheduled task(s):"]
    for t in tasks:
        # 全 12 位 task_id 输出（用户可能复制粘贴完整 id）
        tid = t.get("task_id", "")
        state = "enabled" if t.get("enabled") else "disabled"
        sid = t.get("session_id", "") or "<auto>"
        lines.append(
            f"  - {t.get('name', '?')} "
            f"(id={tid}, cron='{t.get('cron', '?')}', {state}, session='{sid}')"
        )
    return "\n".join(lines)


def cancel_scheduled_task(task_id: str) -> str:
    """按 task_id 取消（支持前缀匹配）。返回确认文本。

    Returns:
        成功：`Cancelled task abc123456789`
        失败：`[NotFound] task abc12345 not found | 调 list_scheduled_tasks 查 task_id`
    """
    url = f"{_backend_base()}/admin/scheduled-tasks/{task_id}"
    try:
        resp = requests.delete(url, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return _format_network_error(e)

    if resp.status_code == 404:
        return _format_error(404, _safe_json(resp), task_id=task_id)
    if resp.status_code != 200:
        return _format_error(resp.status_code, _safe_json(resp), task_id=task_id)

    return f"Cancelled task {task_id}"


def run_scheduled_task_now(task_id: str) -> str:
    """立即触发一次（不修改 cron）。返回触发确认。

    Returns:
        成功：`Triggered task abc123456789 to run now (next cron unchanged)`
        失败：`[NotFound] task abc12345 not found | 调 list_scheduled_tasks 查 task_id`
    """
    url = f"{_backend_base()}/admin/scheduled-tasks/{task_id}/run"
    try:
        resp = requests.post(url, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return _format_network_error(e)

    if resp.status_code == 404:
        return _format_error(404, _safe_json(resp), task_id=task_id)
    if resp.status_code != 200:
        return _format_error(resp.status_code, _safe_json(resp), task_id=task_id)

    return f"Triggered task {task_id} to run now (next cron unchanged)"
