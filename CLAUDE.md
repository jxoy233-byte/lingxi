# ChatMe（灵析）AI 协作指南

> 完整项目说明见 [`README.md`](README.md)。本文档给 AI 协作者阅读：项目怎么组织、关键路径在哪、AI 协作的偏好与约定。

## 项目概述

ChatMe（产品名「灵析」Lingxi）是一个基于 LangGraph 的多智能体数据分析对话系统。后端 FastAPI + LangGraph + Docker 沙盒，前端 Vue 3 + Vite + Electron 桌面端。Redis 做 checkpoint + state saver，OSS 做文件存储。

## 技术栈

### 后端
- **框架**: FastAPI + LangGraph + LangChain
- **状态管理**: Redis (checkpointer + state saver)
- **MCP**: FastMCP 3.x
- **代码沙盒**: Docker 容器池（`mcps/CodeSandboxPool.py`）
- **文档解析**: docling + qwen-vl-utils + unstructured
- **对象存储**: oss2（阿里云 OSS）
- **LLM**: OpenAI 兼容 API（OpenAI / DeepSeek / 本地 VL 模型多 provider）
- **包管理**: uv

### 前端
- **Web**: Vue 3 + Vite（端口 5173）
- **桌面端**: Electron 41 + electron-builder 26
- **样式**: CSS Variables + 原生 CSS
- **Markdown / 数学**: marked + highlight.js + katex
- **Electron 关键能力**：`file://` 协议拦截（→ 后端代理等价 Vite dev proxy）、SSE 流透传、↻ 页面刷新按钮（ChatHeader + DataAnalysisTree 共用 SVG path `M20.49 15a9 9 0 1 1-2.12-9.36L23 10`）、多环境切换（dev/test/prod）
- **特性**: 流式 SSE、主题切换、响应式布局、头部刷新按钮

## 架构

```
ChatMe/
├── backend/
│   ├── ChatMe/
│   │   ├── APIRouter/                    # /chat /static /api /admin 4 个 Router
│   │   ├── ChatDataAnalysis/             # 数据分析规范（ChatDataAnalysisFormat）
│   │   ├── ChatMeConfig/                 # 配置加载器
│   │   ├── ChatService/                  # 聊天服务层（SSE 流式）
│   │   │   └── FilesLoaders/             # 文件加载 + 大文件截断
│   │   ├── ChatWorkflow/                 # LangGraph 工作流核心
│   │   │   ├── config/                   # 图配置 / prompts / state TypedDict
│   │   │   ├── mcps/                     # MCP 工具服务 + Docker 沙盒池
│   │   │   └── Memory/                   # 长期记忆管理
│   │   ├── LoggingManager/
│   │   └── test/
│   ├── skills/                           # Bocha / Exa / Tavily / ImageParser / DataAnalysis
│   ├── .chatme/                          # 局部配置（仓库内已含）
│   ├── pyproject.toml
│   └── main.py                           # FastAPI 入口
├── sandbox/                              # 代码沙盒 Docker 镜像（Python 3.12）
├── frontend/
│   ├── electron/                         # 主进程 / preload / 配置
│   ├── src/
│   │   ├── App.vue                       # 全局状态 + SSE 处理 + 刷新页面
│   │   ├── components/                   # Vue 组件（含 ChatHeader / DataAnalysisTree 等）
│   │   ├── router/
│   │   └── main.js
│   ├── build/                            # electron-builder 资源（icon.icns/ico/png）
│   ├── vite.config.js
│   └── package.json                      # lingxi-frontend + electron-builder 配置
├── docker-compose.yml                    # Redis 服务编排
├── docker_data/                          # Redis 持久化
└── docs/                                 # 综合实践文档（详见 README 引用）
```

## 工作流

```
用户输入 → input_parse_node → context_assembly_node
                                  ↓
                          agent_node ↔ tool_execution_node（循环）
                                  ↓
                            final_node → END
```

