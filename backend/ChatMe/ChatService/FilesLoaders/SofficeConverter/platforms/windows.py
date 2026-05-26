"""
Windows 平台 soffice 实现
"""

import os
import shutil
from .base import BasePlatform


class WindowsPlatform(BasePlatform):
    name = "windows"

    SOFFICE_CANDIDATES = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]

    def find_soffice(self) -> str | None:
        path = shutil.which("soffice.exe")
        if path:
            return path

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