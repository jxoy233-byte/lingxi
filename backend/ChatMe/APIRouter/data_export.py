"""
DataAnalysis 会话产物导出（ZIP / HTML 预览）。

范围：cached/{session_id}/data_analysis/
- charts/  → PNG / HTML / Mermaid
- data/    → CSV / JSON / TXT
- reports/ → Markdown
- scripts/ → Python 脚本

ZIP：保留目录结构，按路径下载。
HTML：单文件预览，内嵌 marked.js + mermaid.js（CDN），PNG 转 base64，CSV/JSON 转 HTML 表格。

另含「导出到某轮对话」功能（/chat/{sid}/export/turn/{checkpoint_id}）：
- openai.json：标准 OpenAI Chat Completions 格式 messages 数组
- chatme.json：直接 dump 该 checkpoint 的 state.values（含 messages / context / tool_call_times / imp_ipt 等所有字段）
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import HTMLResponse, Response

from ChatMe.APIRouter.static_file import CACHED_DIR, list_data_analysis_files
from ChatMe.LoggingManager.logging_config import get_logger

logger = get_logger("data_export")

export_router = APIRouter(prefix="/chat", tags=["DataAnalysis 导出"])

# 范围限制：只导出 data_analysis 目录
_DATA_ANALYSIS_DIRNAME = "data_analysis"

# 导出大小上限（解压后累计），超过即拒绝，避免一次拉空会话
_MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500MB
# 单文件大小上限
_MAX_FILE_BYTES = 100 * 1024 * 1024  # 100MB


def _resolve_data_analysis_dir(session_id: str) -> Optional[Path]:
    """解析 session 的 data_analysis 目录，不存在或 sid 不合法时返回 None。"""
    if not re.match(r"^[0-9a-f]{32}$", session_id):
        return None
    base = CACHED_DIR.resolve()
    d = (base / session_id / _DATA_ANALYSIS_DIRNAME).resolve()
    # 用 Path.parts 判断防止 macOS /tmp ↔ /private/tmp 之类的 symlink resolve 后字符串前缀不一致
    try:
        d.relative_to(base)
    except ValueError:
        return None
    return d


def _collect_files(root: Path) -> list[dict]:
    """
    收集 root 下所有文件（含 gen_xxx 子目录），跳过隐藏文件、_meta.json。
    返回 list[{ abs_path, rel_path, size, mtime, category }]，category ∈ {charts,data,reports,scripts}。
    category 提取规则：gen_xxx 子目录下的第一段作为分类（charts/data/reports/scripts）；
    不在 gen_xxx 下时直接取第一段；不在已知分类时归入 other。
    """
    files: list[dict] = []
    known_categories = {"charts", "data", "reports", "scripts"}
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        if f.name.startswith(".") or f.name == "_meta.json":
            continue
        try:
            rel = f.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        # 跳过根级 _meta.json（已经被上面过滤）
        # 结构通常是 gen_xxx/charts/xxx.png；前两段才算 gen + category
        category = "other"
        if len(parts) >= 2:
            # 第一段是 gen_xxx → category 取第二段
            if re.match(r"^gen_\d+$", parts[0]):
                category = parts[1] if parts[1] in known_categories else "other"
            else:
                # 直接根级子目录如 charts/xxx.png
                category = parts[0] if parts[0] in known_categories else "other"
        try:
            stat = f.stat()
        except OSError:
            continue
        files.append({
            "abs_path": f,
            "rel_path": rel.as_posix(),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "category": category,
        })
    return files


def _check_size_limits(files: list[dict]) -> None:
    """校验总大小 + 单文件大小，超限抛 413。"""
    total = sum(f["size"] for f in files)
    if total > _MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"导出内容过大（{total / 1024 / 1024:.1f}MB > {_MAX_TOTAL_BYTES / 1024 / 1024:.0f}MB）",
        )
    for f in files:
        if f["size"] > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"单文件过大：{f['rel_path']} ({f['size'] / 1024 / 1024:.1f}MB)",
            )


# ─────────────────────────── ZIP 实现 ───────────────────────────


@export_router.get(
    "/{session_id}/export/artifacts",
    summary="导出会话 DataAnalysis 产物（ZIP 或 HTML）",
    responses={
        200: {
            "description": "ZIP 文件（application/zip）或 HTML 预览（text/html）",
            "content": {
                "application/zip": {},
                "text/html": {},
            },
        }
    },
)
async def export_data_analysis_artifacts(
    session_id: str = Path(..., description="会话ID"),
    format: str = Query("zip", pattern="^(zip|html)$", description="导出格式：zip 或 html"),
):
    """
    导出会话 cached/{session_id}/data_analysis/ 下的所有产物。

    - format=zip：返回 ZIP 文件，保留 gen_xxx/charts|reports|data|scripts/ 目录结构
    - format=html：返回单文件 HTML 预览（marked + mermaid CDN，PNG base64 嵌入）

    ZIP 内部结构示例：
        data_analysis/
        ├── gen_001/
        │   ├── charts/06.png
        │   ├── reports/report.md
        │   ├── data/summary.csv
        │   └── scripts/analysis.py
    """
    root = _resolve_data_analysis_dir(session_id)
    if root is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 无 data_analysis 目录")

    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 无 data_analysis 目录")

    files = _collect_files(root)
    if not files:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 的 data_analysis 目录为空")

    _check_size_limits(files)

    if format == "zip":
        return _build_zip_response(files, session_id)
    return _build_html_response(files, root, session_id)


# ─────────────────────────── 对话轮次导出 ───────────────────────────


@export_router.get(
    "/{session_id}/export/turn/{checkpoint_id}",
    summary="导出会话中截至指定 checkpoint 的完整对话历史",
    responses={
        200: {
            "description": "ZIP 文件，含 openai.json（标准 Chat Completions 格式）+ chatme.json（完整 state 快照）",
            "content": {"application/zip": {}},
        }
    },
)
async def export_conversation_turn(
    session_id: str = Path(..., description="会话ID"),
    checkpoint_id: str = Path(..., description="目标 AI 消息的 checkpoint_id"),
):
    """
    导出截至指定 checkpoint 的完整对话历史。

    - openai.json：标准 OpenAI Chat Completions 格式 `[{role, content, tool_calls?, tool_call_id?, name?}, ...]`
    - chatme.json：直接 dump 该 checkpoint 的 state.values（含 messages / context / imp_ipt /
      tool_call_times / memory_* / pending_compaction_* 等所有字段），用于软件内恢复对话

    返回 ZIP 流，前端用 blob 下载。
    """
    # late import 避免循环依赖（main.py 里也用 chat_service）
    from ChatMe.APIRouter.main import chat_service

    if chat_service is None:
        raise HTTPException(status_code=503, detail="后端服务尚未就绪")

    state = await chat_service.graph.aget_state(
        config={"configurable": {"thread_id": session_id, "checkpoint_id": checkpoint_id}}
    )

    if state is None or not state.values:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 checkpoint {checkpoint_id[:16]}... (session={session_id[:8]})",
        )

    messages = state.values.get("messages", [])
    if not messages:
        raise HTTPException(status_code=404, detail="该 checkpoint 没有消息内容")

    openai_messages = _convert_to_openai_format(messages)
    chatme_snapshot = {
        "session_id": session_id,
        "checkpoint_id": checkpoint_id,
        "exported_at": datetime.now().isoformat(),
        "values": _serialize_state_values(state.values),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(
            "openai.json",
            json.dumps(openai_messages, ensure_ascii=False, indent=2),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zf.writestr(
            "chatme.json",
            json.dumps(chatme_snapshot, ensure_ascii=False, indent=2, default=str),
            compress_type=zipfile.ZIP_DEFLATED,
        )

    buf.seek(0)
    short_sid = session_id[:8]
    short_cid = checkpoint_id.replace("-", "")[:8]
    filename = f"chatme_export_{short_sid}_{short_cid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    logger.info(
        f"导出对话轮次: session={short_sid} cid={short_cid} "
        f"messages={len(messages)} openai={len(openai_messages)} bytes={len(buf.getvalue())}"
    )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


# ─────────────────────────── 对话序列化工具 ───────────────────────────


def _convert_to_openai_format(messages: list) -> list[dict]:
    """
    把 LangChain BaseMessage 列表转为 OpenAI Chat Completions 格式。

    规则：
    - SystemMessage → {"role": "system", "content": str(content)}
    - HumanMessage  → {"role": "user", "content": str(content)}
    - AIMessage     → {"role": "assistant", "content": str(content), "tool_calls": [...]}
    - ToolMessage   → {"role": "tool", "content": str(content), "tool_call_id": tool_call_id}
    """
    out: list[dict] = []
    for msg in messages:
        cls_name = type(msg).__name__
        content = _msg_content_to_str(msg.content)

        if cls_name == "SystemMessage":
            out.append({"role": "system", "content": content})
        elif cls_name == "HumanMessage":
            out.append({"role": "user", "content": content})
        elif cls_name == "AIMessage":
            item: dict = {"role": "assistant", "content": content}
            # tool_calls 是 AIMessage 的属性：[{id, name, args}]
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False)
                            if not isinstance(tc.get("args"), str)
                            else tc.get("args"),
                        },
                    }
                    for tc in tool_calls
                ]
            out.append(item)
        elif cls_name == "ToolMessage":
            item = {
                "role": "tool",
                "content": content,
                "tool_call_id": getattr(msg, "tool_call_id", "") or "",
            }
            out.append(item)
        else:
            # 未知类型：归到 user 里至少保留信息
            out.append({"role": "user", "content": f"[{cls_name}] {content}"})
    return out


def _msg_content_to_str(content) -> str:
    """BaseMessage.content 可能是 str 或 list[dict]（多模态），统一转 str。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                else:
                    parts.append(json.dumps(part, ensure_ascii=False, default=str))
            else:
                parts.append(str(part))
        return "\n".join(parts)
    return str(content)


