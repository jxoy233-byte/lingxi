"""
Scheduled tasks REST CRUD API（管理员 / 调试用）

端点：
  - POST   /admin/scheduled-tasks            创建任务
  - GET    /admin/scheduled-tasks            列出任务（支持 ?session_id= 过滤）
  - GET    /admin/scheduled-tasks/{task_id}  任务详情（支持 ?with_history=true）
  - PATCH  /admin/scheduled-tasks/{task_id}  更新 enabled / cron
  - DELETE /admin/scheduled-tasks/{task_id}  删除任务
  - POST   /admin/scheduled-tasks/{task_id}/run  手动触发一次

业务逻辑全在 skills.Scheduler.registry，本文件只做薄路由 + 请求/响应校验。
"""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from ChatMe.LoggingManager.logging_config import get_logger
from skills.Scheduler.registry import (
    add_task,
    delete_task,
    get_task,
    list_tasks,
    run_task_now,
    update_task,
)

logger = get_logger("ScheduledTasksAPI")

router = APIRouter(prefix="/admin/scheduled-tasks", tags=["scheduler"])


# =========================================================================
# Request / Response models
# =========================================================================


class TaskCreate(BaseModel):
    """POST /admin/scheduled-tasks payload"""

    name: str = Field(..., min_length=1, max_length=100, description="任务可读名")
    cron: str = Field(..., description="5-field cron（Asia/Shanghai TZ）")
    prompt: str = Field(..., min_length=1, description="触发时注入到 session 的用户消息")
    session_id: str = Field(
        default="",
        description="目标 session_id（空=触发时新建；非空=用/创建该 sid）",
    )


class TaskUpdate(BaseModel):
    """PATCH /admin/scheduled-tasks/{task_id} payload（字段都可省略）"""

    enabled: Optional[bool] = Field(default=None, description="True/False；None=不修改")
    cron: Optional[str] = Field(default=None, description="新 cron 表达式；None=不修改")


# =========================================================================
# 端点
# =========================================================================


@router.post("", response_model=dict, summary="创建定时任务")
async def create_task(body: TaskCreate = Body(...)):
    """创建任务；返回 task_id"""
    try:
        # registry 不接受 created_by / task_type（保留默认值），session_id 透传
        tid = add_task(
            name=body.name,
            cron=body.cron,
            prompt=body.prompt,
            session_id=body.session_id,
        )
        return {"ok": True, "task_id": tid}
    except ValueError as e:
        # cron 非法
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # scheduler 未启动（lifespan 异常）
        raise HTTPException(status_code=503, detail=str(e))


@router.get("", response_model=dict, summary="列出任务")
async def list_tasks_endpoint(
    session_id: str = Query(
        default="",
        description="可选过滤条件（空=全部；非空=只返回该 session 的任务）",
    ),
):
    """列出所有任务；可按 session_id 过滤"""
    try:
        tasks = list_tasks(session_id=session_id or None)
        return {"ok": True, "tasks": tasks}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/{task_id}", response_model=dict, summary="任务详情")
async def get_task_endpoint(
    task_id: str,
    with_history: bool = Query(
        default=False,
        description="是否附加最近 10 条执行历史",
    ),
):
    """获取任务详情（支持前缀匹配）；
    with_history=true 时返回 history 字段（最近 10 条）"""
    try:
        result = get_task(task_id, with_history=with_history)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if result is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")
    return {"ok": True, **result}


@router.patch("/{task_id}", response_model=dict, summary="更新任务字段")
async def update_task_endpoint(
    task_id: str,
    body: TaskUpdate = Body(...),
):
    """部分更新（enabled / cron 都可省略）"""
    try:
        ok = update_task(
            task_id,
            enabled=int(body.enabled) if body.enabled is not None else None,
            cron=body.cron,
        )
    except ValueError as e:
        # cron 非法
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")
    return {"ok": True}


@router.delete("/{task_id}", response_model=dict, summary="删除任务")
async def delete_task_endpoint(task_id: str):
    """删除任务（清 APScheduler job + meta + history + 防重入锁）"""
    try:
        ok = delete_task(task_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")
    return {"ok": True}


@router.post("/{task_id}/run", response_model=dict, summary="手动触发一次")
async def run_task_endpoint(task_id: str):
    """立刻触发一次任务（不影响原 cron 调度）"""
    try:
        ok = run_task_now(task_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")
    return {"ok": True, "msg": "已触发异步执行"}