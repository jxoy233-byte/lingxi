"""
图片解析技能 - 使用 VL 模型解析图片内容

支持:
- OSS URL (http/https)
- 本地文件（相对于 backend/cached/ 目录，或含 cached/ 的相对路径）
"""

import os
import base64
import io
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image


def _compress_image(image: Image.Image, max_size: int = 512) -> Image.Image:
    """压缩图片到指定最大尺寸，保持比例"""
    if max(image.size) > max_size:
        ratio = max_size / max(image.size)
        new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
        return image.resize(new_size, Image.LANCZOS)
    return image


def _resolve_cached_path(file_path: str) -> str:
    """
    解析文件路径，返回绝对路径

    规则：
    - 绝对路径：直接使用
    - 含 "cached/" 的相对路径：相对于 backend/ 目录
    - 其他相对路径：相对于 backend/cached/ 目录
    """
    # 绝对路径直接使用
    if os.path.isabs(file_path):
        return file_path

    # 获取 backend 目录的绝对路径
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 含 cached/ 的路径，相对于 backend/
    if "cached/" in file_path or file_path.startswith("cached/"):
        return os.path.join(backend_dir, file_path)

    # 其他相对路径，默认在 cached/ 下
    return os.path.join(backend_dir, "cached", file_path)


def _fetch_local_image(file_path: str) -> Image.Image:
    """从本地文件读取图片"""
    full_path = _resolve_cached_path(file_path)

    if not os.path.exists(full_path):
        raise FileNotFoundError(f"文件不存在: {full_path} (解析路径: {full_path})")

    image = Image.open(full_path).convert("RGB")
    return _compress_image(image)


def _fetch_url_image(url: str) -> Image.Image:
    """从 URL 获取图片"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不支持的 URL 协议: {parsed.scheme}")

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    return _compress_image(image)


def _encode_image_to_base64(image: Image.Image) -> str:
    """将图片编码为 base64 字符串"""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def parse_image(
    image_source: str,
    prompt: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7
) -> str:
    """
    使用 VL 模型解析图片

    参数:
        image_source: 图片源，可以是:
            - OSS URL (http/https 开头)
            - 本地文件路径（支持相对路径和绝对路径）
        prompt: 可选的提示词，默认使用通用图片描述
        max_tokens: 最大生成 token 数
        temperature: 温度参数

    返回:
        VL 模型对图片的解析结果文本

    路径解析规则:
        - 绝对路径：直接使用
        - "cached/xxx" 路径：相对于 backend/ 目录
        - 其他相对路径：相对于 backend/cached/ 目录

    示例:
        # OSS URL
        >>> parse_image("https://example.com/image.jpg")
        '这张图片展示了一只可爱的橘猫...'

        # cached/ 下文件（相对路径）
        >>> parse_image("screenshot.png")
        '界面顶部是导航栏，左侧...'

        # 含 cached/ 的相对路径
        >>> parse_image("cached/screenshot.png")

        # 绝对路径
        >>> parse_image("/path/to/image.jpg")
    """
    # 确定图片源类型
    if image_source.startswith("data:image/"):
        # Base64 编码的图片
        base64_data = image_source.split(",", 1)[1]
        image_bytes = base64.b64decode(base64_data)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image = _compress_image(image)
        base64_str = _encode_image_to_base64(image)  # 用压缩后的图片编码
    elif image_source.startswith(("http://", "https://")):
        # URL 图片
        image = _fetch_url_image(image_source)
        base64_str = _encode_image_to_base64(image)
    else:
        # 本地文件
        image = _fetch_local_image(image_source)
        base64_str = _encode_image_to_base64(image)

    # 构建消息
    if prompt is None:
        prompt = "请详细描述这张图片的内容，包括其中的文字、人物、物体、场景等所有可见元素。"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                }
            ]
        }
    ]

    # 调用 VL 模型 API
    try:
        from ChatMe.ChatMeConfig import get_model_vl_config
        vl_config = get_model_vl_config()
        vl_base_url = vl_config.get("base_url", "http://127.0.0.1:8211/api/v1")
        vl_api_key = vl_config.get("api_key", "empty")
        vl_model = vl_config.get("model_name", "Qwen3-VL-2B")
        # 配置仅作为默认值，用户传入参数时优先使用传入值
        # 如需使用配置值，传参时不要指定即可
    except Exception:
        vl_base_url = os.getenv("VL_BASE_URL", "http://127.0.0.1:8211/api/v1")
        vl_api_key = os.getenv("VL_API_KEY", "empty")
        vl_model = os.getenv("VL_MODEL_NAME", "Qwen3-VL-2B")

    payload = {
        "model": vl_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
    }

    headers = {
        "Authorization": f"Bearer {vl_api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            f"{vl_base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120  # 图片解析可能需要更长时间
        )
        response.raise_for_status()
        result = response.json()

        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            return content.strip()
        else:
            return f"VL 模型返回格式异常: {result}"

    except requests.RequestException as e:
        return f"调用 VL 模型失败: {str(e)}"


def parse_images_batch(
    image_sources: list[str],
    prompt: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7
) -> list[str]:
    """
    批量解析多张图片

    参数:
        image_sources: 图片源列表
        prompt: 可选的统一提示词
        max_tokens: 最大生成 token 数
        temperature: 温度参数

    返回:
        每张图片解析结果的列表

    示例:
        >>> results = parse_images_batch(["image1.jpg", "image2.png"])
        >>> for i, result in enumerate(results):
        ...     print(f"图片{i+1}: {result}")
    """
    results = []
    for source in image_sources:
        try:
            result = parse_image(source, prompt=prompt, max_tokens=max_tokens, temperature=temperature)
            results.append(result)
        except Exception as e:
            results.append(f"解析失败: {str(e)}")
    return results
