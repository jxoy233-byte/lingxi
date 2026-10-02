"""
Word 文档整篇编辑 API（抽屉「保存」入口）

端点：
  - POST /api/word_editor/replace
    body={session_id, file_path, paragraphs: List[str]}
    清空 docx body（保留 sectPr 页边距），按 paragraphs 顺序重建段落。

图片位置（v0.3.8 修）：
  前端「原文」视图是纯文本，早前直接跳过 <img>，位置信息在**提取阶段**就丢了；
  后端只能把含 drawing 的段落原地留下、把文字段落全删后追加到末尾 ——
  于是幸存者全部浮到文档最前（实测 8 张图全被顶到 body[0:8]，标题被挤到 index 8）。
  现在前端在原文视图里用 `[[图片 N]]` 占住每个图片的位置（N = 文档顺序，1 起），
  后端按 N 把原 drawing 段落搬回原处。

  占位符数量与文档里的图片数量对不上时**直接拒绝保存**（422），
  绝不能静默丢图——那是不可逆的数据损失。

设计取舍：
  - 仅支持「整篇重写」——表格 / 段落级格式在保存时仍然丢失。
"""
import re
from typing import List

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ChatMe.APIRouter.static_file import SESSION_ID_PATTERN
from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.paths import CACHED_DIR

logger = get_logger("WordEditorAPI")

router = APIRouter(prefix="/api/word_editor", tags=["word_editor"])

# 原文视图里的图片占位符：[[图片 1]] / [[图片 12]]（N 为文档顺序，1 起）
_IMG_PLACEHOLDER = re.compile(r"^\[\[图片\s*(\d+)\]\]$")


class WordReplaceRequest(BaseModel):
    """POST /api/word_editor/replace payload"""

    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(..., min_length=12, max_length=32, pattern=r"^[0-9a-f]+$")
    file_path: str = Field(..., min_length=1, max_length=512, description="相对 cached/{session_id}/ 的路径")
    paragraphs: List[str] = Field(..., max_length=2000, description="按顺序重建的段落文本")


def _resolve_safe(session_id: str, rel_path: str):
    """精确路径解析（不走 static_file._get_safe_path 的 fallback 逻辑）。"""
    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail=f"非法 sid: {session_id!r}")
    if rel_path.startswith("/") or ".." in Path(rel_path).parts:
        raise HTTPException(status_code=400, detail="路径必须为相对路径且不含 ..")
    target = (CACHED_DIR / session_id / rel_path).resolve()
    session_root = (CACHED_DIR / session_id).resolve()
    try:
        target.relative_to(session_root)
    except ValueError:
        raise HTTPException(status_code=403, detail=f"路径越界: {rel_path!r}")
    return target


@router.post("/replace", response_model=dict, summary="整篇重写 docx 段落")
async def replace_word(body: WordReplaceRequest = Body(...)):
    """清空 docx body 段落（保留 sectPr），按 paragraphs 顺序重建。

    `[[图片 N]]` 占位符处把原文档第 N 个 drawing 段落搬回原位。
    """
    from skills.WordEditor import OfficeDocError, WordDoc, _insert_before_sectpr

    target = _resolve_safe(body.session_id, body.file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {body.file_path}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"不是文件: {body.file_path}")
    try:
        doc = WordDoc.open(str(target))
        W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        sectPr = doc._body.find(f"{W}sectPr")

        # 先按文档顺序收集图片锚点。drawing 嵌在 w:p > w:r > w:drawing 两层里，
        # find 只查直接子会漏，必须 iter 全树后裔。
        img_children = [
            c for c in list(doc._body)
            if c is not sectPr and any(True for _ in c.iter(f"{W}drawing"))
        ]

        # 清空 body（保留 sectPr 即页面设置）。图片锚点也一并摘出来，
        # 稍后按占位符位置重新插回去 —— 原地保留会让它们全部浮到文档最前。
        for child in list(doc._body):
            if child is not sectPr:
                doc._body.remove(child)

        if img_children:
            seen = [
                int(m.group(1))
                for m in (_IMG_PLACEHOLDER.match(t.strip()) for t in body.paragraphs)
                if m
            ]
            # 对不上就拒绝保存：宁可报错也不能静默丢图（丢图不可逆）
            if sorted(seen) != list(range(1, len(img_children) + 1)):
                raise OfficeDocError(
                    f"文档含 {len(img_children)} 张图片，但原文视图只定位到 {len(seen)} 个"
                    f"「[[图片 N]]」占位符（期望 1..{len(img_children)}）。"
                    f"占位符被删改过，为避免丢图已中止保存——请刷新文档后重试。"
                )

        # 重建：文字走 add_paragraph，占位符走「把原图片段落搬回原处」
        for text in body.paragraphs:
            m = _IMG_PLACEHOLDER.match(text.strip())
            if m:
                _insert_before_sectpr(doc._body, img_children[int(m.group(1)) - 1])
            else:
                doc.add_paragraph(text)
        doc.save(str(target))
        logger.info(
            f"word_editor.replace: sid={body.session_id} file={body.file_path} "
            f"n={len(body.paragraphs)} images={len(img_children)}"
        )
        return {
            "ok": True,
            "paragraphs": len(body.paragraphs),
            "images_preserved": len(img_children),
        }
    except OfficeDocError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"word_editor.replace 异常: {e}")
        raise HTTPException(status_code=500, detail=f"写入失败: {type(e).__name__}")


# 兼容 — Path 顶层 import 缺失会 NameError；放最后不影响行为，但加 noqa
from pathlib import Path  # noqa: E402