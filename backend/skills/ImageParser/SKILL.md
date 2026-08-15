---
name: image_parser
description: 使用 VL 模型解析截图、照片、文档图片、URL 和 base64 图片
mount: ro
aliases: [ImageParser, OCR, screenshot, parse_image, vision, photo]
module: skills.ImageParser
---

# ImageParser

ImageParser 使用视觉语言模型理解图片中的文字、人物、物体、场景和界面元素。

## 适用场景

- 解析截图、照片或文档图片
- 从 `cached/` 历史缓存中读取图片
- 理解用户提供的 HTTP/HTTPS 图片 URL
- 解析 base64 data URL
- 批量解析多张图片

## 调用方式

```python
from skills.ImageParser import parse_image, parse_images_batch

result = parse_image(
    "cached/example.png",
    prompt="提取图片中的表格和关键数字",
)
```

沙盒也兼容别名导入：

```python
from ImageParser import parse_image
```

## 函数

### `parse_image(image_source, prompt=None, max_tokens=2048, temperature=0.7, **kwargs)`

`image_source` 支持：

- HTTP/HTTPS URL
- 绝对本地路径
- `cached/xxx.png`（相对于 backend）
- `xxx.png`（默认相对于 backend/cached）
- `data:image/...;base64,...`

### `parse_images_batch(image_sources, prompt=None, max_tokens=2048, temperature=0.7, **kwargs)`

按顺序解析多张图片，返回与输入一一对应的结果列表；单张失败不会终止整个批次。
