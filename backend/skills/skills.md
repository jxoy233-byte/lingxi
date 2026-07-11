# 🧠 Skills Registry

本文件定义了 AI 在本环境中可使用的技能（Skills）。
这些技能以 Python 模块形式存在，AI 可以通过生成并执行 Python 代码来调用。

**使用skills**:
import sys
sys.path.insert(0, "/path/to/your/module")

from skills.xxx(直接写脚本名称，如Exa) import 模块名 ✅
from Exa import ... ❌
---

# 🧭 使用总则（非常重要）

当用回答用户问题时，AI 必须遵循以下决策流程：

## ✅ 什么时候使用 Skills

如果用户问题满足以下任一条件，应优先使用技能：

- 需要**最新信息**（新闻、发布、价格、趋势等）
- 涉及**不确定或可能过时的事实**
- 用户要求：
  - “查一下”
  - “最新”
  - “有没有资料”
  - “给我来源”
- 需要**外部数据支持**
- 进行**研究、对比、分析、信息收集**

---

## ⚙️ 调用规则

AI 必须：

1. **先判断是否需要技能**
2. 若需要：
   - 选择合适技能
   - 生成 Python 调用代码
3. **不要编造搜索结果**
4. 返回结果后：
   - 提取关键信息
   - 用自然语言总结
   - 必要时附上来源

---

# 🔍 Skill: Exa

Exa 是一个**深度语义搜索**引擎

**文件名称**: `Exa.py`
**类型**: 搜索 / 信息检索
**能力**: 语义搜索 + 相似内容发现

**适用场景**：
- 需要**深入研究**某个主题，了解全貌
- 查找与给定 URL **相似**的网页
- 需要跨领域的综合性内容

**适用关键词**：研究、原理、对比、分析、详解、类似、相关

**函数**：
- `exa_search(query, num_results, type, maxCharacters)` — 语义搜索
- `exa_find_similar(ids, ...)` — 根据 URL 查找相似内容

---

# 🔍 Skill: Tavily

Tavily 是一个**快速实时搜索**引擎，带 AI 答案摘要

**文件名称**: `Tavily.py`
**类型**: 搜索 / 信息检索
**能力**: 实时网页搜索 + AI 答案摘要 + 快速/深度模式

**适用场景**：
- 需要**快速获取答案**，且希望附带 AI 总结
- 一般实时查询，用户要求"查一下"
- `search_depth="advanced"` 用于需要更全面、更权威结果时

**适用关键词**：是什么、怎么做、怎么写、最新、今天、最近

**函数**：
- `tavily_search(query, search_depth, max_results, include_answer)` — 搜索

---

# 🔍 Skill: Bocha

Bocha 是一个**新闻/时效性**搜索引擎，支持按时间范围筛选

**文件名称**: `Bocha.py`
**类型**: 搜索 / 信息检索
**能力**: 实时网页搜索 + 多时间范围筛选

**适用场景**：
- 需要**最新新闻、近期动态**
- 按时间过滤：当天、一周、一个月内的结果
- 明确要求"今天的"、"本周的"、"上个月的"

**适用关键词**：新闻、动态、消息、发布、近期、最新

**函数**：
- `search_web(query, freshness, count)` — 搜索，`freshness` 可选 `oneDay`/`oneWeek`/`oneMonth`

---

# 🖼️ Skill: ImageParser

ImageParser 是一个**图片解析**技能，使用 VL 模型（Qwen3-VL）来理解图片内容。

**文件名称**: `ImageParser.py`
**类型**: 图片解析 / 视觉理解
**能力**: 解析 OSS URL、本地文件、Base64 图片，返回图片内容描述

**适用场景**：
- 需要解析截图、照片、文档图片
- 从 cached/ 历史缓存中主动查找并解析图片
- 用户提供图片 URL 需要 AI 理解

**函数**：
- `parse_image(image_source, prompt=None, max_tokens=2048, temperature=0.7)` — 解析单张图片
- `parse_images_batch(image_sources, prompt=None, ...)` — 批量解析多张图片

**路径解析**：
- 绝对路径、OSS URL、相对路径（默认在 cached/ 下）均支持
- 找不到文件时，错误信息会显示完整解析路径

---

# 📊 Skill: DataAnalysis

数据分析技能。进行数据分析前先查阅 `DataAnalysis.md` 规范获取配置。

**文件名称**: `DataAnalysis.md`

**核心能力**：
- 数据处理与统计分析（pandas / numpy / scipy）
- 图表生成（matplotlib / plotly / seaborn）
- 流程图 / ER 图 / 序列图等可视化（Mermaid 语法）
- 分析脚本持久化与复用

**适用场景**：
- 数据清洗、特征工程、建模分析
- 统计图表生成（折线/柱/饼/热力/箱线等）
- 数据处理结构图（Mermaid 图表）
- 分析报告自动生成

---

## 🔀 混合使用

当单一引擎结果不够时，可以**组合使用**：

- **Tavily + Bocha**：需要快速答案又要新闻广度
- **Exa + Tavily**：既要做深度研究又要实时概况
- **先 Bocha/Tavily 快速确认，再 Exa 深度挖掘**

同时调用多个引擎的例子：
```python
tavily_result = tavily_search("某话题", search_depth="basic", max_results=3)
exa_result = exa_search("某话题深度分析", num_results=5)
```

---

***对于没有在本文件备注的技能目录或者技能脚本则自行探索使用***

---