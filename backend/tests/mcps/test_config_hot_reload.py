"""
config 热加载单元测试（v0.1.5）

覆盖：
1. _load() mtime 检查：磁盘改了自动重读；没改跳过
2. _load() 文件被外部删除：保留旧 _config，不破坏运行
3. _load() 读失败：保留旧 _config（已加载过的情况）
4. force_reload()：强制下次重读（即使 mtime 没变）
5. save_config()：per-segment restart_required
   - 仅 permissions → restart_required=False, applied=True
   - 仅 skills      → restart_required=False, applied=True
   - 仅 llm_providers → restart_required=True, applied=False
   - 混合（包含 llm_providers）→ restart_required=True
6. save_config() 后立即 get：拿到新值（不依赖磁盘 mtime 检测）
7. force_reload + save_config 后：next get_skills_config 立即返回新 key
8. mtime 精度兜底：force_reload 让写完文件后下一次 get 必然读新值
   （即便 mtime 在某些 fs 上精度只到秒，os.replace 后新 inode mtime 等于旧值）
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ChatMe.ChatMeConfig.core import ChatMeConfig


@pytest.fixture
def reset_singleton():
    """重置 ChatMeConfig 单例（含新加的 _config_file_mtime 字段）"""
    ChatMeConfig._instance = None
    ChatMeConfig._config = {}
    ChatMeConfig._loaded = False
    ChatMeConfig._config_file_mtime = None
    yield
    ChatMeConfig._instance = None
    ChatMeConfig._config = {}
    ChatMeConfig._loaded = False
    ChatMeConfig._config_file_mtime = None


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """写一个真实 config.json 在 tmp_path，monkeypatch 让 _find_config_file 指向它。

    必须 monkeypatch _find_config_file，否则 _find_config_file() 走 Path.cwd() 的 .chatme/config.json
    会污染真实配置或找不到文件。
    """
    config_path = tmp_path / "config.json"
    initial = {
        "llm_providers": {
            "primary": {
                "model_name": "gpt-4o",
                "api_key": "primary-key-old",
                "base_url": "https://api.openai.com/v1",
            }
        },
        "skills": {
            "tavily_api_key": "tavily-old",
            "exa_api_key": "exa-old",
        },
        "permissions": {
            "approval_policy": "default",
            "approved_commands": [],
            "denied_commands": [],
        },
    }
    config_path.write_text(json.dumps(initial), encoding="utf-8")

    monkeypatch.setattr(ChatMeConfig, "_find_config_file", lambda self: config_path)
    return config_path, initial


# =========================================================================
# 1. _load() mtime 检查
# =========================================================================


def test_load_reads_file_when_not_loaded(reset_singleton, config_file):
    """首加载：_loaded=False → 读文件 + 缓存 mtime"""
    config_path, initial = config_file
    cfg = ChatMeConfig()

    # _loaded 还是 False（首加载前）
    assert cfg._loaded is False

    cfg._load()

    assert cfg._loaded is True
    assert cfg._config["skills"]["tavily_api_key"] == "tavily-old"
    # mtime 已缓存
    assert cfg._config_file_mtime == config_path.stat().st_mtime


def test_load_skips_when_mtime_unchanged(reset_singleton, config_file):
    """mtime 没变 → 不重读（最常见路径）"""
    config_path, initial = config_file
    cfg = ChatMeConfig()
    cfg._load()
    cached_mtime = cfg._config_file_mtime

    # 把 _config 改成非法的 sentinel（如果下次 _load 重读，会被新内容覆盖；
    # 如果不重读，sentinel 保留，验证生效）
    cfg._config = {"SENTINEL": True}

    cfg._load()

    # mtime 没变，sentinel 保留
    assert cfg._config == {"SENTINEL": True}
    assert cfg._config_file_mtime == cached_mtime


def test_load_rereads_when_mtime_changes(reset_singleton, config_file):
    """磁盘文件 mtime 变了 → 重读 + 覆盖 _config"""
    config_path, initial = config_file
    cfg = ChatMeConfig()
    cfg._load()
    assert cfg._config["skills"]["tavily_api_key"] == "tavily-old"

    # 外部直接修改文件（模拟 vim 编辑 / 另一个进程写入）
    time.sleep(0.05)  # 确保 mtime 精度足够（fs mtime 只到秒）
    new_data = json.loads(json.dumps(initial))  # 深拷贝
    new_data["skills"]["tavily_api_key"] = "tavily-new"
    config_path.write_text(json.dumps(new_data), encoding="utf-8")

    cfg._load()

    assert cfg._config["skills"]["tavily_api_key"] == "tavily-new"
    # mtime 缓存已更新
    assert cfg._config_file_mtime == config_path.stat().st_mtime


# =========================================================================
# 2. _load() 文件被外部删除
# =========================================================================


def test_load_keeps_existing_config_if_file_deleted_after_load(reset_singleton, config_file):
    """文件已被外部删除（已加载过）→ 保留旧 _config，不破坏运行"""
    config_path, initial = config_file
    cfg = ChatMeConfig()
    cfg._load()
    cached_config = dict(cfg._config)

    # 外部删除文件
    config_path.unlink()

    cfg._load()

    # _config 没被清空
    assert cfg._config == cached_config
    # _loaded 仍为 True（视为内存里的缓存有效）
    assert cfg._loaded is True
    # _config_file_mtime 因为 stat() 抛 OSError → None
    assert cfg._config_file_mtime is None


def test_load_generates_default_when_file_missing_on_first_load(reset_singleton, config_file):
    """首加载 + 文件不存在 → 走 _generate_default_config（与旧行为一致）"""
    config_path, _ = config_file
    # 删除文件后再启动（首加载）
    config_path.unlink()
    ChatMeConfig._instance = None
    ChatMeConfig._config = {}
    ChatMeConfig._loaded = False
    ChatMeConfig._config_file_mtime = None

    cfg = ChatMeConfig()
    cfg._load()

    # 走 _generate_default_config 兜底 → 默认配置被写入
    assert cfg._loaded is True
    assert "app" in cfg._config  # 默认配置有 app 段
    # 文件现在存在（被自动生成）
    assert config_path.exists()


def test_generate_default_includes_per_skill_preapproval(reset_singleton, tmp_path, monkeypatch):
    """_generate_default_config 必须预填 5 个核心 skill 的 per-skill 批准。

    用户首次启动（无 config.json）→ 自动生成的 defaults 应当让
    Tavily / Exa / DataAnalysis / ImageParser / Memory 调用不再弹审批 UI。
    """
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(ChatMeConfig, "_find_config_file", lambda self: config_path)

    cfg = ChatMeConfig()
    cfg._generate_default_config(config_path)

    perms = cfg._config["permissions"]
    assert perms["approval_policy"] == "default"
    patterns = [a["pattern"] for a in perms["approved_commands"]]
    # 5 个 per-skill pattern 必须都在（不写 sandbox= 段 → sandbox + local 两种环境都批准）
    expected_skills = ["Memory", "Tavily", "Exa", "ImageParser", "DataAnalysis"]
    for skill in expected_skills:
        expected_pattern = f"code_fp:lang=python|imp={skill}"
        assert expected_pattern in patterns, (
            f"自动生成的默认配置缺少 {skill} 的预批准 pattern"
        )
    # 所有条目 scope=global
    for entry in perms["approved_commands"]:
        assert entry["scope"] == "global"
        assert entry["reason"]  # 有 reason 说明
    # 没有把 `imp=skills` 写进默认配置（避免通配放行所有 skill）
    assert "code_fp:lang=python|imp=skills" not in patterns
    # 也没有把 `sandbox=0` 写死（避免用户沙盒调用时被误漏）
    for p in patterns:
        assert "|sandbox=0|" not in p, (
            f"per-skill pattern 不应写死 sandbox=0，会漏掉沙盒调用：{p}"
        )


# =========================================================================
# 3. _load() 读失败：保留旧 _config
# =========================================================================


def test_load_keeps_existing_config_on_corrupt_file(reset_singleton, config_file):
    """已加载过 + 文件被破坏 → 保留旧 _config，不抛异常"""
    config_path, initial = config_file
    cfg = ChatMeConfig()
    cfg._load()
    cached_config = dict(cfg._config)

    # 把文件改成非法 JSON
    time.sleep(0.05)
    config_path.write_text("{not valid json", encoding="utf-8")

    cfg._load()  # 不应抛异常

    # 旧 _config 保留（与文件删除场景同款兜底）
    assert cfg._config == cached_config


# =========================================================================
# 4. force_reload()
# =========================================================================


def test_force_reload_marks_next_load_to_reread(reset_singleton, config_file):
    """force_reload() 后 _load() 必然重读（即使 mtime 没变）"""
    config_path, initial = config_file
    cfg = ChatMeConfig()
    cfg._load()
    cfg._config = {"SENTINEL": True}  # 模拟内存被外部 patch

    cfg.force_reload()
    assert cfg._loaded is False
    assert cfg._config_file_mtime is None

    # 下一轮 _load() 必然走磁盘（mtime == None != 当前 mtime）
    cfg._load()

    # SENTINEL 被磁盘内容覆盖
    assert cfg._config != {"SENTINEL": True}
    assert cfg._config["skills"]["tavily_api_key"] == "tavily-old"


# =========================================================================
# 5. save_config() per-segment restart_required
# =========================================================================


def test_save_permissions_only_no_restart(reset_singleton, config_file):
    """只改 permissions → restart_required=False, applied=True, saved_segments=['permissions']"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "permissions": {
            "approval_policy": "yolo",
            "approved_commands": ["ls *"],
        }
    })

    assert result["ok"] is True
    assert result["restart_required"] is False
    assert result["applied"] is True
    assert result["saved_segments"] == ["permissions"]


