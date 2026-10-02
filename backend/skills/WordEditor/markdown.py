"""Markdown 解析 —— inline runs + block 拆分。

设计取舍：
- 零依赖（自写 regex，不引 mistune/markdown-it-py）
- 输出格式与 `WordDoc.add_paragraph(runs=...)` 直接对接（list[dict]）
- 解析失败按字面量处理（未匹配的 `*` `[` 不抛异常）
- close-tag 优先（精确范围），open-only 兜底（自动延伸到段末）

支持语法：
  inline：
    **bold**  *italic*  __underline__  ~~strike~~
    [color=red]文字[/color] / [color=red]文字 (open-only, 延伸到段末)
    [highlight=yellow]文字[/highlight]
    [size=小四]文字[/size] / [font=微软雅黑]文字[/font]
  block：
    `# / ## / ### / #### / ##### / ######` 标题
    空行分隔段落
    `> 引用` → style="Quote"
    `| a | b |` + `|---|---|` → 表格（表头 + 对齐 + 单元格行内样式）
    `- / * / + / 1.` 列表（含 `- [ ] / - [x]` 任务项）
    ``` 围栏代码块 → 等宽段落

API：
    runs = parse_inline("**重要**[color=red]通知[/color]")
    blocks = parse_blocks("# 标题\\n正文")
"""
import re
from typing import List, Dict


# ============================================================================
# inline 解析
# ============================================================================

# markdown 强调 + tag 匹配的 key 集合（用于识别 [key=val] 形态）
_TAG_KEYS = {"color", "highlight", "size", "font", "bold", "italic", "underline"}

# 简单 named-color → hex（与 to_rgb 兼容；解析失败时由 _make_run 走 to_rgb 抛错）
_NAMED_COLORS = {
    "black": "000000", "white": "FFFFFF", "red": "FF0000",
    "green": "008000", "blue": "0000FF", "yellow": "FFFF00",
    "gray": "808080", "grey": "808080", "orange": "FFA500",
    "purple": "800080", "pink": "FFC0CB", "cyan": "00FFFF",
    "magenta": "FF00FF",
}


def _normalize_color(val: str) -> str:
    """'red' / '#FF0000' / 'FF0000' / 'rgb(255,0,0)' → 6 位 hex（无 # 前缀）。

    注意：仅做轻量规范化，让 _make_run 走 to_rgb 兜底。
    真实 16 色 OOXML highlight 名（yellow / darkBlue 等）直接保留。
    """
    v = val.strip()
    if v.startswith("#"):
        v = v[1:]
    if v.lower() in _NAMED_COLORS:
        return _NAMED_COLORS[v.lower()]
    if v.startswith("rgb(") and v.endswith(")"):
        nums = [int(n.strip()) for n in v[4:-1].split(",") if n.strip()]
        if len(nums) == 3:
            return f"{nums[0]:02X}{nums[1]:02X}{nums[2]:02X}"
    return v  # 原样回退（hex / highlight 名）


def _tag_to_spec(key: str, val: str) -> Dict[str, object]:
    """[key=val] → 单 run dict（不含 text）。"""
    key = key.lower().strip()
    val = val.strip()
    if key == "color":
        return {"color": _normalize_color(val)}
    if key == "highlight":
        return {"highlight": val.lower()}
    if key == "size":
        return {"font_size": val}
    if key == "font":
        return {"font": val}
    if key == "bold":
        return {"bold": val.lower() in ("true", "1", "yes", "on")}
    if key == "italic":
        return {"italic": val.lower() in ("true", "1", "yes", "on")}
    if key == "underline":
        return {"underline": val.lower() in ("true", "1", "yes", "on")}
    return {}


# 关闭 tag 模式：`[key=val]content[/key]`
# 注意：用非贪婪 (.*?) + DOTALL，跨段内多行 OK
_CLOSE_TAG_RE = re.compile(
    r"\[(\w+)\s*=\s*([^\]]+)\](.*?)\[/\1\]", re.DOTALL
)

# open-only 模式：`[key=val]content` 一直吃到下一个 [key=val] / [/key] / 段末
# 注意：open-only 的识别要看 `[/key]` 紧跟另一个 `[key=...]` 才算 close
_OPEN_ONLY_TAG_RE = re.compile(
    r"\[(\w+)\s*=\s*([^\]]+)\]"
)

# markdown 强调：`**bold** / *italic* / __underline__ / ~~strike~~`
# 注意：`**` 必须先匹配，避免 `*` 先吃掉一半
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_UNDERLINE_RE = re.compile(r"__(.+?)__")
_STRIKE_RE = re.compile(r"~~(.+?)~~")


