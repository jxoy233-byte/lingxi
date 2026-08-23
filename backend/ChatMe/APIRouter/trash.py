"""
文件 / 目录回收站管理 API。

设计要点：
- 软删除：DELETE /chat/{sid}/file 把目标移到 .trash/{sid}/{timestamp}/{file_path}
  —— 直接保留原路径作为子目录，**不丢信息**。这样 restore 时路径从目录结构反推，
  无需 sidecar 元数据。
- 硬删除：DELETE /chat/{sid}/trash/item 单条物理删除；DELETE /chat/{sid}/trash
  清空当前会话整树。
- 恢复：POST /chat/{sid}/trash/restore 把 .trash/{sid}/{ts}/{rel_path} 整体
  shutil.move 回 cached/{sid}/{rel_path}；目标位置已存在则拒绝（避免覆盖当前数据）。
- 定时兜底：每天 11:30 APScheduler `daily_trash_cleanup` 物理清空整个 .trash/。

为什么用「{timestamp}/{file_path}」目录结构而不是扁平命名：
- 扁平命名 `{ts}_{rel_with_slashes_replaced_by_underscores}` 是**有损**的：
  `data_analysis/gen_001/选题_v2.md` 和 `data_analysis/gen_001/选题/v2.md`
  都会变成 `{ts}_data_analysis_gen_001_选题_v2.md`，**无法区分**。
- 目录结构 `{ts}/{rel_path}` 保留了 `/` 分隔，反推路径无歧义，且无需 sidecar。

路径安全：
- 拒绝绝对路径 / ".." 段 / resolve 后越界（必须落在 TRASH_DIR/{sid}/ 下）。
- 恢复时同样校验恢复目标必须落在 CACHED_DIR/{sid}/ 下。

为什么是软删除不是物理删除：用户误删能找回（直到 11:30 物理清理），
符合「二次确认只是延迟，不是不可逆」的产品约定。
"""
from __future__ import annotations

import pathlib
import re
import shutil
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field

from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.paths import BACKEND_ROOT, CACHED_DIR, TRASH_DIR


router = APIRouter(prefix="/chat", tags=["回收站"])

logger = get_logger("TrashAPI")

# trash_path / timestamp 格式：YYYYMMDD_HHMMSS（防误判 + 校验脏数据）
_TIMESTAMP_RE = re.compile(r"^\d{8}_\d{6}$")


