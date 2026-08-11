"""
Scheduled tasks REST API 测试（Step 3）

覆盖 6 个端点的 happy path + 4xx/404/503：
- POST   /admin/scheduled-tasks              create
- GET    /admin/scheduled-tasks              list（session_id 过滤）
- GET    /admin/scheduled-tasks/{task_id}    detail（with_history）
- PATCH  /admin/scheduled-tasks/{task_id}    update（enabled / cron）
- DELETE /admin/scheduled-tasks/{task_id}    delete
- POST   /admin/scheduled-tasks/{task_id}/run  trigger now

测试方式：直接用 TestClient 调 router（绕过 lifespan 启动 chat_service）。
scheduler / registry 全用 mock，避免依赖真 Redis / APScheduler。
"""

import json
import sys
from pathlib import Path
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ChatMe.APIRouter.scheduled_tasks import router  # noqa: E402


# =========================================================================
# Test app + mock 装配（直接挂 router；scheduler 用 monkeypatch 替换）
# =========================================================================


@pytest.fixture
def app():
    """FastAPI app 只挂载 scheduled_tasks router（其他 lifespan 不需要）"""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# =========================================================================
# Mock registry / scheduler
# =========================================================================
# 用模块级 monkeypatch 替换 registry 函数 —— router 通过 `from ... import`
# 在模块顶部固定引用，所以 monkeypatch 必须改 ChatMe.APIRouter.scheduled_tasks 模块里的名字


@pytest.fixture
def mock_registry(monkeypatch):
    """
    替换 registry 函数为可追踪的 in-memory 实现

    返回 MockRegistry 实例，测试代码可读它内部状态（如 add_task 调用次数、列表内容）
    """

    class MockRegistry:
        def __init__(self):
            self.tasks: dict[str, dict] = {}  # tid → {name, cron, prompt, session_id, ...}
            self.add_calls: list[dict] = []
            self.update_calls: list[dict] = []
            self.delete_calls: list[str] = []
            self.run_calls: list[str] = []

        def _resolve(self, task_id: str) -> Optional[str]:
            if task_id in self.tasks:
                return task_id
            for tid in self.tasks:
                if tid.startswith(task_id):
                    return tid
            return None

    mock = MockRegistry()

    import ChatMe.APIRouter.scheduled_tasks as api_module

    def _add_task(name, cron, prompt, session_id="", created_by="", task_type="send_message"):
        if not cron:
            raise ValueError(f"cron 表达式非法 {cron!r}")
        tid = f"tid_{len(mock.tasks) + 1:08d}"
        mock.tasks[tid] = {
            "task_id": tid, "name": name, "cron": cron, "prompt": prompt,
            "session_id": session_id, "task_type": task_type,
            "enabled": True, "run_count": 0, "last_run": 0.0,
        }
        mock.add_calls.append({"name": name, "cron": cron, "prompt": prompt, "session_id": session_id})
        return tid

    def _list_tasks(session_id=None):
        result = []
        for tid, t in mock.tasks.items():
            if session_id and t["session_id"] != session_id:
                continue
            result.append({
                "task_id": tid,
                "name": t["name"],
                "cron": t["cron"],
                "prompt_preview": t["prompt"][:80] + ("..." if len(t["prompt"]) > 80 else ""),
                "session_id": t["session_id"],
                "task_type": t["task_type"],
                "enabled": t["enabled"],
                "created_by": "",
                "created_at": 0.0,
                "run_count": t["run_count"],
                "last_run": t["last_run"],
            })
        return result

    def _get_task(task_id, with_history=False):
        tid = mock._resolve(task_id)
        if tid is None:
            return None
        result = {"task": mock.tasks[tid]}
        if with_history:
            result["history"] = []  # 测试只验证字段存在
        return result

    def _update_task(task_id, enabled=None, cron=None):
        tid = mock._resolve(task_id)
        if tid is None:
            return False
        mock.update_calls.append({"task_id": tid, "enabled": enabled, "cron": cron})
        if enabled is not None:
            mock.tasks[tid]["enabled"] = bool(enabled)
        if cron is not None:
            if not cron:
                raise ValueError(f"cron 表达式非法 {cron!r}")
            mock.tasks[tid]["cron"] = cron
        return True

    def _delete_task(task_id):
        tid = mock._resolve(task_id)
        if tid is None:
            return False
        mock.delete_calls.append(tid)
        del mock.tasks[tid]
        return True

    def _run_task_now(task_id):
        tid = mock._resolve(task_id)
        if tid is None:
            return False
        mock.run_calls.append(tid)
        return True

    monkeypatch.setattr(api_module, "add_task", _add_task)
    monkeypatch.setattr(api_module, "list_tasks", _list_tasks)
    monkeypatch.setattr(api_module, "get_task", _get_task)
    monkeypatch.setattr(api_module, "update_task", _update_task)
    monkeypatch.setattr(api_module, "delete_task", _delete_task)
    monkeypatch.setattr(api_module, "run_task_now", _run_task_now)

    return mock


