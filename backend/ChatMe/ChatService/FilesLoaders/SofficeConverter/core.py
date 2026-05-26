"""
soffice 转换器核心实现
"""

import subprocess
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from .formats import FORMAT_MAP, get_target_format
from .platforms import get_current_platform, BasePlatform
from ChatMe.LoggingManager.logging_config import get_logger


class LibreOfficeNotFoundError(Exception):
    """LibreOffice 未安装或未在 PATH 中"""
    pass


class ConversionError(Exception):
    """文档转换失败"""
    pass


class SofficeConverter:
    """
    soffice 文档格式转换器

    使用方式:
        converter = SofficeConverter()
        new_path = converter.convert("/path/to/file.doc")  # → /path/to/file.docx
    """

    def __init__(self, timeout: int = 60, platform_impl: Optional[BasePlatform] = None):
        self.timeout = timeout
        self.logger = get_logger("SofficeConverter")
        self._platform = platform_impl or get_current_platform()
        self._soffice_path: Optional[str] = None

    @property
    def soffice_path(self) -> str:
        """延迟加载 soffice 路径"""
        if self._soffice_path is None:
            path = self._platform.find_soffice()
            if not path:
                raise LibreOfficeNotFoundError(
                    "未找到 LibreOffice soffice。"
                    "请安装 LibreOffice: https://www.libreoffice.org/download/download/"
                )
            self._soffice_path = path
        return self._soffice_path

    def is_available(self) -> bool:
        """检查 soffice 是否可用"""
        try:
            _ = self.soffice_path
            return True
        except LibreOfficeNotFoundError:
            return False

    def can_convert(self, suffix: str) -> bool:
        """检查后缀是否需要转换"""
        return suffix.lower() in FORMAT_MAP

    def get_target_suffix(self, suffix: str) -> str:
        """获取转换后的后缀"""
        target = get_target_format(suffix.lower())
        return f".{target}" if target else suffix

    def convert(self, file_path: str, cleanup: bool = True) -> str:
        """
        转换文档格式

        Args:
            file_path: 源文件路径 (.doc/.ppt/.xls)
            cleanup: 转换后是否删除源文件

        Returns:
            转换后的文件路径 (.docx/.pptx/.xlsx)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"源文件不存在: {file_path}")

        suffix = "." + file_path.rsplit(".", 1)[-1].lower()
        if not self.can_convert(suffix):
            return file_path  # 不需要转换

        target_format = get_target_format(suffix)
        output_dir = os.path.dirname(file_path)
        # 去掉原后缀得到纯 base_name（如 "报告.doc" → "报告"）
        pure_base = Path(file_path).stem.replace(suffix, "")
        # 生成简短随机 ID 避免中文路径问题
        short_id = uuid.uuid4().hex[:4]

        # 临时文件：纯 base_name + short_id + 原后缀（让 soffice 转换输出为 base_name.docx）
        temp_base_name = f"{pure_base}_{short_id}"
        temp_input = os.path.join(output_dir, temp_base_name + suffix)

        try:
            shutil.copy(file_path, temp_input)

            cmd = self._platform.build_command(
                self.soffice_path,
                temp_input,
                target_format,
                output_dir,
            )

            self.logger.debug(f"执行转换命令: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if result.returncode != 0:
                raise ConversionError(f"转换失败: {result.stderr}")

            # soffice 输出的文件路径：temp_input 的 stem 去掉后缀 + 新后缀
            target_path = os.path.join(output_dir, f"{temp_base_name}.{target_format}")

            if not os.path.exists(target_path):
                raise ConversionError(f"转换后文件未生成: {target_path}")

            self.logger.info(f"文档转换成功: {file_path} → {target_path}")
            return target_path

        finally:
            if cleanup and os.path.exists(temp_input):
                try:
                    os.remove(temp_input)
                except Exception:
                    pass

    def _prepare_temp_file(self, file_path: str, suffix: str) -> str:
        """准备临时文件（处理路径空格问题）"""
        output_dir = os.path.dirname(file_path)
        base_name = Path(file_path).stem
        temp_path = os.path.join(output_dir, f"_soffice_tmp_{base_name}{suffix}")

        try:
            shutil.copy(file_path, temp_path)
            return temp_path
        except Exception:
            return file_path  # 失败就用原路径


# 全局单例
_converter: Optional[SofficeConverter] = None


def get_converter() -> SofficeConverter:
    """获取全局转换器单例"""
    global _converter
    if _converter is None:
        _converter = SofficeConverter()
    return _converter