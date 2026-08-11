"""
定时任务数据模型

ScheduledTask 是应用层业务对象，与 APScheduler 的 pickle Job 完全解耦：
- APScheduler 负责"什么时候跑"（next_run_time + cron trigger）
- ScheduledTask 负责"跑什么、给谁"（name / prompt / session_id）

两者通过同一个 task_id 关联，分别存在：
- APScheduler:    apscheduler.jobs HASH + apscheduler.run_times ZSET
- 应用层:        scheduled:meta:{tid} HASH
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional, Any


# Redis key 集中管理（避免散落）
SCHEDULED_TASKS_SET = "scheduled:tasks"             # SET  所有 task_id
SCHEDULED_META_PREFIX = "scheduled:meta:"           # HASH 单个任务
SCHEDULED_HISTORY_PREFIX = "scheduled:history:"      # LIST 执行历史
SCHEDULED_LOCK_PREFIX = "scheduled:lock:"            # STRING NX EX 3600 防重入

# APScheduler 自己的 key（与 RedisJobStore 默认对齐，避免混淆）
APSCHEDULER_JOBS_KEY = "apscheduler.jobs"
APSCHEDULER_RUN_TIMES_KEY = "apscheduler.run_times"


@dataclass
class ScheduledTask:
    """
    单个定时任务的全部业务字段

    所有字段都是 Redis 序列化友好的基本类型（str / int / float / bool）
    """

    # === 必填 ===
    task_id: str                 # = uuid.uuid4().hex[:12]
    name: str                    # 用户可读名
    cron: str                    # 5-field cron 表达式
    prompt: str                  # 触发时注入到 session 的"用户消息"
    session_id: str              # 目标 session（空=当前，任意值=灵活）

    # === 元数据（创建时写入）===
    created_by: str = ""         # 创建者的 session_id（权限边界）
    created_at: float = 0.0      # time.time()
    task_type: str = "send_message"  # 当前只有 send_message，留扩展位

    # === 运行时统计（handler 写入）===
    enabled: int = 1             # 0 / 1（HSET 友好；bool 反序列化有陷阱）
    run_count: int = 0
    last_run: float = 0.0        # time.time() of last trigger

    # === Redis meta HASH 字段白名单（避免意外写错字段名）===
    META_FIELDS: tuple = field(
        default=(
            "name", "cron", "task_type", "prompt", "session_id",
            "created_by", "created_at", "enabled",
            "run_count", "last_run",
        ),
        init=False, repr=False,
    )

    def to_hset_mapping(self) -> dict[str, str]:
        """序列化为 Redis HSET 友好的 dict（所有值转 str）"""
        return {k: str(getattr(self, k)) for k in self.META_FIELDS}

    @classmethod
    def from_hgetall(cls, task_id: str, raw: dict[bytes, bytes]) -> Optional["ScheduledTask"]:
        """从 Redis HGETALL 还原（raw 是 {field_bytes: value_bytes}）

        数值字段（created_at / enabled / run_count / last_run）做防御性 int/float：
        Redis 数据被外部写脏时（如 admin 手动改）不应让整个恢复流程崩。
        """
        if not raw:
            return None
        decoded = {k.decode(): v.decode() for k, v in raw.items()}

        def _safe_float(key: str, default: float = 0.0) -> float:
            try:
                return float(decoded.get(key, default) or default)
            except (ValueError, TypeError):
                return default

        def _safe_int(key: str, default: int = 0) -> int:
            try:
                return int(decoded.get(key, default) or default)
            except (ValueError, TypeError):
                return default

        return cls(
            task_id=task_id,
            name=decoded.get("name", ""),
            cron=decoded.get("cron", ""),
            prompt=decoded.get("prompt", ""),
            session_id=decoded.get("session_id", ""),
            created_by=decoded.get("created_by", ""),
            created_at=_safe_float("created_at"),
            task_type=decoded.get("task_type", "send_message"),
            enabled=_safe_int("enabled", 1) or 1,
            run_count=_safe_int("run_count", 0),
            last_run=_safe_float("last_run"),
        )

    def to_api_dict(self) -> dict[str, Any]:
        """
        对外 API 响应字段（前端 ScheduledTasksPanel 数据契约）
        字段命名 snake_case，与 GET /admin/scheduled-tasks 响应一致
        """
        d = {
            "task_id": self.task_id,
            "name": self.name,
            "cron": self.cron,
            "prompt_preview": self.prompt[:80] + ("..." if len(self.prompt) > 80 else ""),
            "session_id": self.session_id,
            "task_type": self.task_type,
            "enabled": bool(self.enabled),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "run_count": self.run_count,
            "last_run": self.last_run,
        }
        return d


# === 历史记录结构（写入 scheduled:history:{tid} LIST 的 JSON）===

@dataclass
class HistoryEntry:
    """单次执行结果（handler 写、API 读）"""
    ts: float                    # time.time() of trigger
    status: str                  # "success" | "error"
    duration_ms: int = 0
    output_preview: str = ""     # 截断到 300 字符
    error: str = ""              # 异常信息

    def to_json(self) -> str:
        import json
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "HistoryEntry":
        import json
        d = json.loads(raw)
        return cls(**d)