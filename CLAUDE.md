# ChatMe（灵析）项目指南

## 项目概述

ChatMe（产品名「灵析」Lingxi）是一个基于 LangGraph 的多智能体数据分析对话系统。
支持流式响应、工具调用、对话记忆管理、文档/图片多模态解析，以及基于 Docker 沙盒的
安全 Python 代码执行（数据分析场景）。同时提供 Web 端和 Electron 桌面端两种运行形态。

## 技术栈

### 后端
- **框架**: FastAPI + LangGraph + LangChain
- **状态管理**: Redis (checkpointer + state saver)，通过 docker-compose 启动
- **工具**: FastMCP (MCP Server)
- **代码沙盒**: Docker 容器池（`CodeSandboxPool.py`），隔离执行 Python 数据分析代码
- **文档解析**: docling + qwen-vl-utils + unstructured
- **对象存储**: oss2（阿里云 OSS）
- **定时任务**: apscheduler
- **LLM**: 支持 OpenAI 兼容 API（OpenAI / DeepSeek / MiniMax 等多 provider，含本地 VL 模型）

### 前端
- **Web 框架**: Vue 3 + Vite（端口 5173，代理 `/chat`、`/static`）
- **桌面端**: Electron 41 + electron-builder（多平台打包）
- **样式**: CSS Variables + 原生 CSS
- **Markdown / 数学**: marked + highlight.js + katex
- **特性**: 流式 SSE、主题切换、响应式布局、网页预览

## 架构

```
ChatMe/
├── backend/                              # Python 后端
│   ├── ChatMe/
│   │   ├── APIRouter/                    # FastAPI 路由
│   │   │   ├── main.py                   # /chat 前缀，主对话路由
│   │   │   ├── static_file.py            # /static 前缀，静态资源
│   │   │   ├── model_vl.py               # /api 前缀，视觉语言模型
│   │   │   └── timed_clean.py            # /admin 前缀，定时清理
│   │   ├── ChatDataAnalysis/             # 数据分析辅助
│   │   ├── ChatMeConfig/                 # 配置管理
│   │   ├── ChatService/                  # 聊天服务层（SSE 流式输出）
│   │   ├── ChatWorkflow/                 # LangGraph 工作流核心
│   │   │   ├── config/                   # 图配置和 prompts
│   │   │   ├── mcps/                     # MCP 工具服务器
│   │   │   │   ├── server.py             # FastMCP 服务入口（原 mcp_server.py）
│   │   │   │   └── CodeSandboxPool.py    # Docker 沙盒容器池
│   │   │   └── Memory/                   # 记忆管理
│   │   ├── LoggingManager/               # 日志
│   │   └── test/                         # 单元测试
│   ├── skills/                           # 搜索/解析技能包（Bocha, Exa, Tavily, ImageParser, DataAnalysis）
│   ├── .chatme/                          # 本地配置（可选，优先于全局配置）
│   ├── pyproject.toml                    # uv 项目配置
│   ├── uv.lock
│   └── main.py                           # FastAPI 入口
├── sandbox/                              # 代码沙盒 Docker 镜像
│   └── Dockerfile                        # Python 3.12 + numpy/pandas/matplotlib/...
├── frontend/
│   ├── electron/                         # Electron 桌面端
│   │   ├── main.js                       # Electron 主进程
│   │   ├── electron.config.js            # 桌面端配置（窗口/快捷键/安全策略）
│   │   ├── preload.js                    # 预加载脚本
│   │   └── public/                       # 图标等静态资源
│   ├── public/                           # Web 图标
│   ├── src/
│   │   ├── App.vue                       # 主应用，全局状态，SSE 流式处理
│   │   ├── components/                   # Vue 组件
│   │   ├── router/                       # 路由
│   │   └── main.js
│   ├── index.html
│   ├── vite.config.js                    # Vite 配置（同时导出给 Electron）
│   └── package.json                      # lingxi-frontend
├── docker-compose.yml                    # Redis 服务编排
├── docker_data/                          # Redis 持久化数据
├── .env.example
└── CLAUDE.md
```

## 工作流

