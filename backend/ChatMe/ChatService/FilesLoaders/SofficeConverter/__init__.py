"""
SofficeConverter - LibreOffice 跨平台文档格式转换模块

使用方式:
    from SofficeConverter import SofficeConverter, get_converter

    converter = SofficeConverter()
    if converter.is_available():
        new_path = converter.convert("/path/to/file.doc")
"""

from .core import (
    SofficeConverter,
    LibreOfficeNotFoundError,
    ConversionError,
    get_converter,
)
from .formats import FORMAT_MAP, get_target_format, get_doc_type

__all__ = [
    "SofficeConverter",
    "LibreOfficeNotFoundError",
    "ConversionError",
    "get_converter",
    "FORMAT_MAP",
    "get_target_format",
    "get_doc_type",
]