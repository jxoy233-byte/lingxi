from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import APIRouter, HTTPException, FastAPI, Path, Body, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from ChatMe.ChatService.FilesLoaders import UploadFileWithId
from ChatMe.ChatService.FilesLoaders.core import OutputFormat
from ChatMe.ChatService.config.models import ChatRequest, ConversationSimple
from ChatMe.ChatService import ChatService, FILE_MAX_LENGTH
from ChatMe.ChatWorkflow import ChatWorkflow
from ChatMe.LoggingManager.logging_config import get_logger

ChatMe_app = APIRouter(prefix="/chat")

chat_service: Optional[ChatService] = None

logger = get_logger("ChatService Router")

async def create_chat_service() -> ChatService:
    """
    初始化chatService的对象

    Return: ChatService()
    """
    global chat_service
    try:
        workflow = ChatWorkflow()

        import asyncio
        try:
            await asyncio.wait_for(workflow.ainit(), timeout=30.0)
            logger.info("ChatWorkflow 初始化成功")

        except asyncio.TimeoutError:
            logger.error("ChatWorkflow 初始化超时（30秒），请检查：")
            logger.error("1. MCP 服务器是否启动")
            logger.error("2. Redis 是否启动")
            raise

        chat_service = ChatService(workflow)
        logger.info("ChatService 创建成功")
    except Exception as e:
        logger.error(f"ChatService 创建失败：{e}")
        raise

    return chat_service

@asynccontextmanager
async def chat_service_lifespan(app: FastAPI):
    """ChatService 的 lifespan"""
    chat_service = await create_chat_service()
    logger.info("ChatService 启动成功")
    yield
    chat_service = None
    logger.info("ChatService 关闭成功")


