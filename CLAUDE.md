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
| `input_parse_node` | 输入预处理、文件解析（docling / OSS / VL）、输入优化（`improve_input`） |
| `context_assembly_node` | 上下文组装（拼接 `imp_ipt` / memory / 当前轮循环消息）、中断检查 |
| `agent_node` | AI 决策（调用工具 or 结束）。工具调用超过 20 次会注入 SystemMessage 提示停止 |
| `tool_execution_node` | LangGraph 官方 `ToolNode`，执行搜索 / MCP / Docker 沙盒 |
| `final_node` | 最终回复生成（独立于 agent 的 LLM），带 SUMMARY 标记 |

State 定义在 [`backend/ChatMe/ChatWorkflow/config/models.py`](backend/ChatMe/ChatWorkflow/config/models.py)（`ChatStateCore2` / `FileParseState`），用 LangGraph TypedDict + `add_messages` reducer。

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
| `backend/ChatMe/ChatWorkflow/core.py` | 工作流定义、节点逻辑、LLM 实例（`MessagesPlaceholder` 处理） |
| `backend/ChatMe/ChatWorkflow/config/graph_config.py` | prompts 与模型配置 |
| `backend/ChatMe/ChatWorkflow/config/models.py` | 图状态 TypedDict |
| `backend/ChatMe/ChatWorkflow/mcps/server.py` | FastMCP 工具入口 |
| `backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py` | Docker 沙盒容器池 |
| `backend/ChatMe/ChatService/core.py` | 聊天服务，SSE 流式输出 |
| `backend/ChatMe/ChatService/FilesLoaders/core.py` | 文件加载 + `_maybe_truncate` 大文件截断 |
| `backend/ChatMe/ChatService/FilesLoaders/config.py` | 文件大小/类型/截断阈值常量 |
| `backend/ChatMe/ChatDataAnalysis/format.py` | 数据分析规范（`ChatDataAnalysisFormat` 类、generation 管理） |
| `backend/ChatMe/ChatMeConfig/core.py` | 配置加载器 |
| `backend/ChatMe/APIRouter/main.py` | `/chat` 前缀主对话路由 |
| `backend/ChatMe/APIRouter/model_vl.py` | `/api` VL 模型路由 |
| `backend/ChatMe/APIRouter/timed_clean.py` | 定时清理任务 |
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

### 代码 / 提交风格

- 提交信息遵循仓库现有风格：`v1.0.0 <说明>`（参考 `git log`）
- 不要引入为假设需求而设计的抽象 / 配置项 / fallback
- 系统边界（用户输入、外部 API）才做校验；内部代码信任框架保证
- 修改代码前先读相关文件，不读不写

### 工作流修改注意点

1. 4 个 LLM 全部用 `MessagesPlaceholder("messages")`，不要回到字符串 `{messages}` 占位（会导致 SystemMessage 被 `str()`）
2. 后端 `_filter_thinking_content` 过滤 `<thinking>` 等思考标签，前端再二次过滤
3. VL 模型只处理图片（`file_process_node` 已跳过非图片文件）
4. `execute_code` 工具默认 `use_sandbox=True`（即 MCP schema 里看到的是 `sandbox`）

## 完整设计文档

仓库内 `docs/综合实践文档/` 提供了完整的设计资料（**注意：该目录受 `.gitignore` 约束，仅在本地存在**）：

- `01_需求规格说明书.md` — 需求规格
- `02_概要设计说明书.md` — 概要设计
- `03_详细设计说明书.md` — 详细设计
- `部署图.png` / `时序图.png` — 架构 / 时序图
- `程序流程图/` — 流程图目录

修改前先读相关设计文档，理解上下文后再动手。