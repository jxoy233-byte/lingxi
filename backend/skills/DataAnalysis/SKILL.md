# 数据分析技能规范

> 本文件是 DataAnalysis skill 的 AI 可读规范。完整方法签名 / 边界条件见
> `skills.DataAnalysis.ChatDataAnalysisFormat` 的 docstring。

- *合理使用包装好的函数*

## 导入

```python
from skills.DataAnalysis import ChatDataAnalysisFormat
```

## 使用流程

### Step 1: 初始化

```python
da = ChatDataAnalysisFormat(session_id=session_id)
```

### Step 2: 获取输入文件

```python
# 自动校验并获取输入文件路径（绝对路径）
INPUT_FILE = ChatDataAnalysisFormat.get_file_dir("cached/{session_id}/xxx.suffix_xxx/xxx.suffix")
```

### Step 3: 获取输出目录

```python
OUTPUT_DIR = da.output_dir  # 例如: cached/{session_id}/data_analysis/gen_001/
```

### Step 4: 编写分析代码（重要）

**⚠️ 同一个分析任务中，不要重复创建 ChatDataAnalysisFormat 实例或重复访问 `output_dir` 属性，多次访问会复用同一个 generation。**

**数据分析可以选择包含mermaid图**：在分析过程中，同步生成数据处理流程图（graph）或 ER 关系图（erDiagram），用于可视化业务流程和数据关系，帮助理解分析逻辑。

**Tip - 抑制无关警告**：代码顶部拼接 `ChatDataAnalysisFormat.get_data_analysis_header()`，静默 pandas / numpy / matplotlib 的常见 warning。

```python
# ✅ 正确写法 - 一次初始化，全程复用 OUTPUT_DIR
da = ChatDataAnalysisFormat(session_id=session_id)
OUTPUT_DIR = da.output_dir
# 后续所有代码全部使用 OUTPUT_DIR，不再访问 da.output_dir
```

**如果需要开启新一轮分析（新的一批图表/报告），显式调用 new_generation()：**
```python
gen = da.new_generation()  # 显式自增，返回新的 gen_xxx
OUTPUT_DIR = str(da.base_dir / gen)
```

### Step 5: 保存分析文件（强制 da.save_*）

**Core：保存文件必须使用 ChatDataAnalysisFormat 提供的方法**

```python
# 保存数据文件（如 CSV、JSON、TXT 等文本格式）
data_path = da.save_data("id,name,value\n1,foo,100\n2,bar,200", "result.csv")
# 保存报告文件（Markdown 或纯文本）
# 长报告分块写入，避免单次 code() 调用超 max_tokens 导致 SyntaxError
report_path = da.save_report("# 分析报告\n\n结论：...", "report.md")              # mode="w" 创建（默认）
report_path = da.save_report("## 第二章\n\n...", "report.md", mode="a")            # 续写到末尾
# Markdown 段落分隔建议在 content 末尾留 \n\n
# 保存分析脚本（可追溯脚本执行）
script_path = da.save_script("print('hello world')")
# 保存 Mermaid 图表（.mmd 文件，前端可渲染）
mmd_path = da.save_mermaid("graph TD\n    A --> B", "flow.mmd")
```

### Step 6: 确保文件路径符合 AI 后续自定义语法格式
**路径格式**: cached/{session_id}/data_analysis/gen_xxx/...

```
[[cached/{session_id}/data_analysis/gen_xxx/charts/xxx.png]]
[[...(同上)/charts/xxx.html]]
[[...(同上)/charts/xxx.mmd]]  # Mermaid 语法文件
[[...(同上)/data/xxx.csv]]    # 数据文件
[[...(同上)/reports/xxx.md]]   # 报告文件
```
**Tip - 验证文件可访问**：生成文件后调用 `ChatDataAnalysisFormat.check_static_file(path)` 校验。返回 `{accessible, status_code, error}`：`accessible=True` 即 OK；`accessible=False` 时读 `error`（ `[类型] 描述 | 建议`）。

### Step 7: (可选) 删除不满意的结果

```python
da.remove_dir("gen_001")  # 删除指定批次
```

### Step 8: 保存分析结果后下一轮分析复用（看需选择）

分析完成后，确保所有结果都已通过 Step 5 的方法保存。若需复用上一轮脚本：

```python
# 读取上一轮的脚本
with open("cached/{session_id}/data_analysis/gen_001/scripts/script_xxx.py") as f:
    old_code = f.read()
# 基于旧脚本继续分析
```

```
cached/
└── {session_id}/
    └── data_analysis/
        ├── gen_001/
        │   ├── charts/
        │   ├── data/
        │   ├── reports/
        │   └── scripts/
        ├── gen_002/
        │   └── ...
        └── _meta.json          # generation 计数器
```

## 注意事项

- `output_dir` 属性在首次访问时自动获取或创建 gen_001，后续访问复用同一个目录，**不会自增**
- 如果需要开启新一轮分析（新的一批图表/报告），调用 `da.new_generation()` 显式创建新 gen
- 删除操作通过 `da.remove_dir("gen_xxx")` 进行
- AI 根据场景自行决定输出格式（png/svg/html/pdf）和图表参数
- 对于流程图/ER图要使用`da.save_mermaid(code)`来保存mmd文件来后续调用