# ─────────────────────────────────────────────────────────────────────────────
# 软删除：DELETE /chat/{sid}/file
# ─────────────────────────────────────────────────────────────────────────────
@router.delete(
    "/{session_id}/file",
    summary="软删除会话文件（移到 .trash/，每天 11:30 定时清理）",
)
async def delete_session_file(
    session_id: str = Path(..., description="会话ID"),
    file_path: str = Query(
        ...,
        description="相对 cached/{session_id}/ 的路径，如 data_analysis/gen_001/charts/sales.png",
    ),
):
    """会话文件树右键/行内删除文件 / 目录 —— 软删除实现。

    1. 拒绝绝对路径 / 路径越界（必须落在 cached/{session_id}/ 下）
    2. 文件 / 目录都支持：shutil.move 对目录自动 rmtree 整树移到 .trash/
    3. 移目标到 .trash/{session_id}/{timestamp}/{file_path}（保留目录结构）
    4. 同秒删不同文件 → 落到不同子目录，无冲突

    Returns:
        {"code": 200, "msg": "...", "trash_path": "...", "timestamp": "..."}
        {"code": 400/404, "msg": "..."} on error
    """
    if not file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="file_path 必须为相对路径")

    if ".." in pathlib.Path(file_path).parts:
        raise HTTPException(status_code=400, detail="file_path 含非法 '..' 段")

    target = (CACHED_DIR / session_id / file_path).resolve()
    session_root = (CACHED_DIR / session_id).resolve()
    try:
        target.relative_to(session_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="file_path 越界，不得跨出会话目录")

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")

    # 直接保留目录结构：.trash/{sid}/{ts}/{file_path}
    # 同秒删两个不同文件 → 落到 {ts} 下的不同子目录，不会撞名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_target = TRASH_DIR / session_id / timestamp / file_path
    trash_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(trash_target))

    logger.info(f"[delete_session_file] {session_id}/{file_path} → {trash_target}")
    return {
        "code": 200,
        "msg": "已移至 .trash/（每天 11:30 定时清理）",
        "trash_path": str(trash_target.relative_to(BACKEND_ROOT)),
        "timestamp": timestamp,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 列回收站：GET /chat/{sid}/trash/tree
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/{session_id}/trash/tree",
    summary="列出当前会话 .trash/ 下的所有软删除项",
)
async def list_session_trash(
    session_id: str = Path(..., description="会话ID"),
):
    """扫描 .trash/{sid}/ 下顶层时间戳目录，每个目录里**递归**列原路径结构的文件。

    .trash/{sid}/{ts}/{file_path}：
    - 第一层 `{ts}` 是删除时间戳（YYYYMMDD_HHMMSS）
    - 第二层开始是原 cached/{sid}/ 下的相对路径（保留 `/`，**递归到所有文件**）

    注意：目录删除会把整树搬过来（如 .trash/{sid}/{ts}/dir/sub/file.md），
    所以必须 `rglob("*")` 而不是只 iterdir 一层 —— 否则深层文件会丢失。

    返回时按删除时间（{ts} 目录的 mtime）倒序排列，最新的在最上面。
    **每条 item 都是一个文件**（目录删除被展开为多个文件项逐个展示/恢复/删除），
    没有"目录当作一个 item"的概念 —— 这样不依赖额外元数据就能 1:1 还原原路径。

    Returns:
        {
            "trash_root": ".trash/{sid}/",
            "items": [
                {
                    "name": "data_analysis/gen_001/charts/选题.md",  # 相对 {ts}/，即原路径
                    "type": "file",
                    "trash_path": "{ts}/data_analysis/gen_001/charts/选题.md",  # ← restore/delete-item 端点直接用这个
                    "size": 12345,
                    "modified_at": "...",
                    "original_path": "data_analysis/gen_001/charts/选题.md",  # 从目录结构反推
                    "deleted_at": "...",  # {ts} 目录的 mtime（删除时间）
                    "timestamp": "20260823_173845",  # 时间戳分组，前端展示
                    "is_directory": false,
                },
                ...
            ],
        }
    """
    trash_session_dir = TRASH_DIR / session_id
    if not trash_session_dir.exists():
        return {
            "trash_root": str(trash_session_dir.relative_to(BACKEND_ROOT)) + "/",
            "items": [],
        }

    items: list[dict] = []
    # 顶层是时间戳目录；可能混有 legacy 扁平文件 / sidecar（v0.1.7 旧版本写的）
    for ts_dir in trash_session_dir.iterdir():
        # 兼容旧格式：顶层是 `.meta.json` 或扁平文件 → 跳过（清单不再展示，但定时清理会一并删）
        if not ts_dir.is_dir():
            continue
        # 校验时间戳格式；非时间戳目录也跳过
        if not _TIMESTAMP_RE.match(ts_dir.name):
            logger.warning(f"[list_session_trash] 跳过非时间戳目录: {ts_dir}")
            continue

        ts_mtime = datetime.fromtimestamp(ts_dir.stat().st_mtime).isoformat()

        # 递归列出 ts_dir 下所有文件 —— 目录删除会把整树搬过来，
        # 必须 rglob 到底，否则只会展示一级子目录（list 一层会漏掉深层文件）
        for entry in ts_dir.rglob("*"):
            if not entry.is_file():
                continue
            # 兼容旧版 sidecar（理论上不该出现，但防御一下）
            if entry.name.endswith(".meta.json"):
                continue
            # 相对 ts_dir 的路径就是 original_path（保留 `/`）
            rel_to_ts = entry.relative_to(ts_dir).as_posix()
            stat = entry.stat()

            items.append(
                {
                    "name": rel_to_ts,
                    "type": "file",
                    "trash_path": f"{ts_dir.name}/{rel_to_ts}",
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "original_path": rel_to_ts,
                    "deleted_at": ts_mtime,
                    "timestamp": ts_dir.name,
                    "is_directory": False,
                }
            )

    # 按 timestamp 字符串倒序（YYYYMMDD_HHMMSS 字典序 = 时间序）
    items.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "trash_root": str(trash_session_dir.relative_to(BACKEND_ROOT)) + "/",
        "items": items,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 硬清空当前会话整树：DELETE /chat/{sid}/trash
