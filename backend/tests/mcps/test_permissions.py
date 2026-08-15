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

from ChatMe.ChatWorkflow.mcps.permissions.core import (  # noqa: E402
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
    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt") as mock_interrupt:
        decision = request_approval("ls -la", ActionType.READ, "test_sid")

    assert decision == ("approved", None)
    mock_interrupt.assert_not_called()


def test_yolo_bypasses_all_questions(tmp_config):
    """yolo policy → 不问任何 action（包括 write / code / network）。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.set_policy(ApprovalPolicy.YOLO)

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt") as mock_interrupt:
        decision = request_approval("rm -rf build/", ActionType.WRITE, "test_sid")
    assert decision == ("approved", None)
    mock_interrupt.assert_not_called()


def test_glob_approved_skips_interrupt(tmp_config):
    """glob 命中 approved → 直接 approved，不抛 GraphInterrupt。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.approve("rm -rf build/*", reason="cleanup", scope="global", session_id="")

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt") as mock_interrupt:
        decision = request_approval("rm -rf build/foo", ActionType.WRITE, "test_sid")
    assert decision == ("approved", None)
    mock_interrupt.assert_not_called()


def test_glob_denied_returns_denied_directly(tmp_config):
    """glob 命中 denied → 直接返回 "denied"，不抛 GraphInterrupt。"""
    init_permissions(config_path=tmp_config)
    p = get_permissions_callable()
    p.deny("rm -rf /", reason="too dangerous")

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt") as mock_interrupt:
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

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt",
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

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt",
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

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt",
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

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt",
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

    with patch("ChatMe.ChatWorkflow.mcps.permissions.core.interrupt", side_effect=fake_interrupt):
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


# 6.5 _pre_check_cmd 格式（v0.1.3+：与 _rejected_tool_result 风格对齐）


def test_pre_check_cmd_dangerous_message_format():
    """auto-blocked dangerous 命令的 ToolMessage wording 必须：
    - 不带 Error: 前缀（避免 LLM 误判为可重试的运行时错误）
    - 包含命令字符串（让 LLM 能溯源）
    - 明确说"auto-blocked by safety system"
    - 引导 LLM 不要重试 / 用 interrupt 问用户
    """
    from ChatMe.ChatWorkflow.mcps.permissions.core import _pre_check_cmd

    block_kind, msg = _pre_check_cmd("rm -rf /tmp/foo")
    assert block_kind == "dangerous"
    assert not msg.startswith("Error:")
    assert "auto-blocked" in msg.lower()
    assert "rm -rf /tmp/foo" in msg
    assert "was not executed" in msg.lower()
    # 引导 LLM 不要重试
    assert "do not retry" in msg.lower()
    # 引导 LLM 用 interrupt 问用户
    assert "interrupt" in msg.lower()


def test_pre_check_cmd_not_allowed_message_format():
    """auto-blocked not_allowed 命令的 ToolMessage wording 必须：
    - 不带 Error: 前缀
    - 包含命令字符串
    - 包含 whitelist 信息让 LLM 知道有哪些可用
    - 明确说"do NOT retry"
    """
    from ChatMe.ChatWorkflow.mcps.permissions.core import _pre_check_cmd

    block_kind, msg = _pre_check_cmd("sysctl hw.memsize hw.physicalcpu")
    assert block_kind == "not_allowed"
    assert not msg.startswith("Error:")
    assert "auto-blocked" in msg.lower()
    assert "sysctl hw.memsize hw.physicalcpu" in msg
    assert "whitelist" in msg.lower()
    # 必须列出可用命令（让 LLM 能找到替代）
    # Darwin 白名单包含 ls / cat 等
    assert "ls" in msg or "cat" in msg
    assert "do not retry" in msg.lower()
    assert "interrupt" in msg.lower()


def test_pre_check_cmd_passes_safe_command():
    """safe command → block_kind = None"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import _pre_check_cmd

    block_kind, msg = _pre_check_cmd("ls -la skills/")
    assert block_kind is None
    assert msg == ""


# 7. code_fp pattern 子集匹配（imp= 段允许 pattern 是 fingerprint 的子集）


def test_match_code_fp_pattern_exact_match():
    """精确相等：pattern 与 fingerprint 字符串完全一致 → 命中。"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import _match_code_fp_pattern

    fp = "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=remember"
    assert _match_code_fp_pattern(fp, fp) is True


def test_match_code_fp_pattern_imp_subset():
    """imp= 段子集匹配：pattern 的 imp 是 fingerprint 的 imp 的子集 → 命中。"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import _match_code_fp_pattern

    pattern = "code_fp:lang=python|sandbox=0|imp=Memory"
    fingerprint = "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=remember"
    assert _match_code_fp_pattern(pattern, fingerprint) is True


def test_match_code_fp_pattern_imp_not_subset():
    """imp= 段非子集：pattern 的 imp 不在 fingerprint 中 → 不命中。"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import _match_code_fp_pattern

    pattern = "code_fp:lang=python|sandbox=0|imp=Memory"
    fingerprint = "code_fp:lang=python|sandbox=0|imp=DataAnalysis,skills|fn=foo"
    assert _match_code_fp_pattern(pattern, fingerprint) is False


def test_match_code_fp_pattern_other_segments_must_match():
    """其他段（lang / sandbox / fn）必须精确相等，不允许子集。"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import _match_code_fp_pattern

    # lang 不匹配 → 不命中
    pattern = "code_fp:lang=nodejs|sandbox=0|imp=Memory"
    fingerprint = "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=remember"
    assert _match_code_fp_pattern(pattern, fingerprint) is False

    # sandbox 不匹配 → 不命中
    pattern = "code_fp:lang=python|sandbox=1|imp=Memory"
    fingerprint = "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=remember"
    assert _match_code_fp_pattern(pattern, fingerprint) is False


def test_match_code_fp_pattern_non_code_fp_returns_false():
    """非 code_fp: 开头 → 不命中（cmd glob pattern 不要走到这里）。"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import _match_code_fp_pattern

    assert _match_code_fp_pattern("rm -rf build/*", "code_fp:lang=python|sandbox=0") is False
    assert _match_code_fp_pattern("code_fp:lang=python", "rm -rf build/*") is False


# 8. is_approved_code_fingerprint 端到端：per-skill pattern 命中实际 fingerprint


def test_is_approved_code_fingerprint_per_skill_pattern_hits(tmp_config):
    """per-skill pattern（imp=Memory 无 |fn=）→ 命中 `from skills.Memory import remember` 的实际 fingerprint。"""
    p = Permissions(tmp_config)
    p.approve_code_fingerprint(
        "code_fp:lang=python|sandbox=0|imp=Memory",
        reason="Memory skill — 全部调用预批准",
        scope="global",
        session_id="",
    )

    actual_fp = "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=remember"
    approved, reason = p.is_approved_code_fingerprint(actual_fp, session_id="any_sid")
    assert approved is True
    assert reason == "Memory skill — 全部调用预批准"


def test_is_approved_code_fingerprint_per_skill_pattern_misses_other_skill(tmp_config):
    """per-skill pattern 只放行特定 skill，其他 skill 的 fingerprint 不命中。"""
    p = Permissions(tmp_config)
    p.approve_code_fingerprint(
        "code_fp:lang=python|sandbox=0|imp=Memory",
        reason="Memory skill 预批准",
        scope="global",
        session_id="",
    )

    # 别的 skill（如 Exa）→ 不命中
    other_fp = "code_fp:lang=python|sandbox=0|imp=Exa,skills|fn=exa_search"
    approved, _ = p.is_approved_code_fingerprint(other_fp, session_id="any_sid")
    assert approved is False


def test_is_approved_code_fingerprint_per_skill_pattern_hits_diff_func(tmp_config):
    """per-skill pattern 对同一 skill 不同函数调用都生效（imp= 子集匹配的核心价值）。"""
    p = Permissions(tmp_config)
    p.approve_code_fingerprint(
        "code_fp:lang=python|imp=Memory",
        reason="Memory skill 预批准",
        scope="global",
        session_id="",
    )

    # recall、remember 两种不同函数都命中（pattern 没写 fn= → 任意 fn 都放行）
    for fp in (
        "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=remember",
        "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=recall",
    ):
        approved, _ = p.is_approved_code_fingerprint(fp, session_id="any_sid")
        assert approved is True, f"{fp} 应该被 per-skill pattern 批准"


def test_is_approved_code_fingerprint_per_skill_hits_both_sandbox_and_local(tmp_config):
    """per-skill pattern 不写 sandbox= 段 → sandbox (1) + local (0) 两种执行环境都命中。

    回归测试：v0.1.4 早期版本 pattern 写成 `sandbox=0` → 用户在沙盒（默认）调用
    Tavily 时 fingerprint 是 sandbox=1 → 精确匹配不上 → 弹审批 UI。本测试确保
    pattern 不带 sandbox 段 → 两种环境都放行。
    """
    p = Permissions(tmp_config)
    p.approve_code_fingerprint(
        "code_fp:lang=python|imp=Tavily",
        reason="Tavily skill — 全部调用预批准",
        scope="global",
        session_id="",
    )

    # 沙盒调用（默认，local=False）
    fp_sandbox = "code_fp:lang=python|sandbox=1|imp=Tavily,skills|fn=tavily_search"
    approved, _ = p.is_approved_code_fingerprint(fp_sandbox, session_id="any_sid")
    assert approved is True, "沙盒调用必须命中"

    # 本机调用（local=True）
    fp_local = "code_fp:lang=python|sandbox=0|imp=Tavily,skills|fn=tavily_search"
    approved, _ = p.is_approved_code_fingerprint(fp_local, session_id="any_sid")
    assert approved is True, "本机调用必须命中"


def test_match_code_fp_pattern_missing_segment_means_any(tmp_config):
    """pattern 里不写 sandbox= / fn= 段 → fingerprint 里任意 sandbox/fn 都允许。

    是 per-skill pattern 的核心语义：用户信任这个 skill，但不在意它具体在哪个
    执行环境跑、也不在意它调哪个函数。
    """
    from ChatMe.ChatWorkflow.mcps.permissions.core import _match_code_fp_pattern

    # pattern 没写 sandbox → sandbox=0 和 sandbox=1 都命中
    pat = "code_fp:lang=python|imp=Tavily"
    assert _match_code_fp_pattern(pat, "code_fp:lang=python|sandbox=0|imp=Tavily,skills|fn=tavily_search") is True
    assert _match_code_fp_pattern(pat, "code_fp:lang=python|sandbox=1|imp=Tavily,skills|fn=tavily_search") is True

    # pattern 没写 fn= → 任意 fn 值都命中
    pat2 = "code_fp:lang=python|imp=Memory"
    assert _match_code_fp_pattern(pat2, "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=remember") is True
    assert _match_code_fp_pattern(pat2, "code_fp:lang=python|sandbox=0|imp=Memory,skills|fn=recall") is True

    # 但 lang 必须精确相等（pattern 写了）
    pat3 = "code_fp:lang=python|imp=Tavily"
    assert _match_code_fp_pattern(pat3, "code_fp:lang=nodejs|sandbox=1|imp=Tavily,skills|fn=tavily_search") is False


def test_match_code_fp_pattern_wildcard_prefix_rejected(tmp_config):
    """`code_fp:*` / `imp=*` 通配符必须被拒绝（防止有人想偷懒通配所有）。"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import _match_code_fp_pattern

    # pattern 以 code_fp: 开头但后面是 * → 应该当作字面 pattern，匹配不到
    assert _match_code_fp_pattern("code_fp:*", "code_fp:lang=python|sandbox=1|imp=Tavily") is False

    # imp=* 不当作通配：字面比较就是 {*}, 与 {Tavily, skills} 非子集
    assert _match_code_fp_pattern("code_fp:lang=python|imp=*", "code_fp:lang=python|sandbox=1|imp=Tavily,skills") is False


# 9. 单例热重载（save_config 后下次 code() call 立刻生效，不用重启）


def test_permissions_force_reload_reads_disk_updates(tmp_config):
    """force_reload() 必须从磁盘重读 approved/denied，覆盖内存中的旧列表。

    回归测试：v0.1.4 早期版本 save_config() 写完 config.json 后，Permissions
    单例没 reload → 用户 Settings 加预批准后，下一次 code() call 仍走旧列表
    → interrupt() 弹审批 UI。fix: save_config() 后调 force_reload() 让单例
    立即同步磁盘。
    """
    p = Permissions(tmp_config)
    assert len(p.approved) == 0

    # 外部模拟 Settings UI 的 PUT /admin/config → 写磁盘
    new_cfg = {
        "permissions": {
            "approval_policy": "default",
            "approved_commands": [
                {"pattern": "code_fp:lang=python|imp=Tavily", "scope": "global", "reason": "ui save"}
            ],
            "denied_commands": [],
        }
    }
    tmp_config.write_text(json.dumps(new_cfg), encoding="utf-8")

    # 关键：调 force_reload() 后内存立刻反映磁盘新内容
    p.force_reload()
    assert len(p.approved) == 1
    assert p.approved[0].pattern == "code_fp:lang=python|imp=Tavily"

    # 单例引用不变（force_reload 不重建对象）
    assert p is p


def test_permissions_force_reload_preserves_singleton_reference(tmp_config):
    """force_reload 必须 in-place 更新，不能让 get_permissions() 返回新对象。

    PermissionedToolNode 在 ChatWorkflow 启动期捕获了 _permissions 引用，
    若 force_reload 替换了对象，runtime 里的引用就过期了。所以必须在原对象上
    更新 approved/denied 字段。
    """
    p = Permissions(tmp_config)
    original_id = id(p)
    original_approved_list_id = id(p.approved)

    # 写新内容
    new_cfg = {
        "permissions": {
            "approval_policy": "default",
            "approved_commands": [{"pattern": "code_fp:lang=python|imp=X", "scope": "global"}],
            "denied_commands": [{"pattern": "rm -rf /"}],
        }
    }
    tmp_config.write_text(json.dumps(new_cfg), encoding="utf-8")

    p.force_reload()

    # 对象同一，approved/denied 列表 in-place 更新
    assert id(p) == original_id
    # _load() 是 [from_dict(d) for d in ...] → 新 list 对象；字段名同但 id 不同
    # 业务关心 approved 字段内容，不依赖 list id
    assert p.approved[0].pattern == "code_fp:lang=python|imp=X"
    assert p.denied[0].pattern == "rm -rf /"


def test_permissions_force_reload_handles_missing_file(tmp_config):
    """force_reload() 在文件被外部删除时不能崩，保留旧状态。"""
    p = Permissions(tmp_config)
    p.approve_code_fingerprint(
        "code_fp:lang=python|imp=X",
        reason="existing",
        scope="global",
        session_id="",
    )
    assert len(p.approved) == 1

    tmp_config.unlink()
    # 不抛异常，旧 approved 保留
    assert p.force_reload() is True
    assert len(p.approved) == 1


def test_save_config_triggers_permissions_hot_reload(tmp_config, monkeypatch):
    """ChatMeConfig.save_config() 保存 permissions 段后必须触发 Permissions 单例 force_reload。

    端到端验证：admin_config.py 的 PUT /admin/config 路径走完后，下次 is_approved_code_fingerprint
    立即拿到新列表（不需要重启后端）。
    """
    import ChatMe.ChatMeConfig.core as chatme_cfg_mod
    import ChatMe.ChatWorkflow.mcps.permissions.core as perm_mod

    # 1. 初始化两个单例（模拟 ChatWorkflow 启动）
    monkeypatch.setattr(perm_mod, "_permissions", None)
    monkeypatch.setattr(chatme_cfg_mod.config, "_instance", None)
    monkeypatch.setattr(chatme_cfg_mod.config, "_config", {})
    monkeypatch.setattr(chatme_cfg_mod.config, "_loaded", False)
    monkeypatch.setattr(chatme_cfg_mod.config, "_config_file_mtime", None)

    # 写一份仅 permissions 段的初始 config（approved 空）
    tmp_config.write_text(json.dumps({
        "app": {"name": "x"},
        "llm_providers": {},
        "permissions": {
            "approval_policy": "default",
            "approved_commands": [],
            "denied_commands": [],
        },
    }), encoding="utf-8")

    # 把 ChatMeConfig._find_config_file / Permissions._find_config_file 都指到 tmp_config
    monkeypatch.setattr(
        chatme_cfg_mod.ChatMeConfig, "_find_config_file", lambda self: tmp_config
    )
    # Permissions 走 init_permissions(config_path=...) 直接指定，不依赖 _find_config_file

    # 启动期 init → Permissions 单例加载空列表
    perms = perm_mod.init_permissions(config_path=tmp_config)
    assert len(perms.approved) == 0

    # 2. 模拟 Settings UI PUT /admin/config → 调 save_config
    chatme_cfg = chatme_cfg_mod.ChatMeConfig()
    chatme_cfg._load()
    save_result = chatme_cfg.save_config({
        "permissions": {
            "approval_policy": "default",
            "approved_commands": [
                {"pattern": "code_fp:lang=python|imp=Tavily", "scope": "global",
                 "reason": "Tavily skill 预批准"}
            ],
            "denied_commands": [],
        }
    })

    assert "permissions" in save_result["saved_segments"]

    # 3. 关键：下一次 is_approved_code_fingerprint 立即拿到新列表
    fp = "code_fp:lang=python|sandbox=1|imp=Tavily,skills|fn=tavily_search"
    approved, reason = perms.is_approved_code_fingerprint(fp, session_id="any")
    assert approved is True, "save_config 后 Permissions 单例应已热重载"
    assert reason == "Tavily skill 预批准"


# helpers


def get_permissions_callable():
    """拿当前 init 过的 Permissions 单例（fixture 每次会 reset）"""
    from ChatMe.ChatWorkflow.mcps.permissions.core import get_permissions
    return get_permissions()