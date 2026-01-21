import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import APIRouter, HTTPException, FastAPI, Path, Body, Query
from fastapi.responses import StreamingResponse
from starlette.responses import RedirectResponse

from ..ChatService.models import ChatRequest, Conversation
from ..ChatService import ChatService
from ..ChatWorkflow import ChatWorkflow

chatMe_app = APIRouter(prefix="/chat")

chat_service: Optional[ChatService] = None


async def create_chat_service() -> ChatService:
    """
    初始化chatService的对象

    Return: ChatService()
    """
    global chat_service
    workflow = ChatWorkflow()
    await workflow.ainit()

    chat_service = ChatService(workflow)

    return chat_service

@asynccontextmanager
async def lifespan(app :FastAPI):
    # 启动时执行：初始化全局 chat_service
    chat_service = await create_chat_service()
    logging.info("ChatService启动成功")
    # 分割启动与关闭逻辑
    yield
    chat_service = None
    logging.info("ChatService关闭成功")


@chatMe_app.post("/", summary="新建对话/继续对话-流式响应，无session_id则新建对话")
async def chat_stream(chatRequest: ChatRequest):
    """
    核心流式对话接口：
    - 不传session_id → 自动生成新会话ID，创建全新对话
    - 传入存在的session_id → 基于该会话的历史上下文继续对话
    - 传入不存在的session_id → 抛出404异常

    参数:
        session_id: 会话 ID，如果没有则为 None
        message: 请求对象，包含用户消息

    返回:
        StreamingResponse: 包含 AI 回应、session_id 和会话标题
    """
    try:
        async def event_generator():
            async for data in chat_service.message_stream(
                message=chatRequest.message,
                session_id=chatRequest.session_id
            ):
                yield f"{data}"

        headers = {
            "Cache-Control": "no-cache",  # 禁用缓存
            "X-Accel-Buffering": "no",  # 禁用nginx/uvicorn缓冲区!
            "Connection": "keep-alive"  # 长连接保持
        }

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=headers,
        )
    except Exception as e:
        logging.error(f"接口执行异常(session_id:{chatRequest.session_id})：{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@chatMe_app.get("/conversations", summary="获取历史会话列表【默认返回最新20条】", response_model=List[Conversation])
async def get_conversations(
    limit: int = Query(default=20, ge=1, le=50, description="返回会话数量，默认20条，最多50条")
):
    """获取所有历史会话，按【更新时间倒序】排列，最新的会话在最前面，自动过滤空会话"""
    try:
        conversations = await chat_service.get_conversation_list(limit=limit)
        return conversations
    except Exception as e:
        logging.error(f"获取会话列表异常：{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@chatMe_app.get("/{session_id}", summary="获取指定会话内容")
async def get_conversation_content(session_id :str = Path(..., description="会话ID")):
    """
    进入指定会话详情页核心接口：
    1. 加载该会话的所有历史聊天记录（用户+AI消息）
    2. 返回会话标题/创建时间/更新时间等完整信息
    3. 前端拿到后渲染聊天界面，之后可调用/chat接口传入该session_id继续对话
    """
    try:
        conversation = await chat_service.get_conversation(session_id)

        if not conversation or len(conversation.messages) == 0:
            logging.warning(f"会话ID: {session_id} 暂无对话内容")
            raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在或暂无聊天记录")

        return conversation
    except Exception as e:
        logging.error(f"获取会话内容异常(session_id:{session_id})：{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@chatMe_app.delete("/{session_id}/clear", summary="删除指定历史会话（含聊天记录）")
async def delete_conversation(
    session_id: str = Path(..., description="会话唯一ID")
):
    """删除会话：彻底删除Redis中的会话上下文+检查点数据，前端删除后刷新列表即可"""
    try:
        success = await chat_service.delete_conversation(session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在，删除失败")
        return {"code": 200, "msg": "会话删除成功", "session_id": session_id}

    except Exception as e:
        logging.error(f"删除会话异常(session_id:{session_id})：{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@chatMe_app.put("/{session_id}/title", summary="修改会话标题")
async def update_conversation_title(
    session_id: str = Path(..., description="会话唯一ID"),
    title: str = Body(..., embed=True, min_length=1, max_length=50, description="会话标题")
):
    """修改会话标题：解决默认标题新对话的问题，前端点击修改标题调用"""
    try:
        success = await chat_service.update_conversation_title(session_id, title)
        if not success:
            raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在，修改失败")
        return {"code": 200, "msg": "标题修改成功", "session_id": session_id, "new_title": title}
    except Exception as e:
        logging.error(f"修改标题异常(session_id:{session_id})：{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@chatMe_app.get("/{session_id}/title", summary="获取单个会话的标题")
async def get_conversation_title(
    session_id: str = Path(..., description="会话唯一ID")
):
    """单独获取会话标题，用于前端会话列表渲染"""
    try:
        conversation = await chat_service.get_conversation(session_id)
        if not conversation:
            raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
        return {"session_id": session_id, "title": conversation.title}
    except Exception as e:
        logging.error(f"获取标题异常(session_id:{session_id})：{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@chatMe_app.get("/common/latest", summary="获取最新的一条会话ID")
async def get_latest_conversation():
    """前端默认进入最新会话，无需手动点击，提升体验"""
    try:
        conv_list = await chat_service.get_conversation_list(limit=1)
        if not conv_list:
            return {"session_id": None}
        return {"session_id": conv_list[0].session_id, "title": conv_list[0].title}
    except Exception as e:
        logging.error(f"获取最新会话异常：{str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



