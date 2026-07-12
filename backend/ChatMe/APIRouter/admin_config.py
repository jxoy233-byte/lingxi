"""
Settings dialog 后端 API：
  - GET  /admin/config         读取当前可编辑配置（密钥脱敏）
  - PUT  /admin/config         表单提交（白名单校验 + 原子写）
  - POST /admin/restart        触发后端重启（BackgroundTasks）
  - GET  /admin/health         健康检查（前端轮询等待重启完成）

所有 LLM/MCP/skills 字段改后必须重启才能生效（langchain client / mcp client
是常驻对象，运行时替换会污染运行态）。
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from ChatMe.ChatMeConfig import config
from ChatMe.LoggingManager.logging_config import get_logger

logger = get_logger("admin_config")

router = APIRouter(prefix="/admin", tags=["admin_config"])


class ConfigUpdate(BaseModel):
    """配置更新 payload — 所有字段可选；api_key 空字符串表示不修改"""

    llm_providers: dict | None = Field(default=None, description="LLM providers 配置")
    mcp_server: dict | None = Field(default=None, description="MCP server 配置")
    skills: dict | None = Field(default=None, description="Skills API keys")


@router.get("/config")
async def get_config():
    """返回前端可编辑视图（密钥脱敏）"""
    try:
        return {"ok": True, "config": config.get_public_config()}
    except Exception as e:
        logger.error(f"[admin/config GET] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取配置失败: {e}")


@router.put("/config")
async def put_config(update: ConfigUpdate):
    """表单提交：仅允许白名单内的顶层 key"""
    payload = {}
    if update.llm_providers is not None:
        payload["llm_providers"] = update.llm_providers
    if update.mcp_server is not None:
        payload["mcp_server"] = update.mcp_server
    if update.skills is not None:
        payload["skills"] = update.skills

    if not payload:
        raise HTTPException(status_code=400, detail="payload 为空")

    try:
        result = config.save_config(payload)
        logger.info(
            f"[admin/config PUT] 保存 {len(result['saved_keys'])} 个字段: "
            f"{result['saved_keys']}"
        )
        return result
    except ValueError as e:
        # 白名单 / 结构校验失败
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # 写文件失败
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart", status_code=202)
async def post_restart(background_tasks: BackgroundTasks):
    """触发后端重启（必须重启才能让新配置生效）"""
    logger.info("[admin/restart] 收到重启请求")
    background_tasks.add_task(config.trigger_restart)
    return {"ok": True, "message": "重启已调度"}


@router.get("/health")
async def get_health():
    """健康检查端点（前端轮询等待重启完成）"""
    return {"ok": True, "status": "running"}
