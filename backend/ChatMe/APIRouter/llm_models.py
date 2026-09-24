"""
LLM 模型管理端点：
- GET /admin/llm/models?provider=xxx
    拉取 {base_url}/v1/models，返回该 api_key 可见的模型列表
    前端用此填充 model_name 下拉框
- GET /admin/llm/cache-info
    当前 llm_factory cache 状态（调试）

为什么后端 proxy 而不是前端直连：
OpenAI 官方 API 没有 Access-Control-Allow-Origin:*，浏览器 fetch 会被 CORS 挡；
DeepSeek / Azure OpenAI 同样。后端 proxy 转发顺带隐藏 base_url / api_key 不外泄。

v0.3.x —— 移除「推荐模型白名单」兜底（_RECOMMENDED_MODELS）：
  远端 /v1/models 返回什么就用什么，没有就返空列表。
  旧逻辑会拼一个 gpt-4o / deepseek-chat / Qwen 等硬编码白名单到下拉框，
  用户不知情选了和 base_url 不匹配的模型 → 实际请求 401。这是误导，不是兜底。
  真正的兜底是「下拉框空 + 提示用户手填」+ 当前已填的 model_name 至少保留在选项里
  （前端 availableModels() 已做）。
"""
import httpx
from fastapi import APIRouter, HTTPException, Query

from ChatMe.ChatMeConfig import config
from ChatMe.ChatWorkflow import llm_factory
from ChatMe.LoggingManager.logging_config import get_logger


logger = get_logger("llm_models")


router = APIRouter(prefix="/admin", tags=["llm_models"])


@router.get("/llm/models")
async def list_models(provider: str = Query(..., description="llm_providers 里的 key")):
    """
    拉取 provider 对应的 {base_url}/v1/models。

    返回 {ok, models, source, error}:
      - source: "remote"（远端 200 返回，可能 models=[]）
                / "error"（远端 4xx/5xx / 请求异常 / 配置缺失）
      - models: 远端返回的 model.id 列表（**严格按远端返回**，不拼白名单）
      - 失败时 models=[] —— 前端用此 + 当前已填 model_name 渲染下拉框
    """
    cfg = config.get(f"llm_providers.{provider}")
    if not cfg or not isinstance(cfg, dict):
        raise HTTPException(status_code=400, detail=f"provider '{provider}' 不存在")

    api_key = (cfg.get("api_key") or "").strip()
    base_url = (cfg.get("base_url") or "").strip()
    if not api_key or not base_url:
        return {
            "ok": False,
            "models": [],
            "source": "error",
            "error": "api_key 或 base_url 为空",
        }

    # 拼接 /v1/models URL（兼容 base_url 已带 /v1 或没带的情况）
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url = url + "/v1"
    url = url + "/models"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if r.status_code == 200:
            data = r.json()
            remote_models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            return {"ok": True, "models": remote_models, "source": "remote", "error": None}
        else:
            logger.warning(
                f"[llm/models] {provider} {url} → {r.status_code}: {r.text[:200]}"
            )
            return {
                "ok": False,
                "models": [],
                "source": "error",
                "error": f"远端返 {r.status_code}",
            }
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.warning(f"[llm/models] {provider} {url} 请求失败: {e}")
        return {
            "ok": False,
            "models": [],
            "source": "error",
            "error": f"请求失败: {type(e).__name__}",
        }


@router.get("/llm/cache-info")
async def get_cache_info():
    """llm_factory 当前缓存状态（调试用）。"""
    return {"ok": True, **llm_factory.cache_info()}