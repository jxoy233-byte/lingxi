# ChatMe（灵析）AI 协作指南

> 完整项目说明见 [`README.md`](README.md)。本文档给 AI 协作者阅读：项目怎么组织、关键路径在哪、AI 协作的偏好与约定。

## 项目概述

ChatMe（产品名「灵析」Lingxi）是一个基于 LangGraph 的多智能体数据分析对话系统。后端 FastAPI + LangGraph + Docker 沙盒，前端 Vue 3 + Vite + Electron 桌面端。Redis 做 checkpoint + state saver，本地文件系统做文件存储。

## 技术栈

### 后端

- **框架**: FastAPI + LangGraph + LangChain；**MCP**: FastMCP 3.x；**包管理**: uv
- **状态**: Redis (checkpointer + state saver)；**沙盒**: Docker 容器池（`ChatWorkflow/mcps/sandbox/pool.py` 的 `SandboxPool`，min=1, max=4）
- **解析**: docling + qwen-vl-utils + unstructured
- **定时任务**: APScheduler `AsyncIOScheduler + RedisJobStore`（Asia/Shanghai，重启可恢复）
- **LLM**: OpenAI 兼容 API（OpenAI / DeepSeek / 本地 VL 模型多 provider）

### 前端

- **Web**: Vue 3 + Vite（端口 18211）；**桌面端**: Electron 41 + electron-builder 26
- **样式**: CSS Variables + 原生 CSS；**Markdown / 数学**: marked + highlight.js + katex
- **Electron 关键能力**：`file://` 协议拦截、SSE 流透传、↻ 页面刷新按钮（SVG path `M20.49 15a9 9 0 1 1-2.12-9.36L23 10`）、多环境切换、**单窗口架构** + BootstrapView 浮窗 + `servicesReady` IPC 状态机 + autoEnter 三态按钮

## 架构

```
backend/
├── ChatMe/                    # FastAPI 应用代码
│   ├── APIRouter/             # /chat /static /api /admin
│   ├── ChatMeConfig/          # 配置加载（_load mtime + force_reload 热加载）
│   ├── ChatService/           # SSE 流式 + FilesLoaders 大文件截断
│   ├── ChatWorkflow/          # LangGraph 5 节点 + ReAct 压缩 + Memory + SkillRegistry + mcps
│   ├── LoggingManager/        # QueueHandler 异步日志
│   └── test/
├── skills/                    # Bocha / Exa / Tavily / ImageParser / DataAnalysis / Scheduler / Memory / SkillForge / _search_health.py
├── .chatme/                   # 局部配置
├── pyproject.toml
└── main.py                    # FastAPI 入口，lifespan: chat_service → scheduler → cleanup

frontend/                     # Vue 3 + Electron 桌面端
sandbox/Dockerfile             # 代码沙盒镜像（Python 3.12）
docker-compose.yml             # Redis 服务编排（端口 48211）
```

> 详细目录树见 `README.md`。

## 工作流

```
用户输入 → input_parse_node → context_assembly_node
                                  ↓
                          agent_node ↔ tool_execution_node（循环）
                                  ↓
                            final_node → END
```

### 节点职责

- **`input_parse_node`**：输入预处理、文件解析（docling / VL）、`improve_input`；给 `imp_ipt` 标记 `additional_kwargs.imp_ipt=True`
- **`context_assembly_node`**：上下文组装（imp_ipt / memory / 当前轮循环消息）+ **ReAct 压缩**（4 阶段循环后台异步）+ **done cycle 检测 + RemoveMessage 清理** + 中断检查
- **`agent_node`**：v0.2.0 新图——AI 决策（调工具 / 调 `done` 收尾 / 无 tool_calls 走英文 SysMsg 重试 ≤ 3 次后强制 final_node）；老图——`should_end_node` LLM 决策节点
- **`tool_execution_node`**：`PermissionedToolNode`（继承 LangGraph `ToolNode` + `_awrap_tool_call` hook），执行搜索 / MCP / Docker 沙盒 / **`done` 工具**（新图）；`cmd` / `code` 走 `interrupt()` 弹审批，Redis `permission:{sid}` hash 跨 SSE 流复用决策
- **`final_node`**：最终回复生成（独立于 agent 的 LLM），用 **dynamic system prompt** 把 `imp_ipt` 注入 system 层

State 定义在 `backend/ChatMe/ChatWorkflow/config/models.py`（`ChatStateCore2` / `FileParseState`），用 LangGraph TypedDict + `add_messages` reducer。

### ReAct 流程压缩

`context_assembly_node` 每轮 cool-down 触发（`(tool_call_times - last_compact_at) >= 5` + 最近 5 轮 chars ≥ 10000 + 无 pending + ≥1 完整 loop）→ `asyncio.create_task` 启动 `_background_compact_react`（**不 await**）→ agent 推进 2 个完整 loop → `len(current_complete_loops) >= replace_at` 时调 `_build_compaction_draft` 重组 context = `[memory + imp_ipt] + [ReAct 摘要 SystemMessage] + [最近 2 轮原文]`。

关键约束（详见偏好 7）：压缩范围除最近 2 轮外所有 loop；imp_ipt 之前整体保留；产物 SystemMessage 形式插入 imp_ipt 之后。输入净化：清空 AIMessage.content 但**保留 `tool_calls`**（API 强校验）。失败兜底：长度 [250, 4096] 区间外 / filter 清不干净 / LLM 异常一律 `return None`。专用 LLM `get_react_compact_config()`（temp=0.3 / max_tokens=4096）。`compression_handled_this_round` bool 标记防 iteration 2+ 重复压缩；`is_done_cycle=True` 时整段跳过。

