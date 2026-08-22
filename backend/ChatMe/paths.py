"""后端运行时路径中心模块。

整个后端只允许**一处**推导 backend/cached/、backend/skills/、.chatme/ 这三个
根目录，其他模块一律 `from ChatMe.paths import ...` 拿现成路径。

禁止再写：
  - `Path.cwd() / "cached"`            ← 进程从别的目录启动会飘
  - `Path(__file__).resolve().parents[N] / "skills"`  ← 文件深度一变就 off-by-one
  - `Path.cwd() / ".chatme" / "logs"`  ← local vs global 逻辑散落各模块

## 三个根

- **CACHED_DIR**：`backend/cached/`，每个 session 的运行时数据（产物 / 文件 / 数据分析）。
  模块级常量，导入时锁定，永不变。

- **SKILLS_ROOT**：`backend/skills/`，skill 注册表的 SKILL.md 根目录。
  模块级常量，导入时锁定。

- **get_chatme_dir() -> Path**：配置 / 日志 / 记忆文件的根目录。**函数而非常量**，
  因为 local（cwd 下的 .chatme）vs global（~/.chatme）需要在调用时根据当前 cwd
  判定，且可能在启动中后期才被 auto-create。

## 锚点

`BACKEND_ROOT` 用 `Path(__file__).resolve().parents[1]` 锚定到 `backend/` 目录，
**不依赖 cwd** —— 后端从任意目录启动都不会漂移。
"""
from __future__ import annotations

from pathlib import Path

# 锚点：本文件位于 backend/ChatMe/paths.py，parents[1] = backend/
# 用 .resolve() 吃掉可能的 symlink（如 pip install -e . 或 develop 模式）
BACKEND_ROOT: Path = Path(__file__).resolve().parents[1]

# 模块级常量：导入时锁定，永不变
CACHED_DIR: Path = BACKEND_ROOT / "cached"
SKILLS_ROOT: Path = BACKEND_ROOT / "skills"
# 软删除回收站：DELETE /chat/{sid}/file 把文件移到 .trash/{sid}/{ts}_{name}，
# 每天 11:30 定时任务清理（MailScheduler.v0.1.4 已有 AsyncIOScheduler 钩子）。
TRASH_DIR: Path = BACKEND_ROOT / ".trash"


def get_chatme_dir() -> Path:
    """解析 .chatme/ 目录。

    优先级（与 ChatMeConfig 既有的 local-first 约定保持一致）：
      1. cwd 下的 .chatme/（local，dev / 测试场景）
      2. ~/.chatme/（global，生产 / 安装场景）

    为什么是函数而不是常量：
      - local vs global 取决于调用瞬间的 cwd 状态，启动后期 .chatme/ 可能
        还没创建（ensure_global_config 之后才存在），导入期定不下来。
      - 测试场景下 cwd 可能中途切换（chdir），常量会变成过期快照。

    为什么不走环境变量 override：ChatMeConfig 自己也没暴露 CHATME_DIR，
    加这里会让"override 在哪生效"的语义跨两个模块。需要时再统一加。
    """
    local = Path.cwd() / ".chatme"
    if local.exists():
        return local
    return Path.home() / ".chatme"