```
用户输入 → input_parse → context_assembly → agent_node ↔ tool_execution_node → final_node
                                                    ↓
                                              (工具调用循环)
```

### 节点说明

1. **input_parse_node**: 输入预处理，文件解析（docling/OSS），输入优化（`improve_input`）
2. **context_assembly_node**: 上下文组装，记忆检索，中断检查
3. **agent_node**: AI 代理决策，决定调用工具或结束
4. **tool_execution_node**: 工具执行（搜索/MCP 工具/Docker 沙盒）
5. **final_node**: 最终回复生成

## 快速启动

### 0. 启动 Redis（Docker Compose）

```bash
# 在项目根目录
docker-compose up -d redis
# Redis 容器端口 6379 -> 主机 6024
# RedisInsight 端口 8001 -> 主机 8111
# 密码：123456
```

### 1. 启动后端

```bash
cd backend

# 安装依赖（使用 uv）
uv sync

# 启动 MCP 服务器（端口 18080）
# 首次启动会：1) 检查 Redis 2) 清理残留沙盒容器 3) 初始化沙盒池
uv run chatme_mcp
# 或：uv run python -m ChatMe.ChatWorkflow.mcps.server

# 启动主服务（端口 8211）
uv run chatme_main
# 或：uv run python main.py
```

### 2. 启动前端

```bash
# Web 开发模式
cd frontend
npm install
npm run dev  # 访问 http://localhost:5173

# Electron 开发模式（同时启动 Vite + Electron）
npm run electron:dev:all

# 打包桌面端
npm run electron:build          # 当前平台
npm run electron:build:mac      # macOS
npm run electron:build:win      # Windows
npm run electron:build:linux    # Linux
```

### 3. 构建沙盒镜像（首次使用代码沙盒前）

```bash
# 沙盒默认 profile=never，需要手动构建并启动
docker-compose build sandbox
# 镜像名：chatme-python-sandbox:latest
# CodeSandboxPool 会自动从池中拉取容器执行用户代码
```

## 配置

### 配置文件优先级

1. **局部配置** `./backend/.chatme/config.json`（项目目录下，仓库内已包含）
2. **全局配置** `~/.chatme/config.json`（用户目录下）
3. **环境变量**（作为默认值填充）

首次运行时会自动在 `~/.chatme/` 生成默认配置。

### 环境变量 (.env)

```env
# LLM 配置
OPENAI_MODEL_NAME=gpt-4o
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TEMPERATURE=0.7
OPENAI_MAX_TOKENS=2048
OPENAI_TOP_P=1.0
OPENAI_FREQUENCY_PENALTY=0.0
OPENAI_PRESENCE_PENALTY=0.0
```

### 配置文件 (`backend/.chatme/config.json`)

```json
{
  "app": {
    "name": "ChatMe",
    "version": "v1.0.0",
    "description": "multiple agents system with HARNESS engineer",
    "host": "127.0.0.1",
    "port": 8211
  },
  "mcp_server": {
    "url": "http://127.0.0.1:18080/streamable",
    "transport": "streamable_http"
  },
  "redis": {
    "checkpointer_url": "redis://:123456@localhost:6024/0",
    "state_saver_url":   "redis://:123456@localhost:6024/1"
  },
  "llm_providers": {
    "openai":   { "model_name": "...", "api_key": "...", "base_url": "..." },
    "deepseek": { "model_name": "deepseek-chat", "api_key": "...", "base_url": "https://api.deepseek.com/" },
    "vl":       { "model_name": "Qwen3-VL-2B", "base_url": "http://127.0.0.1:8211/api/v1", "local": true }
  },
  "directories": {
    "skills_dir": "./skills",
    "cached_dir": "./cached"
  },
  "oss": {
    "access_key_id": "...",
    "access_key_secret": "...",
    "bucket": "chatmebucket",
    "endpoint": "https://oss-cn-beijing.aliyuncs.com"
  }
}
```

## Docker 代码沙盒

`mcps/CodeSandboxPool.py` 提供基于 Docker 容器的安全代码执行能力：