### 工作流启动入口

```bash
uv run chatme_main             # 主服务（默认端口 38211），stdio 模式下 fork MCP 子进程
uv run chatme_mcp              # 仅开发模式单独起 MCP（stdio，正常运行不需要）
```

## 前端组件

详见 [`frontend/README.md`](frontend/README.md)；核心要点：

- **`App.vue`**：全局状态 + SSE + `_sessionHadError` 错误气泡保护 + 四 Set（`_activeStreamingSessions` / `_approvalPendingSessions` / `_completedSessions` / `_errorSessions`）+ `_pendingQueue` / `_queueDrainDeferred` 消息排队 + `scheduledTasksMap` + `refreshPage()`
- **`Sidebar.vue` / `ConversationItem.vue`**：全量入 DOM + 自定义 webkit 滚动条 + 删除行内二次确认 + 底部 ⏰ 触发按钮 + 展开任务列表（localStorage 持久化，max-height 110px）+ 四色状态圆点
- **`MessageList.vue`**：滚动控制（入场 easeInOut + 流式 ramp + 100ms 防抖 + wheel/touch 让出）；转发 `scheduled-task-*` / `restart-session`
- **`MessageItem.vue`**：Markdown / 代码高亮 / 错误框 / 中断态「重新对话」按钮；审批 UI 内嵌到 toolCall 行 + 读 `tool.args.local` 判执行环境
- **`MessageInput.vue`**：流式期间不禁用发送，消息由 App.vue 入队
- **`ScheduledTaskItem.vue`**：⏸/▶ 启停、⚡ 立即运行、🗑 行内小红叉二次确认
- **`ChatHeader.vue`**：↻ 刷新按钮（与 DataAnalysisTree 共用 SVG path）
- **`DataAnalysisTree.vue`**：⬇ ZIP + 👁 HTML 预览 + 🗑 「清空回收站」按钮
- **`DataTreeNode.vue`**：文件行 × 红叉行内二次确认删除（软删除 `.trash/{sid}/`）
- **`SettingsDialog.vue`**：4 tab + VL `local` 开关 + 脱敏编辑 + `buildPayload()` diff-only + 「立即清理 checkpoint」按钮
- **`CheckpointPanel.vue` / `FilePreviewPanel.vue` / `FilePreviewModal.vue` / `WebPreviewPanel.vue` / `SearchResults.vue` / `ConfirmDialog.vue`**：见 README.md

### Electron 主进程能力

- **多环境支持**：`NODE_ENV` 严格切换 dev/test/prod
- **`file://` 协议拦截**：在 `app.whenReady()` 内注册（必须在 createWindow 之前）；`/chat/*` + `/static/*` 走 `net.fetch` 转发到后端，其他走白名单校验后从 asar 内 `dist/` 读盘
- **API 转发三件套**：method / headers / body 显式透传 + `duplex: 'half'`；SSE 流必须显式 `new Response(upstream.body, ...)` 重建 stream
- **静态文件白名单**：`resolvedPath` 必须在 `distDir + path.sep` 之下，否则 403；hashed assets 永久缓存，index.html 不缓存
- **图标必须放包外**：`build/` 通过 `extraResources` 复制到 `app/Contents/Resources/build/`，运行时用 `process.resourcesPath` 取
- **安全策略**：生产环境禁用 DevTools / 右键菜单 / 危险快捷键；外部链接走 `shell.openExternal`

## 关键文件

> 完整职责清单见 `README.md`；本文件只列**AI 协作最常碰到的关键路径**：

### 后端（按调用频次倒排）

