"""
时间和日期工具技能
提供获取当前实时时间和日期的功能
"""
from datetime import datetime
import json


def get_current_datetime() -> str:
    """
    获取当前的日期和时间

    Returns:
        JSON 格式的日期时间信息字符串
        包含：datetime, date, time, weekday, timestamp
    """
    now = datetime.now()

    weekdays_en = {
        0: "Monday",
        1: "Tuesday",
        2: "Wednesday",
        3: "Thursday",
        4: "Friday",
        5: "Saturday",
        6: "Sunday"
    }

    weekdays_cn = {
        0: "星期一",
        1: "星期二",
        2: "星期三",
        3: "星期四",
        4: "星期五",
        5: "星期六",
        6: "星期日"
    }

    result = {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday_en": weekdays_en[now.weekday()],
        "weekday_cn": weekdays_cn[now.weekday()],
        "timestamp": int(now.timestamp())
    }

    return json.dumps(result, ensure_ascii=False)


def get_formatted_date(format_str: str = "%Y-%m-%d") -> str:
    """
    获取指定格式的当前日期

    Args:
        format_str: 日期格式字符串 (默认：%Y-%m-%d)
                   常用格式:
                   - %Y-%m-%d: 2024-01-15
                   - %d/%m/%Y: 15/01/2024
                   - %Y年%m月%d日：2024 年 01 月 15 日
                   - %A, %B %d, %Y: Monday, January 15, 2024

    Returns:
        格式化后的日期字符串
    """
    now = datetime.now()
    return now.strftime(format_str)


def get_formatted_time(format_str: str = "%H:%M:%S") -> str:
    """
    获取指定格式的当前时间

    Args:
        format_str: 时间格式字符串 (默认：%H:%M:%S)
                   常用格式:
                   - %H:%M:%S: 14:30:45
                   - %I:%M %p: 02:30 PM
                   - %H 时%M分%S秒：14 时 30 分 45 秒

    Returns:
        格式化后的时间字符串
    """
    now = datetime.now()
    return now.strftime(format_str)

