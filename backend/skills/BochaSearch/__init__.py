"""
Bocha（博查）搜索引擎技能
提供基于 Bocha Web Search API 的实时网页搜索，针对中文互联网深度优化
"""
import os
from typing import Literal

import requests

from ChatMe.ChatMeConfig import get_skills_config
from skills._search_health import format_others_available


def search_web(
    query: str,
    freshness: Literal["noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"] = "noLimit",
    summary: bool = True,
    count: int = 3,
    **kwargs
) -> str:
    """
    使用 Bocha Web Search API 进行网页搜索。

    参数:
    - query: 搜索关键词
    - freshness: 搜索的时间范围（"noLimit" / "oneDay" / "oneWeek" / "oneMonth" / "oneYear"）
    - summary: 是否显示文本摘要
    - count: 返回的搜索结果数量（默认 3）
    - **kwargs: 其他可选参数（透传给 API）

    返回:
    - 格式化后的搜索结果字符串（包含引用 / 标题 / URL / 摘要 / 网站名称 / 发布时间）
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
        "count": count,
        **kwargs
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        json_response = response.json()

        if json_response.get("code") != 200 or not json_response.get("data"):
            return f"Bocha 搜索API请求失败：{json_response.get('msg', '未知错误')}"

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
        # 网络/SSL 错误比 requests.RequestException 的 traceback 更友好——
        # 避免把整个 urllib3 traceback 灌给 LLM，让 agent 能直接读懂。
        # 末尾追加「其他搜索源可用情况」—— agent 能立刻看到还有什么备选。
        err_msg = str(e)
        others = format_others_available("BochaSearch")
        if "SSLError" in err_msg or "Connection" in err_msg or "timeout" in err_msg.lower():
            return f"Bocha 搜索失败（网络层不可达）：{err_msg}\n提示：请检查网络 / 代理设置，或确认 api.bochaai.com 可访问。{others}"
        return f"Bocha 搜索API请求失败：{err_msg}{others}"


if __name__ == "__main__":
    print(search_web("明天广州番禺天气怎么样？"))
