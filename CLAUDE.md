# ChatMe（灵析）AI 协作指南

> 完整项目说明见 [`README.md`](README.md)。本文档给 AI 协作者阅读：项目怎么组织、关键路径在哪、AI 协作的偏好与约定。

## 项目概述

ChatMe（产品名「灵析」Lingxi）是一个基于 LangGraph 的多智能体数据分析对话系统。后端 FastAPI + LangGraph + Docker 沙盒，前端 Vue 3 + Vite + Electron 桌面端。Redis 做 checkpoint + state saver，OSS 做文件存储。

## 技术栈

### 后端

- **框架**: FastAPI + LangGraph + LangChain；**MCP**: FastMCP 3.x；**包管理**: uv
- **状态管理**: Redis (checkpointer + state saver)
- **代码沙盒**: Docker 容器池（`ChatWorkflow/mcps/sandbox/pool.py` 的 `SandboxPool`）
- **文档解析**: docling + qwen-vl-utils + unstructured
- **对象存储**: oss2（阿里云 OSS）
- **定时任务**: APScheduler `AsyncIOScheduler + RedisJobStore`（Asia/Shanghai，重启可恢复）
- **LLM**: OpenAI 兼容 API（OpenAI / DeepSeek / 本地 VL 模型多 provider）

### 前端

- **Web**: Vue 3 + Vite（端口 18211）；**桌面端**: Electron 41 + electron-builder 26
- **样式**: CSS Variables + 原生 CSS；**Markdown / 数学**: marked + highlight.js + katex
- **Electron 关键能力**：`file://` 协议拦截（→ 后端代理等价 Vite dev proxy）、SSE 流透传、↻ 页面刷新按钮（ChatHeader + DataAnalysisTree 共用 SVG path `M20.49 15a9 9 0 1 1-2.12-9.36L23 10`）、多环境切换（dev/test/prod）、**单窗口架构** + BootstrapView 浮窗 + `servicesReady` IPC 状态机 + autoEnter 三态按钮（详见偏好 22 / 23）

## 架构

```
backend/
├── ChatMe/                    # FastAPI 应用代码
│   ├── APIRouter/             # /chat /static /api /admin (admin_config + scheduled_tasks + checkpoint_janitor + message_queue)
│   ├── ChatMeConfig/          # 配置加载（_load mtime + force_reload 热加载）
│   ├── ChatService/           # SSE 流式 + FilesLoaders 大文件截断
│   ├── ChatWorkflow/          # LangGraph 5 节点 + ReAct 压缩 + Memory + SkillRegistry + mcps(server/session/permissions/sandbox/tools)
│   │   └── CheckpointJanitor.py
│   ├── LoggingManager/        # QueueHandler 异步日志
│   └── test/
├── skills/                    # Bocha / Exa / Tavily / ImageParser / DataAnalysis (含 fonts/) / Scheduler / Memory / SkillForge
├── .chatme/                   # 局部配置
├── pyproject.toml
└── main.py                    # FastAPI 入口，lifespan: chat_service → scheduler → cleanup

frontend/
├── electron/                  # main.js / preload.js / electron.config.js
├── src/                       # App.vue + components/ (含 ChatHeader / Sidebar / MessageList 等)
├── build/                     # electron-builder 图标（icon.icns/ico/png）
└── package.json

sandbox/Dockerfile             # 代码沙盒镜像（Python 3.12）
docker-compose.yml             # Redis 服务编排（端口 6024）
```

> 详细目录树见 `README.md`，本文件不再复述。

## 工作流

```
用户输入 → input_parse_node → context_assembly_node
                                  ↓
                          agent_node ↔ tool_execution_node（循环）
                                  ↓
                            final_node → END
```

### 节点职责

| 节点                      | 职责                                                                                                          |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- |
| `input_parse_node`      | 输入预处理、文件解析（docling / OSS / VL）、输入优化（`improve_input`），给 `imp_ipt` 标记 `additional_kwargs.imp_ipt=True`        |
| `context_assembly_node` | 上下文组装（拼接 `imp_ipt` / memory / 当前轮循环消息）+ **ReAct 流程压缩**（4 阶段循环后台异步，见下）+ **done cycle 检测 + `RemoveMessage` 清理**（v0.2.0 新图）+ 中断检查 |
| `agent_node`            | **v0.2.0 新图**：AI 决策（调工具 / 调 `done` 收尾 / 无 tool_calls 走英文 SysMsg 重试 ≤ 3 次后强制 final_node）；**老图**：`should_end_node` LLM 决策节点判定结束。工具调用超过 50 次会注入 SystemMessage 提示停止 |
| `tool_execution_node`   | `PermissionedToolNode`（继承 LangGraph 官方 `ToolNode` + `_awrap_tool_call` hook），执行搜索 / MCP / Docker 沙盒 / **`done` 工具**（v0.2.0 新图）；`cmd` / `code` 工具执行前走 `interrupt()` 弹审批，Redis `permission:{sid}` hash 跨 SSE 流复用决策 |
| `final_node`            | 最终回复生成（独立于 agent 的 LLM），用 **dynamic system prompt** 把 `imp_ipt` 注入 system 层（不参与 messages 序列），输出带 SUMMARY 标记 |

State 定义在 [`backend/ChatMe/ChatWorkflow/config/models.py`](backend/ChatMe/ChatWorkflow/config/models.py)（`ChatStateCore2` / `FileParseState`），用 LangGraph TypedDict + `add_messages` reducer。

### ReAct 流程压缩（4 阶段循环 + 后台异步，不阻塞工作流）

`context_assembly_node` 每轮进入时按 cool-down 检测条件（默认 `(tool_call_times - last_compact_at) >= 5` 轮 **且** 最近 5 轮 chars ≥ 10000 **且** 无 pending **且** ≥1 完整 loop）触发；命中后用 `asyncio.create_task` 启动 `_background_compact_react` 后台 LLM 调用（**不 await，主流程立即返回**），完成后 result 写 `_background_compaction_results[thread_id]`，同时设 `pending_compaction_replace_at = len(_find_complete_tool_loops(context)) + REACT_KEEP_LOOPS(2)`（**v0.2.0 起改用完整 loop 数，不再用 `tool_call_times + REACT_COMPACT_REPLACE_AFTER`**；动机：并行 1-3 个工具让 `tool_call_times` +2 不稳定）；agent 用旧 context 推进 N=2 个完整 loop 不打扰；到 `len(current_complete_loops) >= replace_at` 时调 `_build_compaction_draft` 重组 context = `[memory + imp_ipt] + [ReAct 摘要 SystemMessage] + [最近 REACT_KEEP_LOOPS=2 轮原文]`，清 pending + 更新 last_compact_at → 回到阶段 1 循环。**v0.2.0 新增**：`compression_handled_this_round` bool 标记防同一轮 iteration 2+ 重复压缩；`is_done_cycle=True` 时整段 ReAct 压缩跳过（避免无用压缩产物灌给 final_node + 后台 asyncio 任务泄漏到 `_background_compaction_results`）。

关键约束（详见 `ChatWorkflow/core.py` 注释与下方偏好 7 / 7.1 / 7.2 / 7.3）：

- 压缩范围：除最近 2 轮外所有 loop；imp_ipt 之前整体保留；产物是 SystemMessage 形式插入 imp_ipt 之后
- 输入净化：`_build_clean_compact_input` 清空 AIMessage.content（去 AI 思考过程 / 描述），但**保留 `tool_calls` 字段**（API 强校验需要）
- 失败兜底：长度 [250, 4096] 区间外 / filter 清不干净 / LLM 异常一律 `return None`；下限 250 是"有效压缩"最低门槛，低于此值说明 prompt 没理解或被 tool_call 残留污染，跳过本轮保留原 context
- filter 兜底：M3 weights 看到 `tool_calls` 字段 100% 会模仿输出伪 tool_call 块，filter regex 7 个变体必须覆盖；新增 M3 输出格式时同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）
- 专用 LLM：`get_react_compact_config()`，temp=0.3 / max_tokens=4096（env 可覆盖），目标 ≤ 4096 tokens 中文 markdown
- 辅助方法（`core.py`）：`_content_chars` / `_should_detect_compact` / `_find_imp_ipt_idx` / `_find_complete_tool_loops` / `_build_compaction_draft` / `_build_clean_compact_input` / `_try_compact_react` / `_background_compact_react`；**全程靠 content 特征扫描定位，不写死下标**
- 后台任务管理：`ChatWorkflow.__init__` 维护 `_background_compaction_tasks: Dict[str, asyncio.Task]` + `_background_compaction_results: Dict[str, Optional[str]]` per-thread；任务 finally 块 pop 自己避免引用泄漏

### 工作流启动入口

```bash
# 主服务（默认端口 38211，stdio 模式下会 fork MCP 子进程，无需单独起）
uv run chatme_main

# 开发模式单独起 MCP 服务（stdio 模式，监听 stdin/stdout ——
# chatme_main 会自动 fork 它，正常运行不需要手动起）
uv run chatme_mcp
```

## 前端组件

详见 [`frontend/README.md`](frontend/README.md) 的组件说明章节；以下是核心要点：

- **`App.vue`**：全局状态 + SSE 分发 + `_sessionHadError` 错误气泡保护 + `_activeStreamingSessions` / `_approvalPendingSessions` / `_completedSessions` / `_errorSessions` 四套 Set（独立非 union）驱动侧栏状态点 + `_pendingQueue` / `_queueDrainDeferred` 消息排队 + `scheduledTasksMap` 定时任务缓存 + `refreshPage()` 触发 `window.location.reload()`
- **`Sidebar.vue` / `ConversationItem.vue`**：全量入 DOM + 自定义 webkit 滚动条 + 删除会话行内二次确认状态机（偏好 21）+ v0.1.5 起底部内嵌 ⏰ 触发按钮 + 展开任务列表（按 `lingxi.scheduledTasksExpanded` localStorage 持久化，max-height 110px）+ 四色状态圆点（streaming 蓝闪 / approval 黄脉冲 / errored 红常 / completed 绿常）
- **`MessageList.vue`**：滚动控制（入场 easeInOut + 流式 ramp + 100ms 防抖 + wheel/touch 让出）；转发 `scheduled-task-*` / `restart-session`
- **`MessageItem.vue`**：Markdown / 代码高亮 / 错误框 / 中断态「重新对话」按钮；审批 UI 内嵌到对应 toolCall 行 + 读 `tool.args.local` 判执行环境
- **`MessageInput.vue`**：流式期间不禁用发送，消息由 App.vue 入队（偏好 29）
- **`ScheduledTaskItem.vue`**（v0.1.5 起）：⏸/▶ 启停、⚡ 立即运行、🗑 行内小红叉二次确认（参考偏好 21）
- **`ChatHeader.vue`**：↻ 刷新按钮（SVG path `M20.49 15a9 9 0 1 1-2.12-9.36L23 10` + polyline，与 DataAnalysisTree 共用）
- **`DataAnalysisTree.vue`**：面板头部 ⬇ ZIP + 👁 HTML 预览（偏好 26）+ 🗑 「清空回收站」按钮（弹 ConfirmDialog 物理清空当前会话 `.trash/{sid}/`）
- **`DataTreeNode.vue`**：文件行悬浮 × 红叉行内二次确认删除（沿用偏好 22 模式），调用 `DELETE /chat/{sid}/file?file_path=...` 软删除（v0.1.7）
- **`SettingsDialog.vue`**：4 tab + VL `local` 开关 + 脱敏编辑 + `buildPayload()` diff-only + 「立即清理 checkpoint」按钮（POST `/admin/checkpoints/prune`）
- **`CheckpointPanel.vue` / `FilePreviewPanel.vue` / `FilePreviewModal.vue` / `WebPreviewPanel.vue` / `SearchResults.vue` / `ConfirmDialog.vue`**：见 README.md

