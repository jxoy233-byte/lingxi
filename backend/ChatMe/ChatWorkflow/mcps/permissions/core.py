"""
工具权限审批系统（Human-in-the-Loop）

cmd/code 工具在 platforms 硬过滤之后多一层用户决策：
- default policy：写操作 / code / network 都问；读操作不问；yolo 全放行
- 永久放行：
  - cmd 工具：config.json 持久化 + fnmatch glob 匹配（同 bash 历史 pattern 风格）
  - code 工具：config.json 持久化 + **fingerprint 精确匹配**——按 import 子工具集 +
    调用函数集 + language + sandbox 判定。下次同样结构（参数值任意变）→ 自动放行。
    解决"code 工具每次参数微变就要重新审批"的痛点。详见 `code_fingerprint.py`。
- 永久拒绝：config.json 持久化 + fnmatch glob 匹配
- 决策通过 `Command(resume=decision)` 回到 `interrupt()` 调用点（非 sys_msg 注入）
- 4 档决策：批准 / 仅本次 / 取消 / **告诉 AI 怎么做**（user guidance 塞进 ToolMessage 内容）
"""

from __future__ import annotations

import fnmatch
import json
import os
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import interrupt
from langgraph.errors import GraphBubbleUp
from langchain_core.messages import ToolMessage

from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.paths import get_chatme_dir
from ..tools.code_fingerprint import code_fingerprint

logger = get_logger("permissions")


class ApprovalPolicy(str, Enum):
    """权限审批策略：default 问写操作/code/network；yolo 全放行（硬危险不在 policy 范围）。"""

    DEFAULT = "default"
    YOLO = "yolo"


# approved_commands 里 code_fp pattern 的特殊子集匹配规则：
# - `imp=` 段：pattern 的 imp 集合 ⊆ fingerprint 的 imp 集合 → 命中（用于
#   "该 skill 所有调用"形式的预批准）
# - 其他段（lang/sandbox/fn）：pattern 写了 → 必须在 fingerprint 里精确相等；
#   pattern 没写 → 该段任意 fingerprint 值都允许（典型用法：per-skill pattern
#   不写 sandbox= 段，让 skill 在 sandbox 和 local 两种执行环境下都命中；
#   不写 fn= 段，让 skill 的多个函数都能命中）
# - 不允许 wildcard `code_fp:*` / `imp=*` 通配 — pattern 必须显式列每段
def _match_code_fp_pattern(pattern: str, fingerprint: str) -> bool:
    """code_fp pattern 子集匹配：仅 `imp=` 段子集；其他段要么精确相等要么 pattern 不写。

    三种典型 pattern 形式：
    1. per-skill 预批准（推荐）：
       pattern    = `code_fp:lang=python|imp=Memory`
       fingerprint = `code_fp:lang=python|sandbox=1|imp=Memory,skills|fn=remember`
       → lang 精确相等；imp ⊆；sandbox/fn pattern 没写 → 任意值都允许 → 命中

    2. per-skill 限定本机（罕见）：
       pattern    = `code_fp:lang=python|sandbox=0|imp=Scheduler`
       fingerprint = `code_fp:lang=python|sandbox=0|imp=Scheduler,skills|fn=create_scheduled_task`
       → lang/sandbox 精确相等；imp ⊆ → 命中
       （用于 Scheduler 这种"必须 local=True 才能跑"的 skill）

    3. 全 fingerprint 精确相等（历史行为）：
       pattern = fingerprint = `code_fp:lang=python|sandbox=0|imp=skills|fn=remember`
       → 直接字符串相等，主流程用 `a.pattern == fingerprint` 走，兜底走这里

    Args:
        pattern: approved_commands 条目的 pattern（code_fp: 开头）
        fingerprint: code 工具实际指纹

    Returns:
        True = pattern 命中 fingerprint
    """
    if not pattern.startswith("code_fp:") or not fingerprint.startswith("code_fp:"):
        return False
    # 拆 `|` 段；imp= 段独立处理，其他段精确相等
    pat_parts = pattern.split("|")
    fp_parts = fingerprint.split("|")
    for pp in pat_parts:
        if not pp:
            continue
        if pp.startswith("imp="):
            # imp 段：pattern 的 imp 集合是 fingerprint 的 imp 集合的子集
            pat_imp = set(pp[4:].split(","))
            matched = False
            for fp in fp_parts:
                if fp.startswith("imp="):
                    fp_imp = set(fp[4:].split(","))
                    if pat_imp.issubset(fp_imp):
                        matched = True
                        break
            if not matched:
                return False
        else:
            # 其他段（lang / sandbox / fn）：精确相等
            if pp not in fp_parts:
                return False
    return True


