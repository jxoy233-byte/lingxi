"""数据分析落盘与校验入口（详见 SKILL.md）。"""
import fcntl
import json
import os
import re
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import requests


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
                f"可通过 CHATME_BACKEND_HOST/CHATME_BACKEND_PORT 环境变量覆盖"
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


class ChatDataAnalysisFormat:
    """详见 `backend/skills/DataAnalysis/SKILL.md`。"""

    def __init__(self, session_id: str):
        """session_id: 会话 ID，用于组织输出目录。"""
        self.session_id = session_id
        self._base_dir: Optional[Path] = None
        self._generation: Optional[str] = None

    # --------------------------------------------------------
    # 路径 & generation 管理
    # --------------------------------------------------------

    @property
    def base_dir(self) -> Path:
        """输出根目录（Path）：`cached/{session_id}/data_analysis`。"""
        if self._base_dir is None:
            self._base_dir = Path.cwd() / "cached" / self.session_id / "data_analysis"
        return self._base_dir

    @property
    def meta_path(self) -> Path:
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
        """自增 generation 计数器，返回 "gen_001" / "gen_002" / ...。"""
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
        """懒加载当前 generation（首次访问时获取或创建 gen_001，不自增）。"""
        if self._generation is None:
            self._generation = f"gen_{self._init_gen_if_needed():03d}"
        return self._generation

    @generation.setter
    def generation(self, value: str) -> None:
        self._generation = value

    @property
    def output_dir(self) -> str:
        """当前 generation 目录路径（str），首次访问时初始化为 gen_001，不自增。"""
        return str(self.get_current_generation_dir())

    def get_current_generation_dir(self) -> Path:
        return self.base_dir / self.generation

    # --------------------------------------------------------
    # 静态工具
    # --------------------------------------------------------

    @staticmethod
    def get_file_dir(path: str | Path) -> Path:
        """路径存在则直接返回；否则在 `cached/` 下按文件名递归查找。"""
        if isinstance(path, str):
            path = Path(path)

        if path.exists():
            return path

        for match in (Path.cwd() / "cached").rglob(path.name):
            return match

        raise FileNotFoundError(f"找不到文件: {path.name}")

    @staticmethod
    def get_data_analysis_header() -> str:
        """warning 抑制 header（prepend 到 code() 入参顶部，省 token）。"""
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

        同时尝试两个路径（沙盒 + 本地 venv 降级，二选一即可）：
          - `/cached/.fonts`（沙盒挂载点）
          - `<cwd>/cached/.fonts`（本地 venv，cwd=backend/）
        把字体文件放到 host `backend/cached/.fonts/`，两种模式都自动注册。

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
            "    _font_dirs = ['/cached/.fonts', os.path.join(os.getcwd(), 'cached', '.fonts')]\n"
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
        """验证 path 是否可通过 /static/ 接口访问（防止 AI 写错路径 / 服务端未启动）。

        path: 相对 /static/ 的路径，如 `cached/{sid}/data_analysis/gen_001/charts/xxx.png`。
        返回 dict 含 `url / accessible / status_code / content_type / error`。
        `error` 失败时统一为 `[类型] 描述 | 建议`，AI 可直接 parse。
        """
        # 沙盒用 host.docker.internal，本机用 127.0.0.1
        host = os.getenv("CHATME_BACKEND_HOST", "host.docker.internal" if _is_sandbox() else "127.0.0.1")
        port = os.getenv("CHATME_BACKEND_PORT", "8211")
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
        """保存脚本到 `scripts/`，filename 默认按时间戳生成。"""
        scripts_dir = self.base_dir / self.generation / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            filename = f"script_{int(time.time())}.py"

        script_path = scripts_dir / filename
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        return str(script_path)

    def save_data(self, content: str, filename: str) -> str:
        """保存文本数据到 `data/`，filename 需含后缀（.csv / .json / .txt ...）。"""
        data_dir = self.get_current_generation_dir() / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        data_path = data_dir / filename
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(content)

        return str(data_path)

    def save_report(self, content: str, filename: str, mode: str = "w") -> str:
        """保存 Markdown / 文本到 `reports/`，`mode="a"` 续写。

        长报告分块写入避免超 LLM max_tokens：
            da.save_report(intro, "report.md")                # mode="w"
            da.save_report(section, "report.md", mode="a")   # 续写
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
        """校验 mermaid 语法，返回 (是否合法, 错误信息)。"""
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
        """保存 mermaid 到 `charts/`，filename 缺 `.mmd` 后缀自动补；语法校验失败抛 ValueError。"""
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