### Electron 主进程能力

- **多环境支持**：`development` / `test` / `production`，通过 `NODE_ENV` 严格切换（不再受 `!app.isPackaged` 拖累，否则 `electron .` 永远走 dev 分支）
- **`file://` 协议拦截**：`protocol.handle('file', ...)` 在 `app.whenReady()` 内注册（必须在 createWindow 之前）；`/chat/*` + `/static/*` 走 `net.fetch` 转发到后端，其他走白名单校验后从 asar 内 `dist/` 读盘
- **API 转发三件套**：method / headers / body 必须显式透传 + `duplex: 'half'`（POST body 否则被丢，等于发 GET）；SSE 流必须显式 `new Response(upstream.body, ...)` 重建 stream 避免 buffer
- **静态文件白名单**：`resolvedPath` 必须在 `distDir + path.sep` 之下，否则 403（防 `fetch('/etc/passwd')`）；hashed assets 永久缓存，index.html 不缓存
- **图标必须放包外**：`nativeImage` 不读 asar 内文件，`build/` 通过 `extraResources` 复制到 `app/Contents/Resources/build/`，运行时用 `process.resourcesPath` 取；`app.dock.setIcon` / `BrowserWindow.icon` 都必须是 PNG
- **安全策略**：生产环境禁用 DevTools / 右键菜单 / 危险快捷键；外部链接走 `shell.openExternal`
- **单窗口架构 + autoEnter 三态按钮**：详见偏好 22 / 23

## 关键文件

> 完整职责清单见 `README.md`；本文件只列**AI 协作最常碰到的关键路径**：

### 后端（按调用频次倒排）

- **`ChatWorkflow/core.py`**：5 节点逻辑 + 5 个 LLM 实例（`MessagesPlaceholder`）+ ReAct 压缩 + final_node 动态 system prompt
- **`ChatService/core.py`**：SSE 流式（`message_stream` / `resume_permission_stream` / `invoke_interrupted_stream` 同构）+ `_memory_update_tasks` 串行队列 + `memory_wait_*` 事件 + 回溯走 `CheckpointJanitor.retarget_to()`
- **`ChatWorkflow/mcps/sandbox/pool.py`**：Docker 容器池 `SandboxPool`（v2 K 容器 × N 并发，池锁必须包住整段 pop→exec→append，偏好 14）
- **`ChatWorkflow/mcps/permissions/core.py`**：`PermissionedToolNode` + Redis `permission:{sid}` hash + 4 档决策（approve / this-time-only / deny / feedback:）+ `code_fingerprint` 永久批准
- **`ChatWorkflow/mcps/tools/platforms/`**：多平台 prompt adapter（`base.py` 抽象 + `darwin.py`/`linux.py`/`windows.py` + `registry.py` 按 `platform.system()` 选），工具 shell 风格差异都走这里，不要在 prompt 硬编码 uname
- **`ChatWorkflow/mcps/server.py` + `session.py`**：FastMCP 工具入口 + stdio 长生命周期子进程 + `ClientSession` 常驻复用（不再每次重开连接）
- **`ChatWorkflow/skills/registry.py`**：`SkillRegistry` 扫 `backend/skills/` SKILL.md + frontmatter 解析 + `_maybe_rescan()` 按每个 SKILL.md `stat()` mtime 检测（macOS APFS 不更新父目录 mtime）+ `build_mount_args()` 加 `@functools.lru_cache(maxsize=1)`，`reset_skill_registry()` 时必须 `cache_clear()`
- **`ChatWorkflow/Memory/core.py`**：per-thread `asyncio.Lock` + 临时文件原子写（`fsync` + `os.replace`）
- **`ChatWorkflow/decorators.py`**：`@node_guard` 装饰器，`except GraphBubbleUp` 必须原样 raise（控制流异常穿透）
- **`ChatWorkflow/CheckpointJanitor.py`**：业务层 LangGraph checkpoint prune + `retarget_to()` 覆写 latest 指针
- **`APIRouter/checkpoint_janitor.py`**：HTTP 层唯一路由 `POST /admin/checkpoints/prune`
- **`ChatWorkflow/config/graph_config.py`**：prompts + `get_react_compact_config()`；`PROMPT_MAIN_FLOW` 只讲决策流，具体工具用法下沉到 `platforms/base.py`
- **`ChatWorkflow/config/models.py`**：`ChatStateCore2` / `FileParseState` TypedDict + `add_messages` reducer
- **`ChatMeConfig/core.py`**：`_load()` mtime + `force_reload()` + `save_config()` 原子写 + 按段决定 `restart_required`（permissions/skills 立即生效；llm_providers 需重启）+ `vl.local` 决定是否加载本地 VL 模型（`false` 时 `_resolve_vl_fallback()` 无条件用主用 LLM 三元组）
- **`APIRouter/admin_config.py`**：`/admin/config` GET/PUT（白名单 llm_providers/skills/permissions，pydantic `extra="forbid"`）+ `/admin/restart` POST（写 marker + `os.execv`）+ `/admin/health` GET
- **`APIRouter/main.py`**：`/chat` 前缀主对话路由
- **`APIRouter/scheduled_tasks.py`**：`/admin/scheduled-tasks` CRUD + APScheduler `AsyncIOScheduler + RedisJobStore`（Asia/Shanghai）
- **`APIRouter/message_queue.py`**：`/chat/{sid}/queue` Redis FIFO 持久化（≤20 × 4000 字符），**不主动 drain**（前端 drain，见偏好 29）
- **`APIRouter/data_export.py`**：`/export/artifacts`（DataAnalysis ZIP/HTML）+ `/export/turn/{cid}`（OpenAI JSON + state 备份）
- **`APIRouter/static_file.py`**：`/static` 静态文件 + 文件树；session_id regex 同时支持 32 位 + 12 位 hex；fallback 规则见偏好 21
- **`APIRouter/model_vl.py`**：VL 模型路由（`local=false` fallback 到主用 LLM）
- **`APIRouter/timed_clean.py`**：定时清理（含 `PRESERVED_TOP_DIRS={"cached/.fonts"}` 兼容 legacy 字体路径，偏好 31）
- **`ChatService/FilesLoaders/core.py`**：文件加载 + `_maybe_truncate` 大文件截断（`TEXT_TRUNCATE_LENGTH=4000`）
- **`LoggingManager/logging_config.py`**：`QueueHandler` + `QueueListener` 异步日志 + `get_thinking_chain_logger()` 单开思维链日志文件
- **`skills/DataAnalysis/`**：数据分析规范包 + 数据库子模块（只读 MySQL/SQLite/PostgreSQL/MongoDB 跨会话配置）
- **`skills/DataAnalysis/fonts/`**（v0.1.6）：matplotlib 中文字体随 skill 自动 mount，无需 gitignore 反向规则
- **`skills/Scheduler/`**：4 层模块（`core` / `models` / `handlers` / `registry`）+ `SKILL.md`；4 个顶层函数走 HTTP 调 `/admin/scheduled-tasks/*`，**必须 `code(..., local=True)`**（沙盒缺 `apscheduler` / `redis` 包）
- **`skills/Memory/`**（v0.1.5）：`remember()` / `recall()` 写入 `.chatme/memory/{tid|global}/{facts|preference}.md`；**写入必须 `code(..., local=True)`**；`context_assembly_node` 每轮开头自动合并注入
- **`skills/SkillForge/`**（v0.1.5）：`create_skill()` / `list_skills()` / `read_skill()`；registry mtime 自动重扫，无需重启；**必须 `code(..., local=True)`**
- **`main.py`**：FastAPI 入口，lifespan 嵌套顺序 `chat_service → scheduler → cleanup`；`uvicorn.run(app, ...)` **传对象不传字符串**（字符串会二次 import）
- **`sandbox/Dockerfile`**：代码沙盒镜像（Python 3.12）

### 前端（精简）

- **`src/App.vue`**：全局状态 + SSE + `refreshPage()`；详细功能列表见 `frontend/README.md`
- **`src/components/`**：业务组件（ChatHeader / Sidebar / ConversationItem / MessageList / MessageItem / MessageInput / ScheduledTaskItem / CheckpointPanel / FilePreviewPanel / FilePreviewModal / DataAnalysisTree / DataTreeNode / WebPreviewPanel / SearchResults / SettingsDialog / ConfirmDialog）
- **`electron/main.js`** + **`electron.config.js`** + **`preload.js`**：主进程 + 配置 + IPC bridge；详见偏好 22 / 23
- **`vite.config.js`**：同时导出 `viteServerConfig` 给 Electron 复用，`base: './'` 必须在顶层
- **`package.json`** + **`build/icon.{icns,ico,png}`**：electron-builder build 配置（files 白名单 + extraResources + 三平台 icon）

## 命令行工具

```bash
# 安装 wheel 后全局可用
chatme_main                      # 主服务（默认端口 38211），stdio 模式下 fork MCP 子进程
chatme_mcp                       # 仅开发模式单独起 MCP（stdio，正常运行不需要）

# 开发模式（不进 wheel）
cd backend
uv run python main.py            # 主服务
uv run python -m ChatMe.ChatWorkflow.mcps.server   # MCP 服务

# 沙盒镜像（首次使用前构建）
docker-compose build sandbox    # chatme-python-sandbox:latest

# Redis
docker-compose up -d redis       # 端口 6024，密码 123456
```

## AI 自动化工具

### 测试 Agent（多轮对话测试）

**端到端测试前必读 `.test_agent/test_agent.md`** —— 硬约束、工具链、DOM selector、完整流程代码、报告生成、已确认的真实后端缺陷都在那。不要凭直觉写 Playwright 脚本。

简要约束：

- **硬约束**：MCP 单调用 ≤280s；单 batch ≤12 轮；IAB 同会话 22+ 轮 R2 后必然 timeout（必须分多 batch 重开会话）
- **首选**：Codex IAB（经 `mcp__node_repl__js` 调 Playwright API）；备选本地 Chrome + CDP（`--remote-debugging-port=9222`）
- **5 个必踩陷阱**：① IAB 22+ 轮卡死（分 batch）；② send-btn 延迟（`waitForTimeout(500)` + `click({force:true})` 跳 disabled）；③ URL 漂移（`/` → `/<hash>` 正常）；④ 完成判定看 AI 文本稳定 1.5-2.5s；⑤ MCP 边界丢 Vue 状态（每 batch `getTab()` + `evaluate()` 重读）
- **已确认的真实后端缺陷**：① 跨多轮记忆上限 19+ 轮 R12/R17 失败；② `POST /chat/improve_input` 返回与原文相同的 `improved_text`；③ 复杂业务题（T08 类）触发 20+ 分钟无限工具调用循环；④ IAB 路由状态不稳

