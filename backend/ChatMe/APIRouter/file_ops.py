"""
文件操作 API —— IDEA 风格「复制/粘贴/剪切/重命名/新建」。

端点（全部 POST /chat/{sid}/file/...）：
- POST /chat/{sid}/file/copy    body={src, dst_dir}        复制 src 到 dst_dir/{basename(src)}
- POST /chat/{sid}/file/move    body={src, dst_dir}        移动（剪切+粘贴）src 到 dst_dir/{basename(src)}
- POST /chat/{sid}/files/copy   body={srcs, dst_dir}       批量复制 srcs 列表到 dst_dir
- POST /chat/{sid}/files/move   body={srcs, dst_dir}       批量移动 srcs 列表到 dst_dir
- POST /chat/{sid}/file/rename  body={src, new_name}       重命名 src（仅改末段名）
- POST /chat/{sid}/folder       body={parent, name}        新建目录
- POST /chat/{sid}/file         body={parent, name, content?} 新建空文件

为什么集中在 file_ops.py：
- 现有 trash.py 只管「删除/恢复」轴；新增「编辑」轴分散到不同 router 会让路径校验、sid 校验、
  CACHED_DIR resolve 等逻辑重复实现。本模块把「文件编辑」四件套（copy/move/rename/create）
  集中在一起，复用同一套路径安全 + sid 校验。

路径安全：
- 拒绝绝对路径 / `..` 段 / resolve 后越界（必须落在 CACHED_DIR/{sid}/ 下）
- src 必须存在；dst 不允许覆盖现有文件 / 目录（避免误操作）
- move 操作：跨目录剪切粘贴；同目录 move 退化成 rename（避免歧义）
- copy / move 到自身子目录 → 400 拒绝（递归死循环防御）

冲突策略：
- copy / move / rename 目标已存在 → 409 冲突（与 trash restore 一致，让用户先手动处理）
- create 新建时已存在 → 409 冲突
- 批量 copy / move：单条冲突 → failures 列出，整体不回滚（让用户感知具体哪些失败）

命名空间边界：
- 一律用相对 cached/{sid}/ 的路径（path / dst_dir / parent 全部相对路径）
- basename 推断由 `Path(src).name` 取，不引入额外字段
"""
from __future__ import annotations

import pathlib
import re
import shutil
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field

from ChatMe.APIRouter.static_file import SESSION_ID_PATTERN
from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.paths import BACKEND_ROOT, CACHED_DIR

logger = get_logger("FileOpsAPI")

router = APIRouter(prefix="/chat", tags=["文件操作"])


# ─────────────────────────────────────────────────────────────────────────────
# 通用路径校验工具
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_safe(session_id: str, rel_path: str) -> pathlib.Path:
    """校验 sid + rel_path，把 rel_path resolve 到绝对路径。

    - sid 必须满足 SESSION_ID_PATTERN（12 或 32 位 hex）
    - rel_path 允许空字符串（表示 sid 根目录） / 拒绝绝对路径 / 含 `..` 段
    - resolve 后必须落在 CACHED_DIR/{sid}/ 下（防 symlink 越界）
    """
    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail=f"非法 sid: {session_id!r}")
    if rel_path.startswith("/"):
        raise HTTPException(status_code=400, detail="路径必须为相对路径（不能以 / 开头）")
    if rel_path and ".." in pathlib.Path(rel_path).parts:
        raise HTTPException(status_code=400, detail="路径含非法 '..' 段")
    target = (CACHED_DIR / session_id / rel_path).resolve()
    session_root = (CACHED_DIR / session_id).resolve()
    try:
        target.relative_to(session_root)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"路径越界: {rel_path!r}")
    return target


def _relativize(p: pathlib.Path, session_id: str) -> str:
    """把绝对路径反算成相对 cached/{sid}/ 的字符串。"""
    return str(p.relative_to(CACHED_DIR / session_id))


_TRAILING_COUNTER_RE = re.compile(r"^(.*?)\((\d+)\)$")


