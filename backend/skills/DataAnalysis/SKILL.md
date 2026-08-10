---
name: data_analysis
description: 数据分析（pandas / matplotlib / mermaid / 数据库只读查询）
mount: rw
aliases: [DataAnalysis, pandas, numpy, matplotlib, chart, visualization, SQL, MySQL, MongoDB, database, CSV, plot]
module: skills.DataAnalysis
---

# 数据分析技能规范

> 方法签名 / 边界条件见 `ChatDataAnalysisFormat` docstring（`format.py`）。

## 技能索引

| 场景 | 方法 |
|---|---|
| 初始化 | `da = ChatDataAnalysisFormat(session_id=session_id)` |
| 输入文件（绝对路径） | `INPUT = ChatDataAnalysisFormat.get_file_dir("cached/{sid}/xxx.suffix/.../file.suffix")` |
| 输出目录（首次自建 gen_001） | `OUTPUT_DIR = da.output_dir` |
| 新一轮分析（自增批次） | `gen = da.new_generation(); OUTPUT_DIR = str(da.base_dir / gen)` |
| 画图 header（抑制 warning） | `da.get_data_analysis_header()` |
| 画图 header（注册字体） | `da.get_fonts_setup_header()` |
| 保存数据 csv / json / txt | `da.save_data(content, "name.csv")` |
| 保存报告 md（续写 mode="a"） | `da.save_report(content, "report.md", mode="w")` |
| 保存脚本（可追溯） | `da.save_script(code)` |
| 保存 Mermaid 流程图 / ER 图 | `da.save_mermaid(mmd_code, "flow.mmd")` |
| 校验文件可访问 | `da.check_static_file(path)` → `{accessible, status_code, error}` |
| 删除指定批次 | `da.remove_dir("gen_xxx")` |

## 典型工作流

```python
# 1) 初始化（每会话只调一次；重复 init 会复用同一 gen_001）
da = ChatDataAnalysisFormat(session_id=session_id)

# 2) 输入文件 → 绝对路径（不存在时在 cached/ 下按文件名递归搜）
INPUT = ChatDataAnalysisFormat.get_file_dir("cached/{sid}/datasets/q1.csv")

# 3) 选 generation
#    - 同会话连续多次分析：复用 output_dir（首次访问自建 gen_001，不自增）
#    - 用户要"重做 / 换一批"：调 new_generation() 进 gen_002
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

## 长报告分块写入

单次 `code()` 受 LLM max_tokens 限制，长报告必须分块：

```python
da.save_report(intro,    "report.md")                # mode="w" 创建
da.save_report(section1, "report.md", mode="a")     # 续写
da.save_report(section2, "report.md", mode="a")     # 续写
```

Markdown 段落分隔建议在 content 末尾留 `\n\n`。

## Header 拼接

```python
code = da.get_data_analysis_header() + da.get_fonts_setup_header() + "<用户代码>"
```

`get_data_analysis_header` 抑制 warning（省 token），`get_fonts_setup_header` 注册中英文字体（避免中文 tofu）。

## 路径格式

`da.save_*` 返回的路径形如 `/.../backend/cached/{sid}/data_analysis/gen_xxx/charts/xxx.png`。
AI 在回复里引用产物时，用 `[[cached/{sid}/data_analysis/gen_xxx/...]]` 语法（去掉 `backend/` 前缀）：

```
[[cached/{session_id}/data_analysis/gen_xxx/charts/xxx.png]]
[[...(同上)/charts/xxx.html]]
[[...(同上)/charts/xxx.mmd]]
[[...(同上)/data/xxx.csv]]
[[...(同上)/reports/xxx.md]]
```

`check_static_file` 的 `path` 参数也用同款格式（不带 `backend/` 前缀，相对 `/static/`）。

## 目录结构

```
cached/{sid}/data_analysis/{gen_xxx}/
├── charts/      ← .png / .html / .mmd
├── data/        ← .csv / .json / .txt
├── reports/     ← .md
└── scripts/     ← 保存的可执行脚本
└── _meta.json   ← generation 计数
```

## 数据库分析能力（按需动态加载）

本 skill 默认不展示数据库相关细节。DataAnalysis agent 只在用户提到数据库、SQL、数据表、MySQL、PostgreSQL、MongoDB、SQLite 等关键词时，才按下面的方式动态加载数据库模块文档。

```python
cmd("cat /skills/DataAnalysis/database/SKILL.md")
```

加载完成后，数据库配置、只读查询、schema 探索、SQL/MongoDB 示例、结果落盘、SQL 方言选择等全部由 `skills/DataAnalysis/database/SKILL.md` 提供。本 skill 不在此处复制粘贴数据库相关函数和示例，避免占用上下文 token。

加载数据库子文档后再继续后续步骤：检查 `list_database_configs()`、必要时中断询问用户、调用 `save_database_config()`、用 `query_sql()` / `query_mongo()` 探索结构与抽取数据、最后把结果转成 `pandas.DataFrame` 并交给本 skill 的 `ChatDataAnalysisFormat` 落盘和分析。

如果用户的问题与数据库无关，不要加载该子文档。




- **不要重复 `ChatDataAnalysisFormat(session_id)`** 或重复访问 `da.output_dir`（会复用同一 `gen_001`，不自增）
- **不要绕过 `da.save_*` 直接 `open()` 写文件**（绕过 generation 管理 + 路径校验）
- **不要**装 MiSans / HarmonyOS Sans SC / OPPO Sans / 阿里普惠体（商用需单独授权）
- **不要**在 `check_static_file` 报错时仍引用 `[[path]]`（用户会看到 broken image）