---
name: BochaSearch
description: 博查（Bocha）实时网页搜索，针对中文互联网深度优化。适合查询最新新闻、时效性资讯、政策、自媒体内容、国内网站信息。支持按时间范围筛选（当天 / 一周 / 一月 / 一年）。少量多次，单次结果数量保持精炼。
mount: ro
aliases: [Bocha, 博查, news, latest, realtime, web_search, search]
module: skills.BochaSearch
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
from skills.BochaSearch import search_web

result = search_web(
    query="检索主题",
    freshness="oneWeek",     # noLimit / oneDay / oneWeek / oneMonth / oneYear
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

## API Key 配置

- **config.json 路径**：`skills.bocha_api_key`
- **环境变量**：`BOCHA_API_KEY`
- **申请**：https://bochaai.com → 控制台 → API Key
- **套餐**：免费 1000 次/3 个月试用；正式 ¥36/1000 次

## 错误处理

- 网络层错误（SSL EOF / Connection timeout）→ 返回「网络层不可达」提示（不是代码 bug）
- API key 缺失 → 返回「BOCHA_API_KEY 未配置」
- 业务错误（code != 200）→ 返回 API 给的 msg 字段

不要编造检索结果；调用后基于函数实际返回内容总结，并保留来源 URL。