### 定时优化 Agent（cron job `a09d41ec`）

`~/.claude/scheduled_tasks.json` 里有个持久化 cron job **每小时 :23 自动触发** ChatMe 项目后端优化 Agent（durable，跨 session 持续；**7 天后自动过期**需续期）。目的：扫思维链日志 + 自动修复 prompt / AI 配置问题。

行为摘要（完整 prompt 见 cron job 本身）：

- 读 `.chatme/logs/thinking_chain-YYYY-MM-DD.log`（偏好 10.1 提到的独立思维链日志）
- 扫 9 个 call site：`imp_ipt` / `react_context` / `react_context_after_compact` / `agent_node_in` / `agent_node_out` / `should_end_in` / `should_end_decision` / `final_node_in_context` / `final_node_out`
- 判定只看思维链方向 + 输出方向合不合适；max_tokens 触发的截断不当 bug
- **✅ 可自主改**：prompt 删冗段加 few-shot 锚定、加 `_filter_thinking_content` regex、env 拆分、改 `format_thinking_chain` max_chars、`PROMPT_MAIN_FLOW` 反冗余约束
- **❌ 不做**：调 max_tokens / temperature、大范围 prompt 重写、加新工具 / 节点、改 ReAct 流程、改 should_end_node 决策、改前端 / Electron、不主动 git commit
- 多文件改动要先列出来（5+ 文件不一次性下）

**接手注意**：发现 `~/.claude/scheduled_tasks.json` 里还有 `a09d41ec` 说明 cron 在跑；文件被清掉（换机器 / 清理 `~/.claude`）需要重新挂上。管理命令：`claude --cron-list` / `--cron-delete a09d41ec`；续期用 `CronCreate` 重建。

## AI 协作偏好

> 这些偏好从用户对话中沉淀，存于 `/Users/jx/.claude/projects/-Users-jx-coding-projects-ChatMe/memory/`。改前先读 `MEMORY.md` 看完整索引。

### 工程约定

1. **后端最小化 + 前端动态加载**：文件树 / 列表类接口后端只返扁平列表，前端构树 + 动态加载内容；path 须含 `cached/` 前缀。
2. **沙盒隐藏文件过滤**：`sandbox/sitecustomize.py` 过滤规则（`.` / `__` 挡、`_` 不挡）+ 只在挂载点根目录一层不递归子目录。
3. **沙盒 config 同步策略**：用中间文件隔离 skills key，仅在 MCP 启动 / 容器重建时重生成，不做运行时自动同步。
4. **流式响应滚动 UX**：入场 `easeInOut`；流式 ramp（慢→快）+ 100ms 打断防抖；用户 wheel / touch 立即让出控制权。
5. **MCP 工具参数前缀被剥（v0.1.3 起改为 `local`）**：Python `local`（旧 `sandbox`/`use_sandbox`）在 MCP schema 里是 `local` 参数；过滤 / 判断要查实际 args key，兼容新旧两种。
6. **`should_end_node` 设计偏好**：LLM 决策节点的单条喂入 / 完整写回、低频字面量子串匹配、独立 `max_tokens` env、prompt / 解析兜底一致。
7. **ReAct 流程压缩 4 阶段循环**：**后台异步 + 不阻塞工作流**——见上方「ReAct 流程压缩」章节；imp_ipt 是唯一 draft 切分锚点（`additional_kwargs.imp_ipt=True`），全程不写死下标；后台任务 finally 块 pop 自己；result 为 None（LLM 失败 / 长度兜底）时不写 pending。
8. **Memory 并发安全**：`MemoryManager` 内部维护 `_thread_locks[thread_id]`，`update_memory` / `delete_memory` / `backtrack_memory` / `delete_latest_backup_memory` 全部走 `async with self._get_thread_lock(thread_id)`；文件写入走 `_atomic_write_text`（写 `*.tmp` + `fsync` + `os.replace`）。
9. **ChatService 记忆任务串行**：每会话在 `_memory_update_tasks[session_id]` 里只保留一个 asyncio.Task，新任务通过 `asyncio.shield` 串接上一轮；新请求发起 / 删除会话 / 回溯 前会先 `_wait_previous_memory_update` 等待；SSE 暴露 `memory_wait_start` / `memory_wait_done` 事件，`interrupt` / `done` 事件携带 `memory_status` 字段。
10. **异步日志**：写文件走 `QueueHandler` + `QueueListener` 模式，业务线程不入 IO；`atexit` 统一 `listener.stop()` 清理。
    10.1. **AI 思维链日志单开文件**：ChatWorkflow 各节点的 `format_thinking_chain(...)` 类思维链日志（`imp_ipt` / `react_context` / `react_context_after_compact` / `agent_node_in/out` / `should_end_in/decision` / `final_node_in_context/out` 共 9 处）**必须**走 `self.thinking_logger.info(...)`（`LoggingManager.logging_config.get_thinking_chain_logger()` 返回），写到独立文件 `thinking_chain-YYYY-MM-DD.log`，**严禁**写到主日志 `YYYY-MM-DD.log`；目的是让 LLM 决策链日志与业务日志按文件维度隔离，回溯时不被工具调用 / Redis / 文件 IO 等噪声淹没。新增节点若要加思维链日志，沿用 `thinking_logger`；`should_end_decision` / `final_node_out` 等带"决策"性质的简明日志也走 `thinking_logger`（不只是长消息）。
11. **节点异常统一兜底**：所有 LangGraph 节点（ChatWorkflow 5 个主节点 + 文件图 3 个节点 + sub_agent agent_node）都打 `@node_guard("<name>")`：`except Exception` 捕获后 log + 包装 `RuntimeError` 让 SSE 外层统一返回 `error` 事件；但 `except GraphBubbleUp`（LangGraph 控制流异常的基类，涵盖 `GraphInterrupt` / `ParentCommand` 等）必须**原样 `raise`**，不能包装 —— `interrupt()` 主动中断、`Command` 透传都依赖该异常穿透各层到达 runtime。新加节点必须继承这个分层约定。
12. **前端错误气泡保护**：App.vue 维护 `_sessionHadError: Set<session_id>`，SSE `error` 事件触发时把 `session_id` 标记为保护态；保护态下 `done` 事件不会覆盖错误气泡，`refreshConversation` / `updateTitleAndRefresh` 跳过 messages 重拉，只更新侧边栏；用户主动发起新一轮请求或续接时清掉保护态。
13. **`cmd` / `code` 工具默认走沙盒（v0.1.3 反向命名 `local`）**：`server.py` 的 `cmd` 和 `code` 都默认 `local=False`（**反向 default**：不传 = 沙盒隔离；要本机才显式 `local=True`），内部仍用 `use_sandbox = not local` 变量走原有逻辑。沙盒不可用时降级到本机（`cmd` → 本机 subprocess.run，`code` → 本机 venv）；白名单 + 危险检测 + 脚本检测在沙盒 / 本机两边都做。沙盒入口是 `SandboxPool.execute_command(cmd)` / `execute(code, lang)`，分别对应 shell / code 执行；`execute_command` 直接 `docker exec sh -c <cmd>`，命令里可含管道 / 重定向 / glob；`execute` 先写 `/code.py` 再跑再删（避免敏感信息残留）。**执行环境区分（v0.1.3 新增）**：`_permission_target_for` 推断 `execution_env = "sandbox" if use_sandbox else "local"`；`interrupt()` payload 带 `execution_env` 字段透传到 SSE；前端 `App.vue:handlePermissionRequest` 写入 `pendingToolApproval.executionEnv`，`MessageItem.vue` 容器挂 `tool-inline-approval--local` modifier class，**唯一视觉差异 = 淡红背景叠加** `rgba(239, 68, 68, 0.06)`（叠在原黄色边框上）；标题文案、批准按钮颜色、图标等保持 sandbox 原状，避免视觉过重。
14. **SandboxPool 池锁必须包住整个 pop → exec → append 周期**：池容量有限（默认 2），并发 N+1（N=池容量）调用时第 N+1 个会撞上空列表报 `No available containers in pool`；**`self.containers.pop()` 必须在 `with self.lock:` 内**，否则 pop 跑在锁外、exec 跑在锁内，N+1 并发下 N 个 pop 完，第 N+1 个直接 `if not self.containers` 报错。`execute(code, lang)` 和 `execute_command(cmd)` 都用同一个 `self.lock`，所有"取出容器 → 跑 → 归还"必须整段锁内。新加执行方法必须继承这个锁结构。
15. **Electron `file://` 协议拦截必须透传 method/body/headers**：`protocol.handle('file', ...)` 在 `app.whenReady()` 内注册；`/chat/*` 转发到后端时**必须**显式带 `method: request.method, headers: request.headers, ...(request.body && { body: request.body, duplex: 'half' })`，否则 POST `/chat/` 的 body 被丢、后端收到 GET 请求、SSE 流式响应直接退化成一次性；SSE 流必须显式 `new Response(upstream.body, { status, statusText, headers })` 透传 stream，避免 `protocol.handle` 把 stream 当 buffer 处理
16. **Electron 图标必须放包外**：`nativeImage.createFromPath` 不读 asar 内文件；`build/` 通过 `package.json` 的 `extraResources` 复制到 `app/Contents/Resources/build/`（macOS）/ `app/resources/build/`（Win）/ `app/build/`（Linux），运行时用 `process.resourcesPath` 取真实路径；`paths.icon` / `paths.iconMac` 通过 `app.isPackaged` 切换 dev (`__dirname/build/icon.png`) vs packaged (`process.resourcesPath/build/icon.png`)；`app.dock.setIcon` 和 `BrowserWindow.icon` 都必须是 PNG，传 `.icns` 会得空 image 并 Promise reject
17. **Electron `protocol.handle` 静态文件必须白名单校验**：`resolvedPath = path.resolve(pathname)` 后必须检查 `startsWith(distDir + path.sep)`，否则 `403 Forbidden`；不写这一行的话渲染层一句 `fetch('/etc/passwd')` 就能读任意磁盘路径
18. **Electron 输出目录用 `release/electron-builder`**：`directories.output` 不要设 `dist/electron-builder`，否则会和 Vite 的 `dist/` 撞目录，且会被 `files` 模式误打进 asar；当前 `output: "release/electron-builder"` + `files: ["dist/**", "electron/**", "vite.config.js", "package.json"]` 是白名单显式列出，asar 体积 5.6MB（之前未优化时 419MB）
19. **可滚动侧栏/面板 CSS 约定**：所有可滚动列表（Sidebar / DataAnalysisTree / WebPreviewPanel / CheckpointPanel 等）必须按以下 7 条点写：① 数据全量入 DOM，禁止 `slice(0, N)` / `displayCount` 切片；② 侧栏 `height: 100vh; flex-shrink: 0; overflow: hidden`，外层不被内容撑大；③ 固定头部 `flex-shrink: 0` 锁尺寸；④ 滚动区用 `height: calc(100vh - X)` **不走** `flex: 1 + min-height: 0`（flex 子项 `min-height: auto` 会让 overflow 失效）；⑤ **`overflow-y: auto`**——浏览器默认；**禁止**用 `overflow-y: scroll`（始终预留轨道，列表短时也空占位）、禁止 `overflow-y: hidden`（用户感知不到还有内容）；⑥ **CSS-only 没法做到「溢出时才显示滚动条」**：因为 `App.vue` 全局 `::-webkit-scrollbar { width: 8px; ... }` 会强制 macOS 自动隐藏失效，scrollbar 一直挂着。要做到「溢出时才出现」必须用 JS：用 `ResizeObserver` 监听 list 尺寸 / `scrollHeight > clientHeight + 1` 判断溢出，溢出时挂 `.has-overflow` class（CSS：`::-webkit-scrollbar { width: 0 }` / `.has-overflow::-webkit-scrollbar { width: 6px }` / thumb `background: var(--border-color); min-height: 30px` / hover `var(--text-secondary)`）；⑦ `@scroll="handleScroll"` 直接绑在 `.list`，mounted 用 `$nextTick` 等首次渲染完再 `checkOverflow()`，监听 conversations / collapsed watch + window resize。
20. **流式响应会话保存（per-session 快照 + 切走保留 in-progress）**：用户流式期间切到别的会话，原会话的 SSE 增量不能丢；切回时显示该会话的实时 in-progress 状态；侧栏该会话处显示闪烁小点；流式完成所触发的 `refreshSession` 不能影响用户当前所在会话的视图。**实现要点**：

