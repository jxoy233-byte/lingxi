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
- **`agent_node`**：AI 决策（调工具 / 调 `done` 收尾 / 无 tool_calls 走英文 SysMsg 重试 ≤ 3 次后强制 final_node）
- **`tool_execution_node`**：`PermissionedToolNode`（继承 LangGraph `ToolNode` + `_awrap_tool_call` hook），执行搜索 / MCP / Docker 沙盒 / **`done` 工具**（新图）；`cmd` / `code` 走 `interrupt()` 弹审批，Redis `permission:{sid}` hash 跨 SSE 流复用决策
- **`final_node`**：最终回复生成（独立于 agent 的 LLM），用 **dynamic system prompt** 把 `imp_ipt` 注入 system 层

State 定义在 `backend/ChatMe/ChatWorkflow/config/models.py`（`ChatStateCore2` / `FileParseState`），用 LangGraph TypedDict + `add_messages` reducer。

### ReAct 流程压缩

`context_assembly_node` 每轮 cool-down 触发（`(tool_call_times - last_compact_at) >= 5` + 最近 5 轮 chars ≥ 10000 + 无 pending + ≥1 完整 loop）→ `asyncio.create_task` 启动 `_background_compact_react`（**不 await**）→ agent 推进 2 个完整 loop → `len(current_complete_loops) >= replace_at` 时调 `_build_compaction_draft` 重组 context = `[memory + imp_ipt] + [ReAct 摘要 SystemMessage] + [最近 2 轮原文]`。

关键约束（详见偏好 6）：压缩范围除最近 2 轮外所有 loop；imp_ipt 之前整体保留；产物 SystemMessage 形式插入 imp_ipt 之后。输入净化：清空 AIMessage.content 但**保留 `tool_calls`**（API 强校验）。失败兜底：长度 [250, 4096] 区间外 / filter 清不干净 / LLM 异常一律 `return None`。专用 LLM `get_react_compact_config()`（temp=0.3 / max_tokens=4096）。`compression_handled_this_round` bool 标记防 iteration 2+ 重复压缩；`is_done_cycle=True` 时整段跳过。

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
- **`MessageItem.vue`**：Markdown / 代码高亮 / 错误框 / 中断态「重新对话」按钮；审批 UI 内嵌到 toolCall 行 + 读 `tool.args.local` 判执行环境；**思考段 >5 行自动折叠**（line-clamp + 实测溢出，详见 frontend/README.md）
- **`MessageInput.vue`**：流式期间不禁用发送，消息由 App.vue 入队
- **`ScheduledTaskItem.vue`**：⏸/▶ 启停、⚡ 立即运行、🗑 行内小红叉二次确认
- **`ChatHeader.vue`**：↻ 刷新按钮（与 DataAnalysisTree 共用 SVG path）
- **`DataAnalysisTree.vue`**：⬇ ZIP + 👁 HTML 预览 + 🗑 「清空回收站」按钮
- **`DataTreeNode.vue`**：文件行 × 红叉行内二次确认删除（软删除 `.trash/{sid}/`）
- **`SettingsDialog.vue`**：4 tab + VL `local` 开关 + 脱敏编辑 + `buildPayload()` diff-only + 「立即清理 checkpoint」按钮
- **`CheckpointPanel.vue` / `FilePreviewPanel.vue` / `FilePreviewModal.vue` / `WebPreviewPanel.vue` / `ConfirmDialog.vue`**：见 README.md

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
- **`ChatService/core.py`**：SSE 流式 + `_memory_update_tasks` 串行队列 + 回溯走 `CheckpointJanitor.retarget_to()`；`_upstream_retry_fields()` 把重试元信息搬进 SSE `error` payload（非瞬时错误返回空 dict，事件形状不变）
- **`ChatWorkflow/mcps/sandbox/pool.py`**：Docker 容器池 `SandboxPool`（v2 K 容器 × N 并发，池锁必须包住整段 pop→exec→append）
- **`ChatWorkflow/mcps/permissions/core.py`**：`PermissionedToolNode` + Redis `permission:{sid}` hash + 4 档决策 + `code_fingerprint` 永久批准
- **`ChatWorkflow/mcps/tools/platforms/`**：多平台 prompt adapter（`base.py` 抽象 + `darwin.py`/`linux.py`/`windows.py` + `registry.py`）；shell 风格差异都走这里
- **`ChatWorkflow/mcps/server.py` + `session.py`**：FastMCP 工具入口 + stdio 长生命周期子进程 + `ClientSession` 常驻复用
- **`ChatWorkflow/skills/registry.py`**：`SkillRegistry` + SKILL.md frontmatter + `_maybe_rescan()` 按每个 SKILL.md `stat()` mtime 检测 + `build_mount_args()` 加 `@functools.lru_cache(maxsize=1)`。`search()` 打分 = `token_hits * 2 + substring_bonus` + 别名命中 `+6`（见 v0.3.8）
- **`ChatWorkflow/Memory/core.py`**：per-thread `asyncio.Lock` + 临时文件原子写（`fsync` + `os.replace`）
- **`ChatWorkflow/decorators.py`**：`@node_guard` 装饰器（7 个节点全覆盖），`except GraphBubbleUp` 必须原样 raise；529/429/5xx/timeout 走原地重试（5 × 8s），耗尽抛 `TransientUpstreamError`
- **`ChatWorkflow/CheckpointJanitor.py`** + **`APIRouter/checkpoint_janitor.py`**：业务层 checkpoint prune + `retarget_to()` 覆写 latest 指针；HTTP 层唯一路由 `POST /admin/checkpoints/prune`
- **`ChatWorkflow/config/{graph_config,models}.py`**：prompts + State TypedDict；`PROMPT_MAIN_FLOW` 只讲决策流，工具用法下沉到 `platforms/base.py`
- **`ChatMeConfig/core.py`**：`_load()` mtime + `force_reload()` + `save_config()` 原子写 + 按段决定 `restart_required`
- **`APIRouter/{admin_config,scheduled_tasks,message_queue}.py`**：`/admin/config` GET/PUT + `/admin/restart` POST + `/admin/health` GET + `/admin/scheduled-tasks` CRUD + `/chat/{sid}/queue` FIFO 持久化（≤20 × 4000 字符，**不主动 drain**）
- **`APIRouter/{main,data_export,static_file,model_vl,timed_clean}.py`**：`/chat` 主路由 + `/export/artifacts`（ZIP/HTML）+ `/export/turn/{cid}` + `/static` 静态文件（session_id dual regex 32+12 hex，fallback 见偏好 20）+ VL 模型路由（`local=false` fallback）+ 定时清理（`PRESERVED_TOP_DIRS={"cached/.fonts"}`）
- **`APIRouter/word_editor.py`**：`POST /api/word_editor/replace` —— Word 原文 tab 保存入口，整篇重写 docx body。图片往返靠 `[[图片 N]]` 占位符（前端 `wordExtract.js` 生成，后端按 N 搬回原位），**占位符数与图片数对不上直接 422**，绝不静默丢图。抽 drawing 必须用 `body.iter()`（嵌在 `w:p > w:r` 两层里，`find()` 查不到）
- **`ChatService/FilesLoaders/core.py`**：文件加载 + `_maybe_truncate` 大文件截断（`TEXT_TRUNCATE_LENGTH=4000`）
- **`LoggingManager/logging_config.py`**：`QueueHandler` + `QueueListener` 异步日志 + `get_thinking_chain_logger()` 单开思维链日志文件
- **`skills/{DataAnalysis,Scheduler,Memory,SkillForge,_search_health}.py` 等**：DataAnalysis 数据分析规范包 + 数据库子模块（只读 MySQL/SQLite/PostgreSQL/MongoDB 跨会话配置）+ Scheduler 4 层模块 + Memory `remember()`/`recall()`（**`code(..., local=True)`**）+ SkillForge `create_skill()`/`list_skills()`/`read_skill()`（**`code(..., local=True)`**）+ `_search_health.py` 三个搜索 skill GET ping 探活
- **`main.py` + `sandbox/Dockerfile`**：FastAPI 入口（lifespan 嵌套顺序 `chat_service → scheduler → cleanup`；`uvicorn.run(app, ...)` **传对象不传字符串**）+ 代码沙盒镜像（Python 3.12）