- **`ChatWorkflow/core.py`**：5 节点逻辑 + 5 个 LLM 实例（`MessagesPlaceholder`）+ ReAct 压缩 + final_node 动态 system prompt
- **`ChatService/core.py`**：SSE 流式 + `_memory_update_tasks` 串行队列 + 回溯走 `CheckpointJanitor.retarget_to()`
- **`ChatWorkflow/mcps/sandbox/pool.py`**：Docker 容器池 `SandboxPool`（v2 K 容器 × N 并发，池锁必须包住整段 pop→exec→append）
- **`ChatWorkflow/mcps/permissions/core.py`**：`PermissionedToolNode` + Redis `permission:{sid}` hash + 4 档决策 + `code_fingerprint` 永久批准
- **`ChatWorkflow/mcps/tools/platforms/`**：多平台 prompt adapter（`base.py` 抽象 + `darwin.py`/`linux.py`/`windows.py` + `registry.py`）；shell 风格差异都走这里
- **`ChatWorkflow/mcps/server.py` + `session.py`**：FastMCP 工具入口 + stdio 长生命周期子进程 + `ClientSession` 常驻复用
- **`ChatWorkflow/skills/registry.py`**：`SkillRegistry` + SKILL.md frontmatter + `_maybe_rescan()` 按每个 SKILL.md `stat()` mtime 检测 + `build_mount_args()` 加 `@functools.lru_cache(maxsize=1)`
- **`ChatWorkflow/Memory/core.py`**：per-thread `asyncio.Lock` + 临时文件原子写（`fsync` + `os.replace`）
- **`ChatWorkflow/decorators.py`**：`@node_guard` 装饰器，`except GraphBubbleUp` 必须原样 raise
- **`ChatWorkflow/CheckpointJanitor.py`** + **`APIRouter/checkpoint_janitor.py`**：业务层 checkpoint prune + `retarget_to()` 覆写 latest 指针；HTTP 层唯一路由 `POST /admin/checkpoints/prune`
- **`ChatWorkflow/config/{graph_config,models}.py`**：prompts + State TypedDict；`PROMPT_MAIN_FLOW` 只讲决策流，工具用法下沉到 `platforms/base.py`
- **`ChatMeConfig/core.py`**：`_load()` mtime + `force_reload()` + `save_config()` 原子写 + 按段决定 `restart_required`
- **`APIRouter/{admin_config,scheduled_tasks,message_queue}.py`**：`/admin/config` GET/PUT + `/admin/restart` POST + `/admin/health` GET + `/admin/scheduled-tasks` CRUD + `/chat/{sid}/queue` FIFO 持久化（≤20 × 4000 字符，**不主动 drain**）
- **`APIRouter/{main,data_export,static_file,model_vl,timed_clean}.py`**：`/chat` 主路由 + `/export/artifacts`（ZIP/HTML）+ `/export/turn/{cid}` + `/static` 静态文件（session_id dual regex 32+12 hex，fallback 见偏好 21）+ VL 模型路由（`local=false` fallback）+ 定时清理（`PRESERVED_TOP_DIRS={"cached/.fonts"}`）
- **`ChatService/FilesLoaders/core.py`**：文件加载 + `_maybe_truncate` 大文件截断（`TEXT_TRUNCATE_LENGTH=4000`）
- **`LoggingManager/logging_config.py`**：`QueueHandler` + `QueueListener` 异步日志 + `get_thinking_chain_logger()` 单开思维链日志文件
- **`skills/{DataAnalysis,Scheduler,Memory,SkillForge,_search_health}.py` 等**：DataAnalysis 数据分析规范包 + 数据库子模块（只读 MySQL/SQLite/PostgreSQL/MongoDB 跨会话配置）+ Scheduler 4 层模块 + Memory `remember()`/`recall()`（**`code(..., local=True)`**）+ SkillForge `create_skill()`/`list_skills()`/`read_skill()`（**`code(..., local=True)`**）+ `_search_health.py` 三个搜索 skill GET ping 探活
- **`main.py` + `sandbox/Dockerfile`**：FastAPI 入口（lifespan 嵌套顺序 `chat_service → scheduler → cleanup`；`uvicorn.run(app, ...)` **传对象不传字符串**）+ 代码沙盒镜像（Python 3.12）


### 前端（精简）

- **`src/App.vue`**：全局状态 + SSE + `refreshPage()`；详细功能列表见 `frontend/README.md`
- **`src/components/`**：业务组件（ChatHeader / Sidebar / ConversationItem / MessageList / MessageItem / MessageInput / ScheduledTaskItem / CheckpointPanel / FilePreviewPanel / FilePreviewModal / DataAnalysisTree / DataTreeNode / WebPreviewPanel / SearchResults / SettingsDialog / ConfirmDialog）
- **`electron/main.js`** + **`electron.config.js`** + **`preload.js`**：主进程 + 配置 + IPC bridge
- **`vite.config.js`**：同时导出 `viteServerConfig` 给 Electron 复用，`base: './'` 必须在顶层
- **`package.json`** + **`build/icon.{icns,ico,png}`**：electron-builder build 配置

## 命令行工具

```bash
chatme_main                      # 主服务（默认端口 38211）
chatme_mcp                       # 仅开发模式单独起 MCP

cd backend
uv run python main.py            # 主服务
uv run python -m ChatMe.ChatWorkflow.mcps.server   # MCP 服务

docker-compose build sandbox     # chatme-python-sandbox:latest
docker-compose up -d redis       # 端口 48211，密码 123456
```

## AI 自动化工具

### 测试 Agent（多轮对话测试）

**端到端测试前必读 `.test_agent/test_agent.md`** —— 硬约束、工具链、DOM selector、完整流程代码、报告生成、已确认的真实后端缺陷都在那。

简要约束：

- **硬约束**：MCP 单调用 ≤280s；单 batch ≤12 轮；IAB 同会话 22+ 轮 R2 后必然 timeout
- **首选 Codex IAB**（`mcp__node_repl__js` 调 Playwright API）；备选本地 Chrome + CDP
- **5 个必踩陷阱**：① IAB 22+ 轮卡死 ② send-btn 延迟（`waitForTimeout(500)` + `click({force:true})` 跳 disabled）③ URL 漂移（`/` → `/<hash>` 正常）④ 完成判定看 AI 文本稳定 1.5-2.5s ⑤ MCP 边界丢 Vue 状态
- **已确认真实后端缺陷**：① 跨多轮记忆上限 19+ 轮 R12/R17 失败 ② `POST /chat/improve_input` 返与原文相同的 `improved_text` ③ 复杂业务题触发 20+ 分钟无限工具调用循环 ④ IAB 路由状态不稳

### 定时优化 Agent（cron job `a09d41ec`）