### 节点职责

| 节点 | 职责 |
|------|------|
| `input_parse_node` | 输入预处理、文件解析（docling / OSS / VL）、输入优化（`improve_input`），给 `imp_ipt` 标记 `additional_kwargs.imp_ipt=True` |
| `context_assembly_node` | 上下文组装（拼接 `imp_ipt` / memory / 当前轮循环消息）+ **ReAct 流程压缩**（见下）+ 中断检查 |
| `agent_node` | AI 决策（调用工具 or 结束）。工具调用超过 20 次会注入 SystemMessage 提示停止 |
| `tool_execution_node` | LangGraph 官方 `ToolNode`，执行搜索 / MCP / Docker 沙盒 |
| `final_node` | 最终回复生成（独立于 agent 的 LLM），用 **dynamic system prompt** 把 `imp_ipt` 注入 system 层（不参与 messages 序列），输出带 SUMMARY 标记 |

State 定义在 [`backend/ChatMe/ChatWorkflow/config/models.py`](backend/ChatMe/ChatWorkflow/config/models.py)（`ChatStateCore2` / `FileParseState`），用 LangGraph TypedDict + `add_messages` reducer。

### ReAct 流程压缩

`context_assembly_node` 在每轮组装时按"完整工具 loop 节拍"触发一次整体覆盖式压缩，避免长 ReAct 轨迹把 prompt 撑爆：

- **触发条件**：完整工具 loop 数 ≥ `REACT_COMPACT_LOOPS`（默认 5）+ `REACT_KEEP_LOOPS`（默认 2）= 7 轮，**且** draft 字符数 ≥ `REACT_COMPACT_MIN_CHARS`（默认 2000），**且** `tool_call_times != last_compact_at_tool_calls`（防 state 恢复或失败后重复触发）。
- **范围**：压缩前 N-keep 轮的 ReAct 轨迹，**最近 keep（默认 2）轮完整 loop 原文保留**（不被摘要覆盖），imp_ipt 之前的 memory / 其他 SystemMessage 整体保留。
- **产物**：新摘要以 `【ReAct 摘要】` 标题的 SystemMessage 形式插入 imp_ipt 之后；写入 state 的 `context_summary_text` / `last_compact_at_tool_calls`。
- **失败兜底**：长度 [80, 2500] 区间外 / 含残留标签 / LLM 异常一律 `return None`，context 保持不变。
- **辅助方法**（`core.py`）：`_content_chars` / `_should_compact_react` / `_find_imp_ipt_idx` / `_find_complete_tool_loops` / `_build_compaction_draft` / `_try_compact_react`。**全程靠 content 特征扫描定位，不写死下标**。
- **专用 LLM**：`get_react_compact_config()`，`REACT_COMPACT_TEMPERATURE=0.3` / `REACT_COMPACT_MAX_TOKENS=2048`（env 可覆盖），目标 ≤ 2000 字中文 markdown。

### 工作流启动入口

```bash
# MCP 服务（端口 18080）
uv run chatme_mcp

# 主服务（端口 8211）
uv run chatme_main
```

## 前端组件

| 组件 | 职责 |
|------|------|
| `App.vue` | 全局状态管理，SSE 事件分发；维护 `_sessionHadError` 集合做"错误气泡保护态"（出错后该 session 不再被右侧刷新覆盖）；`refreshPage()` 触发 `window.location.reload()` |
| `Sidebar.vue` / `ConversationItem.vue` | 会话列表 |
| `MessageList.vue` | 消息列表容器 + 滚动控制 |
| `MessageItem.vue` | 单条消息渲染（思考过程 / Markdown / 代码高亮），`message.error=true` 时渲染为红色错误框（避免报错堆栈被当 markdown） |
| `MessageInput.vue` | 输入框 + 文件上传 + 语音输入 |
| `ChatHeader.vue` | 头部 + 主题切换 + ↻ 刷新页面按钮（与 `DataAnalysisTree` 同款 SVG path：`M20.49 15a9 9 0 1 1-2.12-9.36L23 10` + polyline 箭头） |
| `CheckpointPanel.vue` | 回溯面板 |
| `FilePreviewPanel.vue` / `FilePreviewModal.vue` | 文件预览 |
| `DataAnalysisTree.vue` / `DataTreeNode.vue` | 数据分析树形结构展示；`DataAnalysisTree` 面板头部 reload 按钮与 `ChatHeader` 共用同款 SVG |
| `WebPreviewPanel.vue` | 网页预览窗口（Electron IPC 触发） |
| `SearchResults.vue` | 搜索结果展示 |
| `ConfirmDialog.vue` | 确认对话框 |

