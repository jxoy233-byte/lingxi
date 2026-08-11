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

    def _get_global_config_dir(self) -> Path:
        """获取全局配置目录"""
        return Path.home() / ".chatme"

    def _find_config_file(self) -> Path:
        """查找配置文件路径
        优先级：局部 .chatme/config.json > 全局 CHATME_CONFIG_DIR 或 ~/.chatme/config.json
        """
        # 局部配置路径
        local_path = Path.cwd() / ".chatme" / "config.json"
        if local_path.exists():
            return local_path

        # 全局配置路径
        global_path = self._get_global_config_dir() / "config.json"
        if global_path.exists():
            return global_path

        # 都不存在，返回全局路径（用于生成）
        return global_path

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

        # config.json 不存在，自动生成
        self._generate_default_config(config_file)
        self._loaded = True

    def _generate_default_config(self, config_file: Path) -> None:
        """从环境变量生成默认配置文件"""
        config_file.parent.mkdir(parents=True, exist_ok=True)

        default_config = {
            "app": {
                "name": "ChatMe",
                "version": "v0.1.4",
                "description": "ChatMe LangGraph Workflow",
                "host": "127.0.0.1",
                "port": 8211,
            },
            "llm_providers": {
                "openai": {
                    "model_name": os.getenv("OPENAI_MODEL_NAME", ""),
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                }
            },
            "redis": {
                "checkpointer_url": "redis://:123456@localhost:6024/0",
                "state_saver_url": "redis://:123456@localhost:6024/1",
            },
            "oss": {
                "access_key_id": os.getenv("OSS_ACCESS_KEY_ID", ""),
                "access_key_secret": os.getenv("OSS_ACCESS_KEY_SECRET", ""),
                "bucket": os.getenv("OSS_BUCKET", ""),
                "endpoint": os.getenv("OSS_ENDPOINT", ""),
                "region": os.getenv("OSS_REGION", ""),
            },
            "permissions": {
                "approval_policy": "default",
                "approved_commands": [],
                "denied_commands": [],
            },
        }

        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            print(f"已自动生成配置文件: {config_file}")
        except Exception as e:
            print(f"生成配置文件失败: {e}")

        self._config = default_config

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

    # ========================================================================
    # 主用 / 备用 LLM 链式解析
    # ========================================================================

    @staticmethod
    def _is_provider_valid(provider_cfg) -> bool:
        """
        判断一个 provider 配置是否"完整可用"：
        - 必须是 dict
        - model_name / api_key / base_url 都存在且非空字符串
        """
        if not isinstance(provider_cfg, dict):
            return False
        for key in ("model_name", "api_key", "base_url"):
            v = provider_cfg.get(key)
            if v is None:
                return False
            if isinstance(v, str) and not v.strip():
                return False
        return True

    def get_llm_providers_chain(self) -> list:
        """
        按 config.json 中 llm_providers 的书写顺序，返回所有"有效"的业务 provider 列表
        （vl 单独走 get_model_vl_config，不在本链中）

        返回元素结构：
            {
                "name": "<provider 字段名>",
                "model_name": "...",
                "api_key": "...",
                "base_url": "...",
            }

        第一个 = 主用，第二个 = 备用，依此类推。
        """
        self._load()
        raw = self.get("llm_providers", {}) or {}
        chain = []
        for provider_name, provider_cfg in raw.items():
            # 跳过 vl（视觉语言模型走独立通道）
            if provider_name == "vl":
                continue
            if not self._is_provider_valid(provider_cfg):
                continue
            chain.append({
                "name": provider_name,
                "model_name": str(provider_cfg.get("model_name", "")).strip(),
                "api_key":    str(provider_cfg.get("api_key", "")).strip(),
                "base_url":   str(provider_cfg.get("base_url", "")).strip(),
            })
        return chain

    def get_active_llm_config(self) -> dict:
        """获取主用 LLM 配置（llm_providers 链中的第一个有效项）；空 dict 表示未配置"""
        chain = self.get_llm_providers_chain()
        return chain[0] if chain else {}

    def get_backup_llm_config(self) -> dict:
        """获取备用 LLM 配置（链中的第二个有效项）；空 dict 表示没有备用"""
        chain = self.get_llm_providers_chain()
        return chain[1] if len(chain) > 1 else {}

    # ========================================================================
    # 端到端自检：实际通过 ChatOpenAI 接口发一次最小请求来验证可用性
    # ========================================================================

    @staticmethod
    def probe_llm_config(cfg: dict, timeout: int = 10) -> tuple:
        """
        用 ChatOpenAI 实际调用一次最小请求（输入 "hi"，max_tokens=4），
        验证 cfg 是否能正常连通并返回。

        返回 (ok: bool, message: str)
        """
        if not cfg or not cfg.get("model_name"):
            return False, "配置为空或缺少 model_name"

        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            return False, "未安装 langchain_openai，跳过端到端自检"

        try:
            llm = ChatOpenAI(
                model=cfg.get("model_name"),
                api_key=cfg.get("api_key"),
                base_url=cfg.get("base_url"),
                timeout=timeout,
                max_tokens=512,
            )
            resp = llm.invoke("hi")
            content = getattr(resp, "content", None) or str(resp)
            return True, f"响应: {content[:60]!r}"
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:200]}"

    def self_check_llm(self, timeout: int = 10) -> dict:
        """
        对 llm_providers 链做端到端自检：
        1) 探测主用 → 成功则 active=primary
        2) 主用失败 → 探测备用 → 成功则 active=backup
        3) 都失败 → active=None

        返回结构：
            {
                "active": "<provider name>" | None,
                "primary": {"name": ..., "ok": bool, "msg": ...} | None,
                "backup":  {"name": ..., "ok": bool, "msg": ...} | None,
            }
        """
        chain = self.get_llm_providers_chain()
        result = {"active": None, "primary": None, "backup": None}

        if not chain:
            return result

        primary = chain[0]
        ok, msg = self.probe_llm_config(primary, timeout=timeout)
        result["primary"] = {"name": primary.get("name"), "ok": ok, "msg": msg}
        if ok:
            result["active"] = primary.get("name")
            return result

        if len(chain) > 1:
            backup = chain[1]
            ok2, msg2 = self.probe_llm_config(backup, timeout=timeout)
            result["backup"] = {"name": backup.get("name"), "ok": ok2, "msg": msg2}
            if ok2:
                result["active"] = backup.get("name")

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
        """获取 VL 模型配置

        local 字段语义（vl.local 默认 True）：
        - True  ：走独立 VL provider（默认 Qwen3-VL-2B 本地模型）
        - False ：fallback 到主模型（llm_providers 链中第一个有效项），与主用 LLM 共用
                  api_key / base_url / model_name；适用于"不想额外配 VL、让主模型兼职看图"的场景
        """
        self._load()

        provider_config = self.get("llm_providers.vl", {})

        result = {}
        for key in ["model_name", "api_key", "base_url", "local"]:
            config_value = provider_config.get(key) if isinstance(provider_config, dict) else None
            env_value = os.getenv(f"VL_{key.upper()}", None)

            # 字符串字段：空字符串视为未设
            if key != "local":
                if config_value and config_value != "":
                    result[key] = config_value
                elif env_value is not None and env_value != "":
                    result[key] = env_value
                else:
                    result[key] = None
            else:
                # local 布尔字段：保留 False 语义（不要把 False 当空字符串处理）
                if isinstance(config_value, bool):
                    result[key] = config_value
                elif env_value is not None:
                    result[key] = str(env_value).lower() in ("true", "1", "yes")
                else:
                    result[key] = True  # 默认 True（旧行为）

        for key in ["temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty"]:
            env_value = os.getenv(f"VL_{key.upper()}", None)
            if env_value is not None:
                try:
                    result[key] = float(env_value)
                except (ValueError, TypeError):
                    result[key] = env_value
            else:
                result[key] = None

        # local=False 时 fallback 到主用 LLM（仅覆盖连接三元组，不动 local/temperature/...）
        result = self._resolve_vl_fallback(result)

        return result

    def get_redis_checkpointer_url(self) -> str:
        """获取 Redis checkpointer URL"""
        return self.get("redis.checkpointer_url", fallback_env="REDIS_CHECKPOINTER_URL")

    def get_redis_state_saver_url(self) -> str:
        """获取 Redis state saver URL"""
        return self.get("redis.state_saver_url", fallback_env="REDIS_STATE_SAVER_URL")

    def get_oss_config(self) -> dict:
        """获取 OSS 配置"""
        return {
            "access_key_id": self.get("oss.access_key_id", fallback_env="OSS_ACCESS_KEY_ID"),
            "access_key_secret": self.get("oss.access_key_secret", fallback_env="OSS_ACCESS_KEY_SECRET"),
            "bucket": self.get("oss.bucket", fallback_env="OSS_BUCKET"),
            "endpoint": self.get("oss.endpoint", fallback_env="OSS_ENDPOINT"),
            "region": self.get("oss.region", fallback_env="OSS_REGION"),
        }

    def _resolve_vl_fallback(self, cfg: dict) -> dict:
        """vl.local=False 时把连接三元组 fallback 到"当前生效的" LLM。

        完全无视 vl 段自己填的 model_name / api_key / base_url —— 即便 vl 段配了也丢掉，
        一律用主用 provider（get_active_llm_config 内部已经做了主→备 fallback，
        跟启动健康检查保持一致）。

        输入 cfg 应至少含 model_name/api_key/base_url/local 四个键。
        返回新 dict，不修改入参。

        主模型链空（没配任何有效 provider）时 → 保留 vl 自己的配置兜底，
        比半残的 None 更安全。
        """
        if cfg.get("local") is not False:
            return cfg
        primary = self.get_active_llm_config()
        if not primary:
            return cfg
        out = dict(cfg)
        for key in ("model_name", "api_key", "base_url"):
            primary_val = primary.get(key, "")
            out[key] = primary_val  # 无条件覆盖：完全不管 vl 段自己的配置
        return out

    def get_skills_config(self) -> dict:
        """获取 skills 配置（API key 等）

        优先级：config.json > 环境变量
        - 搜索类（config.json 的 skills 段）：bocha_api_key / exa_api_key / tavily_api_key
        - 视觉模型类（复用 llm_providers.vl）：vl_base_url / vl_api_key / vl_model_name
        - vl.local=False 时连接三元组 fallback 到主用 LLM

        容器内自动把 127.0.0.1 替换为 host.docker.internal（容器访问 host 的特殊 DNS）
        """
        cfg = {
            "bocha_api_key": self.get("skills.bocha_api_key", fallback_env="BOCHA_API_KEY"),
            "exa_api_key": self.get("skills.exa_api_key", fallback_env="EXA_API_KEY"),
            "tavily_api_key": self.get("skills.tavily_api_key", fallback_env="TAVILY_API_KEY"),
            "vl_base_url": self.get("llm_providers.vl.base_url", fallback_env="VL_BASE_URL",
                                     default="http://127.0.0.1:8211/api/v1"),
            "vl_api_key": self.get("llm_providers.vl.api_key", fallback_env="VL_API_KEY", default="empty"),
            "vl_model_name": self.get("llm_providers.vl.model_name", fallback_env="VL_MODEL_NAME",
                                        default="Qwen3-VL-2B"),
            "vl_local": self.get("llm_providers.vl.local", fallback_env="VL_LOCAL", default=True),
        }
        # 容器内：127.0.0.1 → host.docker.internal
        if os.path.exists("/.dockerenv"):
            if "127.0.0.1" in cfg.get("vl_base_url", ""):
                cfg["vl_base_url"] = cfg["vl_base_url"].replace("127.0.0.1", "host.docker.internal")

        # local=False fallback：把连接三元组换成主模型
        fallback_input = {
            "model_name": cfg["vl_model_name"],
            "api_key": cfg["vl_api_key"],
            "base_url": cfg["vl_base_url"],
            "local": cfg["vl_local"] if isinstance(cfg["vl_local"], bool)
                     else str(cfg["vl_local"]).lower() in ("false", "0", "no"),
        }
        resolved = self._resolve_vl_fallback(fallback_input)
        cfg["vl_model_name"] = resolved["model_name"]
        cfg["vl_api_key"] = resolved["api_key"]
        cfg["vl_base_url"] = resolved["base_url"]
        return cfg

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

    # ========================================================================
    # 运行时配置读写（前端 SettingsDialog 用）
    # ========================================================================

    # 前端表单允许编辑的顶层 key 白名单；其他节点（app/redis/dirs/oss）禁止修改
    EDITABLE_TOP_KEYS = ("llm_providers", "skills", "permissions")

    # 修改后必须重启后端才能生效的字段（langchain client / mcp client 是常驻对象）
    RESTART_REQUIRED = True

    @staticmethod
    def _mask_secret(value: Any) -> str:
        """
        密钥脱敏：保留前 4 后 4 字符，中间用 * 代替。
        长度 ≤ 8 的直接全 *，空值原样返回。
        """
        if not isinstance(value, str) or not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"

    def get_public_config(self) -> dict:
        """
        返回前端可编辑的视图（密钥脱敏）

        - llm_providers.*.api_key → 脱敏
        - skills.*_api_key → 脱敏
        - 其他字段原样返回
        """
        self._load()
        result = {}

        llm = self.get("llm_providers", {}) or {}
        if isinstance(llm, dict):
            llm_copy = {}
            for name, cfg in llm.items():
                if not isinstance(cfg, dict):
                    llm_copy[name] = cfg
                    continue
                cfg_copy = dict(cfg)
                if "api_key" in cfg_copy:
                    cfg_copy["api_key"] = self._mask_secret(cfg_copy["api_key"])
                llm_copy[name] = cfg_copy
            result["llm_providers"] = llm_copy

        skills = self.get("skills", {}) or {}
        if isinstance(skills, dict):
            skills_copy = dict(skills)
            for k in list(skills_copy.keys()):
                if k.endswith("_api_key"):
                    skills_copy[k] = self._mask_secret(skills_copy[k])
            result["skills"] = skills_copy

        # permissions 段：原样返回。改动后需重启后端（Permissions 单例是启动时缓存的）
        perms = self.get("permissions", {}) or {}
        if isinstance(perms, dict):
            result["permissions"] = dict(perms)

        return result

    def save_config(self, updates: dict) -> dict:
        """
        原子写配置：仅允许更新白名单内的顶层 key，api_key 为空表示跳过该字段（不修改）。

        Returns:
            {"ok": bool, "applied": bool, "restart_required": True, "saved_keys": [...]}

        Raises:
            ValueError: 顶层 key 不在白名单 / payload 结构非法
            RuntimeError: 写文件失败
        """
        self._load()
        if not isinstance(updates, dict):
            raise ValueError("updates 必须是 dict")

        # 白名单校验：顶层 key 必须在 EDITABLE_TOP_KEYS 内
        unknown_keys = [k for k in updates.keys() if k not in self.EDITABLE_TOP_KEYS]
        if unknown_keys:
            raise ValueError(
                f"不允许编辑的字段: {unknown_keys}（白名单: {list(self.EDITABLE_TOP_KEYS)}）"
            )

        # 校验每个 section 的结构
        for top_key, section in updates.items():
            if not isinstance(section, dict):
                raise ValueError(f"{top_key} 必须是 dict，实际是 {type(section).__name__}")

        # 准备要写入的 merged 配置（不动内存中的 _config；只写文件，避免污染后续 _load()）
        current = json.loads(json.dumps(self._config))  # 深拷贝

        saved_keys = []
        # === llm_providers ===
        if "llm_providers" in updates:
            current.setdefault("llm_providers", {})
            for prov_name, prov_cfg in updates["llm_providers"].items():
                if not isinstance(prov_cfg, dict):
                    continue
                current["llm_providers"].setdefault(prov_name, {})
                for field, value in prov_cfg.items():
                    # api_key 为空字符串表示不修改
                    if field == "api_key" and (value is None or value == ""):
                        continue
                    current["llm_providers"][prov_name][field] = value
                    saved_keys.append(f"llm_providers.{prov_name}.{field}")

        # === skills ===
        if "skills" in updates:
            current.setdefault("skills", {})
            for field, value in updates["skills"].items():
                # api_key 为空表示不修改
                if field.endswith("_api_key") and (value is None or value == ""):
                    continue
                current["skills"][field] = value
                saved_keys.append(f"skills.{field}")

        # === permissions ===
        if "permissions" in updates:
            current.setdefault("permissions", {})
            for field, value in updates["permissions"].items():
                if field == "approval_policy":
                    if value not in ("default", "yolo"):
                        raise ValueError(f"approval_policy 必须是 'default' 或 'yolo'，实际是 {value!r}")
                    current["permissions"]["approval_policy"] = value
                    saved_keys.append("permissions.approval_policy")
                elif field in ("approved_commands", "denied_commands"):
                    if not isinstance(value, list):
                        raise ValueError(f"{field} 必须是 list，实际是 {type(value).__name__}")
                    current["permissions"][field] = value
                    saved_keys.append(f"permissions.{field}")
                else:
                    raise ValueError(f"permissions 段不允许的字段: {field!r}")

        # 原子写：tmp + os.replace（不写 .bak 副本，避免污染用户配置目录 / git untracked 列表）
        # 关键：tmp 文件名带进程 PID，避免与仓库里提交的 config.json.tmp 模板重名
        # （之前用 with_suffix(".json.tmp") 会在首次保存时把模板覆盖掉）
        config_file = self._find_config_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)

        tmp_file = config_file.with_name(f"{config_file.name}.{os.getpid()}.tmp")
        try:
            tmp_file.write_text(
                json.dumps(current, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp_file, config_file)
        except Exception as e:
            # 写失败：清理残留的 tmp 文件（不影响旧 config.json）
            try:
                if tmp_file.exists():
                    tmp_file.unlink()
            except Exception:
                pass
            raise RuntimeError(f"写入 config.json 失败: {e}")

        # 不调用 self._load(force=True)：所有运行时使用的对象都是启动时构造的，
        # 热加载意义不大，让前端提示用户重启即可。

        return {
            "ok": True,
            "applied": False,  # 不热加载
            "restart_required": self.RESTART_REQUIRED,
            "saved_keys": saved_keys,
        }

    def trigger_restart(self) -> None:
        """
        异步重启后端：通过 os.execv 替换当前进程为新的 main.py。
        调用方应通过 FastAPI BackgroundTasks 调用，确保响应已 flush 到客户端再重启。
        """
        import sys
        import time

        # 写 marker 文件，让前端启动后能识别「这是重启恢复」的场景
        marker = Path(self._get_global_config_dir()) / ".restart_pending"
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(int(time.time())), encoding="utf-8")
        except Exception:
            pass

        # 给前端一点时间收响应（FastAPI BackgroundTasks 通常在响应发送后触发）
        time.sleep(0.3)

        # 用同样的 python 重启 main.py；uvicorn 单进程模式下整个服务都会被替换
        os.execv(sys.executable, [sys.executable, "main.py"])


