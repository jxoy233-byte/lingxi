from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from chatMe.APIRouter.main import chatMe_app, lifespan
from chatMe.logging_config import set_logger

version = "1.0.0"
app = FastAPI(
    title = "ChatMe",
    description= "use ChatMe to chat with AI with better MEMORY and TOOLS !",
    version = version,
    lifespan = lifespan
)

logger = set_logger()

logger.info("ChatMe应用启动ing")
logger.info(f"版本:{version}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产中允许进入访问的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chatMe_app)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "ChatMe is running QwQ",
        "version": version,
        "architecture": {
            "workflow": "ChatWorkflow (LangGraph+Langchain)",
            "memory": "RedisSaver(LangGraph)",
            "tools": "waiting for developing",
        }
    }


if __name__ == "__main__":
    # uvicorn.run("main:app", host="127.0.0.1", port=8211, reload=True)
    uvicorn.run("main:app", host="127.0.0.1", port=8211)






