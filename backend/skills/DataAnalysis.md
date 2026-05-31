from ChatMe.ChatDataAnalysis.format import ChatDataAnalysisFormat

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
CONFIG = da.get_config()
OUTPUT_DIR = CONFIG["output_dir"]  # 例如: cached/{session_id}/data_analysis_output/gen_001/
```

### Step 4: 编写分析代码

将分析结果保存到 `OUTPUT_DIR` 下的对应子目录：

```
{OUTPUT_DIR}/charts/     # 图表文件 (png/svg/html)
{OUTPUT_DIR}/data/      # 数据文件 (csv/json)
{OUTPUT_DIR}/reports/   # 报告文件 (md/html)
```

### Step 5: 删除不满意的结果 (可选)

```python
da.remove_dir("gen_001")  # 删除指定批次
```

### Step 6: 上传数学分析结果到oss (可选)

```python
file_oss = da.upload_generated_result_to_oss(f"{path}")  # 删除指定批次
```

## 目录结构

```
cached/
└── {session_id}/
    └── data_analysis_output/
        ├── gen_001/
        │   ├── charts/
        │   ├── data/
        │   └── reports/
        ├── gen_002/
        │   └── ...
        └── _meta.json          # generation 计数器
```

## 注意事项

- `new_generation()` 每次调用自动自增，无需手动管理
- 删除操作通过 `remove_dir("gen_xxx")` 进行
- AI 根据场景自行决定输出格式（png/svg/html/pdf）和图表参数