@ChatMe_app.post("/", summary="新建对话/继续对话-流式响应，无session_id则新建对话")
async def chat_stream(
        # chatRequest: str = Form(...),
        chat_request: ChatRequest = Body(...),
        # files: Optional[list[UploadFile]] = File(default=None, max_length=FILE_MAX_LENGTH)
):
    """
    核心流式对话接口：
    - 不传session_id → 自动生成新会话ID，创建全新对话
    - 传入存在的session_id → 基于该会话的历史上下文继续对话
    - 传入不存在的session_id → 抛出404异常

    参数:
        chatRequest ***前端要用字符串形式传入json字典对象***，包含：
            session_id: 会话 ID，如果没有则为 None
            message: 请求对象，包含用户消息(form-data)
            files_content: 处理好的文件内容返回结果

    返回:
        StreamingResponse: 包含 AI 回应、session_id 和会话标题
    """
    # 将form-data参数转为chatRequest对象
    # chatRequest = ChatRequest.model_validate_json(chatRequest)

    async def event_generator():
        async for data in chat_service.message_stream(
            message=chat_request.message,
            session_id=chat_request.session_id,
            processed_outputs=chat_request.processed_outputs
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

@ChatMe_app.get("/conversations", summary="获取历史会话列表", response_model=List[ConversationSimple])
async def get_conversations():
    """获取所有历史会话列表，按【更新时间倒序】排列，最新的会话在最前面，自动过滤空会话"""
    conversations = await chat_service.get_conversation_list()
    return conversations

@ChatMe_app.get("/{session_id}/conversation", summary="获取指定会话内容")
async def get_conversation_content(session_id :str = Path(..., description="会话ID")):
    """
    进入指定会话详情页核心接口：
    1. 加载该会话的所有历史聊天记录（用户+AI消息）
    2. 返回会话标题/创建时间/更新时间等完整信息
    3. 前端拿到后渲染聊天界面，之后可调用/chat接口传入该session_id继续对话
    """
    conversation = await chat_service.get_conversation(session_id)

    if not conversation or len(conversation.messages) == 0:
        logger.warning(f"会话ID: {session_id} 暂无对话内容")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在或暂无聊天记录")

    return conversation


@ChatMe_app.delete("/{session_id}/clear", summary="删除指定历史会话（含聊天记录）")
async def delete_conversation(
    session_id: str = Path(..., description="会话唯一ID")
):
    """删除会话：彻底删除Redis中的会话上下文+检查点数据，前端删除后刷新列表即可"""
    success = await chat_service.delete_conversation(session_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在，删除失败")
    return {"code": 200, "msg": "会话删除成功", "session_id": session_id}


@ChatMe_app.put("/{session_id}/title", summary="修改会话标题")
async def update_conversation_title(
    session_id: str = Path(..., description="会话唯一ID"),
    title: str = Body(..., embed=True, min_length=1, max_length=50, description="会话标题")
):
    """修改会话标题：解决默认标题新对话的问题，前端点击修改标题调用"""
    success = await chat_service.update_conversation_title(session_id, title)
    if not success:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在，修改失败")
    return {"code": 200, "msg": "标题修改成功", "session_id": session_id, "new_title": title}

@ChatMe_app.get("/{session_id}/title", summary="获取单个会话的标题")
async def get_conversation_title(
    session_id: str = Path(..., description="会话唯一ID")
):
    """单独获取会话标题，用于前端会话列表渲染"""
    conversation = await chat_service.get_conversation(session_id)
    if not conversation:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return {"session_id": session_id, "title": conversation.title}


@ChatMe_app.post("/improve_input", summary="优化用户输入内容")
async def improve_input(
    input_text: str = Body(..., embed=True, min_length=1, max_length=500, description="用户输入内容")
):
    """
    优化用户输入内容，优化成更好让后续进行AI对话中AI来理解用户需求
    """
    improved_text= await chat_service.get_imp_usr_ipt(input_text)
    return {"improved_text": improved_text}


@ChatMe_app.get("/file-config", summary="获取文件上传配置")
async def get_file_config():
    """
    获取文件上传配置信息，包括：
    - 最大文件大小限制
    - 支持的文件类型（图片、文本、文档）
    """
    return await chat_service.get_file_config()


@ChatMe_app.get("/{session_id}/data-analysis/tree", summary="检测会话的 data_analysis 目录结构")
async def get_data_analysis_tree(
    session_id: str = Path(..., description="会话ID")
):
    """
    检测会话 cached 目录下的 data_analysis/ 目录是否存在。
    存在则返回扁平文件列表，供前端自行构树 + 动态加载文件预览。

    返回:
        exists: bool - 目录是否存在
        root_path: str - 根路径（相对 cached/）
        files: list[dict] - 扁平文件列表，每项含 path / size / modified_at
    """
    from ChatMe.APIRouter.static_file import CACHED_DIR, list_data_analysis_files

    data_analysis_dir = CACHED_DIR / session_id / "data_analysis"
    base_rel = f"cached/{session_id}/data_analysis"

    if not data_analysis_dir.exists():
        return {
            "exists": False,
            "root_path": base_rel,
            "files": [],
        }

    return {
        "exists": True,
        "root_path": base_rel,
        "files": list_data_analysis_files(data_analysis_dir, base_rel),
    }


@ChatMe_app.post("/{session_id}/backtrack", summary="会话回溯")
async def backtrack_checkpoint(
    session_id: str = Path(..., description="会话唯一ID"),
    backtrack_id: str = Body(..., embed=True, description="回溯ID")
):
    """
    会话回溯：
    - 获取指定会话的指定回溯ID的会话内容
    - 获取指定会话的指定回溯ID的会话内容，并返回该回溯ID的会话内容
    """
    status = await chat_service.backtrack_state(session_id=session_id, checkpoint_id=backtrack_id)

    if not status:
        return {"code": 500, "msg": "回溯失败", "session_id": session_id, "backtrack_id": backtrack_id}

    return {"code": 200, "msg": "回溯成功", "session_id": session_id, "backtrack_id": backtrack_id}


@ChatMe_app.post("/{session_id}/upload_file", summary="上传文件")
async def upload_file(
    session_id: str = Path(..., description="会话ID"),
    files: Optional[list[UploadFile]] = File(default=None, max_length=FILE_MAX_LENGTH),
    processed_outputs: str = Form(default="[]", description="已处理好的文件信息(JSON字符串)"),
):
    """
        对文件进行预处理，提前处理要发给ai的文件信息

        Args:
            session_id: 会话id
            files: Upload文件
            processed_outputs: 已处理好的文件输出
        Returns:
            包装好的 files_content 结果
    """
    import json

    # 将 JSON 字符串解析为列表
    try:
        processed_outputs_list = json.loads(processed_outputs) if processed_outputs else []
    except json.JSONDecodeError as e:
        logger.error(f"解析 processed_outputs 失败: {e}")
        processed_outputs_list = []

    if not files:
        logger.warning("文件上传请求无文件")
        return {"code": 404, "msg": "无文件上传", "processed_outputs": processed_outputs}

    logger.info(f"文件上传: {len(files)}个文件")

    upload_files_with_id = [
        UploadFileWithId(
            file=f.file,
            filename=f.filename,
            size=f.size,
            headers=f.headers
        ) for f in files
    ]

    outputs = await chat_service.process_files(upload_files_with_id, session_id)
    processed_outputs_list.extend(outputs)

    return {
        "code": 200,
        "msg": "文件处理成功",
        "processed_outputs": processed_outputs_list,
    }

@ChatMe_app.post("/cancel_upload_file", summary="取消已上传的文件")
async def cancel_upload_file(
    file_id: str = Body(..., embed=True, description="每个文件自带的独特id"),
    processed_outputs: List[OutputFormat] = Body(default=[], description="已处理好的文件信息",embed=True)
):
    """
    取消已上传的文件
    """
    if not processed_outputs:
        return {"code": 400, "msg": "无文件上传", "processed_outputs": processed_outputs}

    index = -1
    for i,op in enumerate(processed_outputs):
        if file_id == op.file_id:
            index = i
            break

    if index == -1:
        return {"code": 404, "msg": f"无此{file_id}文件上传", "processed_outputs": processed_outputs}

    await chat_service.remove_processed_files(processed_outputs[index])

    processed_outputs.pop(index)

    return{
        "code": 200,
        "msg": f"取消{file_id}文件上传成功",
        "processed_outputs": processed_outputs,
    }

@ChatMe_app.post("/{session_id}/interrupt", summary="中断当前对话")
async def interrupt(
    session_id: str = Path(..., embed=True, description="会话唯一ID"),
    interrupt_reason: str = Body(..., embed=True, description="中断原因")
):
    """
    中断当前对话
    """
    success = await chat_service.interrupt_stream(session_id=session_id, interrupt_reason=interrupt_reason)
    if not success:
        raise HTTPException(status_code=404, detail=f"会话{session_id}中断失败")

    return {"code": 200, "msg": f"会话中断成功，理由:{interrupt_reason}", "session_id": session_id}

@ChatMe_app.post("/{session_id}/invoke_interrupted/{invoke_message}", summary="中断续接当前对话")
async def invoke_interrupted(
    session_id: str = Path(..., embed=True, description="会话唯一ID"),
    invoke_message: str = Path(..., embed=True, description="中断续接消息")
):
    """
    中断续接当前对话
    """
    async def event_generator():
        async for data in chat_service.invoke_interrupted_stream(
        session_id=session_id,
        message=invoke_message
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

