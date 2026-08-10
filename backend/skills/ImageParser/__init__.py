"""
图片解析技能 - 使用 VL 模型解析图片内容

支持:
- OSS URL (http/https)
- 本地文件（相对于 backend/cached/ 目录，或含 cached/ 的相对路径）
- base64 data URL

实现走 langchain_openai.ChatOpenAI（标准 OpenAI 多模态格式），
vl.local=False 时连接三元组自动 fallback 到主用 LLM（走 get_skills_config）。
"""

import os
import base64
import io
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI


_DEFAULT_PROMPT = (
    "请详细描述这张图片的内容，包括其中的文字、人物、物体、场景等所有可见元素。"
)


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

    # __file__ 位于 skills/ImageParser/__init__.py，向上三层才是 backend/。
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 含 cached/ 的路径，相对于 backend/
    if "cached/" in file_path or file_path.startswith("cached/"):
        return os.path.join(backend_dir, file_path)

    # 其他相对路径，默认在 cached/ 下
    return os.path.join(backend_dir, "cached", file_path)


def _fetch_local_image(file_path: str) -> Image.Image:
    """从本地文件读取图片（不压缩，由调用方统一在 encode 前压缩）"""
    full_path = _resolve_cached_path(file_path)

    if not os.path.exists(full_path):
        raise FileNotFoundError(f"文件不存在: {full_path} (解析路径: {full_path})")

    # 刷新文件时间戳，防止被清理任务删除
    os.utime(full_path, None)

    return Image.open(full_path).convert("RGB")


def _fetch_url_image(url: str) -> Image.Image:
    """从 URL 获取图片（不压缩，由调用方统一在 encode 前压缩）"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不支持的 URL 协议: {parsed.scheme}")

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def _encode_image_to_base64(image: Image.Image) -> str:
    """将图片编码为 base64 字符串"""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _build_vl_llm() -> ChatOpenAI:
    """
    构造 ChatOpenAI（每次调用重建 → config 变更立即生效，无需重启 backend）。

    连接三元组走 get_skills_config：
    - vl.local=False 时自动 fallback 到主用 LLM（chatme_config 内部的主→备链）
    - vl.local=True 时保留 vl 自己的 model_name / api_key / base_url

    信任 config，不校验目标 endpoint 是否真正支持 multimodal。
    """
    from ChatMe.ChatMeConfig import get_skills_config
    try:
        skills = get_skills_config()
        base_url = skills.get("vl_base_url") or os.getenv("VL_BASE_URL", "http://127.0.0.1:8211/api/v1")
        api_key = skills.get("vl_api_key") or os.getenv("VL_API_KEY", "empty")
        model_name = skills.get("vl_model_name") or os.getenv("VL_MODEL_NAME", "Qwen3-VL-2B")
    except Exception:
        base_url = os.getenv("VL_BASE_URL", "http://127.0.0.1:8211/api/v1")
        api_key = os.getenv("VL_API_KEY", "empty")
        model_name = os.getenv("VL_MODEL_NAME", "Qwen3-VL-2B")

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        timeout=120,    # 图片解析可能耗时较长
        max_retries=2,
    )


def parse_image(
    image_source: str,
    prompt: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    **kwargs
) -> str:
    """
    使用 VL 模型解析图片

    参数:
        image_source: 图片源，可以是:
            - OSS URL (http/https 开头)
            - 本地文件路径（支持相对路径和绝对路径）
            - base64 data URL (data:image/...;base64,...)
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
        >>> parse_image("https://example.com/image.jpg")
        '这张图片展示了一只可爱的橘猫...'

        >>> parse_image("screenshot.png")
        '界面顶部是导航栏，左侧...'

        >>> parse_image("cached/screenshot.png")
    """
    # 确定图片源类型（统一压缩：encode 前再压一次，保证三个入口对称）
    if image_source.startswith("data:image/"):
        # Base64 编码的图片
        base64_data = image_source.split(",", 1)[1]
        image_bytes = base64.b64decode(base64_data)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    elif image_source.startswith(("http://", "https://")):
        image = _fetch_url_image(image_source)
    else:
        image = _fetch_local_image(image_source)

    # 统一压缩到 512px 后再 base64 编码（节省 VL 模型 token + 加速推理）
    image = _compress_image(image)
    base64_str = _encode_image_to_base64(image)

    text_prompt = prompt if prompt is not None else _DEFAULT_PROMPT

    # 标准 OpenAI 多模态格式：HumanMessage.content 是 list of content blocks
    msg = HumanMessage(content=[
        {"type": "text", "text": text_prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"},
        },
    ])

    # 每次重建 ChatOpenAI → config 变更立即生效，无需重启
    llm = _build_vl_llm()
    # bind max_tokens / temperature → 与原 requests 实现保持一致
    llm = llm.bind(max_tokens=max_tokens, temperature=temperature)

    try:
        resp = llm.invoke([msg])
    except Exception as e:
        return f"调用 VL 模型失败: {type(e).__name__}: {str(e)[:200]}"

    content = resp.content
    if isinstance(content, str):
        return content.strip()
    # 少数模型返回 list of blocks，统一拍成字符串
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(parts).strip()
    return str(content).strip()


def parse_images_batch(
    image_sources: list[str],
    prompt: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    **kwargs
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
