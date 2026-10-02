import functools
import re
from pathlib import Path
from typing import Optional

from ChatMe.ChatWorkflow.skills.manifest import SkillManifest, parse_frontmatter
from ChatMe.LoggingManager.logging_config import get_logger
from ChatMe.paths import SKILLS_ROOT

logger = get_logger("skill_registry")


def _snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _markdown_body(md_text: str) -> str:
    if not md_text.startswith("---"):
        return md_text.strip()
    lines = md_text.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
    return ""


def _summary(body: str, fallback: str) -> str:
    text = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800] or fallback


def _tokenize_for_search(text: str) -> set[str]:
    """Tokenize for keyword overlap scoring.

    - CJK 字符按字拆分（"深度搜索" → {"深", "度", "搜", "索"}）
    - ASCII 词按空格 / 标点切分（"code execution" → {"code", "execution"}）
    - 进一步按 `_` 和 camelCase 大写字母切分（"exa_search" → {"exa", "search"}）
      —— 这是为了函数名里出现的 search / image / parse 等子词能被 query 命中
    - **中英边界切分**（"做成excel表" → {"做", "成", "表", "excel"}）
      —— 真实 query 几乎全是中英混排，而上面的分隔符集合里没有 CJK，
      "帮我生成一个Excel表格" 会被当成**一个**整词、latin 部分整个丢掉：
      excel 不是 token → ExcelEditor 的 alias 永远命中不了。
      症状是 find_skill 查 "excel" 能中、查 "做成excel表" 却返回 DataAnalysis。
      静默失配比 0 命中更坏：0 命中会提示切 mode='list'，错命中不会，
      模型拿着错误的 top-3 就走了 —— 这正是"有时候反应过来有时候没反应过来"。
    """
    tokens: set[str] = set()
    for word in re.split(r"[\s,.;:!?()\"'\-/]+", text.lower()):
        if not word:
            continue
        # 中英边界切分：CJK 与 ASCII 字母数字的交界处断开
        for seg in re.split(r"(?<=[一-鿿])(?=[a-z0-9])|(?<=[a-z0-9])(?=[一-鿿])", word):
            if not seg:
                continue
            # camelCase + underscore split
            for sub in re.split(r"(?=[A-Z])|_+", seg):
                sub = sub.strip()
                if sub:
                    tokens.add(sub)
        # CJK char split
        for char in word:
            if '\u4e00' <= char <= '\u9fff':
                tokens.add(char)
    return tokens


def _search_signature(text: str) -> set[str]:
    """高区分度的检索签名：拉丁词 + CJK bigram。

    与 `_tokenize_for_search` 的区别是**丢弃 CJK 单字**。
    单字在中文里几乎没有区分度：别名 `数据表` 拆成 {数,据}，query
    "sqlite数据库" 同样含 {数,据} → ExcelEditor 靠噪声压过 data_analysis；
    而 `创建技能` 拆成 {创,建,技,能} 撞上 "做个天气技能" 又是蒙对。
    两种都是巧合，不是信号。bigram 才是词：`数据表`→{数据,据表}、
    `创建技能`→{创建,建技,技能}，前者不撞 "数据库"，后者正确命中 "技能"。

    单字仍留在 `_tokenize_for_search` 里参与基础打分（删了会改动既有权重），
    这里只给高权重的别名层提供干净的比较空间。

    ⚠️ bigram 必须**逐个别名**算，不能先把所有别名的 CJK 拼起来再切：
    "…Excel表格 数据表…" 拼成 "表格数据表" 后，跨边界的 `格数` / `据表`
    会成为根本不存在的伪词。
    """
    sig: set[str] = set()
    for raw in text.split():
        if not raw:
            continue
        sig |= {
            t for t in _tokenize_for_search(raw)
            if any(c.isascii() and c.isalnum() for c in t)
        }
        cjk = re.sub(r"[^一-鿿]", "", raw)
        sig |= {cjk[i:i + 2] for i in range(len(cjk) - 1)}
    return sig