`~/.claude/scheduled_tasks.json` 里持久化 cron job **每小时 :23 自动触发** ChatMe 后端优化 Agent（durable，跨 session 持续；**7 天后自动过期**需续期）。目的：扫思维链日志 + 自动修复 prompt / AI 配置问题。完整 prompt 见 cron job 本身；摘要：读 `thinking_chain-YYYY-MM-DD.log` 9 个 call site → 判定只看思维链 / 输出方向合不合适。**✅ 可自主改**：prompt 删冗段加 few-shot 锚定 / `_filter_thinking_content` regex / env 拆分 / `format_thinking_chain` max_chars / `PROMPT_MAIN_FLOW` 反冗余约束。**❌ 不做**：调 max_tokens / temperature / 大范围 prompt 重写 / 加新工具 / 节点 / 改 ReAct 流程 / 改 should_end_node 决策 / 改前端 / Electron / 不主动 git commit；5+ 文件改动先列出来一次性不下。**管理**：`claude --cron-list` / `--cron-delete a09d41ec`；续期用 `CronCreate` 重建。

## AI 协作偏好

> 这些偏好从用户对话中沉淀，存于 `/Users/jx/.claude/projects/-Users-jx-coding-projects-ChatMe/memory/`。改前先读 `MEMORY.md` 看完整索引。

### 工程约定

