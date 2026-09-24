"""
LLM 实例懒加载工厂。

设计目标：
- 用户改 config.json 后无需重启后端，下次调用即生效
- 5 个工作流角色（llm_core / agent_llm / summary_llm / react_compact_llm /
  llm_imp_ipt / should_end_llm）共享同一个 ChatOpenAI 实例（连接三元组相同）
- VL 模型独立 cache（除非 vl.local=False fallback 到主模型）
- cache key = (role, api_key_fp, base_url, model_name)
  - 任一字段改 → cache miss → 自动 new 一个新实例

为什么 temperature / max_tokens 不进 cache key：
这些是 per-角色调优参数（来自 env var），构造 ChatOpenAI 时传一次，
不会随 config.json 变化。

为什么用 WeakValueDictionary 而不是 lru_cache：
旧的 fingerprint 不会自然从 lru_cache 淘汰（如果 maxsize 够大会一直占着）；
WeakValueDictionary 让失去强引用的实例立刻被 GC → httpx 连接池跟着释放。

参见：CLAUDE.md 关于"config.json 改动不重启后端"的偏好。
"""
import hashlib
import logging
from typing import Optional
from weakref import WeakValueDictionary

from langchain_openai import ChatOpenAI

from ChatMe.ChatMeConfig import config


logger = logging.getLogger(__name__)


# 主 LLM + VL 各一份；用 role 区分避免 key 撞
# vl.local=False 时由 ChatMeConfig._resolve_vl_fallback 把连接三元组覆盖成主模型，
# 此时 key 自然一致，复用主实例
_cache: "WeakValueDictionary[tuple, ChatOpenAI]" = WeakValueDictionary()


def _fp(api_key: str) -> str:
    """api_key 的短 fingerprint（16 字符 sha1）。key 变 → fp 变 → cache miss。"""
    return hashlib.sha1((api_key or "").encode("utf-8")).hexdigest()[:16]


def _make_key(role: str, cfg: dict) -> tuple:
    return (
        role,
        _fp(cfg.get("api_key", "")),
        cfg.get("base_url", ""),
        cfg.get("model_name", ""),
    )


def get_llm(role: str = "main", cfg: Optional[dict] = None) -> ChatOpenAI:
    """
    拿 (role, 连接三元组) 对应的 ChatOpenAI 实例。cache miss → 自动 new。

    role:
      - "main":  5 个工作流角色共享的 LLM（连接三元组相同）
      - "vl":    视觉模型（独立 base_url/api_key/model_name）

    cfg: 传入则跳过 config.get_*_config()（用于测试 / 显式 override）
    """
    if cfg is None:
        if role == "vl":
            cfg = config.get_model_vl_config()
        else:
            cfg = config.get_active_llm_config()

    if not cfg or not cfg.get("api_key") or not cfg.get("model_name"):
        raise RuntimeError(
            f"role={role} 的 LLM 配置不完整："
            f"model_name={cfg.get('model_name')!r} "
            f"base_url={cfg.get('base_url')!r}"
        )

    key = _make_key(role, cfg)
    llm = _cache.get(key)
    if llm is not None:
        return llm

    # cache miss → new 一个 ChatOpenAI
    llm = ChatOpenAI(
        model=cfg["model_name"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
    )
    _cache[key] = llm
    logger.info(
        f"[llm_factory] new ChatOpenAI role={role} model={cfg['model_name']}"
    )
    return llm


def invalidate_for_providers(old_providers: dict, new_providers: dict) -> int:
    """
    config.json 改动后清掉旧 key 对应的实例（让旧实例失去强引用 → GC 释放连接池）。
    返回清掉的实例数量（仅供日志）。
    """
    old_providers = old_providers or {}
    new_providers = new_providers or {}
    cleared = 0

    # 主 LLM 角色：所有非 vl、非 active 的 provider
    names = (set(old_providers.keys()) | set(new_providers.keys())) - {"vl", "active"}
    for name in names:
        old_cfg = old_providers.get(name, {}) or {}
        new_cfg = new_providers.get(name, {}) or {}
        old_key = _make_key("main", old_cfg) if old_cfg.get("api_key") else None
        new_key = _make_key("main", new_cfg) if new_cfg.get("api_key") else None
        if old_key and old_key != new_key and _cache.pop(old_key, None) is not None:
            cleared += 1

    # VL 角色
    old_vl = old_providers.get("vl", {}) or {}
    new_vl = new_providers.get("vl", {}) or {}
    old_vl_key = _make_key("vl", old_vl) if old_vl.get("api_key") else None
    new_vl_key = _make_key("vl", new_vl) if new_vl.get("api_key") else None
    if old_vl_key and old_vl_key != new_vl_key:
        if _cache.pop(old_vl_key, None) is not None:
            cleared += 1

    # active 字段变化可能让 get_active_llm_config() 返不同 provider —— 但 cache
    # key 只看连接三元组，三元组没变就不需要清。如果 active 切换导致返的 provider
    # 变了（chain 里不同 name），上面 names 循环已经覆盖。
    return cleared


def reset():
    """清空所有缓存（测试用 / 手动重启时）。"""
    _cache.clear()


def cache_info() -> dict:
    """返回 cache 当前状态（供 /admin/llm/cache-info 端点调试用）。"""
    return {
        "size": len(_cache),
        "roles": sorted({k[0] for k in _cache.keys()}),
    }