from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from ChatMe.ChatMeConfig import (
    config,
    ensure_global_config,
    get_active_llm_config,
    get_backup_llm_config,
    get_llm_providers_chain,
    self_check_llm,
)
from ChatMe.APIRouter.main import ChatMe_app, chat_service_lifespan
from ChatMe.APIRouter.model_vl import model_vl_app
from ChatMe.APIRouter.static_file import static_file_router
from ChatMe.APIRouter.timed_clean import cleanup_lifespan, cleanup_router
from ChatMe.LoggingManager.logging_config import set_logger


app_config = config.get_app_config()
version = app_config.get("version", "v0.0.1")
app_name = app_config.get("name", "ChatMe")
app_description = app_config.get("description", "")
app_host = app_config.get("host", "127.0.0.1")
app_port = app_config.get("port", 8211)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """组合多个 lifespan"""
    async with chat_service_lifespan(app):
        async with cleanup_lifespan(app):
            yield

    logger.info(f"\n{'='*60}\n  {app_name} {version} 关闭\n{'='*60}")

app = FastAPI(
    title=app_name,
    description=app_description,
    version=version,
    lifespan=lifespan
)

logger = set_logger()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info(f"\n{'='*60}\n  {app_name} {version} 启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}")

# ========== LLM 端到端自检（核心依赖，必须通过）==========
try:
    check = self_check_llm(timeout=10)
    p, b, active = check["primary"], check["backup"], check["active"]

    if not p and not b:
        raise RuntimeError(
            "llm_providers 中没有任何可用的 LLM 配置，请检查 config.json"
        )

    if p:
        tag = "✅ 主用 LLM 自检通过" if p["ok"] else "❌ 主用 LLM 自检失败"
        logger.info(f"{tag}: {p['name']} | {p['msg']}")

    if b:
        tag = "🔁 备用 LLM 自检通过" if b["ok"] else "❌ 备用 LLM 自检失败"
        logger.info(f"{tag}: {b['name']} | {b['msg']}")

    if not active:
        raise RuntimeError(
            "主用与备用 LLM 端到端自检均失败：\n"
            f"  - 主用 {p['name'] if p else '?'}: {p['msg'] if p else '未配置'}\n"
            f"  - 备用 {b['name'] if b else '?'}: {b['msg'] if b else '未配置'}\n"
            "请检查 config.json 中的 llm_providers 或网络连通性"
        )

    if active == (p and p["name"]):
        logger.info(f"🚀 当前生效: 主用 LLM ({active})")
    else:
        logger.warning(f"⚠️  主用不可用，已降级到备用 LLM ({active})")
except RuntimeError:
    raise
except Exception as e:
    # 自检过程本身崩了（导入失败、代码异常等）也视为核心依赖不可用
    raise RuntimeError(f"LLM 自检过程异常: {e}") from e
# =================================================

app.include_router(ChatMe_app)
app.include_router(cleanup_router)
app.include_router(static_file_router)

# 仅在 local=true 时加载本地 VL 模型
try:
    from ChatMe.ChatMeConfig import get_model_vl_config
    vl_config = get_model_vl_config()
    if vl_config.get("local"):
        app.include_router(model_vl_app)
        logger.info("本地 VL 模型已启用")
    else:
        logger.info("使用外部 VL 模型")
except Exception as e:
    logger.error(f"VL 模型配置检测失败: {e}")

# OSS 配置检测
try:
    from ChatMe.ChatMeConfig import get_oss_config
    oss_cfg = get_oss_config()
    if oss_cfg.get("access_key_id") and oss_cfg.get("bucket"):
        logger.info("OSS 已配置")
    else:
        logger.info("OSS 未配置")
except Exception as e:
    logger.error(f"OSS 配置检测失败: {e}")

@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": f"{app_name} is running QwQ",
        "version": version,
    }

def main():
    # 确保全局配置存在
    ensure_global_config()
    uvicorn.run("main:app", host=app_host, port=app_port)
    # uvicorn.run("main:app", host=app_host, port=app_port, reload=True)

if __name__ == "__main__":
    main()





