---
name: word_editor
description: 创建 / 编辑 Word 文档。支持段落、标题、表格、图片、分页符、字段、markdown。仅 .docx
mount: ro
aliases: [WordEditor, word, docx, wps, document, Word文档, doc, 报告, report]
module: skills.WordEditor
---

# WordEditor

```python
from skills.WordEditor import WordDoc

doc = WordDoc.create("/cached/{sid}/report.docx")   # 或 WordDoc.open(path)
doc.add_markdown("# 标题\n\n正文 **加粗** [color=red]红字[/color]")
doc.save()
```

## 核心约定

- **路径**：sid-scoped `/cached/{session_id}/X.docx`——前端能预览能编辑保存；flat `/cached/X.docx` 只能看
- **写入是 append**，不累加；改 / 删已有内容见下方「改删」段
- **改删先拿句柄**：`get_text()` / `get_tables()` 是只读快照，改表格图片必须 `get_table(i)` / `get_picture(i)`——`open()` 打开的旧文档也拿得到
- **行号 0-based**（表格占一个 index）：`set_paragraph(N)` / `remove_paragraph(N)` / `remove_last(n)` / `add_paragraph(text, at_index=N)` / `add_paragraph(text, after=para)`。后两个互斥
- **`get_paragraphs()` 每项带 `type`** ∈ `paragraph / image / page_break / field / table`；图片段和分页符段 `text` 是空串，只能靠 `type` 认。注意表格项只有 `index / type / rows`，**没有 `text`**——遍历时用 `p.get("text")`

## 段内多 run 样式

`add_paragraph(text, bold=True)` 是整段一种样式。要混合用 `runs=[{text, ...}, ...]`：

```python
doc.add_paragraph(
    runs=[{"text": "重要", "bold": True, "color": "red"},
          {"text": "通知：", "color": "595959"},
          {"text": "明日下午 3 点开会。", "highlight": "yellow"}],
    alignment="center", font="Microsoft YaHei",   # 段落级 kwargs 照常生效
)
```

**runs key**：`text / bold / italic / underline / font / font_size / font_weight / color / highlight`。与 run 级 kwargs 同时传时 `runs` 优先；未知 key 静默丢弃；入参列表不会被改写（可复用给多个段落）。链式：`para.add_runs()` 追加 / `para.set_runs()` 替换（留 pPr）/ `para.set_format(**kw)`。

## Markdown 写入

```python
doc.add_markdown("""
# Q3 报告

| 建议 | 收益 | 难度 |
|:---|---:|---:|
| 压到提升复购 | ★★★★★ | 中 |

- 沉默高值客户定向召回
- [x] Silver 权益重设计
""")
```

**语法**：行内 `**b** / *i* / __u__ / ~~s~~ / [key=val]x[/key]`（key ∈ `color/highlight/size/font`，open-only `[color=red]x` 延伸到段末）；块级 `#` ~ `######` / 空行分段 / `> 引用`（连续行合并）/ **表格**（`| a | b |` + `|---|---:|` 分隔行，`---:` 右对齐、`:---:` 居中，单元格走行内解析）/ **列表**（`- * +` 无序，`1. 2)` 保留原编号，`- [ ]` `- [x]` → ☐ ☑，缩进 0~3 共 4 档）/ **反引号围栏代码块**（等宽 9pt，不解析行内语法）/ `---` 跳过。表格不必空行隔开，嵌在段落中间也能认。

**kwarg**：`base_style` 段落默认 style / `alignment` / `heading_levels`（`{1: "Title"}` 重映射）/ `table_style` / `table_header_fill`（默认 None = 表头只加粗）。

**容错**：未匹配的 `*` / `[` 按字面量，不抛异常。单次写整篇、无 typewriter 节奏，要流式就手动 `add_paragraph` + 分段 `save()`。`parse_inline()` 返回 `list[dict]`，可直接喂 `runs=`；速查 `print(supported_syntax.help)`。

## 改删

表格图片的改删都走句柄，句柄上的方法可链式调。