def _serialize_state_values(values: dict) -> dict:
    """
    把 LangGraph state.values 序列化成 JSON-friendly 结构。

    - messages: 每条 BaseMessage 转 dict（保留 type / content / tool_calls / additional_kwargs /
      tool_call_id 等所有字段），不依赖 LangChain 序列化器以避免 version 差异。
    - context: 同 messages
    - 其它字段保持原值（datetime / int / str 等直接 json.dumps，default=str 兜底）
    """
    out: dict = {}
    for k, v in values.items():
        if k in ("messages", "context") and isinstance(v, list):
            out[k] = [_serialize_message(m) for m in v]
        else:
            out[k] = v
    return out


def _serialize_message(msg) -> dict:
    """BaseMessage → JSON dict。"""
    cls_name = type(msg).__name__
    out: dict = {"__type__": cls_name}

    # content
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        out["content"] = content
    elif isinstance(content, list):
        out["content"] = content  # list[dict] 多模态
    else:
        out["content"] = str(content)

    # additional_kwargs（含 checkpoint_id / elapsed_ms / token_usage / imp_ipt / is_file / files 等）
    additional = getattr(msg, "additional_kwargs", None) or {}
    if additional:
        out["additional_kwargs"] = additional

    # response_metadata
    rm = getattr(msg, "response_metadata", None) or {}
    if rm:
        out["response_metadata"] = rm

    # AIMessage 专属
    if cls_name == "AIMessage":
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            out["tool_calls"] = tool_calls
        invalid = getattr(msg, "invalid_tool_calls", None) or []
        if invalid:
            out["invalid_tool_calls"] = invalid
        usage = getattr(msg, "usage_metadata", None)
        if usage:
            out["usage_metadata"] = usage

    # ToolMessage 专属
    if cls_name == "ToolMessage":
        tcid = getattr(msg, "tool_call_id", None)
        if tcid:
            out["tool_call_id"] = tcid
        name = getattr(msg, "name", None)
        if name:
            out["name"] = name

    # HumanMessage 专属：name（多 human 时区分）
    if cls_name == "HumanMessage":
        name = getattr(msg, "name", None)
        if name:
            out["name"] = name

    return out


