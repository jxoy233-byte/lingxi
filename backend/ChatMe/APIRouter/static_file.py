"""
静态文件服务路由器
提供文件访问接口，支持前端预览图片、HTML、Markdown 等文件

使用方式:
    from ChatMe.APIRouter.static_file import static_file_router
    app.include_router(static_file_router)
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ChatMe.LoggingManager.logging_config import get_logger

logger = get_logger("static_file")

# 获取 backend 根目录（使用 __file__ 相对路径，避免依赖启动目录）
BACKEND_DIR = Path.cwd()
CACHED_DIR = BACKEND_DIR / "cached"


static_file_router = APIRouter(prefix="/static", tags=["静态文件"])


def _get_safe_path(path: str) -> Optional[Path]:
    """
    将相对路径转换为安全的绝对路径
    防止路径穿越攻击
    """
    # 移除开头的 /
    if path.startswith("/"):
        path = path[1:]

    # 拼接基础目录
    base = CACHED_DIR
    target = (base / path).resolve()

    logger.info(f"_get_safe_path: path={path}, base={base}, target={target}")
    logger.info(f"startswith check: target={str(target)}, starts with base={str(base)}? {str(target).startswith(str(base))}")

    # 确保目标在 CACHED_DIR 内
    if not str(target).startswith(str(base)):
        logger.warning(f"路径穿越检测: {target} 不在 {base} 内")
        return None

    return target


@static_file_router.get("/cached/{file_path:path}", summary="访问 cached 目录下的文件")
async def serve_cached_file(
    file_path: str,
    download: bool = Query(False, description="是否下载而非预览")
):
    """
    访问 cached 目录下的文件

    Args:
        file_path: 相对于 cached/ 的路径
                   例如: abc123/data_analysis_output/gen_001/charts/sales.png
        download: True=下载, False=预览(默认inline显示)

    Returns:
        文件内容
    """
    logger.info(f"dir: {BACKEND_DIR}")
    safe_path = _get_safe_path(file_path)

    if safe_path is None:
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    if not safe_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")

    if not safe_path.is_file():
        raise HTTPException(status_code=400, detail="该路径不是文件")

    logger.info(f"静态文件访问: {safe_path}, download={download}")

    # 缓存头：1小时
    cache_headers = {
        "Cache-Control": "public, max-age=3600",
        "ETag": f'"{safe_path.stat().st_mtime:.0f}"'
    }

    if download:
        # 下载模式：attachment
        return FileResponse(
            path=str(safe_path),
            filename=safe_path.name,
            media_type=_get_media_type(safe_path),
            headers={
                "Content-Disposition": f'attachment; filename="{safe_path.name}"',
                **cache_headers
            }
        )
    else:
        # 预览模式：inline
        return FileResponse(
            path=str(safe_path),
            filename=safe_path.name,
            media_type=_get_media_type(safe_path),
            headers={
                "Content-Disposition": "inline",
                **cache_headers
            }
        )


def _get_media_type(path: Path) -> str:
    """根据文件后缀获取 MIME 类型"""
    suffix = path.suffix.lower()

    media_types = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.webp': 'image/webp',
        '.html': 'text/html',
        '.htm': 'text/html',
        '.md': 'text/markdown',
        '.markdown': 'text/markdown',
        '.pdf': 'application/pdf',
        '.json': 'application/json',
        '.csv': 'text/csv',
        '.txt': 'text/plain',
    }

    return media_types.get(suffix, 'application/octet-stream')