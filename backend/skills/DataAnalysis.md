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
OUTPUT_DIR = config["output_dir"]  # 例如: cached/{session_id}/data_analysis_output/gen_001/
```

### Step 4: 编写分析代码

将分析结果保存到 `OUTPUT_DIR` 下的对应子目录：

```
{OUTPUT_DIR}/charts/     # 图表文件 (png/svg/html)
{OUTPUT_DIR}/data/      # 数据文件 (csv/json)
{OUTPUT_DIR}/reports/   # 报告文件 (md/html)
```

### Step 5: 在 AI 回复中引用生成的文件

**本地文件** (文件在 cached/ 目录下):
```
[[cached/{session_id}/data_analysis_output/gen_xxx/charts/xxx.png]]
[[cached/{session_id}/data_analysis_output/gen_xxx/charts/xxx.html]]
[[cached/{session_id}/data_analysis_output/gen_xxx/reports/xxx.md]]
```

**路径格式**: cached/{session_id}/data_analysis_output/gen_xxx/...

### Step 6: (可选) 上传分析结果到 OSS

```python
# 上传单个文件到 OSS，返回 markdown 可用的 URL 格式
oss_url = da.upload_result_to_oss(f"{OUTPUT_DIR}/charts/sales.png")

# 上传后返回的格式：
# - 图片: https://bucket.endpoint/xxx.png (可直接用于 ![alt](url))
# - HTML: .../xxx.html (可直接用于 <iframe src="url">)
# - MD: .../xxx.md (可直接用于 <iframe src="url">)
```

### Step 7: (可选) 删除不满意的结果

```python
da.remove_dir("gen_001")  # 删除指定批次
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

- `generation` 在初始化时自动生成，每个实例只生成一次
- 删除操作通过 `remove_dir("gen_xxx")` 进行
- AI 根据场景自行决定输出格式（png/svg/html/pdf）和图表参数
- 本地文件用 `[[ ]]` 语法引用，OSS 文件用标准 markdown/HTML 语法
- 上传 OSS 后建议使用 OSS URL 便于分享和长期访问