def _find_unique_name(dst_dir: pathlib.Path, original_name: str) -> str:
    r"""在 dst_dir 下找一个不冲突的名字，冲突时累加 (1) / (2) / ...

    规则（用「首个非前导点」切 base/ext）：
    - foo.txt → foo(1).txt → foo(2).txt ...
    - foo（无扩展）→ foo(1) → foo(2) ...
    - foo.tar.gz → foo(1).tar.gz → ...（在第一个 . 前插入 (N)）
    - .gitignore（隐藏文件）→ .gitignore(1) → ...
    - .gitignore.backup → .gitignore(1).backup → ...
    - **foo(1).py（已带计数器后缀）→ 剥掉 (1) → base='foo' → foo(2).py**
      —— 复制「已被自动改名过的副本」时也要基于**原始 stem** 找下一个空位，
      否则会生成 `foo(1)(1).py` / `foo(1)(2).py` 这种无限累加后缀的怪名字。
      这条与 macOS Finder / Windows Explorer 的「Duplicate 计数器」行为一致。

    为什么用首个非前导点（而不是末点）：Finder 把 `.tar.gz` 当作一个完整复合扩展，
    重命名时只把前面的 stem 加上 `(N)`；用末点会得到 `foo.tar(1).gz` 同样能跑但语义不如前者清晰。

    为什么 base 和 (N) 之间无空格：紧凑命名 `xxx12.py → xxx12(1).py` 视觉密度更友好，
    跟 Python/JS 常见模式（`x1`, `v2`）一致；带空格的 `foo (1).txt` 偏向 macOS Finder 默认，
    这里按用户偏好选无空格紧凑风格。

    为什么「末尾 (N) 计数剥除」只剥数字：`(bar)` / `(v1-beta)` 这类非纯数字括号会被保留，
    不当作计数器（regex `(\d+)` 限定数字）；避免误伤用户主动起的名字。

    防御：N 上限 10000，避免文件系统死循环（理论上不会到这里）。
    """
    if not (dst_dir / original_name).exists():
        return original_name
    # 找到第一个「非前导」的 . —— 跳过 name 开头的所有 .（隐藏文件支持）
    first_dot = -1
    for i, ch in enumerate(original_name):
        if ch == ".":
            if i == 0:
                continue
            first_dot = i
            break
    if first_dot < 0 or first_dot == len(original_name) - 1:
        # 无扩展名 / 隐藏文件无扩展 / 末尾是 . → 不切 ext
        base, ext = original_name, ""
    else:
        base = original_name[:first_dot]
        ext = original_name[first_dot:]
    # 剥掉 base 末尾的 (N) 计数器后缀，让 foo(N) 副本的「再次复制」回到原始 stem 找下一个空位。
    # 例：复制 foo(1).py 时不再生成 foo(1)(1).py，而是回到 foo → foo(2).py。
    m = _TRAILING_COUNTER_RE.match(base)
    if m:
        base = m.group(1)
    for i in range(1, 10001):
        candidate = f"{base}({i}){ext}"
        if not (dst_dir / candidate).exists():
            return candidate
    raise HTTPException(
        status_code=500,
        detail=f"无法为 {original_name!r} 生成唯一名称（已尝试 10000 次）",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 复制：POST /chat/{sid}/file/copy
# ─────────────────────────────────────────────────────────────────────────────
class CopyFileRequest(BaseModel):
    """复制请求体。src 是相对路径（可指向文件或目录），dst_dir 是目标目录的相对路径。"""

    src: str = Field(..., description="源路径（相对 cached/{sid}/）")
    dst_dir: str = Field(..., description="目标目录（相对 cached/{sid}/），不含 basename")
    auto_rename: bool = Field(
        False,
        description="目标已存在时自动追加 (1)/(2)... 而不是返回 409 冲突",
    )


@router.post(
    "/{session_id}/file/copy",
    summary="复制文件 / 目录到目标目录",
)
async def copy_file(
    session_id: str = Path(..., description="会话ID"),
    body: CopyFileRequest = Body(...),
):
    """shutil.copy2 / copytree：保留元数据；目录递归复制。

    行为：
    - 复制后 dst_dir/{basename(src)}；不重命名
    - auto_rename=false（默认）+ 目标已存在 → 409 冲突（避免覆盖）
    - auto_rename=true + 目标已存在 → 自动追加 (1)/(2)... 直到名字可用
    - 复制目录到自身子目录 → 400 拒绝（递归死循环）
    - dst_dir 不存在 → 400 拒绝（不允许隐式 mkdir 到任意位置）
    """
    src = _resolve_safe(session_id, body.src)
    dst_dir = _resolve_safe(session_id, body.dst_dir)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"源不存在: {body.src}")
    if not dst_dir.exists() or not dst_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"目标目录不存在或不是目录: {body.dst_dir}")
    # 复制目录到自身子目录的循环检测
    if src.is_dir():
        try:
            dst_dir.relative_to(src)
            raise HTTPException(status_code=400, detail="不能把目录复制到自身子目录")
        except ValueError:
            pass  # relative_to 抛 ValueError 表示不在子目录，正常
    if body.auto_rename:
        dst_name = _find_unique_name(dst_dir, src.name)
    else:
        # auto_rename=false：碰到冲突直接 409，不允许默默覆盖
        dst_name = src.name
        if (dst_dir / dst_name).exists():
            raise HTTPException(
                status_code=409,
                detail=f"目标已存在: {_relativize(dst_dir / dst_name, session_id)}",
            )
    dst = dst_dir / dst_name
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))
    logger.info(
        f"[copy_file] {session_id}: {body.src} → {_relativize(dst, session_id)}"
    )
    return {
        "code": 200,
        "msg": "已复制",
        "src": body.src,
        "dst": _relativize(dst, session_id),
        "renamed": dst_name != src.name,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 移动（剪切+粘贴）：POST /chat/{sid}/file/move
# ─────────────────────────────────────────────────────────────────────────────
class MoveFileRequest(BaseModel):
    """移动请求体。"""

    src: str = Field(..., description="源路径（相对 cached/{sid}/）")
    dst_dir: str = Field(..., description="目标目录（相对 cached/{sid}/），不含 basename")
    auto_rename: bool = Field(
        False,
        description="目标已存在时自动追加 (1)/(2)... 而不是返回 409 冲突",
    )


@router.post(
    "/{session_id}/file/move",
    summary="移动文件 / 目录到目标目录（剪切 + 粘贴）",
)
async def move_file(
    session_id: str = Path(..., description="会话ID"),
    body: MoveFileRequest = Body(...),
):
    """shutil.move：跨设备 fallback 用 copy + rmtree。

    与 copy 的差异：源会被删除（move）；目标冲突策略相同（auto_rename 时自动追加）。
    """
    src = _resolve_safe(session_id, body.src)
    dst_dir = _resolve_safe(session_id, body.dst_dir)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"源不存在: {body.src}")
    if not dst_dir.exists() or not dst_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"目标目录不存在或不是目录: {body.dst_dir}")
    # 移动目录到自身子目录的循环检测
    if src.is_dir():
        try:
            dst_dir.relative_to(src)
            raise HTTPException(status_code=400, detail="不能把目录移动到自身子目录")
        except ValueError:
            pass
    # 自粘贴 / no-op move：src 和 dst 解析到同一路径
    # —— 比如「顶层文件夹拖回根 padding」或「文件拖回自己父目录」。
    # 此时 dst_dir + src.name === src.parent / src.name === src（目标 == 源），
    # shutil.move 会丢 src 再 rename，导致 auto_rename 触发「foo (1) / (2) / ...」无限累加。
    # 直接 no-op 返回（前端 _isSelfPaste 应该已拦截，这里是 defense-in-depth 兜底）。
    if src.parent == dst_dir:
        logger.info(
            f"[move_file] {session_id}: no-op move detected, src={body.src} dst_dir={body.dst_dir}"
        )
        return {
            "code": 200,
            "msg": "已在目标位置，无需移动",
            "src": body.src,
            "dst": body.src,
            "renamed": False,
            "session_id": session_id,
        }
    if body.auto_rename:
        dst_name = _find_unique_name(dst_dir, src.name)
    else:
        # auto_rename=false：碰到冲突直接 409，不允许默默覆盖
        dst_name = src.name
        if (dst_dir / dst_name).exists():
            raise HTTPException(
                status_code=409,
                detail=f"目标已存在: {_relativize(dst_dir / dst_name, session_id)}",
            )
    dst = dst_dir / dst_name
    shutil.move(str(src), str(dst))
    logger.info(
        f"[move_file] {session_id}: {body.src} → {_relativize(dst, session_id)}"
    )
    return {
        "code": 200,
        "msg": "已移动",
        "src": body.src,
        "dst": _relativize(dst, session_id),
        "renamed": dst_name != src.name,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 重命名：POST /chat/{sid}/file/rename
# ─────────────────────────────────────────────────────────────────────────────
class RenameFileRequest(BaseModel):
    """重命名请求体。src 是完整路径，new_name 仅改末段名。"""

    src: str = Field(..., description="源路径（相对 cached/{sid}/）")
    new_name: str = Field(..., description="新名字（仅末段名，不含路径分隔符）")


# ─────────────────────────────────────────────────────────────────────────────
# 批量复制：POST /chat/{sid}/files/copy
# ─────────────────────────────────────────────────────────────────────────────
class BatchFileOpRequest(BaseModel):
    """批量文件操作请求体（copy / move 复用）。srcs 是相对路径数组。"""

    srcs: list[str] = Field(
        ...,
        description="源路径数组（相对 cached/{sid}/）",
    )
    dst_dir: str = Field(
        ...,
        description="目标目录（相对 cached/{sid}/），不含 basename",
    )
    auto_rename: bool = Field(
        False,
        description="目标已存在时自动追加 (1)/(2)... 而不是返回 failures 列出",
    )


@router.post(
    "/{session_id}/files/copy",
    summary="批量复制 srcs 到目标目录",
)
async def batch_copy_files(
    session_id: str = Path(..., description="会话ID"),
    body: BatchFileOpRequest = Body(...),
):
    """批量复制 srcs 列表到 dst_dir，每个 src 各自成为 dst_dir/{basename(src)}。

    与 POST /{sid}/file/copy（单条）的区别：
    - 单条只搬一个 src；本端点一次往返搬 N 个
    - 单条冲突 → 409 整条失败；批量冲突 → failures 列出，整体不回滚

    对应前端「多选复制 + 粘贴」一次提交，避免 N 次往返。

    安全：
    - 每个 src 校验：拒绝绝对路径 / `..` 段 / 越界
    - 复制目录到自身子目录 → 跳过（不会死循环）
    - dst_dir 必须存在且是目录
    """
    if not body.srcs:
        raise HTTPException(status_code=400, detail="srcs 不能为空")
    if len(body.srcs) > 500:
        raise HTTPException(status_code=400, detail="srcs 一次最多 500 个")

    dst_dir = _resolve_safe(session_id, body.dst_dir)
    if not dst_dir.exists() or not dst_dir.is_dir():
        raise HTTPException(
            status_code=400, detail=f"目标目录不存在或不是目录: {body.dst_dir}"
        )

    removed = 0
    skipped = 0
    failures: list[dict] = []
    successes: list[dict] = []

    # 按「深 → 浅」排序：先复制深层（子目录）再复制浅层（父目录），避免父 → 子依赖错乱
    sorted_srcs = sorted(body.srcs, key=lambda p: p.count("/"), reverse=True)

    for src_rel in sorted_srcs:
        try:
            src = _resolve_safe(session_id, src_rel)
        except HTTPException as e:
            failures.append({"src": src_rel, "reason": str(e.detail)})
            skipped += 1
            continue
        if not src.exists():
            failures.append({"src": src_rel, "reason": "源不存在"})
            skipped += 1
            continue
        # 复制目录到自身子目录 → 跳过（递归死循环）
        if src.is_dir():
            try:
                dst_dir.relative_to(src)
                failures.append({"src": src_rel, "reason": "不能复制到自身子目录"})
                skipped += 1
                continue
            except ValueError:
                pass
        if body.auto_rename:
            dst_name = _find_unique_name(dst_dir, src.name)
        else:
            dst_name = src.name
            if (dst_dir / dst_name).exists():
                failures.append({
                    "src": src_rel,
                    "reason": f"目标已存在: {_relativize(dst_dir / dst_name, session_id)}"
                })
                skipped += 1
                continue
        dst = dst_dir / dst_name
        try:
            if src.is_dir():
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
            successes.append({"src": src_rel, "dst": _relativize(dst, session_id), "renamed": dst_name != src.name})
            removed += 1
        except Exception as e:
            logger.error(f"[batch_copy_files] {src_rel} 失败: {e}")
            failures.append({"src": src_rel, "reason": str(e)})
            skipped += 1

    logger.info(
        f"[batch_copy_files] {session_id}: {removed} 成功, {skipped} 跳过 → {body.dst_dir}"
    )
    return {
        "code": 200,
        "msg": f"已复制 {removed} 个文件 / 目录",
        "removed": removed,
        "skipped": skipped,
        "failures": failures,
        "successes": successes,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 批量移动：POST /chat/{sid}/files/move
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/{session_id}/files/move",
    summary="批量移动 srcs 到目标目录",
)
async def batch_move_files(
    session_id: str = Path(..., description="会话ID"),
    body: BatchFileOpRequest = Body(...),
):
    """批量移动 srcs 列表到 dst_dir，每个 src 各自成为 dst_dir/{basename(src)}。

    与 POST /{sid}/file/move（单条）的区别：
    - 单条只搬一个 src；本端点一次往返搬 N 个
    - 单条冲突 → 409 整条失败；批量冲突 → failures 列出，整体不回滚

    对应前端「多选剪切 + 粘贴」一次提交。
    """
    if not body.srcs:
        raise HTTPException(status_code=400, detail="srcs 不能为空")
    if len(body.srcs) > 500:
        raise HTTPException(status_code=400, detail="srcs 一次最多 500 个")

    dst_dir = _resolve_safe(session_id, body.dst_dir)
    if not dst_dir.exists() or not dst_dir.is_dir():
        raise HTTPException(
            status_code=400, detail=f"目标目录不存在或不是目录: {body.dst_dir}"
        )

    removed = 0
    skipped = 0
    failures: list[dict] = []
    successes: list[dict] = []

    # 按「深 → 浅」排序：先移动深层（子目录）再移动浅层（父目录）
    sorted_srcs = sorted(body.srcs, key=lambda p: p.count("/"), reverse=True)

    for src_rel in sorted_srcs:
        try:
            src = _resolve_safe(session_id, src_rel)
        except HTTPException as e:
            failures.append({"src": src_rel, "reason": str(e.detail)})
            skipped += 1
            continue
        if not src.exists():
            failures.append({"src": src_rel, "reason": "源不存在"})
            skipped += 1
            continue
        # 移动目录到自身子目录 → 跳过
        if src.is_dir():
            try:
                dst_dir.relative_to(src)
                failures.append({"src": src_rel, "reason": "不能移动到自身子目录"})
                skipped += 1
                continue
            except ValueError:
                pass
        # 自粘贴 / no-op move：src.parent == dst_dir → 目标 == 源，不做 rename
        # （防御兜底，参见 move_file 注释）
        if src.parent == dst_dir:
            successes.append({"src": src_rel, "dst": src_rel, "renamed": False})
            removed += 1
            continue
        if body.auto_rename:
            dst_name = _find_unique_name(dst_dir, src.name)
        else:
            dst_name = src.name
            if (dst_dir / dst_name).exists():
                failures.append({
                    "src": src_rel,
                    "reason": f"目标已存在: {_relativize(dst_dir / dst_name, session_id)}"
                })
                skipped += 1
                continue
        dst = dst_dir / dst_name
        try:
            shutil.move(str(src), str(dst))
            successes.append({"src": src_rel, "dst": _relativize(dst, session_id), "renamed": dst_name != src.name})
            removed += 1
        except Exception as e:
            logger.error(f"[batch_move_files] {src_rel} 失败: {e}")
            failures.append({"src": src_rel, "reason": str(e)})
            skipped += 1

    logger.info(
        f"[batch_move_files] {session_id}: {removed} 成功, {skipped} 跳过 → {body.dst_dir}"
    )
    return {
        "code": 200,
        "msg": f"已移动 {removed} 个文件 / 目录",
        "removed": removed,
        "skipped": skipped,
        "failures": failures,
        "successes": successes,
        "session_id": session_id,
    }


@router.post(
    "/{session_id}/file/rename",
    summary="重命名文件 / 目录",
)
async def rename_file(
    session_id: str = Path(..., description="会话ID"),
    body: RenameFileRequest = Body(...),
):
    """仅改末段名（保留父目录）。允许 new_name 含扩展名。

    校验：
    - new_name 不允许为空 / 含 `/`（路径分隔符，会改变父目录）
    - 目标已存在 → 409 冲突
    - 源不存在 → 404
    """
    if not body.new_name or "/" in body.new_name or "\\" in body.new_name:
        raise HTTPException(
            status_code=400,
            detail="new_name 必须为非空且不含路径分隔符",
        )
    src = _resolve_safe(session_id, body.src)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"源不存在: {body.src}")
    dst = src.parent / body.new_name
    if dst.exists():
        raise HTTPException(
            status_code=409, detail=f"目标已存在: {_relativize(dst, session_id)}"
        )
    shutil.move(str(src), str(dst))
    logger.info(
        f"[rename_file] {session_id}: {body.src} → {_relativize(dst, session_id)}"
    )
    return {
        "code": 200,
        "msg": "已重命名",
        "src": body.src,
        "dst": _relativize(dst, session_id),
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 新建目录：POST /chat/{sid}/folder
# ─────────────────────────────────────────────────────────────────────────────
class CreateFolderRequest(BaseModel):
    """新建目录请求体。parent 是父目录（相对路径），name 是目录名。"""

    parent: str = Field(..., description="父目录路径（相对 cached/{sid}/）")
    name: str = Field(..., description="新目录名（不含路径分隔符）")


@router.post(
    "/{session_id}/folder",
    summary="新建目录",
)
async def create_folder(
    session_id: str = Path(..., description="会话ID"),
    body: CreateFolderRequest = Body(...),
):
    """mkdir 单层目录（不允许递归创建 parent 不存在的路径）。

    校验：
    - parent 必须存在且是目录
    - name 不允许为空 / 含路径分隔符
    - 目标已存在 → 409 冲突
    """
    if not body.name or "/" in body.name or "\\" in body.name:
        raise HTTPException(
            status_code=400,
            detail="name 必须为非空且不含路径分隔符",
        )
    parent = _resolve_safe(session_id, body.parent)
    if body.parent == "":
        # 空 session 还没有 cached/{sid}/ —— 文件树懒加载，第一个文件/文件夹写入时才创建。
        # 先建根目录再 mkdir 子目录，否则「新建文件夹」按钮在全新 session 里会 400。
        parent.mkdir(parents=True, exist_ok=True)
    elif not parent.exists() or not parent.is_dir():
        raise HTTPException(
            status_code=400, detail=f"父目录不存在或不是目录: {body.parent}"
        )
    # 同名静默追加 (N) —— 跟 Finder/Explorer 一样，文件系统不允许同名所以只是改个名落地，
    # 对用户而言就是「创建成功了」，不需要任何「冲突 / 改名」字样。
    original_name = body.name
    unique_name = _find_unique_name(parent, original_name)
    dst = parent / unique_name
    dst.mkdir(parents=False, exist_ok=False)
    logger.info(
        f"[create_folder] {session_id}: {body.parent}/{unique_name}"
        + (" (auto-renamed)" if unique_name != original_name else "")
    )
    return {
        "code": 200,
        "msg": "目录已创建",
        "parent": body.parent,
        "name": unique_name,
        "path": _relativize(dst, session_id),
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 新建文件：POST /chat/{sid}/file
# ─────────────────────────────────────────────────────────────────────────────
class CreateFileRequest(BaseModel):
    """新建文件请求体。parent 是父目录，name 是文件名，content 是可选初始内容。"""

    parent: str = Field(..., description="父目录路径（相对 cached/{sid}/）")
    name: str = Field(..., description="新文件名（不含路径分隔符）")
    content: str = Field("", description="可选初始内容（默认空文件）")


@router.post(
    "/{session_id}/file",
    summary="新建文件（可指定初始内容）",
)
async def create_file(
    session_id: str = Path(..., description="会话ID"),
    body: CreateFileRequest = Body(...),
):
    """touch + write：默认空文件，可指定 content 初始内容。

    校验：
    - parent 必须存在且是目录
    - name 不允许为空 / 含路径分隔符
    - 目标已存在 → 409 冲突
    - content 写入走 UTF-8（os.replace 原子写，简单场景够用；非 IDE 大文件保存场景）
    """
    if not body.name or "/" in body.name or "\\" in body.name:
        raise HTTPException(
            status_code=400,
            detail="name 必须为非空且不含路径分隔符",
        )
    parent = _resolve_safe(session_id, body.parent)
    if body.parent == "":
        # 空 session 还没有 cached/{sid}/ —— 同 create_folder 的懒加载兜底
        parent.mkdir(parents=True, exist_ok=True)
    elif not parent.exists() or not parent.is_dir():
        raise HTTPException(
            status_code=400, detail=f"父目录不存在或不是目录: {body.parent}"
        )
    # 同名静默追加 (N) —— 同 create_folder：foo.py → foo(1).py → foo(2).py ...
    original_name = body.name
    unique_name = _find_unique_name(parent, original_name)
    dst = parent / unique_name
    dst.write_text(body.content, encoding="utf-8")
    logger.info(
        f"[create_file] {session_id}: {body.parent}/{unique_name} ({len(body.content)} bytes)"
        + (" (auto-renamed)" if unique_name != original_name else "")
    )
    return {
        "code": 200,
        "msg": "文件已创建",
        "parent": body.parent,
        "name": unique_name,
        "path": _relativize(dst, session_id),
        "size": dst.stat().st_size,
        "session_id": session_id,
    }