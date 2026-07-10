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
- **桌面端**: Electron 41 + electron-builder
- **样式**: CSS Variables + 原生 CSS
- **Markdown / 数学**: marked + highlight.js + katex
- **特性**: 流式 SSE、主题切换、响应式布局

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
│   │   ├── App.vue                       # 全局状态 + SSE 处理
│   │   ├── components/                   # Vue 组件
│   │   ├── router/
│   │   └── main.js
│   ├── vite.config.js
│   └── package.json                      # lingxi-frontend
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
| `App.vue` | 全局状态管理，SSE 事件分发 |
| `Sidebar.vue` / `ConversationItem.vue` | 会话列表 |
| `MessageList.vue` | 消息列表容器 + 滚动控制 |
| `MessageItem.vue` | 单条消息渲染（思考过程 / Markdown / 代码高亮） |
| `MessageInput.vue` | 输入框 + 文件上传 + 语音输入 |
| `ChatHeader.vue` | 头部 + 主题切换 |
| `CheckpointPanel.vue` | 回溯面板 |
| `FilePreviewPanel.vue` / `FilePreviewModal.vue` | 文件预览 |
| `DataAnalysisTree.vue` / `DataTreeNode.vue` | 数据分析树形结构展示 |
| `WebPreviewPanel.vue` | 网页预览窗口（Electron IPC 触发） |
| `SearchResults.vue` | 搜索结果展示 |
| `ConfirmDialog.vue` | 确认对话框 |

### Electron 主进程能力

- **多环境支持**：`development` / `test` / `production`，通过 `NODE_ENV` 切换
- **安全策略**：生产环境禁用 DevTools / 右键菜单 / 危险快捷键
- **网页预览**：通过 IPC `open-web-preview` 在独立窗口打开外部链接
- **导航控制**：主窗口允许内嵌 localhost/file，外部链接走 `shell.openExternal`

## 关键文件

### 后端

| 文件 | 职责 |
|------|------|
| `backend/main.py` | FastAPI 入口，挂载 4 个 Router |
| `backend/ChatMe/ChatWorkflow/core.py` | 工作流定义、节点逻辑、5 个 LLM 实例（`MessagesPlaceholder` 处理）、ReAct 流程压缩、final_node dynamic system prompt 注入 |
| `backend/ChatMe/ChatWorkflow/config/graph_config.py` | prompts 与模型配置（含 `get_react_compact_config`） |
| `backend/ChatMe/ChatWorkflow/config/models.py` | 图状态 TypedDict（含 `context_summary_text` / `last_compact_at_tool_calls`） |
| `backend/ChatMe/ChatWorkflow/Memory/core.py` | 长期记忆管理：per-thread `asyncio.Lock` + 临时文件原子写（`fsync` + `os.replace`） |
| `backend/ChatMe/ChatWorkflow/mcps/server.py` | FastMCP 工具入口 |
| `backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py` | Docker 沙盒容器池 |
| `backend/ChatMe/ChatService/core.py` | 聊天服务，SSE 流式输出 + 记忆任务调度（`_memory_update_tasks` 串行队列 + `memory_wait_*` 事件） |
| `backend/ChatMe/ChatService/FilesLoaders/core.py` | 文件加载 + `_maybe_truncate` 大文件截断 |
| `backend/ChatMe/ChatService/FilesLoaders/config.py` | 文件大小/类型/截断阈值常量 |
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
| `frontend/src/App.vue` | 全局状态 + SSE 事件处理 |
| `frontend/electron/main.js` | Electron 主进程 |
| `frontend/electron/electron.config.js` | 桌面端配置（窗口 / 快捷键 / 安全 / IPC） |
| `frontend/vite.config.js` | Vite 配置（同时导出 `viteServerConfig` 给 Electron 复用） |

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

## 完整设计文档

仓库内 `docs/综合实践文档/` 提供了完整的设计资料（**注意：该目录受 `.gitignore` 约束，仅在本地存在**）：

- `01_需求规格说明书.md` — 需求规格
- `02_概要设计说明书.md` — 概要设计
- `03_详细设计说明书.md` — 详细设计
- `部署图.png` / `时序图.png` — 架构 / 时序图
- `程序流程图/` — 流程图目录

修改前先读相关设计文档，理解上下文后再动手。