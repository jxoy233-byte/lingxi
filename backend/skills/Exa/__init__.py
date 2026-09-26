"""
Exa 搜索引擎技能
提供基于 Exa API 的语义搜索和 URL 搜索功能
"""
import os

import requests
from typing import List, Dict, Any, Literal

from ChatMe.ChatMeConfig import get_skills_config
from skills._search_health import format_others_available

class ExaSearch:
    """Exa 搜索引擎客户端（class 形态，适合复用连接 / 复杂配置场景）。

    一般 LLM 直接用顶层 `exa_search(...)` / `exa_find_similar(...)` 即可；
    本类用于需要多次调用同一客户端 / 自定义 `api_key` / `base_url` 的场景。

    Raises:
        ValueError: EXA_API_KEY 未配置时（构造时抛）。
    """

    def __init__(self):
        # 优先级：config.json (via get_skills_config) > os.getenv
        self.api_key = get_skills_config().get("exa_api_key") or os.getenv("EXA_API_KEY", "")
        self.base_url = "https://api.exa.ai"

        if not self.api_key:
            raise ValueError("EXA_API_KEY 未配置（config.json 的 skills.exa_api_key 或环境变量）")

    def search(self, query: str, num_results: int = 3, type: Literal["instant","fast","auto","deep"] = "auto", maxCharacters:int =2000, **metadata) -> List[Dict[str, Any]]:
        """调 Exa `/search` 端点；返回 list[dict]（title/url/publishedDate/highlights/author）。
        详细 `help("ExaSearch.search")`。
        """
        headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "query": query,
            "numResults": num_results,
            "contents": {
                "highlights": {"maxCharacters": maxCharacters}
            },
            "type": type,
            **metadata,  # 接受并传递额外参数，API会忽略未知字段
        }

        try:
            with requests.post(
                f"{self.base_url}/search",
                headers=headers,
                json=payload,
                timeout=30
            ) as response:
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])

            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "publishedDate": result.get("publishedDate", ""),
                    "highlights": result.get("highlights", []),
                    "author": result.get("author", None),
                })

            return formatted_results

        except requests.RequestException as e:
            raise Exception(f"Exa 搜索失败：{str(e)}{format_others_available('Exa')}")

    def find_similar(self, ids: List[str], maxCharacters:int =2000, maxAgeHours:int = 168, livercrawlTimeout: int =5000, **metadata) -> List[Dict[str, Any]]:
        """调 Exa `/contents` 端点按 URL 找相似；返回 list[dict]（title/url/author/highlights）。
        详细 `help("ExaSearch.find_similar")`。
        """
        headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
        "highlights": {
            "maxCharacters": maxCharacters,
        },
        "ids": ids,
        "livecrawlTimeout": livercrawlTimeout,
        "maxAgeHours": maxAgeHours,
        **metadata,
    }

        try:
            with requests.post(
                f"{self.base_url}/contents",
                headers=headers,
                json=payload,
                timeout=30
            ) as response:
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])

                formatted_results = []
                for result in results:
                    formatted_results.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "author": result.get("author", ""),
                        "highlights": result.get("highlights", [])
                    })

                return formatted_results

        except requests.RequestException as e:
            raise Exception(f"Exa 相似内容查找失败：{str(e)}{format_others_available('Exa')}")


def exa_search(query: str, num_results: int = 5, type: Literal["instant","fast","auto","deep"] = "auto", maxCharacters:int =2000, **kwargs) -> List[dict]:
    """
    Exa 语义搜索（少量多次，`num_results ≤5`；研究 / 原理 / 对比分析场景）。

    Args: query 关键词；num_results Exa 上限 10；type "instant"/"fast"/"auto"/"deep"（响应时长递增）；
          maxCharacters 页面摘要最大字符数。
    Returns: list[dict]，每项含 `title`/`url`/`publishedDate`/`highlights`/`author`。
    Raises: EXA_API_KEY 未配置抛 `ValueError`；网络错误转 `Exception`（含其他搜索源提示）。
    详细 `help("exa_search")`。
    """

    exa = ExaSearch()
    results = exa.search(query, num_results=num_results, type=type, maxCharacters=maxCharacters, **kwargs)

    return results

def exa_find_similar(ids: List[str], maxCharacters:int =2000, maxAgeHours:int = 168, livercrawlTimeout: int =5000, **kwargs) -> List[dict]:
    """
    Exa 相似内容查找（基于 URL / 域名列表找类似网页）。

    Args: ids URL 或域名列表（例 `["tesla.com", "https://nvidia.com/article"]`）；
          maxCharacters 页面摘要最大字符数；maxAgeHours 缓存有效期（0 始终实时爬 / -1 从不实时爬 / 168 仅 >7 天缓存实时爬）；
          livercrawlTimeout 实时爬最长等待（毫秒）。
    Returns: list[dict]（title/url/author/highlights）。
    Raises: EXA_API_KEY 未配置抛 `ValueError`；网络错误转 `Exception`。
    详细 `help("exa_find_similar")`。
    """

    exa = ExaSearch()
    results = exa.find_similar(ids=ids, maxCharacters=maxCharacters, maxAgeHours=maxAgeHours, livercrawlTimeout=livercrawlTimeout, **kwargs)

    return results


def doc(name=None):
    """查询本 skill 的函数 docstring。

    Args:
        name: None 列出全部；str 返回该函数 / 类的完整 docstring

    Returns:
        字符串（直接 print 即可看）

    用法：
        from skills.Exa import help
        help()              # 列出全部函数 / 类签名 + summary
        help("func_name")   # 单个函数 / 类完整 docstring
    """
    import sys
    from skills._shared._skill_help import skill_help
    return skill_help(sys.modules[__name__], name)


def help(name=None):
    """doc() 别名。"""
    return doc(name)


# 自动给所有顶层函数 / 类挂 .help 属性（func.help / ExaSearch.search.help 直接拿 docstring）
import sys as _sys
from skills._shared._skill_help import auto_attach_help_module as _auto_attach_help_module
_auto_attach_help_module(_sys.modules[__name__])