def _apply_inline(text: str) -> List[Dict]:
    """把一段字符串切成 list[{text, ...format_kwargs}, ...]。

    算法：
    1. 先扫所有 [key=val]...[/key] close-tag，替换成占位 token，避免后续 regex 把内容里
       的 [color=red] 当字面量再匹配一次
    2. 再扫所有 [key=val] open-only，剩余未关闭的 close 视作延伸到段末
    3. 再扫 ** / * / __ / ~~ markdown 强调
    4. 把 token 还原为 run dict，合并相邻同 run 属性的 text
    5. 全部失败：返回 [{text: 原文}]
    """
    if not text:
        return [{"text": ""}]

    # 第 1 步：close-tag → token 替换
    tokens = []  # [(text, run_kwargs)]
    token_idx = [0]

    def _close_repl(m: re.Match) -> str:
        idx = token_idx[0]
        token_idx[0] += 1
        key, val, content = m.group(1), m.group(2), m.group(3)
        spec = _tag_to_spec(key, val)
        tokens.append((content, spec))
        return f"\x00TOKEN{idx}\x00"

    s = _CLOSE_TAG_RE.sub(_close_repl, text)

    # 第 2 步：open-only → 截到下一个 [key=val] / [/key] / 段末
    def _open_only_repl(m: re.Match) -> str:
        idx = token_idx[0]
        token_idx[0] += 1
        key, val = m.group(1), m.group(2)
        spec = _tag_to_spec(key, val)
        # 找 open-only 的范围：下一个 [key=val] / [/key]（同 key）/ 段末
        start = m.end()
        # 找 [/same_key] 或 [other_key=...]
        close_re = re.compile(rf"\[/*{key}\]|\[(\w+)\s*=")
        cm = close_re.search(s, start)
        end = cm.start() if cm else len(s)
        content = s[start:end]
        tokens.append((content, spec))
        return f"\x00TOKEN{idx}\x00"

    s = _OPEN_ONLY_TAG_RE.sub(_open_only_repl, s)

    # 第 3 步：markdown 强调 → token 替换
    def _make_md_token(pat: re.Pattern, spec_key: str, spec_val) -> callable:
        def _repl(m: re.Match) -> str:
            idx = token_idx[0]
            token_idx[0] += 1
            tokens.append((m.group(1), {spec_key: spec_val}))
            return f"\x00TOKEN{idx}\x00"
        return _repl

    s = _BOLD_RE.sub(_make_md_token(_BOLD_RE, "bold", True), s)
    s = _UNDERLINE_RE.sub(_make_md_token(_UNDERLINE_RE, "underline", "single"), s)
    s = _STRIKE_RE.sub(_make_md_token(_STRIKE_RE, "highlight", "lightGray"), s)
    s = _ITALIC_RE.sub(_make_md_token(_ITALIC_RE, "italic", True), s)

    # 第 4 步：还原 token
    runs: List[Dict] = []
    i = 0
    while i < len(s):
        if s[i] == "\x00":
            # token
            m = re.match(r"\x00TOKEN(\d+)\x00", s[i:])
            if m:
                idx = int(m.group(1))
                token_text, token_spec = tokens[idx]
                # token 内可能还含 nested markdown 强调 → 递归
                nested = _apply_inline(token_text)
                if len(nested) == 1:
                    # 简单情况：合并到外层
                    spec = dict(token_spec)
                    spec["text"] = nested[0]["text"]
                    runs.append(spec)
                else:
                    # 复杂情况：嵌套 run 各自带外层 spec
                    for sub in nested:
                        spec = dict(token_spec)
                        spec.update(sub)
                        runs.append(spec)
                i += m.end()
                continue
        # 字面量
        lit_start = i
        while i < len(s) and s[i] != "\x00":
            i += 1
        lit = s[lit_start:i]
        if lit:
            # 合并到前一个无格式 run
            if runs and set(runs[-1].keys()) == {"text"}:
                runs[-1]["text"] += lit
            else:
                runs.append({"text": lit})

    # 合并相邻同 spec 的 run（连续字面量已合并；tag 内容相邻但 spec 不同不合并）
    return runs if runs else [{"text": text}]


def parse_inline(text: str) -> List[Dict]:
    """把 markdown 行内语法切成 list[dict]（key 与 _make_run kwargs 对齐）。

    输出例：
        parse_inline("**重要**[color=red]通知[/color]")
        → [{"text": "重要", "bold": True}, {"text": "通知", "color": "FF0000"}]
    """
    return _apply_inline(text or "")


# ============================================================================
# block 解析
# ============================================================================

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_HR_RE = re.compile(r"^-{3,}\s*$|^\*{3,}\s*$")

# —— 表格 / 列表 / 围栏代码块 ——
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TASK_RE = re.compile(r"^\[([ xX])\]\s*(.*)$")
_FENCE_RE = re.compile(r"^(?:`{3,}|~{3,})\s*(\S*)\s*$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-+:?$")


