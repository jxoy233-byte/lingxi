# ChatMe（灵析 Lingxi）

基于 LangGraph 的多智能体数据分析对话系统。支持流式响应、工具调用、对话记忆管理、文档/图片多模态解析，以及基于 Docker 沙盒的安全 Python 代码执行。同时提供 Web 端和 Electron 桌面端两种运行形态。

---

## 目录

- [项目特性](#项目特性)
- [技术栈](#技术栈)
- [架构概览](#架构概览)
- [工作流](#工作流)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [API 概览](#api-概览)
- [代码沙盒](#代码沙盒)
- [MCP 工具](#mcp-工具)
- [近期优化](#近期优化)
- [部署打包](#部署打包)
- [开发注意事项](#开发注意事项)
- [许可证](#许可证)

---

## 项目特性

- **多智能体工作流**：基于 LangGraph StateGraph 实现 `input_parse → context_assembly → agent_node ↔ tool_execution_node → final_node` 的循环决策结构
- **流式 SSE 响应**：前端通过 EventSource 实时接收 `content` / `reasoning` / `tool_call_*` 事件
- **多模态文件解析**：支持图片（OSS / base64）、文本（CSV / JSON / MD / TXT / XML）、文档（PDF / Word / PowerPoint / Excel），docling + qwen-vl-utils + unstructured 组合方案
- **Docker 沙盒执行**：基于预启动容器池 + tmpfs 隔离，提供安全的 Python 数据分析代码执行环境
- **多 LLM Provider**：OpenAI / DeepSeek / 本地 VL 模型（Qwen3-VL-2B）统一抽象
- **对话记忆管理**：基于 Redis checkpointer 的状态恢复 + 自建 memory manager 的长期记忆
- **OSS 对象存储**：阿里云 OSS 集成，图片/文件上传后通过 URL 直接访问
- **桌面端打包**：Electron + electron-builder 多平台打包（macOS / Windows / Linux）

## 技术栈

### 后端

| 模块 | 选型 |
|------|------|
| Web 框架 | FastAPI |
| 工作流引擎 | LangGraph + LangChain |
| 状态管理 | Redis (checkpointer + state saver) |
| MCP 工具 | FastMCP 3.x |
| 代码沙盒 | Docker 容器池 |
| 文档解析 | docling + qwen-vl-utils + unstructured |
| 对象存储 | oss2（阿里云 OSS） |
| 定时任务 | apscheduler |
| LLM | OpenAI 兼容 API（OpenAI / DeepSeek / 本地 VL） |
| 包管理 | uv |

### 前端

| 模块 | 选型 |
|------|------|
| Web 框架 | Vue 3 + Vite |
| 桌面端 | Electron 41 + electron-builder |
| 样式 | CSS Variables + 原生 CSS |
| Markdown / 数学 | marked + highlight.js + katex |
| 特性 | 流式 SSE、主题切换、响应式布局、网页预览 |

## 架构概览

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
│   │   │   └── FilesLoaders/             # 文件加载与处理
│   │   ├── ChatWorkflow/                 # LangGraph 工作流核心
│   │   │   ├── config/                   # 图配置和 prompts
│   │   │   ├── mcps/                     # MCP 工具服务器
│   │   │   └── Memory/                   # 记忆管理
│   │   ├── LoggingManager/               # 日志
│   │   └── test/                         # 单元测试
│   ├── skills/                           # 技能包（Bocha, Exa, Tavily, ImageParser, DataAnalysis）
│   ├── .chatme/                          # 局部配置（可选）
│   ├── pyproject.toml
│   └── main.py                           # FastAPI 入口
├── sandbox/                              # 代码沙盒 Docker 镜像
├── frontend/                             # Vue + Electron 前端
├── docker-compose.yml                    # Redis 服务编排
├── docker_data/                          # Redis 持久化数据
└── .env.example
```

## 工作流

```
用户输入 → input_parse_node → context_assembly_node
                                    ↓
                              agent_node ──→ tool_execution_node (循环)
                                    ↓
                              final_node → END
```

### 节点说明

| 节点 | 职责 |
|------|------|
| `input_parse_node` | 输入预处理、文件解析（docling / VL）、输入优化（`improve_input`） |
| `context_assembly_node` | 上下文组装（拼接 `imp_ipt`、memory、当前轮循环消息）、中断检查 |
| `agent_node` | AI 代理决策，决定调用工具或结束；工具调用超过 20 次会发 SystemMessage 提示停止 |
| `tool_execution_node` | 工具执行（搜索 / MCP 工具 / Docker 沙盒），由 LangGraph 官方 `ToolNode` 提供 |
| `final_node` | 最终回复生成（独立于 agent 的 LLM），带 SUMMARY 标记 |

> 节点状态使用 LangGraph TypedDict + `add_messages` reducer 维护，state 定义见 [`ChatMe/ChatWorkflow/config/models.py`](backend/ChatMe/ChatWorkflow/config/models.py)。

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+
- uv（Python 包管理）
- Docker + Docker Compose
- 4GB+ 内存（本地 VL 模型需要更多）

### 0. 启动 Redis

```bash
docker-compose up -d redis
# Redis 容器端口 6379 -> 主机 6024
# RedisInsight 端口 8001 -> 主机 8111
# 密码：123456
```

### 1. 启动后端

```bash
cd backend
uv sync                                          # 安装依赖

# 启动 MCP 服务器（端口 18080）
# 首次启动会自动：1) 检查 Redis  2) 清理残留沙盒容器  3) 初始化沙盒池
uv run chatme_mcp / python -m backend/ChatMe/ChatWorkflow/mcps/mcp_server
# 等价：uv run python -m ChatMe.ChatWorkflow.mcps.server

# 另开终端，启动主服务（端口 8211）
uv run chatme_main / python main.py
# 等价：uv run python main.py
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev  # 访问 http://localhost:5173
```

#### Electron 桌面端开发

```bash
npm run electron:dev:all    # 同时启动 Vite + Electron
```

#### 桌面端打包

```bash
npm run electron:build          # 当前平台
npm run electron:build:mac      # macOS DMG
npm run electron:build:win      # Windows NSIS
npm run electron:build:linux    # Linux AppImage
```

### 3. 构建代码沙盒镜像（首次使用前）

```bash
docker-compose build sandbox
# 镜像名：chatme-python-sandbox:latest
# 容器池默认 2 个常驻容器，CodeSandboxPool 自动按需取用
```

## 配置说明

### 配置文件优先级

1. **局部配置** `./backend/.chatme/config.json`（项目目录下，仓库内已包含）
2. **全局配置** `~/.chatme/config.json`（用户目录下）
3. **环境变量**（作为默认值填充）

首次运行时会自动在 `~/.chatme/` 生成默认配置。

### 环境变量（.env）

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

### 配置文件示例

```json
{
  "app": {
    "name": "ChatMe",
    "version": "v1.0.0",
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
    "openai":   { "model_name": "gpt-4o", "api_key": "...", "base_url": "https://api.openai.com/v1" },
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

> 提交代码前请脱敏 `backend/.chatme/config.json` 中的真实 API key。

## 项目结构

```
ChatMe/
├── backend/
│   ├── ChatMe/
│   │   ├── APIRouter/
│   │   ├── ChatDataAnalysis/             # ChatDataAnalysisFormat 类
│   │   ├── ChatMeConfig/                 # 配置加载器
│   │   ├── ChatService/
│   │   │   ├── core.py                   # ChatService，SSE 流式输出
│   │   │   ├── RedisStateSaver/          # 自建 checkpoint 索引
│   │   │   └── FilesLoaders/             # 文件加载 + 大文件截断
│   │   ├── ChatWorkflow/
│   │   │   ├── core.py                   # 工作流定义，4 个 LLM 实例
│   │   │   ├── config/
│   │   │   │   ├── graph_config.py       # prompts 和模型配置
│   │   │   │   └── models.py             # ChatStateCore2 / FileParseState
│   │   │   ├── mcps/
│   │   │   │   ├── server.py             # FastMCP 工具入口
│   │   │   │   └── CodeSandboxPool.py    # Docker 容器池
│   │   │   └── Memory/                   # 长期记忆管理
│   │   ├── LoggingManager/
│   │   └── test/
│   ├── skills/                           # 技能包（Python 模块）
│   ├── .chatme/
│   ├── pyproject.toml
│   └── main.py
├── sandbox/
│   └── Dockerfile                        # Python 3.12 + 数据分析库
├── frontend/
│   ├── electron/                         # 桌面端
│   ├── src/                              # Vue 组件
│   └── vite.config.js
├── docker-compose.yml
└── docker_data/
```

### 关键文件

| 文件 | 职责 |
|------|------|
| `backend/ChatMe/ChatWorkflow/core.py` | 工作流定义，节点逻辑，4 个 LLM 实例（`MessagesPlaceholder` 处理） |
| `backend/ChatMe/ChatWorkflow/config/graph_config.py` | prompts 和模型配置 |
| `backend/ChatMe/ChatWorkflow/config/models.py` | 图状态 TypedDict |
| `backend/ChatMe/ChatWorkflow/mcps/server.py` | FastMCP 工具服务入口 |
| `backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py` | Docker 沙盒容器池 |
| `backend/ChatMe/ChatService/core.py` | 聊天服务，SSE 流式输出 |
| `backend/ChatMe/ChatService/FilesLoaders/core.py` | 文件加载与处理（`_maybe_truncate` 大文件截断） |
| `backend/ChatMe/ChatService/FilesLoaders/config.py` | 文件大小/类型/截断阈值常量 |
| `backend/ChatMe/ChatDataAnalysis/format.py` | 数据分析规范（generation 管理） |
| `backend/ChatMe/APIRouter/main.py` | `/chat` 前缀主对话路由 |
| `backend/ChatMe/APIRouter/model_vl.py` | `/api` 前缀 VL 模型 API |
| `sandbox/Dockerfile` | 代码沙盒镜像定义 |
| `frontend/src/App.vue` | 全局状态管理，SSE 事件处理 |
| `frontend/electron/main.js` | Electron 主进程 |

## API 概览

后端通过 4 个 Router 暴露接口。

### 聊天接口（`/chat` 前缀）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/chat/` | POST | 流式对话（无 session_id 则新建） |
| `/chat/conversations` | GET | 会话列表 |
| `/chat/{session_id}/conversation` | GET | 会话详情 |
| `/chat/{session_id}/title` | GET / PUT | 获取 / 修改会话标题 |
| `/chat/{session_id}/clear` | DELETE | 删除会话（含聊天记录） |
| `/chat/{session_id}/backtrack` | POST | 会话回溯 |
| `/chat/{session_id}/interrupt` | POST | 中断对话 |
| `/chat/{session_id}/invoke_interrupted/{msg}` | POST | 中断续接对话 |
| `/chat/{session_id}/upload_file` | POST | 上传文件 |
| `/chat/cancel_upload_file` | POST | 取消已上传文件 |
| `/chat/improve_input` | POST | 优化用户输入 |
| `/chat/file-config` | GET | 获取文件上传配置 |

### 其它接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/static/cached/{file_path:path}` | GET | 访问 cached 目录静态文件 |
| `/api/v1/chat/completions` | POST | 视觉语言模型服务（本地 Qwen3-VL） |
| `/admin/cleanup` | POST | 手动触发清理任务 |
| `/admin/cleanup/status` | GET | 获取清理状态 |

## 代码沙盒

[`backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py`](backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py) 提供基于 Docker 容器的安全代码执行能力：

- **预启动容器池**：默认 2 个常驻容器（`sleep infinity`），按需取用 / 归还
- **隔离环境**：使用 tmpfs 限制 `/tmp`、`/sandbox`（各 64m，noexec）
- **预装库**：numpy、pandas、scipy、scikit-learn、sympy、matplotlib、seaborn、plotly、bokeh、altair、pygal、pyecharts、folium、networkx、requests、bs4、lxml、openpyxl、xlrd、pillow、jinja2、markupsafe（阿里云 PyPI 镜像）
- **执行流程**：`docker cp` 注入代码 → `docker exec` 运行 → 清空沙盒目录 → 归还容器
- **超时保护**：单次执行 30s 超时
- **自动恢复**：检测到容器未运行时自动重建

容器池大小可在 `SandboxPool(size=N)` 调整。

## MCP 工具

MCP 服务器（`mcps/server.py`，FastMCP 3.x）暴露以下核心工具：

| 工具 | 说明 |
|------|------|
| `execute_code` | Docker 沙盒中执行 Python / Node.js 代码（`use_sandbox=True` 切到容器） |
| `execute_command` | 终端命令白名单执行（带危险命令检测） |
| `interrupt` | 中断当前对话 |
| `get_current_datetime` | 获取当前日期时间 |

每个 tool 函数都带 `session_id` 参数。

## 近期优化

- **大文件截断**：`FilesLoaders._maybe_truncate` 对超过 `TEXT_TRUNCATE_LENGTH`（默认 3000 字符）的文本按行截断，提示 AI 通过环境探索读全量。阈值在 `FilesLoaders/config.py` 调整。
- **SystemMessage 正确传递**：4 个 LLM 全部用 `MessagesPlaceholder("messages")` 替代字符串占位符 `{messages}`，避免 `SystemMessage` 被 `str()` 成一坨塞进 human 消息。
- **VL 模型提速**：`file_process_node` 跳过非图片文件（CSV / MD / TXT / JSON / PDF / Word / Excel 都不再走 Qwen3-VL），VL prompt 也重写为只针对图片。
- **依赖更新**：`pyproject.toml` 新增 `unstructured>=0.16.0`（CSV / MD / XML 解析依赖），安装后自动下载 NLTK 数据。

## 部署打包

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

桌面端通过 `electron-builder` 打包，应用信息（应用名「灵析」、identifier `com.chatme.app`、版本 1.0.0）在 `frontend/electron/electron.config.js` 中配置。

## 开发注意事项

1. **MCP 服务器**必须单独启动，首次启动会自动检查 Redis 并清理残留沙盒容器
2. **Redis** 通过 `docker-compose up -d redis` 启动，端口 6024，密码 `123456`
3. **代码沙盒**需要先 `docker-compose build sandbox` 构建镜像
4. **思考内容过滤**：后端 `_filter_thinking_content` 过滤 AI 输出中的 `<thinking>` 等思考标签
5. **流式响应**：前端通过 SSE 实时接收 `content` / `reasoning` / `tool_call_*` 事件
6. **配置脱敏**：`backend/.chatme/config.json` 包含真实 API key，提交时务必脱敏
7. **多 LLM Provider**：可通过 `llm_providers` 切换 openai / deepseek / vl（本地 VL）
8. **OSS**：图片 / 文件上传后通过 OSS URL 访问，缓存目录在 `cached/`
9. **环境探索模式**：当文件被截断时（提示中含 `[文件过大已截断]`），AI 应走 `execute_command(ls cached/...)` + `cat cached/.../filename` 流程读全量
10. **unstructured 首次使用**：CSV / MD / XML 解析会自动下载 NLTK 数据（punkt、averaged_perceptron_tagger 等），需外网环境

## 许可证

本项目为内部项目，许可证信息请参考项目根目录 LICENSE 文件（如有）。
