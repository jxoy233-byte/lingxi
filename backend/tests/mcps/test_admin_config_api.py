"""
admin/config API 回归测试（v0.1.5）

覆盖：
1. PUT {permissions: {approval_policy: 'yolo'}} → 200 + saved_keys 含 permissions.approval_policy
   （回归 bug：Pydantic v2 ConfigUpdate 没声明 permissions 字段，
    extra="ignore" 默认行为把 permissions 静默丢弃 → payload 为空 → 400）
2. PUT {llm_providers: {model1: {api_key: 'sk-new'}}} → 200 + restart_required=True
3. PUT {skills: {tavily_api_key: 'tvly-new'}} → 200 + restart_required=False
4. PUT {} → 400 "payload 为空"
5. PUT {redis: {...}} → 400 白名单拒绝
6. GET /admin/config → 200 + 密钥脱敏（api_key 是 mask 形式）
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# =========================================================================
# fixture：tmp config.json + monkeypatch _find_config_file
# =========================================================================


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """写一个真实 config.json 到 tmp_path，monkeypatch 让单例的 _find_config_file 指向它。

    必须在每个测试前后重置单例 + mtime 缓存，避免 test_config_hot_reload 用的 fixture
    注入状态污染本测试。
    """
    from ChatMe.ChatMeConfig.core import ChatMeConfig

    config_path = tmp_path / "config.json"
    initial = {
        "llm_providers": {
            "model1": {
                "model_name": "gpt-4o",
                "api_key": "sk-original-primary-key-1234",
                "base_url": "https://api.openai.com/v1",
            },
            "vl": {
                "model_name": "Qwen3-VL-2B",
                "api_key": "sk-original-vl-key-1234",
                "base_url": "http://127.0.0.1:8211/api/v1",
                "local": True,
            },
        },
        "skills": {
            "tavily_api_key": "tvly-original-key-1234",
            "bocha_api_key": "bocha-original-key-1234",
        },
        "permissions": {
            "approval_policy": "default",
            "approved_commands": [],
            "denied_commands": [],
        },
    }
    config_path.write_text(json.dumps(initial), encoding="utf-8")

    # 重置单例
    ChatMeConfig._instance = None
    ChatMeConfig._config = {}
    ChatMeConfig._loaded = False
    ChatMeConfig._config_file_mtime = None
    monkeypatch.setattr(ChatMeConfig, "_find_config_file", lambda self: config_path)

    # 触发一次加载让 _config 填上 tmp 内容
    cfg = ChatMeConfig()
    cfg._load()
    assert cfg._config["permissions"]["approval_policy"] == "default"

    return config_path, initial


@pytest.fixture
def client(tmp_config):
    """FastAPI TestClient with admin router mounted。"""
    # import 在 fixture 里做，避免模块级 import 时 ChatMeConfig 已被
    # 其他 test 残留状态污染
    from fastapi import FastAPI
    from ChatMe.APIRouter.admin_config import router as admin_config_router

    app = FastAPI()
    app.include_router(admin_config_router)
    return TestClient(app)


# =========================================================================
# 1. PUT {permissions: ...} —— 关键回归测试
# =========================================================================


def test_put_permissions_only_yolo_succeeds(client, tmp_config):
    """PUT 仅含 permissions 段 → 200 + saved_segments=['permissions'] + restart_required=False。

    回归 bug：Pydantic v2 ConfigUpdate 没声明 permissions 字段，extra="ignore"
    静默丢弃，payload 退化为空 → 400 "payload 为空"。
    """
    config_path, _ = tmp_config

    resp = client.put("/admin/config", json={"permissions": {"approval_policy": "yolo"}})

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["ok"] is True
    assert "permissions.approval_policy" in body["saved_keys"]
    assert body["saved_segments"] == ["permissions"]
    assert body["restart_required"] is False
    assert body["applied"] is True

    # 实际写入文件
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["permissions"]["approval_policy"] == "yolo"


def test_put_permissions_approved_commands_succeeds(client, tmp_config):
    """PUT permissions.approved_commands 列表 → 200 + 写入磁盘。"""
    config_path, _ = tmp_config

    resp = client.put(
        "/admin/config",
        json={"permissions": {"approved_commands": [{"pattern": "ls *", "scope": "global", "approved_at": "2026-01-01"}]}},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "permissions.approved_commands" in body["saved_keys"]
    assert body["restart_required"] is False

    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert len(on_disk["permissions"]["approved_commands"]) == 1
    assert on_disk["permissions"]["approved_commands"][0]["pattern"] == "ls *"


def test_put_permissions_invalid_policy_returns_400(client, tmp_config):
    """approval_policy 非 default/yolo → 400 ValueError。"""
    resp = client.put("/admin/config", json={"permissions": {"approval_policy": "evil"}})
    assert resp.status_code == 400
    assert "approval_policy" in resp.json()["detail"]


# =========================================================================
# 2. PUT {llm_providers: ...} —— restart_required=True
# =========================================================================


def test_put_llm_providers_only_requires_restart(client, tmp_config):
    """只改 llm_providers → restart_required=True, applied=False。"""
    config_path, _ = tmp_config

    resp = client.put(
        "/admin/config",
        json={"llm_providers": {"model1": {"api_key": "sk-NEW-PRIMARY-KEY"}}},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["restart_required"] is True
    assert body["applied"] is False
    assert body["saved_segments"] == ["llm_providers"]
    assert "llm_providers.model1.api_key" in body["saved_keys"]

    # 实际写盘
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["llm_providers"]["model1"]["api_key"] == "sk-NEW-PRIMARY-KEY"


def test_put_llm_providers_empty_api_key_does_not_count(client, tmp_config):
    """llm_providers 段全 api_key 空 → saved_segments 不含 llm_providers。"""
    resp = client.put(
        "/admin/config",
        json={"llm_providers": {"model1": {"api_key": ""}}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "llm_providers" not in body["saved_segments"]
    assert body["restart_required"] is False


# =========================================================================
# 3. PUT {skills: ...} —— 热加载段
# =========================================================================


def test_put_skills_only_no_restart(client, tmp_config):
    """只改 skills.api_key → restart_required=False, applied=True。"""
    config_path, _ = tmp_config

    resp = client.put(
        "/admin/config",
        json={"skills": {"tavily_api_key": "tvly-NEW-KEY"}},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["restart_required"] is False
    assert body["applied"] is True
    assert body["saved_segments"] == ["skills"]

    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["skills"]["tavily_api_key"] == "tvly-NEW-KEY"


# =========================================================================
# 4. PUT {} → 400
# =========================================================================


def test_put_empty_payload_returns_400(client, tmp_config):
    """空 payload → 400 'payload 为空'。"""
    resp = client.put("/admin/config", json={})
    assert resp.status_code == 400
    assert "payload 为空" in resp.json()["detail"]


# =========================================================================
# 5. PUT 含白名单外字段 → 400
# =========================================================================


def test_put_unknown_top_key_returns_422(client, tmp_config):
    """白名单外的字段（如 redis）→ 422（Pydantic extra="forbid" 拒绝）。

    比"payload 为空"更清晰：用户能直接看到是哪个字段被吃。
    """
    resp = client.put(
        "/admin/config",
        json={"redis": {"checkpointer_url": "redis://hack"}},
    )
    assert resp.status_code == 422
    # Pydantic 错误体里含未知字段名
    assert "redis" in resp.text


# =========================================================================
# 6. GET /admin/config —— 密钥脱敏
# =========================================================================


def test_get_config_masks_api_keys(client, tmp_config):
    """GET 返回的 api_key 必须是脱敏形式（不是真值）。"""
    resp = client.get("/admin/config")
    assert resp.status_code == 200
    cfg = resp.json()["config"]

    # llm_providers.*.api_key 是 mask 形式：原值 'sk-original-primary-key-1234' (28 chars)
    # mask 形式 = 前 4 + N 个 * + 后 4 = 'sk-original-...-1234' 类似
    # 这里只验证不含完整原文（防泄漏）+ 是字符串
    masked_key = cfg["llm_providers"]["model1"]["api_key"]
    assert "sk-original-primary-key-1234" not in masked_key  # 不能泄漏完整原文
    assert "*" in masked_key  # 必须有遮蔽

    # skills.*_api_key 同样脱敏
    masked_tavily = cfg["skills"]["tavily_api_key"]
    assert "tvly-original-key-1234" not in masked_tavily
    assert "*" in masked_tavily

    # permissions 段原样返回（不含密钥）
    assert cfg["permissions"]["approval_policy"] == "default"


def test_get_config_includes_permissions_section(client, tmp_config):
    """GET 返回必须含 permissions 段（前端能编辑）。"""
    resp = client.get("/admin/config")
    assert resp.status_code == 200
    cfg = resp.json()["config"]
    assert "permissions" in cfg
    assert "approval_policy" in cfg["permissions"]
    assert "approved_commands" in cfg["permissions"]
    assert "denied_commands" in cfg["permissions"]