### 前端（精简）

- **`src/App.vue`**：全局状态 + SSE + `refreshPage()`；详细功能列表见 `frontend/README.md`
- **`src/components/`**：业务组件（ChatHeader / Sidebar / ConversationItem / MessageList / MessageItem / MessageInput / ScheduledTaskItem / CheckpointPanel / FilePreviewPanel / FilePreviewModal / DataAnalysisTree / DataTreeNode / TrashTreeNode / WebPreviewPanel / SettingsDialog / ConfirmDialog）
- **`src/utils/fileKind.js`** + **`App.vue` 的 `--ft-*` token**：文件树 / 回收站树**共用**的文件类型判定（`fileBadgeText` 三档：真实扩展名 → 共识短标 → 未知返回 `null` 画字形）。规则表与 token 都不许在这两棵树里各写一份——`TrashTreeNode` 曾自绘一套图标，已跟文件树走样（缺 docx / pdf / markdown）
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

`~/.claude/scheduled_tasks.json` 里持久化 cron job **每小时 :23 自动触发** ChatMe 后端优化 Agent（durable，跨 session 持续；**7 天后自动过期**需续期）。目的：扫思维链日志 + 自动修复 prompt / AI 配置问题。完整 prompt 见 cron job 本身；摘要：读 `thinking_chain-YYYY-MM-DD.log` 9 个 call site → 判定只看思维链 / 输出方向合不合适。**✅ 可自主改**：prompt 删冗段加 few-shot 锚定 / `_filter_thinking_content` regex / env 拆分 / `format_thinking_chain` max_chars / `PROMPT_MAIN_FLOW` 反冗余约束。**❌ 不做**：调 max_tokens / temperature / 大范围 prompt 重写 / 加新工具 / 节点 / 改 ReAct 流程 / 改 agent_node 路由决策 / 改前端 / Electron / 不主动 git commit；5+ 文件改动先列出来一次性不下。**管理**：`claude --cron-list` / `--cron-delete a09d41ec`；续期用 `CronCreate` 重建。

## AI 协作偏好

> 这些偏好从用户对话中沉淀，存于 `/Users/jx/.claude/projects/-Users-jx-coding-projects-ChatMe/memory/`。改前先读 `MEMORY.md` 看完整索引。

### 工程约定

