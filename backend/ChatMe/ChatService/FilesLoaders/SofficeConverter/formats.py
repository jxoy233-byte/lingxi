"""
Office 文档格式转换映射配置
格式：旧后缀 → (新后缀, 文档类别)
"""

FORMAT_MAP = {
    ".doc": ("docx", "document"),
    ".ppt": ("pptx", "presentation"),
    ".xls": ("xlsx", "spreadsheet"),
}

SUPPORTED_OLD_FORMATS = set(FORMAT_MAP.keys())
SUPPORTED_NEW_FORMATS = {v[0] for v in FORMAT_MAP.values()}


def get_target_format(old_suffix: str) -> str | None:
    """根据旧后缀获取目标格式"""
    info = FORMAT_MAP.get(old_suffix.lower())
    return info[0] if info else None


def get_doc_type(old_suffix: str) -> str | None:
    """根据旧后缀获取文档类型"""
    info = FORMAT_MAP.get(old_suffix.lower())
    return info[1] if info else None