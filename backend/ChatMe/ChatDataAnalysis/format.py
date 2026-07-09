"""
数据分析技能规范模块
- 提供在数据分析目录下操作所需要进行的*操作规范*
- 提供数据分析所需要相关的*配置规范*
"""
import fcntl
import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional

import requests

from ChatMe.ChatMeConfig import get_oss_config
from ChatMe.LoggingManager.logging_config import get_logger


class ChatDataAnalysisFormat:
    """
    数据分析执行配置规范类。

    *默认执行路径工作目录就可以了 '/'*
    """


    def __init__(self, session_id: str):
        """
        初始化数据分析配置

        Args:
            session_id: 会话 ID，用于组织输出目录
        """
        # 区分宿主机
        if os.path.exists("/.dockerenv"):
            log_dir = Path.home() / ".chatme" / "logs"
        else:
            log_dir = Path.cwd() / ".chatme" / "logs"

        self.logger = get_logger(name="ChatDataAnalysisFormat", path=log_dir)
        self.session_id = session_id
        self._base_dir: Optional[str] = None
        self._generation: Optional[str] = None

    @property
    def generation(self) -> str:
        """获取当前 generation，懒加载（首次访问时获取或创建 gen_001，不自增计数器）"""
        if self._generation is None:
            self._generation = self._get_or_create_first_generation()
        return self._generation

    @generation.setter
    def generation(self, value: str):
        self._generation = value

    # --------------------------------------------------------
    # 配置规范
    # --------------------------------------------------------

    @property
    def base_dir(self) -> str:
        """获取输出根目录"""
        if self._base_dir is None:
            backend_dir = Path.cwd() / "cached"
            self._base_dir = os.path.join(backend_dir, self.session_id, "data_analysis")
        return self._base_dir

    @property
    def meta_path(self) -> str:
        return os.path.join(self.base_dir, "_meta.json")

    def new_generation(self) -> str:
        """
        开启新的一次分析调用，返回 generation_id

        Returns:
            "gen_001", "gen_002" ...
        """
        os.makedirs(self.base_dir, exist_ok=True)

        with open(self.meta_path, "a+") as f:
            # 文件锁，防止并发自增
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                if content:
                    meta = json.loads(content)
                    gen = meta.get("generation", 0) + 1
                else:
                    gen = 1

                # 写入新值
                f.seek(0)
                f.truncate()
                json.dump({"generation": gen}, f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        return f"gen_{gen:03d}"

    def _get_or_create_first_generation(self) -> str:
        """
        获取当前 session 已有的最新 generation，
        如果完全不存在任何 generation记录，则创建 gen_001。
        此方法不会自增计数器。
        """
        os.makedirs(self.base_dir, exist_ok=True)

        with open(self.meta_path, "a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                if content:
                    meta = json.loads(content)
                    gen = meta.get("generation", 0)
                    if gen > 0:
                        return f"gen_{gen:03d}"
                    # generation 为 0 或无效，初始化为 gen_001
                    gen = 1
                else:
                    gen = 1

                f.seek(0)
                f.truncate()
                json.dump({"generation": gen}, f)
                return f"gen_{gen:03d}"
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get_current_generation(self) -> str:
        """
        获取当前 generation（如果还没有则创建 gen_001）。
        不自增计数器，不会创建新的 generation目录。
        """
        return self.generation

    def get_current_generation_dir(self) -> str:
        return os.path.join(self.base_dir, self.generation)

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
        filename = path.name
        backend_dir = Path.cwd() / "cached"

        for match in backend_dir.rglob(filename):
            return match

        raise FileNotFoundError(f"找不到文件: {filename}")


    # --------------------------------------------------------
    # 操作规范
    # --------------------------------------------------------

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
            from ChatMe.ChatDataAnalysis.format import ChatDataAnalysisFormat
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
            dict 包含 url / accessible / status_code / content_type / size / error

        error 字段格式（AI 可直接 parse）：
            成功时为 None；失败时统一为 `[类型] 描述 | 建议`
            - [后端未连通] / [请求超时] / [网络异常]
            - [文件不存在] / [服务端异常] / [HTTP 错误]
        """

        # 环境检测：沙盒用 host.docker.internal，本机用 127.0.0.1
        is_sandbox = os.path.exists("/.dockerenv")
        default_host = "host.docker.internal" if is_sandbox else "127.0.0.1"
        host = os.getenv("CHATME_BACKEND_HOST", default_host)
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
                "error": None if accessible else ChatDataAnalysisFormat._format_check_error(
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
                "error": ChatDataAnalysisFormat._format_check_error(
                    status_code=None,
                    exception=e,
                    path=path,
                    url=url,
                    port=port,
                ),
            }

    def remove_dir(self, generation: str):
        """
        删除指定 generation 的分析结果目录

        Args:
           generation: generation ID (示例："gen_001" / "gen_002")
        """
        remove_generated_dir = Path(self.base_dir) / generation
        if remove_generated_dir.exists():
            shutil.rmtree(remove_generated_dir)
            self.logger.info(f"成功删除 {self.session_id} 下 {generation} 批次数据分析结果")
        else:
            self.logger.warning(f"不存在 {self.session_id} 下 {generation} 批次数据分析结果")


    def upload_result_to_oss(self, path: str | Path) -> Optional[str]:
        """
        上传数据分析结果到 OSS

        OSS key 格式: chatme/{session_id}/{generation}/{filename}
        与本地 cached 目录结构保持一致

        Args:
            path: 本地文件路径

        Returns:
            OSS URL 字符串，失败返回 None
        """
        if isinstance(path, str):
            path = Path(path)

        try:
            import oss2

            oss_cfg = get_oss_config()
            if not all([oss_cfg.get("access_key_id"), oss_cfg.get("access_key_secret"),
                        oss_cfg.get("bucket"), oss_cfg.get("endpoint")]):
                self.logger.warning(f"OSS 配置不完整，跳过上传: {path}")
                return None

            # 解析 path 提取 generation
            # path 格式: cached/{session_id}/data_analysis/{generation}/charts/xxx.png
            parts = Path(path).parts
            generation = "unknown"
            if "data_analysis" in parts:
                idx = parts.index("data_analysis")
                if idx + 1 < len(parts):
                    generation = parts[idx + 1]

            filename = path.name
            oss_key = f"chatme/{self.session_id}/{generation}/{filename}"

            # 上传到 OSS
            auth = oss2.Auth(oss_cfg["access_key_id"], oss_cfg["access_key_secret"])
            bucket = oss2.Bucket(auth, oss_cfg["endpoint"], oss_cfg["bucket"])
            bucket.put_object_from_file(oss_key, str(path))

            # 返回 OSS URL
            bucket_name = oss_cfg["bucket"]
            endpoint = oss_cfg["endpoint"]
            oss_url = f"https://{bucket_name}.{endpoint.replace('https://', '')}/{oss_key}"
            self.logger.info(f"文件上传 OSS 成功: {path} -> {oss_url}")
            return oss_url

        except ImportError:
            self.logger.warning(f"oss2 模块未安装，无法上传到 OSS: {path}")
            return None
        except Exception as e:
            self.logger.warning(f"上传文件到 OSS 失败: {path}, 错误: {e}")
            return None

    def save_script(self, code: str, filename: str = None) -> str:
        """
        保存分析脚本到 scripts/ 目录

        Args:
            code: Python 代码
            filename: 文件名，默认用时间戳生成
        """
        import time
        scripts_dir = Path(self._base_dir) / self._generation / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            filename = f"script_{int(time.time())}.py"

        script_path = scripts_dir / filename
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        self.logger.debug(f"脚本已保存: {script_path}")
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
        data_dir = Path(self.get_current_generation_dir()) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        data_path = data_dir / filename
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.logger.debug(f"数据文件已保存: {data_path}")
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

        reports_dir = Path(self.get_current_generation_dir()) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_path = reports_dir / filename
        with open(report_path, mode, encoding="utf-8") as f:
            f.write(content)

        self.logger.debug(f"报告已保存 ({mode}): {report_path}")
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
        import re

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

        charts_dir = Path(self.get_current_generation_dir()) / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        # 确保文件名含 .mmd 后缀
        if not filename.endswith('.mmd'):
            filename += '.mmd'

        mermaid_path = charts_dir / filename
        mermaid_path.write_text(code, encoding="utf-8")
        self.logger.debug(f"Mermaid 文件已保存: {mermaid_path}")
        return str(mermaid_path)

    # --------------------------------------------------------
    # 全局配置汇总
    # --------------------------------------------------------

    def get_config(self) -> dict:
        """
        获取完整的配置字典

        注意：此方法复用当前已有的 generation（如果还没有则自动创建 gen_001）。
        不会自增计数器，AI 在同一次分析中多次调用不会创建新目录。

        Returns:
            包含所有路径和默认配置的字典
        """
        return {
            "output_dir": self.get_current_generation_dir()
        }