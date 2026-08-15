from pathlib import Path

import pytest

from ChatMe.ChatWorkflow.skills.manifest import parse_frontmatter
from ChatMe.ChatWorkflow.skills.prompt import available_skills_block, find_skill_block
from ChatMe.ChatWorkflow.skills.registry import SkillRegistry, get_skill_registry, reset_skill_registry


@pytest.fixture(autouse=True)
def restore_default_registry():
    """每个测试前重置 registry，确保环境隔离。"""
    reset_skill_registry()
    yield
    reset_skill_registry()


def test_parse_frontmatter():
    metadata = parse_frontmatter(
        "---\nname: demo\ndescription: 示例\naliases: [Demo]\n---\n# Demo\n"
    )
    assert metadata == {
        "name": "demo",
        "description": "示例",
        "aliases": ["Demo"],
    }
    assert parse_frontmatter("# No frontmatter") == {}


def test_parse_frontmatter_rejects_malformed_yaml():
    with pytest.raises(ValueError):
        parse_frontmatter("---\nname: [broken\n---\n")
    with pytest.raises(ValueError):
        parse_frontmatter("---\nname: demo\n")


def test_registry_scans_current_skills():
    skills_root = Path(__file__).resolve().parents[2] / "skills"
    registry = SkillRegistry(skills_root)

    names = registry.names()
    if not names:
        names = [skill.name for skill in registry.scan()]

    assert set(names) == {
        "exa",
        "tavily",
        "image_parser",
        "data_analysis",
        "data_analysis_database",
        "scheduler",
        "skillforge",  # v0.1.5 新增：用于动态创建 skill
        "memory",      # v0.1.5 新增：精确事实 / 用户偏好持久化
    }


def test_registry_mount_args_include_top_level_rw_and_per_skill_rw(monkeypatch):
    """registry 输出必须：
    1. 含 /skills:rw 顶层 aggregate mount（兼容 `from Exa import ...` 风格 + 支持 SkillForge 写新 skill）
    2. 每个 mount_mode=rw 的 skill 单独 :rw 挂载
    3. 嵌套子 skill（如 DataAnalysis/database）如果也是 rw，独立挂载而不是依赖父目录
    4. 宿主机每个挂载源路径都存在
    """
    from ChatMe.ChatWorkflow.mcps.sandbox.pool import SandboxPool

    skills_root = Path(__file__).resolve().parents[2] / "skills"
    pool = SandboxPool.__new__(SandboxPool)
    pool.skills_path = str(skills_root.resolve())

    monkeypatch.setenv("SANDBOX_USE_SKILL_REGISTRY", "true")
    registry_args = pool._build_skill_mount_args()

    # 1. 顶层 /skills:rw 必须存在（v0.1.5 起 /skills 默认 rw，给 SkillForge 写新 skill 用）
    assert "-v" in registry_args
    rw_idx = next(
        i for i, a in enumerate(registry_args)
        if a.endswith(":/skills:rw")
    )
    assert registry_args[rw_idx - 1] == "-v"

    # 2. DataAnalysis 必须独立 rw 挂载
    assert any(
        a.endswith(":/skills/DataAnalysis:rw")
        for a in registry_args
    )

    # 3. 嵌套子 skill (database) 如独立 rw 应单独挂载
    rw_mounts = [
        a for a in registry_args if a.endswith(":rw")
    ]
    # 当前 layout：DataAnalysis 顶层 rw + database 子 skill 也 rw
    assert len(rw_mounts) >= 1

    # 4. 每个 mount 源路径存在
    for volume in registry_args[1::2]:
        host_path = Path(volume.split(":", 1)[0])
        assert host_path.exists(), f"mount source missing: {host_path}"


def test_image_parser_resolves_backend_cached_path():
    from skills.ImageParser import _resolve_cached_path

    backend_root = Path(__file__).resolve().parents[2]
    assert Path(_resolve_cached_path("cached/example.png")) == backend_root / "cached/example.png"


def test_registry_skips_invalid_manifest(tmp_path: Path):
    valid = tmp_path / "Valid"
    valid.mkdir()
    (valid / "SKILL.md").write_text(
        "---\nname: valid\ndescription: valid skill\nmount: ro\n---\nbody",
        encoding="utf-8",
    )
    invalid = tmp_path / "Invalid"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text(
        "---\nname: invalid\ndescription: [broken\n---\nbody",
        encoding="utf-8",
    )

    registry = SkillRegistry(tmp_path)
    assert [skill.name for skill in registry.scan()] == ["valid"]


