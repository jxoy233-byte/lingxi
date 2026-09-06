# Lingxi™（灵析™）

基于 LangGraph 的单智能体 + 多 LLM 角色数据分析对话系统。支持流式响应、工具调用、对话记忆管理、文档/图片多模态解析，以及基于 Docker 沙盒的安全 Python 代码执行。同时提供 Web 端和 Electron 桌面端两种运行形态。

> 贡献者 / 开发者 / AI 协作者请阅读 [`docs/contributing.md`](docs/contributing.md) 与 [`CLAUDE.md`](CLAUDE.md)：前者汇总开发约定、踩坑记录与 AI 自动化工具，后者是 AI 协作者的工作流指南。

---

## 目录

- [项目特性](#项目特性)
- [界面预览](#界面预览)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [API 概览](#api-概览)
- [代码沙盒](#代码沙盒)
- [MCP 工具](#mcp-工具)
- [定时任务（Scheduler skill）](#定时任务scheduler-skill)
- [效果展示](#效果展示)
- [部署打包](#部署打包)
- [开发注意事项](#开发注意事项)
- [许可证](#许可证)

---

## 项目特性

### v0.1.x 核心能力

- 多智能体工作流 + ReAct 压缩（5 LLM 角色 + 4 阶段后台异步压缩）
- 流式 SSE / 多模态文件解析 / Docker 沙盒 / Redis checkpoint
- 命令级权限审批（`cmd`/`code` 走 LangGraph interrupt()，4 档决策 + Redis hash）
- 数据库只读分析（MySQL / SQLite / PostgreSQL / MongoDB 跨会话配置）
- 一键导出（产物 ZIP / HTML + 对话历史 OpenAI JSON + state 备份）

### v0.2.0 工作流升级

- `_create_graph_improved` 替换老图，引入 MCP `done` 工具作为收尾信号
- 移除 `should_end_node` LLM 决策节点，纯结构化路由
- ReAct 压缩健壮性（pending loop 数阈值 / DETECTION_MIN 4→5 / 防重复压缩 flag）
- 许可证 + 商标（MIT + 「灵析™」/「Lingxi™」）

### v0.2.1 配置 + 启动链路

- SetupView 向导（5 步配置，segment 级热加载）
- 应用启动链路健壮性（`fixRedis` ping-first / 端口预检 / Windows 盘符修复 / `_hasEverConnected` banner 抑制）
- SandboxPool 容器名 + label 双标识 + sha1 seed（pid+time+counter）
- 全局重启遮罩（统一 `handleRestartBackend()`，3 处入口共用）

## 界面预览

![ChatMe 主界面](docs/img/界面.png)

主界面分区：左侧会话列表（支持新建 / 切换 / 删除）+ 中间对话区（流式 SSE 实时渲染 `reasoning` / `tool_call_*` / `content` 事件）+ 下方输入框（文件上传 / 语音输入 / 发送）。思考过程可折叠展开，工具调用次数实时统计。

工作流架构、节点职责、ReAct 压缩实现、5 LLM 角色分工见 [`CLAUDE.md`](CLAUDE.md)。

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
# RedisInsight 端口 8001 -> 主机 28001
# 密码：123456
```

### 1. 启动后端

```bash
cd backend
uv sync                                          # 安装依赖

# 启动主服务（默认端口 38211，stdio 模式下会 fork MCP 子进程）
# 首次启动会自动：1) 检查 Redis  2) 清理残留沙盒容器  3) 初始化沙盒池
uv run chatme_main                               # 等价于 uv run python main.py

# 开发模式单独起 MCP（stdio 模式，监听 stdin/stdout）——
# chatme_main 会自动 fork 它，正常运行不需要手动起
uv run chatme_mcp                                # 等价于 uv run python -m ChatMe.ChatWorkflow.mcps.server
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
# 容器池 min=1, max=4（per_container_concurrency=8）；按需动态扩缩容 + 闲置 GC（见 `ChatWorkflow/mcps/sandbox/pool.py`）
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
    "version": "v0.2.1",
    "host": "127.0.0.1",
    "port": 38211
  },
  "redis": {
    "checkpointer_url": "redis://:123456@localhost:6024/0",
    "state_saver_url":   "redis://:123456@localhost:6024/1"
  },
  "llm_providers": {
    "openai":   { "model_name": "gpt-4o", "api_key": "...", "base_url": "https://api.openai.com/v1" },
    "deepseek": { "model_name": "deepseek-chat", "api_key": "...", "base_url": "https://api.deepseek.com/" },
    "vl":       { "model_name": "Qwen3-VL-2B", "base_url": "http://127.0.0.1:38211/api/v1", "local": true }
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
│   │   ├── ChatMeConfig/                 # 配置加载（_load mtime + 热加载）
│   │   ├── ChatService/                  # SSE 流式 + 记忆任务调度
│   │   ├── ChatWorkflow/                 # LangGraph 5 节点 + ReAct 压缩 + Memory + mcps(server/session/permissions/sandbox/tools)
│   │   ├── LoggingManager/               # QueueHandler 异步日志
│   │   └── APIRouter/                    # /chat /static /api /admin
│   ├── skills/
│   │   ├── DataAnalysis/                 # 数据分析 + 数据库（只读 4 引擎）+ 中文字体
│   │   ├── Scheduler/                    # 定时任务 skill
│   │   ├── Memory/                       # 跨会话记忆
│   │   ├── SkillForge/                   # 动态创建 skill
│   │   ├── Bocha / Exa / Tavily          # 搜索 skill（GET ping 探活见 _search_health.py）
│   │   └── ImageParser/                  # 图片解析
│   ├── .chatme/
│   ├── pyproject.toml
│   └── main.py                           # FastAPI 入口
├── sandbox/Dockerfile                    # Python 3.12 + 数据分析库
├── frontend/                             # Vue 3 + Electron 桌面端
├── .test_agent/test_agent.md             # AI 多轮对话测试 Agent 指南
├── docker-compose.yml                    # Redis 服务编排（端口 6024）
├── LICENSE                               # MIT License
├── NOTICE                                # 上游依赖归属
├── THIRD_PARTY_LICENSES.md               # 第三方许可证汇总
└── docs/
```

## API 概览

后端通过 4 个 Router 暴露接口。

### 聊天接口（`/chat` 前缀）

| 接口                                            | 方法        | 说明                     |
| --------------------------------------------- | --------- | ---------------------- |
| `/chat/`                                      | POST      | 流式对话（无 session_id 则新建） |
| `/chat/conversations`                         | GET       | 会话列表                   |
| `/chat/{session_id}/conversation`             | GET       | 会话详情                   |
| `/chat/{session_id}/title`                    | GET / PUT | 获取 / 修改会话标题            |
| `/chat/{session_id}/clear`                    | DELETE    | 删除会话（含聊天记录）            |
| `/chat/{session_id}/backtrack`                | POST      | 会话回溯                   |
| `/chat/{session_id}/interrupt`                | POST      | 中断对话                   |
| `/chat/{session_id}/invoke_interrupted/{msg}` | POST      | 中断续接对话                 |
| `/chat/{session_id}/permission/decide`        | POST      | 审批权限决策（4 档：`approve` / `this-time-only` / `deny` / `feedback:<text>`）；决策存 Redis hash 后用 `Command(resume=...)` 唤醒 LangGraph 中断点 |
| `/chat/{session_id}/permission/resume`        | POST (SSE)| 决策后 resume permission 中断的 tool call，沿用 `message_stream` 同构 SSE（content / reasoning / tool_call_* / done） |
| `/chat/{session_id}/upload_file`              | POST      | 上传文件                   |
| `/chat/cancel_upload_file`                    | POST      | 取消已上传文件                |
| `/chat/improve_input`                         | POST      | 优化用户输入                 |
| `/chat/file-config`                           | GET       | 获取文件上传配置               |
| `/chat/{session_id}/data-analysis/tree`       | GET       | DataAnalysis 目录文件树（仅 data_analysis 子目录） |
| `/chat/{session_id}/tree`                     | GET       | 整个 session 工作树（data_analysis + 上传文件 + AI 中间产物） |
| `/chat/{session_id}/export/artifacts`         | GET       | 导出 DataAnalysis 产物（`?format=zip\|html`） |
| `/chat/{session_id}/export/turn/{checkpoint_id}` | GET     | 导出截至指定 checkpoint 的对话历史（OpenAI JSON + 完整 state 备份，打包 ZIP） |
| `/chat/{session_id}/queue`                    | GET / POST / DELETE | 排队消息（Redis `queue:{sid}` FIFO，最多 20 条 × 4000 字符）；`DELETE?idx=N` 删单条，不传 `idx` 清空。队列不主动 drain，前端在 SSE `done` 后自行出队续发 |

### 其它接口

| 接口                                | 方法   | 说明                                                  |
| --------------------------------- | ---- | --------------------------------------------------- |
| `/static/cached/{file_path:path}` | GET  | 访问 cached 目录静态文件；详见 [静态文件 fallback](#静态文件-fallback) |
| `/api/v1/chat/completions`        | POST | 视觉语言模型服务（本地 Qwen3-VL，`vl.local=false` 时 fallback 到主用 LLM） |
| `/admin/cleanup`                  | POST | 手动触发清理任务                                            |
| `/admin/cleanup/status`           | GET  | 获取清理状态                                              |
| `/admin/config`                   | GET  | 读取可编辑配置（v0.1.5 新增；密钥脱敏）                              |
| `/admin/config`                   | PUT  | 保存配置（白名单 `llm_providers` / `skills` / `permissions` 段；v0.1.5 起按段决定 `restart_required`） |
| `/admin/restart`                  | POST | 触发后端重启（写 `.restart_pending` marker + `os.execv`）         |
| `/admin/health`                   | GET  | 健康检查（前端轮询等待重启完成）                                    |
| `/admin/checkpoints/prune`        | POST | 手动清理 LangGraph 冗余 checkpoint（v0.1.5 新增；dry_run 预览 / 真删）  |

### 定时任务接口（`/admin/scheduled-tasks` 前缀）

| 接口                                | 方法    | 说明                                              |
| --------------------------------- | ----- | ----------------------------------------------- |
| `/admin/scheduled-tasks`          | POST  | 创建 cron 定时任务（`name` / `cron` / `prompt` / `session_id`；5-field cron，Asia/Shanghai） |
| `/admin/scheduled-tasks`          | GET   | 列出任务，`?session_id=` 可按会话过滤                       |
| `/admin/scheduled-tasks/{task_id}` | GET   | 任务详情，`?with_history=true` 附带最近执行记录               |
| `/admin/scheduled-tasks/{task_id}` | PATCH | 修改 `enabled` 或 `cron`                            |
| `/admin/scheduled-tasks/{task_id}` | DELETE | 删除任务 + 历史 + 调度锁                                 |
| `/admin/scheduled-tasks/{task_id}/run` | POST | 立即异步执行一次，**不改变原 cron**                        |

Redis key：`scheduled:tasks`（索引）/ `scheduled:meta:{task_id}` / `scheduled:history:{task_id}` / `scheduled:lock:{task_id}`，APScheduler 自身用 `apscheduler.jobs` + `apscheduler.run_times`。触发时 handler 直接调 `chat_service.message_stream()` 跑完整 LangGraph 一轮，不走消息队列、不推 SSE。

#### 静态文件 fallback

`serve_cached_file` 在精确路径命中失败时按以下规则走 fallback：

1. **带 sid 路径（`cached/{sid}/...` 或 `{sid}/...`）找不到 → 直接 404**：不去跨会话命中同名文件，避免误把别人 session 的产物当成本会话的图。sid 同时支持 32 位 hex（旧版 `uuid.uuid4().hex`）和 12 位 hex（新版 `uuid.uuid4().hex[:12]`），Referer 提取时优先匹配 32 位。
2. **无 sid 路径找不到 → 双层 fallback**：
   - **第一层（primary）**：从 `Referer` header 正则提取 sid（32 / 12 位 hex 都识别；路径边界 `/[/?#]|$` 防止 31 / 13 位凑巧 hex 长被误匹配），优先在 `cached/{referer_sid}/` 下递归找同名文件
   - **第二层（兜底）**：跨 `cached/*/` 所有 session 子目录递归查找同名文件（`rglob("**/*")`），按 `st_mtime` 降序排序，**最新修改时间**的文件胜出
   - Referer 缺失（隐私模式 / `no-referrer` 策略）/ 不含 sid / 异常格式 → 自动跳过第一层直接走第二层
3. **都无命中 → 404**。

**为什么用 Referer 推断 sid 而不是 `X-Session-Id` 自定义 header**：浏览器 `<img>` 标签加载 markdown 图片（fallback 主要场景）**不能**加自定义 header（浏览器规范限制），EventSource 也不能；只有 fetch 类 API 请求能加。所以 fallback 服务的核心场景（`<img>` 加载裸文件）只能靠浏览器自动带的 `Referer` 拿当前会话 sid，让 fallback 优先返回当前会话的产物。

**适用场景**：AI agent 输出的 markdown 图片用 `./data_analysis/foo.png` 这种**无 sid** 的相对路径时（前端会拼成 `/static/data_analysis/foo.png`），浏览器从当前会话页面发起请求时 Referer 自带 sid，fallback 会优先返回当前会话产物；找不到再跨 sid 取最新同名文件兜底。

## 代码沙盒

`backend/ChatMe/ChatWorkflow/mcps/sandbox/pool.py`（`SandboxPool` 类）提供基于 Docker 容器的安全代码执行：

- **预启动容器池**：min=1, max=4（per_container_concurrency=8），按需动态扩缩容 + 闲置 GC
- **隔离环境**：tmpfs 限制 `/tmp`、`/sandbox`（各 64m，noexec）
- **预装库**：numpy / pandas / scipy / scikit-learn / sympy / matplotlib / seaborn / plotly / bokeh / altair / pygal / pyecharts / folium / networkx / requests / bs4 / lxml / openpyxl / xlrd / pillow / jinja2 / markupsafe（阿里云 PyPI 镜像）
- **两个执行入口**：
  - `execute(code, lang)` —— code 工具：写 `/code.<py|js>` → 运行 → `rm -f`（避免敏感信息残留）
  - `execute_command(cmd)` —— cmd 工具：直接 `docker exec sh -c <cmd>`，可含管道 / 重定向 / glob
- **超时保护**：单次执行 30s 超时
- **自动恢复**：检测到容器未运行时自动重建

容器池大小可在 `SandboxPool(size=N)` 调整。沙盒不可用时降级到本机 venv（`backend/cached/` / `backend/skills/`）。

## MCP 工具

MCP 服务器（`mcps/server.py`，FastMCP 3.x，stdio transport）暴露以下核心工具：

| 工具          | 说明                                                                  |
| ----------- | ------------------------------------------------------------------- |
| `code`      | 默认在 Docker 沙盒中执行 Python / Node.js 代码（`local=True` 降级到本机 venv）；执行前 `PermissionedToolNode` 弹审批，可按 imports + calls + lang + local 算 fingerprint 永久批准 |
| `cmd`       | 默认在 Docker 沙盒中执行白名单内的 shell 命令（`local=True` 降级到本机）；带危险命令检测；执行前 `PermissionedToolNode` 弹审批 |
| `find_skill`| 动态发现 skills（`mode='match'` 按关键词返回 top 3，`mode='list'` 返回完整索引）；替代硬编码 skill examples + `cat skills/skills.md` |
| `interrupt` | 中断当前对话                                                              |
| `ctime`     | 获取当前日期时间                                                            |

> **stdio transport**：MCP 由 `chatme_main` 自动 fork 作为子进程，父子通过 stdin/stdout 通信；不需要 port / URL 配置。`session_id` 不再是工具参数 — 客户端 interceptor 自动从 LangGraph runtime 的 `thread_id` 注入，工具函数通过 `current_session_id.get()` 取。MCP session 为长生命周期（子进程 + `ClientSession` 常驻复用），工具调用不再每次重开连接。

> **未知工具名兜底**：LLM 调到未注册的工具时 `PermissionedToolNode` 不崩，走 LangGraph `ToolNode._validate_tool_call` 返回错误 `ToolMessage`（含未知工具名 + 可用工具列表）让模型重试；已知工具仍照常过权限 gate，`GraphInterrupt` / `GraphBubbleUp` 不被吞。

## 定时任务（Scheduler skill）

`backend/skills/Scheduler/` 把一段 prompt 配成 cron，到点自动注入指定 session 跑完整一轮 LangGraph agent。**不是 MCP 工具**，是 Skill + REST API 组合：agent 通过 `find_skill("定时")` 发现，`cmd("cat /skills/Scheduler/SKILL.md")` 读契约，再用 `code(..., local=True)` 调 4 个顶层函数。

| 函数                                                    | 用途                            |
| ----------------------------------------------------- | ----------------------------- |
| `create_scheduled_task(name, cron, prompt, session_id="")` | 创建（`session_id=""` = 触发时自动新建会话） |
| `list_scheduled_tasks(session_id="")`                 | 列出（可按会话过滤），返回全 12 位 task_id   |
| `cancel_scheduled_task(task_id)`                      | 取消，支持 task_id 前缀匹配            |
| `run_scheduled_task_now(task_id)`                     | 立即触发一次，不改 cron                |

- **必须 `local=True`**：4 个函数内部走 HTTP 调 `127.0.0.1:38211/admin/scheduled-tasks/*`，沙盒网络不可靠且缺 `apscheduler` / `redis` 包
- **调度器**：APScheduler `AsyncIOScheduler + RedisJobStore`，时区 `Asia/Shanghai`，后端重启从 Redis 恢复全部任务
- **lifespan 嵌套顺序**：`chat_service_lifespan → scheduler_lifespan → cleanup_lifespan`——scheduler 的 handler 依赖 `chat_service.message_stream`，必须嵌在 chat_service 之内
- **错误格式**：统一 `[类型] 描述 | 建议`（`[BadRequest]` / `[NotFound]` / `[ServiceUnavailable]` / `[ConnectionError]`），LLM 看前缀就知道换策略
- **前端**：v0.1.5 起改为**每个会话底部内嵌** ⏰ 触发按钮（仅 `tasks.length > 0` 渲染）+ 展开任务列表（`ScheduledTaskItem.vue`，单条卡片含 ⏸/▶ 启停、⚡ 立即运行、🗑 行内二次确认删除）；展开状态按 `lingxi.scheduledTasksExpanded` localStorage 持久化。**面板不提供创建入口**，创建走对话（让 agent 调 skill）

## 效果展示

下面是一次完整的数据分析请求（让 AI 对清洗好的数据集做 EDA 探索性分析）的输出节选。AI 通过 `code` 工具在 Docker 沙盒中调用 matplotlib / seaborn 生成图表，结果通过 `static/cached/` 路径返回前端渲染：

![EDA 探索性分析图表](docs/img/对话效果.png)

> 三张图分别为：① AIGC 置信度分数分布直方图（带阈值参考线）② 不同置信度等级下的媒体类型偏好柱状图 ③ 发帖时段 × 星期的热力图（Hour × Weekday）。所有图表由 AI 在沙盒内生成后自动嵌入到回复流中。

## 部署打包

### 构建 wheel 包

```bash
cd backend
uv build --wheel
# 输出: dist/ChatMe-0.2.1-py3-none-any.whl
```

### 安装 wheel

```bash
uv pip install dist/ChatMe-0.2.1-py3-none-any.whl
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
```

桌面端通过 `electron-builder` 打包，应用信息（应用名「灵析」、identifier `com.chatme.app`、版本 0.2.1）在 `frontend/electron/electron.config.js` 中配置。

**输出位置**：`../release/electron-builder/`（项目根，与 Vite 的 `dist/` / `frontend/` 区分开）：

- `mac-arm64/灵析.app` — 直接打开
- `mac/` — x64 .app
- `灵析-0.2.1-arm64-mac.zip` / `灵析-0.2.1-mac.zip` — 分发包
- `linux-unpacked/` — Linux 解压目录
- `灵析-0.2.1.AppImage` — Linux 便携版（需 FUSE，见下文）
- `灵析-0.2.1.deb` — Debian / Ubuntu 安装包
- `灵析-0.2.1.rpm` — Fedora / RHEL 安装包
- `win-unpacked.exe` — Windows 安装器

## 开发注意事项

启动命令见 [快速开始](#快速开始)。开发侧的额外约定与踩坑（unstructured NLTK 下载、配置脱敏提交规范、流式 SSE 事件类型、桌面端 DMG 镜像绕坑等）见 [`docs/contributing.md`](docs/contributing.md)。

## 许可证

本项目基于 **[MIT License](LICENSE)** 发布 —— 详见根目录 [LICENSE](LICENSE) 文件。

主要上游依赖与第三方归属见 [NOTICE](NOTICE) 与 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。

## 商标

「**灵析™**」与「**Lingxi™**」为本项目产品名商标。MIT 许可证不授予商标使用权，使用商标须经项目维护者书面授权。本项目内部代号 "ChatMe"（包名、配置目录 `~/.chatme/`、Redis key 前缀等）仅为技术标识符，不作为商标声明。