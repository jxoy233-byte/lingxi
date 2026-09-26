"""Word 文档编辑 skill —— 基于 lxml + zipfile 直接操作 OOXML。

零外部 CLI 依赖，不引入 python-docx。仅 .docx（OOXML），WPS / Microsoft Office 双端可打开。

LLM 调用方式（沙盒 code() 内）:
    from skills.WordEditor import WordDoc, OfficeDocError

    doc = WordDoc.create("/work/report.docx")
    doc.add_paragraph("标题", style="Title")
    doc.add_heading("执行摘要", level=1)
    doc.add_paragraph("正文", alignment="justify", font_size="小四")
    doc.add_table(rows=3, cols=2, data=[["a", "b"], ["c", "d"]], header=True)
    doc.add_image("/work/chart.png", width="15cm")
    doc.save()
"""
import io
import re
import sys
import zipfile
from copy import deepcopy
from hashlib import md5
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from lxml import etree

from skills._shared._skill_help import _HelpMeta, auto_attach_help_module


# ============================================================================
# 常量
# ============================================================================

# 中文字号 → pt
_CHINESE_FONT_SIZES = {
    "初号": 42, "小初": 36,
    "一号": 26, "小一": 24,
    "二号": 22, "小二": 18,
    "三号": 16, "小三": 15,
    "四号": 14, "小四": 12,
    "五号": 10.5, "小五": 9,
    "六号": 7.5, "小六": 6.5,
    "七号": 5.5, "八号": 5,
}

# 单位 → pt
_UNIT_TO_PT = {
    "pt": 1.0,
    "px": 0.75,
    "cm": 28.3464567,
    "mm": 2.83464567,
    "in": 72.0,
}

# 对齐白名单
_VALID_ALIGNMENTS = ("left", "center", "right", "justify", "both")

# 行距规则
_VALID_LINE_RULES = ("auto", "exact", "atLeast")

# 下划线别名 → OOXML 标准值
_UNDERLINE_ALIASES = {
    "single": "single", "true": "single", "1": "single",
    "double": "double", "thick": "thick",
    "dotted": "dotted", "dottedheavy": "dottedHeavy",
    "dashed": "dash", "dash": "dash", "dashedheavy": "dashedHeavy",
    "dashlong": "dashLong", "longdash": "dashLong",
    "dashlongheavy": "dashLongHeavy",
    "dotdash": "dotDash", "dashdot": "dotDash",
    "dashdotheavy": "dotDotHeavy",
    "dotdotdash": "dotDotDash",
    "wave": "wave", "wavy": "wave",
    "wavyheavy": "wavyHeavy",
    "wavydouble": "wavyDouble", "wavedouble": "wavyDouble", "doublewave": "wavyDouble",
    "words": "words", "word": "words",
    "none": "none", "false": "none", "0": "none", "": "none",
}

# 字重 → (字体名后缀, 是否设 <w:b/>)
_FONT_WEIGHT_MAP = {
    "thin":       {"suffix": " Thin",       "bold": False},
    "hairline":   {"suffix": " Thin",       "bold": False},
    "light":      {"suffix": " Light",      "bold": False},
    "regular":    {"suffix": "",            "bold": False},
    "normal":     {"suffix": "",            "bold": False},
    "medium":     {"suffix": " Medium",     "bold": False},
    "semibold":   {"suffix": " SemiBold",   "bold": False},
    "demibold":   {"suffix": " SemiBold",   "bold": False},
    "bold":       {"suffix": "",            "bold": True},
    "extrabold":  {"suffix": " ExtraBold",  "bold": False},
    "heavy":      {"suffix": " Black",      "bold": False},
    "black":      {"suffix": " Black",      "bold": False},
    "extrablack": {"suffix": " ExtraBlack", "bold": False},
}

# 高亮色白名单（OOXML 标准）
_VALID_HIGHLIGHTS = frozenset([
    "yellow", "green", "cyan", "magenta", "blue",
    "red", "darkBlue", "darkCyan", "darkGreen", "darkMagenta",
    "darkRed", "darkYellow", "darkGray", "lightGray", "black", "white",
])

# 图片扩展名白名单
_VALID_IMAGE_EXTS = ("png", "jpg", "jpeg", "gif", "bmp")


# ============================================================================
# 工具函数
# ============================================================================

def _xml_escape(s: str) -> str:
    """XML 文本/属性转义。"""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&apos;"))


