from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from ChatMe.ChatMeConfig import config
from ChatMe.APIRouter.main import ChatMe_app, lifespan
from ChatMe.APIRouter.model_vl import model_vl_app
from ChatMe.LoggingManager.logging_config import set_logger

app_config = config.get_app_config()
version = app_config.get("version", "v1.0.0")
app_name = app_config.get("name", "ChatMe")
app_description = app_config.get("description", "")
app_host = app_config.get("host", "127.0.0.1")
app_port = app_config.get("port", 8111)

app = FastAPI(
    title=app_name,
    description=app_description,
    version=version,
    lifespan=lifespan
)

logger = set_logger()

logger.info(f"{app_name} 应用启动ing")
logger.info(f"版本: {version}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产中允许进入访问的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ChatMe_app)

# 仅在 local=true 时加载本地 VL 模型并启用对应路由
try:
    from ChatMe.ChatMeConfig import get_model_vl_config
    vl_config = get_model_vl_config()
    if vl_config.get("local"):
        app.include_router(model_vl_app)
        logger.info("本地 VL 模型已启用（local=true）")
    else:
        logger.info("本地 VL 模型未启用（local=false），将使用外部 VL 模型")
except Exception as e:
    logger.warning(f"VL 模型配置获取失败: {e}")

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