class ActionType(str, Enum):
    """命令分类：read 白名单内默认不问；write/code/network 在 default policy 下都问。"""

    READ = "read"
    WRITE = "write"
    CODE = "code"
    NETWORK = "network"


# 按 main_cmd 首 token 分类命令用
_READ_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "find", "pwd", "which", "where",
    "type", "more", "findstr", "dir", "wc", "awk", "fc", "diff",
}
_WRITE_COMMANDS = {
    "cp", "mv", "mkdir", "rm", "touch", "del", "rmdir", "sort",
    "tar", "gzip", "copy", "move",
}
_NETWORK_COMMANDS = {"curl"}


def _classify_command(command: str) -> ActionType:
    """按命令首 token 分类；未知命令保守按 WRITE 处理。"""
    first = command.strip().split()
    if not first:
        return ActionType.WRITE
    token = first[0].strip('"\'|;$<>').split("/")[-1]
    if token in _READ_COMMANDS:
        return ActionType.READ
    if token in _WRITE_COMMANDS:
        return ActionType.WRITE
    if token in _NETWORK_COMMANDS:
        return ActionType.NETWORK
    return ActionType.WRITE  # 未知命令保守按写操作处理


# =========================================================================
# code 工具语义指纹（fingerprint）—— 见 code_fingerprint.py
# =========================================================================


class ApprovedCommand:
    """永久批准的命令（glob pattern）。scope: global 跨会话 / session 仅当前 sid。"""

    def __init__(
        self,
        pattern: str,
        reason: str = "",
        scope: str = "global",
        approved_at: Optional[str] = None,
        session_id: str = "",
    ):
        self.pattern = pattern
        self.reason = reason
        self.scope = scope
        self.approved_at = approved_at or time.strftime("%Y-%m-%dT%H:%M:%S")
        self.session_id = session_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern": self.pattern,
            "reason": self.reason,
            "scope": self.scope,
            "approved_at": self.approved_at,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ApprovedCommand":
        return cls(
            pattern=d["pattern"],
            reason=d.get("reason", ""),
            scope=d.get("scope", "global"),
            approved_at=d.get("approved_at"),
            session_id=d.get("session_id", ""),
        )


class DeniedCommand:
    """永久拒绝的命令（glob pattern）。"""

    def __init__(
        self,
        pattern: str,
        reason: str = "",
        denied_at: Optional[str] = None,
    ):
        self.pattern = pattern
        self.reason = reason
        self.denied_at = denied_at or time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return {"pattern": self.pattern, "reason": self.reason, "denied_at": self.denied_at}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DeniedCommand":
        return cls(d["pattern"], d.get("reason", ""), d.get("denied_at"))


