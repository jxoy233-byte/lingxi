# 数据分析技能规范

## 导入

```python
from ChatMe.ChatDataAnalysis.format import ChatDataAnalysisFormat
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
config = da.get_config()
OUTPUT_DIR = config["output_dir"]  # 例如: cached/{session_id}/data_analysis/gen_001/
```

### Step 4: 编写分析代码（重要）

**⚠️ 同一个分析任务中，不要重复创建 ChatDataAnalysisFormat 实例或重复调用 get_config()，每次调用 get_config() 都复用同一个 OUTPUT_DIR。**

**数据分析可以选择包含mermaid图**：在分析过程中，同步生成数据处理流程图（graph）或 ER 关系图（erDiagram），用于可视化业务流程和数据关系，帮助理解分析逻辑。

```python
# ✅ 正确写法 - 一次初始化，全程复用 OUTPUT_DIR
da = ChatDataAnalysisFormat(session_id=session_id)
config = da.get_config()
OUTPUT_DIR = config["output_dir"]
# 后续所有代码全部使用 OUTPUT_DIR，不再调用 da.get_config()
```

**如果需要开启新一轮分析（新的一批图表/报告），显式调用 new_generation()：**
```python
gen = da.new_generation()  # 显式自增，返回新的 gen_xxx
OUTPUT_DIR = da.base_dir / gen
```

### Step 5: 在 AI 回复中引用生成的文件

**本地文件** (文件在 cached/ 目录下):
```
[[cached/{session_id}/data_analysis/gen_xxx/charts/xxx.png]]
[[cached/{session_id}/data_analysis/gen_xxx/charts/xxx.html]]
[[cached/{session_id}/data_analysis/gen_xxx/charts/xxx.mmd]]  # Mermaid 语法文件
[[cached/{session_id}/data_analysis/gen_xxx/reports/xxx.md]]
```

**路径格式**: cached/{session_id}/data_analysis/gen_xxx/...

### Step 6: (可选) 上传分析结果到 OSS

```python
# 上传单个文件到 OSS，返回 markdown 可用的 URL 格式
oss_url = da.upload_result_to_oss(f"{OUTPUT_DIR}/charts/sales.png")
```

### Step 7: (可选) 删除不满意的结果

```python
da.remove_dir("gen_001")  # 删除指定批次
```

### Step 8: 结束时保存数据分析脚本

分析完成后，把本次最终执行的脚本整合保存到 `scripts/` 目录，便于后续追溯和复用：

```python
script_path = da.save_script("整合后的最终分析代码")
```

下一轮分析时，先读旧脚本再继续：

```python
# 读取上一轮的脚本
with open("cached/{session_id}/data_analysis/gen_001/scripts/script_xxx.py") as f:
    old_code = f.read()
# 基于旧脚本继续分析
```

### Step 9: （可选）生成 mermaid 结构图

当需要可视化数据处理流程或 ER 关系图时，使用 mermaid 语法生成，并**必须保存为 .mmd 文件**（不保存则无法在前端渲染）：

```python
# 生成 mermaid 语法后，直接调用 save_mermaid 保存（内部自动校验语法）
mmd_path = da.save_mermaid("graph TD\\n    A --> B", "flow.mmd")
# 保存路径示例: cached/{session_id}/data_analysis/gen_xxx/charts/flow.mmd
# 在回复中引用: [[mmd_path]]
```

支持的图类型：流程图（graph）、ER 图（erDiagram）、状态图（stateDiagram-v2）、序列图（sequenceDiagram）、甘特图（gantt）等。

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

- `get_config()` 在首次调用时自动获取或创建 gen_001，后续调用复用同一个目录，**不会自增**
- 如果需要开启新一轮分析（新的一批图表/报告），调用 `da.new_generation()` 显式创建新 gen
- 删除操作通过 `da.remove_dir("gen_xxx")` 进行
- AI 根据场景自行决定输出格式（png/svg/html/pdf）和图表参数
- 上传 OSS 后建议使用 OSS URL 便于分享和长期访问
- 对于流程图/ER图可以先使用`ChatDataAnalysisFormat.validate_mermaid(code)`来校验mermaid字符串是否合格
