---
name: tavily
description: 快速实时网页搜索 + 答案摘要。适合最新信息、一般查询、时效性任务
mount: ro
aliases: [Tavily, news, latest, realtime, web_search, search]
module: skills.Tavily
---

# Tavily

> **搜索策略（硬性约束）**：单次 `max_results` 始终 ≤5，先少量试探；信息不足时调整关键词 / 角度 / `search_depth` **再搜一次**，而不是堆数量。**少量多次**优于单次多量。

## 适用场景

- 查询最新、今天、最近发生的信息
- 用户要求"查一下"或快速确认某个事实
- 希望搜索结果附带摘要
- 需要更全面结果时使用 advanced 深度

适用关键词：是什么、怎么做、怎么写、最新、今天、最近。

## 调用方式

```python
from skills.Tavily import tavily_search

result = tavily_search(
    query="检索主题",
    search_depth="basic",
    max_results=5,
    include_answer=True,
)
```

沙盒也兼容别名导入：

```python
from Tavily import tavily_search
```

## 函数

### `tavily_search(query, search_depth="basic", max_results=5, include_answer=False, **kwargs)`

- **`max_results` 默认 5，强烈建议保持 ≤5**：信息不足就调整 query / `search_depth` 再调一次
- `search_depth="basic"`：快速搜索
- `search_depth="advanced"`：更全面、更深入的搜索
- `max_results`：返回结果数量
- `include_answer=True`：请求 Tavily 生成答案摘要

返回格式化文本，包含标题、URL、内容、可用时的发布时间和答案摘要。

不要编造检索结果；调用后基于函数实际返回内容总结，并保留来源 URL。

## 按需查函数详细用法

拿到引用后直接 `.help`（最常用）：

```python
from skills.Tavily import tavily_search
print(tavily_search.help)        # 完整参数（search_depth/max_results/include_answer/**kwargs）
```

不确定函数名时：`from skills.Tavily import help; help()` 列全部 / `help("tavily_search")` 单查。

`SKILL.md` 只放最常用 80% 用法 + 极简示例；详细按需拿 `.help`，避免 SKILL.md 膨胀。
