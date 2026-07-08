import os
from typing import Literal

import requests

from ChatMe.ChatMeConfig import get_skills_config


def search_web(query: str,
               freshness: Literal["noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"] = "noLimit",
               summary: bool = True,
               count: int = 5,
               **kwargs
               ):
    """
    使用Bocha Web Search API 进行网页搜索。

    参数:
    - query: 搜索关键词
    - freshness: 搜索的时间范围
    - summary: 是否显示文本摘要
    - count: 返回的搜索结果数量
    - **kwargs: 其他可选参数 (用于兼容多餘參數)

    返回:
    - 格式化后的搜索结果字符串
    """
    url = "https://api.bochaai.com/v1/web-search"

    # 优先级：config.json (via get_skills_config) > os.getenv
    api_key = get_skills_config().get("bocha_api_key") or os.getenv("BOCHA_API_KEY", "")
    if not api_key:
        return "Error: BOCHA_API_KEY 未配置（config.json 的 skills.bocha_api_key 或环境变量）"

    payload = {
       "query": query,
       "summary": summary,
       "freshness": freshness,
       "count": count
    }
    headers = {
       'Authorization': f'Bearer {api_key}',
       'Content-Type': 'application/json'
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        json_response = response.json()

        if json_response.get("code") != 200 or not json_response.get("data"):
            return f"搜索API请求失败，原因是: {json_response.get('msg', '未知错误')}"

        webpages = json_response.get("data", {}).get("webPages", {}).get("value", [])
        if not webpages:
            return "未找到相关结果。"

        formatted_results = ""
        for idx, page in enumerate(webpages, start=1):
            formatted_results += (
                f"引用: {idx}\n"
                f"标题: {page.get('name', 'N/A')}\n"
                f"URL: {page.get('url', 'N/A')}\n"
                f"摘要: {page.get('summary', 'N/A')}\n"
                f"网站名称: {page.get('siteName', 'N/A')}\n"
                f"网站图标: {page.get('siteIcon', 'N/A')}\n"
                f"发布时间: {page.get('dateLastCrawled', 'N/A')}\n\n"
            )
        return formatted_results.strip()

    except requests.RequestException as e:
        return f"搜索API请求失败：{str(e)}"


if __name__ == "__main__":
    print(search_web("明天广州番禺天气怎么样？"))