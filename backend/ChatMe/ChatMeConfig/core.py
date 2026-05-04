"""
ChatMe 全局配置加载器
优先从 .chatme/config.json 读取配置，不存在则回退到环境变量
"""
import os
import json
from pathlib import Path
from typing import Any, Optional


class ChatMeConfig:
    """全局配置单例类"""

    _instance: Optional["ChatMeConfig"] = None
    _config: dict = {}
    _loaded: bool = False

    def __new__(cls) -> "ChatMeConfig":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _find_config_file(self) -> Path:
        """查找配置文件路径"""
        search_paths = [
            Path.cwd() / ".chatme" / "config.json",
            Path(__file__).parent.parent / ".chatme" / "config.json",
        ]
        for path in search_paths:
            if path.exists():
                return path
        return search_paths[0]

    def _load(self) -> None:
        """加载配置"""
        if self._loaded:
            return

        config_file = self._find_config_file()

        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                self._loaded = True
                return
            except Exception as e:
                print(f"加载配置文件失败: {e}")

        self._config = {}
        self._loaded = True

    def get(self, key: str, default: Any = None, fallback_env: str = None) -> Any:
        """
        获取配置值
        优先级：config.json > 环境变量 > default
        """
        self._load()

        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                value = None
                break

        if value is not None and (value != "" or default is not None):
            return value

        if fallback_env:
            return os.getenv(fallback_env, default)

        return default

    def get_llm_config(self, provider: str = "openai") -> dict:
        """获取 LLM 配置"""
        self._load()

        provider_config = self.get(f"llm_providers.{provider}", {})

        # 核心参数优先从 config.json 获取，失败则回退到环境变量
        result = {}
        for key in ["model_name", "api_key", "base_url"]:
            config_value = provider_config.get(key, "") if isinstance(provider_config, dict) else ""
            env_value = os.getenv(f"{provider.upper()}_{key.upper()}", None)

            if config_value and config_value != "":
                result[key] = config_value
            elif env_value is not None:
                result[key] = env_value
            else:
                result[key] = None

        # 其他参数（temperature, max_tokens 等）直接从环境变量获取
        for key in ["temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"]:
            env_value = os.getenv(f"{provider.upper()}_{key.upper()}", None)
            if env_value is not None:
                try:
                    result[key] = float(env_value)
                except (ValueError, TypeError):
                    result[key] = env_value
            else:
                result[key] = None

        return result

    def get_app_config(self) -> dict:
        """获取app配置"""
        return {
            "name": self.get("app.name"),
            "version": self.get("app.version"),
            "description": self.get("app.description"),
            "host": self.get("app.host", fallback_env="APP_HOST"),
            "port": self.get("app.port", fallback_env="APP_PORT"),
        }

    def get_model_vl_config(self) -> dict:
        """获取 VL 模型配置"""
        self._load()

        provider_config = self.get("llm_providers.vl", {})

        result = {}
        for key in ["model_name", "api_key", "base_url"]:
            config_value = provider_config.get(key, "") if isinstance(provider_config, dict) else ""
            env_value = os.getenv(f"VL_{key.upper()}", None)

            if config_value and config_value != "":
                result[key] = config_value
            elif env_value is not None:
                result[key] = env_value
            else:
                result[key] = None

        for key in ["temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"]:
            env_value = os.getenv(f"VL_{key.upper()}", None)
            if env_value is not None:
                try:
                    result[key] = float(env_value)
                except (ValueError, TypeError):
                    result[key] = env_value
            else:
                result[key] = None

        return result

    def get_mcp_config(self) -> dict:
        """获取 MCP 服务器配置"""
        return {
            "url": self.get("mcp_server.url", fallback_env="MCP_SERVER_URL"),
            "transport": self.get("mcp_server.transport", fallback_env="MCP_TRANSPORT"),
        }

    def get_redis_checkpointer_url(self) -> str:
        """获取 Redis checkpointer URL"""
        return self.get("redis.checkpointer_url", fallback_env="REDIS_CHECKPOINTER_URL")

    def get_redis_state_saver_url(self) -> str:
        """获取 Redis state saver URL"""
        return self.get("redis.state_saver_url", fallback_env="REDIS_STATE_SAVER_URL")

    def get_directory(self, name: str) -> str:
        """获取目录配置"""
        return self.get(f"directories.{name}", fallback_env=f"{name.upper()}_DIR")

    def get_oss_config(self) -> dict:
        """获取 OSS 配置"""
        return {
            "access_key_id": self.get("oss.access_key_id", fallback_env="OSS_ACCESS_KEY_ID"),
            "access_key_secret": self.get("oss.access_key_secret", fallback_env="OSS_ACCESS_KEY_SECRET"),
            "bucket": self.get("oss.bucket", fallback_env="OSS_BUCKET"),
            "endpoint": self.get("oss.endpoint", fallback_env="OSS_ENDPOINT"),
            "region": self.get("oss.region", fallback_env="OSS_REGION"),
        }

    def get_oss_bucket(self) -> str:
        """获取 OSS bucket 名称"""
        return self.get("oss.bucket", fallback_env="OSS_BUCKET")

    def get_oss_endpoint(self) -> str:
        """获取 OSS endpoint"""
        return self.get("oss.endpoint", fallback_env="OSS_ENDPOINT")

    def get_oss_access_key_id(self) -> str:
        """获取 OSS AccessKeyId"""
        return self.get("oss.access_key_id", fallback_env="OSS_ACCESS_KEY_ID")

    def get_oss_access_key_secret(self) -> str:
        """获取 OSS AccessKeySecret"""
        return self.get("oss.access_key_secret", fallback_env="OSS_ACCESS_KEY_SECRET")

    @property
    def is_loaded(self) -> bool:
        """检查是否已加载配置"""
        return self._loaded


config = ChatMeConfig()


def get_config(key: str, default: Any = None, fallback_env: str = None) -> Any:
    """快捷获取配置"""
    return config.get(key, default, fallback_env)


def get_llm_config(provider: str = "openai") -> dict:
    """获取 LLM 配置"""
    return config.get_llm_config(provider)


def get_mcp_config() -> dict:
    """获取 MCP 配置"""
    return config.get_mcp_config()


def get_redis_checkpointer_url() -> str:
    """获取 Redis checkpointer URL"""
    return config.get_redis_checkpointer_url()


def get_redis_state_saver_url() -> str:
    """获取 Redis state saver URL"""
    return config.get_redis_state_saver_url()


def get_directory(name: str) -> str:
    """获取目录配置"""
    return config.get_directory(name)


def get_oss_config() -> dict:
    """获取 OSS 配置"""
    return config.get_oss_config()


def get_oss_bucket() -> str:
    """获取 OSS bucket 名称"""
    return config.get_oss_bucket()


def get_oss_endpoint() -> str:
    """获取 OSS endpoint"""
    return config.get_oss_endpoint()


def get_app_config() -> dict:
    """获取 app 配置"""
    return config.get_app_config()


def get_model_vl_config() -> dict:
    """获取 VL 模型配置"""
    return config.get_model_vl_config()