def _split_table_row(line: str) -> List[str]:
    """一行表格 → 单元格列表（去掉首尾竖线、转义竖线还原）。

    `| a | b |` / `a | b` / `a \\| b` 三种写法都吃。
    """
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [c.replace("\\|", "|").strip() for c in cells]


def _is_table_sep_row(line: str) -> bool:
    """是否表格分隔行（`|---|---|` / `--- | ---:` / `|:---:|`）。"""
    s = line.strip()
    if "|" not in s:
        return False
    cells = _split_table_row(s)
    return bool(cells) and all(_TABLE_SEP_CELL_RE.match(c.replace(" ", "")) for c in cells)


def _aligns_from_sep(cells: List[str]) -> List[str]:
    """分隔行单元格 → 对齐列表（`:---:` → center，`---:` → right，其余 left）。"""
    out = []
    for c in cells:
        c = c.replace(" ", "")
        if c.startswith(":") and c.endswith(":"):
            out.append("center")
        elif c.endswith(":"):
            out.append("right")
        else:
            out.append("left")
    return out


def _is_table_start(lines: List[str], i: int) -> bool:
    """lines[i] 是表头行、lines[i+1] 是分隔行 → 表格起点。"""
    return i + 1 < len(lines) and "|" in lines[i] and _is_table_sep_row(lines[i + 1])


def _parse_table_at(lines: List[str], i: int):
    """从 lines[i] 起解析整张表，返回 (结束行下标, block 或 None)。

    支持表头行缺失（首行就是分隔行）；列数按各行最大值补齐，缺位补空单元格。
    """
    n = len(lines)
    has_header = not _is_table_sep_row(lines[i])
    if has_header:
        header = _split_table_row(lines[i])
        sep_cells = _split_table_row(lines[i + 1])
        j = i + 2
    else:
        header = None
        sep_cells = _split_table_row(lines[i])
        j = i + 1

    rows = []
    while j < n:
        s = lines[j].strip()
        if not s or "|" not in s or _is_table_sep_row(lines[j]):
            break
        rows.append(_split_table_row(lines[j]))
        j += 1

    # 表头整行空（`| | |`）→ 视为无表头，别在文档里留一行空标题
    if header is not None and not any(header):
        has_header = False
    if not has_header:
        header = None

    ncols = max([len(header) if header else 0] + [len(r) for r in rows] + [0])
    if ncols == 0:
        return i + 1, None

    aligns = (_aligns_from_sep(sep_cells) + ["left"] * ncols)[:ncols]

    def _row_cells(cells: List[str]) -> List[List[Dict]]:
        padded = cells + [""] * (ncols - len(cells))
        return [parse_inline(c) for c in padded[:ncols]]

    rows_out: List[List[List[Dict]]] = []
    if has_header:
        rows_out.append(_row_cells(header))
    rows_out.extend(_row_cells(r) for r in rows)

    return j, {"type": "table", "header": has_header,
               "aligns": aligns, "cells": rows_out}


def _collect_fence(lines: List[str], i: int):
    """收集 ``` 围栏内正文，返回 (行列表, 结束行下标)（未闭合则到文件末）。"""
    n = len(lines)
    body = []
    j = i
    while j < n and not _FENCE_RE.match(lines[j].strip()):
        body.append(lines[j])
        j += 1
    return body, min(j + 1, n)


