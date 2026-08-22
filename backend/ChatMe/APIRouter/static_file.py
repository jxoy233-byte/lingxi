"""
静态文件服务路由器
提供文件访问接口，支持前端预览图片、HTML、Markdown 等文件

使用方式:
    from ChatMe.APIRouter.static_file import static_file_router
    app.include_router(static_file_router)
"""
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Body, Request
from fastapi.responses import FileResponse

from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.paths import BACKEND_ROOT, CACHED_DIR

logger = get_logger("static_file")

# 之前这里写 `BACKEND_DIR = Path.cwd(); CACHED_DIR = BACKEND_DIR / "cached"`，
# cwd-依赖的写法在「从非 backend 目录启动进程」时会飘。统一从 ChatMe.paths
# 拿现成常量（已用 __file__ 锚定到 backend/）。
# 这里仍需要 BACKEND_ROOT 用来把 rglob 出的绝对路径回算成 "cached/..." 相对路径
# —— 跟 /static/cached/ 路由前缀对齐。

# session_id = uuid.uuid4().hex[:12] (12-char lowercase hex)；旧版曾用 32-char hex，
# 仍兼容遗留 sid —— PATH 中带 32-char 旧 sid 时不要 404。
SESSION_ID_PATTERN = re.compile(r"^([0-9a-f]{12}|[0-9a-f]{32})$")
# Referer URL 中提取 sid —— 12-char / 32-char 双兼容。
# 路径边界（`/` 或字符串首）+ 32/12 hex + 路径边界（`/` `?` `#` 或字符串尾）：
# 避免 31/13 等「凑巧 hex 长」被 12-char 分支误匹配（re.search 命中子串即返回）。
# 32-char 写前面 —— re 交替优先匹配左侧，URL 同时含 32/12-char 子串时取更长的那个。
SESSION_ID_RE = re.compile(r"/([0-9a-f]{32}|[0-9a-f]{12})(?:[/?#]|$)")


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
        # 相对 BACKEND_ROOT 取，保证 path 含 "cached/" 前缀，与 /static/cached/ 路由一致
        rel = f.relative_to(BACKEND_ROOT).as_posix()
        stat = f.stat()
        files.append({
            "path": rel,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    files.sort(key=lambda x: x["path"])
    return files


def list_session_files(session_dir: Path) -> List[dict]:
    """
    列出整个 session 目录下所有文件（扁平列表），范围比 list_data_analysis_files 广：
    包含 data_analysis/ 子目录 + 用户上传文件 + AI 中间产物等任何位置的文件。
    供前端 "工作树" 面板构树展示当前会话的全部产物。

    Args:
        session_dir: session 绝对路径 (cached/{session_id})

    Returns:
        [{"path": "cached/.../xxx", "size": int, "modified_at": str}, ...]
    """
    files = []
    if not session_dir.exists() or not session_dir.is_dir():
        return files
    for f in session_dir.rglob("*"):
        # 跳过隐藏文件 + 跳目录（虽然 rglob 也走文件，但 is_file 二次过滤）
        if not f.is_file() or f.name.startswith("."):
            continue
        # 相对 BACKEND_ROOT 取，保证 path 含 "cached/" 前缀，与 /static/cached/ 路由一致
        rel = f.relative_to(BACKEND_ROOT).as_posix()
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

    Returns:
        安全的绝对路径，或 None（路径穿越时）
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


def _has_session_id(path: str) -> bool:
    """检测 file_path 是否含 session_id（12 或 32 位 hex 在第一段）"""
    if path.startswith("cached/"):
        path = path[len("cached/"):]
    if not path:
        return False
    first_segment = path.split("/", 1)[0]
    return bool(SESSION_ID_PATTERN.match(first_segment))


def _extract_sid_from_referer(referer: str) -> Optional[str]:
    """
    从 Referer header 提取当前会话 sid。

    浏览器在发起请求时会自动带 Referer（除非 referrer-policy=no-referrer），
    URL 格式通常为 http://host/{sid} 或 http://host/{sid}/foo/bar。
    SESSION_ID_RE 优先匹配 32 位 hex（兼容旧版 sid），没命中再 fallback 12 位 hex（新版本）。

    Args:
        referer: Referer header 值，可能为空 / None / 异常格式

    Returns:
        提取到的 sid（12 或 32 位 hex），或 None
    """
    if not referer:
        return None
    m = SESSION_ID_RE.search(referer)
    return m.group(1) if m else None


def _resolve_fallback(filename: str, primary_sid: Optional[str] = None) -> Optional[Path]:
    """
    双层 fallback（按优先级）：

    1. **第一层**（如有 primary_sid）：在 `cached/{primary_sid}/` 下递归找 filename，按 mtime 最新返回
    2. **第二层**（兜底）：跨 `cached/*/` 所有 sid 找 filename，按 mtime 最新返回

    用于：URL 没有带 sid 的请求（如 markdown 裸文件 `<img src="/static/cached/06.png">`），
    fallback 时如果能从 Referer 推断出当前会话 sid，就优先返回当前会话的产物；
    没推断出 sid 或当前会话没同名文件时，再跨 sid 兜底。

    Args:
        filename: 纯文件名（basename），如 "06_category_metrics.png"
        primary_sid: 当前会话 sid（从 Referer 推断），可选

    Returns:
        命中的最新文件路径，或 None
    """
    if not CACHED_DIR.exists() or not CACHED_DIR.is_dir():
        return None

    # 第一层：primary_sid 优先
    if primary_sid:
        primary_dir = CACHED_DIR / primary_sid
        if primary_dir.is_dir():
            primary_hits = [
                f for f in primary_dir.rglob("*")
                if f.is_file() and f.name == filename
            ]
            if primary_hits:
                primary_hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return primary_hits[0]

    # 第二层：跨 sid 全局
    candidates = [
        f for f in CACHED_DIR.glob("*/**/*")
        if f.is_file() and f.name == filename
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


@static_file_router.get("/{file_path:path}", summary="访问 cached 目录下的文件")
async def serve_cached_file(
    file_path: str,
    request: Request,
    download: bool = Query(False, description="是否下载而非预览")
):
    """
    访问 cached 目录下的文件

    Args:
        file_path: 相对于 cached/ 的路径（可带或不带 "cached/" 前缀）
                   例如: cached/abc123/data_analysis/gen_001/charts/sales.png
                        或: abc123/data_analysis/gen_001/charts/sales.png
                        或: data_analysis/sales.png  （无 sid，走 fallback）
        download: True=下载, False=预览(默认inline显示)

    Returns:
        文件内容

    Fallback（URL 不带 sid 时触发）:
        1. **第一层**：从 Referer header 推断当前会话 sid（如果 Referer 缺失或无 sid 则跳过），
           优先在 `cached/{referer_sid}/` 下递归找同名文件
        2. **第二层**：跨 `cached/*/` 所有 sid 找同名文件，按 mtime 最新返回
        URL 带 sid 但精确路径找不到 → 直接 404（不跨会话命中）
    """
    safe_path = _get_safe_path(file_path)

    if safe_path is None:
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    if not safe_path.exists() or not safe_path.is_file():
        # 文件不存在或不是文件：尝试 fallback（仅限无 sid 的路径）
        if not _has_session_id(file_path):
            referer = request.headers.get("referer", "")
            referer_sid = _extract_sid_from_referer(referer)
            fallback = _resolve_fallback(Path(file_path).name, primary_sid=referer_sid)
            if fallback is not None:
                safe_path = fallback
                in_primary = referer_sid and referer_sid in fallback.parts
                scope = f"referer_sid={referer_sid}" if in_primary else (
                    f"referer_sid={referer_sid} (无命中，跨 sid)" if referer_sid else "无 referer (跨 sid)"
                )
                logger.info(
                    f"静态文件 fallback 命中: request={file_path} → {safe_path} | {scope}"
                )
            else:
                raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
        else:
            raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")

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