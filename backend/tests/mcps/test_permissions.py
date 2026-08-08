"""
permissions 模块单元测试

覆盖：策略 / 命令分类 / glob 匹配 / 持久化 / 3 档决策（mock interrupt）/ 拒绝消息格式
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ChatMe.ChatWorkflow.mcps.permissions import (  # noqa: E402
    ActionType,
    ApprovalPolicy,
    ApprovedCommand,
    DeniedCommand,
    Permissions,
    _classify_command,
    _rejected_tool_result,
    init_permissions,
    request_approval,
    reset_permissions_cache,
)


# fixture：每个测试用独立 tmp config.json


@pytest.fixture
def tmp_config(tmp_path):
    """每个测试一个独立的 config.json（避免污染真实 .chatme/config.json）。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"permissions": {
        "approval_policy": "default",
        "approved_commands": [],
        "denied_commands": [],
    }}), encoding="utf-8")
    reset_permissions_cache()
    yield config_path
    reset_permissions_cache()


# 1. 策略


def test_policy_default_asks_write(tmp_config):
    p = Permissions(tmp_config)
    p.set_policy(ApprovalPolicy.DEFAULT)
    assert p.should_ask("rm -rf build/", ActionType.WRITE) is True
    assert p.should_ask("python script.py", ActionType.CODE) is True
    assert p.should_ask("curl https://example.com", ActionType.NETWORK) is True


def test_policy_default_skips_read(tmp_config):
    p = Permissions(tmp_config)
    p.set_policy(ApprovalPolicy.DEFAULT)
    assert p.should_ask("ls -la", ActionType.READ) is False
    assert p.should_ask("cat foo.txt", ActionType.READ) is False
    assert p.should_ask("grep pattern", ActionType.READ) is False


def test_policy_yolo_never_asks(tmp_config):
    p = Permissions(tmp_config)
    p.set_policy(ApprovalPolicy.YOLO)
    # yolo 不问任何类型
    assert p.should_ask("rm -rf /", ActionType.WRITE) is False
    assert p.should_ask("python script.py", ActionType.CODE) is False
    assert p.should_ask("curl https://example.com", ActionType.NETWORK) is False
    # 注：硬危险在 is_dangerous 阶段拦，不被 policy 覆盖


def test_policy_invalid_falls_back_to_default(tmp_config):
    """非法 policy 值加载时回退到 default（防御 config.json 写坏）。"""
    bad_config = tmp_config
    bad_config.write_text(json.dumps({"permissions": {
        "approval_policy": "evil_mode",
        "approved_commands": [],
        "denied_commands": [],
    }}), encoding="utf-8")
    p = Permissions(bad_config)
    assert p.policy == ApprovalPolicy.DEFAULT


# 2. 命令分类


@pytest.mark.parametrize("cmd,action", [
    ("ls -la", ActionType.READ),
    ("cat foo.txt", ActionType.READ),
    ("head -n 5 file", ActionType.READ),
    ("grep -r pattern .", ActionType.READ),
    ("pwd", ActionType.READ),
    ("find . -name '*.py'", ActionType.READ),
    ("rm -rf build/", ActionType.WRITE),
    ("cp a b", ActionType.WRITE),
    ("mv a b", ActionType.WRITE),
    ("mkdir -p foo/bar", ActionType.WRITE),
    ("touch foo", ActionType.WRITE),
    ("curl https://example.com", ActionType.NETWORK),
])
def test_classify_command(cmd, action):
    assert _classify_command(cmd) == action


def test_classify_unknown_defaults_to_write():
    """未知命令按 WRITE 处理（保守）。"""
    assert _classify_command("xyz foo bar") == ActionType.WRITE
    assert _classify_command("") == ActionType.WRITE


def test_classify_handles_full_path_token():
    """首 token 带路径（如 /usr/bin/python）也能识别基础名。"""
    assert _classify_command("/usr/bin/rm -rf foo") == ActionType.WRITE
    assert _classify_command("/bin/ls -la") == ActionType.READ


# 3. glob 匹配


def test_glob_match_exact():
    p = Permissions.__new__(Permissions)  # 跳过 _load
    p.config_path = None
    p.policy = ApprovalPolicy.DEFAULT
    p.approved = []
    p.denied = []
    assert p._match_glob("ls -la", "ls -la") is True
    assert p._match_glob("rm -rf build/", "rm -rf build/") is True


def test_glob_match_with_wildcard():
    p = Permissions.__new__(Permissions)
    p.config_path = None
    p.policy = ApprovalPolicy.DEFAULT
    p.approved = []
    p.denied = []
    # `rm -rf build/*` 应该匹配 `rm -rf build/foo` 和 `rm -rf build/foo/bar.txt`
    assert p._match_glob("rm -rf build/foo", "rm -rf build/*") is True
    assert p._match_glob("rm -rf build/foo/bar.txt", "rm -rf build/*") is True
    # 但不匹配 `rm -rf dist/foo`
    assert p._match_glob("rm -rf dist/foo", "rm -rf build/*") is False


