"""
静态文件服务路由器
提供文件访问接口，支持前端预览图片、HTML、Markdown 等文件

使用方式:
    from ChatMe.APIRouter.static_file import static_file_router
    app.include_router(static_file_router)
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import FileResponse

from ChatMe.LoggingManager.logging_config import get_logger

logger = get_logger("static_file")

# 获取 backend 根目录（使用 __file__ 相对路径，避免依赖启动目录）
BACKEND_DIR = Path.cwd()
CACHED_DIR = BACKEND_DIR / "cached"


static_file_router = APIRouter(prefix="/static", tags=["静态文件"])


def list_data_analysis_files(data_analysis_dir: Path, base_rel: str) -> List[dict]:
    """
    列出 data_analysis 目录下所有文件（扁平列表），供前端自行构树。

    Args:
        data_analysis_dir: data_analysis 绝对路径
        base_rel: 路径前缀，如 "cached/{session_id}/data_analysis"

    Returns:
        [{"path": "cached/.../xxx.png", "size": int, "modified_at": str}, ...]
    """
    files = []
    if not data_analysis_dir.exists() or not data_analysis_dir.is_dir():
        return files
    for f in data_analysis_dir.rglob("*"):
        if not f.is_file() or f.name.startswith("."):
            continue
        # 相对 BACKEND_DIR 取，保证 path 含 "cached/" 前缀，与 /static/cached/ 路由一致
        rel = f.relative_to(BACKEND_DIR).as_posix()
        stat = f.stat()
        files.append({
            "path": rel,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    files.sort(key=lambda x: x["path"])
    return files


@static_file_router.put("/{file_path:path}", summary="写入文件内容")
async def write_cached_file(
    file_path: str,
    content: str = Body(..., description="文件内容")
):
    """
    写入文件内容到 cached 目录

    Args:
        file_path: 相对于 cached/ 的路径（可带或不带 "cached/" 前缀）
        content: 文件内容
    """
    safe_path = _get_safe_path(file_path)

    if safe_path is None:
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    # 确保父目录存在
    safe_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入内容
    try:
        safe_path.write_text(content, encoding="utf-8")
    except Exception as e:
        logger.error(f"写入文件失败: {safe_path}, error: {e}")
        raise HTTPException(status_code=500, detail=f"写入文件失败: {e}")

    logger.info(f"文件写入成功: {safe_path}")
    return {"message": "文件保存成功", "path": file_path}


def _get_safe_path(path: str) -> Optional[Path]:
    """
    将相对路径转换为安全的绝对路径
    防止路径穿越攻击
    接受两种格式：
      - "cached/{sid}/..." （自动剥 cached/ 前缀）
      - "{sid}/..." （直接拼到 CACHED_DIR）
    """
    # 移除开头的 cached/
    if path.startswith("cached/"):
        path = path[len("cached/"):]

    # 拼接基础目录
    base = CACHED_DIR
    target = (base / path).resolve()

    # 确保目标在 CACHED_DIR 内
    if not str(target).startswith(str(base)):
        logger.warning(f"路径穿越检测: {target} 不在 {base} 内")
        return None

    return target


@static_file_router.get("/{file_path:path}", summary="访问 cached 目录下的文件")
async def serve_cached_file(
    file_path: str,
    download: bool = Query(False, description="是否下载而非预览")
):
    """
    访问 cached 目录下的文件

    Args:
        file_path: 相对于 cached/ 的路径（可带或不带 "cached/" 前缀）
                   例如: cached/abc123/data_analysis/gen_001/charts/sales.png
                        或: abc123/data_analysis/gen_001/charts/sales.png
        download: True=下载, False=预览(默认inline显示)

    Returns:
        文件内容
    """
    safe_path = _get_safe_path(file_path)

    if safe_path is None:
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    if not safe_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")

    if not safe_path.is_file():
        raise HTTPException(status_code=400, detail="该路径不是文件")

    logger.debug(f"静态文件访问: {safe_path}, download={download}")

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