### Electron 主进程能力

- **多环境支持**：`development` / `test` / `production`，通过 `NODE_ENV` 严格切换（不再受 `!app.isPackaged` 拖累，否则 `electron .` 永远走 dev 分支，加载不到 `dist/`）
- **`file://` 协议拦截**：`protocol.handle('file', ...)` 在 `app.whenReady()` 内注册（必须 ready 才能拿到 `session.defaultSession`，且要在 createWindow 之前）；`/chat/*` + `/static/*` 通过 `net.fetch` 转发到后端（等价 Vite dev proxy），其他走白名单校验后从 asar 内 `dist/` 读盘
- **API 转发三件套**：method / headers / body 必须显式透传 + `duplex: 'half'`（POST `/chat/` 的 body 否则被丢，等于给后端发 GET，请求会落到不对的路由）
- **SSE 流必须重建 Response**：`net.fetch` 返回的 Response 直接给 `protocol.handle` 会被 buffer，SSE 退化成一次性出现；必须显式 `new Response(upstream.body, { status, statusText, headers })` 透传 stream
- **静态文件白名单**：`resolvedPath` 必须在 `distDir + path.sep` 之下，否则 `403 Forbidden`（防 `fetch('/etc/passwd')` 类 path traversal）；hashed assets 永久缓存 `public, max-age=31536000, immutable`，index.html 不缓存
- **图标必须放包外**：`nativeImage` 不读 asar 内文件，所以 `build/` 通过 `package.json` 的 `extraResources: [{ from: "build", to: "build" }]` 复制到 `app/Contents/Resources/build/`，运行时用 `process.resourcesPath` 取；`app.dock.setIcon` / `BrowserWindow.icon` 都必须是 PNG，不认 `.icns`
- **安全策略**：生产环境禁用 DevTools / 右键菜单 / 危险快捷键（`F12` / `CmdOrCtrl+Shift+I/C/J`）
- **网页预览**：通过 IPC `open-web-preview` 在独立窗口打开外部链接
- **导航控制**：主窗口允许内嵌 localhost/file，外部链接走 `shell.openExternal`
- **macOS Dock 图标**：dev 模式下也通过 `app.dock.setIcon` 显式设置（`BrowserWindow.icon` 在 macOS 不影响 Dock）；必须是 PNG，否则 `UnhandledPromiseRejectionWarning: Failed to load image from path`

## 关键文件

### 后端

