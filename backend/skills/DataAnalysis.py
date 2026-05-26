"""
数据分析技能 - 通用数据处理与分析模板

功能:
- 支持 CSV、JSON、TXT、Excel 等常见数据格式
- 生成的分析结果缓存到 cached/data_analysis/ 目录下
- 命名规范：{原始文件名}_{时间戳}_{分析类型}.{扩展名}

使用方式：
    from ChatMe.skills.DataAnalysis import analyze_data, generate_report

    # 基础分析
    result = analyze_data("data.csv")

    # 指定分析类型
    result = analyze_data("data.json", analysis_type="statistics")

    # 生成报告
    report = generate_report("data.csv", report_type="full")
"""
import os
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, Any


# ============================================================
# 路径配置
# ============================================================

def _get_base_dir() -> Path:
    """获取 backend 目录"""
    return Path(__file__).resolve().parents[1]


def _get_analysis_dir() -> Path:
    """获取数据分析缓存目录，不存在则创建"""
    analysis_dir = _get_base_dir() / "cached" / "data_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir


def _generate_filename(
    original_name: str,
    analysis_type: str,
    extension: str,
    timestamp: Optional[datetime] = None
) -> str:
    """
    生成规范化的文件名

    格式: {原始文件名}_{YYYYMMDD_HHmmss}_{分析类型}.{扩展名}

    示例:
        data.csv -> data_20250524_143052_summary.csv
        users.json -> users_20250524_143052_statistics.json
    """
    if timestamp is None:
        timestamp = datetime.now()

    # 提取原始文件名（不含扩展名）
    stem = Path(original_name).stem

    # 规范化时间戳格式
    ts = timestamp.strftime("%Y%m%d_%H%M%S")

    # 规范化分析类型
    atype = analysis_type.lower().strip()

    return f"{stem}_{ts}_{atype}.{extension}"


def _refresh_file_timestamp(file_path: Path):
    """
    刷新文件时间戳，防止被清理任务删除
    """
    try:
        os.utime(file_path, None)
    except OSError:
        pass


# ============================================================
# 数据读取
# ============================================================

