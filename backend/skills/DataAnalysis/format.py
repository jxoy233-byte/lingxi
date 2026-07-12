"""
数据分析技能规范模块
- 提供在数据分析目录下操作所需要进行的*操作规范*
- 提供数据分析所需要相关的*配置规范*
"""
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
    """统一 AI-friendly 错误信息格式：`[类型] 描述 | 建议`

    - HTTP 访问层错误（400/403/404）→ 额外附带 path 字符串语法诊断
    - 网络层 / 服务端错误 → 维持通用建议
    """
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
    """
    数据分析技能（DataAnalysis）会话级落盘与校验入口。

    *默认执行路径工作目录就可以了 '/'*

    详见 `backend/skills/DataAnalysis/SKILL.md`。
    """

    def __init__(self, session_id: str):
        """
        初始化数据分析配置

        Args:
            session_id: 会话 ID，用于组织输出目录
        """
        self.session_id = session_id
        self._base_dir: Optional[Path] = None
        self._generation: Optional[str] = None

    # --------------------------------------------------------
    # 路径 & generation 管理
    # --------------------------------------------------------

    @property
    def base_dir(self) -> Path:
        """获取输出根目录（Path）"""
        if self._base_dir is None:
            self._base_dir = Path.cwd() / "cached" / self.session_id / "data_analysis"
        return self._base_dir

    @property
    def meta_path(self) -> Path:
        return self.base_dir / "_meta.json"

    @contextmanager
    def _meta_file_locked(self):
        """
        以独占 fcntl 锁打开 _meta.json。

        ⚠️ read + write 必须在同一个 `with` 块内完成（不要拆出 _read_meta /
        _write_meta 两个方法），否则多进程并发自增时两个调用之间会引入
        TOCTOU 窗口，导致丢更新。
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        f = open(self.meta_path, "a+")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield f
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()

    def _init_gen_if_needed(self) -> int:
        """
        若 _meta.json 不存在或 gen<=0 则写入 1；返回当前 gen（>=1）。
        同一把 fcntl 锁内完成 read+write，原子。
        """
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
        """
        开启新的一次分析调用（自增并写回 _meta.json），返回 generation_id。

        Returns:
            "gen_001", "gen_002" ...

        同一把 fcntl 锁内完成 read+modify+write，原子；
        多进程并发不会丢更新。
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
        """获取当前 generation，懒加载（首次访问时获取或创建 gen_001，不自增计数器）"""
        if self._generation is None:
            self._generation = f"gen_{self._init_gen_if_needed():03d}"
        return self._generation

    @generation.setter
    def generation(self, value: str) -> None:
        self._generation = value

    @property
    def output_dir(self) -> str:
        """当前 generation 目录路径（str）。

        首次访问时若 meta 不存在则初始化为 gen_001，不自增。
        替代旧的 `get_config()["output_dir"]` 用法：

            OUTPUT_DIR = da.output_dir
        """
        return str(self.get_current_generation_dir())

    def get_current_generation_dir(self) -> Path:
        return self.base_dir / self.generation

    # --------------------------------------------------------
    # 静态工具
    # --------------------------------------------------------

    @staticmethod
    def get_file_dir(path: str | Path) -> Path:
        """
        获取文件的路径

        规则:
        - 路径存在：直接返回
        - 路径不存在：在 backend/cached/ 下递归搜索文件名

        Args:
            path: 文件路径（绝对路径或文件名）

        Returns:
            文件路径
        """
        if isinstance(path, str):
            path = Path(path)

        if path.exists():
            return path

        # 路径不存在，递归搜索文件名
        backend_dir = Path.cwd() / "cached"

        for match in backend_dir.rglob(path.name):
            return match

        raise FileNotFoundError(f"找不到文件: {path.name}")

    @staticmethod
    def get_data_analysis_header() -> str:
        """
        获取数据分析代码的通用 header 字符串

        在 AI 生成的代码字符串顶部拼接此 header，可抑制常见的
        FutureWarning / DeprecationWarning / UserWarning / RuntimeWarning
        等无关紧要的警告。这些警告在 pandas / numpy / matplotlib / sklearn
        等库执行时频繁出现，会污染 stdout、挤占 token 预算。

        Returns:
            可直接 prepend 到 code() 入参代码串的 Python header（不含末尾换行）

        示例：
            from skills.DataAnalysis import ChatDataAnalysisFormat
            header = ChatDataAnalysisFormat.get_data_analysis_header()
            code = header + "\\n" + user_code
        """
        return (
            "import warnings\n"
            "warnings.filterwarnings('ignore', category=FutureWarning)\n"
            "warnings.filterwarnings('ignore', category=DeprecationWarning)\n"
            "warnings.filterwarnings('ignore', category=UserWarning)\n"
            "warnings.filterwarnings('ignore', category=RuntimeWarning)\n"
        )

    @staticmethod
    def check_static_file(path: str) -> dict:
        """
        校验文件是否可通过 /static/ 接口正常访问

        在沙盒内发送 HTTP 请求到后端静态文件服务，验证 AI 生成的文件
        （图表 / 数据 / 报告 / Mermaid 等）已被正确保存并可被前端访问。
        用于防止 AI 写错路径、文件未实际生成、服务端未启动等异常。

        Args:
            path: 相对于 /static/ 的路径，格式如
                  "cached/{session_id}/data_analysis/gen_001/charts/xxx.png"

        Returns:
            dict 包含 url / accessible / status_code / content_type / error

        error 字段格式（AI 可直接 parse）：
            成功时为 None；失败时统一为 `[类型] 描述 | 建议`
            - [后端未连通] / [请求超时] / [网络异常]
            - [文件不存在] / [服务端异常] / [HTTP 错误]
        """
        # 环境检测：沙盒用 host.docker.internal，本机用 127.0.0.1
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
        """
        保存分析脚本到 scripts/ 目录

        Args:
            code: Python 代码
            filename: 文件名，默认用时间戳生成
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
        """
        保存数据文件到 data/ 目录

        Args:
            content: 文件内容（文本格式，如 CSV、JSON、TXT 等）
            filename: 文件名（需含后缀，如 data.csv、result.json）

        Returns:
            保存后的文件绝对路径
        """
        data_dir = self.get_current_generation_dir() / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        data_path = data_dir / filename
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(content)

        return str(data_path)

    def save_report(self, content: str, filename: str, mode: str = "w") -> str:
        """
        保存报告文件到 reports/ 目录

        Args:
            content: 报告内容（Markdown 或纯文本）
            filename: 文件名（需含后缀，如 report.md、summary.txt）
            mode: 写入模式，"w" 覆盖（默认），"a" 追加到末尾

        Returns:
            保存后的文件绝对路径

        用法提示：
            长报告建议分块写，避免单次 code() 调用超过 LLM max_tokens：
            da.save_report(intro, "report.md")                # mode="w" 创建文件
            da.save_report(section1, "report.md", mode="a")   # 续写
            da.save_report(section2, "report.md", mode="a")   # 续写

            Markdown 段落分隔建议在 content 末尾留 \\n\\n。
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
        """
        校验 mermaid 语法，返回 (是否合法, 错误信息)

        Args:
            code: mermaid 语法字符串

        Returns:
            (是否合法, 错误信息)
        """
        if not code or not code.strip():
            return False, "Mermaid 代码为空"

        # 去除代码块包裹符号
        code = code.strip()
        code = re.sub(r'^```(?:mermaid)?\s*', '', code, flags=re.IGNORECASE)
        code = re.sub(r'\s*```$', '', code)

        # 检查图类型声明
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

        # erDiagram 的 { } 是实体属性定义语法，不需要校验括号配对
        # 其他图类型的 { } 才需要校验
        is_erdiagram = any(f"{gt} " in code or f"{gt}\n" in code for gt in ['erDiagram'])
        bracket_pairs = [('{', '}'), ('[', ']'), ('(', ')')] if not is_erdiagram else [('[', ']'), ('(', ')')]
        for open_, close in bracket_pairs:
            if code.count(open_) != code.count(close):
                return False, f"{open_}{close} 括号不匹配"

        # 检查节点ID重复定义（简单校验）
        nodes = re.findall(r'\b([A-Za-z0-9_]+)\[', code)
        if len(nodes) != len(set(nodes)):
            return False, "节点ID重复定义"

        return True, "语法合格"

    def save_mermaid(self, code: str, filename: str) -> str:
        """
        保存 mermaid 语法文件到 charts/ 目录

        Args:
            code: mermaid 语法字符串
            filename: 文件名（应含 .mmd 后缀）

        Returns:
            保存后的文件绝对路径

        Raises:
            ValueError: 语法校验失败时抛出
        """
        ok, msg = self.validate_mermaid(code)
        if not ok:
            raise ValueError(f"Mermaid 语法错误: {msg}")

        charts_dir = self.get_current_generation_dir() / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        # 确保文件名含 .mmd 后缀
        if not filename.endswith('.mmd'):
            filename += '.mmd'

        mermaid_path = charts_dir / filename
        mermaid_path.write_text(code, encoding="utf-8")
        return str(mermaid_path)

    # --------------------------------------------------------
    # 删除
    # --------------------------------------------------------

    def remove_dir(self, generation: str) -> None:
        """
        删除指定 generation 的分析结果目录

        Args:
           generation: generation ID (示例："gen_001" / "gen_002")
        """
        remove_generated_dir = self.base_dir / generation
        if remove_generated_dir.exists():
            shutil.rmtree(remove_generated_dir)
        else:
            pass