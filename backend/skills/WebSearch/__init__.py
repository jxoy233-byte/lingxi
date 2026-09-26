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
    """统一网页搜索 —— 自动在 Bocha / Tavily / Exa 之间选择可用后端。

    后端优先级：Bocha（中文优化）→ Tavily（通用）→ Exa（语义）。
    任一后端抛错自动尝试下一个，全部失败时返回错误汇总。

    Args:
        query: 检索关键词 / 主题（不能为空）。
        count: 返回结果数量（建议 ≤5，少量多次优于单次多量）。默认 5。
        freshness: 时间范围 `noLimit` / `oneDay` / `oneWeek` / `oneMonth` /
                   `oneYear`（实际传给 Bocha 时生效，其他后端会忽略）。
                   默认 "noLimit"。
        engine: 后端选择。`"auto"` = 按 bocha→tavily→exa 顺序尝试；
                或显式指定 `"bocha"` / `"tavily"` / `"exa"`。默认 "auto"。

    Returns:
        格式化文本，前缀标注实际使用的后端 `[engine=xxx]\n...`。
        query 为空时返 `[WebSearch] query 不能为空`。
        所有后端失败时返 `[WebSearch] 所有后端均失败:\n...`。

    Raises:
        不抛异常（内部 try/except 包住所有后端错误，转字符串返回）。

    Example:
        >>> web_search("Q3 GDP 数据", count=3)
        "[engine=bocha]\\n引用: 1\\n标题: ...\\nURL: ...\\n..."
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
    """web_search 的简写别名（参数完全相同）。"""
    return web_search(query=query, count=count, freshness=freshness, engine=engine)


def doc(name=None):
    """查询本 skill 的函数 docstring。

    Args:
        name: None 列出全部；str 返回该函数的完整 docstring

    Returns:
        字符串（直接 print 即可看）

    用法：
        from skills.WebSearch import help
        help()              # 列出全部函数签名 + summary
        help("func_name")   # 单个函数完整 docstring
    """
    import sys
    from skills._shared._skill_help import skill_help
    return skill_help(sys.modules[__name__], name)


def help(name=None):
    """doc() 别名。"""
    return doc(name)


# 自动给所有函数挂 .help 属性（AI 一行 func.help 拿到完整 docstring）
import sys as _sys
from skills._shared._skill_help import auto_attach_help_module as _auto_attach_help_module
_auto_attach_help_module(_sys.modules[__name__])
