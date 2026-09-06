"""
三个搜索引擎（BochaSearch / Exa / Tavily）之间的可用性探测。

设计意图：当一个 skill 的搜索调用抛异常（网络层 SSL EOF / Connection refused /
timeout / 5xx 等），调用其他两个的 GET ping 快速判断「网络层是否可达」，
把可用情况追加到错误信息末尾，让 agent / 用户一眼看清现在还有哪个能用。

ping 策略：
- 用 GET 请求目标 endpoint（POST 才消耗配额，GET 只验网络层连通性）
- 4xx（401 / 404 / 405 / 400 等）→ 服务端在响应 → 网络通 + 端点活
- 5xx → 服务端崩了 → 不可用
- timeout / SSL EOF / Connection refused → 网络层不通 → 不可用
- timeout 设 3s（短）：ping 只是辅助信号，不能拖慢主流程
- 并发跑所有 ping（ThreadPoolExecutor）：失败路径最坏延迟 = max(每个 ping timeout)
  而不是 sum；正常成功路径完全不走这段代码，**0 额外延迟**

为什么不做「真 search ping」：
- 真实 search 会消耗 API 配额（Bocha 按次收费）
- 一次失败 search 已经让用户等 30s，再加 3×30s ping 不可接受
- GET 只验「端点活 + 网络通」，是用户最关心的信号
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

import requests

from ChatMe.ChatMeConfig import get_skills_config


_PING_TIMEOUT = 3  # 秒

# 显示名映射：error 信息里给用户/agent 看的是这个，不是内部 skill 路径
_DISPLAY_NAMES = {
    "BochaSearch": "BochaSearch（博查，国内中文）",
    "Exa":         "Exa",
    "Tavily":      "Tavily",
}


def _ping_bocha() -> bool:
    """GET Bocha endpoint 探活。无 key 也返 False（视为不可用）。"""
    api_key = get_skills_config().get("bocha_api_key") or ""
    if not api_key:
        return False
    try:
        r = requests.get(
            "https://api.bochaai.com/v1/web-search",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_PING_TIMEOUT,
        )
        return r.status_code < 500
    except requests.RequestException:
        return False


def _ping_exa() -> bool:
    """GET Exa 根域探活。"""
    api_key = get_skills_config().get("exa_api_key") or ""
    if not api_key:
        return False
    try:
        r = requests.get(
            "https://api.exa.ai",
            headers={"X-Api-Key": api_key},
            timeout=_PING_TIMEOUT,
        )
        return r.status_code < 500
    except requests.RequestException:
        return False


def _ping_tavily() -> bool:
    """GET Tavily endpoint 探活。"""
    api_key = get_skills_config().get("tavily_api_key") or ""
    if not api_key:
        return False
    try:
        r = requests.get(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_PING_TIMEOUT,
        )
        return r.status_code < 500
    except requests.RequestException:
        return False


# 三个 skill 的 ping 注册表。新加 skill 沿用同一注册格式即可。
_PINGERS = {
    "BochaSearch": _ping_bocha,
    "Exa":         _ping_exa,
    "Tavily":      _ping_tavily,
}


def check_available_except(failed: str) -> Dict[str, bool]:
    """并发检查除 `failed` 之外的其他搜索源是否可用。

    返回 {skill_name: is_available}，不含 failed 自身。
    并发跑（max_workers = 2）：最坏延迟 = max(ping timeout)，不是 sum。
    """
    pingers = [(name, fn) for name, fn in _PINGERS.items() if name != failed]
    if not pingers:
        return {}
    with ThreadPoolExecutor(max_workers=len(pingers)) as ex:
        # map 会等所有完成；每项独立 ping，超时短，total = max 单个耗时
        return {name: ok for name, ok in ex.map(lambda nf: (nf[0], nf[1]()), pingers)}


def format_others_available(failed: str, availability: Dict[str, bool] = None) -> str:
    """格式化「此时可用的其他搜索源」文案，追加到错误信息末尾。

    - 可用 ≥1 → 列出可用的名（中文显示名 + 实现名）
    - 都不通 → 列出实际探测过的源名（不含 failed 自身）+ 「也不可用」提示
    - ping 异常本身也静默（不递归 raise）
    """
    try:
        if availability is None:
            availability = check_available_except(failed)
        available = [n for n, ok in availability.items() if ok]
        if not available:
            # 列出本次实际探测过的源（不含 failed 自身），避免文案里出现矛盾
            others = [_DISPLAY_NAMES.get(n, n) for n in availability.keys()]
            return (
                f"\n提示：{'、'.join(others)} 也不可用，"
                f"可能是网络层全面不可达，或对应 key 都未配置 / 已失效。"
            )
        names = "、".join(_DISPLAY_NAMES.get(n, n) for n in available)
        return f"\n提示：此时可用的搜索源：{names}。"
    except Exception:
        # ping 探测本身出 bug 不能影响主错误信息返回
        return ""

