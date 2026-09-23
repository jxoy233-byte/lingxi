"""
WebSearch 技能 —— 统一网页搜索入口
自动在 Bocha / Tavily / Exa 之间选择可用后端，返回统一格式结果。
"""
from typing import List, Dict, Any


def _try_bocha(query: str, count: int, freshness: str):
    from skills.Bocha import search_web
    return search_web(query=query, freshness=freshness, summary=True, count=count)


def _try_tavily(query: str, count: int, freshness: str):
    from skills.Tavily import tavily_search
    return tavily_search(query=query, max_results=count, include_answer=True)


def _try_exa(query: str, count: int, freshness: str):
    from skills.Exa import exa_search
    return exa_search(query=query, num_results=count)


def web_search(query: str, count: int = 5, freshness: str = "noLimit", engine: str = "auto") -> str:
    """统一网页搜索。

    Args:
        query: 检索关键词 / 主题
        count: 返回结果数量（建议 <=5，少量多次）
        freshness: 时间范围 noLimit / oneDay / oneWeek / oneMonth / oneYear
        engine: auto / bocha / tavily / exa

    Returns:
        格式化后的搜索结果文本（含标题、URL、摘要）
    """
    if not query or not query.strip():
        return "[WebSearch] query 不能为空"

    engines = {
        "bocha": _try_bocha,
        "tavily": _try_tavily,
        "exa": _try_exa,
    }

    if engine != "auto":
        if engine not in engines:
            return f"[WebSearch] 未知 engine: {engine}，可选 auto/bocha/tavily/exa"
        order = [engine]
    else:
        order = ["bocha", "tavily", "exa"]

    errors = []
    for name in order:
        try:
            result = engines[name](query, count, freshness)
            if result:
                return f"[engine={name}]\n{result}"
        except Exception as e:
            errors.append(f"{name}: {e}")

    return "[WebSearch] 所有后端均失败:\n" + "\n".join(errors)


def search(query: str, count: int = 5, freshness: str = "noLimit", engine: str = "auto") -> str:
    """web_search 的简写别名。"""
    return web_search(query=query, count=count, freshness=freshness, engine=engine)
