"""
Docker 沙盒基础设施

- pool.py  SandboxPool 类 —— 预启动 K 个容器 + 每个容器 N 并发（v2 模型），
           暴露 execute(code, lang) 和 execute_command(cmd) 两个入口。
           cmd 工具 / code 工具默认走沙盒（local=False），沙盒不可用时降级到本机 venv。

历史：
- 原 `mcps/CodeSandboxPool.py` 单文件，2026-07 重构时移到 `mcps/sandbox/pool.py`，
  与 tools/ + permissions/ 形成 3 子包语义布局（运行 vs 工具 vs 权限）。
"""