1. **后端最小化 + 前端动态加载**：文件树 / 列表类接口后端只返扁平列表，前端构树 + 动态加载内容；path 须含 `cached/` 前缀。
2. **沙盒隐藏文件过滤**：`sandbox/sitecustomize.py` 过滤规则（`.` / `__` 挡、`_` 不挡）+ 只在挂载点根目录一层不递归子目录。
3. **沙盒 config 同步策略**：用中间文件隔离 skills key，仅在 MCP 启动 / 容器重建时重生成，不做运行时自动同步。
4. **流式响应滚动 UX**：入场 `easeInOut`；流式 ramp（慢→快）+ 100ms 打断防抖；用户 wheel / touch 立即让出控制权。
5. **MCP 工具参数 `local`（v0.1.3 反向命名）**：Python `local`（旧 `sandbox`/`use_sandbox`）在 MCP schema 里是 `local` 参数；过滤 / 判断要查实际 args key，兼容新旧两种。
6. **`should_end_node` 设计偏好**：LLM 决策节点的单条喂入 / 完整写回、低频字面量子串匹配、独立 `max_tokens` env、prompt / 解析兜底一致。
7. **ReAct 流程压缩 4 阶段循环**：**后台异步 + 不阻塞工作流**——见上方「ReAct 流程压缩」章节；imp_ipt 是唯一 draft 切分锚点（`additional_kwargs.imp_ipt=True`）；后台任务 finally 块 pop 自己；result 为 None 时不写 pending。**Why（M3 filter 兜底）**：M3 看到 input `tool_calls` 字段 100% 模仿输出 `<tool_call>` / `[</tool_call>]` / `[<invoke name="cmd">][<command>...]` 等伪 tool_call 块。**关键顺序**：combined regex（`<tool_calls?>.*?\[?</?tool_calls?>\]?`）必须**先**跑，wrapper / 方括号 invoke 块拆成几条放后面兜底。**react_compact prompt 显式禁止 + Few-shot 锚定**：prompt 列出伪 tool_call 格式 + 1 个好例子 + 1 个反例 + 一行点错在哪。新增 M3 输出格式必须同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）。
8. **Memory 并发安全**：`MemoryManager` 内部维护 `_thread_locks[thread_id]`，`update_memory` / `delete_memory` / `backtrack_memory` / `delete_latest_backup_memory` 全部走 `async with self._get_thread_lock(thread_id)`；文件写入走 `_atomic_write_text`（写 `*.tmp` + `fsync` + `os.replace`）。
9. **ChatService 记忆任务串行**：每会话在 `_memory_update_tasks[session_id]` 里只保留一个 asyncio.Task，新任务通过 `asyncio.shield` 串接上一轮；新请求发起 / 删除会话 / 回溯 前会先 `_wait_previous_memory_update` 等待；SSE 暴露 `memory_wait_start` / `memory_wait_done` 事件。
10. **异步日志 + 思维链单开文件**：写文件走 `QueueHandler` + `QueueListener` 模式，业务线程不入 IO；`atexit` 统一 `listener.stop()` 清理。ChatWorkflow 各节点的 `format_thinking_chain(...)` 类思维链日志（9 处）**必须**走 `self.thinking_logger.info(...)`（`get_thinking_chain_logger()` 返回），写到独立文件 `thinking_chain-YYYY-MM-DD.log`，**严禁**写到主日志。
11. **节点异常统一兜底**：所有 LangGraph 节点（ChatWorkflow 5 个主节点 + 文件图 3 个节点 + sub_agent agent_node）都打 `@node_guard("<name>")`：`except Exception` 捕获后 log + 包装 `RuntimeError` 让 SSE 外层统一返回 `error` 事件；但 `except GraphBubbleUp`（LangGraph 控制流异常的基类，涵盖 `GraphInterrupt` / `ParentCommand` 等）必须**原样 `raise`**。
12. **前端错误气泡保护**：App.vue 维护 `_sessionHadError: Set<session_id>`，SSE `error` 事件触发时把 `session_id` 标记为保护态；保护态下 `done` 事件不会覆盖错误气泡，`refreshConversation` / `updateTitleAndRefresh` 跳过 messages 重拉，只更新侧边栏。
13. **`cmd` / `code` 工具默认走沙盒（v0.1.3 反向命名 `local`）**：默认 `local=False`（**反向 default**：不传 = 沙盒隔离；要本机才显式 `local=True`），内部仍用 `use_sandbox = not local`。沙盒不可用降级到本机。**执行环境区分**：`interrupt()` payload 带 `execution_env` 字段透传到 SSE；前端 `MessageItem.vue` 容器挂 `tool-inline-approval--local` modifier class，**唯一视觉差异 = 淡红背景叠加** `rgba(239, 68, 68, 0.06)`。
14. **SandboxPool 池锁必须包住整个 pop → exec → append 周期**：min=1, max=4, per_container_concurrency=8；N+1 并发下 pop 跑锁外会撞空池报 `No available containers`；**新加执行方法必须继承这个锁结构**（v2 用 `Condition.wait` 整个 while 循环包在 `with self._pool_lock:` 内，避免 `cannot wait on un-acquired lock`）。
15. **Electron `file://` 协议拦截必须透传 method/body/headers**：在 `app.whenReady()` 内注册；`/chat/*` 转发到后端时**必须**显式带 `method: request.method, headers: request.headers, ...(request.body && { body: request.body, duplex: 'half' })`，否则 POST `/chat/` 的 body 被丢、后端收到 GET 请求；SSE 流必须显式 `new Response(upstream.body, ...)` 透传 stream。
16. **Electron 图标必须放包外**：`nativeImage.createFromPath` 不读 asar 内文件；`build/` 通过 `package.json` 的 `extraResources` 复制到 `app/Contents/Resources/build/`（macOS）/ `app/resources/build/`（Win），运行时用 `process.resourcesPath` 取真实路径；`app.isPackaged` 三元判断 dev vs packaged 路径；`app.dock.setIcon` 和 `BrowserWindow.icon` 都必须是 PNG。
17. **Electron `protocol.handle` 静态文件必须白名单校验**：`resolvedPath = path.resolve(pathname)` 后必须检查 `startsWith(distDir + path.sep)`，否则 `403 Forbidden`；不写这一行的话渲染层一句 `fetch('/etc/passwd')` 就能读任意磁盘路径。
18. **Electron 输出目录用 `release/electron-builder`**：`directories.output` 不要设 `dist/electron-builder`，否则会和 Vite 的 `dist/` 撞目录，且会被 `files` 模式误打进 asar。
19. **可滚动侧栏/面板 CSS 约定**：① 数据全量入 DOM，禁止 `slice(0, N)` / `displayCount` 切片；② 侧栏 `height: 100vh; flex-shrink: 0; overflow: hidden`，外层不被内容撑大；③ 固定头部 `flex-shrink: 0` 锁尺寸；④ 滚动区用 `height: calc(100vh - X)` **不走** `flex: 1 + min-height: 0`；⑤ **`overflow-y: auto`**——浏览器默认；**禁止** `scroll` / `hidden`；⑥ 必须用 JS + `ResizeObserver` 监听 `scrollHeight > clientHeight + 1`，溢出挂 `.has-overflow` class；⑦ `@scroll="handleScroll"` 直接绑在 `.list`，mounted 用 `$nextTick` 等首次渲染完再 `checkOverflow()`。**CSS-only 没法做到"溢出时才显示滚动条"**——必须靠 JS + ResizeObserver。
20. **流式响应会话保存（per-session 快照 + 切走保留 in-progress）**：用户流式期间切走，原会话 SSE 增量不能丢；切回显示实时状态；侧栏闪烁小点；流式完成 `refreshSession` 不能影响当前会话视图。
    - **三件套**（`App.vue` data）：`_activeStreamingSessions` / `_streamingMessages`（**与 this.messages 同源引用**——SSE 改 this.messages 自动同步 snapshot，不深拷贝）/ `_streamingMeta`。
    - **sessionChanged 分支**：`this.currentSessionId !== requestSessionId` 时所有 content / reasoning / tool_call_* / done / error / interrupt 增量**只写到 snapshot**，不碰 this.messages。
    - **done / error / interrupt 必清三件套 + `refreshSession(sid)`**（只动侧栏）；**`requestSessionId` 必须在 SSE 循环开始前锁定**。
    - **Vue 2 Set 陷阱**：`.add` / `.delete` 不触发重渲染，必须 `new Set(...)` 整替换。
    - **`loadConversation` 双分支**：流式分支直接 `this.messages = snapshot` + `this.isLoading = true` + `startResponseTimer()`，**不调** `get_conversation`。
    - **`cleanupLoadingState` 不能 pop 流式 AI 消息**（同源引用 pop 会污染 snapshot）。
    - **新增流式 SSE 入口**（sendMessage / handleResume / handleRestream）必须按上述点对点实现；F5 恢复不在本约定范围——需要 `/chat/streaming_sessions` 接口 + 恢复 SSE 协议。
