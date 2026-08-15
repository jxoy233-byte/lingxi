"""
SkillForge skill 单元测试

覆盖：
- create_skill：合法路径 / 拒绝非法 name / 拒绝覆盖（默认 overwrite=False）
- overwrite=True：真的覆盖
- list_skills：扫描现有 skill 目录
- read_skill：读 SKILL.md + __init__.py
- SKILL.md 自动生成 / 自定义 body 都被正确写入
- 路径：写到真实 SKILLS_ROOT（monkeypatch 到 tmp_path 避免污染）
"""

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture
def fake_skills_root(monkeypatch, tmp_path: Path):
    """把 skills.SkillForge.SKILLS_ROOT 指向 tmp_path（不污染 host）"""
    from skills import SkillForge
    monkeypatch.setattr(SkillForge, "SKILLS_ROOT", tmp_path)
    return tmp_path


def test_create_skill_writes_skill_md_and_init_py(fake_skills_root):
    """合法参数 → 同时写入 SKILL.md + __init__.py"""
    from skills.SkillForge import create_skill

    functions_py = (
        "def hello():\n"
        "    return 'hi'\n"
    )
    result = create_skill(
        name="test_skill",
        description="测试 skill",
        functions_py=functions_py,
        aliases=["TestSkill", "测试"],
    )

    assert "Created skill 'test_skill'" in result

    skill_dir = fake_skills_root / "test_skill"
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "__init__.py").is_file()

    skill_md_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "name: test_skill" in skill_md_text
    assert "description: 测试 skill" in skill_md_text
    assert 'module: skills.test_skill' in skill_md_text
    assert '"TestSkill"' in skill_md_text and '"测试"' in skill_md_text

    init_text = (skill_dir / "__init__.py").read_text(encoding="utf-8")
    assert "def hello():" in init_text
    assert "return 'hi'" in init_text


def test_create_skill_default_skill_md_body(fake_skills_root):
    """skill_md_body 空 → 自动生成默认正文（含 name + 别名）"""
    from skills.SkillForge import create_skill

    create_skill(
        name="auto_md",
        description="x",
        functions_py="pass\n",
        aliases=["A", "B"],
    )
    body = (fake_skills_root / "auto_md" / "SKILL.md").read_text(encoding="utf-8")
    assert "# auto_md" in body
    assert "from skills.auto_md import" in body
    assert "`A`" in body and "`B`" in body


def test_create_skill_custom_md_body_used(fake_skills_root):
    """自定义 skill_md_body 完全替换默认生成"""
    from skills.SkillForge import create_skill

    create_skill(
        name="custom",
        description="d",
        functions_py="pass\n",
        skill_md_body="# My Custom\n\nDetailed usage here.\n",
    )
    body = (fake_skills_root / "custom" / "SKILL.md").read_text(encoding="utf-8")
    assert "# My Custom" in body
    assert "Detailed usage here." in body
    # 不应含默认生成的 "from skills.custom import"
    assert "from skills.custom import" not in body


def test_create_skill_rejects_invalid_name(fake_skills_root):
    """含特殊字符 / 空 → [BadRequest]，不写文件"""
    from skills.SkillForge import create_skill

    for bad in ("a-b", "a b", "a.b", "", "a/b"):
        result = create_skill(name=bad, description="x", functions_py="pass\n")
        assert "[BadRequest]" in result, f"应拒绝 {bad!r}"


def test_create_skill_rejects_reserved_name(fake_skills_root):
    """保留名（SkillForge / _xxx / __pycache__）→ [BadRequest]"""
    from skills.SkillForge import create_skill

    for reserved in ("SkillForge", "_internal", "__pycache__"):
        result = create_skill(name=reserved, description="x", functions_py="pass\n")
        assert "[BadRequest]" in result, f"应拒绝保留名 {reserved!r}"
        assert "保留" in result


def test_create_skill_rejects_overwrite_by_default(fake_skills_root):
    """overwrite=False 默认 → 已存在 skill 时 [Exists]"""
    from skills.SkillForge import create_skill

    create_skill(name="dup", description="first", functions_py="v1 = 1\n")

    result = create_skill(name="dup", description="second", functions_py="v2 = 2\n")
    assert "[Exists]" in result
    assert "overwrite=True" in result

    # 文件内容仍是 v1
    init_text = (fake_skills_root / "dup" / "__init__.py").read_text(encoding="utf-8")
    assert "v1" in init_text and "v2" not in init_text


def test_create_skill_overwrite_true_replaces(fake_skills_root):
    """overwrite=True → 真的覆盖旧 skill"""
    from skills.SkillForge import create_skill

    create_skill(name="dup", description="first", functions_py="v1 = 1\n")
    result = create_skill(
        name="dup", description="second", functions_py="v2 = 2\n",
        overwrite=True,
    )
    assert "Created skill" in result

    init_text = (fake_skills_root / "dup" / "__init__.py").read_text(encoding="utf-8")
    assert "v2" in init_text and "v1" not in init_text
    md_text = (fake_skills_root / "dup" / "SKILL.md").read_text(encoding="utf-8")
    assert "description: second" in md_text


def test_list_skills_returns_only_dirs_with_skill_md(fake_skills_root):
    """list_skills 只列有 SKILL.md 的目录，跳过 _xxx / __pycache__ / 普通文件"""
    from skills.SkillForge import create_skill, list_skills

    create_skill(name="a", description="d", functions_py="pass\n")
    create_skill(name="b", description="d", functions_py="pass\n")
    # 创建干扰项
    (fake_skills_root / "_internal").mkdir()
    (fake_skills_root / "__pycache__").mkdir()
    (fake_skills_root / "no_md").mkdir()
    (fake_skills_root / "loose.txt").write_text("x")

    result = list_skills()
    assert "a" in result
    assert "b" in result
    assert "_internal" not in result
    assert "__pycache__" not in result
    assert "no_md" not in result


def test_list_skills_empty_returns_no_skills_message(fake_skills_root):
    """空目录 → 'No skills found.'"""
    from skills.SkillForge import list_skills

    assert list_skills() == "No skills found."


def test_read_skill_returns_both_files(fake_skills_root):
    """read_skill 返回 SKILL.md + __init__.py 完整内容"""
    from skills.SkillForge import create_skill, read_skill

    create_skill(name="r", description="d", functions_py="def f(): pass\n")

    result = read_skill("r")
    assert "=== SKILL.md ===" in result
    assert "=== __init__.py ===" in result
    assert "name: r" in result
    assert "def f():" in result


def test_read_skill_not_found(fake_skills_root):
    """不存在的 skill → [NotFound]"""
    from skills.SkillForge import read_skill

    assert "[NotFound]" in read_skill("nonexistent")


def test_create_skill_writes_to_real_skills_root_at_import(monkeypatch):
    """回归：import 时 SKILLS_ROOT 默认指向真实 backend/skills/（不破坏 monkeypatch 前的语义）"""
    from skills import SkillForge

    # 默认应指向 backend/skills/，含 Tavily / Scheduler / SkillForge 等
    assert SkillForge.SKILLS_ROOT.name == "skills"
    assert (SkillForge.SKILLS_ROOT / "Tavily").is_dir()
    assert (SkillForge.SKILLS_ROOT / "SkillForge").is_dir()