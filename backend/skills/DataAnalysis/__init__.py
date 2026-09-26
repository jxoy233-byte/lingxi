from .format import ChatDataAnalysisFormat, doc, help
from .database.config import (
    delete_database_config,
    list_database_configs,
    load_database_config,
    save_database_config,
)
from .database.query import query_mongo, query_sql, save_query_result

__all__ = [
    "ChatDataAnalysisFormat",
    "delete_database_config",
    "doc",
    "help",
    "list_database_configs",
    "load_database_config",
    "query_mongo",
    "query_sql",
    "save_database_config",
    "save_query_result",
]


# 自动给所有顶层函数挂 .help 属性（query_sql.help / save_database_config.help 直接拿 docstring）
import sys as _sys
from skills._shared._skill_help import auto_attach_help_module as _auto_attach_help_module
_auto_attach_help_module(_sys.modules[__name__])