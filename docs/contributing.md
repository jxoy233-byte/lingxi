# ChatMe 贡献者 / 开发者指南

本文档面向 ChatMe 项目的**开发者、贡献者、运维人员、AI 协作者**，汇总开发约定、踩坑记录、自动化测试与定时任务。**普通访客可跳过**——README 已经覆盖项目介绍、快速开始、部署打包与界面预览。

> AI 协作者（Codex / Claude agent 等）请同时阅读 [`CLAUDE.md`](../CLAUDE.md) 获取完整的工作流说明、关键文件、协作偏好与踩坑记录。

---

## 目录

- [启动与依赖](#启动与依赖)
- [前端开发：流式响应事件](#前端开发流式响应事件)
- [桌面端打包踩坑（macOS DMG）](#桌面端打包踩坑macos-dmg)
- [AI 协作者约定](#ai-协作者约定)
- [AI 测试 Agent（多轮对话测试）](#ai-测试-agent多轮对话测试)
- [AI 定时优化 Agent（cron job）](#ai-定时优化-agentcron-job)

---

## 启动与依赖

启动 Redis / 后端 / 前端 / 构建沙盒镜像的命令见 [README → 快速开始](../README.md#快速开始)。下述为开发侧的额外约定与踩坑：

- **MCP 服务器必须单独启动**：首次启动会自动执行 ① 检查 Redis  ② 清理残留沙盒容器  ③ 初始化沙盒池（min=1, max=4, per_container_concurrency=8）
- **Redis** 通过 `docker-compose up -d redis` 启动，端口 6024，密码 `123456`
- **代码沙盒**需要先 `docker-compose build sandbox` 构建镜像（镜像名 `chatme-python-sandbox:latest`）
- **unstructured 首次使用**：CSV / MD / XML 解析会自动下载 NLTK 数据（punkt、averaged_perceptron_tagger 等），需外网环境
- **配置脱敏**：`backend/.chatme/config.json` 包含真实 API key，提交时务必脱敏

## 前端开发：流式响应事件

前端通过 SSE 实时接收 `content` / `reasoning` / `tool_call_*` / `memory_wait_*` / `error` 事件：

- `memory_wait_start` / `memory_wait_done` 在新请求发起 / 中断续接 且上一轮记忆任务仍在后台时插入
- `interrupt` / `done` 事件携带 `memory_status` 字段（`idle` / `pending` / `done` / `failed`）

## 桌面端打包踩坑（macOS DMG）

**DMG 镜像问题**：dmg-builder 在 npmmirror 缺包，DMG 阶段会 404。绕过方案：

- 只打 zip：`npx electron-builder --mac zip --arm64 --x64`
- DMG 走 GitHub 直链：`ELECTRON_BUILDER_BINARIES_MIRROR=https://github.com npx electron-builder --mac dmg`

## AI 协作者约定

工作流实现细节（`imp_ipt` 锚点、ReAct 压缩清空 AIMessage.content + filter 兜底、`@node_guard` 装饰器、`_filter_thinking_content` MiniMax-M3 wrapper（含 `<tool_calls>` / `[<invoke name="cmd">][<command>...]` 7 个变体）、`MemoryManager` per-thread Lock、SandboxPool 池锁整段、Electron `file://` 三件套与图标包外、侧栏 CSS 7 条、流式会话快照 19 条、删除会话行内二次确认（小红叉状态机 + document click / Esc 取消，详见 CLAUDE.md 偏好 21）等）见 [`CLAUDE.md`](../CLAUDE.md)。新增节点 / 流式 SSE 入口 / 执行方法 / 二次确认交互前必须先读对应章节。

## AI 测试 Agent（多轮对话测试）

[`.test_agent/test_agent.md`](../.test_agent/test_agent.md) 是给后续 AI 协作者跑多轮对话测试的完整指南——硬约束（MCP 单调用 ≤280s / 单 batch ≤12 轮）、工具链（首选 Codex IAB 浏览器，备选本地 Chrome + CDP）、DOM 节点 selector、单 batch 完整流程代码、报告生成代码、4 个已确认的真实后端缺陷都在那。**接手后做端到端测试前必须先读这个文件**，不要凭直觉写 Playwright 脚本。已知 4 个真实后端缺陷（测试时遇到是已知问题，不是新 bug）：

1. 跨多轮记忆上限：19+ 轮 R12/R17 失败（IAB 状态丢失，非 LLM）
2. 优化输入无效：`POST /chat/improve_input` 返回的 `improved_text` 与原文完全相同
3. 业务复杂题卡死：复杂业务题（T08 类）触发 20+ 分钟无限工具调用循环
4. IAB 路由状态不稳：新会话 URL 在 R1 后从 `/` 跳到 `/<hash>`，可丢失前端历史

## AI 定时优化 Agent（cron job）

`~/.claude/scheduled_tasks.json` 里的持久化 cron job `a09d41ec` **每小时 :23 自动触发** ChatMe 后端优化 Agent：读 `.chatme/logs/thinking_chain-*.log`，按 ✅/❌ 清单自主优化 prompt / AI 配置（详见 CLAUDE.md "AI 自动化工具 → 定时优化 Agent"）。7 天后自动过期，需要时续期。