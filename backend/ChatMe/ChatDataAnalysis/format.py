"""
数据分析技能规范模块
- 提供在数据分析目录下操作所需要进行的*操作规范*
- 提供数据分析所需要相关的*配置规范*
"""
import fcntl
import json
import os
import shutil
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
        self._generation: Optional[str] = None

    @property
    def generation(self) -> str:
        """获取当前 generation，懒加载初始化"""
        if self._generation is None:
            self._generation = self.new_generation()
        return self._generation

    @generation.setter
    def generation(self, value: str):
        self._generation = value

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
        return os.path.join(self.base_dir, self.generation)

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
        删除指定 generation 的分析结果目录

        Args:
           generation: generation ID (示例："gen_001" / "gen_002")
        """
        remove_generated_dir = Path(self.base_dir) / generation
        if remove_generated_dir.exists():
            shutil.rmtree(remove_generated_dir)
            self.logger.info(f"成功删除 {self.session_id} 下 {generation} 批次数据分析结果")
        else:
            self.logger.warning(f"不存在 {self.session_id} 下 {generation} 批次数据分析结果")


    def upload_result_to_oss(self, path: str | Path) -> Optional[str]:
        """
        上传数据分析结果到 OSS

        OSS key 格式: chatme/{session_id}/{generation}/{filename}
        与本地 cached 目录结构保持一致

        Args:
            path: 本地文件路径

        Returns:
            OSS URL 字符串，失败返回 None
        """
        if isinstance(path, str):
            path = Path(path)

        try:
            import oss2

            oss_cfg = get_oss_config()
            if not all([oss_cfg.get("access_key_id"), oss_cfg.get("access_key_secret"),
                        oss_cfg.get("bucket"), oss_cfg.get("endpoint")]):
                self.logger.warning(f"OSS 配置不完整，跳过上传: {path}")
                return None

            # 解析 path 提取 generation
            # path 格式: cached/{session_id}/data_analysis_output/{generation}/charts/xxx.png
            parts = Path(path).parts
            generation = "unknown"
            if "data_analysis_output" in parts:
                idx = parts.index("data_analysis_output")
                if idx + 1 < len(parts):
                    generation = parts[idx + 1]

            filename = path.name
            oss_key = f"chatme/{self.session_id}/{generation}/{filename}"

            # 上传到 OSS
            auth = oss2.Auth(oss_cfg["access_key_id"], oss_cfg["access_key_secret"])
            bucket = oss2.Bucket(auth, oss_cfg["endpoint"], oss_cfg["bucket"])
            bucket.put_object_from_file(oss_key, str(path))

            # 返回 OSS URL
            bucket_name = oss_cfg["bucket"]
            endpoint = oss_cfg["endpoint"]
            oss_url = f"https://{bucket_name}.{endpoint.replace('https://', '')}/{oss_key}"
            self.logger.info(f"文件上传 OSS 成功: {path} -> {oss_url}")
            return oss_url

        except ImportError:
            self.logger.warning(f"oss2 模块未安装，无法上传到 OSS: {path}")
            return None
        except Exception as e:
            self.logger.warning(f"上传文件到 OSS 失败: {path}, 错误: {e}")
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