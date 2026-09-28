---
name: data_analysis
description: 数据分析与可视化：表格 / CSV 处理、统计图表、可视化报告生成、数据库只读查询
mount: rw
aliases: [DataAnalysis, pandas, numpy, matplotlib, chart, visualization, SQL, MySQL, MongoDB, database, CSV, plot]
module: skills.DataAnalysis
---

# 数据分析技能规范

## 技能索引

| 场景 | 方法 |
|---|---|
| 初始化 | `da = ChatDataAnalysisFormat(session_id=session_id)` |
| 输入文件（绝对路径） | `INPUT = ChatDataAnalysisFormat.get_file_dir("cached/{sid}/xxx.suffix/.../file.suffix")` |
| 输出目录（首次自建 gen_001） | `OUTPUT_DIR = da.output_dir` |
| 新一轮分析（自增批次） | `gen = da.new_generation(); OUTPUT_DIR = str(da.base_dir / gen)` |
| 画图 header（抑制 warning） | `da.get_data_analysis_header()` |
| 画图 header（注册字体） | `da.get_fonts_setup_header()` |
| 保存数据 csv / json / txt | `da.save_data(content, "name.csv")`（filename 需含后缀） |
| 保存报告 md（续写 mode="a"） | `da.save_report(content, "report.md", mode="w")` |
| 保存脚本（filename 缺省自动 `script_{ts}.py`） | `da.save_script(code)` |
| 保存 Mermaid 流程图 / ER 图 | `da.save_mermaid(mmd_code, "flow.mmd")` |
| 校验文件可访问（HTTP `/static/path`） | `da.check_static_file(path)` → `{accessible, status_code, error}` |
| 删除指定批次（真删不可恢复） | `da.remove_dir("gen_xxx")` |
| 归档二进制 / 任意文件 | `da.save_path(src_path, target_subdir="exports", *, action="mv", filename=None)` |

### gen 子目录约定

`save_*` 方法各自落到 `gen_xxx/{子目录}/`：

| 子目录 | 内容 | 对应方法 |
|---|---|---|
| `charts/` | `.png` / `.html` / `.mmd` | matplotlib / plotly / `save_mermaid` |
| `data/` | `.csv` / `.json` / `.txt` | `save_data` |
| `reports/` | `.md` | `save_report` |
| `scripts/` | `.py` | `save_script` |
| `exports/` | `.xlsx` / `.docx` 等二进制 | `save_path` |

## 典型工作流

```python
# 1) 初始化（每会话只调一次；重复 init 会复用同一 gen_001）
da = ChatDataAnalysisFormat(session_id=session_id)

# 2) 输入文件 → 绝对路径（不存在时在 cached/ 下按文件名递归搜）
INPUT = ChatDataAnalysisFormat.get_file_dir("cached/{sid}/datasets/q1.csv")

# 3) 选 generation
#    - 同会话连续多次分析：复用 output_dir（首次访问自建 gen_001，不自增）
#    - 用户要"重做 / 换一批"：调 new_generation() 进 gen_002
#    - **new_generation() 后用返回的 `gen` 拼路径**，不要再调 `da.output_dir`（会拿到旧 gen）
OUTPUT_DIR = da.output_dir

# 4) 拼 code() 入参（两个 header 顺序无关，都 prepend 到顶部）
code = (
    da.get_data_analysis_header()
    + da.get_fonts_setup_header()
    + f'''
import pandas as pd
df = pd.read_csv(r"{INPUT}")
# ... 业务代码（save_* 调用可直接放在这里，返回路径供后续 [[path]] 引用）...
'''
)

# 5) 落盘产物 —— save_* 返回的是绝对路径，自带 cached/{sid}/ 前缀
csv_path = da.save_data(df.to_csv(index=False), "q1_summary.csv")
md_path  = da.save_report("# 分析报告\n\n## 结论 ...", "report.md")
mmd_path = da.save_mermaid("graph LR; A-->B", "flow.mmd")

# 6) 校验文件可访问（防止路径错 / 服务端未启 / 文件未生成）
result = da.check_static_file("cached/{sid}/data_analysis/gen_001/data/q1_summary.csv")
if not result["accessible"]:
    print(result["error"])  # `[类型] 描述 | 建议`，可直接 parse

# 7) AI 回复用户前，把已运行的 code() 字符串存档（可追溯）
da.save_script(code)

# 8) 删除批次（清理 / 回滚旧结果）
da.remove_dir("gen_001")
```

## 路径格式

- 沙盒内绝对路径 `/work/foo.xlsx` ↔ 主进程 `cached/{sid}/work/foo.xlsx`；相对路径 `work/foo.xlsx` 等价
- AI 回复里引用产物用 `[[cached/{sid}/work/foo.xlsx]]`（**不带** `backend/` 前缀）
- `da.check_static_file` 的 `path` 也用同款格式（不带 `backend/` 前缀，相对 `/static/`）

## 数据库分析（按需）

用户提到数据库 / SQL / MySQL / PostgreSQL / MongoDB / SQLite 等关键词时，加载子文档：

```python
cmd("cat /skills/DataAnalysis/database/SKILL.md")
```

数据库配置、查询、schema 探索由子文档提供。不相关时不要加载。

## 文档生成（按需）

用户明确要 Word / xlsx 时（关键词：Word 报告 / .docx / .xlsx / Excel 表格 / WordEditor / ExcelEditor）：

1. `find_skill(query="WordEditor" / "ExcelEditor")` + `cmd("cat /skills/X/SKILL.md")` 加载对应 skill，按 SKILL.md 调对应类生成 .docx / .xlsx（落到 `/work/foo.ext`）
2. `da.save_path("/work/foo.ext", "exports")` 归档到 `data_analysis/{gen}/exports/`（默认 mv，源文件移走）

DataAnalysis 出图（matplotlib PNG / plotly HTML）可作为 `WordEditor.add_image()` 输入；`save_data` 出的 csv 可经 `ExcelDoc.from_csv()` 转 xlsx。

## 按需查函数详细用法

拿到引用后直接 `.help`（最常用）：

```python
from skills.DataAnalysis.format import ChatDataAnalysisFormat
print(ChatDataAnalysisFormat.save_data.help)        # content/filename/返回值
print(xxx.save_path.help)        # src_path/action="cp"/mv + target_subdir
print(xxx.check_static_file.help) # 探活 /static/ 完整返回字段
```

不确定方法名时：`from skills.DataAnalysis.format import help; help()` 列全部 / `help("ChatDataAnalysisFormat.save_data")` 单查。

`SKILL.md` 只放最常用 80% 用法 + 极简示例；详细按需拿 `.help`，避免 SKILL.md 膨胀。

## 不要

- **不要重复 `ChatDataAnalysisFormat(session_id)`** 或重复访问 `da.output_dir`（会复用同一 `gen_001`，不自增）
- **不要绕过 `da.save_*` 直接 `open()` 写文件**（绕过 generation 管理 + 路径校验）
- **不要**用 `save_report` / `save_data` 存 `.xlsx` / `.docx` 等二进制文件——它们只支持文本写入；二进制文件用 WordEditor / ExcelEditor 生成后 `da.save_path(...)` 归档
- **不要**装 MiSans / HarmonyOS Sans SC / OPPO Sans / 阿里普惠体——商用需单独授权；用思源黑体 / 思源宋体 / 系统字体（PingFang SC / Microsoft YaHei）
- **不要**在 `check_static_file` 报错时仍引用 `[[path]]`（用户会看到 broken image）