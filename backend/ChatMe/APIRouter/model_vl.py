import base64
import io
import os
import shutil
from pathlib import Path
from typing import Optional, List, Union, AsyncGenerator
from urllib.parse import urlparse

import requests
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from huggingface_hub import snapshot_download
from pydantic import BaseModel
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
from PIL import Image
import json
import asyncio

# -------------- 你的模型--------------
# 加载顺序：工作目录下 .model/ → HF 默认 cache 搬到 .model/ → snapshot_download 直接下到 .model/
# 目标：让 <cwd>/.model/Qwen3-VL-2B-Instruct 成为权威本地路径，未来启动稳定走本地。
VL_MODEL_ID = "Qwen/Qwen3-VL-2B-Instruct"
VL_LOCAL_DIR = str(Path.cwd() / ".model" / VL_MODEL_ID)

def _find_hf_cached_snapshot(model_id: str) -> Optional[str]:
    """在 HF 默认 cache 目录下找 model_id 的 snapshot 路径，返回第一个匹配。
    HF 缓存目录布局：{HF_HOME or ~/.cache/huggingface}/hub/models--{org}--{name}/snapshots/<sha>/
    """
    hf_home = Path(os.getenv("HF_HOME") or Path.home() / ".cache" / "huggingface" / "hub")
    snapshots_dir = hf_home / f"models--{model_id.replace('/', '--')}" / "snapshots"
    if not snapshots_dir.is_dir():
        return None
    snapshots = sorted(d for d in snapshots_dir.iterdir() if d.is_dir())
    # 必须含 config.json 才算完整 snapshot（空目录不算）
    for snap in snapshots:
        if (snap / "config.json").is_file():
            return str(snap)
    return None

def _ensure_local_model(model_id: str, local_dir: str) -> str:
    """确保模型在 local_dir 可用：
    1. local_dir 已有完整 config.json → 直接返回 local_dir
    2. HF cache 里有 → 复制快照到 local_dir，返回 local_dir
    3. 都没有 → snapshot_download 直接下载到 local_dir（不走 HF cache）
    """
    local_path = Path(local_dir)
    if local_path.is_dir() and (local_path / "config.json").is_file():
        print(f"[VL] 本地目录已就绪: {local_dir}")
        return local_dir

    cached = _find_hf_cached_snapshot(model_id)
    if cached:
        print(f"[VL] 从 HF cache 搬到本地: {cached} → {local_dir}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(cached, local_dir)
        return local_dir

    print(f"[VL] 本地/HF cache 都缺失，下载到本地: {model_id} → {local_dir}")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_id, local_dir=local_dir)
    return local_dir

vl_model_source = _ensure_local_model(VL_MODEL_ID, VL_LOCAL_DIR)

model = Qwen3VLForConditionalGeneration.from_pretrained(
    vl_model_source, dtype="auto", device_map="auto"
)

# 限制像素数量以节省内存和提高速度
# min_pixels/max_pixels 必须是 28 的倍数
processor = AutoProcessor.from_pretrained(
    vl_model_source,
    min_pixels=28 * 28,      # 最小 784 像素
    max_pixels=256 * 28 * 28  # 最大 200k 像素（约 512x512）
)

# -------------- 启动 API 服务 --------------
model_vl_app = APIRouter(prefix="/api")

# --------------------- 数据结构 ---------------------
class ImageURL(BaseModel):
    url: str

class ContentItem(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[Union[ImageURL, dict]] = None

class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[dict]]

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    max_tokens: Optional[int] = 4096
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False

# --------------------- 工具函数 ---------------------
def compress_image_if_needed(image: Image.Image, max_size: int = 512) -> Image.Image:
    """压缩图片到指定最大尺寸，保持比例"""
    if max(image.size) > max_size:
        ratio = max_size / max(image.size)
        new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
        return image.resize(new_size, Image.LANCZOS)
    return image