def _read_csv(file_path: str) -> tuple[list[dict], list[str]]:
    """读取 CSV 文件"""
    analysis_dir = _get_analysis_dir()
    full_path = analysis_dir / file_path if not os.path.isabs(file_path) else Path(file_path)

    with open(full_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames or []
    return rows, headers


def _read_json(file_path: str) -> Any:
    """读取 JSON 文件"""
    analysis_dir = _get_analysis_dir()
    full_path = analysis_dir / file_path if not os.path.isabs(file_path) else Path(file_path)

    with open(full_path, encoding='utf-8') as f:
        return json.load(f)


def _read_txt(file_path: str) -> str:
    """读取 TXT 文件"""
    analysis_dir = _get_analysis_dir()
    full_path = analysis_dir / file_path if not os.path.isabs(file_path) else Path(file_path)

    with open(full_path, encoding='utf-8') as f:
        return f.read()


def read_data(file_path: str) -> tuple[Any, str]:
    """
    根据文件扩展名读取数据文件

    返回: (数据内容, 文件类型)

    支持格式:
    - .csv -> (list[dict], "csv")
    - .json -> (Any, "json")
    - .txt -> (str, "txt")
    - .xlsx -> (list[dict], "excel")  # 需安装 pandas
    """
    ext = Path(file_path).suffix.lower()

    if ext == '.csv':
        data, headers = _read_csv(file_path)
        _refresh_file_timestamp(Path(file_path))
        return data, "csv"

    elif ext == '.json':
        data = _read_json(file_path)
        _refresh_file_timestamp(Path(file_path))
        return data, "json"

    elif ext == '.txt':
        data = _read_txt(file_path)
        _refresh_file_timestamp(Path(file_path))
        return data, "txt"

    elif ext in ('.xlsx', '.xls'):
        try:
            import pandas as pd
            df = pd.read_excel(file_path)
            _refresh_file_timestamp(Path(file_path))
            return df.to_dict('records'), "excel"
        except ImportError:
            raise ImportError("读取 Excel 文件需要安装 pandas: uv add pandas openpyxl")

    else:
        raise ValueError(f"不支持的文件格式: {ext}")


# ============================================================
# 数据分析核心
# ============================================================

def _analyze_csv_summary(data: list[dict], headers: list[str]) -> dict:
    """CSV 汇总分析"""
    return {
        "total_rows": len(data),
        "total_columns": len(headers),
        "columns": headers,
        "sample": data[:5] if len(data) > 5 else data,
    }


def _analyze_json_summary(data: Any) -> dict:
    """JSON 汇总分析"""
    if isinstance(data, list):
        return {
            "type": "array",
            "length": len(data),
            "sample": data[:5] if len(data) > 5 else data,
        }
    elif isinstance(data, dict):
        return {
            "type": "object",
            "keys": list(data.keys()),
            "sample": {k: data[k] for k in list(data.keys())[:5]},
        }
    else:
        return {
            "type": type(data).__name__,
            "value": str(data)[:200],
        }


def _analyze_text_statistics(text: str) -> dict:
    """文本统计分析"""
    lines = text.split('\n')
    return {
        "total_characters": len(text),
        "total_lines": len(lines),
        "non_empty_lines": sum(1 for line in lines if line.strip()),
        "sample_lines": lines[:10],
    }


def analyze_data(
    file_path: str,
    analysis_type: Literal["summary", "statistics", "full"] = "summary",
) -> str:
    """
    分析数据文件并生成分析结果

    参数:
        file_path: 数据文件路径（支持相对 cached/ 目录或绝对路径）
        analysis_type: 分析类型
            - summary: 汇总信息（行数、列名、示例）
            - statistics: 统计分析（数值列的均值、中位数等）
            - full: 完整分析报告

    返回:
        分析结果的格式化字符串

    示例:
        >>> result = analyze_data("sales_2025.csv")
        >>> print(result)
        数据文件: sales_2025.csv
        分析类型: summary
        分析时间: 2025-05-24 14:30:52

        ====================
        汇总信息
        ====================
        总行数: 1500
        总列数: 8
        列名: ['日期', '销售额', '成本', ...]
    """
    analysis_dir = _get_analysis_dir()
    full_path = analysis_dir / file_path if not os.path.isabs(file_path) else Path(file_path)

    # 如果路径不存在，在 cached/ 目录下查找
    if not full_path.exists():
        cached_path = _get_base_dir() / "cached" / file_path
        if cached_path.exists():
            full_path = cached_path
        else:
            raise FileNotFoundError(f"数据文件不存在: {file_path}")

    _refresh_file_timestamp(full_path)

    # 读取数据
    data, data_type = read_data(str(full_path))

    # 执行分析
    timestamp = datetime.now()
    result: dict[str, Any] = {
        "file_name": full_path.name,
        "file_path": str(full_path),
        "data_type": data_type,
        "analysis_type": analysis_type,
        "analysis_time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if data_type == "csv":
        headers = data[0].keys() if data else []
        if analysis_type in ("summary", "full"):
            result["summary"] = _analyze_csv_summary(data, list(headers))
        if analysis_type == "statistics" and analysis_type == "full":
            result["statistics"] = _compute_csv_statistics(data, headers)

    elif data_type == "json":
        if analysis_type in ("summary", "full"):
            result["summary"] = _analyze_json_summary(data)

    elif data_type == "txt":
        if analysis_type in ("summary", "full"):
            result["summary"] = _analyze_text_statistics(data)
        if analysis_type in ("statistics", "full"):
            result["statistics"] = _compute_text_statistics(data)

    # 保存分析结果到缓存
    result_filename = _generate_filename(full_path.name, analysis_type, "json", timestamp)
    result_path = _get_analysis_dir() / result_filename

    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    _refresh_file_timestamp(result_path)

    # 返回格式化字符串
    output = f"""数据文件: {full_path.name}
分析类型: {analysis_type}
分析时间: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}
结果缓存: {result_filename}

{'=' * 40}
分析结果
{'=' * 40}
"""

    if data_type == "csv":
        output += _format_csv_result(result)
    elif data_type == "json":
        output += _format_json_result(result)
    elif data_type == "txt":
        output += _format_text_result(result)

    return output


def _compute_csv_statistics(data: list[dict], headers: list[str]) -> dict:
    """计算 CSV 数值列统计"""
    import statistics

    stats = {}
    numeric_headers = []

    # 检查哪些列是数值类型
    for header in headers:
        values = []
        for row in data:
            try:
                val = float(row.get(header, ''))
                if val != 0 or row.get(header, ''):
                    values.append(val)
            except (ValueError, TypeError):
                pass

        if len(values) > len(data) * 0.5:
            numeric_headers.append(header)
            try:
                stats[header] = {
                    "count": len(values),
                    "sum": sum(values),
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                }
            except statistics.StatisticsError:
                pass

    stats["_numeric_columns"] = numeric_headers
    return stats


def _compute_text_statistics(text: str) -> dict:
    """计算文本统计"""
    words = text.split()
    return {
        "total_words": len(words),
        "unique_words": len(set(w.lower() for w in words)),
        "avg_word_length": sum(len(w) for w in words) / len(words) if words else 0,
    }


def _format_csv_result(result: dict) -> str:
    """格式化 CSV 分析结果"""
    output = ""
    if "summary" in result:
        summary = result["summary"]
        output += f"总行数: {summary['total_rows']}\n"
        output += f"总列数: {summary['total_columns']}\n"
        output += f"列名: {summary['columns']}\n"

    if "statistics" in result:
        stats = result["statistics"]
        output += "\n数值列统计:\n"
        for col in stats.get("_numeric_columns", []):
            s = stats[col]
            output += f"  {col}:\n"
            output += f"    计数: {s['count']}, 均值: {s['mean']:.2f}, 中位数: {s['median']:.2f}\n"
            output += f"    最小值: {s['min']}, 最大值: {s['max']}\n"

    return output


def _format_json_result(result: dict) -> str:
    """格式化 JSON 分析结果"""
    if "summary" in result:
        summary = result["summary"]
        output = f"数据类型: {summary['type']}\n"
        if summary['type'] == "array":
            output += f"数组长度: {summary['length']}\n"
        elif summary['type'] == "object":
            output += f"对象键: {summary['keys']}\n"
        return output
    return ""


def _format_text_result(result: dict) -> str:
    """格式化文本分析结果"""
    output = ""
    if "summary" in result:
        summary = result["summary"]
        output += f"总字符数: {summary['total_characters']}\n"
        output += f"总行数: {summary['total_lines']}\n"
        output += f"非空行数: {summary['non_empty_lines']}\n"

    if "statistics" in result:
        stats = result["statistics"]
        output += f"\n文本统计:\n"
        output += f"  总词数: {stats['total_words']}\n"
        output += f"  唯一词数: {stats['unique_words']}\n"
        output += f"  平均词长: {stats['avg_word_length']:.2f}\n"

    return output


# ============================================================
# 报告生成
# ============================================================

def generate_report(
    file_path: str,
    report_type: Literal["summary", "full"] = "full",
    output_format: Literal["txt", "json"] = "txt",
) -> str:
    """
    生成数据文件分析报告

    参数:
        file_path: 数据文件路径
        report_type: 报告详细程度
        output_format: 输出格式 (txt 或 json)

    返回:
        报告内容字符串（json格式时返回JSON字符串）

    示例:
        >>> report = generate_report("data.csv", report_type="full")
    """
    # 先执行完整分析
    analysis_result = analyze_data(file_path, analysis_type=report_type)

    if output_format == "json":
        # 加载分析结果文件
        analysis_dir = _get_analysis_dir()
        result_files = sorted(analysis_dir.glob(f"*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

        if result_files:
            with open(result_files[0], encoding='utf-8') as f:
                return f.read()

    return analysis_result


# ============================================================
# 工具函数
# ============================================================

def list_analysis_cache() -> list[dict]:
    """
    列出所有分析缓存文件

    返回:
        缓存文件信息列表，包含文件名的命名规范字段
    """
    analysis_dir = _get_analysis_dir()
    if not analysis_dir.exists():
        return []

    files = []
    for f in analysis_dir.iterdir():
        if f.is_file():
            # 解析命名规范
            parts = f.stem.split('_')
            info = {
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "original_file": parts[0] if parts else f.stem,
                "analysis_type": parts[-2] if len(parts) >= 2 else "unknown",
                "timestamp": parts[-1] if parts else "",
            }
            files.append(info)

    return sorted(files, key=lambda x: x["modified"], reverse=True)


def clear_analysis_cache(older_than_days: int = 30) -> int:
    """
    清理分析缓存文件

    参数:
        older_than_days: 清理多少天前的文件

    返回:
        删除的文件数量
    """
    analysis_dir = _get_analysis_dir()
    if not analysis_dir.exists():
        return 0

    cutoff = datetime.now().timestamp() - older_than_days * 86400
    removed = 0

    for f in analysis_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1

    return removed