# =========================================================================
# 1. POST /admin/scheduled-tasks
# =========================================================================


def test_create_task_success(client, mock_registry):
    """happy path：合法 payload → 201/200 + task_id"""
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "每日销售报告",
        "cron": "0 9 * * 1-5",
        "prompt": "搜一下今天的销售数据",
        "session_id": "sid_001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["task_id"].startswith("tid_")
    assert len(mock_registry.tasks) == 1
    assert mock_registry.add_calls[0]["name"] == "每日销售报告"
    assert mock_registry.add_calls[0]["cron"] == "0 9 * * 1-5"
    assert mock_registry.add_calls[0]["session_id"] == "sid_001"


def test_create_task_minimal_payload(client, mock_registry):
    """只填必填字段（session_id 默认空）"""
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "测试",
        "cron": "* * * * *",
        "prompt": "hi",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert mock_registry.add_calls[0]["session_id"] == ""  # 默认


def test_create_task_empty_name_422(client, mock_registry):
    """name 空字符串 → 422（Pydantic 校验）"""
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "",
        "cron": "* * * * *",
        "prompt": "hi",
    })
    assert resp.status_code == 422


def test_create_task_missing_required_422(client, mock_registry):
    """缺 name 字段 → 422"""
    resp = client.post("/admin/scheduled-tasks", json={
        "cron": "* * * * *",
        "prompt": "hi",
    })
    assert resp.status_code == 422


def test_create_task_invalid_cron_400(client, mock_registry):
    """registry 抛 ValueError（非法 cron）→ 400"""
    # mock 让 cron 为空字符串时抛 ValueError
    # 实际生产中 registry 也会校验 cron
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "测试",
        "cron": "not a cron",
        "prompt": "hi",
    })
    # mock 当前的 _add_task 只在 cron 为空时抛；这条测试通过 Pydantic 不拒，落到 mock 也接受
    # 为了真正触发 ValueError，需要 mock 校验。改用 monkeypatch 让 cron "not a cron" 抛错
    # 这里改成对 cron="" 的测试
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "测试",
        "cron": "",
        "prompt": "hi",
    })
    assert resp.status_code == 400
    assert "cron" in resp.json()["detail"]


# =========================================================================
# 2. GET /admin/scheduled-tasks
# =========================================================================


def test_list_tasks_empty(client, mock_registry):
    """无任务 → 空列表"""
    resp = client.get("/admin/scheduled-tasks")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "tasks": []}


