---
name: excel_editor
description: 创建和编辑 .xlsx 表格（Excel OOXML）。基于 openpyxl，内容精确性（数字格式 / 日期 / 公式 / CSV 互转 quote-aware + BOM 处理）。仅支持 .xlsx；.xls / .csv 需先转换
mount: ro
aliases: [ExcelEditor, excel, xlsx, spreadsheet, Excel表格, 数据表, table, sheet]
module: skills.ExcelEditor
---

# ExcelEditor

基于 `openpyxl` 读写 `.xlsx`。

## 调用方式

```python
from skills.ExcelEditor import ExcelDoc

# 创建 / 打开
doc = ExcelDoc.create("/cached/sales.xlsx", sheet_name="Q3")
doc.write_table("A1", data, header=True)
doc.save()
doc = ExcelDoc.open("/cached/existing.xlsx")
text = doc.read_table("A1", "D10")

# CSV ↔ xlsx
doc = ExcelDoc.from_csv("/cached/data.csv", "/cached/data.xlsx", header=True)
doc.save()
doc.to_csv("/cached/report.csv")
```

## 核心约定（必须记住）

### 1. 内容精确性

- **数字**：整数 / 浮点按 number 存储，**不会被自动转字符串**
- **字符串**：原样存（**不会**自动转 number）
- **datetime**：自动应用 `yyyy-mm-dd` 格式（可改）
- **None**：写入空单元格，**不是** `"None"` 字符串
- **公式**：写公式字符串，不计算（Excel/WPS 打开后自动计算）

### 2. CSV 互转

- **BOM**：`encoding="utf-8-sig"` 自动处理 UTF-8 BOM（Excel 中文导出常见）
- **Quote-aware**：字段内可有 `,`（"Doe, John"）—— `csv.reader` 自动处理
- **空行 / CRLF**：自动归一化

## 典型工作流

```python
from skills.ExcelEditor import ExcelDoc
import datetime

doc = ExcelDoc.create("/cached/q3_report.xlsx", sheet_name="Q3")
doc.write_table("A1", [
    ["日期", "产品", "金额", "客户"],
    [datetime.date(2026, 9, 1), "Pro", 12500, "ACME"],
    [datetime.date(2026, 9, 2), "Basic", 3200, "Beta"],
    [datetime.date(2026, 9, 3), "Pro", 8800, "Gamma"],
], header=True, header_fill="4472C4")

doc.add_formula("C5", "=SUM(C2:C4)")
doc.add_formula("C6", "=AVERAGE(C2:C4)")
doc.save()
```

## 函数清单

### 创建 / 打开 / 保存 / 转换

- `ExcelDoc.create(path=None, sheet_name="Sheet1")` —— 创建空白 xlsx
- `ExcelDoc.open(path)` —— 打开已有
- `doc.save(path=None)` —— 落盘
- `ExcelDoc.from_csv(csv_path, xlsx_path=None, header=True, delimiter=",", encoding="utf-8-sig")` —— CSV → xlsx
- `doc.to_csv(path, sheet_name=None, delimiter=",", encoding="utf-8-sig")` —— xlsx → CSV

### Sheet 管理

- `doc.add_sheet(name)` —— 加 sheet（自动切换为新 sheet）
- `doc.select_sheet(name)` —— 切换 sheet
- `doc.sheets()` —— 列出所有 sheet
- `doc.delete_sheet(name)` —— 删 sheet
- `doc.rename_sheet(old, new)` —— 重命名 sheet
- `doc.freeze_cells(cell_ref)` —— 冻结首行 / 列（如 `"A2"` 冻结首行）
- `doc.autofilter(range_ref)` —— 自动筛选（如 `"A1:D100"`）

### 数据写入

- `doc.write_table(start_cell, data, *, header=False, header_fill=None, header_color="FFFFFF", number_formats=None, date_format="yyyy-mm-dd", date_columns=None)` —— 批量写二维数据
- `doc.set_cell(cell_ref, value, *, number_format=None, bold, italic, font, font_size, font_weight, color, fill, alignment)` —— 单格写值+格式（数字设 `number_format="0.00"` 避免科学计数）
- `doc.add_formula(cell_ref, formula)` —— 写公式
- `doc.insert_row(row_idx)` / `doc.delete_row(row_idx)` —— 插入 / 删除行（**公式不自动 shift**）

### 数据读取

- `doc.read_table(start_cell="A1", end_cell=None)` —— 读二维数组
- `doc.get_table_as_dicts(start_cell="A1")` —— 读 list[dict]（第一行作字段名）
- `doc.get_cell(cell_ref)` —— 单格读值

### 行列 / 样式

- `doc.set_column_width(col, width)` / `doc.set_row_height(row_idx, height)` —— 列宽 / 行高
- `doc.merge_cells("A1:D5")` —— 合并单元格
- `doc.used_range()` —— 用过的范围

## 注意事项

- **`from_csv` 中文乱码**：试试 `encoding="gbk"`（Excel 中文导出常用）
- **不要**依赖 `data_only=True` 读"计算后值"——文件需先用 Excel 打开过才有缓存

## 按需查函数详细用法

拿到引用后直接 `.help`（最常用）：

```python
from skills.ExcelEditor import ExcelDoc, to_pt, to_rgb
print(ExcelDoc.create.help)         # 完整 docstring
print(ExcelDoc.from_csv.help)       # CSV → xlsx 详细参数
print(to_pt.help)                    # 中文字号 → pt
```

不确定方法名时：`from skills.ExcelEditor import help; help()` 列全部 / `help("ExcelDoc.from_csv")` 单查。

`SKILL.md` 只放最常用 80% 用法 + 极简示例；详细按需拿 `.help`，避免 SKILL.md 膨胀。