| 文件 | 职责 |
|------|------|
| `backend/main.py` | FastAPI 入口，挂载 4 个 Router |
| `backend/ChatMe/ChatWorkflow/core.py` | 工作流定义、节点逻辑、5 个 LLM 实例（`MessagesPlaceholder` 处理）、ReAct 流程压缩、final_node dynamic system prompt 注入 |
| `backend/ChatMe/ChatWorkflow/decorators.py` | `node_guard` 装饰器：所有节点（ChatWorkflow / sub_agent）统一异常捕获 + 重抛，functools.wraps 保留 `__wrapped__` 让 LangGraph 仍按 `(state, config)` 注入 |
| `backend/ChatMe/ChatWorkflow/config/graph_config.py` | prompts 与模型配置（含 `get_react_compact_config`） |
| `backend/ChatMe/ChatWorkflow/config/models.py` | 图状态 TypedDict（含 `context_summary_text` / `last_compact_at_tool_calls`） |
| `backend/ChatMe/ChatWorkflow/Memory/core.py` | 长期记忆管理：per-thread `asyncio.Lock` + 临时文件原子写（`fsync` + `os.replace`） |
| `backend/ChatMe/ChatWorkflow/mcps/server.py` | FastMCP 工具入口（`code` / `execute_command` 等） |
| `backend/ChatMe/ChatWorkflow/mcps/tools.py` | sub_agent 工具：内部用 `node_guard` 装饰 `agent_node`，整体 try/except 返回 `[sub-agent 执行失败]` 兜底字符串，让主 agent 可继续 |
| `backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py` | Docker 沙盒容器池；`execute(code, lang)` 跑 Python/Node（先写 `/code.<py\|js>` 再跑再删），`execute_command(cmd)` 跑 shell（直接 `docker exec sh -c`） |
| `backend/ChatMe/ChatService/core.py` | 聊天服务，SSE 流式输出 + 记忆任务调度（`_memory_update_tasks` 串行队列 + `memory_wait_*` 事件） |
| `backend/ChatMe/ChatService/FilesLoaders/core.py` | 文件加载 + `_maybe_truncate` 大文件截断 |
| `backend/ChatMe/ChatService/FilesLoaders/config.py` | 文件大小/类型/截断阈值常量（`TEXT_TRUNCATE_LENGTH=4000`） |
| `backend/ChatMe/ChatDataAnalysis/format.py` | 数据分析规范（`ChatDataAnalysisFormat` 类、generation 管理） |
| `backend/ChatMe/ChatMeConfig/core.py` | 配置加载器 |
| `backend/ChatMe/APIRouter/main.py` | `/chat` 前缀主对话路由 |
| `backend/ChatMe/APIRouter/model_vl.py` | `/api` VL 模型路由 |
| `backend/ChatMe/APIRouter/timed_clean.py` | 定时清理任务 |
| `backend/ChatMe/LoggingManager/logging_config.py` | `QueueHandler` + `QueueListener` 异步日志，`atexit` 清理 |
| `sandbox/Dockerfile` | 代码沙盒镜像定义 |

### 前端

| 文件 | 职责 |
|------|------|
| `frontend/src/App.vue` | 全局状态 + SSE 事件处理 + `refreshPage()` 触发 `window.location.reload()` |
| `frontend/src/components/ChatHeader.vue` | 头部 + 主题切换 + ↻ 刷新按钮 |
| `frontend/src/components/DataAnalysisTree.vue` | 数据分析面板 + reload 按钮（与 ChatHeader 共用 SVG path） |
| `frontend/electron/main.js` | Electron 主进程 + `protocol.handle('file', ...)` 拦截器 + macOS Dock `setIcon` |
| `frontend/electron/electron.config.js` | 桌面端配置（窗口 / 快捷键 / 安全 / IPC / 图标路径，含 `app.isPackaged` 双形态） |
| `frontend/electron/preload.js` | preload：`contextBridge` 暴露 `electronAPI` / `electron` |
| `frontend/vite.config.js` | Vite 配置（同时导出 `viteServerConfig` 给 Electron 复用，`base: './'` 必须在顶层） |
| `frontend/package.json` | npm scripts + `electron-builder` build 配置（files 白名单 + extraResources + 三平台 icon） |
| `frontend/build/icon.icns / .ico / .png` | electron-builder 应用图标（mac / win / linux） |

## 命令行工具

安装 wheel 后全局可用：

```bash
chatme_main         # 启动后端主服务（端口 8211）
chatme_mcp          # 启动 MCP 服务（端口 18080）
```

开发模式（不进 wheel）：

