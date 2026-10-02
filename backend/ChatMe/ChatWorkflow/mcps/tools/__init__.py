"""
MCP 工具实现

- code_fingerprint.py  code 工具的语义指纹（imports + calls + lang + sandbox 四元组 SHA1），
                       用于永久批准 pattern 精确匹配
- platforms/           跨平台 adapter：Linux / Darwin / Windows 三平台 + base 抽象；
                       提供 cmd/code/ctime 工具的 prompt 片段 + 平台白名单 +
                       危险模式检测 + 本地 fallback 执行
"""