- **三件套**（`App.vue` data）：`_activeStreamingSessions: Set`（驱动侧栏小点 + loadConversation 分支判断）/ `_streamingMessages: Map<sid, messages[]>`（**与 this.messages 同源引用**，不深拷贝——SSE 改 this.messages 自动同步 snapshot）/ `_streamingMeta: Map<sid, {aiIndex, responseStartTime, ...}>`。
- **SSE 循环 `sessionChanged` 分支**：`this.currentSessionId !== requestSessionId` 时，所有 content / reasoning / tool_call_* / done / error / interrupt 事件增量**只写到 snapshot**（`snap[meta.aiIndex] = {...}`），不碰 this.messages；非切走分支维持 `this.messages[aiIndex] = {...}`（引用同源自动同步 snapshot）。
- **每个 done / error / interrupt 必清三件套**（不管分支）：`_activeStreamingSessions.delete(sid)` + `_streamingMessages.delete(sid)` + `_streamingMeta.delete(sid)` + `await refreshSession(sid)`（**只动侧栏，不动 this.messages**）。
- **Vue 2 Set 响应式陷阱**：`.add` / `.delete` 不触发子组件重渲染，必须整 Set 替换：`this._activeStreamingSessions = new Set(this._activeStreamingSessions)`。
- **`loadConversation` 双分支**：流式分支直接 `this.messages = snapshot` + `this.isLoading = true` + `this.startResponseTimer()`，**不调** `get_conversation`（否则会覆盖 in-progress）；非流式走原 `get_conversation`。
- **`cleanupLoadingState` 绝不能 pop 流式 AI 消息**（snapshot 与 this.messages 同源，pop 会污染 snapshot）；**`startResponseTimer` 不要写 this.messages**（切走后 this.messages 是别的会话数组）；**`requestSessionId` 必须在 SSE 循环开始前锁定**（`const requestSessionId = this.currentSessionId`，handleResume / handleRestream 易漏）。
- **右键 refresh 保护**：流式中会话不能调 `get_conversation` 重拉 messages，只调 `refreshSession` 刷侧栏。**删除会话清理**：`confirmDelete` finally 块也清三件套。
- **侧栏小点**：`ConversationItem` 加 `isStreaming: Boolean` prop；title 前置 8×8 圆点 + `@keyframes blink { 0%,100% { opacity: 0.3 } 50% { opacity: 1 } }` 1.2s 循环；Sidebar 把 `:is-streaming="activeStreamingSessions.has(conv.session_id)"` 下发即可。
- **新增流式 SSE 入口**（sendMessage / handleResume / handleRestream）必须按上述点对点实现；F5 恢复不在本约定范围——需要后端 `/chat/streaming_sessions` 接口 + 恢复 SSE 协议。
21. **静态文件 fallback（无 sid 才跨会话找 + Referer 推断 sid 优先）**：`APIRouter/static_file.py` `serve_cached_file` 精确路径命中失败时分流：
    - **带 sid 路径**（第一段 32 位 hex 旧版 `uuid.uuid4().hex` 或 12 位 hex 新版 `uuid.uuid4().hex[:12]`，dual regex 都接受）找不到 → **直接 404**（不跨会话，避免误把别人 session 产物显示在当前 session）
    - **无 sid 路径**找不到 → 双层 fallback：先从 `Referer` header 正则提取 sid 作为 **primary_sid**（**32 位写前面**——`re` 交替优先左侧分支，URL 同时含 32/12-char 子串时取更长的；带 `/[/?#]|$` 路径边界防 31/13 位凑巧 hex 误匹配），在 `cached/{primary_sid}/**` 下递归找；没命中再跨 `cached/*/` 所有 sid 找（按 `st_mtime` 最新返回）

**为什么只无 sid 才 fallback**：实际请求 URL（前端 markdown 图片、Electron 转发、Vite proxy）都带 sid，fallback 是少数兜底路径；带 sid 还 fallback 会把"我自己 session 缺文件"悄悄变成"别人 session 同名图"。**为什么用 Referer 推断 primary_sid**：浏览器 `<img>` 加载 markdown 图片（fallback 主要场景）**不能**加自定义 header（浏览器规范），EventSource 也不能，所以"前端主动加 `X-Session-Id` header"方案无效。Referer 浏览器自动带，URL 格式如 `http://host/{sid}` 或 `http://host/{sid}/foo` 都能用 hex 正则全局匹配第一个 sid；隐私模式 / `referrer-policy: no-referrer` 时 Referer 缺失，自动降级到跨 sid 兜底（按 mtime 最新）。新加静态文件路由必须沿用 sid-vs-nonsid 分流 + Referer 推断两层优先级。
22. **删除会话行内二次确认（小红叉状态机）**：去除 ConfirmDialog 弹窗，`ConversationItem.vue` 维护 `isConfirmingDelete` 状态机：
    - **第一次点 ×** → `isConfirmingDelete = true`，按钮加 `confirming` class（变红 `color: #ef4444` + `rgba(239,68,68,0.12)` 底 + `opacity: 1` 一直显，不再依赖 hover）
    - **第二次点红 ×** → **立刻** `isConfirmingDelete = false` 再 `$emit('delete')`（先重置是为了防止 document click 冒泡再触发 cancel）；App.vue 收到 `delete-conversation` 后直接 `fetch DELETE /chat/${sessionId}/clear`，不再弹 `ConfirmDialog`
    - **点别处 / Esc 取消**：`mounted` 绑 `document.addEventListener('click', this.cancelDeleteConfirm)` + `('keydown', this.onKeydown)`；`cancelDeleteConfirm` 用 `!this.$el.contains(e.target)` 防御（避免 button click 被二次处理），`onKeydown` 只在 `Escape` 且 confirming 态才重置；`beforeUnmount` 记得 `removeEventListener` 解绑
    - **App.vue 必保留逻辑**：`deleteConversation(sessionId)` 直接执行的版本**必须**保留 finally 块的三件套清理（`stopStreamTimer` + `_activeStreamingSessions.delete` + `_streamingMessages.delete` + `_streamingMeta.delete` + `new Set(...)` 触发响应式）+ 当前会话切换（关 SSE + `cleanupLoadingState()` + `createNewChat()`）；不要因为去掉弹窗就把 finally 一并删了
    - **emit 契约不变**：Sidebar 的 `@delete-conversation="deleteConversation"`、ConversationItem 的 `emits: ['delete']` 都不用动，只有 App.vue 的 `deleteConversation` 内部从"弹窗 + 确认"变成"直接执行"
23. **Electron 单窗口架构 + autoEnter 三态按钮**：早期双 BrowserWindow 关闭引导窗触发 GPU process 重启 + renderer 崩溃；v0.0.4 改单窗口架构：
    - **架构**：`main.js` 始终一个 BrowserWindow；主界面永远在 DOM 里（`appReady=false` 时加 `.app-disabled` 灰显禁用），`<BootstrapView>` 是浮窗叠加（fixed + z-index 1000 + backdrop-filter 模糊）。完全消除窗口创建/销毁竞态。
    - **状态机**：主进程模块级 `let servicesReady = false`；bootstrap 完成后调 `setServicesReady(true, { autoEnterFrontend })` 通过 `webContents.send('startup:services-ready-changed', { ready, autoEnterFrontend })` 推 object payload 给 renderer。
    - **初始 gate**：`App.vue` 新增 `_isInitializing: true` + `servicesReady: null` 兜底 IPC 还没回的窗口期（5-50ms）。warm start（`getServicesReady=true` → 直接进主界面）/ cold start（`false` → BootstrapView 浮窗）/ warm refresh（`webContents.reload()`，同 warm path）三条路径一律不闪 BootstrapView。
    - **三态按钮**：BootstrapView 主按钮 v-if 三态：`launching=true` → 「启动中...」disabled；`servicesReady=true && !autoEnterFrontend` → 「进入应用」enabled emit `enter-app`；其他 → 「启动应用」（`!allOk` 时 disabled）。
    - **避免双源真相**：`BootstrapView.servicesReady` 是 prop（App.vue 下传），不重复 invoke `getServicesReady`；`BootstrapView` 只通过 `@enter-app` 通知父级，所有 `appReady` 翻转都在 App.vue 一处。
    - **重启路径**：`restartBackend()` 完成后也调 `setServicesReady(true, { autoEnterFrontend: true })` —— 用户已在 app 里（被踢回 disabled），重启恢复直接交回交互权，不再弹「进入应用」。
    - **失败兜底**：bootstrap catch 块调 `setServicesReady(false)` 回到冷启动态，BootstrapView 重新挂载显示「启动应用」重试。

24. **DataAnalysis 数据库分析（只读 + 跨会话配置 + 自动中断）**：
    - **能力边界**：`skills/DataAnalysis/database/` 提供 MySQL / SQLite / PostgreSQL / MongoDB 4 个引擎只读分析，写操作（SQL `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE/MERGE/CALL/REPLACE` + Mongo `$out/$merge/$where/$function/$accumulator/mapReduce/eval`）一律拦截。
    - **跨会话配置存储**：DB 连接配置写入 `skills/DataAnalysis/database/.runtime/`（fcntl 文件锁 + 临时文件 + 原子替换）；LLM 只能看到 alias / engine / host / database 等非敏感信息，密码不进入 prompt / checkpoint / 日志。
    - **沙盒挂载**：DataAnalysis 目录 `:rw` 覆盖在 `/skills` 只读挂载之上（`ChatWorkflow/mcps/sandbox/pool.py` 的 `SandboxPool`），保证其他 skill 文件仍只读。
    - **SKILL.md 动态加载**：主 `SKILL.md` 不直接列数据库指引；agent 识别到「数据库/SQL/MySQL/Mongo」等关键词时 `cmd("cat /skills/DataAnalysis/database/SKILL.md")` 动态加载子文档，避免占用主上下文 token。
    - **agent 主动中断**：`need_db_credentials` 中断事件携带 `db_type` / 字段列表，用户在 UI 输入凭据后 resume；中断机制沿用现有 SSE `interrupt` 通道。
    - **`ChatDataAnalysisFormat` 包结构**：`format.py` 已拆分为 `format/` 包（`base` / `artifacts` / `manifest` / `database`），保留旧 `format.py` 导入兼容；数据库查询结果通过 `save_database_result` 落到 `data_analysis/gen_xxx/data/` 后走主流程。