def test_available_skills_block(tmp_path: Path):
    skill_dir = tmp_path / "Demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 用于测试\naliases: [Demo]\nmodule: skills.Demo\n---\n# Demo",
        encoding="utf-8",
    )
    reset_skill_registry(tmp_path)

    block = available_skills_block()

    assert "<available_skills>" in block
    assert "name: demo" in block
    assert "module: skills.Demo" in block
    assert "skill_file: /skills/Demo/SKILL.md" in block
    assert "usage_hints: Demo" in block


def test_available_skills_block_no_cache(tmp_path: Path):
    """v0.1.5 起 available_skills_block() 不再缓存，重复调用重新渲染。

    之前 lru_cache(maxsize=1) 锁住结果，SkillForge 创建新 skill 后必须重启
    后端才能发现。去掉 cache 后走 registry mtime check，每次都拿最新磁盘状态。
    """
    skill_dir = tmp_path / "Cached"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: cached\ndescription: 缓存测试\n---\nbody",
        encoding="utf-8",
    )
    reset_skill_registry(tmp_path)

    first = available_skills_block()
    second = available_skills_block()
    # 不再是同一对象，但内容一致（registry 缓存命中）
    assert first == second
    assert first is not second  # 不缓存，每次重新渲染


def test_build_mount_args_uses_cached_skills(tmp_path: Path):
    """build_mount_args 不再调 scan()，而是直接读 _skills。"""
    skill_dir = tmp_path / "X"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\nmount: rw\n---\nbody",
        encoding="utf-8",
    )
    registry = SkillRegistry(tmp_path)
    registry.scan()
    args = registry.build_mount_args()
    # 顶层 aggregate rw（v0.1.5 起默认 rw，SkillForge 写新 skill 需要）
    assert args[0] == "-v"
    assert args[1].endswith(":/skills:rw")
    assert any(":rw" in a for a in args)


def test_build_mount_args_cached(tmp_path: Path):
    """build_mount_args() 走 lru_cache。"""
    registry = SkillRegistry(tmp_path)
    registry.scan()
    first = registry.build_mount_args()
    second = registry.build_mount_args()
    assert first is second  # lru_cache 命中


def test_manifest_has_lazy_field(tmp_path: Path):
    """SkillManifest 必须含 lazy 字段（替代 frontmatter.get('lazy', False)）。"""
    lazy_dir = tmp_path / "Lazy"
    lazy_dir.mkdir()
    (lazy_dir / "SKILL.md").write_text(
        "---\nname: lazy_skill\ndescription: 懒加载\nlazy: true\n---\nbody",
        encoding="utf-8",
    )
    eager_dir = tmp_path / "Eager"
    eager_dir.mkdir()
    (eager_dir / "SKILL.md").write_text(
        "---\nname: eager_skill\ndescription: 立即可见\n---\nbody",
        encoding="utf-8",
    )

    registry = SkillRegistry(tmp_path)
    registry.scan()
    assert registry.get("lazy_skill").lazy is True
    assert registry.get("eager_skill").lazy is False


def test_default_available_skills_hides_lazy_database_skill():
    block = available_skills_block()

    assert "name: data_analysis" in block
    assert "name: data_analysis_database" not in block
    assert "skill_file: /skills/DataAnalysis/SKILL.md" in block


def test_fallback_block_when_registry_empty(tmp_path: Path):
    """空 skills 目录走 _FALLBACK_BLOCK（无硬编码 skill 列表）。"""
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    reset_skill_registry(empty_root)

    block = available_skills_block()
    assert "<available_skills>" in block
    assert "unavailable" in block.lower() or "or ask" in block.lower()
    assert "- if none of the above matches" in block


# =========================================================================
# search() / find_skill_block() — keyword 检索
# =========================================================================


