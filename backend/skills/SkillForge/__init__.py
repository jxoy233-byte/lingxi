"""
SkillForge — 在 /skills/ 下创建新 skill

⚠️ 必须 code(..., local=True)。创建后立即可被 find_skill 发现（registry
走 mtime 自动重扫，无需重启后端）。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

SKILLS_ROOT = Path(__file__).resolve().parent.parent  # backend/skills/

# 保留名：不能被新 skill 占用
_RESERVED_NAMES = {"SkillForge", "__pycache__"}


def create_skill(
    name: str,
    description: str,
    functions_py: str,
    aliases: Optional[list] = None,
    skill_md_body: str = "",
    overwrite: bool = False,
) -> str:
    """
    创建新 skill。

    Args:
        name: skill 名（小写字母/数字/下划线），会作为目录名 + module 名
        description: 一句话描述，会写入 frontmatter + 默认 SKILL.md
        functions_py: 完整 __init__.py 内容（含 import + 顶层函数）。
                      skill 是 Python wrapper，但 wrapper 内部可调任意
                      外部服务（REST API / CLI / 数据库 / 其他程序），
                      不局限于写 Python helper 函数 —— 封装好能用就行。
        aliases: 别名列表（用于 find_skill 关键词匹配）
        skill_md_body: 自定义 SKILL.md 正文（不含 frontmatter）；空=自动生成
        overwrite: True 时覆盖已存在的同名 skill（默认 False 防误覆盖）

    Returns:
        成功消息（含写入路径）/ 失败消息（[类型] 描述）
    """
    # 1. name 校验
    if not name or not all(c.isalnum() or c == "_" for c in name):
        return f"[BadRequest] skill name 必须是字母/数字/下划线: {name!r}"
    if name in _RESERVED_NAMES or name.startswith("_"):
        return f"[BadRequest] skill name 保留: {name!r}"

    target_dir = SKILLS_ROOT / name
    if target_dir.exists():
        if not overwrite:
            return (
                f"[Exists] skill {name!r} 已存在 ({target_dir})。"
                f"若要覆盖请显式传 overwrite=True。"
            )
        shutil.rmtree(target_dir)

    target_dir.mkdir(parents=True, exist_ok=False)

    # 2. SKILL.md
    if not skill_md_body:
        aliases_list = ", ".join(f"`{a}`" for a in (aliases or []))
        skill_md_body = (
            f"# {name}\n\n"
            f"{description}\n\n"
            f"## 调用方式\n\n"
            f"```python\n"
            f"from skills.{name} import ...\n"
            f"```\n\n"
            f"## 别名\n\n"
            f"{aliases_list or '无'}\n"
        )

    aliases_yaml = ""
    if aliases:
        aliases_yaml = "aliases: [" + ", ".join(f'"{a}"' for a in aliases) + "]\n"

    skill_md = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"module: skills.{name}\n"
        f"{aliases_yaml}"
        f"---\n\n"
        f"{skill_md_body}\n"
    )
    (target_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # 3. __init__.py
    (target_dir / "__init__.py").write_text(functions_py, encoding="utf-8")

    return (
        f"Created skill {name!r} at {target_dir}.\n"
        f"含 SKILL.md + __init__.py。\n"
        f"立即可被 find_skill 发现（registry mtime 自动重扫，无需重启）。"
    )


def list_skills() -> str:
    """列出 /skills/ 下所有 skill 目录（含 SKILL.md 的）。"""
    if not SKILLS_ROOT.is_dir():
        return "[Error] /skills/ 目录不存在"
    skills = []
    for d in sorted(SKILLS_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name == "__pycache__":
            continue
        if (d / "SKILL.md").exists():
            skills.append(d.name)
    return "\n".join(skills) if skills else "No skills found."


def read_skill(name: str) -> str:
    """
    读现有 skill 的 SKILL.md + __init__.py 内容（用于复制格式 / 修改前参考）。

    返回：完整文件内容（SKILL.md 在前，__init__.py 在后）
    """
    target_dir = SKILLS_ROOT / name
    if not target_dir.is_dir():
        return f"[NotFound] skill {name!r} 不存在"
    parts = []
    for fname in ("SKILL.md", "__init__.py"):
        fpath = target_dir / fname
        if fpath.exists():
            parts.append(f"=== {fname} ===\n{fpath.read_text(encoding='utf-8')}")
    return "\n\n".join(parts) if parts else f"[Empty] skill {name!r} 没有文件"