config = ChatMeConfig()


def get_config(key: str, default: Any = None, fallback_env: str = None) -> Any:
    """快捷获取配置"""
    return config.get(key, default, fallback_env)


def get_redis_checkpointer_url() -> str:
    """获取 Redis checkpointer URL"""
    return config.get_redis_checkpointer_url()


def get_redis_state_saver_url() -> str:
    """获取 Redis state saver URL"""
    return config.get_redis_state_saver_url()


def get_oss_config() -> dict:
    """获取 OSS 配置"""
    return config.get_oss_config()


def get_skills_config() -> dict:
    """获取 skills 配置（API key 等）

    优先级：config.json > 环境变量
    """
    return config.get_skills_config()


def get_permissions_config() -> dict:
    """获取 permissions 段（dict 形式）。段缺失时返回 default 配置。"""
    cfg = config.get("permissions", {}) or {}
    return {
        "approval_policy": cfg.get("approval_policy", "default"),
        "approved_commands": cfg.get("approved_commands", []),
        "denied_commands": cfg.get("denied_commands", []),
    }


def get_app_config() -> dict:
    """获取 app 配置"""
    return config.get_app_config()


def get_model_vl_config() -> dict:
    """获取 VL 模型配置"""
    return config.get_model_vl_config()


def get_active_llm_config() -> dict:
    """获取主用 LLM 配置（llm_providers 链中的第一个有效项）"""
    return config.get_active_llm_config()