def test_is_approved_glob_hit(tmp_config):
    p = Permissions(tmp_config)
    p.approve("rm -rf build/*", reason="cleanup", scope="global", session_id="")
    approved, _ = p.is_approved("rm -rf build/foo", session_id="any_sid")
    assert approved is True
    approved, _ = p.is_approved("rm -rf build/foo/bar.txt", session_id="any_sid")
    assert approved is True
    approved, _ = p.is_approved("rm -rf dist/foo", session_id="any_sid")
    assert approved is False


def test_is_approved_session_scope_only_hits_own_sid(tmp_config):
    p = Permissions(tmp_config)
    p.approve("rm -rf build/*", reason="cleanup", scope="session", session_id="sid_a")
    # sid_a 命中
    approved, _ = p.is_approved("rm -rf build/foo", session_id="sid_a")
    assert approved is True
    # sid_b 不命中
    approved, _ = p.is_approved("rm -rf build/foo", session_id="sid_b")
    assert approved is False


def test_is_denied_glob_hit(tmp_config):
    p = Permissions(tmp_config)
    p.deny("rm -rf /", reason="too dangerous")
    denied, reason = p.is_denied("rm -rf /")
    assert denied is True
    assert reason == "too dangerous"
    # 其他不命中
    denied, _ = p.is_denied("rm -rf build/")
    assert denied is False


# 4. 持久化


def test_approve_persists_to_config(tmp_config):
    """批准 → 写入 config.json，下次同 pattern 自动放行。"""
    p = Permissions(tmp_config)
    p.approve("rm -rf build/foo", reason="cleanup", scope="global", session_id="")

    # 重新加载 → approved 还在
    p2 = Permissions(tmp_config)
    approved, reason = p2.is_approved("rm -rf build/foo", session_id="any")
    assert approved is True
    assert reason == "cleanup"


def test_approve_dedup(tmp_config):
    """同 (pattern, scope) 重复批准 → 只更新 reason + approved_at，不重复添加。"""
    p = Permissions(tmp_config)
    p.approve("rm -rf build/foo", reason="first", scope="global", session_id="")
    p.approve("rm -rf build/foo", reason="second", scope="global", session_id="")

    p2 = Permissions(tmp_config)
    assert len(p2.approved) == 1
    approved, reason = p2.is_approved("rm -rf build/foo", session_id="any")
    assert approved is True
    assert reason == "second"


def test_deny_persists_to_config(tmp_config):
    p = Permissions(tmp_config)
    p.deny("rm -rf /", reason="too dangerous")
    p2 = Permissions(tmp_config)
    denied, _ = p2.is_denied("rm -rf /")
    assert denied is True


def test_policy_persists_to_config(tmp_config):
    p = Permissions(tmp_config)
    p.set_policy(ApprovalPolicy.YOLO)
    p2 = Permissions(tmp_config)
    assert p2.policy == ApprovalPolicy.YOLO
    # 恢复 default
    p2.set_policy(ApprovalPolicy.DEFAULT)


def test_save_config_corrupt_does_not_crash(tmp_config, tmp_path):
    """config.json 损坏时 _load 不抛异常，用 default。"""
    bad_config = tmp_path / "bad.json"
    bad_config.write_text("{not valid json", encoding="utf-8")
    p = Permissions(bad_config)
    assert p.policy == ApprovalPolicy.DEFAULT
    assert p.approved == []
    assert p.denied == []


def test_save_missing_config_creates_default(tmp_path):
    """config.json 不存在时 _load 静默通过，不抛异常。"""
    p = Permissions(tmp_path / "missing.json")
    assert p.policy == ApprovalPolicy.DEFAULT
    assert p.approved == []
    assert p.denied == []


# 5. 3 档决策（mock interrupt 返回值）


def test_request_approval_read_action_returns_approved_directly(tmp_config):
    """READ action + DEFAULT policy → 直接 approved，不抛 GraphInterrupt。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.set_policy(ApprovalPolicy.DEFAULT)

    # interrupt 不应被调用
    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt") as mock_interrupt:
        decision = request_approval("ls -la", ActionType.READ, "test_sid")

    assert decision == ("approved", None)
    mock_interrupt.assert_not_called()


def test_yolo_bypasses_all_questions(tmp_config):
    """yolo policy → 不问任何 action（包括 write / code / network）。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.set_policy(ApprovalPolicy.YOLO)

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt") as mock_interrupt:
        decision = request_approval("rm -rf build/", ActionType.WRITE, "test_sid")
    assert decision == ("approved", None)
    mock_interrupt.assert_not_called()


