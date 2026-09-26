---
name: WebSearch
description: 统一网页搜索技能，自动在 Bocha/Tavily/Exa 后端间选择并容错，返回统一格式结果
mount: ro
module: skills.WebSearch
aliases: [WebSearch, web_search, 搜索, 网页搜索, search]
---

# WebSearch

统一网页搜索技能。自动在 Bocha / Tavily / Exa 之间选择可用后端，返回统一格式结果。

## 适用场景

- 需要网页搜索但不确定用哪个后端
- 希望自动容错（一个后端失败自动切换下一个）
- 快速检索最新信息、事实确认

## 调用方式

```python
from skills.WebSearch import web_search

result = web_search(query="检索主题", count=5, freshness="noLimit", engine="auto")
print(result)
```

## 函数

### `web_search(query, count=5, freshness="noLimit", engine="auto")`

- `query`：检索关键词 / 主题
- `count`：返回结果数量（建议 <=5，少量多次优于单次多量）
- `freshness`：时间范围 `noLimit` / `oneDay` / `oneWeek` / `oneMonth` / `oneYear`
- `engine`：`auto`（默认，按 bocha→tavily→exa 顺序尝试）/ `bocha` / `tavily` / `exa`

返回格式化文本，前缀标注实际使用的后端 `[engine=xxx]`。

### `search(...)`

`web_search` 的简写别名，参数相同。

## 说明

- 后端优先级：Bocha（中文优化）→ Tavily（通用）→ Exa（语义）
- 任一后端抛错会自动尝试下一个，全部失败时返回错误汇总
- 不要编造检索结果；基于实际返回内容总结并保留来源 URL

## 按需查函数详细用法

拿到引用后直接 `.help`（最常用）：

```python
from skills.WebSearch import web_search, search
print(web_search.help)        # 完整参数（count/freshness/engine）
print(search.help)             # 别名同 web_search
```

不确定函数名时：`from skills.WebSearch import help; help()` 列全部 / `help("web_search")` 单查。

`SKILL.md` 只放最常用 80% 用法 + 极简示例；详细按需拿 `.help`，避免 SKILL.md 膨胀。

