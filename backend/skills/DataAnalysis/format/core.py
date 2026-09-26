"""数据分析落盘与校验入口（详见 SKILL.md）。"""
import fcntl
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import requests

from skills._shared._skill_help import _HelpMeta, auto_attach_help_module as _auto_attach_help_module


# 沙盒容器标记：Docker 容器内必有此文件
_DOCKERENV_MARKER = "/.dockerenv"


def _is_sandbox() -> bool:
    """是否运行在沙盒容器内（通过 /.dockerenv 标记判定）"""
    return os.path.exists(_DOCKERENV_MARKER)


def _format_check_error(status_code, exception, path, url, port) -> str:
    """统一错误信息格式：`[类型] 描述 | 建议`（AI-friendly）。"""
    if exception is not None:
        exc_name = type(exception).__name__
        exc_msg = str(exception)
        if "Connection" in exc_name or "refused" in exc_msg.lower():
            return (
                f"[后端未连通] 无法连接 {url} | 检查后端服务 (port {port}) 是否启动，"
                f"可通过 LINGXI_BACKEND_HOST/LINGXI_BACKEND_PORT 环境变量覆盖"
            )
        if "timeout" in exc_name.lower() or "timeout" in exc_msg.lower():
            return "[请求超时] 5 秒内未响应 | 网络较慢或后端无响应，可稍后重试"
        return (
            f"[网络异常] {exc_name}: {exc_msg} | "
            f"检查网络连接和后端服务状态"
        )
    if status_code == 400:
        return (
            f"[路径格式错误] {path} | "
            f"合法示例: cached/'session_id'/data_analysis/gen_001/xxx/xxx.png |"
            f"路径要符合规范[[path]]后续引用语法"
        )
    if status_code == 403:
        return (
            f"[访问被拒] {path} | "
            f"合法路径模板:cached/'session_id'/data_analysis/... |"
            f"路径要符合规范[[path]]后续引用语法"
        )
    if status_code == 404:
        return (
            f"[文件不存在] {path} | "
            f"完整文件路径示例:cached/'session_id'/data_analysis/gen_001/xxx/xxx.suffix |"
            f"路径要符合规范[[path]]引用语法"
        )
    if status_code == 500:
        return "[服务端异常] HTTP 500"
    if status_code and status_code >= 400:
        return f"[HTTP 错误] status_code={status_code}"
    return f"[未知错误] status_code={status_code}"