| 场景 | 方法 |
|---|---|
| 取句柄 | `doc.get_table(i=0)` / `doc.get_picture(i=0)`（pic 的 `.path` 是 alt 文字） |
| 改单元格 | `tbl.set_cell(row, col, value, *, runs, **fmt)` |
| 插 / 删行 | `tbl.insert_row(at, values)` · `tbl.add_row(values)` · `tbl.remove_row(row)` |
| 插 / 删列 | `tbl.insert_col(at, values)` · `tbl.remove_col(col)`（列宽自动重算） |
| 改表格样式 | `tbl.set_style("TableGrid")`（只注册了 `TableNormal` / `TableGrid`） |
| 删整张表 | `tbl.remove()` |
| 改尺寸 / 删图片 | `pic.set_size(width, height, keep_ratio=True)` · `pic.remove()` |
| 改 / 删段落 | `doc.set_paragraph(i, text=None, *, runs=None, **fmt)` · `doc.remove_paragraph(i)` |
| 删末尾 n 个 | `doc.remove_last(n=1)` |
| 全文替换 | `doc.replace_text(find, replace, replace_all=True, regex=False) -> int` |

不能删表格最后一行 / 最后一列（OOXML 要求），要删整张请用 `remove()`。`replace_text` 在多 run 段落上会合并成一个 run，多 run 段落慎用。

## 函数清单

| 场景 | 方法 |
|---|---|
| 加段落 | `doc.add_paragraph(text, **format)` · `doc.add_paragraph(runs=[...], **format)` |
| 加标题 | `doc.add_heading(text, level=1, **format)` |
| 加分页符 | `doc.add_page_break()` |
| 加字段（PAGE/NUMPAGES/TOC） | `doc.add_field(text_before, field_code, text_after, **format)` |
| 写 markdown | `doc.add_markdown(md_text, *, base_style, alignment, heading_levels, table_style, table_header_fill)` |
| 加表格 | `doc.add_table(rows, cols, *, data, header, header_fill, alignments, style)` |
| 加图片 | `doc.add_image(path, *, width, height, alignment, alt_text, keep_ratio=True)` |
| 读取 | `doc.get_text()` · `doc.get_paragraphs()` · `doc.get_tables()` |
| 改删 | 见上方「改删」段 |

`format` 完整签名 `print(WordDoc.add_paragraph.help)`，含 `style / bold / italic / alignment / line_spacing / indent_*`（`indent_*` 支持 `"2字符"` / `"0.74cm"` / `"12pt"`）。表格 `data` / `values` 单元格可以是 `str` 或 `list[dict] runs`（保留单元格内 `**加粗**` / `[color=red]`）；`alignments` 每列 `left/center/right`，短了补 left、非法值忽略。图片仅 PNG/JPG/JPEG/GIF/BMP，同内容（md5 一致）自动去重。

## 不要

- 不要处理 `.doc` / `.wps` / `.odt`——提示用户先另存为 `.docx`
- 不要绕过 `WordDoc` 直接操作 zip——会破坏 Content_Types / rels
- 不要用 SVG——Word 实际渲染需要 VML 兼容层
- 不要用 placeholder token（`{name}` / `<TODO>` / `lorem`）——必须替换后再交付
- 不要装 MiSans / HarmonyOS Sans SC / OPPO Sans / 阿里普惠体——商用需单独授权；用思源黑体 / 思源宋体 / 系统字体
- 不要传未注册的 `style` 名——`STYLES_XML` 只有 `Normal` / `Title` / `Heading1-9` / `Quote` / `TableNormal` / `TableGrid`，其他**静默无效**
- 改完 / 加完记得**再 `save()` 一次**

## 按需查

```python
from skills.WordEditor import to_pt, to_rgb, parse_inline, parse_blocks, supported_syntax

print(WordDoc.add_paragraph.help)   # format kwargs / Returns / Raises
print(supported_syntax.help)        # 完整 markdown 语法
```

`help()` 列全部 / `help("WordDoc.add_table")` 单查。本文件只放最常用 80% 用法，细节按需拿 `.help`。