class Permissions:
    """config.json `permissions` 段加载 / 保存 / 查询。原子写（tmp + os.replace，无 fsync）。"""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.policy: ApprovalPolicy = ApprovalPolicy.DEFAULT
        self.approved: List[ApprovedCommand] = []
        self.denied: List[DeniedCommand] = []
        self._load()

    def _load(self) -> None:
        """从 config.json 读 permissions 段。"""
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                full = json.load(f)
            perms = full.get("permissions", {})
            policy_raw = perms.get("approval_policy", "default")
            self.policy = ApprovalPolicy(policy_raw) if policy_raw in {p.value for p in ApprovalPolicy} else ApprovalPolicy.DEFAULT
            self.approved = [ApprovedCommand.from_dict(d) for d in perms.get("approved_commands", [])]
            self.denied = [DeniedCommand.from_dict(d) for d in perms.get("denied_commands", [])]
        except Exception as e:
            logger.warning(f"permissions 段加载失败: {e}，用 default")
            self.policy = ApprovalPolicy.DEFAULT
            self.approved = []
            self.denied = []

    def force_reload(self) -> bool:
        """强制从磁盘重读 config.json 的 permissions 段，更新内存单例。

        用于 Settings → Save 改完 approved/denied 后，让 PermissionedToolNode
        下一次执行（interrupt gate）立刻拿到新列表，不用重启后端。
        单例引用不变，调用方拿到的还是同一个 Permissions 对象。

        Returns:
            True = 重读成功；False = 文件不存在 / 解析失败（保留旧状态）

        为什么不放在每次 is_approved_code_fingerprint 调用时自动 mtime check：
        - 每次 code() call 都 stat() 磁盘太贵
        - Settings UI 保存是显式触发点（用户点 Save 按钮），在那里 reload 一次
          就够了；外部直接编辑 config.json 的场景属于"知道自己在做什么"，
          用户重启后端即可
        """
        try:
            old_policy = self.policy
            old_approved_count = len(self.approved)
            old_denied_count = len(self.denied)
            self._load()
            if (self.policy != old_policy
                    or len(self.approved) != old_approved_count
                    or len(self.denied) != old_denied_count):
                logger.info(
                    f"permissions 热重载: policy {old_policy.value}→{self.policy.value}, "
                    f"approved {old_approved_count}→{len(self.approved)}, "
                    f"denied {old_denied_count}→{len(self.denied)}"
                )
            return True
        except Exception as e:
            logger.error(f"permissions force_reload 失败: {e}")
            return False

    def save(self) -> None:
        """原子写回 config.json。PID 后缀的 tmp 文件名避免覆盖仓库里的 config.json.tmp 模板。"""
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    full = json.load(f)
            else:
                full = {}

            full["permissions"] = {
                "approval_policy": self.policy.value,
                "approved_commands": [a.to_dict() for a in self.approved],
                "denied_commands": [d.to_dict() for d in self.denied],
            }

            tmp = self.config_path.with_name(f"{self.config_path.name}.{os.getpid()}.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(full, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_path)
        except Exception as e:
            logger.error(f"permissions 写回失败: {e}")

    def set_policy(self, policy: ApprovalPolicy) -> None:
        self.policy = policy
        self.save()

    def classify(self, command: str) -> ActionType:
        return _classify_command(command)

    @staticmethod
    def _match_glob(command: str, pattern: str) -> bool:
        """fnmatch glob 匹配。`rm -rf build/*` 匹配 `rm -rf build/foo/bar.txt`。"""
        return fnmatch.fnmatch(command.strip(), pattern.strip())

    def is_denied(self, command: str) -> Tuple[bool, str]:
        """glob 命中永久拒绝列表？"""
        for d in self.denied:
            if self._match_glob(command, d.pattern):
                return True, d.reason or "permanently denied"
        return False, ""

    def is_approved(self, command: str, session_id: str = "") -> Tuple[bool, str]:
        """glob 命中永久批准列表？scope=global 跨 sid；scope=session 仅当前 sid。"""
        for a in self.approved:
            if a.scope == "global":
                if self._match_glob(command, a.pattern):
                    return True, a.reason or "user previously approved"
            elif a.scope == "session":
                if a.session_id == session_id and self._match_glob(command, a.pattern):
                    return True, a.reason or "user previously approved in this session"
        return False, ""

    def is_approved_code_fingerprint(
        self, fingerprint: str, session_id: str = ""
    ) -> Tuple[bool, str]:
        """code 工具专用：匹配 approved list 里的 code fingerprint。

        匹配规则（详见 `_match_code_fp_pattern`）：
        1. pattern 与 fingerprint 字符串完全相等（历史行为，保留）
        2. pattern 是 code_fp: 形式：
           - `imp=` 段：pattern ⊆ fingerprint
           - 其他段（lang/sandbox/fn）：pattern 写了必须精确相等；pattern 没写任意值都允许
           → 让 per-skill 预批准 pattern 既能在 sandbox 跑也能在 local 跑，
              又能区分不同 skill / 不同函数

        scope=global 跨 sid；scope=session 仅当前 sid。
        """
        if not fingerprint:
            return False, ""
        for a in self.approved:
            if a.scope == "session" and a.session_id != session_id:
                continue
            if a.pattern == fingerprint:
                return True, a.reason or "user previously approved"
            if _match_code_fp_pattern(a.pattern, fingerprint):
                return True, a.reason or "user previously approved"
        return False, ""

    def should_ask(self, command: str, action: ActionType) -> bool:
        """yolo 模式：全放行；default 模式：READ 不问，WRITE/CODE/NETWORK 都问。"""
        if self.policy == ApprovalPolicy.YOLO:
            return False
        if action == ActionType.READ:
            return False
        return True

    def approve(self, command: str, reason: str, scope: str, session_id: str) -> None:
        """写入 approved list。同 (pattern, scope) 已存在时更新 reason + approved_at，不重复添加。"""
        for a in self.approved:
            if a.pattern == command and a.scope == scope:
                a.reason = reason or a.reason
                a.approved_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                self.save()
                return
        self.approved.append(
            ApprovedCommand(
                pattern=command, reason=reason, scope=scope, session_id=session_id
            )
        )
        self.save()

    def approve_code_fingerprint(
        self, fingerprint: str, reason: str, scope: str, session_id: str
    ) -> None:
        """code 工具 fingerprint 专用持久化（与 approve 共用 ApprovedCommand 结构）。

        只在 fingerprint 非空（_code_fingerprint 成功提取）时调。同 (fingerprint, scope)
        已存在时更新 reason + approved_at，不重复添加。
        """
        if not fingerprint:
            return
        for a in self.approved:
            if a.pattern == fingerprint and a.scope == scope:
                a.reason = reason or a.reason
                a.approved_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                self.save()
                return
        self.approved.append(
            ApprovedCommand(
                pattern=fingerprint,
                reason=reason,
                scope=scope,
                session_id=session_id,
            )
        )
        self.save()

    def deny(self, command: str, reason: str) -> None:
        """用户拒绝 → 写入 denied list（去重）。"""
        for d in self.denied:
            if d.pattern == command:
                d.reason = reason or d.reason
                self.save()
                return
        self.denied.append(DeniedCommand(pattern=command, reason=reason))
        self.save()


# =========================================================================
# 模块级单例
# =========================================================================


_permissions: Optional[Permissions] = None


def init_permissions(config_path: Optional[Path] = None) -> Permissions:
    """启动时调一次，加载 config.json `permissions` 段。"""
    global _permissions
    if _permissions is None:
        if config_path is None:
            # 默认 .chatme/config.json（local-first，仿 ChatMeConfig._find_config_file）
            config_path = get_chatme_dir() / "config.json"
        _permissions = Permissions(config_path)
    return _permissions


def get_permissions() -> Permissions:
    """懒加载：第一次调 init_permissions()。"""
    if _permissions is None:
        init_permissions()
    return _permissions


def reset_permissions_cache() -> None:
    """测试用：清空单例，下一次 get_permissions() 重新加载。"""
    global _permissions
    _permissions = None


def request_approval(
    command: str,
    action: ActionType,
    session_id: str,
    tool_call_name: str = "",
    fingerprint: str = "",
    execution_env: str = "sandbox",
) -> Tuple[str, Optional[str]]:
    """同步等用户回复（走官方 `langgraph.types.interrupt` + `Command(resume=...)` 通道）。

    Args:
        command: 审批用的命令串（cmd → 命令体；code → 完整 args JSON 给前端 SSE 显示用）
        action: ActionType 分类
        session_id: thread_id
        tool_call_name: 工具名（"cmd" / "code"）—— 用于 SSE permission_request 事件携带，
            前端能精确匹配 pending UI 挂到对应的 tool_call entry 上
        fingerprint: code 工具专用语义指纹（imports + calls + lang + sandbox）；cmd 工具忽略。
            永久批准走此字段精确匹配，不再用 JSON dump 全文 fnmatch。
        execution_env: "sandbox" / "local" —— SSE permission_request payload 透传字段,
            前端按 env 渲染差异化审批 UI(sandbox 黄色 / local 红色脉动)

    Returns:
        (decision, feedback)
        decision: "approved" / "this-time-only" / "denied" / "feedback"
        feedback: 仅 decision == "feedback" 时有值（用户填的指导文本），其他时 None

    Raises:
        langgraph.types.GraphInterrupt: 等用户决策时抛出（图暂停，由 ToolNode 透明传播）
    """
    perms = get_permissions()

    # 永久拒绝 → 直接返回
    if perms.is_denied(command)[0]:
        return "denied", None

    # 已批准检查：cmd 走 fnmatch(command 字符串)；code 走 fingerprint 精确相等
    if action == ActionType.CODE and fingerprint:
        if perms.is_approved_code_fingerprint(fingerprint, session_id)[0]:
            return "approved", None
    else:
        if perms.is_approved(command, session_id)[0]:
            return "approved", None

    # policy 放行 → 直接返回
    if not perms.should_ask(command, action):
        return "approved", None

    # 写 redis pending request（SSE 检测到 + 推 permission_request 事件给前端）
    _write_pending_permission(session_id, command, action, tool_call_name, fingerprint, execution_env)

    # 调官方 interrupt() —— ToolNode 透明传播 GraphInterrupt
    # value 是元数据 payload（让 SSE 推 permission_request 事件用），不是 sys_msg 注入
    # resume 后 interrupt() 返回 Command(resume=...) 的 decision 字符串
    # 不带 request_id —— thread_id (= session_id) 已足够定位 pending permission（每 sid 单例）
    decision_value = interrupt(
        value={
            "type": "permission_request",
            "command": command,
            "action": action.value,
            "session_id": session_id,
            "tool_call_name": tool_call_name,
            "execution_env": execution_env,
        }
    )

    # gate 已被 resume 消费：清掉 hash，避免 astream 末尾 _judge_has_pending_permission
    # 把"已消费"误判为"pending"再 yield 一条 permission_request 事件（前端会再次弹审批 UI）
    _delete_pending_permission(session_id)

    if decision_value == "approve":
        # 持久化：cmd 用 fnmatch pattern；code 用 fingerprint 精确 pattern
        if action == ActionType.CODE and fingerprint:
            perms.approve_code_fingerprint(
                fingerprint, reason="user approved", scope="global", session_id=session_id
            )
        else:
            perms.approve(
                command, reason="user approved", scope="global", session_id=session_id
            )
        return "approved", None
    if decision_value == "this-time-only":
        return "this-time-only", None
    if decision_value in ("deny", "denied", "reject"):
        return "denied", None

    # 4th 选项：feedback:<text> —— 用户告诉 AI 怎么做
    if isinstance(decision_value, str) and decision_value.startswith("feedback:"):
        feedback_text = decision_value[len("feedback:"):].strip()
        if feedback_text:
            return "feedback", feedback_text
        # 空文本 fallback 按 deny 处理
        return "denied", None

    # 未知决策值兜底按 deny
    logger.warning(
        f"会话 {session_id or 'unknown'} 收到未知 permission decision={decision_value!r}，按 deny 处理"
    )
    return "denied", None


def _write_pending_permission(
    session_id: str,
    command: str,
    action: ActionType,
    tool_call_name: str = "",
    fingerprint: str = "",
    execution_env: str = "sandbox",
) -> None:
    """写 redis `permission:{sid}` hash（singleton — 每 sid 只有一个 pending permission）。

    不带 request_id：thread_id (= session_id) 足够定位 pending permission，单例语义下不再需要 sub-id。
    tool_call_name 写到 hash：SSE permission_request 兜底推送（aestream 收尾段）也能带上，
    让前端精确匹配对应工具的 entry，并发工具 sequencing 错位也能正确标位。
    fingerprint 是 code 工具语义指纹（永久批准 match 用），前端不需要，这里入 hash 主要用于
    日志/审计（决策后 _judge_has_pending_permission 推到 SSE 时携带，便于排查）。
    execution_env 是执行环境标签("sandbox" / "local")，写 hash 便于审计与前端兜底推送。
    """
    if not session_id:
        # 没有 sid（裸调场景）：跳过 redis，不阻塞流程
        return

    try:
        import redis as _redis
        from ChatMe.ChatMeConfig import get_redis_checkpointer_url

        r = _redis.from_url(get_redis_checkpointer_url())
        mapping = {
            "command": command,
            "action": action.value,
            "status": "pending",
            "timestamp": str(time.time()),
            "execution_env": execution_env,
        }
        if tool_call_name:
            mapping["tool_call_name"] = tool_call_name
        if fingerprint:
            mapping["fingerprint"] = fingerprint
        r.hset(f"permission:{session_id}", mapping=mapping)
        r.expire(f"permission:{session_id}", 3600)
    except Exception as e:
        logger.warning(f"写 redis permission:{session_id} 失败: {e}（继续走 interrupt）")


def _delete_pending_permission(session_id: str) -> None:
    """gate 被 resume 消费（interrupt() 返回 decision）后清理 redis hash。

    必须清的原因：_write_pending_permission 写的是 status=pending + decision 未设；
    request_approval 走完 interrupt() 后 hash 不会被自动改写。如果不清，
    resume_permission_stream / message_stream 在 astream 末尾调
    _judge_has_pending_permission 会误判"还有 pending" → yield 一条 permission_request
    事件 → 前端 handlePermissionRequest 又合成一条新 tool entry 弹第二次审批 UI，
    用户看到「AI 答完了又来一次审批」的错觉（round-after-loop 的根源）。
    """
    if not session_id:
        return
    try:
        import redis as _redis
        from ChatMe.ChatMeConfig import get_redis_checkpointer_url

        r = _redis.from_url(get_redis_checkpointer_url())
        r.delete(f"permission:{session_id}")
    except Exception as e:
        logger.warning(f"清 redis permission:{session_id} 失败: {e}（继续走 decision 处理）")


def _rejected_tool_result(tool_name: str, args_summary: str) -> str:
    """自然的 tool rejection 结果（看上去像正常 function result，不是硬编码 Error: 前缀）。

    LLM 看到 Error: 会判定为失败并重试，但用户已明确拒绝不该重试，所以用这种 Result+Reason 风格。
    """
    return (
        f"User rejected this {tool_name} call ({args_summary}); "
        f"the {tool_name} was not executed and no side effects occurred. "
        f"Think about possible alternative approaches, "
        f"or use the interrupt tool to ask the user how to proceed."
    )


def _feedback_tool_result(tool_name: str, args_summary: str, feedback: str) -> str:
    """4th 选项「告诉 AI 怎么做」的 ToolMessage 内容。

    用户填的指导文本作为核心内容塞给 ToolMessage，配合最小模板让 LLM 知道：
    1. 用户主动给的指导是什么（直接引用）
    2. 该 tool 没执行，需重试
    3. 重试时应当考虑用户反馈

    不带 Error: 前缀（与 _rejected_tool_result 同款风格，避免 LLM 误判 error 分支）。
    """
    return (
        f"User has provided guidance for this {tool_name} call ({args_summary}); "
        f"the {tool_name} was not executed and no side effects occurred. "
        f"User guidance: {feedback}. "
        f"Re-attempt the call considering this feedback."
    )


# =========================================================================
# PermissionedToolNode: 官方 ToolNode 子类 + _awrap_tool_call hook
# =========================================================================


def _pre_check_cmd(command: str):
    """cmd 工具前置 gate：dangerous / whitelist 两个静态检查。

    返回 (block_kind, message)：
    - block_kind = None → 通过（应继续走 permission gate）
    - "dangerous" / "not_allowed" → 拒，对应 message 即 ToolMessage content

    wording 跟 `_rejected_tool_result` / `_feedback_tool_result` 对齐——
    不带 "Error:" 前缀（避免 LLM 误判为可重试的运行时错误），明确告诉 AI：
    - 命令被系统自动拦截，没有执行、零副作用
    - 不要再换参数重试同一类命令
    - 引导：换思路 / 用 `interrupt` 问用户

    早期版本还有 `is_script` 拦截（python/node 脚本必须走 code 工具），已解除——
    cmd 工具现在可以直接跑 python/node 等脚本（沙盒默认 Linux 环境本身支持）。
    """
    from ..tools.platforms import get_platform

    platform = get_platform()
    is_d, reason = platform.is_dangerous(command)
    if is_d:
        return "dangerous", (
            f"Auto-blocked by safety system: {reason}. "
            f"Command '{command[:200]}' was not executed. "
            f"Do NOT retry — the pattern is permanently blocked. "
            f"Use interrupt tool to ask user if needed."
        )
    is_a, allow_reason = platform.is_allowed(command)
    if not is_a:
        return "not_allowed", (
            f"Auto-blocked: command not in {platform.name} whitelist. "
            f"'{command[:200]}' was not executed. "
            f"Do NOT retry — use one of the whitelisted commands: {allow_reason} "
            f"Or use interrupt tool to ask user."
        )
    return None, ""


def _permission_target_for(tool_call: dict) -> Optional[Dict[str, Any]]:
    """需要审批的工具 → dict（command / fingerprint / action / tool_call_name / execution_env）；其他工具返回 None。

    返回字段说明：
    - command: 给前端 SSE 展示 + redis hash 持久化的命令串
      - cmd 工具：原始命令字符串
      - code 工具：完整 args JSON dump
    - fingerprint: 永久批准的 pattern key
      - cmd 工具：与 command 相同（走 fnmatch glob）
      - code 工具：_code_fingerprint 提取的语义指纹（精确相等匹配，**不**走 glob）
    - action: ActionType 分类（policy 决策用）
    - tool_call_name: 工具名（"cmd" / "code"）—— SSE permission_request event 携带，
      前端能精确匹配 pending UI 挂到对应的 tool_call entry 上（并发场景 sequencing 错位时）
    - execution_env: "sandbox" / "local" —— 由 args.local 反推 (True → "local")
      透传到 SSE permission_request 事件，前端按 env 渲染差异化审批 UI
    """
    name = tool_call.get("name")
    args = tool_call.get("args") or {}
    use_sandbox = not bool(args.get("local", False))  # 反向读取新参数(默认 False → sandbox)
    if name == "cmd":
        command = str(args.get("command", ""))
        return {
            "command": command,
            "fingerprint": command,
            "action": get_permissions().classify(command),
            "tool_call_name": name,
            "execution_env": "sandbox" if use_sandbox else "local",
        }
    if name == "code":
        command = json.dumps(args, ensure_ascii=False)
        return {
            "command": command,
            "fingerprint": code_fingerprint(args),
            "action": ActionType.CODE,
            "tool_call_name": name,
            "execution_env": "sandbox" if use_sandbox else "local",
        }
    return None


class PermissionedToolNode(ToolNode):
    """官方 ToolNode 子类，通过 `awrap_tool_call` hook 注入三层 gate。

    Gate 顺序（按用户体验设计，避免用户审了白审）：
    1. **cmd 静态前置检查**：dangerous（硬保底 / yolo 也拦）/ script 提示改用 code /
       whitelist 不在白名单 → 直接返回对应错误 ToolMessage，**不**问用户。
    2. **permission 审批**：default policy + write/code/network 触发；放行（approved /
       this-time-only）→ 走官方 execute；拒绝 → 自然 rejection ToolMessage。
    3. **其他工具**：无审批，原样转发。

    把静态检查从 MCP 工具搬到这里的原因：
    - 用户审了 `rm -rf /` 后被 MCP `is_dangerous` 拦下 → 浪费了一次审批 + 弹窗
    - 同理 script / whitelist 命中 → 早 fail，不打扰用户

    MCP 工具侧仍保留同样的静态检查作为 defense-in-depth（万一绕过 graph 层直调）。

    继承 ToolNode 的全部原生行为：并行执行 / Command 返回 / state 注入 / 错误处理等。
    用法与官方一致：

        tool_execution_node = PermissionedToolNode(tools=self.tools)

    [TODO] 并行 batch gate：当前 N 个并行 tool_call 各走一次 `interrupt()`，LangGraph
    `scratchpad.resume` 单值只能 consume idx=0，后续 idx 再抛 GraphInterrupt → 用户
    需点 N 次才能走完。优化方向：override `_arun` 按 `_permission_target_for().fingerprint`
    分组，组内一次 interrupt 一次决策应用到整组（cmd 不同命令天然分不同组，
    不会误合并危险命令）。详见会话 955be71c 研究记录。
    """

    def __init__(self, tools):
        # 若 handle_tool_errors=True 会把 GraphInterrupt（GraphBubbleUp 子类）
        # 也吞掉并转成 error ToolMessage，permission 的 interrupt() 就无法 pause 图。
        super().__init__(
            tools=tools,
            awrap_tool_call=self._permission_wrap,
            handle_tool_errors=False,
        )

    async def _permission_wrap(self, request: ToolCallRequest, execute):
        tc = request.tool_call
        name = tc["name"]
        call_id = tc["id"]
        args = tc.get("args") or {}

        # gate 1：cmd 静态前置（dangerous / whitelist）
        if name == "cmd":
            command = str(args.get("command", ""))
            block_kind, message = _pre_check_cmd(command)
            if block_kind is not None:
                logger.info(
                    f"前置 gate 拦截 cmd ({block_kind}): {command[:80]}"
                )
                return ToolMessage(
                    content=message, tool_call_id=call_id, name=name,
                )

        # gate 2：permission 审批（interrupt() 抛 GraphInterrupt 必须穿透到 runtime）
        target = _permission_target_for(tc)
        if target is not None:
            from langgraph.config import get_config
            thread_id = get_config()["configurable"]["thread_id"]
            command = target["command"]
            action = target["action"]
            tool_call_name = target["tool_call_name"]
            fingerprint = target["fingerprint"]
            execution_env = target["execution_env"]
            decision, feedback = request_approval(
                command, action, thread_id, tool_call_name, fingerprint, execution_env
            )
            if decision == "denied":
                logger.info(f"会话 {thread_id} 用户拒绝 {name} 调用: {command[:80]}")
                return ToolMessage(
                    content=_rejected_tool_result(
                        tool_name=name, args_summary=command[:200]
                    ),
                    tool_call_id=call_id,
                    name=name,
                )
            if decision == "feedback":
                # 4th 选项：把用户指导塞进 ToolMessage content（不是 reject，让 LLM 重试时参考）
                logger.info(
                    f"会话 {thread_id} 用户给 {name} 反馈: {(feedback or '')[:80]}"
                )
                return ToolMessage(
                    content=_feedback_tool_result(
                        tool_name=name,
                        args_summary=command[:200],
                        feedback=feedback or "",
                    ),
                    tool_call_id=call_id,
                    name=name,
                )

        # gate 3：放行 → 官方 ToolNode 执行；真实工具错误转 error ToolMessage，
        # GraphBubbleUp（interrupt / Command）原样抛给上层 runtime
        try:
            return await execute(request)
        except GraphBubbleUp:
            raise
        except Exception as e:
            logger.error(
                f"会话 工具 {name} 执行失败: {type(e).__name__}: {e}"
            )
            return ToolMessage(
                content=f"Error: {type(e).__name__}: {str(e)[:300]}",
                tool_call_id=call_id,
                name=name,
            )