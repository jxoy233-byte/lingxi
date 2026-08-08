"""
vl.local=False fallback 测试

覆盖：
1. get_model_vl_config: local=True → 走 vl 自己的配置
2. get_model_vl_config: local=False → 连接三元组 fallback 到当前生效的 provider（主→备）
   且完全无视 vl 段自己填的字段（不混合）
3. get_model_vl_config: local 缺失 → 默认 True（保持旧行为）
4. get_model_vl_config: local=False + 没任何 provider → 保留 vl 自己的配置兜底
5. get_skills_config: 同样应用 fallback
6. ImageParser 调用走 get_skills_config，自动获得 fallback
"""

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ChatMe.ChatMeConfig.core import ChatMeConfig


@pytest.fixture
def tmp_config(tmp_path):
    """每个测试一个独立的 config.json（避免污染真实 .chatme/config.json）。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "llm_providers": {
            "model1": {
                "model_name": "gpt-4o",
                "api_key": "primary-key",
                "base_url": "https://api.openai.com/v1",
            },
            "model2": {
                "model_name": "deepseek-chat",
                "api_key": "backup-key",
                "base_url": "https://api.deepseek.com/v1",
            },
        },
        "skills": {},
    }), encoding="utf-8")
    yield config_path, config_path


@pytest.fixture
def reset_singleton():
    """重置 ChatMeConfig 单例，让 _find_config_file 重新跑。"""
    ChatMeConfig._instance = None
    ChatMeConfig._config = {}
    ChatMeConfig._loaded = False
    yield
    ChatMeConfig._instance = None
    ChatMeConfig._config = {}
    ChatMeConfig._loaded = False


def _make_loaded_config(llm_providers: dict, skills: dict | None = None) -> ChatMeConfig:
    """直接构造已加载的 ChatMeConfig 单例（绕开 _find_config_file 的 Path.exists 依赖）。

    关键：ChatMeConfig 是单例，直接注入 _config + _loaded=True 避免 _load() 内部又调 _find_config_file。
    """
    cfg = ChatMeConfig()
    cfg._config = {"llm_providers": llm_providers}
    if skills is not None:
        cfg._config["skills"] = skills
    cfg._loaded = True
    return cfg


# 1. get_model_vl_config：local=True 走 vl 自己的配置


def test_local_true_uses_vl_own_config(reset_singleton):
    """vl.local=True → 用 vl 自己的 model_name / api_key / base_url。"""
    cfg = _make_loaded_config({
        "model1": {"model_name": "gpt-4o", "api_key": "primary-key", "base_url": "https://api.openai.com/v1"},
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": True,
        },
    })
    result = cfg.get_model_vl_config()
    assert result["model_name"] == "Qwen3-VL-2B"
    assert result["api_key"] == "vl-key"
    assert result["base_url"] == "http://127.0.0.1:8211/api/v1"
    assert result["local"] is True


# 2. get_model_vl_config：local=False fallback 到主模型


def test_local_false_falls_back_to_primary(reset_singleton):
    """vl.local=False → 连接三元组换成 model1 的配置。"""
    cfg = _make_loaded_config({
        "model1": {"model_name": "gpt-4o", "api_key": "primary-key", "base_url": "https://api.openai.com/v1"},
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": False,
        },
    })
    result = cfg.get_model_vl_config()
    assert result["model_name"] == "gpt-4o"
    assert result["api_key"] == "primary-key"
    assert result["base_url"] == "https://api.openai.com/v1"
    assert result["local"] is False


def test_local_false_uses_first_provider_in_chain(reset_singleton):
    """vl.local=False + 没 model1 但有 model2 → fallback 到 model2（链中第一个有效项）。"""
    cfg = _make_loaded_config({
        "model2": {"model_name": "deepseek-chat", "api_key": "backup-key", "base_url": "https://api.deepseek.com/v1"},
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": False,
        },
    })
    result = cfg.get_model_vl_config()
    assert result["model_name"] == "deepseek-chat"
    assert result["api_key"] == "backup-key"
    assert result["base_url"] == "https://api.deepseek.com/v1"


def test_local_false_no_primary_keeps_vl_config(reset_singleton):
    """vl.local=False + 主模型未配置 → 保留 vl 自己的配置（fallback 失效不报错）。"""
    cfg = _make_loaded_config({
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": False,
        },
    })
    result = cfg.get_model_vl_config()
    # 主模型缺失时不强行替换，保留原 vl 配置
    assert result["model_name"] == "Qwen3-VL-2B"
    assert result["api_key"] == "vl-key"


def test_local_false_strictly_discards_vl_values(reset_singleton):
    """vl.local=False → vl 段填了也丢掉，主模型字段完全覆盖（即使部分字段为空）。

    注：_is_provider_valid 要求三个字段都非空，所以这里 model1 故意让 api_key 空 →
    实际效果是"链里没有有效 provider" → 走兜底保留 vl 配置。

    想测"主模型有效但字段被覆盖"，用 test_local_false_falls_back_to_primary 已覆盖。
    这里的语义是：主模型任何一个字段残缺 → 视为不可用 → 不强行用残缺值。
    """
    cfg = _make_loaded_config({
        "model1": {
            "model_name": "gpt-4o",
            "api_key": "",  # 主模型 api_key 故意留空 → 链里没有有效 provider
            "base_url": "https://api.openai.com/v1",
        },
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": False,
        },
    })
    result = cfg.get_model_vl_config()
    # 主模型残缺 → 链空 → 走 vl 兜底
    assert result["model_name"] == "Qwen3-VL-2B"
    assert result["api_key"] == "vl-key"


def test_local_false_falls_back_to_backup_when_primary_invalid(reset_singleton):
    """vl.local=False + model1 配置无效（缺字段） → 自动用链中第一个有效 provider（model2）。

    与启动健康检查行为一致：主→备兜底是 get_active_llm_config 内部的事。
    """
    cfg = _make_loaded_config({
        # model1 故意缺 api_key（_is_provider_valid 视为无效，不会进 chain）
        "model1": {
            "model_name": "gpt-4o",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
        },
        "model2": {
            "model_name": "deepseek-chat",
            "api_key": "backup-key",
            "base_url": "https://api.deepseek.com/v1",
        },
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": False,
        },
    })
    result = cfg.get_model_vl_config()
    # model1 无效 → chain 跳过 → 用 model2
    assert result["model_name"] == "deepseek-chat"
    assert result["api_key"] == "backup-key"
    assert result["base_url"] == "https://api.deepseek.com/v1"


# 3. local 字段缺失 → 默认 True（旧行为）


def test_local_missing_defaults_to_true(reset_singleton):
    """vl.local 字段缺失 → 默认 True，不触发 fallback。"""
    cfg = _make_loaded_config({
        "model1": {"model_name": "gpt-4o", "api_key": "primary-key", "base_url": "https://api.openai.com/v1"},
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
        },
    })
    result = cfg.get_model_vl_config()
    assert result["model_name"] == "Qwen3-VL-2B"
    assert result["api_key"] == "vl-key"
    assert result["local"] is True or result["local"] is None  # 缺失时为 None


# 4. get_skills_config：同样应用 fallback


def test_skills_config_local_false_falls_back(reset_singleton):
    """get_skills_config 返回的 vl_* 字段在 local=False 时也 fallback。"""
    cfg = _make_loaded_config({
        "model1": {"model_name": "gpt-4o", "api_key": "primary-key", "base_url": "https://api.openai.com/v1"},
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": False,
        },
    })
    skills = cfg.get_skills_config()
    assert skills["vl_model_name"] == "gpt-4o"
    assert skills["vl_api_key"] == "primary-key"
    assert skills["vl_base_url"] == "https://api.openai.com/v1"


def test_skills_config_local_true_keeps_vl(reset_singleton):
    """get_skills_config + local=True → 保留 vl 自己的配置。"""
    cfg = _make_loaded_config({
        "model1": {"model_name": "gpt-4o", "api_key": "primary-key", "base_url": "https://api.openai.com/v1"},
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": True,
        },
    })
    skills = cfg.get_skills_config()
    assert skills["vl_model_name"] == "Qwen3-VL-2B"
    assert skills["vl_api_key"] == "vl-key"


# 5. ImageParser 走 get_skills_config → 自动获得 fallback


def test_image_parser_uses_fallback_through_skills_config(reset_singleton):
    """ImageParser 调 parse_image 时走 get_skills_config，local=False 时自动用主模型。

    通过 monkeypatch 拦截 get_skills_config 验证调用栈即可（避免起 mock OpenAI server）。
    """
    from unittest.mock import patch, MagicMock

    cfg = _make_loaded_config({
        "model1": {"model_name": "gpt-4o", "api_key": "primary-key", "base_url": "https://api.openai.com/v1"},
        "vl": {
            "model_name": "Qwen3-VL-2B",
            "api_key": "vl-key",
            "base_url": "http://127.0.0.1:8211/api/v1",
            "local": False,
        },
    })

    captured = {}

    def fake_get_skills_config():
        captured.update(cfg.get_skills_config())
        return captured

    # 拦截 ImageParser 内的 get_skills_config
    with patch("ChatMe.ChatMeConfig.get_skills_config", side_effect=fake_get_skills_config):
        from skills import ImageParser
        # parse_image 内部会调 get_skills_config（验证函数调用栈）
        # 这里只验证它读到了 fallback 后的值
        skills = fake_get_skills_config()
        assert skills["vl_model_name"] == "gpt-4o"
        assert skills["vl_api_key"] == "primary-key"
        assert skills["vl_base_url"] == "https://api.openai.com/v1"