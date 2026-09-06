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
    """Exa 搜索引擎客户端"""

    def __init__(self):
        # 优先级：config.json (via get_skills_config) > os.getenv
        self.api_key = get_skills_config().get("exa_api_key") or os.getenv("EXA_API_KEY", "")
        self.base_url = "https://api.exa.ai"

        if not self.api_key:
            raise ValueError("EXA_API_KEY 未配置（config.json 的 skills.exa_api_key 或环境变量）")

    def search(self, query: str, num_results: int = 3, type: Literal["instant","fast","auto","deep"] = "auto", maxCharacters:int =2000, **metadata) -> List[Dict[str, Any]]:
        """
        语义搜索

        Args:
            query: 搜索查询
            num_results: 返回结果数量 (默认 3，最大10)
            type: 查询精细方式的不同(instant:200ms, fast:400ms, auto:1s, deep:4~12s)
            maxCharacters: 页面摘要的最大返回字体数
            metadata:

        Returns:
            搜索结果列表
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
        """
        查找与给定 URL 相似的内容

        Args:
            ids: 给定urls, 比如:tesla.com
            num_results: 返回结果数量0
            maxCharacters: 页面摘要的最大返回字体数
            maxAgeHours: 缓存内容最大有效期，缓存信息距离现在时间(0:始终进行实时爬取，-1:从不进行实时爬取，168:仅对超过 7 天（168 小时）的缓存内容触发实时爬取)
            livercrawlTimeout: 最大等待实施爬取的时长

        Returns:
            相似内容列表
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
    使用 Exa进行语义搜索

    Returns:
        格式化输出结果列表
    """

    exa = ExaSearch()
    results = exa.search(query, num_results=num_results, type=type, maxCharacters=maxCharacters, **kwargs)

    return results

def exa_find_similar(ids: List[str], maxCharacters:int =2000, maxAgeHours:int = 168, livercrawlTimeout: int =5000, **kwargs) -> List[dict]:
    """
    查找与指定 URL 相似的内容

    Returns:
        JSON 格式的相似内容列表字符串
    """

    exa = ExaSearch()
    results = exa.find_similar(ids=ids, maxCharacters=maxCharacters, maxAgeHours=maxAgeHours, livercrawlTimeout=livercrawlTimeout, **kwargs)

    return results

