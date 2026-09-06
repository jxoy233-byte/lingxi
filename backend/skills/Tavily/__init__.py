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
    """Tavily 搜索引擎客户端"""

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
        """
        使用 Tavily 进行网页搜索

        Args:
            query: 搜索查询
            search_depth: 搜索深度 ("basic": 快速, "advanced": 深度)
            max_results: 返回结果数量 (默认 5，最大 20)
            include_answer: 是否包含 AI 生成的答案摘要
            include_raw_content: 是否包含页面原始内容摘要
            include_images: 是否包含相关图片
            **kwargs: 其他可选参数

        Returns:
            搜索结果列表
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
    使用 Tavily 进行网页搜索

    Args:
        query: 搜索查询
        search_depth: 搜索深度 ("basic": 快速, "advanced": 深度)
        max_results: 返回结果数量
        include_answer: 是否包含 AI 生成的答案摘要

    Returns:
        格式化输出结果字符串
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


