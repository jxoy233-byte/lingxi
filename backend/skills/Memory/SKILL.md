---
name: memory
description: 记住精确事实 / 用户偏好到会话或全局记忆文件，context_assembly_node 自动注入让未来对话直接可用
mount: ro
aliases: [Memory, 记忆, remember, recall, save_memory, 记住, fact, preference, 偏好, 事实, 记录]
module: skills.Memory
lazy: false
---

# Memory

把对话里反复出现的精确事实 / 用户偏好持久化到记忆文件，让未来对话开箱即用。
context_assembly_node 每轮开头自动合并注入，所以**只管写、读不用主动调**。

## 什么时候用

remember 是显式动作 —— 只在该记的时候记，不要每个事实都往上扔。

**值得记** 的通常是：精确数值（金额、阈值、口径）、路径 / 端口 / API endpoint / DB 表名、业务规则（"X 必须先于 Y"、"Z 每月 5 号生成"）、用户偏好（语言 / 单位 / 时区 / 回答风格）、反复出现的事实。

**不必记** 的通常是：临时状态、调试过程、一次性查询、上一轮已经记过的事实、用户的"嗯嗯 / 好的"这种噪声。把握不准时宁可少记 —— 写错了比少记更难清理。

## 调用方式

**remember 必须 `code(..., local=True)`** —— 沙盒挂的是 ro，写必须走 host。
**recall / `cmd("cat ...")` 沙盒也能用** —— `.chatme/memory/` 在沙盒里挂到 `/memory` (ro)。

**执行时机**：不阻塞主线 —— 主任务进行中并行记，或任务收尾前统一写。

```python
# 写（host-only）
from skills.Memory import remember
print(remember(
    key="Q2 销售聚合口径",
    value="按月 + 品类聚合\n销售数据来自 sales.csv\n口径与 Q1 一致",
    thread_id="<current>",
    category="facts",
))
```

```python
# 读（沙盒或 host 都能调）
from skills.Memory import recall
print(recall(thread_id="<current>", category="facts"))

# 或者直接 cat
# cmd("cat /memory/<tid>/facts.md")
```

返回：

```
[OK] remembered 'Q2 销售聚合口径' (28 chars) → .chatme/memory/abc123def456/facts.md
```

## 函数

### `remember(key, value, thread_id, category="facts", scope="thread") -> str`

| 参数 | 说明 |
|---|---|
| `key` | 事实标题（短而具体，agent 用此 key 做 dedup） |
| `value` | 内容；单行 ≤200 字符自动 inline；含 `\n` 或 ≥200 字符自动 block |
| `thread_id` | 当前会话 ID（agent 从 prompt context 取 12 / 32 位 hex） |
| `category` | `"facts"`（精确事实 / 数值 / 路径 / 业务规则）或 `"preference"`（用户偏好 / 习惯 / 风格） |
| `scope` | `"thread"`（当前会话）或 `"global"`（跨会话共享） |

写入语义：同名 key 替换旧值（updated），新 key 追加（remembered）。

返回：

- `[OK] remembered/updated '{key}' ({N} chars) → {path}`
- `[BadRequest] category 必须为 'facts' 或 'preference'，收到: ...`
- `[WriteError] 写入 ... 失败: ...`

### `recall(thread_id, category="facts", scope="thread") -> str`

回忆完整记忆文件。context_assembly_node 在每轮开头已自动合并注入；
本函数用于对话中需要主动核对某条精确事实、或展示给用户看时调用。

## 写入原则

1. **去重优先**：调之前先 `cmd("cat /memory/<tid>/facts.md")` 看看是否已存在；已存在的就走更新，不重新发明。
2. **key 短而稳**：用「主谓宾」短语（"Q2 销售聚合口径"、"用户偏好单位"、"DB 端口"），避免"刚才那个表的数据"这种代词。
3. **value 自包含**：未来读这行的人（或你自己）没看过原始对话也要能懂，不要写"前面那个口径" —— 写"按月 + 品类聚合"。
4. **不写中间过程**：调试日志、命令输出、临时探索路径、失败堆栈一律不写。
5. **global 慎用**：跨会话共享有重量 —— 真用户级别偏好（"始终中文回答"、"用人民币万元"）才走 global，会话级任务细节走 thread。

## 文件路径速查

| scope | category | host 路径 | 沙盒路径 |
|---|---|---|---|
| thread | facts | `.chatme/memory/{thread_id}/facts.md` | `/memory/{thread_id}/facts.md` |
| thread | preference | `.chatme/memory/{thread_id}/preference.md` | `/memory/{thread_id}/preference.md` |
| global | facts | `.chatme/memory/global/facts.md` | `/memory/global/facts.md` |
| global | preference | `.chatme/memory/global/preference.md` | `/memory/global/preference.md` |