1. **后端最小化 + 前端动态加载**：文件树 / 列表类接口后端只返扁平列表，前端构树 + 动态加载内容；path 须含 `cached/` 前缀。
2. **沙盒隐藏文件过滤**：`sandbox/sitecustomize.py` 过滤规则（`.` / `__` 挡、`_` 不挡）+ 只在挂载点根目录一层不递归子目录。
3. **沙盒 config 同步策略**：用中间文件隔离 skills key，仅在 MCP 启动 / 容器重建时重生成，不做运行时自动同步。
4. **流式响应滚动 UX**：入场 `easeInOut`；流式 ramp（慢→快）+ 100ms 打断防抖；用户 wheel / touch 立即让出控制权。
5. **MCP 工具参数 `local`（v0.1.3 反向命名）**：Python `local`（旧 `sandbox`/`use_sandbox`）在 MCP schema 里是 `local` 参数；过滤 / 判断要查实际 args key，兼容新旧两种。
6. **ReAct 流程压缩 4 阶段循环**：**后台异步 + 不阻塞工作流**——见上方「ReAct 流程压缩」章节；imp_ipt 是唯一 draft 切分锚点（`additional_kwargs.imp_ipt=True`）；后台任务 finally 块 pop 自己；result 为 None 时不写 pending。**Why（M3 filter 兜底）**：M3 看到 input `tool_calls` 字段 100% 模仿输出 `<tool_call>` / `[</tool_call>]` / `[<invoke name="cmd">][<command>...]` 等伪 tool_call 块。**关键顺序**：combined regex（`<tool_calls?>.*?\[?</?tool_calls?>\]?`）必须**先**跑，wrapper / 方括号 invoke 块拆成几条放后面兜底。**react_compact prompt 显式禁止 + Few-shot 锚定**：prompt 列出伪 tool_call 格式 + 1 个好例子 + 1 个反例 + 一行点错在哪。新增 M3 输出格式必须同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）。
7. **Memory 并发安全**：`MemoryManager` 内部维护 `_thread_locks[thread_id]`，`update_memory` / `delete_memory` / `backtrack_memory` / `delete_latest_backup_memory` 全部走 `async with self._get_thread_lock(thread_id)`；文件写入走 `_atomic_write_text`（写 `*.tmp` + `fsync` + `os.replace`）。
8. **ChatService 记忆任务串行**：每会话在 `_memory_update_tasks[session_id]` 里只保留一个 asyncio.Task，新任务通过 `asyncio.shield` 串接上一轮；新请求发起 / 删除会话 / 回溯 前会先 `_wait_previous_memory_update` 等待；SSE 暴露 `memory_wait_start` / `memory_wait_done` 事件。
9. **异步日志 + 思维链单开文件**：写文件走 `QueueHandler` + `QueueListener` 模式，业务线程不入 IO；`atexit` 统一 `listener.stop()` 清理。ChatWorkflow 各节点的 `format_thinking_chain(...)` 类思维链日志（9 处）**必须**走 `self.thinking_logger.info(...)`（`get_thinking_chain_logger()` 返回），写到独立文件 `thinking_chain-YYYY-MM-DD.log`，**严禁**写到主日志。
10. **节点异常统一兜底**：所有 LangGraph 节点（ChatWorkflow 5 个主节点 + 文件图 3 个节点）都打 `@node_guard("<name>")`：`except Exception` 捕获后 log + 包装 `RuntimeError` 让 SSE 外层统一返回 `error` 事件；但 `except GraphBubbleUp`（LangGraph 控制流异常的基类，涵盖 `GraphInterrupt` / `ParentCommand` 等）必须**原样 `raise`**。
11. **前端错误气泡保护**：App.vue 维护 `_sessionHadError: Set<session_id>`，SSE `error` 事件触发时把 `session_id` 标记为保护态；保护态下 `done` 事件不会覆盖错误气泡，`refreshConversation` / `updateTitleAndRefresh` 跳过 messages 重拉，只更新侧边栏。
12. **`cmd` / `code` 工具默认走沙盒（v0.1.3 反向命名 `local`）**：默认 `local=False`（**反向 default**：不传 = 沙盒隔离；要本机才显式 `local=True`），内部仍用 `use_sandbox = not local`。沙盒不可用降级到本机。**执行环境区分**：`interrupt()` payload 带 `execution_env` 字段透传到 SSE；前端 `MessageItem.vue` 容器挂 `tool-inline-approval--local` modifier class，**唯一视觉差异 = 淡红背景叠加** `rgba(239, 68, 68, 0.06)`。**`on_tool_start` 在 gate 3 内部发**（`langchain_core/tools/base.py` 的 `BaseTool.ainvoke`，不是 ToolNode 在 wrapper 前发）→ pre-check 拦截 / deny 时**不发**（预期内，没写文件），per-skill 预批准自动放行时走 gate 3 **照常发**——所以 WordEditor/ExcelEditor 走预批准时写作面板照常自动打开。
13. **SandboxPool 池锁必须包住整个 pop → exec → append 周期**：min=1, max=4, per_container_concurrency=8；N+1 并发下 pop 跑锁外会撞空池报 `No available containers`；**新加执行方法必须继承这个锁结构**（v2 用 `Condition.wait` 整个 while 循环包在 `with self._pool_lock:` 内，避免 `cannot wait on un-acquired lock`）。
14. **Electron `file://` 协议拦截必须透传 method/body/headers**：在 `app.whenReady()` 内注册；`/chat/*` 转发到后端时**必须**显式带 `method: request.method, headers: request.headers, ...(request.body && { body: request.body, duplex: 'half' })`，否则 POST `/chat/` 的 body 被丢、后端收到 GET 请求；SSE 流必须显式 `new Response(upstream.body, ...)` 透传 stream。
15. **Electron 图标必须放包外**：`nativeImage.createFromPath` 不读 asar 内文件；`build/` 通过 `package.json` 的 `extraResources` 复制到 `app/Contents/Resources/build/`（macOS）/ `app/resources/build/`（Win），运行时用 `process.resourcesPath` 取真实路径；`app.isPackaged` 三元判断 dev vs packaged 路径；`app.dock.setIcon` 和 `BrowserWindow.icon` 都必须是 PNG。
16. **Electron `protocol.handle` 静态文件必须白名单校验**：`resolvedPath = path.resolve(pathname)` 后必须检查 `startsWith(distDir + path.sep)`，否则 `403 Forbidden`；不写这一行的话渲染层一句 `fetch('/etc/passwd')` 就能读任意磁盘路径。
17. **Electron 输出目录用 `release/electron-builder`**：`directories.output` 不要设 `dist/electron-builder`，否则会和 Vite 的 `dist/` 撞目录，且会被 `files` 模式误打进 asar。
18. **可滚动侧栏/面板 CSS 约定**：① 数据全量入 DOM，禁止 `slice(0, N)` / `displayCount` 切片；② 侧栏 `height: 100vh; flex-shrink: 0; overflow: hidden`，外层不被内容撑大；③ 固定头部 `flex-shrink: 0` 锁尺寸；④ 滚动区用 `height: calc(100vh - X)` **不走** `flex: 1 + min-height: 0`；⑤ **`overflow-y: auto`**——浏览器默认；**禁止** `scroll` / `hidden`；⑥ 必须用 JS + `ResizeObserver` 监听 `scrollHeight > clientHeight + 1`，溢出挂 `.has-overflow` class；⑦ `@scroll="handleScroll"` 直接绑在 `.list`，mounted 用 `$nextTick` 等首次渲染完再 `checkOverflow()`。**CSS-only 没法做到"溢出时才显示滚动条"**——必须靠 JS + ResizeObserver。
19. **流式响应会话保存（per-session 快照 + 切走保留 in-progress）**：用户流式期间切走，原会话 SSE 增量不能丢；切回显示实时状态；侧栏闪烁小点；流式完成 `refreshSession` 不能影响当前会话视图。
    - **三件套**（`App.vue` data）：`_activeStreamingSessions` / `_streamingMessages`（**与 this.messages 同源引用**——SSE 改 this.messages 自动同步 snapshot，不深拷贝）/ `_streamingMeta`。
    - **sessionChanged 分支**：`this.currentSessionId !== requestSessionId` 时所有 content / reasoning / tool_call_* / done / error / interrupt 增量**只写到 snapshot**，不碰 this.messages。
    - **done / error / interrupt 必清三件套 + `refreshSession(sid)`**（只动侧栏）；**`requestSessionId` 必须在 SSE 循环开始前锁定**。
    - **Vue 2 Set 陷阱**：`.add` / `.delete` 不触发重渲染，必须 `new Set(...)` 整替换。
    - **`loadConversation` 双分支**：流式分支直接 `this.messages = snapshot` + `this.isLoading = true` + `startResponseTimer()`，**不调** `get_conversation`。
    - **`cleanupLoadingState` 不能 pop 流式 AI 消息**（同源引用 pop 会污染 snapshot）。
    - **新增流式 SSE 入口**（sendMessage / handleResume / handleRestream）必须按上述点对点实现；F5 恢复不在本约定范围——需要 `/chat/streaming_sessions` 接口 + 恢复 SSE 协议。
