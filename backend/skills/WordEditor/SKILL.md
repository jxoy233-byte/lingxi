---
name: word_editor
description: 创建和编辑 .docx 文档（Word OOXML）。WPS 与 Microsoft Word 双端可打开。仅支持 .docx；.doc / .wps / .odt 需用户先另存为 .docx
mount: ro
aliases: [WordEditor, word, docx, wps, document, Word文档, doc, 报告, report]
module: skills.WordEditor
---

# WordEditor

## 调用方式

```python
from skills.WordEditor import WordDoc

doc = WordDoc.create("/work/report.docx")    # 或 WordDoc.open(path)
doc.add_paragraph(...)
doc.save()                                     # 或 doc.save("/work/new.docx")
```

## 核心约定（必须记住）

### 写入是 append（追加），不是累加

```python
doc.add_paragraph("A")
doc.add_paragraph("B")    # 第二段，不是合并到 A
```

改 / 删用 `set_paragraph` / `remove_paragraph`，**不要**靠再 add 一次实现覆盖。

### 行号定位（sed 风格）

```python
doc.set_paragraph(N, "新内容", bold=True)        # 改第 N 行（0-based）
doc.add_paragraph("前面插入", at_index=N)         # 在第 N 行前插入
doc.add_paragraph("后面插入", after=anchor_para)   # 锚点后插入（_WordParagraph 对象）
doc.remove_paragraph(N)                          # 删第 N 行
```

`at_index` 和 `after` **互斥**。`get_paragraphs()` 返回列表含表格和占位段——表格后必有占位空段（OOXML 规范）。`set_paragraph(N, ...)` 如果 N 是表格会抛 `OfficeDocError`。

## 典型工作流

```python
from skills.WordEditor import WordDoc

doc = WordDoc.create("/work/q3_report.docx")

doc.add_paragraph("Q3 营收分析报告", style="Title")
doc.add_heading("执行摘要", level=1)
doc.add_paragraph(
    "Q3 营收增长 25%，主要驱动来自海外市场。",
    alignment="justify", line_spacing=1.5, indent_first_line="2字符",
    font="Microsoft YaHei", font_size="小四",
)
doc.add_table(
    rows=4, cols=3,
    data=[["指标", "营收", "同比"], ["Q1", "100M", "+10%"],
          ["Q2", "120M", "+20%"], ["Q3", "150M", "+25%"]],
    header=True, header_fill="4472C4",
)
doc.add_image("/work/charts/q3.png", width="15cm", alignment="center")
doc.save()
```

## 函数清单

### 创建 / 打开 / 保存

| 场景 | 调用 |
|---|---|
| 创建空白 docx | `WordDoc.create(path=None)` |
| 打开已有 | `WordDoc.open(path)` |
| 落盘 | `doc.save(path=None)` |

### 段落 / 标题

| 场景 | 方法 |
|---|---|
| 加段落 | `doc.add_paragraph(text, **format)` |
| 加标题 | `doc.add_heading(text, level=1, **format)` |
| 加分页符 | `doc.add_page_break()` |
| 加字段（PAGE/NUMPAGES） | `doc.add_field(text_before, field_code, text_after, **format)` |
| 改段落 | `doc.set_paragraph(index, text=None, **format)` |
| 删段落 | `doc.remove_paragraph(index)` |
| 链式改格式 | `para = doc.add_paragraph(...); para.set_format(...)` |

**`format` / `indent_*` 完整签名**（含 `style/bold/alignment/line_spacing/indent_*` 中文排版）：`print(WordDoc.add_paragraph.help)`。`indent_*` 支持 `"2字符"`（OOXML `firstLineChars`/`leftChars`）/ `"0.74cm"` / `"12pt"`。

### 表格

| 场景 | 方法 |
|---|---|
| 加表格 | `doc.add_table(rows, cols, *, data, header, header_fill, style)` |
| 取所有表格 | `doc.get_tables() -> list[list[list[str]]]` |

### 图片

| 场景 | 方法 |
|---|---|
| 加图片 | `doc.add_image(path, *, width, height, alignment, alt_text, keep_ratio=True)` |

支持 PNG / JPG / JPEG / GIF / BMP。**不支持** SVG。相同内容（md5 一致）自动去重复用。

### 读取

| 场景 | 方法 |
|---|---|
| 全段落文本 | `doc.get_text()` |
| 段落列表（含表格占位） | `doc.get_paragraphs()` → `[{"index","text","style"}` / `{"index","type":"table","rows"}]` |
| 全文查找替换 | `doc.replace_text(find, replace, replace_all=True, regex=False) -> int` |

`get_paragraphs()` 的 `index` 与 `set_paragraph` / `remove_paragraph` 的 `index` 一致（0-based），**表格也算一个 index**。

## 不要

- 不要处理 `.doc` / `.wps` / `.odt`——提示用户先另存为 `.docx`
- 不要绕过 `WordDoc` 直接操作 zip——会破坏 Content_Types / rels 结构
- 不要在 `save()` 之后又调 `add_image()`（v0.1 限制）
- 不要用 SVG——Word 实际渲染需要 VML 兼容层
- 不要用 placeholder token（`{name}` / `<TODO>` / `lorem`）——这些是 build-time token，必须替换后再交付
- 不要装 MiSans / HarmonyOS Sans SC / OPPO Sans / 阿里普惠体——商用需单独授权；用思源黑体 / 思源宋体 / 系统字体（PingFang SC / Microsoft YaHei）

## 按需查函数详细用法

拿到引用后直接 `.help`（最常用）：

```python
from skills.WordEditor import WordDoc, to_pt, to_rgb
print(WordDoc.add_paragraph.help)    # 完整 docstring（format kwargs / indent_* 中文排版 / Returns / Raises）
print(to_pt.help)                     # 中文字号 → pt
```

不确定方法名时：`from skills.WordEditor import help; help()` 列全部 / `help("WordDoc.add_table")` 单查。

`SKILL.md` 只放最常用 80% 用法 + 极简示例；详细按需拿 `.help`，避免 SKILL.md 膨胀。