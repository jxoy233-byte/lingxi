# ChatMe（灵析）AI 协作指南

> 完整项目说明见 [`README.md`](README.md)。本文档给 AI 协作者阅读：项目怎么组织、关键路径在哪、AI 协作的偏好与约定。

## 项目概述

ChatMe（产品名「灵析」Lingxi）是一个基于 LangGraph 的多智能体数据分析对话系统。后端 FastAPI + LangGraph + Docker 沙盒，前端 Vue 3 + Vite + Electron 桌面端。Redis 做 checkpoint + state saver，OSS 做文件存储。

## 技术栈

### 后端

- **框架**: FastAPI + LangGraph + LangChain；**MCP**: FastMCP 3.x；**包管理**: uv
- **状态**: Redis (checkpointer + state saver)；**沙盒**: Docker 容器池（`ChatWorkflow/mcps/sandbox/pool.py` 的 `SandboxPool`，min=1, max=4）
- **解析**: docling + qwen-vl-utils + unstructured；**对象存储**: oss2
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
│   ├── LoggingManager/        # QueueHandler 异步日志
│   └── test/
├── skills/                    # Bocha / Exa / Tavily / ImageParser / DataAnalysis (含 fonts/) / Scheduler / Memory / SkillForge / _search_health.py
├── .chatme/                   # 局部配置
├── pyproject.toml
└── main.py                    # FastAPI 入口，lifespan: chat_service → scheduler → cleanup

frontend/                     # Vue 3 + Electron 桌面端（main.js / preload.js / vite.config.js + src/components/）
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

- **`input_parse_node`**：输入预处理、文件解析（docling / OSS / VL）、`improve_input`；给 `imp_ipt` 标记 `additional_kwargs.imp_ipt=True`
- **`context_assembly_node`**：上下文组装（imp_ipt / memory / 当前轮循环消息）+ **ReAct 压缩**（4 阶段循环后台异步）+ **done cycle 检测 + RemoveMessage 清理**（v0.2.0 新图）+ 中断检查
- **`agent_node`**：**v0.2.0 新图**——AI 决策（调工具 / 调 `done` 收尾 / 无 tool_calls 走英文 SysMsg 重试 ≤ 3 次后强制 final_node）；**老图**——`should_end_node` LLM 决策节点。工具调用超过 50 次注入 SystemMessage 提示停止
- **`tool_execution_node`**：`PermissionedToolNode`（继承 LangGraph `ToolNode` + `_awrap_tool_call` hook），执行搜索 / MCP / Docker 沙盒 / **`done` 工具**（新图）；`cmd` / `code` 走 `interrupt()` 弹审批，Redis `permission:{sid}` hash 跨 SSE 流复用决策
- **`final_node`**：最终回复生成（独立于 agent 的 LLM），用 **dynamic system prompt** 把 `imp_ipt` 注入 system 层（不参与 messages 序列），输出带 SUMMARY 标记

State 定义在 [`backend/ChatMe/ChatWorkflow/config/models.py`](backend/ChatMe/ChatWorkflow/config/models.py)（`ChatStateCore2` / `FileParseState`），用 LangGraph TypedDict + `add_messages` reducer。

### ReAct 流程压缩（4 阶段循环 + 后台异步，不阻塞工作流）

`context_assembly_node` 每轮 cool-down 触发（默认 `(tool_call_times - last_compact_at) >= 5` 轮 + 最近 5 轮 chars ≥ 10000 + 无 pending + ≥1 完整 loop）→ `asyncio.create_task` 启动 `_background_compact_react`（**不 await**），result 写 `_background_compaction_results[thread_id]`，`pending_compaction_replace_at = len(_find_complete_tool_loops) + REACT_KEEP_LOOPS(2)`（v0.2.0 起改用完整 loop 数，**Why**：并行工具让 +2 不稳定）→ agent 推进 2 个完整 loop → `len(current_complete_loops) >= replace_at` 时调 `_build_compaction_draft` 重组 context = `[memory + imp_ipt] + [ReAct 摘要 SystemMessage] + [最近 2 轮原文]`，清 pending → 回到阶段 1 循环。

关键约束（详见偏好 7）：

- **压缩范围**：除最近 2 轮外所有 loop；imp_ipt 之前整体保留；产物 SystemMessage 形式插入 imp_ipt 之后
- **输入净化**：清空 AIMessage.content 但**保留 `tool_calls`**（API 强校验）
- **失败兜底**：长度 [250, 4096] 区间外 / filter 清不干净 / LLM 异常一律 `return None`（下限 250 = "有效压缩"最低门槛）
- **专用 LLM**：`get_react_compact_config()`，temp=0.3 / max_tokens=4096（env 可覆盖）
- **辅助方法**（`core.py`）：`_content_chars` / `_should_detect_compact` / `_find_imp_ipt_idx` / `_find_complete_tool_loops` / `_build_compaction_draft` / `_build_clean_compact_input` / `_try_compact_react` / `_background_compact_react`；**全程靠 content 特征扫描定位，不写死下标**
- **后台任务管理**：`ChatWorkflow.__init__` 维护 `_background_compaction_tasks` + `_background_compaction_results` per-thread；任务 finally 块 pop 自己避免引用泄漏
- **v0.2.0 防重复压缩**：`compression_handled_this_round` bool 标记防同一轮 iteration 2+ 重复压缩；`is_done_cycle=True` 时整段 ReAct 压缩跳过

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

- **`App.vue`**：全局状态 + SSE + `_sessionHadError` 错误气泡保护 + 四套 Set（`_activeStreamingSessions` / `_approvalPendingSessions` / `_completedSessions` / `_errorSessions`，独立非 union）驱动侧栏状态点 + `_pendingQueue` / `_queueDrainDeferred` 消息排队 + `scheduledTasksMap` 定时任务缓存 + `refreshPage()`
- **`Sidebar.vue` / `ConversationItem.vue`**：全量入 DOM + 自定义 webkit 滚动条 + 删除会话行内二次确认（偏好 21）+ 底部内嵌 ⏰ 触发按钮 + 展开任务列表（`lingxi.scheduledTasksExpanded` localStorage 持久化，max-height 110px）+ 四色状态圆点（streaming 蓝闪 / approval 黄脉冲 / errored 红常 / completed 绿常）
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

- **多环境支持**：`NODE_ENV` 严格切换 dev/test/prod（不再受 `!app.isPackaged` 拖累，否则 `electron .` 永远走 dev）
- **`file://` 协议拦截**：`protocol.handle('file', ...)` 在 `app.whenReady()` 内注册（必须在 createWindow 之前）；`/chat/*` + `/static/*` 走 `net.fetch` 转发到后端，其他走白名单校验后从 asar 内 `dist/` 读盘
- **API 转发三件套**：method / headers / body 必须显式透传 + `duplex: 'half'`（POST body 否则被丢）；SSE 流必须显式 `new Response(upstream.body, ...)` 重建 stream
- **静态文件白名单**：`resolvedPath` 必须在 `distDir + path.sep` 之下，否则 403；hashed assets 永久缓存，index.html 不缓存
- **图标必须放包外**：`nativeImage` 不读 asar 内文件，`build/` 通过 `extraResources` 复制到 `app/Contents/Resources/build/`（macOS）/ `app/resources/build/`（Win）/ `app/build/`（Linux），运行时用 `process.resourcesPath` 取；`app.dock.setIcon` / `BrowserWindow.icon` 都必须是 PNG（传 `.icns` 会得空 image）
- **安全策略**：生产环境禁用 DevTools / 右键菜单 / 危险快捷键；外部链接走 `shell.openExternal`
- **单窗口架构 + autoEnter 三态按钮**：详见偏好 22 / 23

