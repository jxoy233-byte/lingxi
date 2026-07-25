# ChatMe（灵析 Lingxi）

基于 LangGraph 的多智能体数据分析对话系统。支持流式响应、工具调用、对话记忆管理、文档/图片多模态解析，以及基于 Docker 沙盒的安全 Python 代码执行。同时提供 Web 端和 Electron 桌面端两种运行形态。

> AI 协作者请阅读 [`CLAUDE.md`](CLAUDE.md) 获取完整的工作流说明、关键文件、协作偏好与踩坑记录。

---

## 目录

- [项目特性](#项目特性)
- [界面预览](#界面预览)
- [技术栈](#技术栈)
- [架构概览](#架构概览)
- [工作流](#工作流)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [API 概览](#api-概览)
- [代码沙盒](#代码沙盒)
- [MCP 工具](#mcp-工具)
- [效果展示](#效果展示)
- [设计文档](#设计文档)
- [部署打包](#部署打包)
- [开发注意事项](#开发注意事项)
- [许可证](#许可证)

---

## 项目特性

- **多智能体工作流**：基于 LangGraph StateGraph 实现 `input_parse → context_assembly → agent_node ↔ tool_execution_node → final_node` 循环
- **ReAct 流程压缩**：`context_assembly_node` 按完整工具 loop 节拍自动压缩长 ReAct 轨迹，`imp_ipt` 标记做切分锚点，最近 keep 轮原文保留（详见 CLAUDE.md）
- **流式 SSE 响应**：前端通过 EventSource 实时接收 `content` / `reasoning` / `tool_call_*` / `memory_wait_*` 事件
- **多模态文件解析**：图片（OSS / base64）、文本（CSV / JSON / MD / TXT / XML）、文档（PDF / Word / PowerPoint / Excel），docling + qwen-vl-utils + unstructured
- **Docker 沙盒执行**：预启动容器池 + tmpfs 隔离，提供安全的 Python 数据分析环境
- **多 LLM Provider**：OpenAI / DeepSeek / 本地 VL（Qwen3-VL-2B）统一抽象，5 个独立 LLM（core / agent / summary / react_compact / imp_ipt）可分别配参
- **对话记忆**：Redis checkpointer 状态恢复 + 自建 memory manager 长期记忆；per-thread Lock + 原子写 + 后台任务串行
- **节点异常统一兜底**：`@node_guard` 装饰器包住所有 LangGraph 节点，异常后 SSE 外层统一返回 `error` 事件
- **OSS 对象存储**：阿里云 OSS，图片 / 文件上传后通过 URL 直接访问
- **桌面端打包**：Electron 41 + electron-builder 26 多平台打包，含 `file://` 协议拦截器等价 Vite dev proxy、↻ 刷新按钮、网页预览窗口

## 界面预览

![ChatMe 主界面](docs/img/界面.png)

主界面分区：左侧会话列表（支持新建 / 切换 / 删除）+ 中间对话区（流式 SSE 实时渲染 `reasoning` / `tool_call_*` / `content` 事件）+ 下方输入框（文件上传 / 语音输入 / 发送）。思考过程可折叠展开，工具调用次数实时统计。

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
| 桌面端关键能力 | `file://` 协议拦截（→ 后端代理）、SSE 流透传、↻ 刷新按钮、多环境切换 |
| 特性 | 流式 SSE、主题切换、响应式布局、网页预览 |

## 架构概览

```
ChatMe/
├── backend/
│   ├── ChatMe/
│   │   ├── APIRouter/                    # FastAPI 路由（/chat /static /api /admin）
│   │   ├── ChatMeConfig/                 # 配置管理
│   │   ├── ChatService/                  # 聊天服务层（SSE 流式输出）
│   │   │   └── FilesLoaders/             # 文件加载与处理
│   │   ├── ChatWorkflow/                 # LangGraph 工作流核心
│   │   │   ├── config/                   # 图配置与 prompts
│   │   │   ├── decorators.py             # node_guard 节点异常统一兜底
│   │   │   ├── mcps/                     # MCP 工具服务器 + Docker 沙盒
│   │   │   └── Memory/                   # 长期记忆管理
│   │   ├── LoggingManager/               # 异步日志
│   │   └── test/                         # 单元测试
│   ├── skills/                           # 技能包（Bocha / Exa / Tavily / ImageParser / DataAnalysis）
│   ├── .chatme/                          # 局部配置（仓库内已含）
│   ├── pyproject.toml
│   └── main.py                           # FastAPI 入口
├── sandbox/                              # 代码沙盒 Docker 镜像（Python 3.12）
├── frontend/
│   ├── electron/                         # 主进程 / preload / 配置
│   ├── src/                              # Vue 组件
│   └── vite.config.js
├── docker-compose.yml                    # Redis 服务编排
├── docker_data/                          # Redis 持久化
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

| 节点 | 职责 |
|------|------|
| `input_parse_node` | 输入预处理、文件解析（docling / VL）、输入优化，给 `imp_ipt` 打 `additional_kwargs.imp_ipt=True` 标记 |
| `context_assembly_node` | 上下文组装 + **ReAct 流程压缩** + 中断检查 |
| `agent_node` | AI 决策，决定调用工具或结束；工具调用超过 20 次会注入 SystemMessage 提示停止 |
| `tool_execution_node` | 工具执行（搜索 / MCP / Docker 沙盒），由 LangGraph 官方 `ToolNode` 提供 |
| `final_node` | 最终回复生成（独立 LLM），用 dynamic system prompt 把 `imp_ipt` 注入 system 层，输出带 SUMMARY 标记 |

State 定义在 `backend/ChatMe/ChatWorkflow/config/models.py`（`ChatStateCore2` / `FileParseState`）。完整工作流说明、ReAct 压缩实现、关键文件、协作偏好见 [`CLAUDE.md`](CLAUDE.md)。

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

# 启动 MCP 服务器（端口 28211）
# 首次启动会自动：1) 检查 Redis  2) 清理残留沙盒容器  3) 初始化沙盒池
uv run chatme_mcp                                # 等价于 uv run python -m ChatMe.ChatWorkflow.mcps.server

# 另开终端，启动主服务（端口 8211）
uv run chatme_main                               # 等价于 uv run python main.py
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev  # 访问 http://localhost:18211
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
    "version": "v0.0.3",
    "host": "127.0.0.1",
    "port": 8211
  },
  "mcp_server": {
    "url": "http://127.0.0.1:28211/streamable",
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
│   │   │   ├── core.py                   # 工作流定义，5 个 LLM 实例 + ReAct 压缩
│   │   │   ├── decorators.py             # node_guard 装饰器
│   │   │   ├── config/
│   │   │   │   ├── graph_config.py       # prompts 与模型配置
│   │   │   │   └── models.py             # ChatStateCore2 / FileParseState
│   │   │   ├── mcps/
│   │   │   │   ├── server.py             # FastMCP 工具入口
│   │   │   │   └── CodeSandboxPool.py    # Docker 容器池
│   │   │   └── Memory/                   # 长期记忆
│   │   ├── LoggingManager/               # 异步日志
│   │   └── test/
│   ├── skills/                           # 技能包
│   ├── .chatme/
│   ├── pyproject.toml
│   └── main.py
├── sandbox/
│   └── Dockerfile                        # Python 3.12 + 数据分析库
├── frontend/
│   ├── electron/                         # 桌面端
│   ├── src/                              # Vue 组件
│   └── vite.config.js
├── .test_agent/
│   └── test_agent.md                     # AI 多轮对话测试 Agent 指南（见开发注意事项）
├── docker-compose.yml
├── docs/                                 # 文档
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
| `/static/cached/{file_path:path}` | GET | 访问 cached 目录静态文件；详见 [静态文件 fallback](#静态文件-fallback) |
| `/api/v1/chat/completions` | POST | 视觉语言模型服务（本地 Qwen3-VL） |
| `/admin/cleanup` | POST | 手动触发清理任务 |
| `/admin/cleanup/status` | GET | 获取清理状态 |

#### 静态文件 fallback

`serve_cached_file` 在精确路径命中失败时按以下规则走 fallback：

1. **带 sid 路径（`cached/{32-hex}/...` 或 `{32-hex}/...`）找不到 → 直接 404**：不去跨会话命中同名文件，避免误把别人 session 的产物当成本会话的图。
2. **无 sid 路径找不到 → 双层 fallback**：
   - **第一层（primary）**：从 `Referer` header 提取 32hex sid（如 `http://localhost:18211/{sid}` 或 `http://localhost:18211/{sid}/foo`），优先在 `cached/{referer_sid}/` 下递归找同名文件
   - **第二层（兜底）**：跨 `cached/*/` 所有 session 子目录递归查找同名文件（`rglob("**/*")`），按 `st_mtime` 降序排序，**最新修改时间**的文件胜出
   - Referer 缺失（隐私模式 / `no-referrer` 策略）/ 不含 sid / 异常格式 → 自动跳过第一层直接走第二层
3. **都无命中 → 404**。

**为什么用 Referer 推断 sid 而不是 `X-Session-Id` 自定义 header**：浏览器 `<img>` 标签加载 markdown 图片（fallback 主要场景）**不能**加自定义 header（浏览器规范限制），EventSource 也不能；只有 fetch 类 API 请求能加。所以 fallback 服务的核心场景（`<img>` 加载裸文件）只能靠浏览器自动带的 `Referer` 拿当前会话 sid，让 fallback 优先返回当前会话的产物。

**适用场景**：AI agent 输出的 markdown 图片用 `./data_analysis/foo.png` 这种**无 sid** 的相对路径时（前端会拼成 `/static/data_analysis/foo.png`），浏览器从当前会话页面发起请求时 Referer 自带 sid，fallback 会优先返回当前会话产物；找不到再跨 sid 取最新同名文件兜底。

## 代码沙盒

`backend/ChatMe/ChatWorkflow/mcps/CodeSandboxPool.py` 提供基于 Docker 容器的安全代码执行：

- **预启动容器池**：默认 2 个常驻容器（`sleep infinity`），按需取用 / 归还
- **隔离环境**：tmpfs 限制 `/tmp`、`/sandbox`（各 64m，noexec）
- **预装库**：numpy / pandas / scipy / scikit-learn / sympy / matplotlib / seaborn / plotly / bokeh / altair / pygal / pyecharts / folium / networkx / requests / bs4 / lxml / openpyxl / xlrd / pillow / jinja2 / markupsafe（阿里云 PyPI 镜像）
- **两个执行入口**：
  - `execute(code, lang)` —— code 工具：写 `/code.<py|js>` → 运行 → `rm -f`（避免敏感信息残留）
  - `execute_command(cmd)` —— cmd 工具：直接 `docker exec sh -c <cmd>`，可含管道 / 重定向 / glob
- **超时保护**：单次执行 30s 超时
- **自动恢复**：检测到容器未运行时自动重建

容器池大小可在 `SandboxPool(size=N)` 调整。沙盒不可用时降级到本机 venv（`backend/cached/` / `backend/skills/`）。

## MCP 工具

MCP 服务器（`mcps/server.py`，FastMCP 3.x）暴露以下核心工具：

| 工具 | 说明 |
|------|------|
| `execute_code` | 默认在 Docker 沙盒中执行 Python / Node.js 代码（`use_sandbox=False` 降级到本机 venv） |
| `execute_command` | 默认在 Docker 沙盒中执行白名单内的 shell 命令（`use_sandbox=False` 降级到本机）；带危险命令检测 |
| `interrupt` | 中断当前对话 |
| `get_current_datetime` | 获取当前日期时间 |

每个 tool 函数都带 `session_id` 参数。

## 效果展示

### 数据分析对话效果

下面是一次完整的数据分析请求（让 AI 对清洗好的数据集做 EDA 探索性分析）的输出节选。AI 通过 `execute_code` 工具在 Docker 沙盒中调用 matplotlib / seaborn 生成图表，结果通过 `static/cached/` 路径返回前端渲染：

![EDA 探索性分析图表](docs/img/对话效果.png)

> 三张图分别为：① AIGC 置信度分数分布直方图（带阈值参考线）② 不同置信度等级下的媒体类型偏好柱状图 ③ 发帖时段 × 星期的热力图（Hour × Weekday）。所有图表由 AI 在沙盒内生成后自动嵌入到回复流中。

### 完整分析输出

下面是一次 AIGC 数据挖掘任务的完整 AI 回复，展示了 agent_node 在多轮工具调用 + 长上下文压缩 + 最终回复生成的完整链路：

![完整分析输出](docs/img/图效果.png)

> 输出包含：① 数据集概览（行数 / 字段数 / 文件大小）② 数据质量报告（缺失率 / 重复值 / 长尾分布）③ 衍生字段说明 ④ 关键发现总结 ⑤ 完整可复用的执行脚本。整套流程通过 ReAct 循环（agent_node ↔ tool_execution_node）驱动，最终在 final_node 用独立 LLM + dynamic system prompt 整合输出。

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

### 启动与依赖

1. **MCP 服务器**必须单独启动，首次启动会自动检查 Redis 并清理残留沙盒容器
2. **Redis** 通过 `docker-compose up -d redis` 启动，端口 6024，密码 `123456`
3. **代码沙盒**需要先 `docker-compose build sandbox` 构建镜像
4. **unstructured 首次使用**：CSV / MD / XML 解析会自动下载 NLTK 数据（punkt、averaged_perceptron_tagger 等），需外网环境
5. **配置脱敏**：`backend/.chatme/config.json` 包含真实 API key，提交时务必脱敏

### 流式响应

前端通过 SSE 实时接收 `content` / `reasoning` / `tool_call_*` / `memory_wait_*` / `error` 事件：
- `memory_wait_start` / `memory_wait_done` 在新请求发起 / 中断续接 且上一轮记忆任务仍在后台时插入
- `interrupt` / `done` 事件携带 `memory_status` 字段（`idle` / `pending` / `done` / `failed`）

### AI 协作者约定

工作流实现细节（`imp_ipt` 锚点、ReAct 压缩清空 AIMessage.content + filter 兜底、`@node_guard` 装饰器、`_filter_thinking_content` MiniMax-M3 wrapper（含 `<tool_calls>` / `[<invoke name="cmd">][<command>...]` 7 个变体）、`MemoryManager` per-thread Lock、SandboxPool 池锁整段、Electron `file://` 三件套与图标包外、侧栏 CSS 7 条、流式会话快照 19 条、删除会话行内二次确认（小红叉状态机 + document click / Esc 取消，详见偏好 21）等）见 [`CLAUDE.md`](CLAUDE.md)。新增节点 / 流式 SSE 入口 / 执行方法 / 二次确认交互前必须先读对应章节。

### AI 测试 Agent（多轮对话测试）

`.test_agent/test_agent.md` 是给后续 AI 协作者跑多轮对话测试的完整指南——硬约束（MCP 单调用 ≤280s / 单 batch ≤12 轮）、工具链（首选 Codex IAB 浏览器，备选本地 Chrome + CDP）、DOM 节点 selector、单 batch 完整流程代码、报告生成代码、4 个已确认的真实后端缺陷都在那。**接手后做端到端测试前必须先读这个文件**，不要凭直觉写 Playwright 脚本。已知 4 个真实后端缺陷（测试时遇到是已知问题，不是新 bug）：

1. 跨多轮记忆上限：19+ 轮 R12/R17 失败（IAB 状态丢失，非 LLM）
2. 优化输入无效：`POST /chat/improve_input` 返回的 `improved_text` 与原文完全相同
3. 业务复杂题卡死：复杂业务题（T08 类）触发 20+ 分钟无限工具调用循环
4. IAB 路由状态不稳：新会话 URL 在 R1 后从 `/` 跳到 `/<hash>`，可丢失前端历史

### AI 定时优化 Agent（cron job）

`~/.claude/scheduled_tasks.json` 里的持久化 cron job `a09d41ec` **每小时 :23 自动触发** ChatMe 后端优化 Agent：读 `.chatme/logs/thinking_chain-*.log`，按 ✅/❌ 清单自主优化 prompt / AI 配置（详见 CLAUDE.md "AI 自动化工具 → 定时优化 Agent"）。7 天后自动过期，需要时续期。

## 许可证

本项目为内部项目，许可证信息请参考项目根目录 LICENSE 文件（如有）。