20. **静态文件 fallback（无 sid 才跨会话找 + Referer 推断 sid 优先）**：`APIRouter/static_file.py` `serve_cached_file` 精确路径命中失败时分流：**带 sid 路径**（dual regex 32+12 hex）找不到 → **直接 404**；**无 sid 路径**找不到 → 双层 fallback：先从 `Referer` header 正则提取 sid 作 `primary_sid`（32 位写前面，路径边界 `/[/?#]|$`），在 `cached/{primary_sid}/**` 下递归找；没命中再跨 `cached/*/` 所有 sid 找（按 `st_mtime` 最新返回）。**Why 只无 sid 才 fallback**：实际请求 URL 都带 sid，fallback 是少数兜底；带 sid fallback 会把"我自己 session 缺文件"变成"别人 session 同名图"。**Why Referer**：浏览器 `<img>` 加载 markdown 图片**不能**加自定义 header，EventSource 也不能；Referer 浏览器自动带。
21. **删除会话行内二次确认（小红叉状态机）**：`ConversationItem.vue` 维护 `isConfirmingDelete`：第一次点 × → `confirming` class 变红 `rgba(239,68,68,0.12)` 底常显；第二次点红 × → **立刻** `isConfirmingDelete = false` 再 `$emit('delete')`；点别处 / Esc 取消（`mounted` 绑 `document.click` + `keydown(Escape)`，`beforeUnmount` 解绑）。**App.vue `deleteConversation` finally** 必须清理三件套（`stopStreamTimer` + 三个 Map/Set delete + `new Set(...)` 触发响应式）+ 当前会话切换（关 SSE + `cleanupLoadingState()` + `createNewChat()`）。
22. **Electron 单窗口架构 + autoEnter 三态按钮**：单 BrowserWindow + 主界面永远在 DOM 里（`appReady=false` 时加 `.app-disabled` 灰显禁用），`<BootstrapView>` 浮窗叠加（fixed + z-index 1000 + backdrop-filter 模糊）。主进程 `let servicesReady = false`；bootstrap 完成后 `webContents.send('startup:services-ready-changed', { ready, autoEnterFrontend })` 推 object payload。warm / cold / warm-refresh 三条路径一律不闪 BootstrapView。**三态按钮**：`launching=true` → 「启动中...」disabled；`servicesReady=true && !autoEnterFrontend` → 「进入应用」emit `enter-app`；其他 → 「启动应用」（`!allOk` 时 disabled）。**避免双源真相**：`BootstrapView.servicesReady` 是 prop，不重复 invoke `getServicesReady`；所有 `appReady` 翻转都在 App.vue 一处。**重启路径**：`restartBackend()` 完成后 `setServicesReady(true, { autoEnterFrontend: true })` —— 用户已在 app 里，重启恢复直接交回交互权。
23. **LLM 懒加载 + 热切换（v0.3.x）**：用户改 `llm_providers`（api_key / base_url / model_name / active）后**无需重启后端**，下次调用自动用新配置。设计：
    - **`backend/ChatMe/ChatWorkflow/llm_factory.py`**：`WeakValueDictionary` 按 `(role, api_key_fp, base_url, model_name)` 缓存 `ChatOpenAI`；`get_llm("main")` cache miss → 自动 new，cache hit → 返回缓存实例（~0 耗时）。
    - **5 个工作流角色共享同一实例**：`llm_core / agent_llm_with_done / summary_llm / react_compact_llm / llm_imp_ipt` 都拿 `llm_factory.get_llm("main")`（连接三元组相同），VL 走 `get_llm("vl")`（独立 base_url / api_key / model_name，vl.local=False fallback 时与主模型 key 撞 → 复用同实例）。
    - **`ChatWorkflow/core.py`**：7 个 `self.xxx_llm = ChatOpenAI(**)` 改为 8 个 `@property` getter（每次访问重新组合 LCEL `prompt | llm.bind_tools(tools)`，~µs 级开销）；`init_llms` 只持有 prompts 不 new `ChatOpenAI`。
    - **`ChatMeConfig.save_config`** 加 `llm_factory.invalidate_for_providers()` hook（写之前抓旧快照 + 写后比对前后 key，主动 pop 旧 key → 旧实例失去强引用 → GC 释放 httpx 连接池）；`restart_required` 一律 False（v0.3.x 起所有段都热生效）。
    - **`ChatMeConfig.get_active_llm_config`** 加 `llm_providers.active` 字段优先级（最高 > self_check_llm 探测 > chain[0]），让用户在 SettingsDialog / SetupView 手动选主用 provider。
    - **新增路由**：`GET /admin/llm/models?provider=xxx`（后端 proxy 调 `{base_url}/v1/models`，**严格按远端返回**，不拼白名单；远端空就返空 + source='remote'/models=[], 失败返 source='error'/models=[]），`GET /admin/llm/cache-info`（调试用）。**Why 不拼白名单**：旧版拼了 `gpt-4o/deepseek-chat/Qwen` 等硬编码列表，用户不知情选了和 base_url 不匹配的模型 → 401。误导 > 兜底。
    - **前端 SettingsDialog / SetupView**：「⟳ 拉取模型列表」按钮填充 model 下拉框、provider group-title 加「设为当前生效」radio、顶部 active-bar 显示当前生效 provider + model。`buildPayload` 把 `activeProviderName` 单独 diff 写到 `payload.llm_providers.active`。
    - **vl.local 切换例外**：决定是否加载 Qwen3-VL 本地模型到内存，必须重启后端。SetupView.onFinish 的 `needsRestart` 只在 `vl.local` 变了才 emit('restart-requested')。