## 关键文件

> 完整职责清单见 `README.md`；本文件只列**AI 协作最常碰到的关键路径**：

### 后端（按调用频次倒排）

- **`ChatWorkflow/core.py`**：5 节点逻辑 + 5 个 LLM 实例（`MessagesPlaceholder`）+ ReAct 压缩 + final_node 动态 system prompt
- **`ChatService/core.py`**：SSE 流式（`message_stream` / `resume_permission_stream` / `invoke_interrupted_stream` 同构）+ `_memory_update_tasks` 串行队列 + `memory_wait_*` 事件 + 回溯走 `CheckpointJanitor.retarget_to()`
- **`ChatWorkflow/mcps/sandbox/pool.py`**：Docker 容器池 `SandboxPool`（v2 K 容器 × N 并发，池锁必须包住整段 pop→exec→append，偏好 14）
- **`ChatWorkflow/mcps/permissions/core.py`**：`PermissionedToolNode` + Redis `permission:{sid}` hash + 4 档决策（approve / this-time-only / deny / feedback:）+ `code_fingerprint` 永久批准
- **`ChatWorkflow/mcps/tools/platforms/`**：多平台 prompt adapter（`base.py` 抽象 + `darwin.py`/`linux.py`/`windows.py` + `registry.py` 按 `platform.system()` 选）；shell 风格差异都走这里，不要在 prompt 硬编码 uname
- **`ChatWorkflow/mcps/server.py` + `session.py`**：FastMCP 工具入口 + stdio 长生命周期子进程 + `ClientSession` 常驻复用
- **`ChatWorkflow/skills/registry.py`**：`SkillRegistry` + SKILL.md frontmatter + `_maybe_rescan()` 按每个 SKILL.md `stat()` mtime 检测（macOS APFS 不更新父目录 mtime）+ `build_mount_args()` 加 `@functools.lru_cache(maxsize=1)`，`reset_skill_registry()` 时必须 `cache_clear()`
- **`ChatWorkflow/Memory/core.py`**：per-thread `asyncio.Lock` + 临时文件原子写（`fsync` + `os.replace`）
- **`ChatWorkflow/decorators.py`**：`@node_guard` 装饰器，`except GraphBubbleUp` 必须原样 raise
- **`ChatWorkflow/CheckpointJanitor.py`**：业务层 LangGraph checkpoint prune + `retarget_to()` 覆写 latest 指针
- **`APIRouter/checkpoint_janitor.py`**：HTTP 层唯一路由 `POST /admin/checkpoints/prune`
- **`ChatWorkflow/config/graph_config.py`**：prompts + `get_react_compact_config()`；`PROMPT_MAIN_FLOW` 只讲决策流，工具用法下沉到 `platforms/base.py`
- **`ChatWorkflow/config/models.py`**：`ChatStateCore2` / `FileParseState` TypedDict + `add_messages` reducer
- **`ChatMeConfig/core.py`**：`_load()` mtime + `force_reload()` + `save_config()` 原子写 + 按段决定 `restart_required`（permissions/skills 立即生效；llm_providers 需重启）+ `vl.local=false` 时 `_resolve_vl_fallback()` 无条件用主用 LLM 三元组
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
- **`skills/_search_health.py`**（v0.2.1+）：三个搜索 skill（Bocha / Exa / Tavily）的 GET ping 探活；3s timeout；`ThreadPoolExecutor` 并发跑（最坏延迟 = max，非 sum）；4xx 算 alive（端点响应），5xx + `RequestException` = 不可用；`format_others_available(failed)` 追加错误信息末尾显示其余源可用状态
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

- **硬约束**：MCP 单调用 ≤280s；单 batch ≤12 轮；IAB 同会话 22+ 轮 R2 后必然 timeout（分多 batch 重开会话）
- **首选 Codex IAB**（`mcp__node_repl__js` 调 Playwright API）；备选本地 Chrome + CDP（`--remote-debugging-port=9222`）
- **5 个必踩陷阱**：① IAB 22+ 轮卡死 ② send-btn 延迟（`waitForTimeout(500)` + `click({force:true})` 跳 disabled）③ URL 漂移（`/` → `/<hash>` 正常）④ 完成判定看 AI 文本稳定 1.5-2.5s ⑤ MCP 边界丢 Vue 状态（每 batch `getTab()` + `evaluate()` 重读）
- **已确认真实后端缺陷**：① 跨多轮记忆上限 19+ 轮 R12/R17 失败 ② `POST /chat/improve_input` 返与原文相同的 `improved_text` ③ 复杂业务题（T08 类）触发 20+ 分钟无限工具调用循环 ④ IAB 路由状态不稳

### 定时优化 Agent（cron job `a09d41ec`）

`~/.claude/scheduled_tasks.json` 里持久化 cron job **每小时 :23 自动触发** ChatMe 后端优化 Agent（durable，跨 session 持续；**7 天后自动过期**需续期）。目的：扫思维链日志 + 自动修复 prompt / AI 配置问题。

行为摘要（完整 prompt 见 cron job 本身）：