class SkillRegistry:
    """扫描 backend/skills/ 下的所有 SKILL.md，构造 SkillManifest 列表。

    目录约定：每个 skill = 一个目录 + SKILL.md（含 YAML frontmatter）。
    顶层 SKILL.md 一律视为顶层 skill；更深层的 SKILL.md 也被识别但需带
    frontmatter（顶级无 frontmatter 走默认配置，子级必须显式声明）。
    """

    def __init__(self, skills_root: Path) -> None:
        self.skills_root = Path(skills_root).resolve()
        self._skills: dict[str, SkillManifest] = {}
        # 上次 scan 时每个 SKILL.md 的 mtime，用于检测磁盘变动（SkillForge
        # 创建 / 修改 skill 后无需重启后端即可被 find_skill 发现）。
        # macOS APFS 修改现有文件不更新父目录 mtime，所以必须按文件 stat。
        self._last_file_mtimes: dict[Path, float] = {}

    def scan(self) -> list[SkillManifest]:
        """Scan skills_root and populate the cached manifest dict. Idempotent."""
        manifests: dict[str, SkillManifest] = {}
        if not self.skills_root.is_dir():
            logger.warning(f"skills 目录不存在: {self.skills_root}")
            self._skills = manifests
            self._last_file_mtimes = {}
            return []

        # 顶层目录式 skill
        for skill_md in sorted(self.skills_root.glob("*/SKILL.md")):
            manifest = self._manifest_from_markdown(skill_md, require_frontmatter=False)
            if manifest:
                manifests[manifest.name] = manifest

        # 嵌套子目录（如 DataAnalysis/database/）—— 必须带 frontmatter
        for skill_md in sorted(self.skills_root.glob("*/**/SKILL.md")):
            if skill_md.parent.parent == self.skills_root:
                continue
            manifest = self._manifest_from_markdown(skill_md, require_frontmatter=True)
            if manifest:
                manifests[manifest.name] = manifest

        self._skills = manifests
        # 记录本次每个 SKILL.md 的 mtime，让 _maybe_rescan() 能识别「磁盘未变」
        self._last_file_mtimes = self._stat_all_skill_mds()
        return list(manifests.values())

    def _stat_all_skill_mds(self) -> dict[Path, float]:
        """Return {path: mtime} for every SKILL.md under skills_root. 找不到的视为 -1。"""
        result: dict[Path, float] = {}
        for skill_md in sorted(self.skills_root.glob("*/SKILL.md")):
            try:
                result[skill_md] = skill_md.stat().st_mtime
            except OSError:
                result[skill_md] = -1.0
        for skill_md in sorted(self.skills_root.glob("*/**/SKILL.md")):
            if skill_md.parent.parent == self.skills_root:
                continue
            try:
                result[skill_md] = skill_md.stat().st_mtime
            except OSError:
                result[skill_md] = -1.0
        return result

    def get(self, name: str) -> Optional[SkillManifest]:
        self._maybe_rescan()
        return self._skills.get(name)

    def names(self) -> list[str]:
        self._maybe_rescan()
        return list(self._skills)

    def search(self, query: str, top_k: int = 3) -> list[SkillManifest]:
        """Keyword-search against all (non-lazy) skill metadata.

        给 find_skill MCP tool 用：LLM 拿到 query 后匹配 description / summary /
        aliases / name，按 token overlap 评分排序返回 top_k。
        0 匹配返空列表（让 LLM 决定切 mode='list'）。

        Example:
            registry.search("搜索") → [exa, tavily]  (CJK char-token 命中)
            registry.search("mysql") → [data_analysis]  (alias 命中)
        """
        self._maybe_rescan()
        if not query or not query.strip():
            return []
        query_tokens = _tokenize_for_search(query)
        if not query_tokens:
            return []
        query_sig = _search_signature(query)

        scored: list[tuple[SkillManifest, int]] = []
        for skill in self._skills.values():
            if skill.lazy:
                continue
            corpus = " ".join([
                skill.name,
                str(skill.frontmatter.get("description", "")),
                skill.summary,
                " ".join(skill.import_aliases),
            ])
            corpus_tokens = _tokenize_for_search(corpus)
            # token overlap 为主，substring 命中为辅（兜底 edge case）
            token_hits = len(query_tokens & corpus_tokens)
            substring_bonus = 1 if query.lower() in corpus.lower() else 0
            score = token_hits * 2 + substring_bonus
            # 名字 / 别名命中额外加权。
            # Why：CJK 按字拆开后噪声极大 —— "做成excel表" 的 token 是
            # {做,成,表,excel}，前三字在半数 skill 的中文 description 里都出现，
            # 而 excel 只命中 1 个。按基础算法 ExcelEditor 拿 2 分，
            # DataAnalysis 靠零散 CJK 字拿 8 分，Excel 被挤出 top-3。
            # 别名是作者显式声明的"我叫什么名字"，信噪比远高于描述里的常用字。
            # 用 _search_signature（拉丁词 + CJK bigram）比较，见其 docstring。
            if query_sig & _search_signature(
                f"{skill.name} {' '.join(skill.import_aliases)}"
            ):
                score += 6
            if score > 0:
                scored.append((skill, score))

        scored.sort(key=lambda x: (-x[1], x[0].name))
        return [skill for skill, _ in scored[:top_k]]

    def _maybe_rescan(self) -> None:
        """若任意 SKILL.md mtime 变了（SkillForge 新建/修改/删除 skill），自动 rescan。

        macOS APFS 修改现有文件不更新父目录 mtime，所以必须按每个 SKILL.md
        自己 stat（O(n) 但 n ≤ 几十，仍比 glob+读文件便宜两个数量级）。
        """
        current = self._stat_all_skill_mds()
        if current != self._last_file_mtimes:
            self.scan()
            # scan() 已经更新了 _last_file_mtimes

    @functools.lru_cache(maxsize=1)
    def build_mount_args(self) -> list[str]:
        """Build aggregate read-only mount plus explicit writable overrides.

        The aggregate /skills mount is required for legacy imports such as
        ``from Exa import exa_search``. Do not remove it without migrating all
        alias-style imports and PYTHONPATH behavior first.

        缓存：registry 启动后只读，重复调用直接返回同一 list。

        注：若调用方未先 scan()（如 CodeSandboxPool 临时建 registry 走 mount），
        第一次调用会 lazy scan 一次再 cache。
        """
        if not self._skills:
            self.scan()
        args = ["-v", f"{self.skills_root}:/skills:rw"]
        writable_paths = sorted(
            {skill.path.resolve() for skill in self._skills.values() if skill.mount_mode == "rw"},
            key=lambda path: (len(path.parts), str(path)),
        )
        mounted: list[Path] = []
        for host_path in writable_paths:
            if any(host_path.is_relative_to(parent) for parent in mounted):
                continue
            relative_path = host_path.relative_to(self.skills_root)
            args.extend(["-v", f"{host_path}:/skills/{relative_path.as_posix()}:rw"])
            mounted.append(host_path)
        return args

    def _manifest_from_markdown(
        self,
        skill_md: Path,
        require_frontmatter: bool,
    ) -> Optional[SkillManifest]:
        try:
            md_text = skill_md.read_text(encoding="utf-8")
            frontmatter = parse_frontmatter(md_text)
        except (OSError, UnicodeError, ValueError) as exc:
            logger.warning(f"跳过无法解析的 skill {skill_md}: {exc}")
            return None

        if require_frontmatter and not frontmatter:
            return None

        directory_name = skill_md.parent.name
        name = str(frontmatter.get("name") or _snake_case(directory_name))
        description = str(frontmatter.get("description") or "").strip()
        if frontmatter and (not name or not description):
            logger.warning(f"跳过缺少 name/description 的 skill: {skill_md}")
            return None

        mount_mode = str(frontmatter.get("mount", "ro")).lower()
        if mount_mode not in {"ro", "rw"}:
            logger.warning(f"跳过 mount 非法的 skill {skill_md}: {mount_mode}")
            return None

        aliases = frontmatter.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
            logger.warning(f"跳过 aliases 非法的 skill: {skill_md}")
            return None

        module_path = str(
            frontmatter.get("module")
            or f"skills.{skill_md.parent.relative_to(self.skills_root).as_posix().replace('/', '.')}"
        )
        body = _markdown_body(md_text)
        return SkillManifest(
            name=name,
            path=skill_md.parent,
            frontmatter=frontmatter,
            summary=_summary(body, description or directory_name),
            mount_mode=mount_mode,
            lazy=bool(frontmatter.get("lazy", False)),
            import_aliases=aliases,
            module_path=module_path,
        )


_DEFAULT_SKILLS_ROOT = SKILLS_ROOT  # alias：保留旧名字避免外部代码引用 _DEFAULT_SKILLS_ROOT 时破坏
_registry: Optional[SkillRegistry]
try:
    _registry = SkillRegistry(_DEFAULT_SKILLS_ROOT)
    _registry.scan()
except Exception as exc:
    logger.warning(f"初始化 SkillRegistry 失败: {exc}")
    _registry = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry(_DEFAULT_SKILLS_ROOT)
        _registry.scan()
    return _registry


def reset_skill_registry(skills_root: Optional[Path] = None) -> SkillRegistry:
    """Test-only: rebuild the singleton with a fresh skills_root.

    同步清掉 build_mount_args lru_cache（mount args 跟目录绑定）。
    available_skills_block / find_skill_block 已经在 v0.1.5 去掉 lru_cache，
    每次调用自动走 mtime check，不需要清。
    """
    global _registry
    _registry = SkillRegistry(skills_root or _DEFAULT_SKILLS_ROOT)
    _registry.scan()
    _registry.build_mount_args.cache_clear()
    return _registry