### 版本约定（按版本倒排）

> 每条只留「改了什么 + 为什么」，实现细节看 `git log` 和对应文件。

**v0.3.9**
- agent 工具调用原则从「省工具」改成「先正确」（Correct first / No redundant calls / Progress check / Switch strategy on failure）。**Why**：原措辞把 agent 推向为少调一次而跳过 `cat SKILL.md` / `ls` 验证，省下的是正确性；反滥用改成两条可判定的跳过条件
- 4-phase 第 4 步收尾改调 `done` 工具（原「reply with paths, then output `Done`」是「未采纳回复草稿」缺陷的根），并删掉依赖旧字面量的 `flow.replace`。**不提 final_node**：agent_node 没有下游节点概念，改成「回复会在你交完之后替你写好」
- 标题派生 + `updated_at` 都跳过 `imp_ipt`。**Why**：imp_ipt 是排在真实用户消息后面的 HumanMessage，两处都倒序找第一个就 break → 标题变成优化后文本的截断；`updated_at` 落到 `datetime.now()` 兜底 → **每次刷新侧边栏时间都跟着刷新时刻跳**，会话列表排序跟着抖。兜底一并换成 `created_at`
- 思考段 / 理解意图块 >5 行折叠，判据从 `scrollHeight > clientHeight` 改成 `round(scrollHeight / lineHeight) > 5`。**Why 原判据是死循环**：只在已加高度约束后成立，未 clamp 时两者恒等 → 永不触发
- 折叠宽度自适应改用 `ResizeObserver`（150ms 防抖）+ `window.resize` 兜底。**Why**：侧栏开合改列宽但不触发 resize
- `-webkit-box` 把子元素块级化，`.imp-ipt-label` 恒为块级，否则折叠/展开两态间徽章跳行
- 上传的 office 预览改走 `file_path`（`staticUrlFromFilePath`），并**委托 `onDataAnalysisFileClick`** 与文件树共用同一分流 → 两条路命中同一个 tab。**Why**：后端内联的 `data:` base64 撑不住 `?t=` 破缓存（`?` 之后全算 payload → `Failed to fetch`），原文 tab 保存也剥不出 sid。只对 office 收窄，图片走 OSS/blob 一直正常
- `openFilePreviewTab` 修死代码：回传响应式代理的 `return` 早退把「文本类 tab 立刻取内容」盖住了 → 文件树点 md 原文和渲染同时空白
- Esc 收起文件预览面板（走 `closeFilePreviewPanel()`，与 ✕ 同入口），同轮补 `ToolDocPreview` / `MessageInput` 两处 `stopPropagation`——已消费的按键别让下游再解释一遍

