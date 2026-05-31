"""
数据分析技能规范模块
- 提供在数据分析目录下操作所需要进行的*操作规范*
- 提供数据分析所需要相关的*配置规范*
"""
import fcntl
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ChatMe.ChatMeConfig import get_oss_config
from ChatMe.LoggingManager.logging_config import get_logger


class ChatDataAnalysisFormat:
    """
    数据分析执行配置规范类
    """


    def __init__(self, session_id: str):
        """
        初始化数据分析配置

        Args:
            session_id: 会话 ID，用于组织输出目录
        """
        self.logger = get_logger("ChatDataAnalysisFormat")
        self.session_id = session_id
        self._base_dir: Optional[str] = None

    # --------------------------------------------------------
    # 配置规范
    # --------------------------------------------------------

    @property
    def base_dir(self) -> str:
        """获取输出根目录"""
        if self._base_dir is None:
            backend_dir = Path.cwd() / "cached"
            self._base_dir = os.path.join(backend_dir, self.session_id, "data_analysis_output")
        return self._base_dir

    @property
    def meta_path(self) -> str:
        return os.path.join(self.base_dir, "_meta.json")

    def new_generation(self) -> str:
        """
        开启新的一次分析调用，返回 generation_id

        Returns:
            "gen_001", "gen_002" ...
        """
        os.makedirs(self.base_dir, exist_ok=True)

        with open(self.meta_path, "a+") as f:
            # 文件锁，防止并发自增
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                if content:
                    meta = json.loads(content)
                    gen = meta.get("generation", 0) + 1
                else:
                    gen = 1

                # 写入新值
                f.seek(0)
                f.truncate()
                json.dump({"generation": gen}, f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        return f"gen_{gen:03d}"

    def get_current_generation_dir(self) -> str:
        return os.path.join(self.base_dir, self.new_generation())

    @staticmethod
    def get_file_dir(path: str | Path) -> Path:
        """
        获取文件的路径

        规则:
        - 路径存在：直接返回
        - 路径不存在：在 backend/cached/ 下递归搜索文件名

        Args:
            path: 文件路径（绝对路径或文件名）

        Returns:
            文件路径
        """
        if isinstance(path, str):
            path = Path(path)

        if path.exists():
            return path

        # 路径不存在，递归搜索文件名
        filename = path.name
        backend_dir = Path.cwd() / "cached"

        for match in backend_dir.rglob(filename):
            return match

        raise FileNotFoundError(f"找不到文件: {filename}")


    # --------------------------------------------------------
    # 操作规范
    # --------------------------------------------------------

    def remove_dir(self, generation: str):
        """
        删除操作规范

        Params:
           generation(示例："gen_001" / "gen_002")
        """
        remove_generated_dir = Path(self._base_dir) / generation
        if Path.exists(remove_generated_dir):
            os.remove(remove_generated_dir)
            self.logger.info(f"成功删除{self.session_id}下{generation}批次数学分析结果")
        else:
            self.logger.warning(f"不存在{self.session_id}下{generation}批次数学分析结果")


    def upload_generated_result_to_oss(self, path: str | Path):
        if isinstance(path, str):
            path = Path(path)

        try:
            import oss2

            oss_cfg = get_oss_config()
            access_key_id = oss_cfg.get("access_key_id")
            access_key_secret = oss_cfg.get("access_key_secret")
            bucket_name = oss_cfg.get("bucket")
            endpoint = oss_cfg.get("endpoint")

            if not all([access_key_id, access_key_secret, bucket_name, endpoint]):
                self.logger.warning(f"OSS 配置不完整，跳过上传: {path}")
                return None

            # 生成 OSS key：chatme/{年份月份}/{uuid}_{原文件名}
            date_prefix = datetime.now().strftime("%Y-%m")
            filename = path.name or os.path.basename(path)
            oss_key = f"chatme/{date_prefix}/{uuid.uuid4().hex[:4]}_{filename}"

            # 上传到 OSS
            auth = oss2.Auth(access_key_id, access_key_secret)
            bucket = oss2.Bucket(auth, endpoint, bucket_name)
            bucket.put_object_from_file(oss_key, str(path))

            # 返回 OSS URL
            oss_url = f"https://{bucket_name}.{endpoint.replace('https://', '')}/{oss_key}"
            self.logger.info(f"文件上传 OSS 成功: {path} -> {oss_url}")
            return oss_url

        except ImportError:
            self.logger.warning(f"oss2 模块未安装，无法上传到 OSS: {path}")
            return None
        except Exception as e:
            self.logger.warning(f"上传图片到 OSS 失败: {path}, 错误: {e}")
            return None

    # --------------------------------------------------------
    # 全局配置汇总
    # --------------------------------------------------------

    def get_config(self) -> dict:
        """
        获取完整的配置字典

        Returns:
            包含所有路径和默认配置的字典
        """
        return {
            "output_dir": self.get_current_generation_dir()
        }