def fetch_and_process_image(image_url: str) -> Image.Image:
    """获取并处理图片"""
    if image_url.startswith("data:image/"):
        # Base64
        base64_data = image_url.split(",")[1]
        image_bytes = base64.b64decode(base64_data)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return compress_image_if_needed(image)
    elif urlparse(image_url).scheme in ("http", "https"):
        # URL - 下载并压缩
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
        return compress_image_if_needed(image)
    elif os.path.exists(image_url):
        # 本地文件 - 读取并压缩
        image = Image.open(image_url).convert("RGB")
        return compress_image_if_needed(image)
    raise ValueError(f"不支持的图片格式: {image_url[:50]}...")


def process_messages(qwen_messages: List[dict]):
    """处理消息并返回 image_inputs, video_inputs"""
    image_inputs, video_inputs = process_vision_info(qwen_messages)
    return image_inputs, video_inputs


def generate_result(qwen_messages: List[dict], image_inputs: list, video_inputs: list, max_tokens: int, temperature: float) -> str:
    """生成完整结果"""
    text = processor.apply_chat_template(
        qwen_messages, tokenize=False, add_generation_prompt=True
    )

    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt"
    ).to(model.device)

    outputs = model.generate(
        **inputs,
        max_new_tokens=max_tokens,
        temperature=temperature
    )
    result = processor.batch_decode(outputs, skip_special_tokens=True)[0]

    # 提取 assistant 后的实际回复内容
    if "assistant\n" in result:
        result = result.split("assistant\n", 1)[1]
    elif "assistant " in result:
        result = result.split("assistant ", 1)[1]

    return result.strip()


async def generate_streaming_response(
    qwen_messages: List[dict],
    image_inputs: list,
    video_inputs: list,
    max_tokens: int,
    temperature: float,
    model_name: str
) -> AsyncGenerator[str, None]:
    """异步流式响应生成"""
    # 预生成完整响应
    result = generate_result(qwen_messages, image_inputs, video_inputs, max_tokens, temperature)

    # 分块发送
    chunk_size = 20
    for i in range(0, len(result), chunk_size):
        chunk_text = result[i:i + chunk_size]
        chunk = {
            "id": "qwen3-vl-local",
            "object": "chat.completion.chunk",
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {"content": chunk_text},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)

    # 发送结束块
    final_chunk = {
        "id": "qwen3-vl-local",
        "object": "chat.completion.chunk",
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }]
    }
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


# --------------------- OpenAI 标准接口 /v1/chat/completions ---------------------
@model_vl_app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    qwen_messages = []
    for msg in request.messages:
        content = msg.content
        if isinstance(content, str):
            qwen_messages.append({"role": msg.role, "content": content})
        elif isinstance(content, list):
            items = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "text":
                        text_val = item.get("text", "")
                        if text_val:
                            items.append({"type": "text", "text": text_val})
                    elif item_type == "image_url":
                        image_url_data = item.get("image_url", {})
                        if isinstance(image_url_data, dict):
                            image_url = image_url_data.get("url")
                        else:
                            image_url = image_url_data

                        if image_url:
                            try:
                                image = fetch_and_process_image(image_url)
                                items.append({"type": "image", "image": image})
                            except Exception:
                                pass
                elif isinstance(item, str):
                    if item:
                        items.append({"type": "text", "text": item})

            qwen_messages.append({"role": msg.role, "content": items})

    image_inputs, video_inputs = process_messages(qwen_messages)

    # 流式输出
    if request.stream:
        return StreamingResponse(
            generate_streaming_response(
                qwen_messages, image_inputs, video_inputs,
                request.max_tokens, request.temperature, request.model
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    # 非流式输出
    result = generate_result(qwen_messages, image_inputs, video_inputs, request.max_tokens, request.temperature)

    return {
        "id": "qwen3-vl-local",
        "object": "chat.completion",
        "model": request.model,
        "choices": [{
            "message": {"role": "assistant", "content": result},
            "finish_reason": "stop"
        }]
    }