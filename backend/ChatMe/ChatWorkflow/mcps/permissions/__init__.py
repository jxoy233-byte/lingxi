"""
权限系统 —— cmd / code 工具执行前的审批流

- core.py  PermissionedToolNode 类 —— 继承 LangGraph 官方 ToolNode + _awrap_tool_call hook，
           在敏感工具执行前调 LangGraph interrupt() 弹审批。
           4 档决策（approve / this-time-only / deny / feedback:<text>）走 Redis
           permission:{sid} hash，code 工具按 fingerprint 做永久批准匹配。

历史：
- 原 `mcps/permissions.py` 单文件，2026-07 重构时拆为 `mcps/permissions/core.py`，
  与 tools/ + sandbox/ 形成 3 子包语义布局（运行 vs 工具 vs 权限）。
"""