21. **静态文件 fallback（无 sid 才跨会话找 + Referer 推断 sid 优先）**：`APIRouter/static_file.py` `serve_cached_file` 精确路径命中失败时分流：**带 sid 路径**（dual regex 32+12 hex）找不到 → **直接 404**；**无 sid 路径**找不到 → 双层 fallback：先从 `Referer` header 正则提取 sid 作 `primary_sid`（32 位写前面，路径边界 `/[/?#]|$`），在 `cached/{primary_sid}/**` 下递归找；没命中再跨 `cached/*/` 所有 sid 找（按 `st_mtime` 最新返回）。**Why 只无 sid 才 fallback**：实际请求 URL 都带 sid，fallback 是少数兜底；带 sid fallback 会把"我自己 session 缺文件"变成"别人 session 同名图"。**Why Referer**：浏览器 `<img>` 加载 markdown 图片**不能**加自定义 header，EventSource 也不能；Referer 浏览器自动带。
22. **删除会话行内二次确认（小红叉状态机）**：`ConversationItem.vue` 维护 `isConfirmingDelete`：第一次点 × → `confirming` class 变红 `rgba(239,68,68,0.12)` 底常显；第二次点红 × → **立刻** `isConfirmingDelete = false` 再 `$emit('delete')`；点别处 / Esc 取消（`mounted` 绑 `document.click` + `keydown(Escape)`，`beforeUnmount` 解绑）。**App.vue `deleteConversation` finally** 必须清理三件套（`stopStreamTimer` + 三个 Map/Set delete + `new Set(...)` 触发响应式）+ 当前会话切换（关 SSE + `cleanupLoadingState()` + `createNewChat()`）。
23. **Electron 单窗口架构 + autoEnter 三态按钮**：单 BrowserWindow + 主界面永远在 DOM 里（`appReady=false` 时加 `.app-disabled` 灰显禁用），`<BootstrapView>` 浮窗叠加（fixed + z-index 1000 + backdrop-filter 模糊）。主进程 `let servicesReady = false`；bootstrap 完成后 `webContents.send('startup:services-ready-changed', { ready, autoEnterFrontend })` 推 object payload。warm / cold / warm-refresh 三条路径一律不闪 BootstrapView。**三态按钮**：`launching=true` → 「启动中...」disabled；`servicesReady=true && !autoEnterFrontend` → 「进入应用」emit `enter-app`；其他 → 「启动应用」（`!allOk` 时 disabled）。**避免双源真相**：`BootstrapView.servicesReady` 是 prop，不重复 invoke `getServicesReady`；所有 `appReady` 翻转都在 App.vue 一处。**重启路径**：`restartBackend()` 完成后 `setServicesReady(true, { autoEnterFrontend: true })` —— 用户已在 app 里，重启恢复直接交回交互权。
24. **LLM 懒加载 + 热切换（v0.3.x）**：用户改 `llm_providers`（api_key / base_url / model_name / active）后**无需重启后端**，下次调用自动用新配置。设计：
    - **`backend/ChatMe/ChatWorkflow/llm_factory.py`**：`WeakValueDictionary` 按 `(role, api_key_fp, base_url, model_name)` 缓存 `ChatOpenAI`；`get_llm("main")` cache miss → 自动 new，cache hit → 返回缓存实例（~0 耗时）。
    - **5 个工作流角色共享同一实例**：`llm_core / agent_llm / agent_llm_with_done / summary_llm / react_compact_llm / llm_imp_ipt / should_end_llm` 都拿 `llm_factory.get_llm("main")`（连接三元组相同），VL 走 `get_llm("vl")`（独立 base_url / api_key / model_name，vl.local=False fallback 时与主模型 key 撞 → 复用同实例）。
    - **`ChatWorkflow/core.py`**：7 个 `self.xxx_llm = ChatOpenAI(**)` 改为 8 个 `@property` getter（每次访问重新组合 LCEL `prompt | llm.bind_tools(tools)`，~µs 级开销）；`init_llms` 只持有 prompts 不 new `ChatOpenAI`。
    - **`ChatMeConfig.save_config`** 加 `llm_factory.invalidate_for_providers()` hook（写之前抓旧快照 + 写后比对前后 key，主动 pop 旧 key → 旧实例失去强引用 → GC 释放 httpx 连接池）；`restart_required` 一律 False（v0.3.x 起所有段都热生效）。
    - **`ChatMeConfig.get_active_llm_config`** 加 `llm_providers.active` 字段优先级（最高 > self_check_llm 探测 > chain[0]），让用户在 SettingsDialog / SetupView 手动选主用 provider。
    - **新增路由**：`GET /admin/llm/models?provider=xxx`（后端 proxy 调 `{base_url}/v1/models`，**严格按远端返回**，不拼白名单；远端空就返空 + source='remote'/models=[], 失败返 source='error'/models=[]），`GET /admin/llm/cache-info`（调试用）。**Why 不拼白名单**：旧版拼了 `gpt-4o/deepseek-chat/Qwen` 等硬编码列表，用户不知情选了和 base_url 不匹配的模型 → 401。误导 > 兜底。
    - **前端 SettingsDialog / SetupView**：「⟳ 拉取模型列表」按钮填充 model 下拉框、provider group-title 加「设为当前生效」radio、顶部 active-bar 显示当前生效 provider + model。`buildPayload` 把 `activeProviderName` 单独 diff 写到 `payload.llm_providers.active`。
    - **vl.local 切换例外**：决定是否加载 Qwen3-VL 本地模型到内存，必须重启后端。SetupView.onFinish 的 `needsRestart` 只在 `vl.local` 变了才 emit('restart-requested')。


### 版本约定（按版本倒排）

**v0.3.2** — BootstrapView deps 模式「进入应用」按钮无效 bug 修复 + 移除 LLM 模型白名单兜底（`/admin/llm/models` 严格按远端返回，空就返空）。