def _build_zip_response(files: list[dict], session_id: str) -> Response:
    """打包 ZIP 流式返回。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            arcname = f"{_DATA_ANALYSIS_DIRNAME}/{f['rel_path']}"
            with f["abs_path"].open("rb") as src:
                zf.writestr(arcname, src.read(), compress_type=zipfile.ZIP_DEFLATED)

    buf.seek(0)
    filename = f"data_analysis_{session_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    logger.info(f"导出 ZIP: session={session_id} files={len(files)} size={len(buf.getvalue())}")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


# ─────────────────────────── HTML 实现 ───────────────────────────


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DataAnalysis 预览 · {sid_short}</title>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>
  :root {{
    --bg: #ffffff;
    --bg-secondary: #f9fafb;
    --border: #e5e7eb;
    --text: #111827;
    --text-secondary: #6b7280;
    --primary: #3b82f6;
    --code-bg: #f3f4f6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f172a;
      --bg-secondary: #1e293b;
      --border: #334155;
      --text: #f1f5f9;
      --text-secondary: #94a3b8;
      --primary: #60a5fa;
      --code-bg: #1e293b;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.6;
  }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
  header {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 24px;
  }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  .meta {{ color: var(--text-secondary); font-size: 13px; }}
  .summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin: 16px 0 32px;
  }}
  .summary-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 14px;
  }}
  .summary-card .label {{ font-size: 12px; color: var(--text-secondary); }}
  .summary-card .value {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
  nav.toc {{
    position: sticky;
    top: 0;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    padding: 12px 0;
    margin-bottom: 24px;
    z-index: 10;
  }}
  nav.toc h3 {{ font-size: 13px; margin: 0 0 8px; color: var(--text-secondary); }}
  nav.toc a {{
    display: inline-block;
    margin-right: 12px;
    color: var(--primary);
    text-decoration: none;
    font-size: 13px;
  }}
  nav.toc a:hover {{ text-decoration: underline; }}
  section {{ margin-bottom: 48px; }}
  section h2 {{
    font-size: 18px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
    margin: 0 0 16px;
  }}
  section h3 {{ font-size: 14px; margin: 24px 0 8px; color: var(--text-secondary); }}
  .file-block {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
  }}
  .file-block .file-name {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    color: var(--text-secondary);
    margin-bottom: 8px;
    word-break: break-all;
  }}
  .file-block .file-content {{ margin-top: 8px; }}
  img.chart {{
    max-width: 100%;
    height: auto;
    border: 1px solid var(--border);
    border-radius: 4px;
    display: block;
    margin: 8px 0;
  }}
  pre {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px;
    overflow-x: auto;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.5;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
    margin: 8px 0;
    overflow-x: auto;
    display: block;
  }}
  table th, table td {{
    border: 1px solid var(--border);
    padding: 6px 10px;
    text-align: left;
    white-space: nowrap;
  }}
  table th {{ background: var(--bg-secondary); font-weight: 600; }}
  table tbody tr:nth-child(even) {{ background: var(--bg-secondary); }}
  .mermaid {{ background: var(--bg-secondary); padding: 12px; border-radius: 4px; margin: 8px 0; overflow-x: auto; }}
  .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
    margin-top: 16px;
    margin-bottom: 8px;
  }}
  .markdown-body p {{ margin: 8px 0; }}
  .markdown-body code {{
    background: var(--code-bg);
    padding: 1px 5px;
    border-radius: 3px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
  }}
  .markdown-body pre code {{ padding: 0; background: transparent; }}
  .empty {{ color: var(--text-secondary); font-style: italic; padding: 8px 0; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>📊 DataAnalysis 预览</h1>
    <div class="meta">
      会话 <code>{sid_short}</code> · 共 {file_count} 个文件 · 导出时间 {export_time}
    </div>
  </header>

  <div class="summary">
    <div class="summary-card"><div class="label">图表</div><div class="value">{count_charts}</div></div>
    <div class="summary-card"><div class="label">数据</div><div class="value">{count_data}</div></div>
    <div class="summary-card"><div class="label">报告</div><div class="value">{count_reports}</div></div>
    <div class="summary-card"><div class="label">脚本</div><div class="value">{count_scripts}</div></div>
  </div>

  <nav class="toc">
    <h3>目录</h3>
    {toc_links}
  </nav>

  <main>
    {sections_html}
  </main>
</div>

<script>
  marked.setOptions({{ breaks: true, gfm: true }});
  mermaid.initialize({{ startOnLoad: true, theme: window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default', securityLevel: 'loose' }});
  // marked 渲染
  document.querySelectorAll('.markdown-body').forEach(el => {{
    el.innerHTML = marked.parse(el.textContent || el.dataset.raw || '');
  }});
</script>
</body>
</html>
"""