def test_save_skills_only_no_restart(reset_singleton, config_file):
    """只改 skills → restart_required=False, applied=True, saved_segments=['skills']"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "skills": {
            "tavily_api_key": "tavily-new",
        }
    })

    assert result["ok"] is True
    assert result["restart_required"] is False
    assert result["applied"] is True
    assert result["saved_segments"] == ["skills"]
    # 实际写入文件
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["skills"]["tavily_api_key"] == "tavily-new"


def test_save_skills_empty_api_key_does_not_count(reset_singleton, config_file):
    """skills 段传空 api_key → 当作不修改（不计入 saved_segments）"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "skills": {
            "tavily_api_key": "",   # 空字符串表示不修改
            "exa_api_key": "exa-new",  # 实际改了这个
        }
    })

    assert result["ok"] is True
    assert result["saved_segments"] == ["skills"]  # 仍有有效改动 → 计入
    assert "skills.tavily_api_key" not in result["saved_keys"]
    assert "skills.exa_api_key" in result["saved_keys"]


def test_save_skills_all_empty_api_keys_no_segment(reset_singleton, config_file):
    """skills 段全部空 api_key → saved_segments 不含 skills"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "skills": {
            "tavily_api_key": "",
            "exa_api_key": "",
        }
    })

    assert result["ok"] is True
    assert "skills" not in result["saved_segments"]
    # 没改动 segments → restart_required 兜底 False
    assert result["restart_required"] is False


def test_save_llm_providers_requires_restart(reset_singleton, config_file):
    """只改 llm_providers → restart_required=True, applied=False"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "llm_providers": {
            "primary": {
                "api_key": "primary-key-new",  # 实际改了
            }
        }
    })

    assert result["ok"] is True
    assert result["restart_required"] is True
    assert result["applied"] is False
    assert result["saved_segments"] == ["llm_providers"]