- **预启动容器池**：默认 2 个常驻容器（`sleep infinity`），按需取用/归还
- **隔离环境**：使用 tmpfs 限制 `/tmp`、`/sandbox`（各 64m，noexec）
- **预装库**：numpy、pandas、scipy、scikit-learn、sympy、matplotlib、seaborn、
  plotly、bokeh、altair、pygal、pyecharts、folium、networkx、requests、bs4、lxml、
  openpyxl、xlrd、pillow、jinja2、markupsafe（使用阿里云 PyPI 镜像）
- **执行流程**：`docker cp` 注入代码 → `docker exec` 运行 → 清空沙盒目录 → 归还容器
- **超时保护**：单次执行 30s 超时
- **自动恢复**：检测到容器未运行时自动重建

MCP 工具直接通过 `SandboxPool.execute(code, language="python")` 调用。

## MCP 工具

MCP 服务器（`mcps/server.py`，FastMCP 3.x）提供核心工具能力：

| 工具 | 说明 |
|------|------|
| `execute_code` | Docker 沙盒中执行 Python 代码（数据分析/绘图） |
| `execute_command` | 安全终端命令执行（带危险命令检测） |
| `interrupt` | 中断当前对话 |
| `get_current_datetime` | 获取当前日期时间 |

每个 tool 函数构建时需带上 `session_id` 参数。

## API 接口

后端通过 4 个 Router 暴露接口：`/chat`、`/static`、`/api`、`/admin`。

### 聊天接口（`/chat` 前缀，`APIRouter/main.py`）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/chat/` | POST | 流式对话（无 session_id 则新建） |
| `/chat/conversations` | GET | 会话列表 |
| `/chat/{session_id}/conversation` | GET | 会话详情 |
| `/chat/{session_id}/title` | GET / PUT | 获取/修改会话标题 |
| `/chat/{session_id}/clear` | DELETE | 删除会话（含聊天记录） |
| `/chat/{session_id}/backtrack` | POST | 会话回溯 |
| `/chat/{session_id}/interrupt` | POST | 中断对话 |
| `/chat/{session_id}/invoke_interrupted/{invoke_message}` | POST | 中断续接对话 |
| `/chat/{session_id}/upload_file` | POST | 上传文件 |
| `/chat/cancel_upload_file` | POST | 取消已上传的文件 |
| `/chat/improve_input` | POST | 优化用户输入 |
| `/chat/file-config` | GET | 获取文件上传配置 |

### 其它接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/static/cached/{file_path:path}` | GET | 访问 cached 目录静态文件 |
| `/api/...` | * | 视觉语言（VL）模型服务（本地 Qwen3-VL 等） |
| `/admin/cleanup` | POST | 手动触发清理任务 |
| `/admin/cleanup/status` | GET | 获取清理状态 |

## 前端组件

| 组件 | 功能 |
|------|------|
| `App.vue` | 主应用，全局状态，SSE 流式处理 |
| `Sidebar.vue` | 会话列表 |
| `ConversationItem.vue` | 单个会话条目 |
| `MessageList.vue` | 消息列表容器，滚动控制 |
| `MessageItem.vue` | 单条消息渲染（含思考过程/Markdown/代码高亮） |
| `MessageInput.vue` | 输入框，文件上传，语音输入 |
| `ChatHeader.vue` | 头部，主题切换 |
| `CheckpointPanel.vue` | 回溯面板 |
| `FilePreviewPanel.vue` / `FilePreviewModal.vue` | 文件预览 |
| `WebPreviewPanel.vue` | 网页预览窗口（通过 Electron IPC 打开） |
| `SearchResults.vue` | 搜索结果展示 |
| `ConfirmDialog.vue` | 确认对话框 |

### Electron 主进程能力

- **多环境支持**：`development` / `test` / `production`，通过 `NODE_ENV` 切换
- **安全策略**：生产环境禁用 DevTools、右键菜单、危险快捷键
- **网页预览**：通过 IPC `open-web-preview` 在独立窗口打开外部链接
- **导航控制**：主窗口允许内嵌 localhost/file，外部链接走 `shell.openExternal`

## 关键文件