```bash
cd backend
uv run python main.py                                 # 主服务
uv run python -m ChatMe.ChatWorkflow.mcps.server      # MCP 服务
```

构建沙盒镜像（首次使用沙盒前）：

```bash
docker-compose build sandbox                          # 镜像名 chatme-python-sandbox:latest
```

启动 Redis：

```bash
docker-compose up -d redis                            # 端口 6024，密码 123456
```

## AI 协作偏好

> 这些偏好从用户对话中沉淀，存于 `/Users/jx/.claude/projects/-Users-jx-coding-projects-ChatMe/memory/`。改前先读 `MEMORY.md` 看完整索引。

### 工程约定

1. **后端最小化 + 前端动态加载**：文件树 / 列表类接口后端只返扁平列表，前端构树 + 动态加载内容；path 须含 `cached/` 前缀。
2. **沙盒隐藏文件过滤**：`sandbox/sitecustomize.py` 过滤规则（`.` / `__` 挡、`_` 不挡）+ 只在挂载点根目录一层不递归子目录。
3. **沙盒 config 同步策略**：用中间文件隔离 skills key，仅在 MCP 启动 / 容器重建时重生成，不做运行时自动同步。
4. **流式响应滚动 UX**：入场 `easeInOut`；流式 ramp（慢→快）+ 100ms 打断防抖；用户 wheel / touch 立即让出控制权。
5. **MCP 工具参数前缀被剥**：Python `use_sandbox` 在 MCP schema 里是 `sandbox`；过滤 / 判断要查实际 args key，兼容新旧两种。
6. **`should_end_node` 设计偏好**：LLM 决策节点的单条喂入 / 完整写回、低频字面量子串匹配、独立 `max_tokens` env、prompt / 解析兜底一致。
7. **ReAct 流程压缩节拍**：`REACT_COMPACT_LOOPS=5` + `REACT_KEEP_LOOPS=2`（≥ 7 个完整工具 loop 才触发），压缩前 N-keep 轮，**最近 keep 轮原文保留不被摘要覆盖**；imp_ipt 是唯一 draft 切分锚点（`additional_kwargs.imp_ipt=True`），全程不写死下标。
8. **Memory 并发安全**：`MemoryManager` 内部维护 `_thread_locks[thread_id]`，`update_memory` / `delete_memory` / `backtrack_memory` / `delete_latest_backup_memory` 全部走 `async with self._get_thread_lock(thread_id)`；文件写入走 `_atomic_write_text`（写 `*.tmp` + `fsync` + `os.replace`）。
9. **ChatService 记忆任务串行**：每会话在 `_memory_update_tasks[session_id]` 里只保留一个 asyncio.Task，新任务通过 `asyncio.shield` 串接上一轮；新请求发起 / 删除会话 / 回溯 前会先 `_wait_previous_memory_update` 等待；SSE 暴露 `memory_wait_start` / `memory_wait_done` 事件，`interrupt` / `done` 事件携带 `memory_status` 字段。
10. **异步日志**：写文件走 `QueueHandler` + `QueueListener` 模式，业务线程不入 IO；`atexit` 统一 `listener.stop()` 清理。
11. **节点异常统一兜底**：所有 LangGraph 节点（ChatWorkflow 5 个主节点 + 文件图 3 个节点 + sub_agent agent_node）都打 `@node_guard("<name>")`：`except Exception` 捕获后 log + 包装 `RuntimeError` 让 SSE 外层统一返回 `error` 事件；但 `except GraphBubbleUp`（LangGraph 控制流异常的基类，涵盖 `GraphInterrupt` / `ParentCommand` 等）必须**原样 `raise`**，不能包装 —— `interrupt()` 主动中断、`Command` 透传都依赖该异常穿透各层到达 runtime。新加节点必须继承这个分层约定。
12. **前端错误气泡保护**：App.vue 维护 `_sessionHadError: Set<session_id>`，SSE `error` 事件触发时把 `session_id` 标记为保护态；保护态下 `done` 事件不会覆盖错误气泡，`refreshConversation` / `updateTitleAndRefresh` 跳过 messages 重拉，只更新侧边栏；用户主动发起新一轮请求或续接时清掉保护态。
13. **`cmd` / `code` 工具默认走沙盒**：`server.py` 的 `cmd` 和 `code` 都默认 `use_sandbox=True`（MCP schema 里是 `sandbox` 参数），沙盒不可用时降级到本机（`cmd` → 本机 subprocess.run，`code` → 本机 venv）；白名单 + 危险检测 + 脚本检测在沙盒 / 本机两边都做。沙盒入口是 `SandboxPool.execute_command(cmd)` / `execute(code, lang)`，分别对应 shell / code 执行；`execute_command` 直接 `docker exec sh -c <cmd>`，命令里可含管道 / 重定向 / glob；`execute` 先写 `/code.py` 再跑再删（避免敏感信息残留）。
14. **SandboxPool 池锁必须包住整个 pop → exec → append 周期**：池容量有限（默认 2），并发 N+1（N=池容量）调用时第 N+1 个会撞上空列表报 `No available containers in pool`；**`self.containers.pop()` 必须在 `with self.lock:` 内**，否则 pop 跑在锁外、exec 跑在锁内，N+1 并发下 N 个 pop 完，第 N+1 个直接 `if not self.containers` 报错。`execute(code, lang)` 和 `execute_command(cmd)` 都用同一个 `self.lock`，所有"取出容器 → 跑 → 归还"必须整段锁内。新加执行方法必须继承这个锁结构。
14. **Electron `file://` 协议拦截必须透传 method/body/headers**：`protocol.handle('file', ...)` 在 `app.whenReady()` 内注册；`/chat/*` 转发到后端时**必须**显式带 `method: request.method, headers: request.headers, ...(request.body && { body: request.body, duplex: 'half' })`，否则 POST `/chat/` 的 body 被丢、后端收到 GET 请求、SSE 流式响应直接退化成一次性；SSE 流必须显式 `new Response(upstream.body, { status, statusText, headers })` 透传 stream，避免 `protocol.handle` 把 stream 当 buffer 处理
15. **Electron 图标必须放包外**：`nativeImage.createFromPath` 不读 asar 内文件；`build/` 通过 `package.json` 的 `extraResources` 复制到 `app/Contents/Resources/build/`（macOS）/ `app/resources/build/`（Win）/ `app/build/`（Linux），运行时用 `process.resourcesPath` 取真实路径；`paths.icon` / `paths.iconMac` 通过 `app.isPackaged` 切换 dev (`__dirname/build/icon.png`) vs packaged (`process.resourcesPath/build/icon.png`)；`app.dock.setIcon` 和 `BrowserWindow.icon` 都必须是 PNG，传 `.icns` 会得空 image 并 Promise reject
16. **Electron `protocol.handle` 静态文件必须白名单校验**：`resolvedPath = path.resolve(pathname)` 后必须检查 `startsWith(distDir + path.sep)`，否则 `403 Forbidden`；不写这一行的话渲染层一句 `fetch('/etc/passwd')` 就能读任意磁盘路径
17. **Electron 输出目录用 `release/electron-builder`**：`directories.output` 不要设 `dist/electron-builder`，否则会和 Vite 的 `dist/` 撞目录，且会被 `files` 模式误打进 asar；当前 `output: "release/electron-builder"` + `files: ["dist/**", "electron/**", "vite.config.js", "package.json"]` 是白名单显式列出，asar 体积 5.6MB（之前未优化时 419MB）