**v0.3.1** — 首启 UX 重构：基于 `autoEnterFrontend` 切换 BootstrapView `classic` / `deps` 二形态 + App.vue 自动 bootstrap + StartupLoadingView 等待动画 + SkillForge 自动 refetch slash 面板。

**v0.3** — 取消 upload 阶段产物软删到 `.trash/{sid}/{ts}/`，11:30 `daily_trash_cleanup` 兜底物理清。

**v0.2.4** — 启动链路鲁棒性 + 重启遮罩 retry（`main.js:bootstrapSession` 取消令牌 / `App.vue:handleRestartBackend` `_restartVersion` race 防护 / 单实例锁 + macOS 退出行为符合 HIG）。

**v0.2.3** — 部署产物清理（统一删除 `frontend/` + `cloud/`）+ tar 打包 race 修复（`lingxi-sync.sh:_package_targz` 改 `/tmp/`）+ 末尾 `sync` 刷盘。

**v0.2.2** — 健壮性 + 文档精简：搜索源健康探测（`_search_health.py` 并发 ping）/ SandboxPool 池锁修复（`Condition.wait` 包 `with self._pool_lock`）/ Redis 端口 6024 → 48211（避开 Hyper-V excludedportrange）/ final_node SysMsg 改写双轨制。

**v0.2.1** — 配置向导 SetupView（独立组件，**不要混用 BootstrapView**）+ fixRedis ping-first 四段判定 + startBackend 端口预检（`killPortIfListening`）+ Windows `file://` API 路径修复（`apiPathname = IS_WIN ? pathname.replace(/^\/[A-Za-z]:/, '') : pathname`）+ unified restart overlay 三处入口共用。

**v0.2.0** — 图工作流大重构：新默认图 `_create_graph_improved` 替代 `_create_graph_core2`（老图完整保留作回滚基线）+ MCP `done` 工具（仅新图暴露）+ `route_agent_output` 纯结构化路由 + agent no-tool-call retry（≤3 次英文 SysMsg）+ `RemoveMessage` 清理 done cycle + `compression_handled_this_round` 防重复压缩 + `REACT_COMPACT_DETECTION_MIN_ROUNDS` 4 → 5 + 前端 `done` 工具调用过滤（两处）+ MIT 许可证。

**v0.1.8** — 文件树 Finder 化：长按框选（250ms / 移动 ≥8px 才进 box-select）+ HTML5 拖拽移动（Alt 切 copy/move）+ 焦点目录 `focusDir`（Cmd/Ctrl+V 目标）+ copy/cut 视觉 + 空状态 + 树底 `+文件夹/+文件` 按钮（`Cmd+Shift+N/Alt+N`）+ OS 系统拖拽 overlay + 后端 `_find_unique_name` 不剥 `(v1-beta)`。

**v0.1.7** — 文件树行内删除 + 软删除 `.trash/{sid}/{ts}_{rel}` + 11:30 `daily_trash_cleanup` 兜底 + 标题自动派生（`update_conversation_title` 派生 → `PUT /chat/{sid}/title`）。

**v0.1.6** — matplotlib 中文字体随 skill 自动 mount：`NotoSansSC-Regular.otf` 放 `backend/skills/DataAnalysis/fonts/`，`get_fonts_setup_header()` 同时扫描 4 路径（按序去重，优先 skill 路径）；`legacy cached/.fonts/` 保留兼容老部署（`PRESERVED_TOP_DIRS={"cached/.fonts"}`）。

**v0.1.5** — Memory + SkillForge + Scheduler + CheckpointJanitor + 热加载：Memory 4 变体（`facts/preference × thread/global`）/ SkillForge `create_skill/list_skills/read_skill` 写入必须 `code(..., local=True)` + registry mtime 自动重扫 + SKILL.md frontmatter YAML（`name/description/aliases/mount/module/lazy`）+ `build_mount_args()` `@lru_cache(maxsize=1)` + Scheduler 4 层模块 + CheckpointJanitor 拆两层 + `/admin/config` 热加载（segment 级，`permissions/skills` 立即生效，`llm_providers` 需重启）+ `ChatMeConfig._load()` mtime。

**v0.1.4** — `mcps/` 三包重构（permissions / sandbox / tools，各 `__init__.py` 只写说明不 re-export，除 `tools/platforms/`）+ 定时任务 = Skill + REST（不走 MCP）+ 启动配置 lifespan 嵌套顺序 `chat_service_lifespan → scheduler_lifespan → cleanup_lifespan` + `uvicorn.run(app, ...)` 传对象不传字符串 + 消息排队（`/chat/{sid}/queue` Redis FIFO ≤20 × 4000 字符，不主动 drain）+ 回溯走 `CheckpointJanitor.retarget_to()` 覆写 latest 指针 + 未知工具名不崩（`ToolNode._validate_tool_call` 返错误 ToolMessage）+ MAIN_FLOW 只讲「怎么想」工具用法下沉 `platforms/base.py` 的 `<tool>_tool_prompt_block`。
**v0.1.3**：**Pre-check 拦截 SSE 兜底**——`PermissionedToolNode._permission_wrap` pre-check（`dangerous` / `whitelist not_allowed`）拦截时直接 `return ToolMessage` 不调 `execute()`，LangGraph 不发 `on_tool_start`/`on_tool_end`，前端流式看不到拦截结果必须 F5 刷新。**兜底**：`on_chain_end` 节点为 `tool_execution_node` 时按 `tool_call_id` 配对 AIMessage.tool_calls 与 ToolMessage，补 `tool_call_name` + `tool_call_result` SSE。**去重**：per-stream `emitted_tool_call_ids: set`。**Helper**：`ChatService._build_intercepted_tool_call_events(chunk, emitted_ids, elapsed_ms, token_usage)` 统一封装，3 个 SSE 流都加。


