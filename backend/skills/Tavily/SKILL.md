---
name: tavily
description: 快速实时网页搜索与答案摘要，适合最新信息、一般查询和时效性任务
mount: ro
aliases: [Tavily, news, latest, realtime, web_search, search]
module: skills.Tavily
---

# Tavily

Tavily 是实时网页搜索技能，适合快速获取最新信息、网页结果和可选的 AI 答案摘要。

## 适用场景

- 查询最新、今天、最近发生的信息
- 用户要求“查一下”或快速确认某个事实
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

## 搜索策略

单次结果 ≤5 条，先少量试探；信息不足时调整关键词 / 角度**再搜一次**，而不是堆数量。**少量多次**优于单次多量。

## 函数

### `tavily_search(query, search_depth="basic", max_results=5, include_answer=False, **kwargs)`

- `search_depth="basic"`：快速搜索
- `search_depth="advanced"`：更全面、更深入的搜索
- `max_results`：返回结果数量
- `include_answer=True`：请求 Tavily 生成答案摘要

返回格式化文本，包含标题、URL、内容、可用时的发布时间和答案摘要。

不要编造检索结果；调用后基于函数实际返回内容总结，并保留来源 URL。
