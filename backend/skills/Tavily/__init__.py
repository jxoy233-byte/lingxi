"""
Tavily 搜索引擎技能
提供基于 Tavily API 的实时网页搜索功能
"""
import os
from typing import List, Dict, Any, Literal

import requests

from ChatMe.ChatMeConfig import get_skills_config
from skills._search_health import format_others_available


class TavilySearch:
    """Tavily 搜索引擎客户端（class 形态，适合复用连接 / 复杂配置场景）。

    一般 LLM 直接用顶层 `tavily_search(...)` 即可；本类用于需要
    多次调用同一客户端 / 自定义 `api_key` / `base_url` 的场景。

    Raises:
        ValueError: TAVILY_API_KEY 未配置时（构造时抛）。
    """

    def __init__(self):
        # 优先级：config.json (via get_skills_config) > os.getenv
        self.api_key = get_skills_config().get("tavily_api_key") or os.getenv("TAVILY_API_KEY", "")
        self.base_url = "https://api.tavily.com/search"

        if not self.api_key:
            raise ValueError("TAVILY_API_KEY 未配置（config.json 的 skills.tavily_api_key 或环境变量）")

    def search(
        self,
        query: str,
        search_depth: Literal["basic", "advanced"] = "basic",
        max_results: int = 3,
        include_answer: bool = False,
        include_raw_content: bool = False,
        include_images: bool = False,
        **kwargs
    ) -> dict[str, list[Any] | Any]:
        """调 Tavily `/search` 端点；返回 dict 含 `results` / `answer` / `response_time`。
        详细 `help("TavilySearch.search")`。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images,
            **kwargs
        }

        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            answer = data.get("answer", None)

            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "content": result.get("content", ""),
                    "published_date": result.get("published_date", None),
                    "score": result.get("score", None),
                })

            return {
                "results": formatted_results,
                "answer": answer,
                "response_time": data.get("response_time", None)
            }

        except requests.RequestException as e:
            raise Exception(f"Tavily 搜索失败：{str(e)}{format_others_available('Tavily')}")


def tavily_search(
    query: str,
    search_depth: Literal["basic", "advanced"] = "basic",
    max_results: int = 5,
    include_answer: bool = False,
    **kwargs
) -> str:
    """
    Tavily 网页搜索（少量多次，`max_results ≤5`；可带 AI 答案摘要）。

    Args: query 关键词；search_depth "basic"/"advanced"；max_results 上限 20（建议 ≤5）；
          include_answer True 时末尾追加 Tavily 生成的 AI 答案摘要。
    Returns: 格式化字符串（标题/URL/内容/发布时间）+ 可选 `AI 答案摘要`。
    Raises: TAVILY_API_KEY 未配置抛 `ValueError`；网络错误转 `Exception`（含其他搜索源提示）。
    详细 `help("tavily_search")`。
    """
    tavily = TavilySearch()
    result = tavily.search(
        query=query,
        search_depth=search_depth,
        max_results=max_results,
        include_answer=include_answer,
        **kwargs
    )

    output = ""
    for idx, item in enumerate(result["results"], start=1):
        output += f"结果 {idx}:\n"
        output += f"标题: {item['title']}\n"
        output += f"URL: {item['url']}\n"
        output += f"内容: {item['content']}\n"
        if item.get("published_date"):
            output += f"发布时间: {item['published_date']}\n"
        output += "\n"

    if result.get("answer"):
        output += f"AI 答案摘要: {result['answer']}\n"

    return output.strip()


def doc(name=None):
    """查询本 skill 的函数 docstring。

    Args:
        name: None 列出全部；str 返回该函数 / 类的完整 docstring

    Returns:
        字符串（直接 print 即可看）

    用法：
        from skills.Tavily import help
        help()              # 列出全部函数 / 类签名 + summary
        help("func_name")   # 单个函数 / 类完整 docstring
    """
    import sys
    from skills._shared._skill_help import skill_help
    return skill_help(sys.modules[__name__], name)


def help(name=None):
    """doc() 别名。"""
    return doc(name)


# 自动给所有顶层函数 / 类挂 .help 属性（func.help / TavilySearch.search.help 直接拿 docstring）
import sys as _sys
from skills._shared._skill_help import auto_attach_help_module as _auto_attach_help_module
_auto_attach_help_module(_sys.modules[__name__])