25. **导出端点（产物 + 对话历史）**：`backend/ChatMe/APIRouter/data_export.py`：
    - **`/chat/{sid}/export/artifacts?format=zip|html`**：打包 `cached/{sid}/data_analysis/` 全目录。ZIP 保留 `gen_xxx/charts|data|reports|scripts/` 结构；HTML 单文件预览（marked.js + mermaid.js CDN，PNG/SVG 转 base64，CSV/JSON 转 HTML 表格）；单文件 ≤100MB，总和 ≤500MB；`_meta.json` / 隐藏文件跳过；macOS `/tmp` 解析用 `Path.relative_to(base)` 防 symlink 字符串不一致。
    - **`/chat/{sid}/export/turn/{checkpoint_id}`**：截至指定 checkpoint 的完整对话历史打包 ZIP：`openai.json`（标准 Chat Completions 格式）/ `chatme.json`（直接 dump `state.values` 全字段，用于软件内恢复，恢复接口后续实现）。
    - **前端入口**：`DataAnalysisTree.vue` 头部 ⬇ ZIP + 👁 HTML 预览按钮（`exporting` data 防连点）；`MessageItem.vue` AI 消息按钮排新增 ⬇ 「导出到本轮」（`canExportTurn`：仅 AI + 非流式 + 非 error + 有 `checkpointId`）。
    - **Electron 转发**：现有 `protocol.handle('file')` 已含 `pathname.startsWith('/chat/')`，无需修改。

26. **v0.1.1 新增约定**：
    - **`PermissionedToolNode` + LangGraph `interrupt()` 审批**：`cmd` / `code` 工具执行前走 LangGraph 官方 `interrupt()`（不要自己写 try/except 拦截 tool call，会被 LangGraph runtime 忽略）；`_awrap_tool_call` hook 是 `ToolNode` 的官方扩展点。决策存 Redis `permission:{sid}` hash 字段：`command` / `action` / `status` / `timestamp` / `tool_call_name` / `fingerprint`（code 才有）。`resume` 走 LangGraph 官方 `Command(resume=decision)` 通道。
    - **4 档决策**：`approve` / `this-time-only` / `deny` / `feedback:<text>`。`approve` 永久有效（按 command pattern 或 code fingerprint 缓存到 `permissions.approved_commands`）；`this-time-only` 一次性；`deny` 永久拒绝；`feedback` 让用户给反馈文本，agent 拿回继续生成。`code_fingerprint` = SHA1(`imports + calls + lang + sandbox` 四元组)，行号微调不影响 fingerprint。
    - **审批 UI 内嵌**：`handlePermissionRequest` 必须把审批按钮**内嵌**到对应 `toolCall` 行（详见 `feedback_inline_approval_ui.md`），不要做独立 modal 弹窗。`/permission/decide` 不带 `embed=True`（modal 才需要）；`/permission/resume` 走 SSE 流式输出，结构对齐 `message_stream`。
    - **多平台 prompt adapter**：`ChatWorkflow/platforms/` 把 `cmd` / `code` / `ctime` 工具的 shell 风格差异抽到 `darwin.py` / `linux.py` / `windows.py` + `base.py` 抽象；`registry.py` 启动时按 `platform.system()` 选。新加工具涉及跨平台 shell 行为差异，必须走 `platforms/` 适配器，不要在 prompt 里硬编码 `uname` 判断。
    - **`sub_agent` 工具 deprecated**：主 agent 现在直接调 `cmd` / `code` + 审批流；新代码不要引入 sub_agent 路径。
    - **session_id 兼容 32 + 12 位 hex**：`APIRouter/static_file.py` 的 `SESSION_ID_PATTERN` / `SESSION_ID_RE` 必须同时接受 32 位（旧 `uuid.uuid4().hex`）和 12 位（新 `uuid.uuid4().hex[:12]`）hex。新加 session_id 解析代码沿用同一 dual regex。

27. **v0.1.2 新增约定**：
    - **跨 SSE 临时 metrics 累加器**：每 round 走独立 `round_metrics:{sid}` Redis hash（`started_at_wall` + `token_usage`），**不**写正式 `threads:{sid}:checkpoints` 列表。`message_stream` / `invoke_interrupted_stream` 全新 init；`resume_permission_stream` 走 `_load_or_recover_round_metrics` 优先读临时键，缺失时从 LangGraph state 派生一次。
    - **`on_chat_model_end` 实时累加 + 持久化**：每个节点（`input_parse_node` / `agent_node` / `should_end_node` / `final_node`）的 LLM 调用结束事件触发 `_accumulate_workflow_tokens` 累加到本地 `token_usage`，返回值 `True` 时立刻 `_persist_round_token_usage` 刷到临时键，保证下一个 SSE stream 续接能拿到最新累计。**不能**只在 stream 边界写一次（permission 等待 / 异常中断会丢）。
    - **stream 边界 `finally` 兜底**：`message_stream` / `resume_permission_stream` / `invoke_interrupted_stream` 三个 `try/except` 的 `return` 都套 `finally`，末尾 `_persist_round_token_usage`，异常路径不丢累计。
    - **终态落盘与清理**：`_save_round_checkpoint` 写完 `cp_meta` 后必须 `_clear_round_metrics(session_id)` 清掉临时键。终态 `elapsed_ms = int((time.time() - round_metrics:{sid}.started_at_wall) * 1000)`，`token_usage` 来自临时键最后一次累计值。
    - **不污染 CID 列表**：**禁止**把审批等待 / 中断续接的中间 metrics 写进 `threads:{sid}:checkpoints`（会让 `get_conversation` 按下标映射错位，把审批前部分值当成整轮 metrics 显示）。需要中途恢复就只写 `round_metrics:{sid}`，终态再走 `_save_round_checkpoint`。
    - **删除废弃项**：`pending_round_metrics` conversation 字段、`_save_pending_permission_checkpoint` 方法、imp_ipt.additional_kwargs 的 `round_started_at_mono` / `round_started_at_wall` / `token_usage` 字段、前端 `applyPendingRoundMetrics` / `_pendingMetricsTickers` / `msg.startTs` 死代码全部移除。时间锚点完全由 `round_metrics:{sid}.started_at_wall` 承担，imp_ipt 只保留 `additional_kwargs.imp_ipt=True` 作为 draft 切分标志。
    - **删除会话清理**：`delete_conversation` 必须 `DEL round_metrics:{sid}`，避免脏临时键遗留。
    - **前端 metrics 单一权威来源**：流式中由后端 `init` / 实时 SSE 事件的 `elapsed_ms` / `token_usage` 同步到 message（`writeStreamMetrics`），本地 timer 持续 250ms tick；终态走 `cp_meta`；F5 / 刷新走 `get_conversation` 返回的 `cp_meta` 回填。前端不再依赖任何"中途持久化"的字段（`pending_round_metrics` / `applyPendingRoundMetrics` / `startTs` 都已删）。
28. **v0.1.3 新增约定 — Pre-check 拦截 SSE 兜底**：
    - **问题**：`PermissionedToolNode._permission_wrap` 在 pre-check（`dangerous` / `whitelist not_allowed`）拦截时直接 `return ToolMessage`，不调 `execute()` —— LangGraph 不发 `on_tool_start` / `on_tool_end`，前端流式响应看不到拦截结果，必须 F5 刷新。
    - **兜底**：`on_chain_end` 节点为 `tool_execution_node` 时，按 `tool_call_id` 配对 `data.input.messages.AIMessage.tool_calls` 与 `data.output.messages.ToolMessage`，补 `tool_call_name` + `tool_call_result` SSE。
    - **去重**：per-stream `emitted_tool_call_ids: set`；正常路径 `on_tool_end` emit 后写入 set，`on_chain_end` 兜底查 set 跳过避免双发。
    - **Helper**：`ChatService._build_intercepted_tool_call_events(chunk, emitted_ids, elapsed_ms, token_usage)` 统一封装；3 个 SSE 流（`message_stream` / `resume_permission_stream` / `invoke_interrupted_stream`）都加这套。**orphan 防御**：`tool_calls_by_id.get(tc_id)` 查不到时跳过，避免 emit 缺 args 的脏事件。
    - **测试**：`tests/mcps/test_intercepted_tool_call_events.py` 7 个 helper 单测 + 2 个端到端集成（混合正常 / 拦截验证不双发）。
29. **v0.1.4 新增约定**：
    - **`mcps/` 三包重构**：`mcps/permissions/core.py`（原 `permissions.py`）/ `mcps/sandbox/pool.py`（原 `CodeSandboxPool.py`）/ `mcps/tools/`（`code_fingerprint.py` + `deprecated.py` + `platforms/`）。**各包 `__init__.py` 只写说明不 re-export**（除 `tools/platforms/__init__.py` 导出 adapter），所以 import 必须写到具体模块：`from ...mcps.permissions.core import PermissionedToolNode`，不能 `from ...mcps.permissions import`。
    - **定时任务 = Skill + REST，不是 MCP 工具**：`skills/Scheduler/` 4 个顶层函数走 HTTP 调 `/admin/scheduled-tasks/*`，agent 用 `code(..., local=True)` 调用（沙盒网络不可靠 + 缺 `apscheduler` / `redis` 包，`local=False` 会卡死或 ModuleNotFoundError）。触发时 handler 直接调 `chat_service.message_stream()` 跑完整一轮，**不走消息队列、不推 SSE**。Redis key：`scheduled:tasks` / `scheduled:meta:{tid}` / `scheduled:history:{tid}` / `scheduled:lock:{tid}`。
    - **lifespan 嵌套顺序不可换**：`chat_service_lifespan → scheduler_lifespan → cleanup_lifespan`（scheduler handler 依赖 `chat_service.message_stream`）。
    - **`uvicorn.run(app, ...)` 传对象不传字符串**：`"main:app"` 会让 uvicorn 重新 import 一次 `main.py`，模块体二次执行（banner 打两次、LLM 自检跑两遍、VL / OSS 重复检测）。
    - **消息排队（前端 drain，后端只存）**：`/chat/{sid}/queue` 只做 Redis `queue:{sid}` FIFO 持久化（≤20 条 × 4000 字符），**不主动 drain**。前端 `sendMessage` 守卫 `currentSessionId ∈ _activeStreamingSessions` 则入队 return；两个 watcher 触发 drain（`_activeStreamingSessions` 变化算「刚结束」的 sid / `currentSessionId` 变化查 `_queueDrainDeferred`）；用户不在该会话时推迟到 `_queueDrainDeferred`，切回再发。`cleanupLoadingState` 同步清 `_pendingQueue` / `_queueDrainDeferred`。**未新增 SSE 事件类型**，纯客户端逻辑 + REST。
    - **发新消息必须清旧审批 singleton**：`sendMessage` 里把旧 `_pendingApproval` 置 false 并塞合成 result；`onToolDecision` 用 `submittingToolDecision || permissionResumeInFlight` 早返做 JS 层去重。
    - **回溯走 `CheckpointJanitor.retarget_to()`**：直接覆写 LangGraph latest 指针 + 删除其余 checkpoint / write，**不再产 artifact checkpoint**；Memory 回溯时保持原 cid 不重命名（支持重复回溯）。回溯前先 `_wait_previous_memory_update`。
    - **未知工具名不崩**：LLM 调未注册工具时走 LangGraph `ToolNode._validate_tool_call` 返回错误 `ToolMessage`（含未知工具名 + 可用工具列表）让模型重试；已知工具仍过权限 gate，`GraphInterrupt` / `GraphBubbleUp` 不被吞。
    - **MAIN_FLOW 只讲「怎么想」**：`PROMPT_MAIN_FLOW` 承载决策流 + 8 条 Good Chain Examples；**具体工具调用模式下沉到 `platforms/base.py` 的 `<tool>_tool_prompt_block`**，由 `all_tool_prompt_blocks()` 拼接。新增工具的用法说明写 prompt block，不要塞回 MAIN_FLOW。
    - **MCP session 长生命周期**：`session.py` 的 stdio 子进程 + `ClientSession` 常驻复用，工具调用不再每次重开连接。

