"""
Scheduler skill 单元测试（4 个顶层函数）

覆盖：
- 4 个函数 happy path（mock requests.post / get / delete）
- session_id 透传（空 vs 非空 → URL/JSON 是否带）
- 错误响应 400 / 404 / 503 → 统一 `[类型] 描述 | 建议` 文本
- `CHATME_BACKEND_HOST` / `CHATME_BACKEND_PORT` 环境变量覆盖 base URL
- ConnectionError → `[ConnectionError]` 文本
- list 输出包含全 12 位 task_id（不用 8 位前缀）
- 沙盒检测（`_is_sandbox()` 通过 `/.dockerenv` 标记）→ base URL 走 host.docker.internal

测试方式：monkeypatch `requests.post / get / delete`，避免真打后端。
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import skills.Scheduler as scheduler_skill  # noqa: E402
from skills.Scheduler import (  # noqa: E402
    cancel_scheduled_task,
    create_scheduled_task,
    list_scheduled_tasks,
    run_scheduled_task_now,
)


# =========================================================================
# fixture：拦截 requests，让 4 个函数走可控的 mock 响应
# =========================================================================


@pytest.fixture
def mock_http(monkeypatch):
    """
    用 MagicMock 替代 requests.post / get / delete，统一管理：
    - status_code：默认 200
    - json_response：默认 {task_id: 'tid_abcdef012345', tasks: [...]}
    - connection_error：模拟网络异常
    """
    state = {
        "status_code": 200,
        "json_response": {},
        "calls": [],  # [(method, url, json_or_None)]
        "connection_error": None,
    }

    def _make_response():
        resp = MagicMock()
        resp.status_code = state["status_code"]
        resp.json.return_value = state["json_response"]
        return resp

    def _post(url, json=None, timeout=None, **kwargs):
        state["calls"].append(("POST", url, json))
        if state["connection_error"] is not None:
            raise state["connection_error"]
        return _make_response()

    def _get(url, params=None, timeout=None, **kwargs):
        state["calls"].append(("GET", url, params))
        if state["connection_error"] is not None:
            raise state["connection_error"]
        return _make_response()

    def _delete(url, timeout=None, **kwargs):
        state["calls"].append(("DELETE", url, None))
        if state["connection_error"] is not None:
            raise state["connection_error"]
        return _make_response()

    monkeypatch.setattr(scheduler_skill.requests, "post", _post)
    monkeypatch.setattr(scheduler_skill.requests, "get", _get)
    monkeypatch.setattr(scheduler_skill.requests, "delete", _delete)

    return state


# =========================================================================
# 1. create_scheduled_task
# =========================================================================


def test_create_success_returns_task_id_summary(mock_http):
    """完整 payload → 200 → 成功摘要含 task_id + cron + session."""
    mock_http["json_response"] = {"task_id": "tid_abcdef012345"}
    result = create_scheduled_task(
        name="每日销售汇总",
        cron="0 9 * * *",
        prompt="分析昨天的 sales.csv",
        session_id="sid_001",
    )
    assert "Scheduled task" in result
    assert "每日销售汇总" in result
    assert "0 9 * * *" in result
    assert "sid_001" in result

    # 验证 HTTP 请求
    assert len(mock_http["calls"]) == 1
    method, url, payload = mock_http["calls"][0]
    assert method == "POST"
    assert url.endswith("/admin/scheduled-tasks")
    assert payload["name"] == "每日销售汇总"
    assert payload["cron"] == "0 9 * * *"
    assert payload["prompt"] == "分析昨天的 sales.csv"
    assert payload["session_id"] == "sid_001"


def test_create_with_empty_session_id_shows_auto(mock_http):
    """session_id 空 → 透传到后端，response 摘要显示 <auto>。"""
    mock_http["json_response"] = {"task_id": "tid_xyz"}
    result = create_scheduled_task(
        name="测试",
        cron="* * * * *",
        prompt="hi",
    )
    # 摘要里 session 显示为 <auto>
    assert "<auto>" in result
    # payload 里 session_id 是空串
    _, _, payload = mock_http["calls"][0]
    assert payload["session_id"] == ""


def test_create_bad_request_returns_formatted_error(mock_http):
    """400 → [BadRequest] 错误文本。"""
    mock_http["status_code"] = 400
    mock_http["json_response"] = {"detail": "cron expression invalid: foo"}
    result = create_scheduled_task(
        name="测试", cron="invalid", prompt="hi",
    )
    assert "[BadRequest]" in result
    assert "cron expression invalid" in result
    # 应给建议
    assert "5-field" in result or "Asia/Shanghai" in result


# =========================================================================
# 2. list_scheduled_tasks
# =========================================================================


def test_list_empty_returns_no_tasks_message(mock_http):
    """空列表 → 'No scheduled tasks.'"""
    mock_http["json_response"] = {"tasks": []}
    result = list_scheduled_tasks()
    assert result == "No scheduled tasks."


def test_list_returns_full_12_char_task_id(mock_http):
    """list 输出含全 12 位 task_id，不用 8 位前缀。"""
    mock_http["json_response"] = {
        "tasks": [
            {
                "task_id": "tid_aaaa1111",
                "name": "任务A",
                "cron": "0 9 * * *",
                "session_id": "sid_001",
                "enabled": True,
            },
            {
                "task_id": "tid_bbbb2222",
                "name": "任务B",
                "cron": "*/30 * * * *",
                "session_id": "",
                "enabled": False,
            },
        ]
    }
    result = list_scheduled_tasks()
    assert "2 scheduled task(s)" in result
    assert "任务A" in result
    assert "0 9 * * *" in result
    # 全 12 位 task_id（不截断）
    assert "tid_aaaa1111" in result
    assert "tid_bbbb2222" in result
    # 状态字段
    assert "enabled" in result
    assert "disabled" in result
    # 空 session_id 显示 <auto>
    assert "<auto>" in result


def test_list_with_session_id_filter_passes_query(mock_http):
    """session_id 非空 → URL ?session_id=xxx。"""
    mock_http["json_response"] = {"tasks": []}
    list_scheduled_tasks(session_id="sid_001")
    method, url, _ = mock_http["calls"][0]
    assert method == "GET"
    assert "session_id=sid_001" in url


def test_list_not_found_returns_formatted_error(mock_http):
    """404（理论上 list 不会 404，但兜底）→ [NotFound] 文本。"""
    mock_http["status_code"] = 404
    mock_http["json_response"] = {"detail": "not found"}
    result = list_scheduled_tasks()
    assert "[NotFound]" in result


# =========================================================================
# 3. cancel_scheduled_task
# =========================================================================


def test_cancel_success_returns_confirmation(mock_http):
    """200 + 取消成功 → 'Cancelled task <task_id>'。"""
    mock_http["status_code"] = 200
    mock_http["json_response"] = {"ok": True}
    result = cancel_scheduled_task(task_id="tid_abcdef012345")
    assert "Cancelled task" in result
    assert "tid_abcdef012345" in result
    # DELETE 请求打到正确 URL
    method, url, _ = mock_http["calls"][0]
    assert method == "DELETE"
    assert url.endswith("/admin/scheduled-tasks/tid_abcdef012345")


def test_cancel_not_found_returns_formatted_error(mock_http):
    """404 → [NotFound] 错误 + 建议调 list_scheduled_tasks。"""
    mock_http["status_code"] = 404
    mock_http["json_response"] = {"detail": "not found"}
    result = cancel_scheduled_task(task_id="nonexistent")
    assert "[NotFound]" in result
    assert "list_scheduled_tasks" in result


# =========================================================================
# 4. run_scheduled_task_now
# =========================================================================


def test_run_now_success_returns_confirmation(mock_http):
    """200 + 触发成功 → 'Triggered task <id> to run now (next cron unchanged)'。"""
    mock_http["status_code"] = 200
    mock_http["json_response"] = {"ok": True}
    result = run_scheduled_task_now(task_id="tid_abcdef012345")
    assert "Triggered task" in result
    assert "tid_abcdef012345" in result
    assert "next cron unchanged" in result
    # POST .../run 端点
    method, url, _ = mock_http["calls"][0]
    assert method == "POST"
    assert url.endswith("/admin/scheduled-tasks/tid_abcdef012345/run")


def test_run_now_not_found_returns_formatted_error(mock_http):
    """404 → [NotFound] 文本。"""
    mock_http["status_code"] = 404
    mock_http["json_response"] = {"detail": "not found"}
    result = run_scheduled_task_now(task_id="missing")
    assert "[NotFound]" in result


# =========================================================================
# 5. 网络错误
# =========================================================================


def test_create_connection_refused_returns_connection_error(mock_http):
    """requests.ConnectionError → [ConnectionError] 文本，含后端 base URL。"""
    import requests

    mock_http["connection_error"] = requests.exceptions.ConnectionError("refused")
    result = create_scheduled_task(
        name="x", cron="* * * * *", prompt="hi",
    )
    assert "[ConnectionError]" in result
    assert "127.0.0.1:8211" in result or "host.docker.internal:8211" in result


def test_create_timeout_returns_timeout_error(mock_http):
    """requests.Timeout → [Timeout] 文本。"""
    import requests

    mock_http["connection_error"] = requests.exceptions.Timeout("slow")
    result = create_scheduled_task(
        name="x", cron="* * * * *", prompt="hi",
    )
    assert "[Timeout]" in result


# =========================================================================
# 6. 503 scheduler 未启动
# =========================================================================


def test_create_service_unavailable_returns_formatted_error(mock_http):
    """503 → [ServiceUnavailable] + 建议检查后端 lifespan 日志。"""
    mock_http["status_code"] = 503
    mock_http["json_response"] = {"detail": "scheduler not started"}
    result = create_scheduled_task(
        name="x", cron="* * * * *", prompt="hi",
    )
    assert "[ServiceUnavailable]" in result
    assert "lifespan" in result or "scheduler" in result


# =========================================================================
# 7. 环境变量覆盖
# =========================================================================


def test_chatme_backend_host_env_overrides_base(monkeypatch, mock_http):
    """CHATME_BACKEND_HOST / CHATME_BACKEND_PORT env 覆盖 base URL。"""
    monkeypatch.setenv("CHATME_BACKEND_HOST", "my.test.host")
    monkeypatch.setenv("CHATME_BACKEND_PORT", "9999")
    # 强制重算（_backend_base 不缓存，每次调用读 env）
    mock_http["json_response"] = {"task_id": "tid_x"}
    create_scheduled_task(name="x", cron="* * * * *", prompt="hi")
    method, url, _ = mock_http["calls"][0]
    assert "my.test.host:9999" in url


# =========================================================================
# 8. 沙盒检测
# =========================================================================


def test_sandbox_marker_picks_host_docker_internal(monkeypatch):
    """/.dockerenv 存在 → base URL 用 host.docker.internal。"""
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/.dockerenv")
    base = scheduler_skill._backend_base()
    assert "host.docker.internal" in base
    assert ":8211" in base


def test_no_sandbox_marker_picks_loopback(monkeypatch):
    """/.dockerenv 不存在 → base URL 用 127.0.0.1。"""
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    base = scheduler_skill._backend_base()
    assert "127.0.0.1" in base
    assert ":8211" in base


# =========================================================================
# 9. 回归：registry 模块不能因为 from .core import _scheduler 快照了 None
# =========================================================================
# Bug 背景：
#   registry.py 旧实现 `from .core import _scheduler, get_redis` —— 在 lifespan
#   启动前 import 时 _scheduler=None 被快照到 registry 命名空间，后续
#   `core._scheduler = AsyncIOScheduler(...)` 不会同步过来，导致 add_task
#   永远 raise "scheduler 未启动（lifespan 未就绪）"，后端返 503。
#   修复：改用 core.get_scheduler() 函数调用读最新值。
# 本测试：模拟 lifespan 启动后再调 add_task，验证不 raise。
# =========================================================================


def test_registry_add_task_uses_fresh_scheduler_after_lifespan(monkeypatch):
    """lifespan 启动后 registry.add_task 应能看到 core._scheduler，不抛 503 错。"""
    from unittest.mock import MagicMock

    from skills.Scheduler import core as core_module
    from skills.Scheduler import registry

    # 1) Mock 掉 Redis（避免真连）+ Mock AsyncIOScheduler（不让真起事件循环）
    fake_redis = MagicMock()
    monkeypatch.setattr(core_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(registry, "get_redis", lambda: fake_redis)

    fake_scheduler = MagicMock()
    # add_job / get_job 等接口返回 MagicMock，调用不抛
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)

    # 2) 防 handlers 循环 import 副作用 —— 替换 handle_send_message 为 dummy
    import skills.Scheduler.handlers as handlers_module
    monkeypatch.setattr(handlers_module, "handle_send_message", lambda tid: None)

    # 3) 核心断言：模拟 lifespan 启动后再调 add_task，应不抛 "scheduler 未启动"
    try:
        tid = registry.add_task(
            name="回归测试任务",
            cron="0 9 * * *",
            prompt="测试 prompt",
            session_id="sid_regression",
        )
    except RuntimeError as e:
        if "scheduler 未启动" in str(e):
            pytest.fail(
                f"回归 bug：registry 仍在用快照的 _scheduler=None，"
                f"lifespan 启动后 add_task 仍 raise 503 错。err={e}"
            )
        raise

    # 4) 业务断言：add_task 拿到了 task_id + 真的调到了 scheduler.add_job
    assert isinstance(tid, str) and len(tid) == 12
    assert fake_scheduler.add_job.called, "scheduler.add_job 应被调用"


def test_registry_get_scheduler_returns_fresh_value(monkeypatch):
    """get_scheduler() 必须读 core._scheduler 最新值（不能被快照）。"""
    from unittest.mock import MagicMock

    from skills.Scheduler import core as core_module
    from skills.Scheduler import registry

    # 1) 起始状态：_scheduler = None
    monkeypatch.setattr(core_module, "_scheduler", None)
    assert registry.get_scheduler() is None, "未启动时 get_scheduler 应返 None"

    # 2) 模拟 lifespan 启动：_scheduler 被赋值
    fake_scheduler = MagicMock()
    monkeypatch.setattr(core_module, "_scheduler", fake_scheduler)

    # 3) 关键：registry 通过 get_scheduler() 拿到新值，不是快照 None
    assert registry.get_scheduler() is fake_scheduler, (
        "get_scheduler 必须从 core 模块 globals 读最新值，"
        "如果用了 `from .core import _scheduler` 快照，这里会拿到 None"
    )