def _build_html_response(files: list[dict], root: Path, session_id: str) -> Response:
    """构建单文件 HTML 预览。"""
    by_category: dict[str, list[dict]] = {"charts": [], "data": [], "reports": [], "scripts": [], "other": []}
    for f in files:
        by_category.setdefault(f["category"], []).append(f)

    # TOC 锚点
    toc_links_parts: list[str] = []
    cat_labels = {"charts": "📈 图表", "data": "📋 数据", "reports": "📝 报告", "scripts": "🐍 脚本", "other": "📦 其它"}
    for cat in ("charts", "data", "reports", "scripts", "other"):
        if by_category[cat]:
            anchor = f"section-{cat}"
            toc_links_parts.append(f'<a href="#{anchor}">{cat_labels[cat]} ({len(by_category[cat])})</a>')

    # 各 section
    sections_parts: list[str] = []
    for cat in ("charts", "data", "reports", "scripts", "other"):
        items = by_category[cat]
        if not items:
            continue
        sections_parts.append(f'<section id="section-{cat}"><h2>{cat_labels[cat]}</h2>')
        for f in items:
            sections_parts.append(_render_file_block(f))
        sections_parts.append("</section>")

    counts = {f"count_{k}": len(v) for k, v in by_category.items() if k in ("charts", "data", "reports", "scripts")}

    html_doc = _HTML_TEMPLATE.format(
        sid_short=session_id[:8],
        export_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        file_count=len(files),
        toc_links="\n    ".join(toc_links_parts) if toc_links_parts else '<span class="empty">无文件</span>',
        sections_html="\n".join(sections_parts) if sections_parts else '<p class="empty">暂无产物</p>',
        count_charts=counts.get("count_charts", 0),
        count_data=counts.get("count_data", 0),
        count_reports=counts.get("count_reports", 0),
        count_scripts=counts.get("count_scripts", 0),
    )

    logger.info(f"导出 HTML 预览: session={session_id} files={len(files)}")
    return HTMLResponse(
        content=html_doc,
        headers={"Cache-Control": "no-cache"},
    )