- 读 `.chatme/logs/thinking_chain-YYYY-MM-DD.log`（偏好 10 提到的独立思维链日志），扫 9 个 call site（`imp_ipt` / `react_context` / `react_context_after_compact` / `agent_node_in/out` / `should_end_in/decision` / `final_node_in_context/out`）
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
5. **MCP 工具参数 `local`（v0.1.3 反向命名）**：Python `local`（旧 `sandbox`/`use_sandbox`）在 MCP schema 里是 `local` 参数；过滤 / 判断要查实际 args key，兼容新旧两种。
6. **`should_end_node` 设计偏好**：LLM 决策节点的单条喂入 / 完整写回、低频字面量子串匹配、独立 `max_tokens` env、prompt / 解析兜底一致。
7. **ReAct 流程压缩 4 阶段循环**：**后台异步 + 不阻塞工作流**——见上方「ReAct 流程压缩」章节；imp_ipt 是唯一 draft 切分锚点（`additional_kwargs.imp_ipt=True`），全程不写死下标；后台任务 finally 块 pop 自己；result 为 None 时不写 pending。**Why（MiniMax-M3 filter 兜底）**：M3 看到 input `tool_calls` 字段 100% 模仿输出 `<tool_call>` / `[</tool_call>]` / `[<invoke name="cmd">][<command>...]` 等伪 tool_call 块。**关键顺序**：combined regex（`<tool_calls?>.*?\[?</?tool_calls?>\]?`）必须**先**跑，wrapper / 方括号 invoke 块拆成几条放后面做兜底（否则 wrapper 先剥 → 留下 78 字符半截垃圾）。**react_compact prompt 显式禁止 + Few-shot 锚定**：prompt 列出伪 tool_call 格式 + 1 个好例子 + 1 个反例 + 一行点错在哪（few-shot 比单纯禁止清单强得多）。新增 M3 输出格式必须同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）。
8. **Memory 并发安全**：`MemoryManager` 内部维护 `_thread_locks[thread_id]`，`update_memory` / `delete_memory` / `backtrack_memory` / `delete_latest_backup_memory` 全部走 `async with self._get_thread_lock(thread_id)`；文件写入走 `_atomic_write_text`（写 `*.tmp` + `fsync` + `os.replace`）。
9. **ChatService 记忆任务串行**：每会话在 `_memory_update_tasks[session_id]` 里只保留一个 asyncio.Task，新任务通过 `asyncio.shield` 串接上一轮；新请求发起 / 删除会话 / 回溯 前会先 `_wait_previous_memory_update` 等待；SSE 暴露 `memory_wait_start` / `memory_wait_done` 事件，`interrupt` / `done` 事件携带 `memory_status` 字段。
10. **异步日志 + 思维链单开文件**：写文件走 `QueueHandler` + `QueueListener` 模式，业务线程不入 IO；`atexit` 统一 `listener.stop()` 清理。ChatWorkflow 各节点的 `format_thinking_chain(...)` 类思维链日志（`imp_ipt` / `react_context` / `react_context_after_compact` / `agent_node_in/out` / `should_end_in/decision` / `final_node_in_context/out` 共 9 处）**必须**走 `self.thinking_logger.info(...)`（`get_thinking_chain_logger()` 返回），写到独立文件 `thinking_chain-YYYY-MM-DD.log`，**严禁**写到主日志 `YYYY-MM-DD.log`；目的是让 LLM 决策链日志与业务日志按文件维度隔离，回溯时不被工具调用 / Redis / 文件 IO 等噪声淹没。新增节点若要加思维链日志，沿用 `thinking_logger`。
11. **节点异常统一兜底**：所有 LangGraph 节点（ChatWorkflow 5 个主节点 + 文件图 3 个节点 + sub_agent agent_node）都打 `@node_guard("<name>")`：`except Exception` 捕获后 log + 包装 `RuntimeError` 让 SSE 外层统一返回 `error` 事件；但 `except GraphBubbleUp`（LangGraph 控制流异常的基类，涵盖 `GraphInterrupt` / `ParentCommand` 等）必须**原样 `raise`**，不能包装 —— `interrupt()` 主动中断、`Command` 透传都依赖该异常穿透各层到达 runtime。新加节点必须继承这个分层约定。
12. **前端错误气泡保护**：App.vue 维护 `_sessionHadError: Set<session_id>`，SSE `error` 事件触发时把 `session_id` 标记为保护态；保护态下 `done` 事件不会覆盖错误气泡，`refreshConversation` / `updateTitleAndRefresh` 跳过 messages 重拉，只更新侧边栏；用户主动发起新一轮请求或续接时清掉保护态。
13. **`cmd` / `code` 工具默认走沙盒（v0.1.3 反向命名 `local`）**：`server.py` 的 `cmd` / `code` 都默认 `local=False`（**反向 default**：不传 = 沙盒隔离；要本机才显式 `local=True`），内部仍用 `use_sandbox = not local` 变量走原逻辑。沙盒不可用降级到本机（`cmd` → 本机 subprocess.run，`code` → 本机 venv）；白名单 + 危险检测 + 脚本检测在沙盒 / 本机两边都做。**执行环境区分**：`interrupt()` payload 带 `execution_env` 字段透传到 SSE；前端 `MessageItem.vue` 容器挂 `tool-inline-approval--local` modifier class，**唯一视觉差异 = 淡红背景叠加** `rgba(239, 68, 68, 0.06)`。
14. **SandboxPool 池锁必须包住整个 pop → exec → append 周期**：min=1, max=4, per_container_concurrency=8；N+1 并发下 pop 跑锁外会撞空池报 `No available containers`；**新加执行方法必须继承这个锁结构**。see `ChatWorkflow/mcps/sandbox/pool.py:_acquire (L244-303)`（v2 用 `Condition.wait` 整个 while 循环包在 `with self._pool_lock:` 内，避免 `cannot wait on un-acquired lock`）+ `_create_container (L182-187)`（曾误写 `os.time()` → AttributeError → silent 0-pool，修复为 `sha1(pid + time + counter)`）。
15. **Electron `file://` 协议拦截必须透传 method/body/headers**：`protocol.handle('file', ...)` 在 `app.whenReady()` 内注册；`/chat/*` 转发到后端时**必须**显式带 `method: request.method, headers: request.headers, ...(request.body && { body: request.body, duplex: 'half' })`，否则 POST `/chat/` 的 body 被丢、后端收到 GET 请求、SSE 流式响应直接退化成一次性；SSE 流必须显式 `new Response(upstream.body, { status, statusText, headers })` 透传 stream，避免 `protocol.handle` 把 stream 当 buffer 处理
16. **Electron 图标必须放包外**：`nativeImage.createFromPath` 不读 asar 内文件；`build/` 通过 `package.json` 的 `extraResources` 复制到 `app/Contents/Resources/build/`（macOS）/ `app/resources/build/`（Win）/ `app/build/`（Linux），运行时用 `process.resourcesPath` 取真实路径；`app.isPackaged` 三元判断 dev vs packaged 路径；`app.dock.setIcon` 和 `BrowserWindow.icon` 都必须是 PNG，传 `.icns` 会得空 image 并 Promise reject
17. **Electron `protocol.handle` 静态文件必须白名单校验**：`resolvedPath = path.resolve(pathname)` 后必须检查 `startsWith(distDir + path.sep)`，否则 `403 Forbidden`；不写这一行的话渲染层一句 `fetch('/etc/passwd')` 就能读任意磁盘路径
18. **Electron 输出目录用 `release/electron-builder`**：`directories.output` 不要设 `dist/electron-builder`，否则会和 Vite 的 `dist/` 撞目录，且会被 `files` 模式误打进 asar；当前 `output: "release/electron-builder"` + `files: ["dist/**", "electron/**", "vite.config.js", "package.json"]` 是白名单显式列出，asar 体积 5.6MB。
19. **可滚动侧栏/面板 CSS 约定**：所有可滚动列表（Sidebar / DataAnalysisTree / WebPreviewPanel / CheckpointPanel 等）必须按 7 条点写：① 数据全量入 DOM，禁止 `slice(0, N)` / `displayCount` 切片；② 侧栏 `height: 100vh; flex-shrink: 0; overflow: hidden`，外层不被内容撑大；③ 固定头部 `flex-shrink: 0` 锁尺寸；④ 滚动区用 `height: calc(100vh - X)` **不走** `flex: 1 + min-height: 0`；⑤ **`overflow-y: auto`**——浏览器默认；**禁止** `scroll`（始终预留轨道）、`hidden`（感知不到还有内容）；⑥ **CSS-only 没法做到「溢出时才显示滚动条」**：必须用 JS + `ResizeObserver` 监听 `scrollHeight > clientHeight + 1`，溢出挂 `.has-overflow` class；⑦ `@scroll="handleScroll"` 直接绑在 `.list`，mounted 用 `$nextTick` 等首次渲染完再 `checkOverflow()`。
20. **流式响应会话保存（per-session 快照 + 切走保留 in-progress）**：用户流式期间切到别的会话，原会话的 SSE 增量不能丢；切回时显示该会话的实时 in-progress 状态；侧栏该会话处显示闪烁小点；流式完成所触发的 `refreshSession` 不能影响用户当前所在会话的视图。**实现要点**（每条都不可漏）：
- **三件套**（`App.vue` data）：`_activeStreamingSessions: Set` / `_streamingMessages: Map<sid, messages[]>`（**与 this.messages 同源引用**——SSE 改 this.messages 自动同步 snapshot，不深拷贝）/ `_streamingMeta: Map<sid, {aiIndex, responseStartTime, ...}>`。
- **SSE 循环 `sessionChanged` 分支**：`this.currentSessionId !== requestSessionId` 时所有 content / reasoning / tool_call_* / done / error / interrupt 事件增量**只写到 snapshot**（`snap[meta.aiIndex] = {...}`），不碰 this.messages；非切走分支维持 `this.messages[aiIndex] = {...}`（引用同源自动同步）。
- **每个 done / error / interrupt 必清三件套**（不管分支）：`delete` 三个 Map/Set + `await refreshSession(sid)`（**只动侧栏，不动 this.messages**）；**`requestSessionId` 必须在 SSE 循环开始前锁定**（`const requestSessionId = this.currentSessionId`，handleResume / handleRestream 易漏）。
- **Vue 2 Set 响应式陷阱**：`.add` / `.delete` 不触发子组件重渲染，必须整 Set 替换：`this._activeStreamingSessions = new Set(this._activeStreamingSessions)`。
- **`loadConversation` 双分支**：流式分支直接 `this.messages = snapshot` + `this.isLoading = true` + `this.startResponseTimer()`，**不调** `get_conversation`；非流式走原 `get_conversation`。
- **`cleanupLoadingState` 绝不能 pop 流式 AI 消息**（snapshot 与 this.messages 同源，pop 会污染 snapshot）；**`startResponseTimer` 不要写 this.messages**（切走后 this.messages 是别的会话数组）。
- **右键 refresh 保护**：流式中会话不能调 `get_conversation` 重拉 messages，只调 `refreshSession` 刷侧栏。**删除会话清理**：`confirmDelete` finally 块也清三件套。
- **侧栏小点**：`ConversationItem` 加 `isStreaming: Boolean` prop；title 前置 8×8 圆点 + `@keyframes blink` 1.2s 循环；Sidebar 下发 `:is-streaming="activeStreamingSessions.has(conv.session_id)"`。
- **新增流式 SSE 入口**（sendMessage / handleResume / handleRestream）必须按上述点对点实现；F5 恢复不在本约定范围——需要后端 `/chat/streaming_sessions` 接口 + 恢复 SSE 协议。
21. **静态文件 fallback（无 sid 才跨会话找 + Referer 推断 sid 优先）**：`APIRouter/static_file.py` `serve_cached_file` 精确路径命中失败时分流：**带 sid 路径**（dual regex 32+12 hex）找不到 → **直接 404**；**无 sid 路径**找不到 → 双层 fallback：先从 `Referer` header 正则提取 sid 作 `primary_sid`（32 位写前面，路径边界 `/[/?#]|$`），在 `cached/{primary_sid}/**` 下递归找；没命中再跨 `cached/*/` 所有 sid 找（按 `st_mtime` 最新返回）。
    - **为什么只无 sid 才 fallback**：实际请求 URL（前端 markdown 图片、Electron 转发、Vite proxy）都带 sid，fallback 是少数兜底路径；带 sid 还 fallback 会把"我自己 session 缺文件"悄悄变成"别人 session 同名图"。
    - **为什么用 Referer 推断 primary_sid**：浏览器 `<img>` 加载 markdown 图片（fallback 主要场景）**不能**加自定义 header（浏览器规范），EventSource 也不能；Referer 浏览器自动带，hex 正则全局匹配第一个 sid。隐私模式 / `referrer-policy: no-referrer` 时 Referer 缺失，自动降级到跨 sid 兜底（按 mtime 最新）。新加静态文件路由必须沿用 sid-vs-nonsid 分流 + Referer 推断两层优先级。