def get_backup_llm_config() -> dict:
    """获取备用 LLM 配置（链中的第二个有效项）"""
    return config.get_backup_llm_config()


def get_llm_providers_chain() -> list:
    """获取所有有效的业务 LLM provider 列表（主 → 备）"""
    return config.get_llm_providers_chain()


def is_provider_valid(provider_cfg) -> bool:
    """判断一个 provider 配置是否完整可用"""
    return ChatMeConfig._is_provider_valid(provider_cfg)


def probe_llm_config(cfg: dict, timeout: int = 10) -> tuple:
    """用 ChatOpenAI 实际调用一次，验证 cfg 是否可用"""
    return ChatMeConfig.probe_llm_config(cfg, timeout=timeout)


def self_check_llm(timeout: int = 10) -> dict:
    """
    对 llm_providers 链做端到端自检（主用 → 备用）
    返回 {"active", "primary", "backup"} 结构
    """
    return config.self_check_llm(timeout=timeout)


def ensure_global_config() -> None:
    """确保全局配置目录和文件存在，优先使用局部配置"""
    # 1. 如果局部配置存在，直接返回
    local_path = Path.cwd() / ".chatme" / "config.json"
    if local_path.exists():
        return

    # 2. 如果全局配置存在，也直接返回
    global_path = Path.home() / ".chatme" / "config.json"
    if global_path.exists():
        return

    # 3. 都不存在，在全局目录生成
    config._generate_default_config(global_path)