class ChatDataAnalysisFormat(metaclass=_HelpMeta):
    """详见 `backend/skills/DataAnalysis/SKILL.md`。详细 help("ChatDataAnalysisFormat")。"""

    def __init__(self, session_id: str):
        """初始化数据分析落盘实例。

        Args:
            session_id: 会话 ID（32 或 12 位 hex），用于组织输出目录
        """
        self.session_id = session_id
        self._base_dir: Optional[Path] = None
        self._generation: Optional[str] = None

    # --------------------------------------------------------
    # 路径 & generation 管理
    # --------------------------------------------------------

    @property
    def base_dir(self) -> Path:
        """输出根目录：`<cwd>/cached/{session_id}/data_analysis`。

        Returns:
            Path 对象（首次访问时 lazy 创建）
        """
        if self._base_dir is None:
            self._base_dir = Path.cwd() / "cached" / self.session_id / "data_analysis"
        return self._base_dir

    @property
    def meta_path(self) -> Path:
        """`_meta.json` 路径（generation 计数器持久化文件）。"""
        return self.base_dir / "_meta.json"

    @contextmanager
    def _meta_file_locked(self):
        """独占 fcntl 锁打开 _meta.json —— read+write 必须在同一 `with` 内完成，避免 TOCTOU。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        f = open(self.meta_path, "a+")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield f
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()

    def _init_gen_if_needed(self) -> int:
        """meta 不存在或 gen<=0 时初始化为 1，返回当前 gen。"""
        with self._meta_file_locked() as f:
            f.seek(0)
            content = f.read()
            current = json.loads(content).get("generation", 0) if content else 0
            if current <= 0:
                current = 1
                f.seek(0)
                f.truncate()
                json.dump({"generation": current}, f)
            return current

    def new_generation(self) -> str:
        """自增 generation 计数器并返回新批次名。

        Returns:
            形如 `"gen_001"` / `"gen_002"` 的 3 位零填充批次名

        Example:
            gen = da.new_generation()  # "gen_002"
        """
        with self._meta_file_locked() as f:
            f.seek(0)
            content = f.read()
            current = json.loads(content).get("generation", 0) if content else 0
            new_gen = (current + 1) if current > 0 else 1
            f.seek(0)
            f.truncate()
            json.dump({"generation": new_gen}, f)
            return f"gen_{new_gen:03d}"

    @property
    def generation(self) -> str:
        """当前 generation 名（首次访问懒加载或创建 gen_001，不自增）。

        Returns:
            形如 `"gen_001"` 的 3 位零填充批次名

        Example:
            # 复用同一批次（不会自增）
            gen = da.generation  # "gen_001"
            gen = da.generation  # 仍是 "gen_001"
        """
        if self._generation is None:
            self._generation = f"gen_{self._init_gen_if_needed():03d}"
        return self._generation

    @generation.setter
    def generation(self, value: str) -> None:
        """手动覆写当前 generation 引用（一般无需调用）。"""
        self._generation = value

    @property
    def output_dir(self) -> str:
        """当前 generation 目录绝对路径（str 形式）。

        首次访问时懒加载并初始化为 `gen_001`，不自增。

        Returns:
            形如 `"<cwd>/cached/{sid}/data_analysis/gen_001"`

        Example:
            out = da.output_dir  # ".../data_analysis/gen_001"
        """
        return str(self.get_current_generation_dir())

    def get_current_generation_dir(self) -> Path:
        """当前 generation 目录 Path 对象（懒加载 generation）。

        Returns:
            `self.base_dir / self.generation`
        """
        return self.base_dir / self.generation

    # --------------------------------------------------------
    # 静态工具
    # --------------------------------------------------------

    @staticmethod
    def get_file_dir(path: str | Path) -> Path:
        """解析输入文件绝对路径，必要时在 `cached/` 下递归查找。

        1. 路径已存在 → 直接返回
        2. 不存在 → 在 `<cwd>/cached/` 下按文件名 `rglob` 找
        3. 仍找不到 → 抛 `FileNotFoundError`

        Args:
            path: 原始路径（绝对 / 相对均可）

        Returns:
            Path 对象（绝对路径）

        Raises:
            FileNotFoundError: 路径不存在且 `cached/` 下无同名文件

        Example:
            INPUT = ChatDataAnalysisFormat.get_file_dir(
                "cached/{sid}/datasets/q1.csv"
            )
        """
        if isinstance(path, str):
            path = Path(path)

        if path.exists():
            return path

        for match in (Path.cwd() / "cached").rglob(path.name):
            return match

        raise FileNotFoundError(f"找不到文件: {path.name}")

    @staticmethod
    def get_data_analysis_header() -> str:
        """生成 `warnings.filterwarnings` 抑制 header（prepend 到 `code()` 入参顶部）。

        Returns:
            多行 Python 字符串（直接 `+` 拼接到 `code()` 头部即可）

        Example:
            code = da.get_data_analysis_header() + "..."
        """
        return (
            "import warnings\n"
            "warnings.filterwarnings('ignore', category=FutureWarning)\n"
            "warnings.filterwarnings('ignore', category=DeprecationWarning)\n"
            "warnings.filterwarnings('ignore', category=UserWarning)\n"
            "warnings.filterwarnings('ignore', category=RuntimeWarning)\n"
        )

    @staticmethod
    def get_fonts_setup_header() -> str:
        """字体注册 header —— matplotlib / seaborn / pandas 绘图前自动加载字体。

        seaborn / pandas 都走 matplotlib backend，`rcParams['font.sans-serif']` 对三者都生效。

        同时尝试 4 个路径（按顺序，去重；目录不存在 no-op 不报错）：
          1. `/skills/DataAnalysis/fonts`（沙盒 mount 主路径，**推荐**）
          2. `<cwd>/skills/DataAnalysis/fonts`（本地 venv，cwd=backend/）
          3. `/cached/.fonts`（legacy 沙盒挂载点）
          4. `<cwd>/cached/.fonts`（legacy 本地 venv）
        把字体文件放到 `backend/skills/DataAnalysis/fonts/`（推荐）—— 随 skill 自动进
        git、自动 mount 到容器内 `/skills/DataAnalysis/fonts/`，无需任何额外配置。
        legacy `cached/.fonts/` 保留作为老部署兼容。

        推荐单文件 `NotoSansSC-Regular.otf`（~5-7MB，SIL OFL，无授权商用）：
          https://github.com/notofonts/noto-cjk/tree/main/Sans/SubsetOTF/SC

        ⚠️ 不要装 MiSans / HarmonyOS Sans SC / OPPO Sans / 阿里普惠体（商用需单独授权）。

        字体目录不存在时 no-op，不影响绘图。
        """
        return (
            "import os\n"
            "import matplotlib\n"
            "import matplotlib.pyplot as plt\n"
            "try:\n"
            "    import matplotlib.font_manager as fm\n"
            "    _font_dirs = [\n"
            "        '/skills/DataAnalysis/fonts',\n"
            "        os.path.join(os.getcwd(), 'skills', 'DataAnalysis', 'fonts'),\n"
            "        '/cached/.fonts',\n"
            "        os.path.join(os.getcwd(), 'cached', '.fonts'),\n"
            "    ]\n"
            "    for _font_dir in dict.fromkeys(_font_dirs):\n"
            "        if not os.path.isdir(_font_dir):\n"
            "            continue\n"
            "        for _f in os.listdir(_font_dir):\n"
            "            if _f.lower().endswith(('.ttf', '.otf', '.ttc')):\n"
            "                try:\n"
                    "                    fm.fontManager.addfont(os.path.join(_font_dir, _f))\n"
                    "                except Exception:\n"
                    "                    pass\n"
            "    plt.rcParams['font.sans-serif'] = ['Noto Sans SC', 'DejaVu Sans']\n"
            "    plt.rcParams['font.family'] = 'sans-serif'\n"
            "    plt.rcParams['axes.unicode_minus'] = False\n"
            "except Exception:\n"
            "    pass\n"
        )

    @staticmethod
    def check_static_file(path: str) -> dict:
        """验证 `path` 是否可通过 `/static/` 接口访问。

        用途：保存完图表后做一次 HTTP 探活，确认前端 `/static/path` 真能取到文件
        （防止 AI 写错路径 / 服务端未启动 / 文件未真生成）。

        Args:
            path: 相对 `/static/` 的路径，如
                `"cached/{sid}/data_analysis/gen_001/charts/xxx.png"`

        Returns:
            dict 含 `url / accessible / status_code / content_type / error`
            - `accessible`: `True` 表示 HTTP 200
            - `error`: 失败时统一为 `"[类型] 描述 | 建议"`，AI 可直接 parse

        Raises:
            无（网络异常被捕获转为 `error` 字段）

        Example:
            result = da.check_static_file("cached/{sid}/data_analysis/gen_001/charts/x.png")
            if not result["accessible"]:
                print(result["error"])
        """
        # 沙盒用 host.docker.internal，本机用 127.0.0.1
        host = os.getenv("LINGXI_BACKEND_HOST", "host.docker.internal" if _is_sandbox() else "127.0.0.1")
        port = os.getenv("LINGXI_BACKEND_PORT", "38211")
        url = f"http://{host}:{port}/static/{path}"

        try:
            resp = requests.get(url, timeout=5)
            accessible = resp.status_code == 200
            return {
                "url": url,
                "accessible": accessible,
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type"),
                "error": None if accessible else _format_check_error(
                    status_code=resp.status_code,
                    exception=None,
                    path=path,
                    url=url,
                    port=port,
                ),
            }
        except Exception as e:
            return {
                "url": url,
                "accessible": False,
                "status_code": None,
                "content_type": None,
                "error": _format_check_error(
                    status_code=None,
                    exception=e,
                    path=path,
                    url=url,
                    port=port,
                ),
            }

    # --------------------------------------------------------
    # 保存
    # --------------------------------------------------------

    def save_script(self, code: str, filename: str | None = None) -> str:
        """保存执行过的代码脚本到 `gen_xxx/scripts/`（AI 可追溯）。

        Args:
            code: 完整 Python 源码字符串（建议传 `code()` 入参，便于回溯）
            filename: 文件名（默认 `script_{timestamp}.py`），缺省时按 unix ts 自动生成避免冲突

        Returns:
            保存后的磁盘绝对路径

        Example:
            path = da.save_script(code)  # ".../scripts/script_1737000000.py"
        """
        scripts_dir = self.base_dir / self.generation / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            filename = f"script_{int(time.time())}.py"

        script_path = scripts_dir / filename
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        return str(script_path)

    def save_data(self, content: str, filename: str) -> str:
        """保存文本数据到 `gen_xxx/data/`（CSV / JSON / TXT 等）。

        Args:
            content: 文本内容（字符串，非二进制）
            filename: 文件名，**必须含后缀**（`.csv` / `.json` / `.txt` / ...）

        Returns:
            磁盘绝对路径（形如 `<cwd>/cached/{sid}/data_analysis/gen_001/data/{filename}`）

        Raises:
            无（`filename` 缺后缀时不抛错，但前端无法识别文件类型）

        Example:
            path = da.save_data(df.to_csv(index=False), "q1_summary.csv")
        """
        data_dir = self.get_current_generation_dir() / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        data_path = data_dir / filename
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(content)

        return str(data_path)

    def save_path(self, src_path: str, target_subdir: str = "exports", *,
                  action: str = "mv", filename: str | None = None) -> str:
        """归档二进制 / 任意文件到 `gen_xxx/{target_subdir}/`。

        用途：保存 WordEditor / ExcelEditor 产物（`.xlsx` / `.docx`），或 `cp` / `mv`
        沙盒内已有的任意文件。`save_report` / `save_data` 只支持文本，二进制文件必须用本方法。

        Args:
            src_path: 源文件绝对路径（沙盒内）
            target_subdir: 目标子目录名（默认 `"exports"`，可自定义 `"work"` / `"attachments"` 等）
            action: `"cp"` 复制 / `"mv"` 移动（默认 `"mv"`，移走后源文件被删除）
            filename: 重命名（默认保留 `src_path` 的 basename）

        Returns:
            目标磁盘绝对路径

        Raises:
            ValueError: `action` 不是 `"cp"` / `"mv"`
            FileNotFoundError: `src_path` 不存在

        Example:
            path = da.save_path("/work/report.docx", "exports")
        """
        if action not in ("cp", "mv"):
            raise ValueError(f"action 必须是 'cp' 或 'mv'，收到: {action!r}")

        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"源文件不存在: {src_path}")

        target_dir = self.get_current_generation_dir() / target_subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        target_name = filename or src.name
        target_path = target_dir / target_name

        if action == "cp":
            shutil.copy2(src, target_path)
        else:
            shutil.move(str(src), str(target_path))

        return str(target_path)

    def save_report(self, content: str, filename: str, mode: str = "w") -> str:
        """保存 Markdown / 文本到 `gen_xxx/reports/`。

        长报告分块写入避免超 LLM max_tokens：先 `mode="w"` 写开头，再多次 `mode="a"` 续写。

        Args:
            content: 文本内容（建议 Markdown）
            filename: 文件名（建议 `.md` 后缀）
            mode: `"w"` 覆盖写入（默认）/ `"a"` 续写

        Returns:
            保存后的磁盘绝对路径

        Raises:
            ValueError: `mode` 不是 `"w"` / `"a"`

        Example:
            da.save_report(intro, "report.md")
            da.save_report(section, "report.md", mode="a")
        """
        if mode not in ("w", "a"):
            raise ValueError(f"save_report mode 必须是 'w' 或 'a'，收到: {mode}")

        reports_dir = self.get_current_generation_dir() / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_path = reports_dir / filename
        with open(report_path, mode, encoding="utf-8") as f:
            f.write(content)

        return str(report_path)

    # --------------------------------------------------------
    # Mermaid 语法校验与保存
    # --------------------------------------------------------

    @staticmethod
    def validate_mermaid(code: str) -> tuple[bool, str]:
        """校验 Mermaid 语法（语法级别，不渲染）。

        Args:
            code: Mermaid 代码字符串

        Returns:
            `(是否合法, 错误信息)`；合法时第二项为 `"语法合格"`
        """
        if not code or not code.strip():
            return False, "Mermaid 代码为空"

        # 去除代码块包裹符号
        code = code.strip()
        code = re.sub(r'^```(?:mermaid)?\s*', '', code, flags=re.IGNORECASE)
        code = re.sub(r'\s*```$', '', code)

        graph_types = [
            'graph', 'flowchart', 'flowchart-v2',
            'stateDiagram', 'stateDiagram-v2',
            'erDiagram', 'sequenceDiagram', 'classDiagram', 'pie',
            'gantt', 'gitGraph', 'requirementDiagram'
        ]
        has_graph_type = any(
            f"{gt} " in code or f"{gt}\n" in code
            for gt in graph_types
        )
        if not has_graph_type:
            return False, "缺少图类型声明（如 graph, flowchart, erDiagram...）"

        # erDiagram 的 { } 是实体属性定义语法，不校验；其他图类型才校验括号配对
        is_erdiagram = any(f"{gt} " in code or f"{gt}\n" in code for gt in ['erDiagram'])
        bracket_pairs = [('{', '}'), ('[', ']'), ('(', ')')] if not is_erdiagram else [('[', ']'), ('(', ')')]
        for open_, close in bracket_pairs:
            if code.count(open_) != code.count(close):
                return False, f"{open_}{close} 括号不匹配"

        nodes = re.findall(r'\b([A-Za-z0-9_]+)\[', code)
        if len(nodes) != len(set(nodes)):
            return False, "节点ID重复定义"

        return True, "语法合格"

    def save_mermaid(self, code: str, filename: str) -> str:
        """保存 Mermaid 图表到 `gen_xxx/charts/`，自动校验语法。

        Args:
            code: Mermaid 代码（可包含 ```mermaid 包裹，会自动剥掉）
            filename: 文件名，缺 `.mmd` 后缀自动补

        Returns:
            保存后的磁盘绝对路径

        Raises:
            ValueError: Mermaid 语法错误（缺失图类型 / 括号不配对 / 节点 ID 重复）

        Example:
            path = da.save_mermaid("graph LR; A-->B", "flow.mmd")
        """
        ok, msg = self.validate_mermaid(code)
        if not ok:
            raise ValueError(f"Mermaid 语法错误: {msg}")

        charts_dir = self.get_current_generation_dir() / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith('.mmd'):
            filename += '.mmd'

        mermaid_path = charts_dir / filename
        mermaid_path.write_text(code, encoding="utf-8")
        return str(mermaid_path)

    # --------------------------------------------------------
    # 删除
    # --------------------------------------------------------

    def remove_dir(self, generation: str) -> None:
        """删除指定 generation 目录（如 `"gen_001"`），不存在则 no-op。"""
        remove_generated_dir = self.base_dir / generation
        if remove_generated_dir.exists():
            shutil.rmtree(remove_generated_dir)


# ============================================================================
# help() / doc() —— AI 按需查函数详细用法
# ============================================================================

def doc(name=None):
    """查询本 skill 的函数 / 类 / 方法 docstring。

    Args:
        name: None 列出全部；str 返回该目标的完整 docstring
            （链式如 `"ChatDataAnalysisFormat.save_data"`）

    Returns:
        字符串（直接 print 即可看）

    用法:
        from skills.DataAnalysis.format import help
        help()                                            # 全部函数 / 类签名
        help("ChatDataAnalysisFormat")                    # 类详情 + 方法列表
        help("ChatDataAnalysisFormat.save_data")          # 单个方法详细用法
    """
    import sys
    from skills._shared._skill_help import skill_help
    return skill_help(sys.modules[__name__], name)


def help(name=None):
    """`doc()` 别名。"""
    return doc(name)


# 自动给模块顶层 callable 挂 .help 属性（类方法由 _HelpMeta 在类创建时挂）
_auto_attach_help_module(sys.modules[__name__])