22. **删除会话行内二次确认（小红叉状态机）**：`ConversationItem.vue` 维护 `isConfirmingDelete`：第一次点 × → `confirming` class 变红 `rgba(239,68,68,0.12)` 底常显；第二次点红 × → **立刻** `isConfirmingDelete = false` 再 `$emit('delete')`（先重置防 document click 冒泡）；点别处 / Esc 取消（`mounted` 绑 `document.click` + `keydown(Escape)`，`beforeUnmount` 解绑）。**App.vue 必保留逻辑**：`deleteConversation(sessionId)` finally 块必须清理三件套（`stopStreamTimer` + 三个 Map/Set delete + `new Set(...)` 触发响应式）+ 当前会话切换（关 SSE + `cleanupLoadingState()` + `createNewChat()`）。**emit 契约不变**：Sidebar `@delete-conversation`、ConversationItem `emits: ['delete']` 都不用动。
23. **Electron 单窗口架构 + autoEnter 三态按钮**：单 BrowserWindow + 主界面永远在 DOM 里（`appReady=false` 时加 `.app-disabled` 灰显禁用），`<BootstrapView>` 浮窗叠加（fixed + z-index 1000 + backdrop-filter 模糊）。主进程 `let servicesReady = false`；bootstrap 完成后 `webContents.send('startup:services-ready-changed', { ready, autoEnterFrontend })` 推 object payload。`App.vue` 新增 `_isInitializing: true` + `servicesReady: null` 兜底 IPC 窗口期。warm / cold / warm-refresh 三条路径一律不闪 BootstrapView。**三态按钮**：`launching=true` → 「启动中...」disabled；`servicesReady=true && !autoEnterFrontend` → 「进入应用」emit `enter-app`；其他 → 「启动应用」（`!allOk` 时 disabled）。**避免双源真相**：`BootstrapView.servicesReady` 是 prop，不重复 invoke `getServicesReady`；所有 `appReady` 翻转都在 App.vue 一处。**重启路径**：`restartBackend()` 完成后 `setServicesReady(true, { autoEnterFrontend: true })` —— 用户已在 app 里，重启恢复直接交回交互权。

24. **DataAnalysis 数据库分析（只读 + 跨会话配置 + 自动中断）**：`skills/DataAnalysis/database/` 提供 MySQL / SQLite / PostgreSQL / MongoDB 4 引擎只读，写操作（SQL `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE/MERGE/CALL/REPLACE` + Mongo `$out/$merge/$where/$function/$accumulator/mapReduce/eval`）一律拦截。DB 配置写 `.runtime/`（fcntl + 临时文件 + 原子替换）；LLM 只看 alias / engine / host / database 非敏感字段。DataAnalysis 目录 `:rw` 覆盖在 `/skills` ro 挂载之上。`need_db_credentials` 中断事件带 `db_type` / 字段列表，用户 UI 输入凭据后 resume；沿用 SSE `interrupt` 通道。

25. **导出端点（产物 + 对话历史）**：`backend/ChatMe/APIRouter/data_export.py`。`/chat/{sid}/export/artifacts?format=zip|html`：打包 `cached/{sid}/data_analysis/`（ZIP 保留 `gen_xxx/charts|data|reports|scripts/`；HTML marked.js + mermaid.js CDN + PNG/SVG base64；单文件 ≤100MB / 总 ≤500MB）。`/chat/{sid}/export/turn/{checkpoint_id}`：截至 checkpoint 的对话 ZIP（`openai.json` Chat Completions + `chatme.json` dump `state.values`）。前端：`DataAnalysisTree.vue` 头部 ⬇ ZIP + 👁 HTML（`exporting` 防连点）；`MessageItem.vue` AI 按钮 ⬇ 「导出到本轮」（`canExportTurn`：AI + 非流式 + 非 error + 有 `checkpointId`）。