def _make_list_item(m: "re.Match") -> Dict:
    """列表行 → block（marker 折进首个 run，缩进层级按前导空白推）。"""
    indent, marker, content = m.group(1), m.group(2), m.group(3)
    level = min(len(indent.replace("\t", "    ")) // 2, 3)

    m_task = _TASK_RE.match(content)
    if m_task:
        prefix = "☑ " if m_task.group(1).lower() == "x" else "☐ "
        content = m_task.group(2)
    elif marker[0].isdigit():
        prefix = marker + " "      # 保留原编号，3./4. 开头也能对上
    else:
        prefix = "• "

    return {"type": "list_item", "level": level,
            "runs": parse_inline(prefix + content)}


def parse_blocks(text: str) -> List[Dict]:
    """逐行扫描 → block 列表（标题 / 段落 / 引用 / 表格 / 列表 / 代码块）。

    输出例：
        parse_blocks("# Q3 报告\\n\\n正文内容\\n> 风险")
        → [
            {"type": "heading", "level": 1, "runs": [{"text": "Q3 报告"}]},
            {"type": "paragraph", "runs": [{"text": "正文内容"}]},
            {"type": "quote", "level": 0, "runs": [{"text": "风险"}]},
          ]

        parse_blocks("| a | b |\\n|---|---|\\n| 1 | 2 |")
        → [{"type": "table", "header": True, "aligns": ["left", "left"],
            "cells": [[[{"text": "a"}], [{"text": "b"}]],
                     [[{"text": "1"}], [{"text": "2"}]]]}]

    Args:
        text: 多行 markdown 字符串

    Returns:
        list[dict]: 每项含 type + runs；表格另有 header/aligns/cells

    规则：
        - `# / ## / ...` 开头的行 → heading（最多 6 级）
        - `> ` 开头的行 → quote（连续多行合并为一段）
        - 含 `|` 且下一行是 `---|---` → table（表格可嵌在段落中间，不要求空行分隔）
        - `- / * / + / 1.` 开头 → list_item（`[ ] / [x]` 折成 ☐ / ☑）
        - ``` / ~~~ 围栏 → code（内容不走行内解析）
        - `---` / `***` 水平线 → 跳过
        - 其余按空行分段成 paragraph
    """
    if not text or not text.strip():
        return []

    lines = text.splitlines()
    blocks: List[Dict] = []
    para_buf: List[str] = []
    quote_buf: List[str] = []

    def _flush_para():
        if para_buf:
            blocks.append({"type": "paragraph",
                           "runs": parse_inline("\n".join(para_buf))})
            para_buf.clear()

    def _flush_quote():
        if quote_buf:
            blocks.append({"type": "quote", "level": 0,
                           "runs": parse_inline("\n".join(quote_buf))})
            quote_buf.clear()

    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        stripped = ln.strip()

        # 1. 围栏代码块
        m_fence = _FENCE_RE.match(stripped)
        if m_fence:
            _flush_para()
            _flush_quote()
            body, i = _collect_fence(lines, i + 1)
            blocks.append({"type": "code", "lang": m_fence.group(1) or "",
                           "text": "\n".join(body)})
            continue

        # 2. 表格
        if _is_table_start(lines, i):
            _flush_para()
            _flush_quote()
            end, tbl = _parse_table_at(lines, i)
            if tbl:
                blocks.append(tbl)
                i = end
                continue
            para_buf.append(ln)   # 解析不出列 → 当普通行，避免死循环
            i += 1
            continue

        # 3. 空行
        if not stripped:
            _flush_para()
            _flush_quote()
            i += 1
            continue

        # 4. 水平线 → 跳过
        if _HR_RE.match(stripped):
            _flush_para()
            _flush_quote()
            i += 1
            continue

        # 5. 标题
        m_h = _HEADING_RE.match(stripped)
        if m_h:
            _flush_para()
            _flush_quote()
            blocks.append({
                "type": "heading",
                "level": min(max(len(m_h.group(1)), 1), 6),
                "runs": parse_inline(m_h.group(2)),
            })
            i += 1
            continue

        # 6. 引用（连续多行合并）
        m_q = _QUOTE_RE.match(stripped)
        if m_q:
            _flush_para()
            quote_buf.append(m_q.group(1))
            i += 1
            continue

        # 7. 列表
        m_l = _LIST_RE.match(ln)
        if m_l:
            _flush_para()
            _flush_quote()
            blocks.append(_make_list_item(m_l))
            i += 1
            continue

        # 8. 普通行
        _flush_quote()
        para_buf.append(ln)
        i += 1

    _flush_para()
    _flush_quote()
    return blocks


# ============================================================================
# AI 容错快查表
# ============================================================================

def supported_syntax() -> dict:
    """返回支持的语法清单（AI 自查用，SKILL.md 可省略重复列举）。"""
    return {
        "inline": {
            "bold": "**text**",
            "italic": "*text*",
            "underline": "__text__",
            "strike": "~~text~~",
            "color_close": "[color=red]text[/color]",
            "color_open": "[color=red]text  # 自动延伸到段末",
            "highlight_close": "[highlight=yellow]text[/highlight]",
            "size": "[size=小四]text[/size]",
            "font": "[font=微软雅黑]text[/font]",
        },
        "block": {
            "heading": "# / ## / ### ... ###### (最多 6 级)",
            "paragraph": "空行分隔",
            "quote": "> 文字（连续多行合并）",
            "table": "| a | b |\\n|---|---:|\\n| 1 | 2 |  （表头 / 对齐 / 单元格行内样式）",
            "list": "- / * / + 无序；1. / 2) 有序（保留原编号）；- [ ] / - [x] 任务项",
            "code": "```lang ... ``` 围栏（等宽，不走行内解析）",
            "hr": "--- (跳过)",
        },
        "color_formats": ["#FF0000", "FF0000", "red", "rgb(255,0,0)"],
        "highlight_names": "OOXML 16 色：yellow / green / cyan / magenta / blue / red "
                           "/ darkBlue / darkCyan / darkGreen / darkMagenta / darkRed "
                           "/ darkYellow / darkGray / lightGray / black / white",
    }