**v0.3.8**
- Word/Excel 实时预览回到**已有的** `FilePreviewPanel`（v0.3.7 内嵌进 `tool_call_item` → 100 段文档把思考面板撑爆，层级全乱），思考面板只留 `.tool-doc-indicator` 胶囊
- AIMessage / ToolMessage 层级改缩进阶梯（▸ 0 / └ 18 / ⎿ 36px，零新增边框）；`impIpt` 块改卡片式排版
- docx 改字保存图片不丢：前端 `[[图片 N]]` 占位 + 后端 `word_editor.replace` 按 N 搬回原位，**对不上直接 422**
- 撤回分「流式中先中断 / 非流式直接回溯」两分支；回溯 / 撤回 / 重新对话走 `sessionActionBusy` 互斥锁
- `find_skill` 中英混排查修（分词器无 CJK 分隔符 → `做成excel表` 整词、latin 丢弃 → ExcelEditor alias 永不命中还被挤掉）：分词加中英边界切分 + 新增 `_search_signature`（只留拉丁词 + bigram）专供别名层 `+6`。**Why**：静默错命中比 0 命中更坏——0 命中会提示切 `mode='list'`，错命中不会
- 思考段超 5 行自动折叠（CSS line-clamp + 实测 `scrollHeight/clientHeight` 判溢出，附「展开全部」按钮）；窗口缩放重量
- 写作面板：AI 调 WordEditor/ExcelEditor 时**自动打开**面板（面板关着才弹；开着且看的是另一份就不抢 active）+ 内容追加后**自动跟底**，用户在预览区滚过就停止跟底（滚回底部自动恢复）；文档路径**优先取 stdout 里的真实路径**，code 文本解析只负责更早弹面板（f-string 变量前缀 / `os.path.join` 都解不出来，解不出就退化成「末段文件名 + 当前 session」）
- `[[cached/x.docx]]` 这类不直接渲染的类型渲染成高亮可点的文件名链接（`.file-link`），点击开右侧文件预览面板；markdown `[名](path)` 写法同样处理
- 预批准 skill 补 Bocha / WebSearch（共 9 个 per-skill pattern，`_generate_default_config` 模板 + 本地 config 两处都要改；**不写 `sandbox=` 段** → sandbox / local 都命中）
- 文件树 / 回收站树文件类型徽章重做：18px 圆角方块印**真实扩展名**（`PDF` / `DOCX` / `PY`），字号按字符数分 4 档。**Why 不用抽象图形字形**：18px 下「文档轮廓 / 网格 / 地球」十几种全糊成同一坨，用户反馈「没有区分度」；印扩展名才跟 Windows / Finder 一致。图标 16→18px（行高预算够：min-height 24 + 上下 padding 3）
- 徽章配色**按对比度反解而非凭感觉调浅**：白字压在色块上，`ratio = 1.05 / (L + 0.05)`，16 个文字徽章在浅 / 深两套主题下全部 ≥3.3:1（实际最低 3.31:1）——这就是「再浅就看不见字」的上限。文件夹不压白字，不受此约束
- 无扩展名 / 后缀未注册（Makefile / LICENSE / `.foo`）画**文档页字形**而不是印 `FILE`：印 `FILE` 既没信息量、又跟别的文本徽章长得一样。为此把兜底 kind 从 `FILE_KIND_RULES` 里拆出来单独定义——混进去会让 `isKnownKind('doc')` 恒为 true，`FILE` 还是会被印出来
- **上游瞬时错误重试**：`node_guard` 判定 529 / 429 / 5xx / timeout 为瞬时错误后原地重试（`NODE_GUARD_MAX_RETRIES=5` × `NODE_GUARD_RETRY_DELAY=8s` 固定间隔）。**Why 收窄到错误类型**：KeyError / 配置缺失重试 5 遍只是把真 bug 变成 5 倍延迟；**Why 固定 8s 不指数退避**：529 是集群整体过载，秒级重连必然再撞同一堵墙，固定间隔让 5 次均匀覆盖约 40s 过载窗口；**Why `GraphBubbleUp` 绝不重试**：用户的「停」不能变成「再试五次」。耗尽抛 `TransientUpstreamError`（带 `attempts` / `max_attempts` / `node`），ChatService 塞进 SSE `error` payload
- 前端「上游静默读秒」：`stalledMs`（`_lastStreamActivity` 距上次任意 SSE 事件的时长）超阈值显示「上游繁忙，正在自动重试 · 已等待 Ns」，耗尽则显示「已自动重试 N/M 次仍失败」。**不新增 SSE 事件**——静默计时 + 复用现有 error payload 就够了，加 `retrying` 事件要动 5 个 dispatch 块 × 多分支
- 删 `should_end_node`（多一跳 LLM 判定该收尾）+ 废弃的 `sub_agent` 工具（`mcps/tools/deprecated.py` 整文件 311 行删除，`get_mcp_tools(include_done=)` 参数一并去掉）
- `PROMPT_MAIN_FLOW` 重写（-409 行）：Decision Flow 去掉编号和时序箭头（它是**分诊不是流程**，用户原话已沉淀为偏好 7/8）、工具用法下沉到 `platforms/base.py`、补 Word / Excel 输出格式示例
- 「未采纳回复草稿」不再污染 context：无 `tool_calls` 的 REASONING AIMessage（agent 决策层被要求「要么调工具要么调 `done`」时输出的草稿）一律不进 LLM 输入、也不留在 history。**Why 不留在 history**：F5 刷新会把它当思考文本渲染进折叠面板；**Why 必须在 final_node 删**：agent_node 里删会坏掉循环边界锚点和 `route_agent_output` 路由判据
- permission decision 白名单前置：`decide` 写 redis **之前**校验（`approve` / `deny` / `this-time-only` / `feedback` / `feedback:<text>`）。**Why**：写进去就等于给图挖坑——resume 必然 400，LangGraph 永久停在 `interrupt()`，用户既没待办可点也等不到 AI 推进。特意放行裸 `feedback`（文本为空的前端竞态），让它走 deny 兜底好过 400 掐死
- 传递依赖升为直接依赖（`pyproject.toml`）：`pymysql` / `psycopg` / `pymongo`（宿主降级路径要用跨库只读查询）+ `pypdf` / `pypdfium2`（原本是 docling / unstructured 的传递依赖，装在 venv 里但从未声明，上游哪天换掉 PDF 后端 `uv sync` 就直接卸载，而报错现场在 docling）。**⚠️ 不要换 PyMuPDF**：AGPL-3.0 会污染 Electron 分发
- Electron 健康检测语义收窄：5xx / 4xx 是「后端活着但业务出错」，不能当存活信号（否则纯业务错误弹「后端服务已断开连接」banner，且点「重新连接」也治不好）；失败计数重置必须写在状态早退**之前**，否则「连续 N 次失败」被悄悄降级成「累计第 N 次失败」，表现为 banner 闪一下又恢复
- `impIpt` 身份判定从 `is` 改为 `messages[i].id == imp_ipt.id`（LangGraph 反序列化后是等价不同对象）；`imp_ipt` / `final_node` 的 SSE 增量补 `source` 字段，前端据此区分「理解意图阶段」与「正式回复阶段」
- `/[xxx]` pill 改为**按命令清单校验**（`App.vue slashCommands` → `MessageList` → `MessageItem`），不在清单里就**原样保留文本、不 pill 化**；判定 case-insensitive，skill 未拉回（`skillsLoaded=false`）时不判定。**Why**：pill 是「这是个真命令」的承诺，拼错的 `/[Excle]` 跟 `/[WordEditor]` 长得一样等于替错误背书，用户以为命令生效了
- 输入框手打未知命令不再静默：`extractTypedSlashCommand` emit `unknown-slash-command` → toast 提示 + 列相近候选（同一前缀只提示一次）
- `lazyLibs.js` 的 mammoth 从 `mammoth/mammoth.browser.js` 改走包主入口 `mammoth`：Vite 客户端构建会应用 mammoth 的 `browser` 字段（`lib/unzip.js` → `browser/unzip.js` 真 ArrayBuffer 实现、`lib/docx/files.js` → 浏览器版），调用方仍传 `{ arrayBuffer }` 无需改。**Why**：深路径是伸手进别人包里的 browserify 预构建产物，路径随时会消失，且失败只在「那台机器 node_modules 没装全」时出现（Windows 打包就是这么断的），本地永远复现不了；换过去 chunk 还小 113KB（494→381）。17 个 mammoth fixture 实测 16 个输出逐字节一致，第 17 个 external-picture 是外链图片，两条路径都读不了（既有 browser 限制，非回归）