26. **v0.1.1 约定**：`PermissionedToolNode` + LangGraph `interrupt()` 审批（`_awrap_tool_call` hook 是 `ToolNode` 官方扩展点，自己 try/except 拦截会被 runtime 忽略）；决策存 Redis `permission:{sid}` hash（`command` / `action` / `status` / `timestamp` / `tool_call_name` / `fingerprint`）；`resume` 走 `Command(resume=decision)`。**4 档决策**：`approve` / `this-time-only` / `deny` / `feedback:<text>`；`code_fingerprint` = SHA1(`imports + calls + lang + sandbox`)。**审批 UI 内嵌**到 `toolCall` 行。**多平台 prompt adapter**：`platforms/` 抽 `cmd`/`code`/`ctime` shell 差异到 `darwin.py`/`linux.py`/`windows.py` + `base.py`，新工具走 `platforms/`，prompt 不硬编码 `uname`。**`sub_agent` 工具 deprecated**。**session_id 兼容 32 + 12 位 hex**：dual regex 都接受。

27. **v0.1.2 约定**：跨 SSE 临时 metrics 累加器（每 round 独立 `round_metrics:{sid}` Redis hash，**不**写正式 `threads:{sid}:checkpoints`）。**实时累加**：`on_chat_model_end` 触发 `_accumulate_workflow_tokens` 累加本地 `token_usage`，返 `True` 立刻 `_persist_round_token_usage` 刷到临时键。**stream `finally` 兜底**：3 个 SSE 流 `return` 都套 `finally` 末尾 `_persist_round_token_usage`。**终态清理**：`_save_round_checkpoint` 写完 `cp_meta` 后 `_clear_round_metrics(session_id)` 清临时键。**不污染 CID 列表**：禁止把审批等待 / 中断续接的中间 metrics 写进 `threads:{sid}:checkpoints`。**`delete_conversation` 必须 `DEL round_metrics:{sid}`**。**前端 metrics 单一权威**：流式中由后端 `init` / SSE 事件 `elapsed_ms` / `token_usage` 同步到 message，本地 timer 250ms tick；终态走 `cp_meta`；F5 走 `get_conversation` 返的 `cp_meta` 回填。
28. **v0.1.3 约定**：Pre-check 拦截 SSE 兜底：`PermissionedToolNode._permission_wrap` pre-check（`dangerous` / `whitelist not_allowed`）拦截时直接 `return ToolMessage` 不调 `execute()`，LangGraph 不发 `on_tool_start`/`on_tool_end`，前端流式看不到拦截结果必须 F5 刷新。**兜底**：`on_chain_end` 节点为 `tool_execution_node` 时按 `tool_call_id` 配对 AIMessage.tool_calls 与 ToolMessage，补 `tool_call_name` + `tool_call_result` SSE。**去重**：per-stream `emitted_tool_call_ids: set`（正常 emit 后写入，兜底查 set 跳过避免双发）。**Helper**：`ChatService._build_intercepted_tool_call_events(chunk, emitted_ids, elapsed_ms, token_usage)` 统一封装，3 个 SSE 流都加；orphan 防御：`tool_calls_by_id.get(tc_id)` 查不到时跳过。
29. **v0.1.4 约定**：
    - **`mcps/` 三包重构**：`mcps/permissions/core.py` / `mcps/sandbox/pool.py` / `mcps/tools/`（`code_fingerprint.py` + `deprecated.py` + `platforms/`）。**各包 `__init__.py` 只写说明不 re-export**（除 `tools/platforms/__init__.py` 导出 adapter）—— import 必须写到具体模块：`from ...mcps.permissions.core import PermissionedToolNode`，不能 `from ...mcps.permissions import`。
    - **定时任务 = Skill + REST**：不是 MCP 工具。`skills/Scheduler/` 4 个顶层函数走 HTTP 调 `/admin/scheduled-tasks/*`，agent 用 `code(..., local=True)` 调用（沙盒网络不可靠 + 缺 `apscheduler` / `redis` 包）。
    - **lifespan 嵌套顺序不可换**：`chat_service_lifespan → scheduler_lifespan → cleanup_lifespan`（scheduler handler 依赖 `chat_service.message_stream`）。
    - **`uvicorn.run(app, ...)` 传对象不传字符串**：`"main:app"` 让 uvicorn 重新 import（banner 打两次 / LLM 自检跑两遍）。
    - **消息排队（前端 drain，后端只存）**：`/chat/{sid}/queue` 只做 Redis `queue:{sid}` FIFO 持久化（≤20 × 4000 字符），**不主动 drain**。
    - **回溯走 `CheckpointJanitor.retarget_to()`**：覆写 LangGraph latest 指针 + 删其余 checkpoint / write，**不再产 artifact checkpoint**；回溯前 `_wait_previous_memory_update`。
    - **未知工具名不崩**：走 LangGraph `ToolNode._validate_tool_call` 返回错误 `ToolMessage`（含未知工具名 + 可用工具列表）让模型重试；已知工具仍过权限 gate，`GraphInterrupt` / `GraphBubbleUp` 不被吞。
    - **MAIN_FLOW 只讲「怎么想」**：具体工具调用模式下沉 `platforms/base.py` 的 `<tool>_tool_prompt_block`，由 `all_tool_prompt_blocks()` 拼接。
    - **MCP session 长生命周期**：`session.py` stdio 子进程 + `ClientSession` 常驻复用，不再每次重开连接。