def test_save_llm_providers_empty_api_key_no_segment(reset_singleton, config_file):
    """llm_providers 段全 api_key 空 → 不计入 saved_segments"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "llm_providers": {
            "primary": {
                "api_key": "",  # 空字符串表示不修改
            }
        }
    })

    assert result["ok"] is True
    assert "llm_providers" not in result["saved_segments"]
    assert result["restart_required"] is False


def test_save_mixed_segments_requires_restart(reset_singleton, config_file):
    """permissions + llm_providers 都改 → restart_required=True（按最严的来）"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "permissions": {"approval_policy": "yolo"},
        "llm_providers": {"primary": {"api_key": "new-key"}},
    })

    assert result["restart_required"] is True
    assert result["applied"] is False
    assert set(result["saved_segments"]) == {"permissions", "llm_providers"}


def test_save_permissions_plus_skills_no_restart(reset_singleton, config_file):
    """permissions + skills 都改（都不需要重启）→ restart_required=False"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    result = cfg.save_config({
        "permissions": {"approved_commands": ["ls"]},
        "skills": {"tavily_api_key": "new-key"},
    })

    assert result["restart_required"] is False
    assert result["applied"] is True
    assert set(result["saved_segments"]) == {"permissions", "skills"}


# =========================================================================
# 6. save_config() 后立即 get：拿到新值
# =========================================================================


def test_save_permissions_then_get_returns_new_value(reset_singleton, config_file):
    """save_config({permissions: ...}) → 立即 get_permissions_config() 拿到新值"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    # 保存前
    from ChatMe.ChatMeConfig import get_permissions_config
    assert get_permissions_config()["approval_policy"] == "default"

    # 保存
    cfg.save_config({
        "permissions": {"approval_policy": "yolo"},
    })

    # 保存后立即 get（不重启）→ 拿到新值
    assert get_permissions_config()["approval_policy"] == "yolo"


