---
name: exa
description: 深度语义搜索与相似网页发现，适合研究、原理、对比和综合分析。默认少量结果（≤5 条），信息不足再调关键词/角度/type 重搜，少量多次优于单次多量。
mount: ro
aliases: [Exa, research, semantic_search, deep_search, find_similar]
module: skills.Exa
---

# Exa

> **搜索策略（硬性约束）**：单次 `num_results` 始终 ≤5，先少量试探；信息不足时调整关键词 / 角度 / `type` **再搜一次**，而不是堆数量。**少量多次**优于单次多量。

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

- **`num_results` 默认 5，强烈建议保持 ≤5**：信息不足就调整 query / `type` 再调一次
- `type` 可选：

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
