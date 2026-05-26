"""
macOS (Darwin) 平台 soffice 实现
"""

import os
import shutil
from .base import BasePlatform


class DarwinPlatform(BasePlatform):
    name = "darwin"

    SOFFICE_CANDIDATES = [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]

    def find_soffice(self) -> str | None:
        # 1. PATH 中查找
        path = shutil.which("soffice")
        if path:
            return path

        # 2. 常见路径
        for candidate in self.SOFFICE_CANDIDATES:
            if os.path.exists(candidate):
                return candidate

        return None

    def build_command(
        self,
        soffice_path: str,
        input_path: str,
        output_format: str,
        output_dir: str,
    ) -> list[str]:
        return [
            soffice_path,
            "--headless",
            "--convert-to", output_format,
            "--outdir", output_dir,
            input_path,
        ]