---
name: excel_editor
description: 创建 / 编辑 Excel 表格。支持单元格、批量数据、公式、格式、Sheet 管理、CSV 互转。仅 .xlsx
mount: ro
aliases: [ExcelEditor, excel, xlsx, spreadsheet, Excel表格, 数据表, table, sheet]
module: skills.ExcelEditor
---

# ExcelEditor

## 调用方式

```python
from skills.ExcelEditor import ExcelDoc

doc = ExcelDoc.create("/cached/{sid}/sales.xlsx", sheet_name="Q3")
doc.write_table("A1", data, header=True)
doc.save()

doc = ExcelDoc.open("/cached/{sid}/existing.xlsx")
doc.read_table("A1", "D10")

# CSV ↔ xlsx
doc = ExcelDoc.from_csv("/cached/data.csv", "/cached/data.xlsx", header=True)
doc.to_csv("/cached/report.csv")
```

## 核心约定

- **路径**：推荐 sid-scoped `/cached/{session_id}/X.xlsx`——前端 inline preview 能看、能编辑保存
- **内容精确性**：数字按 number 存（**不**自动转字符串）；字符串原样存（**不**自动转 number）；datetime 自动 `yyyy-mm-dd` 格式（可改 `date_format`）；None 写入空单元格（**不是** `"None"`）；公式写字符串，不计算（Excel/WPS 打开后自动算）
- **CSV 互转**：`encoding="utf-8-sig"` 自动处理 BOM（Excel 中文常见）；`csv.reader` quote-aware 自动处理字段内 `,`；空行 / CRLF 自动归一

## 函数清单

| 场景 | 方法 |
|---|---|
| 创建空白 xlsx | `ExcelDoc.create(path=None, sheet_name="Sheet1")` |
| 打开已有 | `ExcelDoc.open(path)` |
| 落盘 | `doc.save(path=None)` |
| CSV → xlsx | `ExcelDoc.from_csv(csv_path, xlsx_path=None, header=True, delimiter=",", encoding="utf-8-sig")` |
| xlsx → CSV | `doc.to_csv(path, sheet_name=None, delimiter=",", encoding="utf-8-sig")` |
| 加 / 切 / 列 / 删 / 重命名 sheet | `add_sheet(name)` / `select_sheet(name)` / `sheets()` / `delete_sheet(name)` / `rename_sheet(old, new)` |
| 冻结 / 自动筛选 | `freeze_cells(cell_ref)` / `autofilter(range_ref)` |
| 批量写二维数据 | `doc.write_table(start_cell, data, *, header, header_fill, header_color, number_formats, date_format, date_columns)` |
| 单格写值 + 格式 | `doc.set_cell(cell_ref, value, *, number_format, bold, italic, font, font_size, font_weight, color, fill, alignment)` |
| 写公式 | `doc.add_formula(cell_ref, formula)` |
| 插入 / 删除行 | `doc.insert_row(idx)` / `doc.delete_row(idx)`（**公式不自动 shift**） |
| 读二维 / dict-of-list / 单格 | `read_table(start_cell, end_cell=None)` / `get_table_as_dicts(start_cell)` / `get_cell(cell_ref)` |
| 列宽 / 行高 | `set_column_width(col, width)` / `set_row_height(row_idx, height)` |
| 合并 / 已用范围 | `merge_cells("A1:D5")` / `used_range()` |

## 注意事项

- **`from_csv` 中文乱码**：试试 `encoding="gbk"`（Excel 中文导出常用）
- **不要**依赖 `data_only=True` 读"计算后值"——文件需先用 Excel 打开过才有缓存

## 按需查函数详细用法

```python
print(ExcelDoc.create.help)         # 完整 docstring
print(ExcelDoc.from_csv.help)       # CSV → xlsx 详细参数
print(ExcelDoc.set_cell.help)       # 单格写值 + 格式完整 kwargs
print(to_pt.help) / print(to_rgb.help)  # 中文字号 / 颜色
```

不确定方法名：`help()` 列全部 / `help("ExcelDoc.from_csv")` 单查。

`SKILL.md` 只放最常用 80% 用法 + 极简示例；详细按需拿 `.help`，避免 SKILL.md 膨胀。