**v0.3.7**
- WordEditor 段内多 run 样式 `runs=[{text,...format_kwargs}]` + `add_markdown()`（自写零依赖 parser 在 `markdown.py`）
- typewriter race fix（`:is-streaming` 绑 `_isStreaming` 而非 `result === null`）——**v0.3.8 已把整条 typewriter 链路删掉**，内容增量刷新本身就是进度信号
- ChatHeader 4 个 SVG 统一 18×18 + 5 个 `--header-*` token；SKILL.md 精简（Word 215→133 / Excel 152→68）

**v0.3.5**
- 滚动行为重做：`ResizeObserver` 观察 `.messages-column` + rAF 函数式 `targetTop` 追底 + `lastSetTop` 方向无关打断检测 + `localStorage` 会话滚动位置缓存（TTL 30 天 / 最多 60 会话 / 底部自动跳过）
- `done` 工具 prompt 块（base 加 `done_tool_prompt_block`，新图 `get_agent_node_improved_prompt()` 单独 splice）

**v0.3.4**
- skill `func.help` 双轨 API（`_HelpMeta` 自动挂 `.help` + `auto_attach_help_module` 补 module-level）
- 思考段与工具调用配对：`toolCall.reasoningBefore` 存切片，`thinkingBlocks` 按长度累加切 `message.reasoning`，渲染成「思考段 → 它触发的工具」交替序列
- CC 风格面板重设计（thinking-section 只留 3px 左竖条 / tool 行去外框 / args 折叠为灰色 summary / 单 tool 粒度审批高亮）+ 6 个 theme token
- WordEditor / ExcelEditor 写作抽屉 + SKILL.md 精简

**v0.3.2**
- BootstrapView deps 模式「进入应用」按钮无效 bug 修复
- 移除 LLM 模型白名单兜底（`/admin/llm/models` 严格按远端返回，空就返空）

**v0.3.1**
- 首启 UX 重构：按 `autoEnterFrontend` 切 BootstrapView `classic` / `deps` 二形态 + App.vue 自动 bootstrap + StartupLoadingView 等待动画

**v0.3**
- upload 阶段产物不再软删，11:30 `daily_trash_cleanup` 统一物理清

**v0.2.4**
- 启动链路鲁棒性 + 重启遮罩 retry（bootstrapSession 取消令牌 / `_restartVersion` race 防护 / 单实例锁）

**v0.2.3** — 部署产物清理 + tar 打包 race 修复（改写 `/tmp/`）+ 末尾 `sync` 刷盘。

**v0.2.2**
- 搜索源健康探测（`_search_health.py` 并发 ping）/ SandboxPool 池锁修复（`Condition.wait` 包 `with self._pool_lock`）
- Redis 端口 6024 → 48211（避开 Hyper-V excludedportrange）；final_node SysMsg 改写双轨制

**v0.2.1**
- 配置向导 SetupView（独立组件，**不要混用 BootstrapView**）+ fixRedis ping-first 四段判定 + startBackend 端口预检
- Windows `file://` API 路径修复（`apiPathname = IS_WIN ? pathname.replace(/^\/[A-Za-z]:/, '') : pathname`）

**v0.2.0**
- 新默认图 `_create_graph_improved` 替代 `_create_graph_core2`（老图完整保留作回滚基线）+ MCP `done` 工具（仅新图暴露）
- `route_agent_output` 纯结构化路由 + agent no-tool-call retry（≤3 次英文 SysMsg）+ `RemoveMessage` 清理 done cycle + `compression_handled_this_round` 防重复压缩
- 消息排队 `/chat/{sid}/queue`（Redis FIFO ≤20 × 4000 字符，**不主动 drain**）+ 回溯走 `CheckpointJanitor.retarget_to()` 覆写 latest 指针

**v0.1.8**
- 文件树 Finder 化：长按框选（250ms / 移动 ≥8px 才进 box-select）+ HTML5 拖拽移动（Alt 切 copy/move）+ 焦点目录 `focusDir` + 树底 `+文件夹/+文件` 按钮 + OS 系统拖拽 overlay

**v0.1.7** — 文件树行内删除 + 软删除 `.trash/{sid}/{ts}_{rel}` + 11:30 兜底物理清 + 标题自动派生（`PUT /chat/{sid}/title`）。

**v0.1.6**
- matplotlib 中文字体随 skill 自动 mount（`NotoSansSC-Regular.otf` 移到 `skills/_shared/fonts/`，`get_fonts_setup_header()` 扫 4 路径按序去重；`cached/.fonts/` 保留兼容老部署）
- ⚠️ 该 `.otf` 是 CFF/PostScript 轮廓，matplotlib 正常，**reportlab 只认 TrueType(glyf) 轮廓**，嵌 PDF 前须先转 TTF

**v0.1.5**
- Memory 4 变体（`facts/preference × thread/global`）/ SkillForge（`create_skill/list_skills/read_skill` 写入必须 `code(..., local=True)`）/ Scheduler 4 层模块 / CheckpointJanitor 拆两层
- SKILL.md frontmatter YAML（`name/description/aliases/mount/module/lazy`）+ registry mtime 自动重扫 + `build_mount_args()` `@lru_cache(maxsize=1)`
- `/admin/config` segment 级热加载 + `ChatMeConfig._load()` mtime