### 后端
- `main.py`: FastAPI 入口，挂载 4 个 Router
- `ChatMe/ChatWorkflow/core.py`: 工作流定义，节点逻辑，LLM 实例初始化（含 MessagesPlaceholder 处理）
- `ChatMe/ChatWorkflow/config/graph_config.py`: prompts 和模型配置
- `ChatMe/ChatWorkflow/config/models.py`: 图状态 TypedDict 定义（`ChatStateCore2` / `FileParseState`）
- `ChatMe/ChatWorkflow/mcps/server.py`: FastMCP 工具服务入口
- `ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py`: Docker 沙盒容器池
- `ChatMe/ChatService/core.py`: 聊天服务，SSE 流式输出
- `ChatMe/ChatService/FilesLoaders/core.py`: 文件加载与处理（含 `_maybe_truncate` 大文件截断）
- `ChatMe/ChatService/FilesLoaders/config.py`: 文件大小/类型/截断阈值常量
- `ChatMe/ChatDataAnalysis/format.py`: 数据分析规范（`ChatDataAnalysisFormat` 类、generation 管理）
- `ChatMe/ChatMeConfig/core.py`: 配置加载器
- `ChatMe/APIRouter/model_vl.py`: VL 模型 API
- `ChatMe/APIRouter/timed_clean.py`: 定时清理（apscheduler）
- `sandbox/Dockerfile`: 代码沙盒镜像定义

### 前端
- `App.vue`: 全局状态管理，SSE 事件处理
- `MessageItem.vue`: 消息渲染，思考过程显示
- `MessageList.vue`: 消息列表，滚动控制
- `electron/main.js`: Electron 主进程
- `electron/electron.config.js`: 桌面端配置（窗口/快捷键/安全策略/IPC）
- `vite.config.js`: Vite 配置（同时导出 `viteServerConfig` 给 Electron 复用）

## 开发注意事项

1. **MCP 服务器**需要单独启动（`chatme_mcp`），首次启动会自动检查 Redis 并清理残留沙盒容器
2. **Redis** 通过 `docker-compose up -d redis` 启动，端口 6024，密码 123456
3. **代码沙盒**需要先 `docker-compose build sandbox` 构建镜像；容器池大小可通过 `SandboxPool(size=N)` 调整
4. **思考内容过滤**：后端 `_filter_thinking_content` 过滤 AI 输出中的思考标签
5. **流式响应**：前端通过 SSE 实时接收 `content`/`reasoning`/`tool_call_*` 事件
6. **配置加载**：仓库内已包含 `backend/.chatme/config.json`（含真实 API key，提交时注意脱敏）
7. **多 LLM Provider**：可通过 `llm_providers` 切换 openai / deepseek / vl（本地 VL）
8. **OSS**：图片/文件上传后通过 OSS URL 访问，缓存目录在 `cached/`

## 命令行工具

安装 wheel 后可用：

```bash
chatme_main   # 启动后端主服务（端口 8211）
chatme_mcp    # 启动 MCP 服务器（端口 18080）
```

### 开发模式

```bash
cd backend
uv run python main.py                                    # 后端主服务
uv run python -m ChatMe.ChatWorkflow.mcps.server         # MCP 服务
```

## 打包部署

### 构建 wheel 包

```bash
cd backend
uv build --wheel
# 输出: dist/ChatMe-1.0.0-py3-none-any.whl
```

### 安装 wheel

```bash
uv pip install dist/ChatMe-1.0.0-py3-none-any.whl
# 安装后 chatme_main 和 chatme_mcp 命令全局可用
```

### 部署结构

```
~/.chatme/config.json              # 全局配置（首次运行自动生成）
/usr/local/bin/chatme_main         # 安装时创建
/usr/local/bin/chatme_mcp          # 安装时创建

# 沙盒镜像（部署时需预构建）
docker-compose build sandbox

# Redis 服务
docker-compose up -d redis
```

### 桌面端打包

```bash
cd frontend
npm run electron:build          # 当前平台
npm run electron:build:mac      # macOS DMG
npm run electron:build:win      # Windows NSIS
npm run electron:build:linux    # Linux AppImage
```

桌面端通过 `electron-builder` 打包，应用信息在 `electron/electron.config.js` 中配置
（应用名「灵析」、identifier `com.chatme.app`、版本 1.0.0）。