def test_glob_approved_skips_interrupt(tmp_config):
    """glob 命中 approved → 直接 approved，不抛 GraphInterrupt。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.approve("rm -rf build/*", reason="cleanup", scope="global", session_id="")

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt") as mock_interrupt:
        decision = request_approval("rm -rf build/foo", ActionType.WRITE, "test_sid")
    assert decision == ("approved", None)
    mock_interrupt.assert_not_called()


def test_glob_denied_returns_denied_directly(tmp_config):
    """glob 命中 denied → 直接返回 "denied"，不抛 GraphInterrupt。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.deny("rm -rf /", reason="too dangerous")

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt") as mock_interrupt:
        decision = request_approval("rm -rf /", ActionType.WRITE, "test_sid")
    assert decision == ("denied", None)
    mock_interrupt.assert_not_called()


def test_approve_decision_writes_to_config(tmp_config):
    """用户点"批准" → 调 permissions.approve() 写入 config，下次同 pattern 自动放行。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.approved.clear()
    p.denied.clear()
    p.save()

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt",
               return_value="approve") as mock_interrupt:
        decision = request_approval("rm -rf build/foo", ActionType.WRITE, "test_sid")

    assert decision == ("approved", None)
    mock_interrupt.assert_called_once()  # 确认走到了 interrupt
    # 重新加载确认写入
    p2 = Permissions(tmp_config)
    approved, _ = p2.is_approved("rm -rf build/foo", session_id="any")
    assert approved is True


def test_this_time_only_does_not_write_to_config(tmp_config):
    """用户点"仅本次" → 放行但不写 config，下次同 pattern 还会问。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.approved.clear()
    p.denied.clear()
    p.save()

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt",
               return_value="this-time-only") as mock_interrupt:
        decision = request_approval("rm -rf build/foo", ActionType.WRITE, "test_sid")

    assert decision == ("this-time-only", None)
    mock_interrupt.assert_called_once()
    # 关键：config 没被写入
    p2 = Permissions(tmp_config)
    approved, _ = p2.is_approved("rm -rf build/foo", session_id="test_sid")
    assert approved is False
    denied, _ = p2.is_denied("rm -rf build/foo")
    assert denied is False


def test_deny_decision_does_not_write_to_config(tmp_config):
    """用户点"取消" → 返回 denied，不写 approved / 也不写 denied。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.approved.clear()
    p.denied.clear()
    p.save()

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt",
               return_value="deny") as mock_interrupt:
        decision = request_approval("rm -rf build/foo", ActionType.WRITE, "test_sid")

    assert decision == ("denied", None)
    mock_interrupt.assert_called_once()
    p2 = Permissions(tmp_config)
    assert p2.is_approved("rm -rf build/foo", session_id="test_sid")[0] is False
    assert p2.is_denied("rm -rf build/foo")[0] is False


def test_unknown_decision_defaults_to_deny(tmp_config):
    """未知 decision 值（如 LLM 决策 API 返回异常）按 deny 处理（保守兜底）。"""
    init_permissions(config_path=tmp_config)

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt",
               return_value="totally_made_up_value"):
        decision = request_approval("rm -rf build/foo", ActionType.WRITE, "test_sid")

    assert decision == ("denied", None)


def test_interrupt_payload_contains_metadata(tmp_config):
    """interrupt(value=...) 传的 payload 含 command / action / session_id。

    不含 request_id —— thread_id (= session_id) 已足够定位 pending permission（singleton），
    不需要 sub-id。
    """
    init_permissions(config_path=tmp_config)

    captured = {}
    def fake_interrupt(value):
        captured.update(value)
        return "approve"

    with patch("ChatMe.ChatWorkflow.mcps.permissions.interrupt", side_effect=fake_interrupt):
        request_approval("rm -rf build/foo", ActionType.WRITE, "test_sid")

    assert captured["type"] == "permission_request"
    assert captured["command"] == "rm -rf build/foo"
    assert captured["action"] == "write"
    assert captured["session_id"] == "test_sid"
    # request_id 已被移除（singleton 语义，session_id 已足够定位）
    assert "request_id" not in captured


# 6. _rejected_tool_result 格式


def test_rejected_tool_result_format():
    msg = _rejected_tool_result("cmd", "command=rm -rf build/")
    assert msg.startswith("User rejected this cmd call")
    assert "(command=rm -rf build/)" in msg
    assert "was not executed" in msg
    assert "no side effects occurred" in msg
    # 不应是硬编码 Error: 前缀（避免 LLM 误判为失败并重试）
    assert not msg.startswith("Error:")
    # 引导 LLM 思考替代方案 / 用 interrupt 工具问
    assert "alternative approaches" in msg or "interrupt tool" in msg


def test_rejected_tool_result_code_tool():
    msg = _rejected_tool_result("code", "language=python, code_len=120")
    assert "code call" in msg
    assert "language=python" in msg


# helpers


def get_permissions_callable():
    """拿当前 init 过的 Permissions 单例（fixture 每次会 reset）"""
    from ChatMe.ChatWorkflow.mcps.permissions import get_permissions
    return get_permissions()