def test_save_skills_then_get_returns_new_value(reset_singleton, config_file):
    """save_config({skills: ...}) → 立即 get_skills_config() 拿到新 api_key"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    from ChatMe.ChatMeConfig import get_skills_config
    assert get_skills_config()["tavily_api_key"] == "tavily-old"

    cfg.save_config({
        "skills": {"tavily_api_key": "tavily-just-saved"},
    })

    # 立即 get → 拿到新值（不依赖 mtime 检测：force_reload 已保证）
    assert get_skills_config()["tavily_api_key"] == "tavily-just-saved"


# =========================================================================
# 7. force_reload + mtime 精度兜底
# =========================================================================


def test_save_then_get_works_even_when_mtime_resolution_is_coarse(reset_singleton, config_file):
    """fs mtime 精度只到秒、os.replace 后新 inode mtime 等于旧值的极端场景：
    save_config() 内部调 force_reload() → _loaded=False → 下次 _load() 必然重读，
    不依赖 mtime 检测。直接验证调用后单例状态被重置即可。
    """
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    # 写之前 _loaded=True（首加载已生效）
    assert cfg._loaded is True
    assert cfg._config_file_mtime is not None

    cfg.save_config({
        "skills": {"tavily_api_key": "tavily-coarse-fs"},
    })

    # save_config 内部 force_reload() → _loaded=False, _config_file_mtime=None
    # 下次 _load() 必然走磁盘（不再依赖 mtime 检测）
    assert cfg._loaded is False
    assert cfg._config_file_mtime is None

    # get_skills_config() 走 _load() → 读到新内容
    from ChatMe.ChatMeConfig import get_skills_config
    assert get_skills_config()["tavily_api_key"] == "tavily-coarse-fs"


# =========================================================================
# 8. 端到端：覆盖所有白名单字段
# =========================================================================


def test_save_unknown_top_key_rejected(reset_singleton, config_file):
    """白名单外的字段仍按原逻辑拒绝（回归保护）"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    with pytest.raises(ValueError, match="不允许编辑的字段"):
        cfg.save_config({
            "redis": {"checkpointer_url": "redis://hack"},
        })


def test_save_unknown_permission_field_rejected(reset_singleton, config_file):
    """permissions 段不允许的字段仍按原逻辑拒绝"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    with pytest.raises(ValueError, match="permissions 段不允许的字段"):
        cfg.save_config({
            "permissions": {"foo": "bar"},
        })


def test_save_then_get_skills_returns_updated_full_dict(reset_singleton, config_file):
    """end-to-end：改 skills 后 get_skills_config 返回完整 dict（其他字段也正确）"""
    config_path, _ = config_file
    cfg = ChatMeConfig()
    cfg._load()

    cfg.save_config({
        "skills": {"tavily_api_key": "tavily-fresh"},
    })

    from ChatMe.ChatMeConfig import get_skills_config
    skills = get_skills_config()

    assert skills["tavily_api_key"] == "tavily-fresh"
    # 其他字段保留
    assert skills["exa_api_key"] == "exa-old"
    # vl_* 字段走 get_skills_config 也应该存在
    assert "vl_base_url" in skills