**v0.1.4**
- `mcps/` 三包重构（permissions / sandbox / tools，`__init__.py` 只写说明不 re-export）
- 启动 lifespan 嵌套顺序 `chat_service → scheduler → cleanup`；`uvicorn.run(app, ...)` **传对象不传字符串**
- MAIN_FLOW 只讲「怎么想」，工具用法下沉 `platforms/base.py` 的 `<tool>_tool_prompt_block`

**v0.1.3**
- `cmd` / `code` 默认走沙盒（`local=False`，反向命名）；审批 payload 带 `execution_env`，前端唯一视觉差异 = 淡红底
- **Pre-check 拦截 SSE 兜底**：pre-check 直接 `return ToolMessage` 不调 `execute()`，LangGraph 不发 `on_tool_*` → 前端必须靠 `on_chain_end` 兜底补 `tool_call_name` / `tool_call_result`，per-stream `emitted_tool_call_ids` 去重

**v0.1.2** — 跨 SSE 临时 metrics 累加器（每 round 独立 `round_metrics:{sid}` Redis hash，**不**写正式 checkpoints；`delete_conversation` 必须 `DEL`）。

**v0.1.1**
- `PermissionedToolNode` + LangGraph `interrupt()` 审批（`_awrap_tool_call` 是 `ToolNode` 官方扩展点，自己 try/except 拦截会被 runtime 忽略）
- 4 档决策（`approve` / `this-time-only` / `deny` / `feedback:<text>`）+ Redis `permission:{sid}` hash 跨 SSE 流复用 + `code_fingerprint` = SHA1(`imports + calls + lang + sandbox`)
- 多平台 prompt adapter（`platforms/` 抽 `cmd`/`code`/`ctime` 的 shell 差异）；session_id 兼容 32 + 12 位 hex（dual regex）

**DataAnalysis 数据库分析**：MySQL / SQLite / PostgreSQL / MongoDB 4 引擎只读，写操作一律拦截（见 `skills/DataAnalysis/database/`）。DB 配置写 `.runtime/`；LLM 只看 alias / engine / host / database 非敏感字段；`need_db_credentials` 中断沿用 SSE `interrupt` 通道。

**导出端点**：`/chat/{sid}/export/artifacts?format=zip|html` + `/chat/{sid}/export/turn/{checkpoint_id}`（见 `APIRouter/data_export.py`）。

### 代码 / 提交风格

- 提交信息遵循仓库现有风格：`v0.X.Y <说明>`（参考 `git log`）
- 不要引入为假设需求而设计的抽象 / 配置项 / fallback
- 系统边界（用户输入、外部 API）才做校验；内部代码信任框架保证
- 修改代码前先读相关文件，不读不写

### 工作流修改注意点

1. 5 个 LLM（`llm_core` / `agent_llm_with_done` / `summary_llm` / `react_compact_llm` / `llm_imp_ipt`）全部用 `MessagesPlaceholder("messages")`，不要回到字符串 `{messages}` 占位（会导致 SystemMessage 被 `str()`）
2. 后端 `_filter_thinking_content` 过滤 `<thinking>` 等思考标签，前端再二次过滤
3. VL 模型只处理图片（`file_process_node` 已跳过非图片文件）
4. `execute_code` 工具默认 `local=False`（v0.1.3 反向命名：MCP schema 里看到的是 `local` 参数，False = 沙盒）
5. **`imp_ipt` 是 draft 切分锚点**：`input_parse_node` 输出的 `imp_ipt` 唯一身份是 `additional_kwargs.imp_ipt == True`；ReAct 压缩 / final_node 注入 / 后续扩展都靠这个标志定位本轮意图
6. **final_node 不再走 `MessagesPlaceholder`**：imp_ipt 走 `_final_system_template.format(imp_ipt=...)` 注入到 system prompt 独占最高注意力位；context 中要先把 `imp_ipt` pop 出去再喂给 `llm_core`，避免重复注入
7. **ReAct 压缩失败不要 raise**：`_try_compact_react` 一律返回 `None`
   7.1. **`_filter_thinking_content` 是 MiniMax-M3 输出的兜底主力**：filter 必须能吃掉 `[</tool_call>]` / `[<]tool_call[>]` / `[<invoke name="cmd">][<command>...</command>]` 等方括号包装的伪 tool_call 块。**关键顺序**：combined regex（`<tool_calls?>.*?\[?</?tool_calls?>\]?`）必须**先**跑；wrapper / 方括号 invoke 块拆成几条放后面兜底。否则 wrapper 先剥 → 留下 78 字符半截垃圾。新增 M3 输出格式时必须同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）。
   7.2. **`_try_compact_react` 必须调用 filter**：input 已经 `_build_clean_compact_input` 清空 AIMessage.content 但保留 `tool_calls` 字段（API 强校验需要），LLM 仍会模仿输出 `<tool_call>` 块。**根因**：M3 与 agent_llm 共用同一个 weights，看到 input 里的 `tool_calls` 字段会模仿输出 tool_call 块。filter 是所有调用 M3 的节点（agent_node / final_node / imp_ipt / `_try_compact_react`）的兜底。
   7.3. **react_compact prompt 显式禁止 tool_call + Few-shot 锚定**：prompt 的"禁止"段必须包含伪 tool_call 格式；同时配 1 个好例子 + 1 个反例 + 一行点错在哪。
8. **Memory 操作加锁 + 串行**：见偏好 7 / 8
9. **节点异常统一打 `@node_guard`**：见偏好 10
10. **前端错误气泡不被覆盖**：见偏好 11
11. **SandboxPool 池锁**：见偏好 13
12. **Electron `protocol.handle` 注册时机 + 路径双形态**：见偏好 14 / 15
