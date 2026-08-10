import functools

from ChatMe.ChatWorkflow.skills.manifest import SkillManifest
from ChatMe.ChatWorkflow.skills.registry import get_skill_registry
from ChatMe.LoggingManager.logging_config import get_logger

logger = get_logger("skill_prompt")


# Fallback 仅在 registry 启动失败 / skills 目录完全空时使用，
# 列出 4 个老 skill 名称 + 引导用户去 `code()` 自定义。
_FALLBACK_BLOCK = """<available_skills>
(skills registry unavailable — see backend/skills/ for available skills)
- if none of the above matches: use code() to write custom logic
</available_skills>"""


def _relative_path(skill: SkillManifest) -> str:
    """Maps a manifest back to its /skills/<path>/SKILL.md location."""
    if skill.module_path.startswith("skills."):
        return skill.module_path.removeprefix("skills.").replace(".", "/")
    return skill.path.name


def _format_skill(skill: SkillManifest) -> str:
    """Full 7-line markdown block for `<available_skills>` index."""
    aliases = ", ".join(skill.import_aliases)
    description = str(skill.frontmatter.get("description") or skill.summary)
    lines = [
        f"- name: {skill.name}",
        f"  description: {description}",
        f"  module: {skill.module_path}",
        f"  aliases: [{aliases}]",
        f"  mount: {skill.mount_mode}",
        f"  skill_file: /skills/{_relative_path(skill)}/SKILL.md",
        f"  usage_hints: {skill.summary}",
    ]
    return "\n".join(lines)


def _format_skill_brief(skill: SkillManifest) -> str:
    """Compact one-line description for find_skill match results."""
    description = str(skill.frontmatter.get("description") or skill.summary[:80])
    return (
        f"name={skill.name} | description={description} | "
        f"module={skill.module_path} | file=/skills/{_relative_path(skill)}/SKILL.md"
    )


@functools.lru_cache(maxsize=1)
def available_skills_block() -> str:
    """Generate the full <available_skills> prompt block (mode='list' response).

    Cached: registry is read-only after init, so repeated calls during a
    session return the same string. `reset_skill_registry()` clears this
    cache for tests.
    """
    try:
        skills = [s for s in get_skill_registry().scan() if not s.lazy]
    except Exception as exc:
        logger.warning(f"生成 available_skills 失败，使用静态兜底: {exc}")
        return _FALLBACK_BLOCK

    if not skills:
        return _FALLBACK_BLOCK

    formatted = "\n".join(_format_skill(skill) for skill in skills)
    return (
        "<available_skills>\n"
        f"{formatted}\n"
        "- if none of the above matches: use code() to write custom logic\n"
        "</available_skills>"
    )


@functools.lru_cache(maxsize=32)
def find_skill_block(query: str, top_k: int = 3) -> str:
    """Tool response for find_skill(query, mode='match').

    Returns brief matches by token overlap. 0 matches → suggest mode='list'.

    缓存：相同 query 重复调用返回同一字符串（find_skill 工具可能被 LLM
    在同一会话多次调用避免重复计算）。
    """
    try:
        matches = get_skill_registry().search(query, top_k=top_k)
    except Exception as exc:
        logger.warning(f"find_skill 搜索失败: {exc}")
        return f"[find_skill error: {exc}]"

    if not matches:
        return (
            f"[No matching skill for query: {query!r}]\n"
            "If you think there should be a match, try mode='list' to see all skills."
        )

    header = f"Matched {len(matches)} skill(s) for query: {query!r}"
    body = "\n".join(f"- {_format_skill_brief(skill)}" for skill in matches)
    footer = (
        "To use: read the SKILL.md via cmd('cat /skills/<name>/SKILL.md') "
        "if you need details, then invoke via code() with the listed module path."
    )
    return f"{header}\n{body}\n{footer}"
