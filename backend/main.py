from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from ChatMe.ChatMeConfig import config
from ChatMe.APIRouter.main import ChatMe_app, chat_service_lifespan
from ChatMe.APIRouter.model_vl import model_vl_app
from ChatMe.APIRouter.timed_clean import cleanup_lifespan, cleanup_router
from ChatMe.LoggingManager.logging_config import set_logger


app_config = config.get_app_config()
version = app_config.get("version", "v1.0.0")
app_name = app_config.get("name", "ChatMe")
app_description = app_config.get("description", "")
app_host = app_config.get("host", "127.0.0.1")
app_port = app_config.get("port", 8111)

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

app.include_router(ChatMe_app)
app.include_router(cleanup_router)

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


if __name__ == "__main__":
    # uvicorn.run("main:app", host=app_host, port=app_port, reload=True)
    uvicorn.run("main:app", host=app_host, port=app_port)