def _render_file_block(f: dict) -> str:
    """渲染单个文件的 HTML 块。"""
    name = f["rel_path"]
    abs_path: Path = f["abs_path"]
    size = f["size"]
    size_str = _format_size(size)
    suffix = abs_path.suffix.lower()

    header = (
        f'<div class="file-block">'
        f'<div class="file-name">📄 {html.escape(name)} <span style="opacity:0.6">({size_str})</span></div>'
        f'<div class="file-content">'
    )

    try:
        if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            return header + _render_image(abs_path) + "</div></div>"
        if suffix == ".svg":
            return header + _render_svg(abs_path) + "</div></div>"
        if suffix == ".html" or suffix == ".htm":
            return header + _render_html_iframe() + "</div></div>"
        if suffix == ".mmd":
            return header + _render_mermaid(abs_path) + "</div></div>"
        if suffix in (".md", ".markdown"):
            return header + _render_markdown(abs_path) + "</div></div>"
        if suffix == ".csv":
            return header + _render_csv(abs_path) + "</div></div>"
        if suffix == ".json":
            return header + _render_json(abs_path) + "</div></div>"
        if suffix in (".py", ".js", ".ts", ".txt"):
            return header + _render_code(abs_path, lang=suffix.lstrip(".")) + "</div></div>"
        # 兜底：纯文本预览
        return header + _render_code(abs_path, lang="text") + "</div></div>"
    except Exception as e:
        return header + f'<p class="empty">⚠️ 渲染失败：{html.escape(str(e))}</p></div></div>'


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.2f} MB"