30. **v0.1.5 新增约定**：
    - **Memory skill 跨会话持久化**：`backend/skills/Memory/`（mount=ro）提供 `remember(key, value, thread_id, category, scope)` / `recall(thread_id, category, scope)`（4 变体维度：`facts`/`preference` × `thread`/`global`）。**写入必须 `code(..., local=True)`**（沙盒挂 ro）；`recall` / `cmd("cat /memory/...")` 沙盒也支持。`context_assembly_node` 每轮开头自动合并注入，所以**只管写、读不用主动调**（同名 key 替换旧值）。**写入原则**：去重优先（先 `cat` 看是否已存在）；key 短而稳（主谓宾短语）；value 自包含；不写中间过程；global 慎用。文件路径：`.chatme/memory/{tid|global}/{category}.md`，沙盒映射 `/memory/{tid|global}/{category}.md`。
    - **SkillForge 动态创建 skill**：`backend/skills/SkillForge/`（mount=rw）提供 `create_skill()` / `list_skills()` / `read_skill()`。**registry mtime 自动重扫，无需重启后端**：macOS APFS 修改现有文件**不**更新父目录 mtime，所以 `_maybe_rescan()` 按每个 SKILL.md 自己 `stat()` 检测变更（O(n)）。**必须 `code(..., local=True)`**（写入主进程文件系统）。**保留名禁用**：`SkillForge` / `_xxx` 前缀不能做 skill 名（防覆盖核心逻辑）。
    - **`/skills/<name>/SKILL.md` frontmatter 规范**：YAML 解析支持 `name`（必填）/ `description`（必填，find_skill 检索字段）/ `aliases`（额外 keyword）/ `mount`（`ro`/`rw`，默认 ro；rw 段路径单独 `-v :rw` 覆盖在 `/skills:ro` 聚合挂载之上）/ `module`（默认 `skills.<相对路径>`）/ `lazy`（true 时不进 find_skill 索引，常驻还是会被注入）。**`build_mount_args()` 加 `@functools.lru_cache(maxsize=1)`**；`reset_skill_registry()` 时必须 `cache_clear()`。
    - **Scheduler 模块重组为 4 层**：`backend/skills/Scheduler/` 拆成 `models.py`（`ScheduledTask` dataclass + Redis key 常量）/ `handlers.py`（`handle_send_message(task_id)` 异步执行入口）/ `registry.py`（CRUD：add/list/get/update/delete/run_now + 同步 APScheduler）/ `core.py`（`get_scheduler()` + `get_redis()` + `scheduler_lifespan()`）。**`core.py` 不暴露内部单例对象**——`get_scheduler()` 单值快照可能错过 lifespan 启动后的重新赋值；新增代码走 `get_scheduler()` 函数。handlers 走 lazy import 避免循环。
    - **CheckpointJanitor 拆分为两层**：`ChatWorkflow/CheckpointJanitor.py`（业务类，注入 `chat_service` 供 hook）+ `APIRouter/checkpoint_janitor.py`（HTTP 层，唯一路由 `POST /admin/checkpoints/prune`，pydantic `PruneRequest` 含 `session_id` / `dry_run` / `min_scanned`）。保护规则：保留 `checkpoint_latest:{tid}:{ns}` + `threads:{tid}:checkpoints` HASH 所有 cid；删其余 `checkpoint:{tid}:*` / `checkpoint_write:{tid}:*` / `write_keys_zset:{tid}:*`。**前端 Settings「立即清理」按钮**走 POST `/admin/checkpoints/prune?dry_run=false`。**main.py 多注册一个 router**（`checkpoint_janitor_router`）。
    - **SettingsDialog 4 tab 改造**：
      - **VL `local` 开关 + fallback**：`vl.local=False` 时 `_resolve_vl_fallback()` 无条件覆盖 `model_name`/`api_key`/`base_url`（无视 vl 段自己填的），fallback 到主用 LLM 三元组。Settings 显示 checkbox + 三层说明（勾选 / 不勾选 fallback / 改动需重启）。
      - **`/admin/config` 热加载（segment 级）**：`permissions` / `skills` 段立即生效（`ChatMeConfig._load()` 带 mtime check + `save_config()` 后 `force_reload()` 清 mtime cache + `get_permissions().force_reload()` 同步单例）；`llm_providers` 段需重启（ChatOpenAI / Redis client / VL weights 是启动期长生命周期对象；`restart_required = "llm_providers" in saved_segments` 按段判断，**不再** 一刀切 `True`）。前端 `buildPayload()` 维护 `originalConfig` 快照 + `_deepDiff()` + `_stripEmptyObjects()`，只发修改段（防止 Permissions 改一字段把 llm_providers 全带上）。原子写 `tmp + os.replace`，tmp 文件名带 PID。
      - **`/admin/restart` + `/admin/health` + `/admin/config` REST**：`POST /admin/restart` 写 marker `.restart_pending` + 0.3s sleep + `os.execv` 替换进程；`GET /admin/health` 前端 `pollHealth(120s)` 轮询等待；恢复后 `window.location.reload()`。
    - **Sidebar / ConversationItem 内嵌定时任务**：v0.1.4 的 `ScheduledTasksPanel` 已**删除**；改为 `ConversationItem` 底部内嵌 ⏰ 触发按钮（仅 `tasks.length > 0` 渲染）+ `<transition name="scheduled-expand">` 展开任务列表（`max-height: 0 → 110px`，超过 3 条滚动）。展开状态按 `lingxi.scheduledTasksExpanded` localStorage 持久化。App.vue data 加 `scheduledTasksMap: Map<session_id, ScheduledTask[]>` + `_scheduledTasksRefreshing: bool`。Sidebar 转发 `scheduled-task-toggle/run/delete` 给 App.vue。
    - **三色侧栏状态点（ConversationItem 顶部圆点）**：streaming 蓝闪（`@keyframes blink 1.2s`）/ approval 黄脉冲（`pulse-yellow 2s`）/ errored 红常显（`#ef4444`）/ completed 绿常显（`#22c55e`，仅 clean done 后等用户点进去看的窗口期）。**`dotTitle` tooltip 优先级**：`streaming > approval > errored > completed`。**App.vue 四 Set 独立维护**：`_activeStreamingSessions` / `_approvalPendingSessions` / `_completedSessions` / `_errorSessions`，**不是** union；`_sessionHadError`（保护态）与 `_errorSessions`（视觉驱动）并行而非耦合。
    - **`ScheduledTaskItem` 行内小红叉二次确认**：参考偏好 21 模式：第一次点 🗑 → `confirmingDelete = true`（按钮变红 `rgba(239,68,68,0.12)` 底常显）；第二次点红 🗑 → `confirmingDelete = false` 再 emit `delete`（先重置防 document click 冒泡）。`mounted` 绑 `document.click` + `keydown(Escape)` 取消，`beforeUnmount` 解绑。
    - **`ChatMeConfig._load()` mtime 失效 + `force_reload()`**：每次 `get()` 先 `_load()`：磁盘 `current_mtime == cached_mtime` → 直接 return（最常见路径零开销）；变了 → 重读 + 刷新 `_config`；不存在文件时按需生成默认 / 保留旧 `_config`（外部误删可恢复，**不破坏运行**）；首加载失败 → 兜底生成默认。**`force_reload()`** 把 `_loaded=False` + `_config_file_mtime=None`。**测试 fixture 路径**：`cfg._config + cfg._loaded=True` 注入时 `_config_file_mtime=None`（从未读过磁盘），`_load()` 直接 return。
    - **PRNG skill 重构成包 + `image_parser` regex 更稳健**：`backend/skills/Exa.py` / `ImageParser.py` / `Tavily.py` 单文件 → `Exa/{__init__.py,SKILL.md}` / `ImageParser/{__init__.py,SKILL.md}` / `Tavily/{__init__.py,SKILL.md}` 包结构。**保留旧 `Exa.py` / `Tavily.py` / `ImageParser.py` 兼容旧 `import skills.Exa` 路径**，新代码走 `from skills.Exa import exa_search`。
31. **v0.1.6 新增约定**：
    - **matplotlib 中文字体随 skill 自动 mount**：把 `NotoSansSC-Regular.otf`（或其它商用免费字体）放到 `backend/skills/DataAnalysis/fonts/`，随 skill 进 git、自动 mount 到容器内 `/skills/DataAnalysis/fonts/`。**`get_fonts_setup_header()` 同时扫描 4 个路径**（按顺序、去重、目录不存在 no-op）：① `/skills/DataAnalysis/fonts` ② `<cwd>/skills/DataAnalysis/fonts` ③ `/cached/.fonts`（legacy 沙盒挂载点）④ `<cwd>/cached/.fonts`（legacy 本地 venv）。**优先 skill 路径**——字体作为 skill 资源走标准 mount 协议，无需 gitignore 反向规则（`cached/` 整体被忽略时 `!cached/.fonts/` 无法重新包含子文件）。**`legacy cached/.fonts/` 保留兼容老部署**：定时清理脚本 `timed_clean.py` 的 `PRESERVED_TOP_DIRS={"cached/.fonts"}` 不动，不删老路径下文件。新加 matplotlib 字体支持沿用「skill 资源」模式，不要再放 `cached/` 下。
