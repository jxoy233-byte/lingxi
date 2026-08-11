---
name: scheduler
description: 定时任务管理（cron 周期任务的创建 / 查询 / 取消 / 立即触发）
mount: ro
aliases: [Scheduler, cron, schedule, scheduled_task, 定时, 定时任务, 周期, 提醒, reminder, recurring, timer]
module: skills.Scheduler
---

# Scheduler

定时任务管理：把一段 prompt 配成 cron，到点自动注入指定 session 跑 LangGraph agent 完整一轮。

## 适用场景

- 用户说"每天 9 点帮我..."、"每小时提醒我..."、"每 30 分钟巡检..."
- 用户说"现在帮我跑一次"（不走 cron，立即触发已有任务）
- 用户说"取消 / 删除 / 停掉那个定时任务"

适用关键词：定时、周期、每天、每小时、cron、提醒、schedule、recurring、reminder、trigger、run now。

## ⚠️ 调 `code()` 必须传 `local=True`

主进程跑（不走沙盒），4 个函数内部走 HTTP 调 `127.0.0.1:8211/admin/scheduled-tasks/*`；沙盒网络层在本项目不可靠且缺 `apscheduler`/`redis` 包，`local=False` 会卡死 / `ModuleNotFoundError`。看到 `ConnectionError` / `Timeout` / `ModuleNotFoundError` → 检查是否漏了 `local=True`。

```python
# code("""...""", local=True)
from skills.Scheduler import create_scheduled_task
print(create_scheduled_task(
    name="每日销售汇总",
    cron="0 9 * * *",
    prompt="汇总昨天的 sales.csv",
    session_id="<current_thread_id>",
))
```

## 调用方式

skill 暴露 **4 个独立顶层函数**，不通过 action dispatch。LLM 直接按需 import 调用（`code()` 工具里 `print(...)` 顶层结果，**且 `local=True`**）：

```python
from skills.Scheduler import (
    create_scheduled_task,
    list_scheduled_tasks,
    cancel_scheduled_task,
    run_scheduled_task_now,
)
```

主进程本机也兼容别名导入（Python path 包含 `/skills`）：

```python
from Scheduler import create_scheduled_task
```

## 函数

### `create_scheduled_task(name, cron, prompt, session_id="")`

- `name`：任务名（1-100 字符，便于用户侧栏识别）
- `cron`：5-field cron，**Asia/Shanghai 时区**，例如 `"0 9 * * *"` = 每天 9:00
- `prompt`：触发时注入到 session 的用户消息（agent 看到的就是这条）
- `session_id`：目标 session。`""` = 触发时自动新建一个 session；非空 = 复用 / 创建该 sid

返回字符串：`Scheduled task 'X' (id=abc123456789, cron='0 9 * * *', session='<auto>')`

### `list_scheduled_tasks(session_id="")`

- `session_id`：过滤条件，`""` = 全部；非空 = 只列该 session 的任务

返回多行字符串：
```
3 scheduled task(s):
  - 每日销售汇总 (id=abc123456789, cron='0 9 * * *', enabled, session='<auto>')
  - AI 新闻日报 (id=def678901234, cron='0 9 * * *', enabled, session='abc123456789')
  - 数据库巡检 (id=ghi111213141, cron='*/30 * * * *', disabled, session='<auto>')
```
`task_id` 输出**全 12 位**（不是 8 位前缀），用户要复制定粘贴就用全的。

### `cancel_scheduled_task(task_id)`

- `task_id`：支持前缀匹配（传 `abc123` 也能命中 `abc123456789`）

返回字符串：`Cancelled task abc123456789`

### `run_scheduled_task_now(task_id)`

- `task_id`：同上，支持前缀匹配
- **不修改 cron**，只是立即触发一次

返回字符串：`Triggered task abc123456789 to run now (next cron unchanged)`

## 错误格式

所有 HTTP 错误统一为 `[类型] 描述 | 建议`（AI-friendly，可直接 parse）：

- `[BadRequest] cron expression invalid: ...` → 用 5-field Asia/Shanghai TZ，例如 `"0 9 * * *"`
- `[NotFound] task abc12345 not found` → 调 `list_scheduled_tasks` 查 task_id
- `[ServiceUnavailable] scheduler not started` → 检查后端 lifespan 日志
- `[ConnectionError] cannot reach ChatMe backend at {host}` → 确认后端在 :8211 启动

## 注意事项

- 4 个函数都是 `code()` 工具调用，**必须 `local=True` + `print(...)` 顶层结果**（详见顶部 ⚠️ 节）
- `session_id` 不在工具参数里自动注入；LLM 需从 memory block 的 `## 缓存文件目录\n- cached/{thread_id}` 读 thread_id 透传
- Skill 内的错误响应都已格式化（含可读建议），LLM 看到 `[类型]` 前缀就知道该换策略
- 持久化依赖主后端 Redis，**重启后端服务**会从 Redis 恢复所有任务（APScheduler RedisJobStore）