30. **v0.1.5 约定**：
    - **Memory skill 跨会话持久化**：`backend/skills/Memory/`（mount=ro）4 变体（`facts`/`preference` × `thread`/`global`）。**写入必须 `code(..., local=True)`**（沙盒 ro）；`context_assembly_node` 每轮开头自动合并注入，**只管写、读不用主动调**。路径 `.chatme/memory/{tid|global}/{category}.md`。
    - **SkillForge 动态创建 skill**：`backend/skills/SkillForge/`（mount=rw）`create_skill()` / `list_skills()` / `read_skill()`。**registry mtime 自动重扫**（APFS 不更新父目录 mtime，按每个 SKILL.md `stat()` 检测）。**必须 `code(..., local=True)`**。保留名禁用 `SkillForge` / `_xxx` 前缀。
    - **`/skills/<name>/SKILL.md` frontmatter**：YAML 支持 `name` / `description` / `aliases` / `mount`（`ro`/`rw`，默认 ro）/ `module` / `lazy`。`build_mount_args()` 加 `@functools.lru_cache(maxsize=1)`；`reset_skill_registry()` 必须 `cache_clear()`。
    - **Scheduler 4 层模块**：`models.py` / `handlers.py` / `registry.py` / `core.py`（`get_scheduler()` 函数入口）。handlers 走 lazy import 避免循环。
    - **CheckpointJanitor 拆两层**：业务类 `ChatWorkflow/CheckpointJanitor.py` + HTTP `APIRouter/checkpoint_janitor.py`（唯一路由 `POST /admin/checkpoints/prune`）。保护规则保留 `checkpoint_latest:{tid}:{ns}` + `threads:{tid}:checkpoints` HASH 所有 cid；删其余 `checkpoint:{tid}:*` / `checkpoint_write:{tid}:*` / `write_keys_zset:{tid}:*`。
    - **`/admin/config` 热加载（segment 级）**：`permissions` / `skills` 立即生效（`save_config()` 后 `force_reload()` 清 mtime cache + `get_permissions().force_reload()`）；`llm_providers` 需重启（`restart_required = "llm_providers" in saved_segments`）。前端 `buildPayload()` 维护 `originalConfig` + `_deepDiff()` + `_stripEmptyObjects()`，只发修改段。原子写 `tmp + os.replace`。
    - **`/admin/restart` + `/admin/health` + `/admin/config` REST**：`POST /admin/restart` 写 marker `.restart_pending` + 0.3s sleep + `os.execv`；`GET /admin/health` 前端 `pollHealth(120s)` 轮询；恢复 `window.location.reload()`。
    - **Sidebar 内嵌定时任务**：`ScheduledTasksPanel` 已**删除**；`ConversationItem` 底部内嵌 ⏰ 触发按钮（`tasks.length > 0`）+ `<transition name="scheduled-expand">` 展开（`max-height: 0 → 110px`）。展开状态 `lingxi.scheduledTasksExpanded` localStorage 持久化。
    - **三色侧栏状态点**：streaming 蓝闪（`blink 1.2s`）/ approval 黄脉冲（`pulse-yellow 2s`）/ errored 红常显（`#ef4444`）/ completed 绿常显（`#22c55e`）。**App.vue 四 Set 独立维护**：`_activeStreamingSessions` / `_approvalPendingSessions` / `_completedSessions` / `_errorSessions`，**不是** union；`_sessionHadError`（保护态）与 `_errorSessions`（视觉驱动）并行而非耦合。
    - **`ScheduledTaskItem` 行内小红叉二次确认**：参考偏好 22。
    - **`ChatMeConfig._load()` mtime 失效 + `force_reload()`**：`current_mtime == cached_mtime` → 直接 return（零开销）；变了 → 重读；不存在文件按需生成默认 / 保留旧 `_config`（外部误删可恢复，**不破坏运行**）。`force_reload()` 把 `_loaded=False` + `_config_file_mtime=None`。
31. **v0.1.6 约定**：matplotlib 中文字体随 skill 自动 mount —— `NotoSansSC-Regular.otf` 放 `backend/skills/DataAnalysis/fonts/`，容器内 `/skills/DataAnalysis/fonts/` 可用。**`get_fonts_setup_header()` 同时扫描 4 路径**（按序、去重、不存在 no-op）：① `/skills/DataAnalysis/fonts` ② `<cwd>/skills/DataAnalysis/fonts` ③ `/cached/.fonts`（legacy）④ `<cwd>/cached/.fonts`（legacy）。**优先 skill 路径**——字体作为 skill 资源走标准 mount 协议，无需 gitignore 反向规则。**`legacy cached/.fonts/` 保留兼容老部署**：定时清理脚本 `PRESERVED_TOP_DIRS={"cached/.fonts"}` 不动。
32. **v0.1.7 约定**：
    - **文件树行内删除 + 软删除 `.trash/` 兜底**：路径 `backend/.trash/{sid}/{YYYYMMDD_HHMMSS}_{rel_path_underscored}`（同秒追加 sha1[:6] 防碰撞）。**API**：`DELETE /chat/{sid}/file?file_path=<rel>`（拒绝绝对路径 / `..` / 越界）；`DELETE /chat/{sid}/trash` 手工清空。**定时清空**：`timed_clean.py` 每天 11:30 `daily_trash_cleanup`（与 23:30 `daily_cleanup` 错开避免 IO 叠加）。**前端**：`DataTreeNode.vue` × 红叉（沿用偏好 22）；`DataAnalysisTree` 面板 🗑 + `ConfirmDialog` 清回收站。**目录删除前补 `path` 字段**：`buildTree` 目录节点也得存 `cached/{sid}/dir/sub/` 完整路径。**Why 软删除**：误删能找回（直到 11:30 才物理清），符合偏好 22「二次确认是兜底」。
    - **/help 重构「能做什么 + 使用技巧」两段**：h3 + h4 子标题（键盘 / 审批 / 文件树 / 引用&撤回 / 产物导出）；移除对话与流式（实现级描述）+ 会话管理（UI 视觉元素）；新增 `.help-section h4` + `:first-of-type { margin-top: 0 }` 收头。

33. **标题自动派生（v0.1.7，剥离 `<quote>` + `/[xxx]` + 截断 12 字符）**：`ChatService/core.py` 模块级 helpers（`_TITLE_MAX_LEN=12` / `_QUOTE_BLOCK_RE` / `_SLASH_PILL_RE` / `_WHITESPACE_RE`）+ 3 函数 `_clean_message_for_title` / `_truncate_title` / `_derive_title_from_latest_human`（倒序找 HumanMessage，multimodal 取首个 text 段，全 quote/pill 返 `""`）。`update_conversation_title(session_id, new_title=None) -> Optional[str]`：`new_title` 非空 → 直接存；空 → 调派生；派生空 → 返 `None`（类型从 `bool` 改 `Optional[str]`）。**API**：`PUT /chat/{sid}/title` 的 `title` 改 `Optional[str] = Body(None)`；响应 `new_title` 是后端实际写入。前端 `App.vue`：`updateTitleOnly` / `updateTitleAndRefresh` 用 `body: JSON.stringify({})` 触发派生；用响应 `new_title` 更新侧栏。
34. **v0.1.8 约定 —— 文件树 Finder 化大优化**：
    - **长按框选状态机**（`Sidebar._startBoxSelect`）：`mousedown` 后等 **250ms** 或 **移动 ≥8px** 才进 box-select；`mouseup` 矩宽 `<4px` 且非 additive → 清选区。
    - **HTML5 拖拽移动**：节点 `:draggable="!renaming"` + `dragstart.stop`；多选拖用 `setData('application/x-lingxi-paths', JSON.stringify([...selectedPaths]))` + `effectAllowed='copyMove'`（Alt 切 copy/move）+ 自定义 ghost；drop 调 `POST /chat/{sid}/files/move?auto_rename=true`。
    - **焦点目录 `focusDir`（Cmd/Ctrl+V 目标）**：点目录行 → 该目录相对路径；点文件行 → 父目录（Finder 习惯）；完成操作后回根。视觉 `.dtn-dir.focus-target` —— 蓝色实心左边框 + 浅蓝底。
    - **copy / cut 视觉（蓝 → 琥珀）**：copy amber 500 浅底 + ⎘ 角标；focus 蓝色实心左边框；focus + copy 共存时背景偏 amber 但保留蓝色左竖线。
    - **空状态 + 树底 `+` 操作行**：`.empty-state` 重做（📂 + 标题 + 提示 + [新建文件夹/文件]）；树底 `.tree-new-actions` 始终挂 `+文件夹 / +文件` 快捷按钮 + `Cmd+Shift+N` / `Cmd+Shift+Alt+N`；按钮 `@mousedown.stop` 防 box-select。**OS 系统拖拽 overlay** —— Finder/Explorer 拖系统文件时显示「⬇ 释放以上传」全屏浮层。
    - **拖拽事件穿透重构**（`MessageInput.handleWindowDrop` + `_isDragOverFilesTree(e)`）：原 `drag-overlay` 拦截所有 drop 导致 Sidebar drop 失效，改为 `pointer-events: none` + window-level `drop` 监听 + 检测 `.files-tree` 内（在则让 Sidebar 处理）。
    - **后端文件操作体验优化**：`_find_unique_name` 计数器剥除（regex `^(.*?)\((\d+)\)$`：`(bar)` / `(v1-beta)` 保留）。`move_file` / `batch_move_files` 自粘贴兜底（`src.parent == dst_dir` no-op）。同名静默追加（`create_folder` / `create_file` 调 `_find_unique_name`）。空 session 懒加载（`body.parent == ""` 先 `parent.mkdir(parents=True)`）。
    - **Skill 描述前端覆盖**（`skillDescriptionOverrides`）：App.vue + MessageInput.vue 维护 `{ Memory, ImageParser, SkillForge }` 三条更准确描述，缺省 fallback 后端 `/chat/skills`。HelpDialog 文件树 h4 段同步展示 + 4 条 bullet（焦点 / 复制 vs 剪切 / 框选 / 拖拽），跨平台通过 `_isMac` / `_modKey` / `_fileManager` computed 切修饰键文案。