def _render_image(path: Path) -> str:
    """图片转 base64 内嵌，避免依赖外部资源访问。"""
    data = path.read_bytes()
    import base64
    b64 = base64.b64encode(data).decode("ascii")
    suffix = path.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp"}.get(suffix, "image/png")
    return f'<img class="chart" alt="{html.escape(path.name)}" src="data:{mime};base64,{b64}">'


def _render_svg(path: Path) -> str:
    """SVG 内嵌（保留矢量缩放）。"""
    content = path.read_text(encoding="utf-8", errors="replace")
    # 去掉 XML 声明，避免 HTML 嵌套问题
    content = re.sub(r"<\?xml[^?]*\?>", "", content).strip()
    return f'<div class="chart">{content}</div>'


def _render_html_iframe() -> str:
    return (
        '<p class="empty">⚠️ HTML 文件未内嵌（避免沙箱逃逸）。请下载 ZIP 后用浏览器打开。</p>'
    )


def _render_mermaid(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", path.stem)[:50] or "mermaid"
    return (
        f'<pre class="mermaid" id="{safe_id}">\n{html.escape(content)}\n</pre>'
        f'<script>mermaid.run();</script>'
    )


def _render_markdown(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    # 双大括号在 .format() 模板里会被吃掉，转义后用 marked 客户端渲染
    escaped = html.escape(content)
    return f'<div class="markdown-body" data-raw="{escaped}">{escaped}</div>'


def _render_csv(path: Path, max_rows: int = 200) -> str:
    """CSV 转 HTML 表格（限制行数防巨型表爆炸）。"""
    rows: list[list[str]] = []
    headers: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                else:
                    rows.append(row)
                if i >= max_rows:
                    break
    except Exception as e:
        return f'<p class="empty">⚠️ CSV 解析失败：{html.escape(str(e))}</p>'

    truncated = len(rows) >= max_rows
    thead = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    tbody_rows = []
    for row in rows[:max_rows]:
        tbody_rows.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>")
    tbody = "\n".join(tbody_rows)
    note = f'<p class="empty">（仅显示前 {max_rows} 行，完整数据请下载 CSV）</p>' if truncated else ""
    return f'<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>{note}'


def _render_json(path: Path, max_chars: int = 100_000) -> str:
    """JSON 优先以表格展示（数组对象），否则代码块。"""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f'<p class="empty">⚠️ 读取失败：{html.escape(str(e))}</p>'

    if len(content) > max_chars:
        return f'<pre>{html.escape(content[:max_chars])}</pre><p class="empty">（文件过大，已截断到 {max_chars} 字符）</p>'

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # 非合法 JSON，原样展示
        return f'<pre>{html.escape(content)}</pre>'

    # 数组形式 [{...}, {...}] → 表格
    if isinstance(data, list) and data and isinstance(data[0], dict):
        headers = list(data[0].keys())
        thead = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
        tbody_rows = []
        for item in data[:200]:
            tbody_rows.append("<tr>" + "".join(
                f"<td>{html.escape(str(item.get(h, '')))}</td>" for h in headers
            ) + "</tr>")
        tbody = "\n".join(tbody_rows)
        note = '<p class="empty">（仅显示前 200 行）</p>' if len(data) > 200 else ""
        return f'<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>{note}'

    # 对象 → key-value 表
    if isinstance(data, dict):
        rows = "".join(
            f"<tr><td><code>{html.escape(str(k))}</code></td><td>{html.escape(json.dumps(v, ensure_ascii=False, default=str))}</td></tr>"
            for k, v in data.items()
        )
        return f'<table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>'

    # 标量 / 嵌套结构 → 代码块
    return f'<pre>{html.escape(json.dumps(data, ensure_ascii=False, indent=2, default=str))}</pre>'


def _render_code(path: Path, lang: str = "text", max_chars: int = 200_000) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f'<p class="empty">⚠️ 读取失败：{html.escape(str(e))}</p>'
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n...（文件过大，已截断到 {max_chars} 字符）"
    return f'<pre><code class="language-{html.escape(lang)}">{html.escape(content)}</code></pre>'