### 代码 / 提交风格

- 提交信息遵循仓库现有风格：`v1.0.0 <说明>`（参考 `git log`）
- 不要引入为假设需求而设计的抽象 / 配置项 / fallback
- 系统边界（用户输入、外部 API）才做校验；内部代码信任框架保证
- 修改代码前先读相关文件，不读不写

### 工作流修改注意点

1. 5 个 LLM（`llm_core` / `agent_llm` / `summary_llm` / `react_compact_llm` / `llm_imp_ipt`）全部用 `MessagesPlaceholder("messages")`，不要回到字符串 `{messages}` 占位（会导致 SystemMessage 被 `str()`）
2. 后端 `_filter_thinking_content` 过滤 `<thinking>` 等思考标签，前端再二次过滤
3. VL 模型只处理图片（`file_process_node` 已跳过非图片文件）
4. `execute_code` 工具默认 `use_sandbox=True`（即 MCP schema 里看到的是 `sandbox`）
5. **`imp_ipt` 是 draft 切分锚点**：`input_parse_node` 输出的 `imp_ipt` 唯一身份是 `additional_kwargs.imp_ipt == True`；ReAct 压缩 / final_node 注入 / 后续扩展都靠这个标志定位本轮意图，不要换成"最后一条 HumanMessage"这种隐式契约
6. **final_node 不再走 `MessagesPlaceholder`**：imp_ipt 走 `_final_system_template.format(imp_ipt=...)` 注入到 system prompt 独占最高注意力位；context 中要先把 `imp_ipt` pop 出去再喂给 `llm_core`，避免重复注入
7. **ReAct 压缩失败不要 raise**：`_try_compact_react` 一律返回 `None`，由 `context_assembly_node` 保持原 context 不变；不要让压缩异常把整轮回复炸掉
8. **Memory 操作加锁**：读写 / 删除 / 回溯全部走 `_get_thread_lock(thread_id).acquire()`，新方法（如新增的 `restore_memory`）必须继承这个约定
9. **ChatService 记忆任务串行**：新入口（新建 / 中断续接 / 回溯 / 删除）必须先 `_wait_previous_memory_update(session_id)`，避免读到旧记忆或与后台 task 写竞争
10. **节点异常统一打 `@node_guard`**：新加 LangGraph 节点必须 `@node_guard("<node_name>")`，禁止裸定义让异常穿透；`sub_agent` 这种嵌套调用外层再包一层 try/except 返回兜底字符串，主 agent 才能继续
11. **前端错误气泡不被覆盖**：SSE 出现 `error` 时前端已经把 `message.error=true` 渲染到气泡，后端 `done` 不能复活 AI 内容；新增 SSE 事件路径必须沿用 `wasError` 防御
12. **SandboxPool 池锁**：新加执行方法（除 `execute` / `execute_command` 外）必须把 pop → exec → append 整段放在 `with self.lock:` 内，不能像原 `execute` 那样 pop 在锁外；不要因为"exec 不需要锁"就只锁 exec，池子本身的"取容器"操作也得串行化，否则 N+1 并发撞空池
12. **Electron `protocol.handle` 注册时机**：必须放在 `app.whenReady().then(...)` 内（内部访问 `session.defaultSession` 要求 ready），且要在 `createWindow` 之前；否则首屏 `file://` 请求绕过拦截器、asar 协议相关 API 抛 `Session can only be received when app is ready`
13. **Electron 路径双形态**：asar 内可读的文件（preload、index.html）用 `__dirname`（asar patch 支持）；asar 外（图标、`extraResources` 复制过去的资源）用 `process.resourcesPath`；用 `app.isPackaged` 三元判断是 dev 还是 packaged 的统一约定

## 完整设计文档

仓库内 `docs/综合实践文档/` 提供了完整的设计资料（**注意：该目录受 `.gitignore` 约束，仅在本地存在**）：

- `01_需求规格说明书.md` — 需求规格
- `02_概要设计说明书.md` — 概要设计
- `03_详细设计说明书.md` — 详细设计
- `部署图.png` / `时序图.png` — 架构 / 时序图
- `程序流程图/` — 流程图目录

修改前先读相关设计文档，理解上下文后再动手。