35. **v0.2.0 约定 —— 图工作流大重构 + done 工具 + ReAct 压缩健壮性**：
    - **新默认图 `_create_graph_improved` 替换 `_create_graph_core2`**：`init_graph()` 切换（`ChatWorkflow/core.py` line 254）；老 `_create_graph_core2`（line 891-1354）**完整保留**作回滚基线。工具集用 `init_llms` 内 `self.tools` vs `self.tools_with_done` 区分（`include_done` 参数）。**Why**：老图 prompt 强制 LLM 输出 `Done` + `should_end_node` LLM 决策不收敛；新图改「AIMessage 含 tool_calls → tool_execution_node；不含 → 重试或 final_node」纯结构化路由 + `done` 工具作显式收尾。
    - **MCP `done` 工具**（`mcps/server.py` line 246+）：无参函数，调用即返回固定字符串。**只在 `_create_graph_improved` 工具集里**暴露；老图 `get_mcp_tools(include_done=False)` 过滤掉。
    - **`route_agent_output` 决策函数**：纯结构化路由 —— 倒序找最后 AIMessage（含 tool_calls → tool_execution_node；无且 `agent_no_tool_call_retries >= RETRY_TIMES=3` → final_node；retry < 3 → context_assembly_node 注入英文 SysMsg）。**新图不再用 LLM 做决策**。
    - **`route_after_context_assembly` 双源**：done cycle 已被 `RemoveMessage` 把 AIMessage(done) 从 messages 里删了；改看 `state["done_cycle_detected"]` flag（每轮开头重置 False）。
    - **agent no-tool-call retry**（`agent_node` 内）：AIMessage 无 tool_calls → `retry_times += 1`；`< 3` 注入英文 SysMsg；成功调出 tool_calls → `retry_times = 0`；`= 3` → route_agent_output 强制 final_node。state `agent_no_tool_call_retries: int` 跨轮清零（`input_parse_node` 重置 0）。
    - **`RemoveMessage` 清理 done cycle**：单 done（tool_calls 长度 1 且唯一是 done）→ 整轮清理；并发调度（done 跟其他 tool 并存同 AIMessage）→ 只删匹配 done `tool_call_id` 的 ToolMessage，AIMessage（其他 tool_calls）和 TM 全部保留（F5 刷新后还能看到「搜了 XXX 拿到 YYY」）。
    - **`compression_handled_this_round` 防重复压缩**：bool 标记，iteration 2+ 跳过整个 ReAct 压缩段。`is_done_cycle=True` 时整段 ReAct 压缩不跑。
    - **`pending_compaction_replace_at` 改完整 loop 数**：`= len(_find_complete_tool_loops(context)) + REACT_KEEP_LOOPS`，**不**用 `tool_call_times + REACT_COMPACT_REPLACE_AFTER`。**Why**：agent 并行调 1-3 个工具会让 `tool_call_times` 一次 +1~3；loop 数版本无论并行多少次都稳定。
    - **`REACT_COMPACT_DETECTION_MIN_ROUNDS` 4 → 5**：`REACT_COMPACT_REPLACE_AFTER` 字段移除（被 `REACT_KEEP_LOOPS=2` 复用语义）；**保留 `REACT_KEEP_LOOPS`**。
    - **前端 `done` 工具调用过滤**（`App.vue` 两处）：① `mergeToolCallStart`（line 1911+）`if (data.content?.name === 'done') return message`；② `_processBackendToolCalls`（line 5066+）`if (tc.name === 'done') continue`（老 checkpoint 迁移安全网）。
    - **测试清理 + 许可证**：`.gitignore` 加 `tests/` / `**/tests/`；18 个 `backend/tests/` 测试文件 staged for deletion；单测跟随 .venv 落本地，不入 git；`pyproject.toml` 保留 `[dependency-groups] dev = ["pytest>=9.1.1"]`。项目 **MIT License**（`LICENSE` / `NOTICE` / `THIRD_PARTY_LICENSES.md` 三件套）；「灵析™」/「Lingxi™」为产品名商标，MIT 不授予商标使用权。
