# Lingxi™（灵析™）

基于 LangGraph 的多智能体数据分析对话系统。支持流式响应、工具调用、对话记忆管理、文档/图片多模态解析，以及基于 Docker 沙盒的安全 Python 代码执行。同时提供 Web 端和 Electron 桌面端两种运行形态。

> 贡献者 / 开发者 / AI 协作者请阅读 [`docs/contributing.md`](docs/contributing.md) 与 [`CLAUDE.md`](CLAUDE.md)。

## 目录

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
- [许可证](#许可证)
- [软件著作权](#软件著作权)

## 项目特性

- **多智能体工作流**：5 个 LLM 角色 + ReAct 4 阶段后台异步压缩（CLAUDE.md 详述）
- **流式 SSE / 多模态文件解析 / Docker 沙盒 / Redis checkpoint**：标准 FastAPI + LangGraph 后端
- **命令级权限审批**：`cmd` / `code` 走 LangGraph `interrupt()`，4 档决策 + Redis hash 持久化
- **数据库只读分析**：MySQL / SQLite / PostgreSQL / MongoDB 4 引擎跨会话配置
- **动态 Skill 创建**：SkillForge 让 AI 自己写 SKILL.md + 包装代码，slash 命令面板实时显示新 skill
- **一键导出**：DataAnalysis 产物 ZIP / HTML + 对话历史 OpenAI JSON + state 备份
- **Web + Electron 双端**：Vue 3 + Vite + electron-builder 26，单窗口架构 + autoEnter 启动体验

## 界面预览

![灵析 主界面](docs/img/界面.png)

主界面分区：左侧会话列表（支持新建 / 切换 / 删除）+ 中间对话区（流式 SSE 实时渲染 `reasoning` / `tool_call_*` / `content` 事件）+ 下方输入框（文件上传 / slash 命令面板 / 发送）。思考过程可折叠展开，工具调用次数实时统计。

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+
- uv（Python 包管理）
- Docker + Docker Compose
- 4GB+ 内存（本地 VL 模型需要更多）

### 启动 Redis

```bash
docker-compose up -d redis
# Redis 容器端口 6379 -> 主机 48211 / RedisInsight 端口 8001 -> 主机 28001 / 密码 123456
```

### 启动后端

```bash
cd backend
uv sync                                          # 安装依赖

# 启动主服务（默认端口 38211，stdio 模式下会 fork MCP 子进程）
# 首次启动会自动：1) 检查 Redis  2) 清理残留沙盒容器  3) 初始化沙盒池
uv run chatme_main                               # 等价于 uv run python main.py
```

### 启动前端

```bash
cd frontend
npm install
npm run dev  # 访问 http://localhost:18211

# Electron 桌面端开发（同时启动 Vite + Electron）
npm run electron:dev:all
```

### 构建代码沙盒镜像（首次使用前）

```bash
docker-compose build sandbox
# 镜像名：chatme-python-sandbox:latest
# 容器池 min=1, max=4（per_container_concurrency=8）；按需动态扩缩容 + 闲置 GC
```

## 配置说明

### 配置文件优先级

1. **局部配置** `./backend/.chatme/config.json`（项目目录下，仓库内已包含）
2. **全局配置** `~/.chatme/config.json`（用户目录下）
3. **环境变量**（作为默认值填充）

首次运行时会自动在 `~/.chatme/` 生成默认配置。

### 配置文件示例（`config.json`）

```json
{
  "app": {
    "name": "ChatMe",
    "version": "v0.3.1",
    "host": "127.0.0.1",
    "port": 38211
  },
  "redis": {
    "checkpointer_url": "redis://:123456@localhost:48211/0",
    "state_saver_url":   "redis://:123456@localhost:48211/1"
  },
  "llm_providers": {
    "openai":   { "model_name": "gpt-4o", "api_key": "...", "base_url": "https://api.openai.com/v1" },
    "deepseek": { "model_name": "deepseek-chat", "api_key": "...", "base_url": "https://api.deepseek.com/" },
    "vl":       { "model_name": "Qwen3-VL-2B", "base_url": "http://127.0.0.1:38211/api/v1", "local": true }
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
│   │   ├── ChatWorkflow/                 # LangGraph 5 节点 + ReAct 压缩 + Memory + mcps
│   │   ├── LoggingManager/               # QueueHandler 异步日志
│   │   └── APIRouter/                    # /chat /static /api /admin
│   ├── skills/
│   │   ├── DataAnalysis/                 # 数据分析 + 数据库（只读 4 引擎）+ 中文字体
│   │   ├── Scheduler/                    # 定时任务 skill
│   │   ├── Memory/                       # 跨会话记忆
│   │   ├── SkillForge/                   # 动态创建 skill
│   │   ├── Bocha / Exa / Tavily          # 搜索 skill
│   │   └── ImageParser/                  # 图片解析
│   ├── .chatme/                          # 局部配置
│   ├── pyproject.toml
│   └── main.py                           # FastAPI 入口
├── sandbox/Dockerfile                    # Python 3.12 + 数据分析库
├── frontend/                             # Vue 3 + Electron 桌面端
├── docs/                                 # 开发者文档
├── docker-compose.yml                    # Redis 服务编排（端口 48211）
├── LICENSE                               # MIT License
├── NOTICE / THIRD_PARTY_LICENSES.md      # 上游依赖归属
└── CLAUDE.md                             # AI 协作者工作流指南
```

## API 概览

后端通过 4 个 Router 暴露接口。

### 聊天接口（`/chat` 前缀）

| 接口                                            | 方法             | 说明                     |
| --------------------------------------------- | -------------- | ---------------------- |
| `/chat/`                                      | POST           | 流式对话（无 session_id 则新建） |
| `/chat/conversations`                         | GET            | 会话列表                   |
| `/chat/{session_id}/conversation`             | GET            | 会话详情                   |
| `/chat/{session_id}/title`                    | GET / PUT      | 获取 / 修改会话标题            |
| `/chat/{session_id}/clear`                    | DELETE         | 删除会话（含聊天记录）            |
| `/chat/{session_id}/backtrack`                | POST           | 会话回溯                   |
| `/chat/{session_id}/interrupt`                | POST           | 中断对话                   |
| `/chat/{session_id}/invoke_interrupted/{msg}` | POST           | 中断续接对话                 |
| `/chat/{session_id}/permission/decide`        | POST           | 审批权限决策（4 档决策 + Redis hash）  |
| `/chat/{session_id}/permission/resume`        | POST (SSE)     | 决策后 resume permission 中断     |
| `/chat/{session_id}/upload_file`              | POST           | 上传文件                   |
| `/chat/improve_input`                         | POST           | 优化用户输入                 |
| `/chat/{session_id}/data-analysis/tree`       | GET            | DataAnalysis 目录文件树          |
| `/chat/{session_id}/tree`                     | GET            | 整个 session 工作树          |
| `/chat/{session_id}/export/artifacts`         | GET            | 导出 DataAnalysis 产物（zip / html） |
| `/chat/{session_id}/export/turn/{checkpoint_id}` | GET         | 导出截至指定 checkpoint 的对话历史  |
| `/chat/{session_id}/queue`                    | GET / POST / DELETE | 排队消息（Redis FIFO ≤20 × 4000 字符） |

### 其它接口

| 接口                                | 方法   | 说明                                                  |
| --------------------------------- | ---- | --------------------------------------------------- |
| `/static/cached/{file_path:path}` | GET  | 访问 cached 目录静态文件（含 sid / Referer fallback）        |
| `/api/v1/chat/completions`        | POST | 视觉语言模型服务（本地 Qwen3-VL，`vl.local=false` fallback 到主用 LLM） |
| `/admin/cleanup`                  | POST | 手动触发清理任务                                            |
| `/admin/config`                   | GET / PUT | 读取 / 保存可编辑配置（segment 级热加载，密钥脱敏）                |
| `/admin/restart`                  | POST | 触发后端重启（写 `.restart_pending` marker + `os.execv`）         |
| `/admin/health`                   | GET  | 健康检查                                                |
| `/admin/checkpoints/prune`        | POST | 手动清理 LangGraph 冗余 checkpoint                         |
| `/admin/scheduled-tasks`          | CRUD | 定时任务管理（5-field cron，Asia/Shanghai）                 |

完整 API 列表与边角细节（sandbox 池锁、permission hash、fallback 策略等）见 [`docs/contributing.md`](docs/contributing.md) 与 [`CLAUDE.md`](CLAUDE.md)。

## 代码沙盒

`backend/ChatMe/ChatWorkflow/mcps/sandbox/pool.py`（`SandboxPool` 类）提供基于 Docker 容器的安全代码执行：

- **预启动容器池**：min=1, max=4（per_container_concurrency=8），按需动态扩缩容 + 闲置 GC
- **隔离环境**：tmpfs 限制 `/tmp`、`/sandbox`（各 64m，noexec）
- **预装库**：numpy / pandas / scipy / scikit-learn / sympy / matplotlib / seaborn / plotly / requests / bs4 / openpyxl / pillow 等
- **两个执行入口**：
  - `execute(code, lang)` —— code 工具：写 `/code.<py|js>` → 运行 → `rm -f`
  - `execute_command(cmd)` —— cmd 工具：`docker exec sh -c <cmd>`，可含管道 / 重定向 / glob
- **超时保护**：单次执行 30s 超时
- **自动恢复**：检测到容器未运行时自动重建
- **沙盒不可用时降级**：本机 venv（`backend/cached/` / `backend/skills/`）

## MCP 工具

MCP 服务器（`mcps/server.py`，FastMCP 3.x，stdio transport）暴露以下核心工具：

| 工具          | 说明                                                                  |
| ----------- | ------------------------------------------------------------------- |
| `code`      | Docker 沙盒执行 Python / Node.js（`local=True` 降级本机）；执行前弹审批，按 fingerprint 永久批准 |
| `cmd`       | Docker 沙盒执行白名单内 shell 命令；带危险命令检测 + 审批                       |
| `find_skill`| 动态发现 skills（`mode='match'` top 3 / `mode='list'` 全索引）              |
| `interrupt` | 中断当前对话                                                              |
| `ctime`     | 获取当前日期时间                                                            |

> **stdio transport**：MCP 由 `chatme_main` 自动 fork 作为子进程；`session_id` 客户端 interceptor 从 LangGraph runtime 的 `thread_id` 自动注入。MCP session 为长生命周期（子进程 + `ClientSession` 常驻复用）。

> **未知工具名兜底**：LLM 调到未注册的工具时 `PermissionedToolNode` 不崩，走 LangGraph `ToolNode._validate_tool_call` 返回错误 `ToolMessage` 让模型重试。

## 定时任务（Scheduler skill）

`backend/skills/Scheduler/` 把一段 prompt 配成 cron，到点自动注入指定 session 跑完整一轮 LangGraph agent。**不是 MCP 工具**，是 Skill + REST API 组合：agent 通过 `find_skill("定时")` 发现，再 `code(..., local=True)` 调 4 个顶层函数（`create_scheduled_task` / `list_scheduled_tasks` / `cancel_scheduled_task` / `run_scheduled_task_now`）。

- **调度器**：APScheduler `AsyncIOScheduler + RedisJobStore`，时区 `Asia/Shanghai`，后端重启从 Redis 恢复全部任务
- **前端**：每个会话底部内嵌 ⏰ 触发按钮 + 展开任务列表（`ScheduledTaskItem.vue`）

## 效果展示

下面是一次数据分析请求的输出节选。AI 通过 `code` 工具在 Docker 沙盒中调用 matplotlib / seaborn 生成图表，结果通过 `static/cached/` 路径返回前端渲染：

![数据分析沙盒图表](docs/img/对话效果.png)

> 三张图分别为：① AIGC 置信度分数分布直方图（带阈值参考线）② 不同置信度等级下的媒体类型偏好柱状图 ③ 发帖时段 × 星期的热力图（Hour × Weekday）。所有图表由 AI 在沙盒内生成后自动嵌入到回复流中。

## 部署打包

### 构建 wheel 包

```bash
cd backend
uv build --wheel
# 输出: dist/ChatMe-0.3.1-py3-none-any.whl
uv pip install dist/ChatMe-0.3.1-py3-none-any.whl
# 安装后 chatme_main 和 chatme_mcp 命令全局可用
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

应用信息（应用名「灵析」、identifier `com.chatme.app`、版本 0.3.1）在 `frontend/electron/electron.config.js` 中配置。**输出位置**：`../release/electron-builder/`，包含 `灵析.app` / `灵析-0.3.1-arm64.dmg` / `灵析-0.3.1.dmg` / `灵析 Setup 0.3.1.exe`。

## 开发注意事项

启动命令见 [快速开始](#快速开始)。开发侧的额外约定与踩坑（unstructured NLTK 下载、配置脱敏提交规范、流式 SSE 事件类型、桌面端 DMG 镜像绕坑等）见 [`docs/contributing.md`](docs/contributing.md)。

## 许可证

本项目基于 **[MIT License](LICENSE)** 发布 —— 详见根目录 [LICENSE](LICENSE) 文件。主要上游依赖与第三方归属见 [NOTICE](NOTICE) 与 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。

## 软件著作权

本项目（含但不限于源代码、文档、配置文件、UI 设计、图标、工作流定义、提示词模板、数据集及一切衍生作品）的著作权（含软件著作权）受《中华人民共和国著作权法》及《计算机软件保护条例》保护，**归灵析所有**。完整声明见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
