"""
平台基类 - 所有平台实现需继承此类
"""

from abc import ABC, abstractmethod
import os
from typing import Optional


class BasePlatform(ABC):
    """soffice 路径查找和命令执行抽象"""

    name: str  # 平台名称

    @abstractmethod
    def find_soffice(self) -> Optional[str]:
        """查找 soffice 可执行文件路径"""
        pass

    @abstractmethod
    def build_command(
        self,
        soffice_path: str,
        input_path: str,
        output_format: str,
        output_dir: str,
    ) -> list[str]:
        """构建转换命令"""
        pass

    def validate_env(self) -> bool:
        """验证环境是否可用"""
        path = self.find_soffice()
        if not path or not os.path.exists(path):
            return False
        return os.access(path, os.X_OK) or os.name == 'nt'