def test_list_tasks_returns_all(client, mock_registry):
    """不传 session_id → 返回所有任务"""
    # seed 2 个任务
    client.post("/admin/scheduled-tasks", json={"name": "A", "cron": "* * * * *", "prompt": "p1", "session_id": "s1"})
    client.post("/admin/scheduled-tasks", json={"name": "B", "cron": "0 9 * * *", "prompt": "p2", "session_id": "s2"})

    resp = client.get("/admin/scheduled-tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["tasks"]) == 2
    names = {t["name"] for t in data["tasks"]}
    assert names == {"A", "B"}


def test_list_tasks_filters_by_session_id(client, mock_registry):
    """?session_id=s1 → 只返回 s1 的任务"""
    client.post("/admin/scheduled-tasks", json={"name": "A", "cron": "* * * * *", "prompt": "p1", "session_id": "s1"})
    client.post("/admin/scheduled-tasks", json={"name": "B", "cron": "0 9 * * *", "prompt": "p2", "session_id": "s2"})
    client.post("/admin/scheduled-tasks", json={"name": "C", "cron": "*/5 * * * *", "prompt": "p3", "session_id": "s1"})

    resp = client.get("/admin/scheduled-tasks?session_id=s1")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert len(tasks) == 2
    names = {t["name"] for t in tasks}
    assert names == {"A", "C"}


def test_list_tasks_includes_required_fields(client, mock_registry):
    """响应含前端 ScheduledTasksPanel 所需字段"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "0 9 * * *", "prompt": "hi", "session_id": "s1"})
    resp = client.get("/admin/scheduled-tasks")
    task = resp.json()["tasks"][0]
    for field in ("task_id", "name", "cron", "prompt_preview", "session_id", "enabled", "run_count", "last_run"):
        assert field in task, f"缺字段 {field}"


# =========================================================================
# 3. GET /admin/scheduled-tasks/{task_id}
# =========================================================================


def test_get_task_detail_success(client, mock_registry):
    """已知 task_id → 返回 task dict"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "* * * * *", "prompt": "hi", "session_id": "s1"})
    tid = mock_registry.add_calls[0].get("task_id") or list(mock_registry.tasks.keys())[0]

    resp = client.get(f"/admin/scheduled-tasks/{tid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["task"]["name"] == "测试"


def test_get_task_detail_with_history(client, mock_registry):
    """?with_history=true → 返回 history 字段"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "* * * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.get(f"/admin/scheduled-tasks/{tid}?with_history=true")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
    assert isinstance(data["history"], list)


def test_get_task_detail_not_found(client, mock_registry):
    """不存在的 task_id → 404"""
    resp = client.get("/admin/scheduled-tasks/nonexistent")
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


def test_get_task_detail_prefix_match(client, mock_registry):
    """前缀匹配：传短前缀也能命中"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "* * * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.get(f"/admin/scheduled-tasks/{tid[:4]}")
    assert resp.status_code == 200
    assert resp.json()["task"]["task_id"] == tid


# =========================================================================
# 4. PATCH /admin/scheduled-tasks/{task_id}
# =========================================================================


def test_update_task_enabled(client, mock_registry):
    """enabled=false → 任务 enabled 字段更新"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "* * * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.patch(f"/admin/scheduled-tasks/{tid}", json={"enabled": False})
    assert resp.status_code == 200
    assert mock_registry.tasks[tid]["enabled"] is False
    assert mock_registry.update_calls[0] == {"task_id": tid, "enabled": 0, "cron": None}


def test_update_task_cron(client, mock_registry):
    """cron 修改 → 任务 cron 字段更新"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "0 9 * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.patch(f"/admin/scheduled-tasks/{tid}", json={"cron": "*/30 * * * *"})
    assert resp.status_code == 200
    assert mock_registry.tasks[tid]["cron"] == "*/30 * * * *"


def test_update_task_both_fields(client, mock_registry):
    """enabled + cron 同时更新"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "0 9 * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.patch(f"/admin/scheduled-tasks/{tid}", json={"enabled": False, "cron": "* * * * *"})
    assert resp.status_code == 200
    assert mock_registry.tasks[tid]["enabled"] is False
    assert mock_registry.tasks[tid]["cron"] == "* * * * *"


def test_update_task_empty_patch(client, mock_registry):
    """空 PATCH（两个字段都 None）→ 200（noop）"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "0 9 * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.patch(f"/admin/scheduled-tasks/{tid}", json={})
    assert resp.status_code == 200


def test_update_task_not_found(client, mock_registry):
    """不存在的 task_id → 404"""
    resp = client.patch("/admin/scheduled-tasks/nonexistent", json={"enabled": False})
    assert resp.status_code == 404


def test_update_task_invalid_cron_400(client, mock_registry):
    """非法 cron → 400"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "* * * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.patch(f"/admin/scheduled-tasks/{tid}", json={"cron": ""})
    assert resp.status_code == 400


# =========================================================================
# 5. DELETE /admin/scheduled-tasks/{task_id}
# =========================================================================


def test_delete_task_success(client, mock_registry):
    """已知 task_id → 删除成功"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "* * * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.delete(f"/admin/scheduled-tasks/{tid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert tid not in mock_registry.tasks


def test_delete_task_not_found(client, mock_registry):
    """不存在的 task_id → 404"""
    resp = client.delete("/admin/scheduled-tasks/nonexistent")
    assert resp.status_code == 404


# =========================================================================
# 6. POST /admin/scheduled-tasks/{task_id}/run
# =========================================================================


def test_run_task_success(client, mock_registry):
    """已知 task_id → 触发一次"""
    client.post("/admin/scheduled-tasks", json={"name": "测试", "cron": "* * * * *", "prompt": "hi"})
    tid = list(mock_registry.tasks.keys())[0]

    resp = client.post(f"/admin/scheduled-tasks/{tid}/run")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "异步" in resp.json()["msg"]
    assert mock_registry.run_calls == [tid]


def test_run_task_not_found(client, mock_registry):
    """不存在的 task_id → 404"""
    resp = client.post("/admin/scheduled-tasks/nonexistent/run")
    assert resp.status_code == 404


# =========================================================================
# 7. 503（scheduler 未启动）路径
# =========================================================================


def test_create_task_503_when_scheduler_not_started(client, monkeypatch):
    """registry.add_task 抛 RuntimeError（scheduler 未启动）→ 503"""
    import ChatMe.APIRouter.scheduled_tasks as api_module

    def _raise_runtime_error(*args, **kwargs):
        raise RuntimeError("scheduler 未启动（lifespan 未就绪）")

    monkeypatch.setattr(api_module, "add_task", _raise_runtime_error)

    resp = client.post("/admin/scheduled-tasks", json={
        "name": "测试", "cron": "* * * * *", "prompt": "hi",
    })
    assert resp.status_code == 503
    assert "scheduler" in resp.json()["detail"]


def test_list_tasks_503_when_scheduler_not_started(client, monkeypatch):
    """registry.list_tasks 抛 RuntimeError → 503"""
    import ChatMe.APIRouter.scheduled_tasks as api_module

    def _raise_runtime_error(*args, **kwargs):
        raise RuntimeError("scheduler 未启动")

    monkeypatch.setattr(api_module, "list_tasks", _raise_runtime_error)

    resp = client.get("/admin/scheduled-tasks")
    assert resp.status_code == 503


# =========================================================================
# 8. Pydantic payload 校验细节
# =========================================================================


def test_create_task_name_too_long_422(client, mock_registry):
    """name 超过 100 字符 → 422"""
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "x" * 101,
        "cron": "* * * * *",
        "prompt": "hi",
    })
    assert resp.status_code == 422


def test_create_task_empty_prompt_422(client, mock_registry):
    """prompt 为空 → 422"""
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "测试",
        "cron": "* * * * *",
        "prompt": "",
    })
    assert resp.status_code == 422


def test_create_task_extra_fields_ignored(client, mock_registry):
    """Pydantic 默认忽略未知字段（不 422）"""
    resp = client.post("/admin/scheduled-tasks", json={
        "name": "测试",
        "cron": "* * * * *",
        "prompt": "hi",
        "extra_unknown": "value",
    })
    assert resp.status_code == 200