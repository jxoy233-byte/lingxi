"""
MCP（Model Context Protocol）工具层

布局（2026-07 三子包拆分重构后）：
- server.py           FastMCP 入口（CLI: chatme_mcp）；注册 code / cmd / find_skill /
                      interrupt / ctime 工具
- session.py           MCP stdio session 工具（client interceptor + session_id 注入）
- tools/              工具相关代码
  ├── code_fingerprint.py   code 工具语义指纹（永久批准精确匹配）
  ├── deprecated.py         sub_agent 已废弃（保留导入兼容）
  └── platforms/            跨平台 adapter（cmd/code/ctime prompt + 本地执行）
- sandbox/            沙盒基础设施
  └── pool.py         SandboxPool（Docker 容器池，K 容器 × N 并发 v2）
- permissions/        权限系统
  └── core.py         PermissionedToolNode + Redis hash 审批流 + LangGraph interrupt()

公开 import 样例：

    from ChatMe.ChatWorkflow.mcps.server import server  # FastMCP 实例
    from ChatMe.ChatWorkflow.mcps.sandbox.pool import SandboxPool
    from ChatMe.ChatWorkflow.mcps.permissions.core import PermissionedToolNode, init_permissions
    from ChatMe.ChatWorkflow.mcps.tools.platforms import get_platform, init_platform
    from ChatMe.ChatWorkflow.mcps.tools.code_fingerprint import code_fingerprint
"""