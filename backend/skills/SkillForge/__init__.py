"""
SkillForge — 在 /skills/ 下创建新 skill

⚠️ 必须 code(..., local=True)。创建后立即可被 find_skill 发现（registry
走 mtime 自动重扫，无需重启后端）。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from ChatMe.paths import SKILLS_ROOT

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
    在 /skills/<name>/ 下创建新 skill：写入 SKILL.md + __init__.py，registry 自动重扫（无需重启后端）。

    Args: name 字母数字下划线（保留 `SkillForge`/`_*`）；description 一句话写 frontmatter；
          functions_py `__init__.py` 完整内容；aliases 别名列表；skill_md_body 自定义正文（空=自动）；
          overwrite True 时先 rmtree 再 mkdir（默认 False 防误覆盖）。
    Returns: `Created skill 'X' at ...` 或 `[BadRequest]/[Exists]`。
    详细 `help("create_skill")`。
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
    """列出 /skills/ 下所有带 SKILL.md 的 skill 目录名（按字典序，跳过隐藏目录 / `__pycache__`）。

    Returns: 多行字符串，每行一个 skill 名；空目录返 `"No skills found."`。
    详细 `help("list_skills")`。
    """
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
    读现有 skill 的 SKILL.md + __init__.py 完整内容（用于复制格式 / 修改前参考）。

    Args: name skill 名（与目录名一致）。
    Returns: SKILL.md + `__init__.py` 内容（`=== filename ===` 分隔）；不存在返 `[NotFound]`；都缺返 `[Empty]`。
    详细 `help("read_skill")`。
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


def doc(name=None):
    """查询本 skill 的函数 docstring。

    Args:
        name: None 列出全部；str 返回该函数的完整 docstring

    Returns:
        字符串（直接 print 即可看）

    用法：
        from skills.SkillForge import help
        help()              # 列出全部函数签名 + summary
        help("func_name")   # 单个函数完整 docstring
    """
    import sys
    from skills._shared._skill_help import skill_help
    return skill_help(sys.modules[__name__], name)


def help(name=None):
    """doc() 别名。"""
    return doc(name)


# 自动给所有顶层函数挂 .help 属性（func.help 直接拿 docstring）
import sys as _sys
from skills._shared._skill_help import auto_attach_help_module as _auto_attach_help_module
_auto_attach_help_module(_sys.modules[__name__])