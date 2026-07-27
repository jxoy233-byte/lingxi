"""
ChatMe 全局配置加载器
"""
from .core import (
    config,
    ChatMeConfig,
    get_config,
    get_mcp_config,
    get_redis_checkpointer_url,
    get_redis_state_saver_url,
    get_app_config,
    get_model_vl_config,
    get_oss_config,
    get_skills_config,
    ensure_global_config,
    # 主用 / 备用 LLM 链式解析
    get_active_llm_config,
    get_backup_llm_config,
    get_llm_providers_chain,
    is_provider_valid,
    # 端到端自检（实际通过 ChatOpenAI 调用验证）
    probe_llm_config,
    self_check_llm,
)

__all__ = [
    "config",
    "ChatMeConfig",
    "get_config",
    "get_mcp_config",
    "get_redis_checkpointer_url",
    "get_redis_state_saver_url",
    "get_app_config",
    "get_model_vl_config",
    "get_oss_config",
    "get_skills_config",
    "ensure_global_config",
    "get_active_llm_config",
    "get_backup_llm_config",
    "get_llm_providers_chain",
    "is_provider_valid",
    "probe_llm_config",
    "self_check_llm",
]