**v0.1.2**：跨 SSE 临时 metrics 累加器（每 round 独立 `round_metrics:{sid}` Redis hash，**不**写正式 `threads:{sid}:checkpoints`）。实时累加 + stream `finally` 兜底 + 终态清理 + `delete_conversation` 必须 `DEL round_metrics:{sid}`。


**v0.1.1**：`PermissionedToolNode` + LangGraph `interrupt()` 审批（`_awrap_tool_call` hook 是 `ToolNode` 官方扩展点，自己 try/except 拦截会被 runtime 忽略）；决策存 Redis `permission:{sid}` hash；`resume` 走 `Command(resume=decision)`。**4 档决策**：`approve` / `this-time-only` / `deny` / `feedback:<text>`；`code_fingerprint` = SHA1(`imports + calls + lang + sandbox`)。**审批 UI 内嵌**到 `toolCall` 行。**多平台 prompt adapter**：`platforms/` 抽 `cmd`/`code`/`ctime` shell 差异到 `darwin.py`/`linux.py`/`windows.py` + `base.py`。**`sub_agent` 工具 deprecated**。**session_id 兼容 32 + 12 位 hex**：dual regex 都接受。

**DataAnalysis 数据库分析**：`skills/DataAnalysis/database/` 提供 MySQL / SQLite / PostgreSQL / MongoDB 4 引擎只读，写操作（SQL `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE/MERGE/CALL/REPLACE` + Mongo `$out/$merge/$where/$function/$accumulator/mapReduce/eval`）一律拦截。DB 配置写 `.runtime/`（fcntl + 临时文件 + 原子替换）；LLM 只看 alias / engine / host / database 非敏感字段。`need_db_credentials` 中断事件带 `db_type` / 字段列表，用户 UI 输入凭据后 resume；沿用 SSE `interrupt` 通道。

**导出端点**：`backend/ChatMe/APIRouter/data_export.py`。`/chat/{sid}/export/artifacts?format=zip|html`：打包 `cached/{sid}/data_analysis/`（ZIP 保留 `gen_xxx/charts|data|reports|scripts/`；HTML marked.js + mermaid.js CDN + PNG/SVG base64；单文件 ≤100MB / 总 ≤500MB）。`/chat/{sid}/export/turn/{checkpoint_id}`：截至 checkpoint 的对话 ZIP（`openai.json` Chat Completions + `chatme.json` dump `state.values`）。前端：`DataAnalysisTree.vue` 头部 ⬇ ZIP + 👁 HTML（`exporting` 防连点）；`MessageItem.vue` AI 按钮 ⬇ 「导出到本轮」（`canExportTurn`：AI + 非流式 + 非 error + 有 `checkpointId`）。

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
5. **`imp_ipt` 是 draft 切分锚点**：`input_parse_node` 输出的 `imp_ipt` 唯一身份是 `additional_kwargs.imp_ipt == True`；ReAct 压缩 / final_node 注入 / 后续扩展都靠这个标志定位本轮意图
6. **final_node 不再走 `MessagesPlaceholder`**：imp_ipt 走 `_final_system_template.format(imp_ipt=...)` 注入到 system prompt 独占最高注意力位；context 中要先把 `imp_ipt` pop 出去再喂给 `llm_core`，避免重复注入
7. **ReAct 压缩失败不要 raise**：`_try_compact_react` 一律返回 `None`
   7.1. **`_filter_thinking_content` 是 MiniMax-M3 输出的兜底主力**：filter 必须能吃掉 `[</tool_call>]` / `[<]tool_call[>]` / `[<invoke name="cmd">][<command>...</command>]` 等方括号包装的伪 tool_call 块。**关键顺序**：combined regex（`<tool_calls?>.*?\[?</?tool_calls?>\]?`）必须**先**跑；wrapper / 方括号 invoke 块拆成几条放后面兜底。否则 wrapper 先剥 → 留下 78 字符半截垃圾。新增 M3 输出格式时必须同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）。
   7.2. **`_try_compact_react` 必须调用 filter**：input 已经 `_build_clean_compact_input` 清空 AIMessage.content 但保留 `tool_calls` 字段（API 强校验需要），LLM 仍会模仿输出 `<tool_call>` 块。**根因**：M3 与 agent_llm 共用同一个 weights，看到 input 里的 `tool_calls` 字段会模仿输出 tool_call 块。filter 是所有调用 M3 的节点（agent_node / final_node / imp_ipt / `_try_compact_react`）的兜底。
   7.3. **react_compact prompt 显式禁止 tool_call + Few-shot 锚定**：prompt 的"禁止"段必须包含伪 tool_call 格式；同时配 1 个好例子 + 1 个反例 + 一行点错在哪。
8. **Memory 操作加锁 + 串行**：见偏好 8 / 9
9. **节点异常统一打 `@node_guard`**：见偏好 11
10. **前端错误气泡不被覆盖**：见偏好 12
11. **SandboxPool 池锁**：见偏好 14
12. **Electron `protocol.handle` 注册时机 + 路径双形态**：见偏好 15 / 16