def to_pt(value) -> Optional[float]:
    """字号 / 尺寸 → pt（float）。详细 help("to_pt")。

    Args: value None / 数字 / "12pt" / "0.5cm" / "小四" 等。
    Returns: float（pt）；None 入参返回 None。
    Raises: 无法解析抛 OfficeDocError。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    if s in _CHINESE_FONT_SIZES:
        return _CHINESE_FONT_SIZES[s]
    for unit in sorted(_UNIT_TO_PT.keys(), key=len, reverse=True):
        if s.endswith(unit):
            try:
                return float(s[:-len(unit)].strip()) * _UNIT_TO_PT[unit]
            except ValueError:
                break
    try:
        return float(s)
    except ValueError:
        raise OfficeDocError(
            f"无法解析尺寸: {value!r}\n"
            f"支持格式: '12pt' / '0.5cm' / '1in' / '小四' / 纯数字"
        )


def _parse_indent_chars(value) -> Optional[int]:
    """`"2字符"` → 200（OOXML firstLineChars/leftChars 单位 = 1/100 字符）；非字符单位返回 None。"""
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("字符"):
            try:
                return int(float(s[:-2].strip()) * 100)
            except ValueError:
                pass
    return None


def to_rgb(value) -> Optional[Tuple[int, int, int]]:
    """颜色 → (r, g, b) 元组。详细 help("to_rgb")。

    Args: value None / hex / named / "rgb()" / 3 元组（"#1F2937" / "red" / "rgb(255,0,0)" / (255, 0, 0)）。
    Returns: Tuple[int,int,int]（0-255）；None 入参返回 None。
    Raises: 无法解析抛 OfficeDocError。
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(int(v) for v in value)
    s = str(value).strip()
    if not s:
        return None
    if s.startswith("#"):
        s = s[1:]
    if s.startswith("rgb(") and s.endswith(")"):
        try:
            nums = [int(n.strip()) for n in s[4:-1].split(",")]
            if len(nums) == 3:
                return tuple(nums)
        except ValueError:
            pass
    named = {
        "black": (0, 0, 0), "white": (255, 255, 255),
        "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
        "gray": (128, 128, 128), "grey": (128, 128, 128),
        "yellow": (255, 255, 0), "orange": (255, 165, 0),
        "purple": (128, 0, 128), "pink": (255, 192, 203),
        "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    }
    if s.lower() in named:
        return named[s.lower()]
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    raise OfficeDocError(
        f"无法解析颜色: {value!r}\n"
        f"支持格式: '#1F2937' / 'FF0000' / 'red' / 'rgb(255, 0, 0)' / (255, 0, 0)"
    )


def _normalize_underline(value) -> Optional[str]:
    """下划线别名 → OOXML 标准值。None 入参返回 None。"""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s not in _UNDERLINE_ALIASES:
        raise OfficeDocError(
            f"无效的 underline 值: {value!r}\n"
            f"有效值: single, double, thick, dotted, dashed, dashLong, "
            f"dotDash, dotDotDash, wave, wavyHeavy, wavyDouble, words, none"
        )
    return _UNDERLINE_ALIASES[s]


def _normalize_alignment(value) -> Optional[str]:
    """对齐方式校验。None 入参返回 None。"""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s not in _VALID_ALIGNMENTS:
        raise OfficeDocError(
            f"无效的 alignment 值: {value!r}\n"
            f"有效值: {', '.join(_VALID_ALIGNMENTS)}"
        )
    return s


def _normalize_line_rule(value) -> Optional[str]:
    """行距规则校验。None 入参返回 None。"""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s not in _VALID_LINE_RULES:
        raise OfficeDocError(
            f"无效的 line_rule 值: {value!r}\n"
            f"有效值: {', '.join(_VALID_LINE_RULES)}"
        )
    return s


def _normalize_font_weight(value) -> Optional[dict]:
    """字体粗细 → {suffix, bold}。None 入参返回 None。"""
    if value is None:
        return None
    s = str(value).strip().lower().replace(" ", "").replace("-", "")
    if s not in _FONT_WEIGHT_MAP:
        raise OfficeDocError(
            f"无效的 font_weight 值: {value!r}\n"
            f"有效值: thin, light, regular, medium, semibold, bold, extrabold, "
            f"heavy, black, extrablack"
        )
    return _FONT_WEIGHT_MAP[s]


def _normalize_highlight(value) -> Optional[str]:
    """高亮色校验。None 入参返回 None。"""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s not in _VALID_HIGHLIGHTS:
        raise OfficeDocError(
            f"无效的 highlight 值: {value!r}\n"
            f"有效值: {', '.join(sorted(_VALID_HIGHLIGHTS))}"
        )
    return s


def _resolve_font_with_weight(font: str, weight_info: Optional[dict]) -> str:
    """合并 font + 字重后缀（避免重复追加）。"""
    if not font or not weight_info:
        return font
    suffix = weight_info.get("suffix", "")
    if not suffix:
        return font
    if any(w in font for w in (
        " Thin", " Light", " Medium", " SemiBold",
        " ExtraBold", " Black", " ExtraBlack",
    )):
        return font
    return f"{font}{suffix}"


# ============================================================================
# 异常
# ============================================================================

class OfficeDocError(Exception):
    """Word 文档操作的统一异常。"""
    pass


# ============================================================================
# OOXML 模板 + namespace 常量
# ============================================================================

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

NAMESPACES = {
    "w": W_NS, "r": R_NS, "a": A_NS, "wp": WP_NS, "pic": PIC_NS,
}


def _wt(tag: str) -> str:
    """短命名空间 helper: 'p' → '{w}p'."""
    return f"{{{W_NS}}}{tag}"


CONTENT_TYPES_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''

ROOT_RELS_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

DOC_RELS_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>'''

CORE_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
xmlns:dc="http://purl.org/dc/elements/1.1/"
xmlns:dcterms="http://purl.org/dc/terms/"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:creator>ChatMe</dc:creator>
<cp:lastModifiedBy>ChatMe</cp:lastModifiedBy>
</cp:coreProperties>'''

APP_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
<Application>ChatMe</Application>
</Properties>'''

SETTINGS_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:defaultTabStop w:val="720"/>
<w:characterSpacingControl w:val="doNotCompress"/>
</w:settings>'''

STYLES_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults>
<w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Calibri" w:eastAsia="SimSun" w:hAnsi="Calibri" w:cs="Times New Roman"/>
<w:sz w:val="21"/><w:szCs w:val="22"/>
<w:lang w:val="en-US" w:eastAsia="zh-CN" w:bidi="ar-SA"/>
</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr>
<w:spacing w:after="160" w:line="259" w:lineRule="auto"/>
</w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
<w:name w:val="Normal"/><w:qFormat/>
</w:style>
<w:style w:type="paragraph" w:styleId="Title">
<w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="300"/><w:jc w:val="center"/></w:pPr>
<w:rPr><w:rFonts w:ascii="Cambria" w:hAnsi="Cambria"/><w:b/><w:sz w:val="56"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading1">
<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading2">
<w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading3">
<w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading4">
<w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="3"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading5">
<w:name w:val="heading 5"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="4"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading6">
<w:name w:val="heading 6"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="5"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading7">
<w:name w:val="heading 7"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="6"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading8">
<w:name w:val="heading 8"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="7"/></w:pPr>
<w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading9">
<w:name w:val="heading 9"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="8"/></w:pPr>
<w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Quote">
<w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:ind w:left="480" w:right="480"/></w:pPr>
<w:rPr><w:i/><w:color w:val="404040"/></w:rPr>
</w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal">
<w:name w:val="Normal Table"/><w:uiPriority w:val="99"/>
<w:semiHidden/><w:unhideWhenUsed/>
<w:tblPr>
<w:tblInd w:w="0" w:type="dxa"/>
<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar>
</w:tblPr>
</w:style>
<w:style w:type="table" w:styleId="TableGrid">
<w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/><w:uiPriority w:val="39"/>
<w:pPr><w:spacing w:after="0"/></w:pPr>
<w:tblPr>
<w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>
<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>
</w:tblBorders>
</w:tblPr>
</w:style>
</w:styles>'''

EMPTY_DOCUMENT_XML = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<w:body>
<w:sectPr>
<w:pgSz w:w="11906" w:h="16838"/>
<w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" w:header="720" w:footer="720" w:gutter="0"/>
<w:cols w:space="720"/>
<w:docGrid w:linePitch="312"/>
</w:sectPr>
</w:body>
</w:document>'''


# ============================================================================
# 内部辅助
# ============================================================================

def _make_element(tag: str):
    """创建带 namespace map 的 lxml 元素."""
    return etree.Element(tag, nsmap=NAMESPACES)


def _parse_doc_xml(doc_bytes: bytes):
    """解析 word/document.xml 字节."""
    try:
        return etree.fromstring(doc_bytes)
    except etree.XMLSyntaxError as e:
        raise OfficeDocError(f"document.xml 解析失败: {e}")


def _to_emu(value) -> int:
    """单位 → EMU（1pt = 12700 EMU）."""
    return int(to_pt(value) * 12700)


def _build_rPr(*, bold=None, italic=None, underline=None,
               font=None, font_size=None, color=None, highlight=None):
    """构造 w:rPr 元素（None 表示不设置）."""
    rPr = _make_element(_wt("rPr"))
    has_any = False

    if font is not None:
        rFonts = etree.SubElement(rPr, _wt("rFonts"))
        rFonts.set(_wt("ascii"), font)
        rFonts.set(_wt("hAnsi"), font)
        rFonts.set(_wt("eastAsia"), font)
        rFonts.set(_wt("cs"), font)
        has_any = True
    if bold is not None:
        b = etree.SubElement(rPr, _wt("b"))
        if not bold:
            b.set(_wt("val"), "false")
        has_any = True
    if italic is not None:
        i = etree.SubElement(rPr, _wt("i"))
        if not italic:
            i.set(_wt("val"), "false")
        has_any = True
    if underline is not None:
        u = etree.SubElement(rPr, _wt("u"))
        u.set(_wt("val"), underline)
        has_any = True
    if font_size is not None:
        sz_val = str(int(to_pt(font_size) * 2))  # 半点
        sz = etree.SubElement(rPr, _wt("sz"))
        sz.set(_wt("val"), sz_val)
        szCs = etree.SubElement(rPr, _wt("szCs"))
        szCs.set(_wt("val"), sz_val)
        has_any = True
    if color is not None:
        c = etree.SubElement(rPr, _wt("color"))
        rgb = to_rgb(color)
        c.set(_wt("val"), f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")
        has_any = True
    if highlight is not None:
        h = etree.SubElement(rPr, _wt("highlight"))
        h.set(_wt("val"), highlight)
        has_any = True

    return rPr if has_any else None


def _build_pPr(*, style=None, alignment=None,
               line_spacing=None, line_rule=None,
               indent_left=None, indent_right=None, indent_first_line=None,
               space_before=None, space_after=None):
    """构造 w:pPr 元素（None 表示不设置）."""
    pPr = _make_element(_wt("pPr"))
    has_any = False

    if style is not None:
        pStyle = etree.SubElement(pPr, _wt("pStyle"))
        pStyle.set(_wt("val"), style.replace(" ", ""))
        has_any = True
    if alignment is not None:
        jc = etree.SubElement(pPr, _wt("jc"))
        jc.set(_wt("val"), alignment)
        has_any = True
    if (indent_left is not None or indent_right is not None
            or indent_first_line is not None):
        ind = etree.SubElement(pPr, _wt("ind"))
        if indent_left is not None:
            chars = _parse_indent_chars(indent_left)
            if chars is not None:
                ind.set(_wt("leftChars"), str(chars))
            else:
                ind.set(_wt("left"), str(int(to_pt(indent_left) * 20)))
        if indent_right is not None:
            chars = _parse_indent_chars(indent_right)
            if chars is not None:
                ind.set(_wt("rightChars"), str(chars))
            else:
                ind.set(_wt("right"), str(int(to_pt(indent_right) * 20)))
        if indent_first_line is not None:
            chars = _parse_indent_chars(indent_first_line)
            if chars is not None:
                ind.set(_wt("firstLineChars"), str(chars))
            else:
                first_pt = to_pt(indent_first_line)
                if first_pt < 0:
                    ind.set(_wt("hanging"), str(int(-first_pt * 20)))
                else:
                    ind.set(_wt("firstLine"), str(int(first_pt * 20)))
        has_any = True
    if (space_before is not None or space_after is not None
            or line_spacing is not None):
        spacing = etree.SubElement(pPr, _wt("spacing"))
        if space_before is not None:
            spacing.set(_wt("before"), str(int(to_pt(space_before) * 20)))
        if space_after is not None:
            spacing.set(_wt("after"), str(int(to_pt(space_after) * 20)))
        if line_spacing is not None:
            spacing.set(_wt("line"), str(int(to_pt(line_spacing) * 20)))
        spacing.set(_wt("lineRule"), line_rule or "auto")
        has_any = True

    return pPr if has_any else None


def _make_run(text: str, *, bold=None, italic=None, underline=None,
              font=None, font_size=None,
              font_weight=None, color=None, highlight=None):
    """构造 w:r 元素（含 w:rPr 样式属性 + w:t 文本）."""
    weight_info = _normalize_font_weight(font_weight)
    if weight_info and weight_info["bold"]:
        bold = True
    if font and weight_info:
        font = _resolve_font_with_weight(font, weight_info)

    r = _make_element(_wt("r"))
    rPr = _build_rPr(bold=bold, italic=italic, underline=underline,
                     font=font, font_size=font_size,
                     color=color, highlight=highlight)
    if rPr is not None:
        r.append(rPr)
    t = etree.SubElement(r, _wt("t"))
    t.set(f"{{{XML_NS}}}space", "preserve")
    t.text = text or ""
    return r


def _para_text(p) -> str:
    """提取段落所有 run 的文本（lxml 自动转义）."""
    return "".join((t.text or "") for t in p.iter(_wt("t")))


def _para_style(p) -> str:
    """提取段落样式名（去掉空格，如 'Heading 1' → 'Heading1'）."""
    pStyle = p.find(f"{_wt('pPr')}/{_wt('pStyle')}")
    if pStyle is not None:
        return pStyle.get(_wt("val"), "")
    return "Normal"


def _body_children(body):
    """body 直接子元素列表（跳过 sectPr）."""
    return [c for c in body if c.tag != _wt("sectPr")]


def _insert_before_sectpr(body, elem):
    """在 sectPr 之前追加元素（sectPr 必须 body 末尾）."""
    sectPr = body.find(_wt("sectPr"))
    if sectPr is not None:
        sectPr.addprevious(elem)
    else:
        body.append(elem)


# ============================================================================
# 辅助类
# ============================================================================

class _WordParagraph:
    """段落包装（OOXML <w:p>）。详细 help("_WordParagraph")。

    Args: text 段落初始文字；parent 所属 WordDoc；p_elem lxml <w:p> 元素。
    属性: text 段落文字；_element 内部 XML elem；_parent 所属 WordDoc。
    """

    def __init__(self, text: str, parent: "WordDoc", p_elem):
        self.text = text or ""
        self._parent = parent
        self._element = p_elem

    def set_text(self, text: str):
        """替换段落文字（保留第一个 run 的样式）。"""
        existing_runs = list(self._element.findall(_wt("r")))
        first_rPr_copy = deepcopy(existing_runs[0].find(_wt("rPr"))) if existing_runs else None
        for r in existing_runs:
            self._element.remove(r)
        if text:
            r = _make_run(text)
            if first_rPr_copy is not None:
                new_rPr = r.find(_wt("rPr"))
                if new_rPr is None:
                    r.insert(0, first_rPr_copy)
            self._element.append(r)
        self.text = text or ""

    def set_format(self, *, style=None, alignment=None,
                   line_spacing=None, line_rule=None,
                   indent_left=None, indent_right=None, indent_first_line=None,
                   space_before=None, space_after=None,
                   bold=None, italic=None, underline=None,
                   font=None, font_size=None, font_weight=None,
                   color=None, highlight=None) -> "_WordParagraph":
        """链式改段落样式（段落属性写 pPr，run 属性应用到所有 run）。详细 help("set_format")。

        Returns: self（链式）。
        """
        # 段落属性
        if any(x is not None for x in (
            style, alignment, line_spacing, indent_left, indent_right,
            indent_first_line, space_before, space_after,
        )):
            pPr = self._element.find(_wt("pPr"))
            if pPr is None:
                pPr = _make_element(_wt("pPr"))
                self._element.insert(0, pPr)
            if style is not None:
                pStyle = pPr.find(_wt("pStyle"))
                if pStyle is None:
                    pStyle = _make_element(_wt("pStyle"))
                    pPr.insert(0, pStyle)
                pStyle.set(_wt("val"), style.replace(" ", ""))
            if alignment is not None:
                jc = pPr.find(_wt("jc"))
                if jc is None:
                    jc = _make_element(_wt("jc"))
                    pPr.append(jc)
                jc.set(_wt("val"), _normalize_alignment(alignment))
            if line_spacing is not None:
                spacing = pPr.find(_wt("spacing"))
                if spacing is None:
                    spacing = _make_element(_wt("spacing"))
                    pPr.append(spacing)
                spacing.set(_wt("line"), str(int(to_pt(line_spacing) * 20)))
                spacing.set(_wt("lineRule"),
                            _normalize_line_rule(line_rule) or "auto")

        # run 属性（应用到所有 run）
        run_kwargs_set = any(x is not None for x in (
            bold, italic, underline, font, font_size, font_weight,
            color, highlight,
        ))
        if run_kwargs_set:
            weight_info = _normalize_font_weight(font_weight)
            eff_bold = bold if bold is not None else (weight_info["bold"] if weight_info else None)
            eff_underline = _normalize_underline(underline) if underline is not None else None
            eff_font = (_resolve_font_with_weight(font, weight_info)
                        if font and weight_info else font)
            eff_highlight = _normalize_highlight(highlight) if highlight is not None else None
            new_rPr = _build_rPr(
                bold=eff_bold, italic=italic, underline=eff_underline,
                font=eff_font, font_size=font_size,
                color=color, highlight=eff_highlight,
            )
            if new_rPr is not None:
                for run in self._element.findall(_wt("r")):
                    old = run.find(_wt("rPr"))
                    if old is not None:
                        run.remove(old)
                    run.insert(0, deepcopy(new_rPr))

        return self


class _WordTable:
    """Word 表格包装（OOXML <w:tbl>）。详细 help("_WordTable")。

    Args: rows 行数；cols 列数；parent 所属 WordDoc；tbl_elem lxml <w:tbl> 元素。
    属性: rows/cols 行列数；cells 二维列表 [[{text, tc}]]；_element 内部 XML elem；_parent。
    """

    def __init__(self, rows: int, cols: int, parent: "WordDoc", tbl_elem):
        self.rows = rows
        self.cols = cols
        self._parent = parent
        self._element = tbl_elem
        self.cells = self._index_cells()

    def _index_cells(self) -> list:
        """建立二维 cells 列表（每格包 text + tc 元素）."""
        grid = []
        for tr in self._element.findall(_wt("tr")):
            row = []
            for tc in tr.findall(_wt("tc")):
                first_p = tc.find(_wt("p"))
                row.append({
                    "text": _para_text(first_p) if first_p is not None else "",
                    "tc": tc,
                })
            grid.append(row)
        return grid

    def set_cell(self, row: int, col: int, value: str, **format_kwargs):
        """设指定单元格文字 + 格式（覆盖原段落）。详细 help("set_cell")。

        Args: row/col 0-based 行列索引；value 文字；**format_kwargs run 格式（bold/italic/font/color/...）。
        Raises: row/col 越界抛 OfficeDocError。
        """
        rows = self._element.findall(_wt("tr"))
        if row < 0 or row >= len(rows):
            raise OfficeDocError(f"行索引超出范围: {row}（共 {len(rows)} 行）")
        cells = rows[row].findall(_wt("tc"))
        if col < 0 or col >= len(cells):
            raise OfficeDocError(f"列索引超出范围: {col}（共 {len(cells)} 列）")
        cell = cells[col]
        for p in list(cell.findall(_wt("p"))):
            cell.remove(p)
        para = _make_element(_wt("p"))
        if value:
            r = _make_run(value, **format_kwargs)
            para.append(r)
        cell.append(para)
        self.cells = self._index_cells()

    def add_row(self, values: Optional[list] = None) -> None:
        """追加一行到表格末尾。详细 help("add_row")。

        Args: values 单元格值列表（长度=列数；不足补空字符串）。
        """
        values = values or []
        tr = etree.SubElement(self._element, _wt("tr"))
        cols = self.cols
        for c_idx in range(cols):
            tc = etree.SubElement(tr, _wt("tc"))
            tcPr = etree.SubElement(tc, _wt("tcPr"))
            tcW = etree.SubElement(tcPr, _wt("tcW"))
            tcW.set(_wt("w"), str(int(5000 / cols)))
            tcW.set(_wt("type"), "pct")
            p = etree.SubElement(tc, _wt("p"))
            if c_idx < len(values) and values[c_idx] is not None:
                r = etree.SubElement(p, _wt("r"))
                t = etree.SubElement(r, _wt("t"))
                t.set(f"{{{XML_NS}}}space", "preserve")
                t.text = str(values[c_idx])
        self.rows += 1
        self.cells = self._index_cells()

    def set_style(self, style: str) -> None:
        """改表格样式（如 'TableGrid' / 'LightShading'）。详细 help("set_style")。

        Args: style 样式名（默认样式 'TableGrid'）。
        """
        tblPr = self._element.find(_wt("tblPr"))
        if tblPr is None:
            tblPr = _make_element(_wt("tblPr"))
            self._element.insert(0, tblPr)
        tblStyle = tblPr.find(_wt("tblStyle"))
        if tblStyle is None:
            tblStyle = _make_element(_wt("tblStyle"))
            tblPr.insert(0, tblStyle)
        tblStyle.set(_wt("val"), style)


class _WordPicture:
    """Word 图片包装。详细 help("_WordPicture")。

    Args: path 图片路径；parent 所属 WordDoc；drawing_elem lxml <w:drawing> 元素。
    属性: path 路径；width_pt/height_pt 宽高（pt）；_element 内部 XML elem；_parent。
    """

    def __init__(self, path: str, parent: "WordDoc", drawing_elem):
        self.path = path
        self._parent = parent
        self._element = drawing_elem
        self.width_pt, self.height_pt = self._extract_size(drawing_elem)

    @staticmethod
    def _extract_size(drawing_elem) -> Tuple[Optional[float], Optional[float]]:
        """从 <wp:extent> 提取 EMU → pt."""
        extent = drawing_elem.find(f"{{{WP_NS}}}inline/{{{WP_NS}}}extent")
        if extent is None:
            return None, None
        cx = int(extent.get("cx", "0"))
        cy = int(extent.get("cy", "0"))
        return cx / 12700.0, cy / 12700.0


# ============================================================================
# 核心类
# ============================================================================

class WordDoc(metaclass=_HelpMeta):
    """Word 文档（.docx）封装，基于 lxml + zipfile 直接操作 OOXML。

    写入默认 append 到 body 末尾；改 / 删用 set_paragraph / remove_paragraph；插入用 add_paragraph(at_index=) / add_paragraph(after=)。
    """

    def __init__(self, body_elem, rels=None, path: Optional[str] = None):
        """内部构造，请用 `create()` / `open()` 类方法."""
        self._body = body_elem
        self._rels = rels or {}
        self._path = path
        self._media_files = []  # [(rid, src_path, target, hash)]
        self._next_rid = 10  # 避开 rId1/rId2/rId3

    # ---- 工厂 ----

    @classmethod
    def create(cls, path: Optional[str] = None) -> "WordDoc":
        """创建空白 docx。详细 help("create")。

        Args: path 文件保存路径（None 时 save() 必须显式传）。
        Returns: WordDoc 实例。
        """
        root = _parse_doc_xml(EMPTY_DOCUMENT_XML)
        body = root.find(_wt("body"))
        return cls(body, path=path)

    @classmethod
    def open(cls, path: str) -> "WordDoc":
        """打开已有 docx。详细 help("open")。

        Args: path .docx 文件路径。
        Returns: WordDoc 实例。
        Raises: 文件不存在 / zip 损坏 / XML 解析失败抛 OfficeDocError。
        """
        path = str(Path(path))
        if not Path(path).exists():
            raise OfficeDocError(f"文件不存在: {path}")
        try:
            with zipfile.ZipFile(path, "r") as z:
                doc_xml = z.read("word/document.xml")
        except KeyError:
            raise OfficeDocError(f"docx 缺少 word/document.xml，文件可能损坏: {path}")
        except zipfile.BadZipFile:
            raise OfficeDocError(f"不是有效的 docx（zip 解析失败）: {path}")
        root = _parse_doc_xml(doc_xml)
        body = root.find(_wt("body"))
        return cls(body, path=path)

    # ---- 持久化 ----

    def save(self, path: Optional[str] = None):
        """落盘到 path 或 create/open 时指定的路径。详细 help("save")。

        Args: path 输出路径（None 用 create()/open() 时指定的路径）。
        Raises: 都没有 path 抛 OfficeDocError。
        Note: add_image() 必须在 save() 前调用；save() 自动把图片二进制写入 word/media/ 并注册 Content_Types + document.xml.rels。
        """
        out = path or self._path
        if not out:
            raise OfficeDocError("save() 需要 path，或在 create()/open() 时指定 path")

        # 重置 doc_root（用 EMPTY_DOCUMENT_XML 模板包装 body）
        # 根元素声明完整 NAMESPACES：子元素（_make_element 创建）的 nsmap 与已在 scope 内的
        # 前缀/URI 相同的，lxml 序列化时自动省略，不再每个元素重复 xmlns:a/pic/wp 声明
        doc_root = etree.Element(
            _wt("document"),
            nsmap=NAMESPACES,
        )
        doc_root.append(self._body)

        doc_bytes = etree.tostring(
            doc_root, xml_declaration=True, encoding="UTF-8", standalone=True,
        )

        content_types = self._build_content_types()
        doc_rels = self._build_doc_rels()

        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", ROOT_RELS_XML)
            z.writestr("word/document.xml", doc_bytes)
            z.writestr("word/_rels/document.xml.rels", doc_rels)
            z.writestr("word/styles.xml", STYLES_XML)
            z.writestr("word/settings.xml", SETTINGS_XML)
            z.writestr("docProps/core.xml", CORE_XML)
            z.writestr("docProps/app.xml", APP_XML)

            for rid, src_path, target, _hash in self._media_files:
                with open(src_path, "rb") as f:
                    z.writestr(f"word/{target}", f.read())

        self._path = out

    def _build_content_types(self) -> bytes:
        """根据图片类型动态生成 [Content_Types].xml."""
        extensions = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "gif": "image/gif",
            "bmp": "image/bmp",
        }
        seen = set()
        defaults_extra = ""
        overrides = []
        for rid, src_path, target, _hash in self._media_files:
            ext = Path(src_path).suffix.lower().lstrip(".")
            mime = extensions.get(ext, "application/octet-stream")
            overrides.append(
                f'<Override PartName="/word/{target}" ContentType="{mime}"/>'
            )
            if ext not in seen and ext in extensions:
                seen.add(ext)
                defaults_extra += (
                    f'\n<Default Extension="{ext}" ContentType="{extensions[ext]}"/>'
                )

        body = (
            f'<Default Extension="rels" '
            f'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'\n<Default Extension="xml" ContentType="application/xml"/>'
            f'{defaults_extra}'
            f'\n<Override PartName="/word/document.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            f'\n<Override PartName="/word/styles.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            f'\n<Override PartName="/word/settings.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
            f'\n<Override PartName="/docProps/core.xml" '
            f'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            f'\n<Override PartName="/docProps/app.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        )
        if overrides:
            body += "\n" + "\n".join(overrides)

        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Types xmlns="{CT_NS}">\n{body}\n</Types>'
        )
        return xml.encode("utf-8")

    def _build_doc_rels(self) -> bytes:
        """根据图片动态生成 word/_rels/document.xml.rels."""
        rels = [
            '<Relationship Id="rId1" '
            f'Type="{R_NS}/styles" Target="styles.xml"/>',
            '<Relationship Id="rId2" '
            f'Type="{R_NS}/settings" Target="settings.xml"/>',
        ]
        for rid, src_path, target, _hash in self._media_files:
            rels.append(
                f'<Relationship Id="{rid}" '
                f'Type="{R_NS}/image" Target="{target}"/>'
            )
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{RELS_NS}">\n'
            + "\n".join(rels)
            + "\n</Relationships>"
        )
        return xml.encode("utf-8")

    # ---- 段落 ----

    def add_paragraph(self, text: str = "", *,
                      style: str = None,
                      bold: bool = None, italic: bool = None,
                      underline: str = None,
                      font: str = None, font_size=None, font_weight: str = None,
                      color: str = None, highlight: str = None,
                      alignment: str = None,
                      line_spacing=None, line_rule: str = None,
                      indent_left=None, indent_right=None,
                      indent_first_line=None,
                      space_before=None, space_after=None,
                      at_index: int = None,
                      after=None) -> _WordParagraph:
        """加段落（默认 append 到 body 末尾）。详细 help("add_paragraph")。

        Args: text 段落文字（空=空段落）；style "Heading 1"/"Title"/"Normal"；bold/italic/underline/font/font_size/font_weight/color/highlight run 样式；alignment/line_spacing/line_rule/indent_*/space_* 段落属性（indent_* 支持 "2字符" 走 OOXML firstLineChars，或 "0.74cm"/"12pt" 走绝对长度）；at_index 0-based 插入位置；after `_WordParagraph` 锚点（与 at_index 互斥）。
        Returns: _WordParagraph（可链式 set_format）。
        Raises: at_index 和 after 同时给 / 对齐/下划线/字重非法值抛 OfficeDocError。
        """
        if at_index is not None and after is not None:
            raise OfficeDocError("at_index 和 after 互斥，只能选一个")

        # 规范化
        alignment_v = _normalize_alignment(alignment)
        underline_v = _normalize_underline(underline)
        line_rule_v = _normalize_line_rule(line_rule)
        weight_info = _normalize_font_weight(font_weight)
        if weight_info and weight_info["bold"]:
            bold = True
        if font and weight_info:
            font = _resolve_font_with_weight(font, weight_info)
        highlight_v = _normalize_highlight(highlight)

        # 构建段落
        p = _make_element(_wt("p"))
        pPr = _build_pPr(
            style=style, alignment=alignment_v,
            line_spacing=line_spacing, line_rule=line_rule_v,
            indent_left=indent_left, indent_right=indent_right,
            indent_first_line=indent_first_line,
            space_before=space_before, space_after=space_after,
        )
        if pPr is not None:
            p.append(pPr)

        if text:
            r = _make_run(text, bold=bold, italic=italic, underline=underline_v,
                          font=font, font_size=font_size,
                          color=color, highlight=highlight_v)
            p.append(r)

        # 插入位置
        if after is not None:
            anchor_p = after._element
            anchor_p.addnext(p)
        elif at_index is not None:
            self._insert_paragraph_at(p, at_index)
        else:
            _insert_before_sectpr(self._body, p)

        return _WordParagraph(text, self, p)

    def add_heading(self, text: str, level: int = 1, **format_kwargs) -> _WordParagraph:
        """加标题（add_paragraph + style="Heading N" 的便捷封装）。详细 help("add_heading")。

        Args: text 标题文字；level 1~9（对应 Heading 1~9）；**format_kwargs 透传给 add_paragraph（若用户显式传 style 则覆盖默认的 "Heading N"）。
        Returns: _WordParagraph。
        """
        level = max(1, min(9, level))
        # 用户传的 style 优先于默认 "Heading N"
        style = format_kwargs.pop("style", None) or f"Heading {level}"
        return self.add_paragraph(text, style=style, **format_kwargs)

    def add_page_break(self) -> None:
        """加分页符（追加一个仅含 w:br type=page 的段）。详细 help("add_page_break")。"""
        p = _make_element(_wt("p"))
        r = etree.SubElement(p, _wt("r"))
        br = etree.SubElement(r, _wt("br"))
        br.set(_wt("type"), "page")
        _insert_before_sectpr(self._body, p)

    def add_field(self, text_before: str, field_code: str,
                  text_after: str = "", *,
                  alignment: str = None, font_size=None, bold=None,
                  font=None, font_weight=None, color=None) -> _WordParagraph:
        """插字段（如 PAGE / NUMPAGES / TOC）。详细 help("add_field")。

        Args: text_before 字段前字面文字；field_code 字段代码（PAGE/NUMPAGES/TOC 等）；text_after 字段后字面文字；alignment/font_size/bold/font/font_weight/color 段落与 run 样式。
        Returns: _WordParagraph。
        """
        alignment_v = _normalize_alignment(alignment)
        weight_info = _normalize_font_weight(font_weight)
        if weight_info and weight_info["bold"]:
            bold = True
        if font and weight_info:
            font = _resolve_font_with_weight(font, weight_info)

        def _run_kwargs():
            return dict(bold=bold, font=font, font_size=font_size, color=color)

        p = _make_element(_wt("p"))
        if alignment_v:
            pPr = _make_element(_wt("pPr"))
            jc = etree.SubElement(pPr, _wt("jc"))
            jc.set(_wt("val"), alignment_v)
            p.append(pPr)

        if text_before:
            p.append(_make_run(text_before, **_run_kwargs()))

        # fldChar begin
        r1 = _make_element(_wt("r"))
        rPr1 = _build_rPr(bold=bold, font=font, font_size=font_size, color=color)
        if rPr1 is not None:
            r1.append(rPr1)
        fld_begin = etree.SubElement(r1, _wt("fldChar"))
        fld_begin.set(_wt("fldCharType"), "begin")
        p.append(r1)

        # instrText（字段代码）
        r2 = _make_element(_wt("r"))
        rPr2 = _build_rPr(bold=bold, font=font, font_size=font_size, color=color)
        if rPr2 is not None:
            r2.append(rPr2)
        instr = etree.SubElement(r2, _wt("instrText"))
        instr.set(f"{{{XML_NS}}}space", "preserve")
        instr.text = _xml_escape(f" {field_code} ")
        p.append(r2)

        # fldChar separate
        r3 = _make_element(_wt("r"))
        fld_sep = etree.SubElement(r3, _wt("fldChar"))
        fld_sep.set(_wt("fldCharType"), "separate")
        p.append(r3)

        # cached value（占位 "?"，Word/WPS 打开时自动重算）
        p.append(_make_run("?", **_run_kwargs()))

        # fldChar end
        r5 = _make_element(_wt("r"))
        fld_end = etree.SubElement(r5, _wt("fldChar"))
        fld_end.set(_wt("fldCharType"), "end")
        p.append(r5)

        if text_after:
            p.append(_make_run(text_after, **_run_kwargs()))

        _insert_before_sectpr(self._body, p)
        return _WordParagraph(text_before, self, p)

    def _insert_paragraph_at(self, p, index: int):
        """在 body 指定位置插入段落（跳过 sectPr）."""
        children = _body_children(self._body)
        if index >= len(children):
            _insert_before_sectpr(self._body, p)
        else:
            children[index].addprevious(p)

    # ---- 表格 ----

    def add_table(self, rows: int, cols: int, *,
                  data: Optional[list] = None,
                  header: bool = False,
                  header_fill: str = None,
                  style: str = "TableGrid") -> _WordTable:
        """加表格到 body 末尾（表格后必有占位空段）。详细 help("add_table")。

        Args: rows/cols 行列数（必须 > 0）；data 二维列表（缺位补空字符串）；header True 时首行作表头（加粗+白字+header_fill 背景）；header_fill 表头背景色；style 表样式名（默认 "TableGrid"，None=无样式+默认边框）。
        Returns: _WordTable。
        Raises: rows/cols <= 0 抛 OfficeDocError。
        """
        if rows <= 0 or cols <= 0:
            raise OfficeDocError(f"表格行列数必须 > 0: rows={rows}, cols={cols}")

        tbl = _make_element(_wt("tbl"))

        # tblPr
        tblPr = _make_element(_wt("tblPr"))
        if style:
            tblStyle = etree.SubElement(tblPr, _wt("tblStyle"))
            tblStyle.set(_wt("val"), style)
        tblW = etree.SubElement(tblPr, _wt("tblW"))
        tblW.set(_wt("w"), "5000")  # 100%
        tblW.set(_wt("type"), "pct")
        if not style:
            tblBorders = etree.SubElement(tblPr, _wt("tblBorders"))
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                b = etree.SubElement(tblBorders, _wt(side))
                b.set(_wt("val"), "single")
                b.set(_wt("sz"), "4")
                b.set(_wt("space"), "0")
                b.set(_wt("color"), "auto")
        tbl.append(tblPr)

        # tblGrid（列宽平均分配）
        tblGrid = _make_element(_wt("tblGrid"))
        for _ in range(cols):
            gridCol = etree.SubElement(tblGrid, _wt("gridCol"))
            gridCol.set(_wt("w"), str(int(9000 / cols)))
        tbl.append(tblGrid)

        # 行
        for r_idx in range(rows):
            tr = _make_element(_wt("tr"))
            for c_idx in range(cols):
                tc = _make_element(_wt("tc"))
                tcPr = _make_element(_wt("tcPr"))
                tcW = etree.SubElement(tcPr, _wt("tcW"))
                tcW.set(_wt("w"), str(int(5000 / cols)))
                tcW.set(_wt("type"), "pct")

                # 表头背景色
                if header and r_idx == 0 and header_fill:
                    rgb = to_rgb(header_fill)
                    shd = etree.SubElement(tcPr, _wt("shd"))
                    shd.set(_wt("val"), "clear")
                    shd.set(_wt("color"), "auto")
                    shd.set(_wt("fill"),
                            f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")
                tc.append(tcPr)

                # 段落
                value = ""
                if data and r_idx < len(data) and c_idx < len(data[r_idx]):
                    raw = data[r_idx][c_idx]
                    value = str(raw) if raw is not None else ""

                p = _make_element(_wt("p"))
                if value:
                    bold_flag = True if (header and r_idx == 0) else None
                    cell_color = "FFFFFF" if (header and r_idx == 0 and header_fill) else None
                    r = _make_run(value, bold=bold_flag, color=cell_color)
                    p.append(r)
                tc.append(p)
                tr.append(tc)
                tbl.append(tr)

        _insert_before_sectpr(self._body, tbl)
        # 表格后必须有空段落（OOXML 规范）
        _insert_before_sectpr(self._body, _make_element(_wt("p")))
        return _WordTable(rows, cols, self, tbl)

    # ---- 图片 ----

    def add_image(self, path: str, *, width=None, height=None,
                  alignment: str = None, alt_text: str = None,
                  keep_ratio: bool = True) -> _WordPicture:
        """加图片到 body 末尾（PNG/JPG/JPEG/GIF/BMP，**不支持 SVG**）。详细 help("add_image")。

        Args: path 图片路径；width 宽度（"15cm"/"150px"/"5in"）；height 高度；alignment 对齐；alt_text 替代文本；keep_ratio 按比例缩放（默认 True）。
        Returns: _WordPicture。
        Raises: 文件不存在 / 不支持的扩展名抛 OfficeDocError。
        Note: 必须在 save() 前调用；相同内容（md5 一致）自动去重复用同一 rid/docPr。
        """
        if not Path(path).exists():
            raise OfficeDocError(f"图片不存在: {path}")

        ext = Path(path).suffix.lower().lstrip(".")
        if ext not in _VALID_IMAGE_EXTS:
            raise OfficeDocError(
                f"不支持的图片格式: .{ext}\n"
                f"支持: png, jpg, jpeg, gif, bmp\n"
                f"SVG 暂不支持（Word 实际渲染需要 VML 兼容层）"
            )

        width_emu, height_emu = self._calc_image_size(path, width, height, keep_ratio)

        # 按 md5 去重
        with open(path, "rb") as f:
            content_hash = md5(f.read()).hexdigest()

        rid = None
        media_target = None
        for existing_rid, existing_src, existing_target, existing_hash in self._media_files:
            if existing_hash == content_hash:
                rid = existing_rid
                media_target = existing_target
                break

        if rid is None:
            rid = f"rId{self._next_rid}"
            self._next_rid += 1
            media_target = f"media/image_{rid}.{ext}"
            self._media_files.append((rid, path, media_target, content_hash))

        # 构建 w:p > w:r > w:drawing > wp:inline > ...
        p = _make_element(_wt("p"))
        if alignment:
            pPr = _make_element(_wt("pPr"))
            jc = etree.SubElement(pPr, _wt("jc"))
            jc.set(_wt("val"), _normalize_alignment(alignment))
            p.append(pPr)

        r = etree.SubElement(p, _wt("r"))
        drawing = etree.SubElement(r, _wt("drawing"))

        alt = alt_text or f"Image {Path(path).name}"
        alt_escaped = _xml_escape(alt)

        # 用 hash 末 4 位做唯一 id（避免 docPr id 冲突）
        docpr_id = abs(hash(content_hash)) % 100000 + 1

        inline_xml = (
            f'<wp:inline xmlns:wp="{WP_NS}" '
            f'distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{width_emu}" cy="{height_emu}"/>'
            f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:docPr id="{docpr_id}" name="Picture {alt_escaped}" descr="{alt_escaped}"/>'
            f'<wp:cNvGraphicFramePr>'
            f'<a:graphicFrameLocks xmlns:a="{A_NS}" noChangeAspect="1"/>'
            f'</wp:cNvGraphicFramePr>'
            f'<a:graphic xmlns:a="{A_NS}">'
            f'<a:graphicData uri="{PIC_NS}">'
            f'<pic:pic xmlns:pic="{PIC_NS}">'
            f'<pic:nvPicPr>'
            f'<pic:cNvPr id="{docpr_id}" name="{alt_escaped}" descr="{alt_escaped}"/>'
            f'<pic:cNvPicPr/>'
            f'</pic:nvPicPr>'
            f'<pic:blipFill>'
            f'<a:blip xmlns:r="{R_NS}" r:embed="{rid}"/>'
            f'<a:stretch><a:fillRect/></a:stretch>'
            f'</pic:blipFill>'
            f'<pic:spPr>'
            f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'</pic:spPr>'
            f'</pic:pic>'
            f'</a:graphicData>'
            f'</a:graphic>'
            f'</wp:inline>'
        )
        inline = etree.fromstring(inline_xml)
        drawing.append(inline)

        _insert_before_sectpr(self._body, p)

        return _WordPicture(path, self, drawing)

    def _calc_image_size(self, path: str, width, height, keep_ratio: bool):
        """计算图片 EMU 尺寸，支持自动保持比例（默认宽 ~3.5cm）."""
        DEFAULT_W_EMU = 4500000  # ~3.5cm

        if width and height:
            return _to_emu(width), _to_emu(height)

        orig_w_emu = orig_h_emu = None
        try:
            from PIL import Image
            with Image.open(path) as im:
                px_w, px_h = im.size
                orig_w_emu = int(px_w * 914400 / 96)
                orig_h_emu = int(px_h * 914400 / 96)
        except ImportError:
            pass
        except Exception:
            pass

        if width:
            w_emu = _to_emu(width)
            if keep_ratio and orig_w_emu and orig_h_emu:
                ratio = orig_h_emu / orig_w_emu
                return w_emu, int(w_emu * ratio)
            return w_emu, DEFAULT_W_EMU

        if height:
            h_emu = _to_emu(height)
            if keep_ratio and orig_w_emu and orig_h_emu:
                ratio = orig_w_emu / orig_h_emu
                return int(h_emu * ratio), h_emu
            return DEFAULT_W_EMU, h_emu

        if orig_w_emu and orig_h_emu:
            max_w_emu = _to_emu("15cm")
            if orig_w_emu > max_w_emu:
                ratio = max_w_emu / orig_w_emu
                return max_w_emu, int(orig_h_emu * ratio)
            return orig_w_emu, orig_h_emu

        return DEFAULT_W_EMU, DEFAULT_W_EMU

    # ---- 读取 ----

    def get_text(self) -> str:
        """全文文字（含表格，按出现顺序拼接，表格单元格用 \\t 分隔）。详细 help("get_text")。

        Returns: 段落文字按换行符拼接的字符串。
        """
        parts = []
        for child in self._body:
            if child.tag == _wt("p"):
                parts.append(_para_text(child))
            elif child.tag == _wt("tbl"):
                # 表格：每行单元格用 \t 拼接
                for tr in child.findall(_wt("tr")):
                    row = []
                    for tc in tr.findall(_wt("tc")):
                        cell_text = "\n".join(
                            _para_text(p) for p in tc.findall(_wt("p"))
                        )
                        row.append(cell_text)
                    parts.append("\t".join(row))
            # sectPr 跳过
        return "\n".join(parts)

    def get_paragraphs(self) -> list:
        """段落列表（含表格和占位空段，OOXML 规范）。详细 help("get_paragraphs")。

        Returns: list[dict]——段落 {"index", "text", "style"}；表格 {"index", "type": "table", "rows"}；0-based index 与 set_paragraph/remove_paragraph 一致。
        """
        result = []
        idx = 0
        for child in self._body:
            if child.tag == _wt("sectPr"):
                continue
            if child.tag == _wt("p"):
                result.append({
                    "index": idx,
                    "text": _para_text(child),
                    "style": _para_style(child),
                })
            elif child.tag == _wt("tbl"):
                result.append({
                    "index": idx,
                    "type": "table",
                    "rows": len(child.findall(_wt("tr"))),
                })
            idx += 1
        return result

    def get_tables(self) -> List[List[List[str]]]:
        """所有顶层表格内容（不含嵌套表格）。详细 help("get_tables")。

        Returns: list[list[list[str]]]——外层=表格列表，中层=行，内层=单元格文字（多段用 \\n 拼接）。
        """
        result = []
        for tbl in self._body.findall(_wt("tbl")):
            table_data = []
            for tr in tbl.findall(_wt("tr")):
                row = []
                for tc in tr.findall(_wt("tc")):
                    cell_text = "\n".join(
                        _para_text(p) for p in tc.findall(_wt("p"))
                    )
                    row.append(cell_text)
                table_data.append(row)
            result.append(table_data)
        return result

    # ---- 修改 ----

    def set_paragraph(self, index: int, text: str = None, **format_kwargs):
        """改第 N 行（0-based）。详细 help("set_paragraph")。

        Args: index 段落索引；text 新文字（None=保留原文字，仅改格式）；**format_kwargs 格式参数（bold/italic/font/font_size/color/alignment/style 等）。
        Raises: index 越界 / index 指向表格抛 OfficeDocError。
        Note: 改 text 时会把段落所有 run 合并为一个新 run，保留第一个 run 的 rPr 样式。
        """
        children = _body_children(self._body)
        if index < 0 or index >= len(children):
            raise OfficeDocError(
                f"段落索引超出范围: {index}（共 {len(children)} 个段落/表格）"
            )
        target = children[index]
        if target.tag != _wt("p"):
            raise OfficeDocError(f"索引 {index} 是表格，不是段落")

        para = _WordParagraph(_para_text(target), self, target)
        if text is not None:
            para.set_text(text)
        if format_kwargs:
            para.set_format(**format_kwargs)

    def remove_paragraph(self, index: int):
        """删第 N 行（0-based）。详细 help("remove_paragraph")。

        Args: index 段落索引。
        Raises: index 越界抛 OfficeDocError。
        """
        children = _body_children(self._body)
        if index < 0 or index >= len(children):
            raise OfficeDocError(
                f"段落索引超出范围: {index}（共 {len(children)} 个段落/表格）"
            )
        target = children[index]
        self._body.remove(target)

    def replace_text(self, find: str, replace: str,
                     replace_all: bool = True, regex: bool = False) -> int:
        """全文查找替换（含表格）。详细 help("replace_text")。

        Args: find 查找串（regex=True 时视为正则）；replace 替换串；replace_all 替换全部（默认 True）；regex 是否正则（默认 False）。
        Returns: 替换次数。
        """
        pattern = re.compile(find if regex else re.escape(find))
        count = 0
        done = False

        for p in self._body.iter(_wt("p")):
            if done:
                break
            runs = p.findall(_wt("r"))
            full_text = _para_text(p)
            if not pattern.search(full_text):
                continue

            if regex:
                n = len(pattern.findall(full_text))
                if n == 0:
                    continue
                new_text = pattern.sub(replace, full_text)
            else:
                n = full_text.count(find)
                if n == 0:
                    continue
                new_text = full_text.replace(find, replace)

            first_rPr_copy = deepcopy(runs[0].find(_wt("rPr"))) if runs else None
            for r in runs:
                p.remove(r)
            new_r = _make_run(new_text)
            if first_rPr_copy is not None:
                new_r.insert(0, first_rPr_copy)
            p.append(new_r)

            if replace_all:
                count += n
            else:
                count += 1
                done = True

        return count


# ============================================================================
# 公共辅助函数
# ============================================================================

def path_to_work(sandbox_path: str) -> str:
    """沙盒 `/work/xxx` → 主进程 `cached/{sid}/xxx` 相对路径。详细 help("path_to_work")。

    Args: sandbox_path 沙盒内绝对路径（如 `/work/data.xlsx`）或其他字符串。
    Returns: 去掉 `/work/` 前缀的相对路径；非 `/work/` 开头的输入原样返回。
    """
    p = Path(sandbox_path)
    if p.is_absolute() and str(p).startswith("/work/"):
        return str(p.relative_to("/work"))
    return sandbox_path


def version_info() -> dict:
    """返回底层依赖版本（诊断用）。详细 help("version_info")。

    Returns: dict key=库名 value=版本字符串；库未装时 value="NOT INSTALLED"。
    """
    out = {}
    for lib in ("lxml",):
        try:
            m = __import__(lib)
            out[lib] = getattr(m, "__version__", "?")
        except ImportError:
            out[lib] = "NOT INSTALLED"
    return out


# ============================================================================
# help() / doc() —— AI 按需查函数详细用法
# ============================================================================

def doc(name=None):
    """查询本 skill 的函数 / 类 / 方法 docstring。详细 help("doc")。

    用法:
        from skills.WordEditor import help
        help()                       # 全部函数 / 类签名
        help("WordDoc")              # WordDoc 类详情 + 方法列表
        help("WordDoc.add_table")    # 单个方法详细用法
    """
    from skills._shared._skill_help import skill_help
    return skill_help(sys.modules[__name__], name)


def help(name=None):
    """doc() 别名。"""
    return doc(name)


# 自动给所有函数挂 .help 属性
auto_attach_help_module(sys.modules[__name__])