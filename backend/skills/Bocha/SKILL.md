---
name: Bocha
description: 博查实时网页搜索（中文互联网深度优化）。适合新闻、时效资讯、政策、国内网站信息；支持当天 / 一周 / 一月 / 一年时间筛选
mount: ro
aliases: [Bocha, 博查, news, latest, realtime, web_search, search]
module: skills.Bocha
---

# Bocha Search

> **搜索策略（硬性约束）**：单次 `count` 始终 ≤3-5，先少量试探；信息不足时调整 `query` / `freshness` / `summary` **再搜一次**，而不是堆数量。**少量多次**优于单次多量。

## 适用场景

- 查询最新、今天、最近发生的信息
- 中文新闻、时事、政策、自媒体内容
- 国内网站 / App / 产品信息（博查对中文站点覆盖比 Tavily / Exa 强很多）
- 需要按时间过滤：当天、一周、一月、一年内

适用关键词：新闻、动态、消息、发布、最新、最近、中文、国内。

**什么时候用 Bocha 而不是 Tavily / Exa**：
- 网络环境在国内 / 不稳定连海外 API（Tavily / Exa 经常 SSL EOF timeout）
- 搜索主题以中文为主
- 想要新闻 / 政策类时效性内容

## 调用方式

```python
from skills.Bocha import search_web

result = search_web(
    query="检索主题",
    freshness="oneWeek",  # noLimit / oneDay / oneWeek / oneMonth / oneYear
    summary=True,
    count=3,
)
```

沙盒也兼容别名导入：

```python
from BochaSearch import search_web
```

## 函数

### `search_web(query, freshness="noLimit", summary=True, count=3, **kwargs)`

- **`count` 默认 3，强烈建议保持 ≤5**：信息不足就调整 `query` / `freshness` 再调一次
- `freshness="noLimit"`（默认）：不限时间
- `freshness="oneDay"`：仅当天
- `freshness="oneWeek"`：一周内
- `freshness="oneMonth"`：一月内
- `freshness="oneYear"`：一年内
- `summary=True`：返回文本摘要（默认开）
- `summary=False`：只返标题 / URL，更快

返回格式化文本，包含引用编号、标题、URL、摘要、网站名称、网站图标、发布时间。

## 错误处理

- 网络层错误（SSL EOF / Connection timeout）→ 返回「网络层不可达」提示（不是代码 bug）
- API key 缺失 → 返回「BOCHA_API_KEY 未配置」
- 业务错误（code != 200）→ 返回 API 给的 msg 字段

不要编造检索结果；调用后基于函数实际返回内容总结，并保留来源 URL。

## 按需查函数详细用法

拿到引用后直接 `.help`（最常用）：

```python
from skills.Bocha import search_web
print(search_web.help)        # 完整参数（freshness/summary/count/**kwargs）
```

不确定函数名时：`from skills.Bocha import help; help()` 列全部 / `help("search_web")` 单查。

`SKILL.md` 只放最常用 80% 用法 + 极简示例；详细按需拿 `.help`，避免 SKILL.md 膨胀。