36. **v0.2.1 约定 —— 配置向导 SetupView + 应用启动链路健壮性**：
    - **BootstrapView ≠ SetupView**：v0.2.1 起 `frontend/src/components/` 既有 `BootstrapView.vue`（首启 / 服务未就绪时浮窗 + bootstrap 进度 + autoEnter 三态按钮）又有 `SetupView.vue`（独立配置向导，**首次启动 + 任何时候 🪄 按钮**打开）。**注意**：偏好 22 / 23 描述的「SetUpView」是 BootstrapView 的前身（v0.2.0 之前的命名），新代码用 BootstrapView；SetupView 是独立组件，**不要混用**。
    - **SetupView 关键约束**（1223 行大组件）：`emit('close')` / `emit('restart-requested')` 必须声明在 `emits: []`（Vue 3 运行时只对声明过的事件往父级传）；App.vue `@close="setupVisible = false"` + `@restart-requested="handleRestartBackend"`。**重启逻辑完全交给 App.vue**：SetupView 自己**不**写 `setInterval` / `restartBackend` / `window.location.reload()`，只 `emit('restart-requested')`；否则重启遮罩三套副本（Settings + SetupView + App.vue）状态不同步。localStorage 持久化按 step key 命名（`lingxi.setup.step.<key>`）。
    - **fixRedis ping-first + 状态归一化**（启动链路 bug 修复核心）：`probeRedisContainer` / `fixRedis` 不能直接相信 `docker inspect` 返的 status。**四段判定**：① **`tryRedisPing` 第一步**：`docker exec chatme-redis redis-cli -a 123456 --no-auth-warning ping` → PONG 视为「健康」**完全跳过修复**；② ping 失败 + `inspectOut` = running/restarting：只 `waitForRedisReady` 探，不再 `docker start`（**避免端口重绑冲突**）；③ ping 失败 + status = exited/created/paused/dead：`docker start chatme-redis`，**失败不立即 throw**——日志 + `waitForRedisReady` 兜底；④ ping 失败 + 容器不存在：`docker compose up -d redis`。`normalizeDockerStatus(s)`：trim + 剥首尾成对引号 + toLowerCase。
    - **startBackend 启动前端口预检**：`killPortIfListening(port)` 跨平台 helper（Win `netstat -ano | findstr :PORT → taskkill /F /PID`；Unix `lsof -ti:PORT -sTCP:LISTEN | xargs kill -9`），spawn backend 前清理 38211 上残留进程。**只针对本应用专用端口**（38211 backend / 8211 老端口）。
    - **discoverProjectRoot 自动迁移**：`~/lingxi` / `~/lingxi-v2` 多副本共存 + git pull 后旧 saved 路径指向老副本（端口 8211 / 旧 pyproject version）会冲突。新增 `_readProjectFingerprint` 读 pyproject `version` + main.py `app_config.get("port")`；candidate 更新 → 自动 swap → BootstrapView 弹琥珀色「已自动切换到更新的项目目录」横幅。
    - **健康监测启动期 banner 抑制（`_hasEverConnected` gate）**：冷启动 backend=false 是预期 → **不**弹 banner；只有 `_hasEverConnected=true` 后再次变 false 才显示。**主进程 `HEALTH_FAILURE_THRESHOLD=2`**：单次失败可能是网络抖动 → 不能立刻推 false，连续 2 次失败（约 10s）才推 IPC。
    - **`source='restart'` 重启窗口期不走 BootstrapView**：主进程先 `setServicesReady(false, { source: 'restart' })` → App.vue 看到 source='restart' 保持 `appReady=true`，主界面走 `.app-disabled` 灰显 + banner 提示，但不踢回 BootstrapView。
    - **`proc.on('exit')` 立即推 health 检查**：后端意外退出（非 0 + 非 SIGTERM/SIGKILL）→ 50ms 后 `runHealthCheck` + 重置 `consecutiveHealthFailures=0`，banner 在 10s 内出现。
    - **`checkBackendHealth` timeout 1.5s → 3s**：FastAPI 启动期 uvicorn 已经 LISTEN 但 lifespan 还没跑完时 /health 会 timeout；3s 给 QwenVL weights 加载缓冲。
    - **Windows `file://` API 转发路径修复**：`file:///C:/.../dist/index.html` 协议下，renderer `fetch('/chat/xxx')` 解析成 `file:///C:/chat/xxx`，`pathname = /C:/chat/xxx`（带盘符）`startsWith('/chat/')` 失败。**解法**：`apiPathname = IS_WIN ? pathname.replace(/^\/[A-Za-z]:/, '') : pathname`。
    - **startBackend config.json 不存在兜底**：fresh clone / 用户删 `.chatme/` 时 `fs.readFileSync` 抛 ENOENT，改成「读不到就用空对象 + `fs.mkdirSync(parent, { recursive: true })`」。

37. **v0.2.1 约定 —— 全局重启遮罩 + SetupView wizard 多步骤配置**：
    - **三处入口共用一份 UI（unified restart overlay）**：banner「重新连接」/ Settings「Save & Restart」/ SetupView 改 apikey → **统一走 App.vue 的 `handleRestartBackend()`**，弹同一个 `.restart-mask`（z-index 1900）+ spinner + 倒计时。**`emit('restart-requested')` 契约**：SettingsDialog / SetupView `emits: []` 加 `'restart-requested'`，父级 `@restart-requested="handleRestartBackend"`；**子组件 emit 后立即 `close()`**。**`handleRestartBackend` 状态机**：`_backendRestarting` / `_restartElapsed` / `_restartTimer` 都在 App.vue；`setInterval` 内 **`this._restartElapsed = (this._restartElapsed || 0) + 1`**（显式赋值不用 `++` —— Vue 3 Proxy 自增在 babel/minify 下会丢响应性）。**`refreshPage()` 而非 `window.location.reload()`**：reload 前清 timer，Electron 走 `electronAPI.refreshPage()` → `webContents.reload()`，web fallback `window.location.reload()`。
    - **SetupView wizard 5 步骤**：v0.2.0 之前改 API key 只能手编辑 `backend/.chatme/config.json`，SetupView UI 化后点顶栏 🪄 / `/setup` 命令打开。`setupVisible` 在 App.vue 维护，SetupView 只接 `visible: Boolean` prop + `close`/`restart-requested` emit。**step 1 基础检查**：依赖 / Redis / 路径探测走主进程 IPC；失败项高亮 + 「重新探测」按钮不阻塞。**step 2 LLM 连接**：列 `llm_providers` 三元组 + 「测试连接」 → `/admin/config/test-llm`。**step 3 skill 开关**：实时 `/chat/skills`，存 `skills` 段（**不需重启**）。**step 4 权限策略**：白名单 / 危险检测 / 4 档决策；存 `permissions` 段（**不需重启**）。**step 5 完成**：diff 摘要 → `putConfig` → 若 `llm_providers` 在改动段里 → `emit('restart-requested')` → App.vue 接管。沿用 v0.1.5 segment 级热加载。

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
   7.1. **`_filter_thinking_content` 是 MiniMax-M3 输出的兜底主力**：filter 必须能吃掉 `[</tool_call>]` / `[<]tool_call[>]` / `[<invoke name="cmd">][<command>...</command>]` 等方括号包装的伪 tool_call 块。**关键顺序**：combined regex（`<tool_calls?>.*?\[?</?tool_calls?>\]?`）必须**先**跑；wrapper / 方括号 invoke 块拆成几条放后面兜底。否则 wrapper 先剥 → 留下 78 字符半截垃圾。新增 M3 输出格式时必须同步更新两处 filter（`ChatWorkflow/core.py` + `Memory/core.py`）。
   7.2. **`_try_compact_react` 必须调用 filter**：input 已经 `_build_clean_compact_input` 清空 AIMessage.content，但保留 `tool_calls` 字段（API 强校验需要），所以 LLM 仍会模仿输出 `<tool_call>` 块；filter 是兜底主力，prompt 是源头。**根因**：M3 与 agent_llm 共用同一个 weights，看到 input 里的 `tool_calls` 字段会模仿输出 tool_call 块。filter 是所有调用 M3 的节点（agent_node / final_node / imp_ipt / `_try_compact_react`）的兜底。
   7.3. **react_compact prompt 显式禁止 tool_call + Few-shot 锚定**：prompt 的"禁止"段必须包含 `<tool_call>` / `[</tool_call>]` / `[<invoke name="cmd">][<command>...]` 等伪 tool_call 格式；同时配 1 个好例子 + 1 个反例 + 一行点错在哪，few-shot 锚定比单纯禁止清单强得多。
8. **Memory 操作加锁 + 串行**：见偏好 8 / 9，新方法（如 `restore_memory`）必须继承
9. **节点异常统一打 `@node_guard`**：见偏好 11，`sub_agent` 这种嵌套调用外层再包一层 try/except 返回兜底字符串，主 agent 才能继续
10. **前端错误气泡不被覆盖**：见偏好 12，新增 SSE 事件路径必须沿用 `wasError` 防御
11. **SandboxPool 池锁**：见偏好 14，新加执行方法（除 `execute` / `execute_command` 外）必须把 pop → exec → append 整段放在 `with self.lock:` 内，否则 N+1 并发撞空池
12. **Electron `protocol.handle` 注册时机 + 路径双形态**：见偏好 15 / 16；必须放在 `app.whenReady().then(...)` 内 + createWindow 之前；asar 内可读用 `__dirname`，asar 外用 `process.resourcesPath`，用 `app.isPackaged` 三元判断 dev/packaged