# ─────────────────────────────────────────────────────────────────────────────
@router.delete(
    "/{session_id}/trash",
    summary="手工清空当前会话的 .trash/ 目录",
)
async def clear_session_trash(
    session_id: str = Path(..., description="会话ID"),
):
    """物理清理 .trash/{session_id}/ 下所有文件（前端文件树「清空回收站」按钮走这里）。

    与定时清理的关系：
    - 每天 11:30 APScheduler 会自动跑 `clean_trash()` 清空整个 .trash/
    - 本接口允许用户从前端随时清空当前会话的 trash（不阻塞其他 session）
    - 都基于 `TRASH_DIR` 同款路径，无歧义

    Returns:
        {"code": 200, "removed": N, "freed_bytes": B, "session_id": "..."}
    """
    trash_session_dir = TRASH_DIR / session_id
    if not trash_session_dir.exists():
        return {
            "code": 200,
            "msg": "回收站为空",
            "removed": 0,
            "freed_bytes": 0,
            "session_id": session_id,
        }

    # 先扫一遍统计：rglob("*") 包含子目录，但只统计文件大小 / 数量
    removed = 0
    freed_bytes = 0
    for entry in trash_session_dir.rglob("*"):
        if entry.is_file():
            freed_bytes += entry.stat().st_size
            removed += 1
    shutil.rmtree(trash_session_dir)

    logger.info(f"[clear_session_trash] {session_id} 清理 {removed} 个文件，释放 {freed_bytes} bytes")
    return {
        "code": 200,
        "msg": f"已清理 {removed} 个文件",
        "removed": removed,
        "freed_bytes": freed_bytes,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 整目录批量删除：DELETE /chat/{sid}/trash/folder
# ─────────────────────────────────────────────────────────────────────────────
@router.delete(
    "/{session_id}/trash/folder",
    summary="批量物理删除 .trash/ 下指定 original_path 前缀的所有项",
)
async def delete_trash_folder(
    session_id: str = Path(..., description="会话ID"),
    path_prefix: str = Query(
        ...,
        description="original_path 前缀，如 data_analysis/gen_001/；会删 original_path 完全等于"
                    "或以此为前缀 + '/' 的所有文件（区分 'data/foo' 单文件和 'data/foo/bar' 子文件）",
    ),
):
    """批量删除回收站中 original_path 以 path_prefix 开头的所有项。

    用于「回收站树目录节点 ×」按钮（一键删整目录 + 所有子文件）。

    与 DELETE /{sid}/trash/item（单条）的区别：
    - 单条只删一条；本端点按 prefix 批量匹配，**单次往返删 N 个文件**
    - 不返回每条 trash_path，只返回总数 + 释放字节数

    匹配规则（避免「data/foo」误匹配「data/foo2/x」这种）：
    - `rel == prefix`（精确匹配，覆盖「原删除对象本身是单文件」的情况）
    - `rel.startswith(prefix + '/')`（子路径匹配）

    路径安全：
    - 拒绝绝对路径 / ".." 段（path_prefix 是 original_path 前缀，恒为相对路径）
    - 不需要 relative_to 校验 —— path_prefix 只用来字符串匹配 + 拼路径做 unlink，
      实际 unlink 目标必须落在 TRASH_DIR/{sid}/ 下，路径安全靠 `..` 段校验把住

    顺带清理：
    - 空目录（用户删了一个空目录进 trash 的情况，rglob 不列）→ rmdir
    - 变空的 ts_dir → rmdir

    Returns:
        {"code": 200, "msg": "...", "removed": N, "freed_bytes": B, "path_prefix": "..."}
    """
    if not path_prefix or path_prefix.startswith("/"):
        raise HTTPException(status_code=400, detail="path_prefix 必须为相对路径")

    if ".." in pathlib.Path(path_prefix).parts:
        raise HTTPException(status_code=400, detail="path_prefix 含非法 '..' 段")

    trash_session_dir = TRASH_DIR / session_id
    if not trash_session_dir.exists():
        return {
            "code": 200,
            "msg": "回收站为空",
            "removed": 0,
            "freed_bytes": 0,
            "path_prefix": path_prefix,
            "session_id": session_id,
        }

    # 规范化 prefix（去掉末尾 /），避免 "data/" 和 "data" 被当成不同 prefix
    prefix = path_prefix.rstrip("/")
    prefix_slash = prefix + "/"

    removed = 0
    freed_bytes = 0
    affected_ts_dirs: set = set()

    for ts_dir in trash_session_dir.iterdir():
        if not ts_dir.is_dir() or not _TIMESTAMP_RE.match(ts_dir.name):
            continue

        # 先 collect 再 unlink —— rglob 是 generator，迭代中修改文件系统会乱
        to_delete: list[pathlib.Path] = []
        for entry in ts_dir.rglob("*"):
            if not entry.is_file():
                continue
            if entry.name.endswith(".meta.json"):
                continue
            rel = entry.relative_to(ts_dir).as_posix()
            if rel == prefix or rel.startswith(prefix_slash):
                to_delete.append(entry)

        for entry in to_delete:
            freed_bytes += entry.stat().st_size
            entry.unlink()
            removed += 1
        if to_delete:
            affected_ts_dirs.add(ts_dir)

        # 兜底：原删除对象本身是空目录 → rglob 不会列出，单独 rmdir
        target_dir = ts_dir / prefix
        if target_dir.is_dir():
            try:
                target_dir.rmdir()  # 只在空目录成功，非空抛 OSError
            except OSError:
                pass

    # 清理可能变空的 ts_dir
    for ts_dir in affected_ts_dirs:
        while ts_dir != trash_session_dir and ts_dir.is_dir():
            try:
                ts_dir.rmdir()
                break
            except OSError:
                break

    logger.info(
        f"[delete_trash_folder] {session_id}/{path_prefix} 删除 {removed} 个文件，"
        f"释放 {freed_bytes} bytes"
    )
    return {
        "code": 200,
        "msg": f"已删除 {removed} 个文件",
        "removed": removed,
        "freed_bytes": freed_bytes,
        "path_prefix": path_prefix,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 硬删除单条：DELETE /chat/{sid}/trash/item
# ─────────────────────────────────────────────────────────────────────────────
@router.delete(
    "/{session_id}/trash/item",
    summary="物理删除 .trash/ 下单个项",
)
async def delete_trash_item(
    session_id: str = Path(..., description="会话ID"),
    trash_path: str = Query(
        ...,
        description="相对 .trash/{sid}/ 的路径，格式 {timestamp}/{file_path}",
    ),
):
    """从回收站永久删除单个项。

    trash_path 格式：`{YYYYMMDD_HHMMSS}/{rel_to_cached}`（与 list_session_trash 返回的 path 一致）

    与 DELETE /{session_id}/trash（整树清空）的区别：本接口是行内单条删除，
    适用于「保留其他项、只彻底删这一条」的精细场景。

    安全：
    - 拒绝绝对路径 / .. 段 / 越界（必须落在 .trash/{sid}/ 下）
    - 文件 unlink，目录 rmtree

    Returns:
        {"code": 200, "msg": "已物理删除", "trash_path": "..."}
    """
    if not trash_path or trash_path.startswith("/"):
        raise HTTPException(status_code=400, detail="trash_path 必须为相对路径")

    if ".." in pathlib.Path(trash_path).parts:
        raise HTTPException(status_code=400, detail="trash_path 含非法 '..' 段")

    target = (TRASH_DIR / session_id / trash_path).resolve()
    trash_root = (TRASH_DIR / session_id).resolve()
    try:
        target.relative_to(trash_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="trash_path 越界，不得跨出回收站")

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"回收站项不存在: {trash_path}")

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    # 顺手把空的时间戳目录也清掉（最后一个 item 删除后 ts_dir 变空 → rmdir）
    # 用 try/except 兜底：rmdir 在目录非空时会抛 OSError，捕获即可
    ts_dir = target.parent
    while ts_dir != trash_root and ts_dir.is_dir():
        try:
            ts_dir.rmdir()  # 只在空目录成功，非空抛 OSError
            break  # rmdir 成功说明该 ts_dir 已空，整链就此打住
        except OSError:
            break  # 还有别的 item，跳过

    logger.info(f"[delete_trash_item] {session_id}/{trash_path} 已物理删除")
    return {
        "code": 200,
        "msg": "已物理删除",
        "trash_path": str(target.relative_to(BACKEND_ROOT)),
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 恢复单条：POST /chat/{sid}/trash/restore
# ─────────────────────────────────────────────────────────────────────────────
class RestoreTrashRequest(BaseModel):
    """恢复请求体：trash_path 是相对 .trash/{sid}/ 的路径（格式 `{ts}/{rel}`）。"""

    trash_path: str


@router.post(
    "/{session_id}/trash/restore",
    summary="从 .trash/ 恢复一个项到原始位置",
)
async def restore_trash_item(
    session_id: str = Path(..., description="会话ID"),
    body: RestoreTrashRequest = Body(...),
):
    """把 .trash/{sid}/{ts}/{file_path} 移回 cached/{sid}/{file_path}。

    original_path 从目录结构反推：`trash_path = {ts}/{rel}` → original = `{rel}`
    （无需 sidecar 即可恢复，不会猜错）

    流程：
    1. 解析 trash_path 拆出 timestamp + file_path
    2. 校验 timestamp 是 YYYYMMDD_HHMMSS 格式（防脏数据）
    3. 计算恢复目标 cached/{sid}/{file_path}，校验必须落在 CACHED_DIR/{sid}/ 下
    4. 若恢复目标已存在 → 409 冲突（拒绝覆盖，避免意外丢当前数据）
    5. mkdir -p 父目录 → shutil.move
    6. 顺手清理空的时间戳目录

    Returns:
        {"code": 200, "msg": "已恢复", "restored_path": "...", "original_path": "..."}
        {"code": 409, "msg": "目标位置已存在文件，请先处理后再恢复"} on collision
    """
    trash_path = body.trash_path
    if not trash_path or trash_path.startswith("/"):
        raise HTTPException(status_code=400, detail="trash_path 必须为相对路径")
    if ".." in pathlib.Path(trash_path).parts:
        raise HTTPException(status_code=400, detail="trash_path 含非法 '..' 段")

    # 拆出 {ts}/{rel} —— 必须恰好一段 '/'
    parts = trash_path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(
            status_code=400,
            detail="trash_path 格式必须为 {timestamp}/{file_path}",
        )
    timestamp, original_path = parts

    if not _TIMESTAMP_RE.match(timestamp):
        raise HTTPException(
            status_code=400,
            detail=f"timestamp 格式不合法（应为 YYYYMMDD_HHMMSS）: {timestamp!r}",
        )

    # trash 源路径安全检查
    source = (TRASH_DIR / session_id / trash_path).resolve()
    trash_root = (TRASH_DIR / session_id).resolve()
    try:
        source.relative_to(trash_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="trash_path 越界，不得跨出回收站")

    if not source.exists():
        raise HTTPException(status_code=404, detail=f"回收站项不存在: {trash_path}")

    # 恢复目标：cached/{sid}/{original_path}
    restore_target = (CACHED_DIR / session_id / original_path).resolve()
    session_root = (CACHED_DIR / session_id).resolve()
    try:
        restore_target.relative_to(session_root)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"original_path 越界: {original_path!r}",
        )

    # 冲突保护：恢复位置已存在 → 拒绝（避免覆盖当前数据）
    if restore_target.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f"恢复目标已存在: {original_path}；请先处理同名文件再恢复，"
                "或先删再恢复"
            ),
        )

    # mkdir -p 父目录 → shutil.move
    restore_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(restore_target))

    # 顺手把空了的时间戳目录删掉（最后一个 item 恢复后 ts_dir 变空 → rmdir）
    ts_dir = source.parent  # 这是 .trash/{sid}/{ts}/
    try:
        ts_dir.rmdir()
    except OSError:
        pass  # 还有别的 item，保留目录

    logger.info(
        f"[restore_trash_item] {session_id}/{trash_path} → "
        f"{restore_target.relative_to(BACKEND_ROOT)}"
    )
    return {
        "code": 200,
        "msg": "已恢复",
        "restored_path": str(restore_target.relative_to(BACKEND_ROOT)),
        "original_path": original_path,
        "timestamp": timestamp,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 一键全部软删除：DELETE /chat/{sid}/files
# ─────────────────────────────────────────────────────────────────────────────
@router.delete(
    "/{session_id}/files",
    summary="一键软删除工作树下全部文件 / 目录（移到 .trash/）",
)
async def soft_delete_all_files(
    session_id: str = Path(..., description="会话ID"),
):
    """一键软删除 cached/{session_id}/ 下的全部文件 / 目录到 .trash/{session_id}/{timestamp}/。

    对应前端文件树面板头部的「一键软删除」按钮（ConfirmDialog 二次确认后触发）。

    与 DELETE /{sid}/file（单条软删除）的区别：
    - 单条每调用一次生成一个新 timestamp；本端点**共享一个 timestamp**（逻辑分组：
      「这次一键全删」），trash 树里能看到一个统一的 `{ts}/` 根目录容纳本次全部产物
    - 单次往返删 N 个文件 / 目录

    与 DELETE /{sid}/trash（物理清空整树回收站）的区别：
    - 那条是**物理删除**（rmtree，不可恢复）；本端点是**软删除**（移到 .trash，
      可恢复，符合偏好 32 「二次确认是兜底」原则）

    安全：
    - 拒绝绝对路径 / .. 段（已在原 `delete_session_file` 校验过，此处同理）
    - 只操作 CACHED_DIR/{sid}/ 下的内容（不跨会话）

    容错：
    - 单个文件不存在（race condition：并发删）→ 跳过，计入 skipped
    - 目录不存在（session 已被清空）→ 返回 removed=0

    Returns:
        {
        "code": 200,
        "msg": "已软删除 N 个文件 / 目录",
        "removed": N,
        "skipped": M,
        "timestamp": "20260823_173845",
        "trash_path": ".trash/{sid}/{ts}/",
        "session_id": "...",
        }
    """
    session_root = (CACHED_DIR / session_id).resolve()
    if not session_root.exists():
        return {
            "code": 200,
            "msg": "会话无文件，无需清理",
            "removed": 0,
            "skipped": 0,
            "timestamp": None,
            "session_id": session_id,
        }

    # 共享一个 timestamp：trash 树里整个一键全删的产物集中在同一 ts_dir 下，
    # 视觉上像「一次操作」的产物。
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_root = TRASH_DIR / session_id / timestamp
    trash_root.mkdir(parents=True, exist_ok=True)

    removed = 0
    skipped = 0
    # 先 collect 再 move：rglob 是 generator，迭代中修改文件系统会乱
    entries = [e for e in session_root.rglob("*") if e.exists()]
    for entry in entries:
        try:
            rel = entry.relative_to(session_root).as_posix()
        except ValueError:
            # resolve 后路径不再 relative_to session_root（symlink 越界）
            logger.warning(f"[soft_delete_all_files] 跳过越界项: {entry}")
            skipped += 1
            continue
        target = trash_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(entry), str(target))
            removed += 1
        except FileNotFoundError:
            # race condition：并发删了，跳过
            skipped += 1
        except Exception as e:
            logger.error(f"[soft_delete_all_files] move 失败 {entry}: {e}")
            skipped += 1

    logger.info(
        f"[soft_delete_all_files] {session_id} 软删除 {removed} 项（跳过 {skipped}） → {trash_root}"
    )
    return {
        "code": 200,
        "msg": f"已软删除 {removed} 个文件 / 目录",
        "removed": removed,
        "skipped": skipped,
        "timestamp": timestamp,
        "trash_path": str(trash_root.relative_to(BACKEND_ROOT)) + "/",
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 指定路径批量软删除：POST /chat/{sid}/files/soft-delete
# ─────────────────────────────────────────────────────────────────────────────
class BatchSoftDeleteRequest(BaseModel):
    """批量软删除请求体：file_paths 是相对 cached/{sid}/ 的路径数组。

    对应前端多选场景：用户 Cmd/Ctrl+click 选中 N 个节点 → Delete 一次软删。
    """

    file_paths: list[str] = Field(
        ...,
        description="相对 cached/{session_id}/ 的路径数组（可同时含文件和目录）",
    )


@router.post(
    "/{session_id}/files/soft-delete",
    summary="批量软删除指定路径列表（移到 .trash/，前端多选 Delete 走这里）",
)
async def soft_delete_files(
    session_id: str = Path(..., description="会话ID"),
    body: BatchSoftDeleteRequest = Body(...),
):
    """批量软删除指定路径列表到 .trash/{session_id}/{timestamp}/。

    与 DELETE /{sid}/files（一键全删）的区别：
    - 一键全删遍历整棵 cached 树，本端点按 caller 给的精确路径集合删
    - 共享一个 timestamp（与一键全删一致，trash 树里同一 ts_dir 容纳本次全部产物）
    - 单次往返删 N 个文件 / 目录

    与 DELETE /{sid}/file（单条软删除）的区别：
    - 单条每调用一次生成一个新 timestamp；本端点**共享一个 timestamp**
    - 单次往返删 N 个文件 / 目录

    安全：
    - 每个 file_path 拒绝绝对路径 / 含 `..` 段 / 越界（必须落在 CACHED_DIR/{sid}/ 下）
    - 校验失败的路径跳过（记 skipped + reason），不阻断整体操作

    容错：
    - 单个路径不存在（race condition 或 stale 视图）→ 跳过（skipped++）
    - 父目录在前面已被删的情况 → 跳过（避免重复删）

    Returns:
        {
        "code": 200,
        "msg": "已软删除 N 个路径",
        "removed": N,
        "skipped": M,
        "failures": [{"path": "...", "reason": "..."}],
        "timestamp": "20260823_173845",
        "session_id": "...",
        }
    """
    file_paths = body.file_paths
    if not file_paths:
        raise HTTPException(status_code=400, detail="file_paths 不能为空")

    if len(file_paths) > 500:
        # 防御性上限：避免一次搬 1 万个文件撑爆 FS / 锁
        raise HTTPException(status_code=400, detail="file_paths 一次最多 500 个")

    session_root = (CACHED_DIR / session_id).resolve()
    if not session_root.exists():
        raise HTTPException(status_code=404, detail=f"会话目录不存在: {session_id}")

    # 共享一个 timestamp：trash 树里整次批量软删的产物集中在同一 ts_dir 下，
    # 视觉上像「一次操作」的产物，与一键全删一致
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_root = TRASH_DIR / session_id / timestamp
    trash_root.mkdir(parents=True, exist_ok=True)

    removed = 0
    skipped = 0
    failures: list[dict] = []

    # 先按「深 → 浅」排序，让父目录排在子目录之后（避免先删父再删子的 dependency 错乱）
    sorted_paths = sorted(file_paths, key=lambda p: p.count("/"), reverse=True)

    for rel_path in sorted_paths:
        # 路径安全校验
        if not rel_path or rel_path.startswith("/"):
            failures.append({"path": rel_path, "reason": "必须是相对路径"})
            skipped += 1
            continue
        if ".." in pathlib.Path(rel_path).parts:
            failures.append({"path": rel_path, "reason": "路径含非法 '..' 段"})
            skipped += 1
            continue
        target = (CACHED_DIR / session_id / rel_path).resolve()
        try:
            target.relative_to(session_root)
        except ValueError:
            failures.append({"path": rel_path, "reason": "路径越界"})
            skipped += 1
            continue
        if not target.exists():
            failures.append({"path": rel_path, "reason": "不存在"})
            skipped += 1
            continue
        trash_target = trash_root / rel_path
        trash_target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(target), str(trash_target))
            removed += 1
        except FileNotFoundError:
            failures.append({"path": rel_path, "reason": "race condition"})
            skipped += 1
        except Exception as e:
            logger.error(f"[soft_delete_files] move 失败 {rel_path}: {e}")
            failures.append({"path": rel_path, "reason": str(e)})
            skipped += 1

    logger.info(
        f"[soft_delete_files] {session_id} 软删除 {removed} 项（跳过 {skipped}） → {trash_root}"
    )
    return {
        "code": 200,
        "msg": f"已软删除 {removed} 个路径",
        "removed": removed,
        "skipped": skipped,
        "failures": failures,
        "timestamp": timestamp,
        "session_id": session_id,
    }