32. **v0.1.7 新增约定**：
    - **文件树行内删除 + 软删除 `.trash/` 兜底**：
      - **路径**：`backend/.trash/{sid}/{YYYYMMDD_HHMMSS}_{rel_path_underscored}`。**保留 sid 标志**（`.trash/{sid}/` 二级目录隔离会话）+ 时间戳前缀避免同名碰撞 + 极小概率同秒同 path 再追加 sha1[:6] 后缀兜底。
      - **API**：`DELETE /chat/{session_id}/file?file_path=<rel_to_cached_sid>`。校验：拒绝绝对路径 / `..` 段 / 越界 `relative_to(session_root)`。**文件 / 目录都支持**（v0.1.7 起去掉目录拒绝）：`shutil.move` 对目录自动 rmtree 整树移到 `.trash/{sid}/`，树结构保留便于排查。
      - **手工清空**：`DELETE /chat/{session_id}/trash` 物理清理当前会话的 `.trash/{sid}/`（不阻塞其他会话），前端走 `DataAnalysisTree` 面板 🗑 按钮 + `ConfirmDialog` 二次确认弹窗。
      - **定时清空**：`APIRouter/timed_clean.py` 的 `clean_trash()` 函数 + 每天 11:30（Asia/Shanghai）APScheduler job `daily_trash_cleanup`，与 23:30 的 `daily_cleanup` 错开避免 IO 叠加。
      - **前端入口**：`DataTreeNode.vue` 文件 / 目录行都显示 × 红叉行内二次确认（沿用偏好 22 模式：第一次点 × 进 `confirmingDelete=true`、第二次点红 × 才真删；document.click + Esc 解绑；`beforeDestroy` 解绑）。**目录删除前要把 `path` 字段补上**：`DataAnalysisTree.buildTree` 之前只有文件 leaf 带 path，目录节点也得存 `cached/{sid}/dir/sub/` 完整路径，否则 `onFileDelete` 取不到 `node.path`。点击成功 → 调 DELETE → 后端 200 → 调 `check()` 刷新树。`node.path` = 完整相对路径 `"cached/{sid}/xxx"`，前端 `_extractRelativePath` 剥 `rootPath` 前缀得 `xxx` 给后端。
      - **为什么是软删除不是物理删除**：用户误删能找回（直到 11:30 才物理清），符合偏好 22 的"二次确认是兜底"——确认只是延迟，不是不可逆。
    - **/help 重构成「能做什么 + 使用技巧」两段**：
      - **「灵析能做什么」**：精简 5-7 条 bullet 描述核心能力（多轮对话 / 工具调用 / 沙盒 / 数据分析 / 记忆+定时 / 数据库 / 导出）。
      - **「使用技巧」**：h3 一级标题 + h4 子标题（键盘 / 审批 / 文件树 / 引用&撤回 / 产物导出）。**移除**：对话与流式（实现级描述）+ 会话管理（四色状态点 / ⏰ / × 二次确认等 UI 视觉元素，用户一眼可见不必复述）。
      - **新增内容**：文件树 h4 子段（📁 入口 / × 红叉 / 软删除到 `.trash/{sid}/` / 🗑 手工清空）。
      - **保留**：键盘快捷键（精简到 5 条）/ 命令 + 技能 auto-generated（按 `commands` prop 的 `kind` 字段分组）。
      - **styles**：新增 `.help-section h4`（比 h3 小一档，与正文视觉分层）+ `:first-of-type { margin-top: 0 }` 收头。

33. **标题自动派生（后端剥离 `<quote>` + `/[xxx]` + 截断 12 字符）**：
    - **目的**：用户消息里常含 `<quote>...</quote>` 引用块（从历史消息拖入）和 `/[skill-name]` slash pill（Codex 风格输入面板），这些不属于本轮标题意图。旧逻辑前端直接 substring(0, 12)，导致"<quote>长引用噪音</quote>真标题"被截到噪声段。
    - **`ChatService/core.py` helpers**（模块级）：
      - `_TITLE_MAX_LEN = 12`
      - `_QUOTE_BLOCK_RE = re.compile(r"<quote>.*?</quote>", re.DOTALL)` — DOTALL 让 `.` 跨行匹配
      - `_SLASH_PILL_RE = re.compile(r"/\[[\w-]+]")` — pill 名只允许 word/dash，与前端 regex 一致
      - `_WHITESPACE_RE = re.compile(r"\s+")` — collapse 空白
      - `_clean_message_for_title(content)` → str：剥 quote + pill + 归一空白
      - `_truncate_title(text, max_len=12)` → str：超长末尾加 `...`
      - `_derive_title_from_latest_human(messages)` → str：倒序找 HumanMessage（multimodal 取首个 `text` 段），调 clean + truncate；找不到或全是 quote/pill → 返回 `""`
    - **`update_conversation_title(session_id, new_title: Optional[str] = None) -> Optional[str]`**：
      - `new_title` 非空 → 直接存（手动改名场景）
      - `new_title` 为空 / None → 调 `_derive_title_from_latest_human(state.values["messages"])` 自动派生
      - 派生空（无 HumanMessage / 全 quote/pill）→ 返回 `None` 让上层 fallback
      - **返回类型从 `bool` 改成 `Optional[str]`**：实际写入的标题，方便 API 透传给前端同步侧栏
    - **API 端点**：`PUT /chat/{session_id}/title` 的 `title` 参数从 `str` 改成 `Optional[str] = Body(None)`；响应 `new_title` 是后端实际写入的版本（前端不需要再算一遍）。
    - **前端 `App.vue`**：`updateTitleOnly` / `updateTitleAndRefresh` 改为 `body: JSON.stringify({})` 触发后端派生；用响应 `new_title` 更新侧栏（剥了 quote/pill 的干净版本），仅在请求失败时 fallback 到客户端 substring。
    - **测试**：`ChatMe/test/test_title_derive.py` 30 个 case 覆盖 clean / truncate / derive（含 multimodal、quote-only、pill-only、long-truncate、empty 等边界）。
33. **v0.1.8 新增约定 —— 文件树 Finder 化大优化**：
    - **长按框选状态机**（`Sidebar._startBoxSelect` / `_boxPressTimer` / `_boxPressActivated`）：`mousedown` 后等 **250ms** 或 **移动 ≥8px** 才进 box-select，避免「点空白清选区 vs 长按拖框选」误触；`mouseup` 矩宽 `<4px` 且非 additive → 清选区。
    - **HTML5 拖拽移动**：节点 `:draggable="!renaming"` + `dragstart.stop`；多选整组拖用 `setData('application/x-lingxi-paths', JSON.stringify([...selectedPaths]))` + `effectAllowed='copyMove'`（Alt/Option 切 copy/move）+ 自定义 ghost 拖拽图像；drop 调 `POST /chat/{sid}/files/move?auto_rename=true`；drop target 目录行高亮（蓝色虚线 outline + 浅蓝底）。
    - **焦点目录 `focusDir`（Cmd/Ctrl+V 目标）**：点目录行 → `focusDir = 该目录相对路径`；点文件行 → `focusDir = 父目录`（Finder 习惯 —— 焦点是用户所在目录）；Shift 范围选 / 多选切换 / 框选 / 拖拽都不动 focus；完成任何文件操作后回根。视觉 `.dtn-dir.focus-target` —— 蓝色实心左边框 + 浅蓝底。
    - **copy / cut 视觉重做（蓝 → 琥珀）**：copy 改成 amber 500 浅底 + ⎘ 角标（之前蓝色虚线左边框与 focus 冲突）；focus 蓝色实心左边框。冷暖对比 + 角标 + 边框三层信号区分「源 / 目的」；focus + copy 共存时背景偏 amber 但保留蓝色左竖线。
    - **空状态 + 树底 `+` 操作行**：`.empty-state` 重做（📂 图标 + 标题 + 提示 + [📁 新建文件夹] [📄 新建文件]）；树底 `.tree-new-actions` 始终挂 `+文件夹 / +文件` 两条快捷按钮 + 快捷键 `Cmd+Shift+N` / `Cmd+Shift+Alt+N`；按钮 `@mousedown.stop` 防 box-select 抢焦点。**OS 系统拖拽 overlay** —— 从 Finder/Explorer 拖系统文件时显示「⬇ 释放以上传到当前会话」全屏浮层。
    - **拖拽事件穿透重构**（`MessageInput.handleWindowDrop` + `_isDragOverFilesTree(e)`）：原 `drag-overlay` 拦截所有 drop 导致 Sidebar drop 失效，改为 overlay 加 `pointer-events: none` + window-level `drop` 监听 + 检测 target 是否在 `.files-tree` 内（在则让 Sidebar 处理）。`dragend` / `dragleave(relatedTarget=null)` 兜底重置 isDragging。
    - **后端文件操作体验优化**：
      - **`_find_unique_name` 计数器剥除**（regex `^(.*?)\((\d+)\)$`）：`foo(1).py` 复制 → `foo(2).py`，不再 `foo(1)(1).py` 无限累加；`(\d+)` 限定数字，`(bar)` / `(v1-beta)` 保留。
      - **无空格紧凑命名**：`foo(1).txt`（按用户偏好紧凑风格）。
      - **`move_file` / `batch_move_files` 自粘贴兜底**：`src.parent == dst_dir` 直接 no-op（防御兜底，避免 auto_rename 触发无限累加）。
      - **创建同名静默追加**：`create_folder` / `create_file` 同名直接调 `_find_unique_name` 自动改名落地（Finder 习惯，无 409 冲突提示）。
      - **空 session 懒加载**：`body.parent == ""` 时先 `parent.mkdir(parents=True, exist_ok=True)`，全新 session 第一个新建按钮不再 400。
    - **Skill 描述前端覆盖**（`skillDescriptionOverrides`）：App.vue + MessageInput.vue 维护 `{ Memory, ImageParser, SkillForge }` 三条更准确描述，缺省 fallback 后端 `/chat/skills` 的 description。HelpDialog 文件树 h4 段同步展示 + 4 条 bullet（焦点 / 复制 vs 剪切 / 框选 / 拖拽），通过 `_isMac` / `_modKey` / `_fileManager` computed 跨平台切换修饰键文案。