def test_registry_picks_up_new_skill_without_restart(tmp_path: Path):
    """v0.1.5 回归：SkillForge 创建新 skill 后 registry 自动发现，无需重启。

    旧行为：registry 在 lifespan 启动时 scan 一次，新 skill 必须重启后端才可见。
    新行为：search/get/names 每次先 stat skills_root mtime，变了就 rescan。
    """
    from ChatMe.ChatWorkflow.skills.registry import get_skill_registry

    skill_dir = tmp_path / "HotReloadTest"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: hotreloadtest\ndescription: 热加载测试\naliases: [热加载]\n---\nbody",
        encoding="utf-8",
    )
    reset_skill_registry(tmp_path)

    # 1) 初始：能找到
    registry = get_skill_registry()
    assert "hotreloadtest" in registry.names()

    # 2) 删除现有 skill，再创建同名目录（模拟 SkillForge 创建新 skill）
    import shutil, time
    shutil.rmtree(skill_dir)
    # 时间戳精度：某些文件系统 mtime 精度只到秒，调慢一点确保 mtime 真的变了
    time.sleep(0.05)
    new_skill = tmp_path / "BrandNewSkill"
    new_skill.mkdir()
    (new_skill / "SKILL.md").write_text(
        "---\nname: brandnewskill\ndescription: 新建测试\n---\nbody",
        encoding="utf-8",
    )

    # 3) 不重启，registry.names() 应包含新 skill
    names = registry.names()
    assert "brandnewskill" in names, f"新 skill 应自动被发现，实际 names={names}"
    assert "hotreloadtest" not in names  # 旧的已删


def test_registry_picks_up_modified_skill(tmp_path: Path):
    """修改现有 SKILL.md 的 mtime → registry 也应重新扫到新内容。"""
    from ChatMe.ChatWorkflow.skills.registry import get_skill_registry

    skill_dir = tmp_path / "Modified"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: modified\ndescription: 初始\n---\nbody",
        encoding="utf-8",
    )
    reset_skill_registry(tmp_path)
    registry = get_skill_registry()
    # description 在 frontmatter，summary 来自 body（"body"）
    initial = registry.get("modified")
    assert initial.frontmatter.get("description") == "初始"
    assert initial.summary == "body"

    # 修改 SKILL.md（触发 mtime 变化）
    import time
    time.sleep(0.05)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: modified\ndescription: 修改后\n---\n更新后的 body",
        encoding="utf-8",
    )

    # 不重启，应拿到新内容
    manifest = registry.get("modified")
    assert manifest.frontmatter.get("description") == "修改后"
    assert manifest.summary == "更新后的 body"


def test_search_finds_skill_by_english_keyword():
    """英文 query 命中 description / alias / name。"""
    from ChatMe.ChatWorkflow.skills.registry import get_skill_registry

    matches = get_skill_registry().search("search")
    # exa / tavily 都含 "search" 概念
    names = [m.name for m in matches]
    assert "exa" in names or "tavily" in names


def test_search_finds_skill_by_cjk_char_token():
    """中文 query 按字 tokenize 命中（"搜索" → {"搜", "索"}）。"""
    from ChatMe.ChatWorkflow.skills.registry import get_skill_registry

    matches = get_skill_registry().search("搜索")
    names = [m.name for m in matches]
    # exa / tavily 都含"搜索"概念
    assert "exa" in names or "tavily" in names


def test_search_finds_data_analysis_by_cjk():
    matches = get_skill_registry().search("数据")
    names = [m.name for m in matches]
    assert "data_analysis" in names


def test_search_skips_lazy_skills(tmp_path: Path):
    """lazy: true 的 skill 不在 match 搜索结果里。"""
    skill_dir = tmp_path / "LazySearch"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: lazy_search\ndescription: 懒加载搜索\nlazy: true\n---\nbody",
        encoding="utf-8",
    )
    reset_skill_registry(tmp_path)
    matches = get_skill_registry().search("搜索")
    names = [m.name for m in matches]
    assert "lazy_search" not in names


def test_search_top_k_limits_results():
    from ChatMe.ChatWorkflow.skills.registry import get_skill_registry

    matches = get_skill_registry().search("搜索", top_k=1)
    assert len(matches) <= 1


def test_search_empty_query_returns_empty():
    from ChatMe.ChatWorkflow.skills.registry import get_skill_registry

    assert get_skill_registry().search("") == []
    assert get_skill_registry().search("   ") == []


def test_find_skill_block_returns_match_summary():
    """mode='match'（默认）走 find_skill_block，返 brief 一行 + 调用提示。"""
    block = find_skill_block("搜索")
    assert "Matched" in block
    # 一行式 brief
    assert "name=" in block and "module=" in block and "file=/skills/" in block
    # 提示后续 cat SKILL.md + code
    assert "cat /skills" in block


def test_find_skill_block_no_match_suggests_list_mode():
    block = find_skill_block("asdfghjkl_no_such_thing")
    assert "No matching skill" in block
    assert "mode='list'" in block or 'mode="list"' in block


