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
- [设计文档](#设计文档)
- [部署打包](#部署打包)
- [开发注意事项](#开发注意事项)
- [许可证](#许可证)

---

## 项目特性

- **多智能体工作流**：基于 LangGraph StateGraph 实现 `input_parse → context_assembly → agent_node ↔ tool_execution_node → final_node` 的循环决策结构
- **ReAct 流程压缩**：`context_assembly_node` 按"完整工具 loop 节拍"自动压缩长 ReAct 轨迹，imp_ipt 标记做切分锚点，最近 keep 轮原文保留，防止 prompt 撑爆
- **流式 SSE 响应**：前端通过 EventSource 实时接收 `content` / `reasoning` / `tool_call_*` / `memory_wait_*` 事件
- **多模态文件解析**：支持图片（OSS / base64）、文本（CSV / JSON / MD / TXT / XML）、文档（PDF / Word / PowerPoint / Excel），docling + qwen-vl-utils + unstructured 组合方案
- **Docker 沙盒执行**：基于预启动容器池 + tmpfs 隔离，提供安全的 Python 数据分析代码执行环境
- **多 LLM Provider**：OpenAI / DeepSeek / 本地 VL 模型（Qwen3-VL-2B）统一抽象，5 个独立 LLM（core / agent / summary / react_compact / imp_ipt）可分别配参
- **对话记忆管理**：基于 Redis checkpointer 的状态恢复 + 自建 memory manager 的长期记忆；per-thread `asyncio.Lock` + 原子写（`fsync` + `os.replace`）保证并发安全；后台记忆任务按会话串行执行
- **节点异常统一兜底**：`@node_guard("<node_name>")` 装饰器包住所有 LangGraph 节点，捕获异常后 log + 重抛，SSE 外层统一返回 `error` 事件
- **final_node dynamic system prompt**：imp_ipt 通过 `_final_system_template.format(imp_ipt=...)` 注入 system 层独占最高注意力位
- **OSS 对象存储**：阿里云 OSS 集成，图片/文件上传后通过 URL 直接访问
- **异步日志**：`QueueHandler` + `QueueListener` 解耦业务线程与 IO，`atexit` 统一清理
- **桌面端打包**：Electron 41 + electron-builder 26 多平台打包（macOS / Windows / Linux），含 `file://` 协议拦截器等价 Vite dev proxy、↻ 页面刷新按钮、IPC `open-web-preview` 网页预览窗口

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
| 桌面端 | Electron 41 + electron-builder 26 |
| 样式 | CSS Variables + 原生 CSS |
| Markdown / 数学 | marked + highlight.js + katex |
| 桌面端关键能力 | `file://` 协议拦截（→ 后端代理）、SSE 流透传、↻ 页面刷新、多环境切换（dev/test/prod） |
| 特性 | 流式 SSE、主题切换、响应式布局、网页预览、头部刷新按钮 |

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
│   │   ├── ChatMeConfig/                 # 配置管理
│   │   ├── ChatService/                  # 聊天服务层（SSE 流式输出）
│   │   │   └── FilesLoaders/             # 文件加载与处理
│   │   ├── ChatWorkflow/                 # LangGraph 工作流核心
│   │   │   ├── config/                   # 图配置和 prompts
│   │   │   ├── decorators.py             # node_guard 节点异常统一兜底装饰器
│   │   │   ├── mcps/                     # MCP 工具服务器
│   │   │   └── Memory/                   # 记忆管理
│   │   ├── LoggingManager/               # 日志
│   │   └── test/                         # 单元测试
│   ├── skills/                           # 技能包（Bocha, Exa, Tavily, ImageParser, DataAnalysis）
│   ├── .chatme/                          # 局部配置（可选）
│   ├── pyproject.toml
│   └── main.py                           # FastAPI 入口
├── sandbox/                              # 代码沙盒 Docker 镜像
├── frontend/                             # Vue + Electron 前端（详见 frontend/README.md）
│   ├── electron/                         # 主进程 / preload / 配置
│   ├── src/                              # Vue 组件
│   └── vite.config.js
├── docker-compose.yml                    # Redis 服务编排
├── docker_data/                          # Redis 持久化数据
├── docs/                                 # 综合实践文档（详见 [设计文档](#设计文档)）
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
| `input_parse_node` | 输入预处理、文件解析（docling / VL）、输入优化（`improve_input`），给 `imp_ipt` 打 `additional_kwargs.imp_ipt=True` 标记 |
| `context_assembly_node` | 上下文组装（拼接 `imp_ipt`、memory、当前轮循环消息）、**ReAct 流程压缩**、中断检查 |
| `agent_node` | AI 代理决策，决定调用工具或结束；工具调用超过 20 次会发 SystemMessage 提示停止 |
| `tool_execution_node` | 工具执行（搜索 / MCP 工具 / Docker 沙盒），由 LangGraph 官方 `ToolNode` 提供 |
| `final_node` | 最终回复生成（独立于 agent 的 LLM），用 **dynamic system prompt** 把 `imp_ipt` 注入 system 层（不参与 messages 序列），输出带 SUMMARY 标记 |

### ReAct 流程压缩

`context_assembly_node` 在每轮组装时按"完整工具 loop 节拍"触发一次整体覆盖式压缩：

- **触发**：完整工具 loop 数 ≥ `REACT_COMPACT_LOOPS`（默认 5）+ `REACT_KEEP_LOOPS`（默认 2）= 7，**且** draft 字符数 ≥ `REACT_COMPACT_MIN_CHARS`（默认 2000），**且** `tool_call_times != last_compact_at_tool_calls`（防 state 恢复或失败后重复触发）。
- **范围**：压缩前 N-keep 轮 ReAct 轨迹，**最近 keep（默认 2）轮完整 loop 原文保留**；imp_ipt 之前的 memory / 其他 SystemMessage 整体保留。
- **产物**：以 `【ReAct 摘要】` SystemMessage 形式插入 imp_ipt 之后；写入 state 的 `context_summary_text` / `last_compact_at_tool_calls`。
- **失败兜底**：长度 [80, 4000] 区间外 / 过滤后只剩孤立标点（filter 漏网的 MiniMax-M3 tool_call 残骸）/ 含残留标签 / LLM 异常一律丢弃，context 保持不变。
- **专用 LLM**：`get_react_compact_config()`，`REACT_COMPACT_TEMPERATURE=0.3` / `REACT_COMPACT_MAX_TOKENS=5120`（env 可覆盖），目标 ≤ 4000 字中文 markdown。

> AI 协作者请阅读 [`CLAUDE.md`](CLAUDE.md) 获取完整的工作流说明、关键文件、协作偏好。

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
uv run chatme_mcp                                # 等价于 uv run python -m ChatMe.ChatWorkflow.mcps.server

# 另开终端，启动主服务（端口 8211）
uv run chatme_main                               # 等价于 uv run python main.py
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

### 配置文件示例（重命名为 config.json）

```json
{
  "app": {
    "name": "ChatMe",
    "version": "v0.0.1",
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

## 项目结构

```
ChatMe/
├── backend/
│   ├── ChatMe/
│   │   ├── APIRouter/
│   │   ├── ChatMeConfig/                 # 配置加载器
│   │   ├── ChatService/
│   │   │   ├── core.py                   # ChatService，SSE 流式输出 + 记忆任务调度
│   │   │   ├── RedisStateSaver/          # 自建 checkpoint 索引
│   │   │   └── FilesLoaders/             # 文件加载 + 大文件截断
│   │   ├── ChatWorkflow/
│   │   │   ├── core.py                   # 工作流定义，5 个 LLM 实例 + ReAct 流程压缩
│   │   │   ├── decorators.py             # node_guard 装饰器：所有节点异常统一捕获
│   │   │   ├── config/
│   │   │   │   ├── graph_config.py       # prompts 和模型配置（含 react_compact）
│   │   │   │   └── models.py             # ChatStateCore2 / FileParseState
│   │   │   ├── mcps/
│   │   │   │   ├── server.py             # FastMCP 工具入口
│   │   │   │   └── CodeSandboxPool.py    # Docker 容器池
│   │   │   └── Memory/                   # 长期记忆（per-thread Lock + 原子写）
│   │   ├── LoggingManager/               # 异步日志（QueueHandler + QueueListener）
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
├── docs/                                 # 综合实践文档
└── docker_data/
```

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

`backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py` 提供基于 Docker 容器的安全代码执行能力：

- **预启动容器池**：默认 2 个常驻容器（`sleep infinity`），按需取用 / 归还
- **隔离环境**：使用 tmpfs 限制 `/tmp`、`/sandbox`（各 64m，noexec）
- **预装库**：numpy、pandas、scipy、scikit-learn、sympy、matplotlib、seaborn、plotly、bokeh、altair、pygal、pyecharts、folium、networkx、requests、bs4、lxml、openpyxl、xlrd、pillow、jinja2、markupsafe（阿里云 PyPI 镜像）
- **执行流程**：`docker cp` 注入代码 → `docker exec` 运行 → 清空沙盒目录 → 归还容器
- **两个执行入口**：
  - `execute(code, lang)` —— code 工具：写 `/code.<py|js>` → `python /code.<py|js>` → `rm -f`（避免敏感信息残留）
  - `execute_command(cmd)` —— cmd 工具：直接 `docker exec -w / sh -c <cmd>`，命令里可含管道 / 重定向 / glob
- **池锁结构**：`pop → exec → append` 整段在 `with self.lock:` 内串行化，避免 N+1 并发撞空池报 `No available containers in pool`
- **超时保护**：单次执行 30s 超时
- **自动恢复**：检测到容器未运行时自动重建

容器池大小可在 `SandboxPool(size=N)` 调整。

### 沙盒 vs 本地 venv 语义对齐

- **沙盒**：容器内 cwd=`/`，挂载点 `/cached` / `/skills`；AI 写代码用相对路径 `cached/xxx` / `skills/xxx`。
- **本地 venv 降级**（`mcps/server.py:_execute_code_in_local`）：宿主机 cwd=`backend/`，`backend/cached/` / `backend/skills/` 真实存在；PYTHONPATH 同时包含 `backend/` + `skills/`，让 `import Exa` / `from ChatMe.xxx import xxx` 都能解析；临时文件写到 `/tmp/code.<py|js>`。
- 两边写代码时统一使用相对路径，AI 不需要感知运行在沙盒还是本地。

## MCP 工具

MCP 服务器（`mcps/server.py`，FastMCP 3.x）暴露以下核心工具：

| 工具 | 说明 |
|------|------|
| `execute_code` | 默认在 Docker 沙盒中执行 Python / Node.js 代码（`use_sandbox=False` 降级到本机 venv） |
| `execute_command` | 默认在 Docker 沙盒中执行白名单内的 shell 命令（`use_sandbox=False` 降级到本机 subprocess.run）；带危险命令检测 |
| `interrupt` | 中断当前对话 |
| `get_current_datetime` | 获取当前日期时间 |

每个 tool 函数都带 `session_id` 参数。

**沙盒执行入口**（`mcps/CodeSandboxPool.py`）：
- `execute(code, lang)` — code 工具用，先把 code 写到容器 `/code.<py\|js>` 再跑，跑完立即删（避免敏感信息残留）
- `execute_command(cmd)` — cmd 工具用，直接 `docker exec sh -c <cmd>`，命令里可含管道 / 重定向 / glob

两者共享同一池（默认 2 容器），`pop → exec → append` 整段走 `self.lock`，避免 N+1 并发撞空池。

## 设计文档

`docs/综合实践文档/` 目录下提供了完整的设计资料（**该目录在 `.gitignore` 中，仅在本地存在**）：

| 文件 | 内容 |
|------|------|
| `01_需求规格说明书.md` | 需求规格说明书 |
| `02_概要设计说明书.md` | 概要设计说明书 |
| `03_详细设计说明书.md` | 详细设计说明书 |
| `部署图.png` | 系统部署架构图 |
| `时序图.png` | 关键时序图 |
| `程序流程图/` | 程序流程图目录 |

每个 `.md` 文件有对应的 `.docx` 版本。如果目录缺失，请从团队渠道获取。

## 部署打包

### 构建 wheel 包

```bash
cd backend
uv build --wheel
# 输出: dist/ChatMe-0.0.1-py3-none-any.whl
```

### 安装 wheel

```bash
uv pip install dist/ChatMe-0.0.1-py3-none-any.whl
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
npm install

# 当前平台
npm run electron:build

# 明确指定平台
npm run electron:build:mac      # macOS arm64 + x64（DMG + ZIP）
npm run electron:build:win      # Windows NSIS（x64）
npm run electron:build:linux    # Linux AppImage（x64）
```

桌面端通过 `electron-builder` 打包，应用信息（应用名「灵析」、identifier `com.chatme.app`、版本 0.0.1）在 `frontend/electron/electron.config.js` 中配置。

**图标路径双形态**：`build/`（`icon.icns` / `icon.ico` / `icon.png`）通过 `package.json` 的 `extraResources` 复制到 `app/Contents/Resources/build/`，运行时用 `process.resourcesPath` 读取；`nativeImage` 不能读 asar 内文件，所以必须放包外。

**输出位置**：`../release/electron-builder/`（项目根，与 Vite 的 `dist/` / `frontend/` 区分开）：
- `mac-arm64/灵析.app` — 直接打开
- `mac/` — x64 .app
- `灵析-0.0.1-arm64-mac.zip` / `灵析-0.0.1-mac.zip` — 分发包
- `linux-unpacked/` — Linux 解压目录
- `win-unpacked.exe` — Windows 安装器

**DMG 镜像问题**：dmg-builder 在 npmmirror 缺包，DMG 阶段会 404。绕过方案：
- 只打 zip：`npx electron-builder --mac zip --arm64 --x64`
- DMG 走 GitHub 直链：`ELECTRON_BUILDER_BINARIES_MIRROR=https://github.com npx electron-builder --mac dmg`

**Electron 核心机制**（详见 `frontend/README.md`）：
- `protocol.handle('file', ...)` 在 `app.whenReady()` 内注册，把 `/chat/*` 和 `/static/*` 转发到后端（等价 Vite dev proxy）；其他 `file://` 走白名单校验后从 asar 内 `dist/` 读盘
- API 转发必须显式带 `method/headers/body + duplex: 'half'`（POST `/chat/` 的 body 否则被丢），SSE 流必须显式 `new Response(upstream.body, ...)` 透传避免被 buffer
- 多环境由 `NODE_ENV` 严格控制：`development` / `test` / `production` 分别走 Vite dev / Vite dev / 本地 dist；`app.isPackaged` 仅用于决定图标路径来源

## 开发注意事项

1. **MCP 服务器**必须单独启动，首次启动会自动检查 Redis 并清理残留沙盒容器
2. **Redis** 通过 `docker-compose up -d redis` 启动，端口 6024，密码 `123456`
3. **代码沙盒**需要先 `docker-compose build sandbox` 构建镜像
4. **思考内容过滤**：后端 `_filter_thinking_content` 过滤 AI 输出中的 `<thinking>` 等思考标签
5. **流式响应**：前端通过 SSE 实时接收 `content` / `reasoning` / `tool_call_*` / `memory_wait_*` / `error` 事件；`memory_wait_start` / `memory_wait_done` 在新请求发起 / 中断续接 且上一轮记忆任务仍在后台时插入；`interrupt` / `done` 事件携带 `memory_status` 字段（`idle` / `pending` / `done` / `failed`）
6. **配置脱敏**：`backend/.chatme/config.json` 包含真实 API key，提交时务必脱敏
7. **多 LLM Provider**：可通过 `llm_providers` 切换 openai / deepseek / vl（本地 VL）；`react_compact` 共用活动 provider，可通过 `REACT_COMPACT_TEMPERATURE` / `REACT_COMPACT_MAX_TOKENS` 单独配参
8. **OSS**：图片 / 文件上传后通过 OSS URL 访问，缓存目录在 `cached/`
9. **环境探索模式**：当文件被截断时（提示中含 `[文件过大已截断]`），AI 应走 `execute_command(ls cached/...)` + `cat cached/.../filename` 流程读全量
10. **unstructured 首次使用**：CSV / MD / XML 解析会自动下载 NLTK 数据（punkt、averaged_perceptron_tagger 等），需外网环境
11. **ReAct 流程压缩**：`context_assembly_node` 按"完整工具 loop 节拍"自动压缩（前 N-keep 轮被摘要，最近 2 轮原文保留）；`REACT_COMPACT_LOOPS=5` / `REACT_KEEP_LOOPS=2` / `REACT_COMPACT_MIN_CHARS=2000` / 摘要上限 `4000` 字 / `REACT_COMPACT_MAX_TOKENS=5120`；压缩失败不 raise；`_filter_thinking_content` 已带 MiniMax-M3 wrapper 正则（`[</tool_call>]` / `[<]tool_call[>]` 等）+ `_try_compact_react` 孤立标点兜底，react_compact prompt 显式禁止 tool_call 块
12. **Memory 并发安全**：`MemoryManager` 内部 per-thread `asyncio.Lock` 串行化；新加 memory 方法必须继承 `async with self._get_thread_lock(thread_id)`；写盘走 `_atomic_write_text`（`*.tmp` + `fsync` + `os.replace`）
13. **ChatService 记忆任务串行**：每会话只有一个后台 `_update_memory_bg` 任务（`_memory_update_tasks[session_id]`），新请求 / 删除 / 回溯前会先 `_wait_previous_memory_update` 等待；新入口必须先等待，避免读到旧记忆或与后台 task 写竞争
14. **异步日志**：`LoggingManager` 用 `QueueHandler` + `QueueListener` 写文件，业务线程不入 IO；`atexit` 统一 `listener.stop()` 清理，新增 logger 走 `set_logger`
15. **imp_ipt 唯一标识**：`input_parse_node` 输出的 `imp_ipt` 身份是 `additional_kwargs.imp_ipt == True`；ReAct 压缩 / final_node 注入 / 后续扩展都靠这个标志定位本轮意图
16. **节点异常统一兜底**：所有 LangGraph 节点（含 ChatWorkflow 5 个主节点 + 文件图 3 个节点 + sub_agent agent_node）都通过 `@node_guard("<name>")` 装饰；新加节点必须继承这个约定，否则异常会穿透到 LangGraph 内核造成不可预期行为
17. **前端错误气泡保护**：App.vue 维护 `_sessionHadError: Set<session_id>`，SSE 出现 `error` 时把 `message.error=true` 渲染为红色错误框（避免报错堆栈被当 markdown），同时把 session 标记为保护态；保护态下 `done` 事件不会复活 AI 内容，`refreshConversation` / `updateTitleAndRefresh` 跳过 messages 重拉只更新侧边栏；用户主动发起新一轮请求或续接时清掉保护态
18. **SandboxPool 池锁必须包整段**：池默认 2 容器，新加 `execute_*` 方法时必须把 `pop → exec → append` 整段放在 `with self.lock:` 内；不能像最初 `execute()` 那样把 pop 放锁外只锁 exec——并发 N+1 会撞空池报 `No available containers in pool`
18. **Electron `file://` 协议拦截**：`protocol.handle('file', ...)` 在 `app.whenReady()` 内注册（必须 ready 才能拿到 `session.defaultSession`），`/chat/*` + `/static/*` 转发到后端（等价 Vite dev proxy），其他走白名单校验后从 asar 内 `dist/` 读盘；API 转发必须显式带 `method/headers/body + duplex:'half'`（POST `/chat/` 的 body 否则被丢），SSE 流必须显式 `new Response(upstream.body, ...)` 透传避免被 buffer
19. **Electron 图标必须放包外**：`nativeImage` 不能读 asar 内文件，所以 `build/` 通过 `extraResources` 复制到 `app/Contents/Resources/build/`，运行时用 `process.resourcesPath` 取；`app.dock.setIcon` / `BrowserWindow.icon` 都必须是 PNG，不认 `.icns`（打包后的 `.icns` 由 `package.json` 的 `build.mac.icon` 给 OS 用）
20. **可滚动侧栏/面板 CSS**：所有可滚动列表（Sidebar / DataAnalysisTree / WebPreviewPanel / CheckpointPanel 等）必须按以下 7 条点写——① 数据全量入 DOM，禁止 `slice(0, N)` / `displayCount` 切片（CSS overflow 自己负责滚动）；② 侧栏 `height: 100vh; flex-shrink: 0; overflow: hidden`，外层不被内容撑大；③ 固定头部 `flex-shrink: 0` 锁尺寸；④ 滚动区用 `height: calc(100vh - X)` **不走** `flex: 1 + min-height: 0`（flex 子项 `min-height: auto` 会让 overflow 失效）；⑤ **`overflow-y: auto`**——浏览器默认；禁止用 `overflow-y: scroll`（始终空占位，列表短时也碍眼）或 `overflow-y: hidden`（用户感知不到还有内容）；⑥ **CSS-only 没法做到「溢出时才显示」**：`App.vue` 全局 `::-webkit-scrollbar { width: 8px; ... }` 会强制 macOS 自动隐藏失效。要做到溢出时才出现必须 JS + class：mounted 用 `ResizeObserver` 监听 list；`el.scrollHeight > el.clientHeight + 1` 判定溢出；挂 `.has-overflow` class；CSS：`::-webkit-scrollbar { width: 0 }` 默认隐藏，`.has-overflow::-webkit-scrollbar { width: 6px }` 才显出，滑块 `var(--border-color)` + `min-height: 30px`，hover `var(--text-secondary)`；⑦ `@scroll="handleScroll"` 直接绑在 `.list`。同时监听 conversations 增删 / collapsed 切换 / window resize，触发 `checkOverflow()` 重新挂载 class。

## 许可证

本项目为内部项目，许可证信息请参考项目根目录 LICENSE 文件（如有）。