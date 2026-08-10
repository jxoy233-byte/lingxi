from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml


@dataclass(frozen=True)
class SkillManifest:
    name: str
    path: Path
    frontmatter: dict
    summary: str
    mount_mode: Literal["ro", "rw"]
    lazy: bool
    import_aliases: list[str]
    module_path: str


def parse_frontmatter(md_text: str) -> dict:
    """Parse a leading YAML frontmatter block from SKILL.md text."""
    if not md_text.startswith("---"):
        return {}

    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise ValueError("SKILL.md frontmatter is missing its closing delimiter") from exc

    try:
        parsed = yaml.safe_load("\n".join(lines[1:closing_index])) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid SKILL.md frontmatter: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")
    return parsed
