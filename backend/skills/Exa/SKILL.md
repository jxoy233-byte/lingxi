---
name: exa
description: 深度语义搜索与相似网页发现，适合研究、原理、对比和综合分析
mount: ro
aliases: [Exa, research, semantic_search, deep_search, find_similar]
module: skills.Exa
---

# Exa

Exa 是深度语义搜索技能，适合需要理解主题全貌、跨领域检索或查找相似网页的任务。

## 适用场景

- 深入研究某个主题、原理或技术方案
- 对多个概念、产品或观点做对比分析
- 根据一个或多个 URL 查找相似内容
- 需要语义相关性而非单纯关键词匹配

适用关键词：研究、原理、对比、分析、详解、类似、相关。

## 调用方式

```python
from skills.Exa import exa_search, exa_find_similar

results = exa_search(
    query="检索主题",
    num_results=5,
    type="auto",
    maxCharacters=2000,
)
```

沙盒也兼容别名导入：

```python
from Exa import exa_search
```

## 函数

### `exa_search(query, num_results=5, type="auto", maxCharacters=2000, **kwargs)`

执行语义搜索并返回结果列表。`type` 可选：

- `instant`：约 200ms
- `fast`：约 400ms
- `auto`：自动选择，默认
- `deep`：深度搜索，约 4–12s

每项通常包含 `title`、`url`、`publishedDate`、`highlights`、`author`。

### `exa_find_similar(ids, maxCharacters=2000, maxAgeHours=168, livercrawlTimeout=5000, **kwargs)`

根据 URL 列表查找相似网页：

```python
similar = exa_find_similar(["https://example.com/article"])
```

不要编造检索结果；调用后基于函数实际返回内容总结，并保留来源 URL。