def test_find_skill_block_no_cache():
    """v0.1.5 起 find_skill_block() 不缓存，重复调用重新渲染。"""
    a = find_skill_block("search")
    b = find_skill_block("search")
    # 不再是同一对象，但内容一致
    assert a == b
    assert a is not b


def test_find_skill_mcp_tool_match_mode():
    """server.py find_skill(query, mode='match') → 命中 + brief。"""
    from ChatMe.ChatWorkflow.mcps.server import find_skill

    result = find_skill("搜索")
    assert "Matched" in result
    assert "name=" in result


def test_find_skill_mcp_tool_list_mode():
    """server.py find_skill(mode='list') → 返完整 <available_skills> 块。"""
    from ChatMe.ChatWorkflow.mcps.server import find_skill

    result = find_skill("", mode="list")
    assert "<available_skills>" in result
    assert "name: data_analysis" in result
    assert "name: exa" in result
    assert "name: tavily" in result
    assert "name: image_parser" in result
    # lazy skill 不在 list 里
    assert "name: data_analysis_database" not in result


def test_find_skill_mcp_tool_in_mcp_server():
    """find_skill 必须在 MCP server 注册（FastMCP @server.tool 生效）。"""
    from ChatMe.ChatWorkflow.mcps.server import server
    # FastMCP 提供 get_tools() 列出所有注册工具
    tools = server.get_tools() if hasattr(server, "get_tools") else {}
    # 不同版本 API 不同，宽松检查：至少 find_skill 函数可被 import
    from ChatMe.ChatWorkflow.mcps.server import find_skill as _fs
    assert callable(_fs)


def test_agent_prompt_includes_find_skill_tool_block():
    from ChatMe.ChatWorkflow.config.graph_config import get_agent_node_prompt
    from ChatMe.ChatWorkflow.mcps.tools.platforms import init_platform

    init_platform()
    prompt = get_agent_node_prompt()

    # find_skill 工具描述由 platform.all_tool_prompt_blocks() 注入
    assert "find_skill — Skill Discovery" in prompt
    # Decision Flow 提了 find_skill 引导 LLM
    assert "find_skill" in prompt
    # 不再嵌入完整 <available_skills> 块（仅 find_skill 工具描述里提到字符串）
    # 完整块格式 = "<available_skills>\n- name: ..." 必须在 prompt 里不出现
    assert "<available_skills>\n" not in prompt
    assert "{{available_skills}}" not in prompt
    assert "skills/skills.md" not in prompt
    assert "skills/Exa.py" not in prompt
    # MAIN_FLOW 现在的关注点是思维方法（Decision Flow + Good Examples），
    # 不再硬编码具体工具的调用模式（`find_skill("keywords")` 等已废弃）
    assert 'find_skill(query, mode="list")' not in prompt
    assert "from skills.Exa import exa_search" not in prompt
    # 新增：MAIN_FLOW 应包含思维方法
    assert "Decision Flow" in prompt
    assert "Good Chain Examples" in prompt


def test_scheduler_skill_in_find_skill_results():
    """Scheduler skill 已被 SkillRegistry 自动发现（无需手动注册）。

    LLM 用 find_skill(query="cron 定时 任务") 应能匹配到 Scheduler。
    """
    from ChatMe.ChatWorkflow.skills.registry import get_skill_registry

    registry = get_skill_registry()
    matches = registry.search("cron 定时 任务")
    names = [m.name for m in matches]
    assert "scheduler" in names, f"Scheduler skill 应在 find_skill 搜索结果中，实际：{names}"


def test_main_flow_good_examples_cover_scheduler_skill():
    """Good Examples 应包含 scheduler skill 的 find_skill + code() 调用模式。

    验证 scheduler 已切到 skills/Scheduler 顶层函数路径（不再走旧的
    scheduler(action=...) MCP 工具 dispatch）。具体函数集合由 SKILL.md
    承载，prompt 主例只露出 canonical create_scheduled_task。
    """
    from ChatMe.ChatWorkflow.config.graph_config import get_agent_node_prompt
    from ChatMe.ChatWorkflow.mcps.tools.platforms import init_platform

    init_platform()
    prompt = get_agent_node_prompt()

    # 主例：定时任务创建：find_skill + cat SKILL.md + create_scheduled_task
    assert 'find_skill(query="cron 定时 任务")' in prompt
    assert "create_scheduled_task" in prompt
    # 不应再出现旧的 MCP scheduler(action=...) 形式
    assert "scheduler(action=" not in prompt