34. **v0.2.0 新增约定 —— 图工作流大重构 + done 工具 + ReAct 压缩健壮性**：
    - **新默认图 `_create_graph_improved` 替换 `_create_graph_core2`**：`init_graph()`（`ChatWorkflow/core.py` line 254）从 `_create_graph_core2()` 切换到 `_create_graph_improved()`；老 `_create_graph_core2` 完整保留（line 891-1354 一字不动）作为回滚基线，新图与老图用 `init_llms` 内 `self.tools` vs `self.tools_with_done` 区分工具集（`include_done` 参数）。**动机**：老图靠 prompt 强制 LLM 输出 `Done` 单词 + `should_end_node` LLM 决策节点判定结束，决策不收敛（LLM 写完 `Done` 又补内容 / should_end_node 误判 retry 触发循环）。新图改成「AIMessage 含 tool_calls → tool_execution_node；不含 → 重试或 final_node」纯结构化路由 + `done` 工具作为显式收尾信号。
    - **MCP `done` 工具**（`mcps/server.py` line 246+）：无参函数，调用即返回固定字符串 `"Task marked as done. Graph will route to final_node for user-facing reply."`；文档字符串强调「思维链完成时调」，替代老图 `should_end_node` 决策。**只在 `_create_graph_improved` 工具集里**暴露 —— 老 `_create_graph_core2` 走 `get_mcp_tools(include_done=False)` 过滤掉（避免老图 prompt 里没有 `done` 描述时 LLM 误调）。`sub_agent`（deprecated）始终包含（无害）。
    - **`get_mcp_tools(include_done=False)` 双模式**（`mcps/session.py` line 84+）：默认 False 走老图工具集；True 追加 `done` 工具。**两个工具集 cache 共享同一份底层**（`_mcp_tools_cache`），只是过滤一层，O(n) 重建开销忽略不计。
    - **`route_agent_output` 决策函数**（`ChatWorkflow/core.py` `_create_graph_improved` 内）：纯结构化路由 —— 倒序找最后一条 AIMessage（含 tool_calls → tool_execution_node；无 tool_calls 且 `agent_no_tool_call_retries >= RETRY_TIMES=3` → final_node 放弃；retry < 3 → context_assembly_node 注入英文 SysMsg 提示必须调工具）。**新图不再用 LLM 做决策**，避开 should_end_node 的不收敛问题。
    - **`route_after_context_assembly` 双源真相**：done cycle 已被 `RemoveMessage` 把 AIMessage(done) 从 messages 里删了，路由函数无法仅靠 messages 判定；改看 `state["done_cycle_detected"]` flag（`context_assembly_node` 与 `is_done_cycle` 同源设置）。flag 在每轮 context_assembly_node 开头显式重置为 False，避免上一轮 done 残留误判。
    - **agent no-tool-call retry 机制**（`agent_node` 内）：AIMessage 无 tool_calls → `retry_times += 1`；`retry_times < 3` 注入英文 SysMsg「You must invoke at least one tool ... or the `done` tool when reasoning is complete」；成功调出 tool_calls → `retry_times = 0`（一次成功打断失败链，给完整重试预算）；达到 3 次 → route_agent_output 强制 final_node。state 字段 `agent_no_tool_call_retries: int` 跨轮清零（`input_parse_node` 重置为 0，避免上一轮残留 retry 撞上限）。
    - **`RemoveMessage` 清理 done cycle**（`context_assembly_node` 内 `is_done_cycle` 分支）：单 done（tool_calls 长度 1 且唯一是 done）→ 整轮清理（`[RemoveMessage(id=...) for m in cycle_msg if m.id]`）；并发调度（done 跟其他 tool 并存同 AIMessage）→ 只删匹配 done `tool_call_id` 的 ToolMessage，AIMessage（含其他 tool_calls）和其他 TM 全部保留（F5 刷新后还能看到「搜了 XXX 拿到 YYY」的上下文）。前端 `mergeToolCallStart` 已过滤 done 显示，所以保留 AIMessage 不会污染 UI。
    - **`compression_handled_this_round` 防重复压缩**（`context_assembly_node` 内）：老代码同一轮 context_assembly_node 调用里，迭代 2+ 会重复跑 `_build_compaction_draft` / `_find_complete_tool_loops` / 重复触发后台 LLM。改用 `bool` 标记，本轮第一次成功后置 True，iteration 2+ 跳过整个 ReAct 压缩段。**配合 done cycle 跳过压缩**：`is_done_cycle=True` 时整段 ReAct 压缩不跑（避免无用压缩产物灌给 final_node + 后台 asyncio 任务泄漏到 `_background_compaction_results`）。
    - **`pending_compaction_replace_at` 改用完整 loop 数**：阶段 2 完成时设 `= len(_find_complete_tool_loops(context)) + REACT_KEEP_LOOPS`，**不**用 `tool_call_times + REACT_COMPACT_REPLACE_AFTER`。**动机**：agent 并行调 1-3 个工具会让 `tool_call_times` 一次 +1~3，导致「等 2 轮」+2 实际是「等 0~1 轮」不稳定；loop 数版本无论并行多少次都稳定等价于「再走 N 个完整 AIMessage+ToolMessages pair 才替换」。**阶段 4 触发条件改为 `len(current_complete_loops) >= pending_replace_at`**，不再 `tool_call_times >= pending_replace_at`。state 字段注释同步更新（`config/models.py` line 60-65 强调「完整 loop 数阈值，不基于 tool_call_times」）。
    - **`REACT_COMPACT_DETECTION_MIN_ROUNDS` 4 → 5**：减少过早触发压缩的概率；DETECTION_MIN_ROUNDS=4 时某些对话第 4 轮就触发，summary 质量不稳；5 轮后最近 5 轮原文对 LLM 上下文足够。
    - **`REACT_COMPACT_REPLACE_AFTER` 2 字段移除**：被 `REACT_KEEP_LOOPS=2` 复用语义（替换阈值 = 当前 loop 数 + KEEP_LOOPS），不再单独存常量。**保留 `REACT_KEEP_LOOPS`**（2 轮原文保留是设计意图，分离它会让 caller 困惑）。
    - **前端 `done` 工具调用过滤**（`App.vue` 两处）：① `mergeToolCallStart`（line 1911+）开头 `if (data.content?.name === 'done') return message` —— 后端 `RemoveMessage` 后流式响应过程中不会再闪一下再消失；② `_processBackendToolCalls`（line 5066+）开头 `if (tc.name === 'done') continue` —— 老 checkpoint / 跨版本迁移场景的安全网（兜底防 `done` 工具调出现在历史 checkpoint 恢复出的 messages 里）。
    - **测试清理**（`.gitignore` line 50+）：`tests/` / `**/tests/` 加入 ignore 列表，18 个 `backend/tests/` 测试文件 staged for deletion；今后单测跟随 .venv 落在本地，不入 git。**`pyproject.toml` 仍保留 `[dependency-groups] dev = ["pytest>=9.1.1"]`** 让本地能跑。
    - **许可证 + 商标**：项目以 **MIT License** 发布（`LICENSE` / `NOTICE` / `THIRD_PARTY_LICENSES.md` 三件套）；`pyproject.toml` 加 `license = "MIT"` / `license-files` / `authors = [{name = "灵析"}]`；`frontend/package.json` 加 `"license": "MIT"` + `author` 顶层字段。「灵析™」与「Lingxi™」为产品名商标（README「商标」段），MIT 不授予商标使用权，使用须经项目维护者书面授权。
    - **新图 / 老图共存保留路径**：v0.2.0 起 `_create_graph_core2`（line 891-1354）**完整保留**作为回滚基线；切换通过 `init_graph` 一行注释切换（`# self.graph = await self._create_graph_core2()` 注释 + 上面行 active）。回滚时把注释行启用 + 把 `_create_graph_improved` 行注释即可，无须 git revert。新图 prompt / 状态字段 / 工具集与老图严格隔离，不互相污染。

### 代码 / 提交风格

- 提交信息遵循仓库现有风格：`v0.X.Y <说明>`（参考 `git log`）
- 不要引入为假设需求而设计的抽象 / 配置项 / fallback
- 系统边界（用户输入、外部 API）才做校验；内部代码信任框架保证
- 修改代码前先读相关文件，不读不写

### 工作流修改注意点

1. 5 个 LLM（`llm_core` / `agent_llm` / `summary_llm` / `react_compact_llm` / `llm_imp_ipt`）全部用 `MessagesPlaceholder("messages")`，不要回到字符串 `{messages}` 占位（会导致 SystemMessage 被 `str()`）
2. 后端 `_filter_thinking_content` 过滤 `<thinking>` 等思考标签，前端再二次过滤
3. VL 模型只处理图片（`file_process_node` 已跳过非图片文件）
4. `execute_code` 工具默认 `local=False`（v0.1.3 反向命名：MCP schema 里看到的是 `local` 参数，False = 沙盒）
5. **`imp_ipt` 是 draft 切分锚点**：`input_parse_node` 输出的 `imp_ipt` 唯一身份是 `additional_kwargs.imp_ipt == True`；ReAct 压缩 / final_node 注入 / 后续扩展都靠这个标志定位本轮意图，不要换成"最后一条 HumanMessage"这种隐式契约
6. **final_node 不再走 `MessagesPlaceholder`**：imp_ipt 走 `_final_system_template.format(imp_ipt=...)` 注入到 system prompt 独占最高注意力位；context 中要先把 `imp_ipt` pop 出去再喂给 `llm_core`，避免重复注入
7. **ReAct 压缩失败不要 raise**：`_try_compact_react` 一律返回 `None`，由 `context_assembly_node` 保持原 context 不变；不要让压缩异常把整轮回复炸掉
   7.1. **`_filter_thinking_content` 是 MiniMax-M3 输出的兜底主力**：filter 必须能吃掉 MiniMax-M3 输出的 `[</tool_call>]` / `[<]tool_call[>]` / `[<invoke name="cmd">][<command>...</command>]` 等方括号包装的伪 tool_call 块。**关键顺序**：combined regex（`<tool_calls?>.*?\[?</?tool_calls?>\]?`，兼容单/复数与方括号包裹闭）必须**先**跑；wrapper / 方括号 invoke 块的正则拆成几条放后面做兜底。否则 wrapper 先剥 → tool_call 块找不到闭合 → 留下 78 字符半截垃圾。新增 MiniMax-M3 输出格式时必须同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）。
   7.2. **`_try_compact_react` 必须调用 filter**：input 已经 `_build_clean_compact_input` 清空 AIMessage.content，但保留 `tool_calls` 字段（API 强校验需要），所以 LLM 仍会模仿输出 `<tool_call>` 块；filter 是兜底主力，prompt 是源头。**根因**：M3 与 agent_llm 共用同一个 weights，看到 input 里的 `tool_calls` 字段会模仿输出 tool_call 块。filter 是所有调用 M3 的节点（agent_node / final_node / imp_ipt / `_try_compact_react`）的兜底。
   7.3. **react_compact prompt 显式禁止 tool_call + Few-shot 锚定**：prompt 的"禁止"段必须包含 `<tool_call>` / `[</tool_call>]` / `[<invoke name="cmd">][<command>...]` 等伪 tool_call 格式；同时配 1 个好例子 + 1 个反例 + 一行点错在哪，few-shot 锚定比单纯禁止清单强得多。
8. **Memory 操作加锁 + 串行**：见偏好 8 / 9，新方法（如 `restore_memory`）必须继承
9. **节点异常统一打 `@node_guard`**：见偏好 11，`sub_agent` 这种嵌套调用外层再包一层 try/except 返回兜底字符串，主 agent 才能继续
10. **前端错误气泡不被覆盖**：见偏好 12，新增 SSE 事件路径必须沿用 `wasError` 防御
11. **SandboxPool 池锁**：见偏好 14，新加执行方法（除 `execute` / `execute_command` 外）必须把 pop → exec → append 整段放在 `with self.lock:` 内，否则 N+1 并发撞空池
12. **Electron `protocol.handle` 注册时机 + 路径双形态**：见偏好 15 / 16；必须放在 `app.whenReady().then(...)` 内 + createWindow 之前；asar 内可读用 `__dirname`，asar 外用 `process.resourcesPath`，用 `app.isPackaged` 三元判断 dev/packaged