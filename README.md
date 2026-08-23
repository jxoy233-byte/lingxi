# Lingxi（灵析）

基于 LangGraph 的单智能体 + 多 LLM 角色数据分析对话系统。支持流式响应、工具调用、对话记忆管理、文档/图片多模态解析，以及基于 Docker 沙盒的安全 Python 代码执行。同时提供 Web 端和 Electron 桌面端两种运行形态。

> 贡献者 / 开发者 / AI 协作者请阅读 [`docs/contributing.md`](docs/contributing.md) 与 [`CLAUDE.md`](CLAUDE.md)：前者汇总开发约定、踩坑记录与 AI 自动化工具，后者是 AI 协作者的工作流指南。

---

## 目录

- [项目特性](#项目特性)
- [界面预览](#界面预览)
- [技术栈](#技术栈)
- [工作流](#工作流)
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

- **单智能体 + 多 LLM 角色工作流**：基于 LangGraph StateGraph 实现 `input_parse → context_assembly → agent_node ↔ tool_execution_node → final_node` 循环；5 个独立 LLM（core / agent / summary / react_compact / imp_ipt）各司其职，共用一个图状态
- **ReAct 流程压缩**：`context_assembly_node` 按 4 阶段循环自动压缩长 ReAct 轨迹，后台 LLM 异步推进不阻塞工作流，`imp_ipt` 标记做切分锚点，最近 keep 轮原文保留；`final_node` 用 dynamic system prompt 把 `imp_ipt` 注入 system 层独占最高注意力位（详见 CLAUDE.md）
- **流式 SSE 响应**：前端通过 EventSource 实时接收 `content` / `reasoning` / `tool_call_*` / `memory_wait_*` 事件
- **多模态文件解析**：图片（OSS / base64）、文本（CSV / JSON / MD / TXT / XML）、文档（PDF / Word / PowerPoint / Excel），docling + qwen-vl-utils + unstructured
- **Docker 沙盒执行**：预启动容器池 + tmpfs 隔离，提供安全的 Python 数据分析环境
- **多 LLM Provider**：OpenAI / DeepSeek / 本地 VL（Qwen3-VL-2B）统一抽象，5 个独立 LLM（core / agent / summary / react_compact / imp_ipt）可分别配参
- **对话记忆**：Redis checkpointer 状态恢复 + 自建 memory manager 长期记忆；per-thread Lock + 原子写 + 后台任务串行
- **节点异常统一兜底**：`@node_guard` 装饰器包住所有 LangGraph 节点，异常后 SSE 外层统一返回 `error` 事件
- **命令级权限审批**：`cmd` / `code` 工具走 `PermissionedToolNode`（基于官方 `ToolNode` + `_awrap_tool_call` hook），敏感命令执行前触发 LangGraph `interrupt()` 弹审批；4 档决策（`approve` / `this-time-only` / `deny` / `feedback:<text>`）走 Redis `permission:{sid}` hash；`code` 工具按 imports + calls + lang + sandbox 计算 fingerprint 做永久批准匹配
- **OSS 对象存储**：阿里云 OSS，图片 / 文件上传后通过 URL 直接访问
- **桌面端打包**：Electron 41 + electron-builder 26 多平台打包，含 `file://` 协议拦截器等价 Vite dev proxy、↻ 刷新按钮、网页预览窗口
- **数据库分析**：DataAnalysis skill 支持 MySQL / SQLite / PostgreSQL / MongoDB 只读查询（agent 在 `data_analysis/` 工作树模式下可主动调用 `query_sql` / `query_mongo`，配置跨会话保存在 `skills/DataAnalysis/database/.runtime/`）
- **一键导出**：
  - 文件树「会话文件」面板头部的 ⬇ / 👁 按钮把 `data_analysis/` 产物打包成 ZIP 或单文件 HTML 预览（marked.js + mermaid.js CDN，PNG/SVG 转 base64 内嵌，CSV/JSON 转 HTML 表格）
  - AI 消息气泡下方按钮排的 ⬇ 「导出到本轮」按钮，截至该 checkpoint 导出 OpenAI Chat Completions 格式 JSON + 自家完整 state 备份 JSON（ZIP 下载，后续可恢复）
- **定时任务**：`Scheduler` skill 把一段 prompt 配成 cron，到点自动注入指定 session 跑完整一轮 LangGraph agent；APScheduler `AsyncIOScheduler + RedisJobStore`（Asia/Shanghai）持久化，后端重启自动恢复；**v0.1.5 起**每个会话底部内嵌 ⏰ 触发按钮 + 展开任务列表（仅 `tasks.length > 0` 渲染；展开状态 localStorage 持久化）
- **消息排队**：AI 流式期间用户仍可输入，消息进 Redis `queue:{sid}` FIFO（最多 20 条 × 4000 字符），本轮 `done` 后自动出队续发；用户切走会话时推迟 drain，切回再发
- **Memory 跨会话记忆（v0.1.5 新增）**：`Memory` skill 把精确事实 / 用户偏好持久化到 `.chatme/memory/{tid|global}/{facts|preference}.md`，`context_assembly_node` 每轮开头自动合并注入，让未来对话开箱即用。**remember 必须 `code(..., local=True)`**（沙盒挂 ro）；recall 在沙盒里也支持（挂到 `/memory`）。
- **SkillForge 动态创建 skill（v0.1.5 新增）**：`SkillForge` skill 让 agent / 用户写一段 Python wrapper 落到 `/skills/<name>/`，立即被 `find_skill` 发现（registry 按 mtime 自动重扫，无需重启）。
- **Settings 4 tab + 热加载（v0.1.5 新增）**：`vl.local` 开关决定是否加载本地 VL 模型 + fallback 主用 LLM；`/admin/config` GET / PUT（白名单 llm_providers / skills / permissions）；**按段决定 `restart_required`** —— permissions / skills 改动立即生效，llm_providers 需重启；`/admin/restart` + `/admin/health` 支持前端轮询等待重启恢复。**前端 `buildPayload()` diff-only**（`_deepDiff` + `_stripEmptyObjects`），避免「在 Permissions 改一字段把 llm_providers 全部带上」的误判。
- **Checkpoint 清理端点（v0.1.5 新增）**：LangGraph `AsyncRedisSaver` 每节点 aput 会攒几十～几百个 checkpoint，dump.rdb 膨胀且启动慢；`POST /admin/checkpoints/prune` 手动清理（dry_run 预览 / 真删两种），前端 Settings「立即清理」按钮调用；后台已自动 hook 进 `_save_round_checkpoint` 每轮 round 收尾时异步 prune。
- **Slash 命令面板（v0.1.7 新增）**：行首输入 `/` 弹出 Codex 风格面板，分「命令 / 技能」两组；静态 action（`/backtrack` `/settings` `/reload` `/worktree` `/help`）+ 动态 skill（后端 `/chat/skills` 实时拉取，按目录名 PascalCase 显示）。选中后以 `/[SkillName]` chip 形态浮在输入框左侧，`handleSend` 时还原成 `/[xxx] ` 前缀发给后端。prompt 注入对应 hint：前缀一字不改、args 可优化；非 slash 输入不要凭空加 `/[SkillName]`。
- **文件树行内删除 + 软删除 .trash/（v0.1.7 新增）**：文件 / 文件夹行内 × 红叉二次确认调 `DELETE /chat/{sid}/file`，文件移到 `backend/.trash/{sid}/{timestamp}_{rel_path}`；每天 11:30 APScheduler 定时清空，前端 DataAnalysisTree 头部 🗑 「清空回收站」按钮手动触发 `DELETE /chat/{sid}/trash`。误删可找回。
- **标题自动派生（v0.1.7 新增）**：`PUT /chat/{sid}/title` title 为空时后端从 state 最新 HumanMessage 派生（剥 `<quote>` 引用块 + `/[xxx]` slash pill + 截断 12 字符），返回实际写入的 `new_title`，前端不再依赖客户端 substring 兜底。
- **后端路径中心化（v0.1.7 新增）**：`backend/ChatMe/paths.py` 集中导出 `BACKEND_ROOT` / `CACHED_DIR` / `SKILLS_ROOT` / `TRASH_DIR` / `get_chatme_dir()`，替代所有模块里散落的 `Path.cwd()` / `parents[N]` 调用；从任意 cwd 启动后端都不会漂移。
- **Linux 多格式打包（v0.1.7 新增）**：`electron-builder` 同时产出 AppImage / `.deb` / `.rpm`，x64 + arm64 双架构；`README` 增「Linux 安装与故障排查」段覆盖 FUSE 缺失、AppImage 直接解压等场景。

## 界面预览

![ChatMe 主界面](docs/img/界面.png)

主界面分区：左侧会话列表（支持新建 / 切换 / 删除）+ 中间对话区（流式 SSE 实时渲染 `reasoning` / `tool_call_*` / `content` 事件）+ 下方输入框（文件上传 / 语音输入 / 发送）。思考过程可折叠展开，工具调用次数实时统计。

## 技术栈

### 后端

| 模块     | 选型                                       |
| ------ | ---------------------------------------- |
| Web 框架 | FastAPI                                  |
| 工作流引擎  | LangGraph + LangChain                    |
| 状态管理   | Redis (checkpointer + state saver)       |
| MCP 工具 | FastMCP 3.x                              |
| 代码沙盒   | Docker 容器池                               |
| 文档解析   | docling + qwen-vl-utils + unstructured   |
| 对象存储   | oss2（阿里云 OSS）                            |
| 定时任务   | apscheduler                              |
| LLM    | OpenAI 兼容 API（OpenAI / DeepSeek / 本地 VL） |
| 包管理    | uv                                       |

### 前端

| 模块            | 选型                                       |
| ------------- | ---------------------------------------- |
| Web 框架        | Vue 3 + Vite                             |
| 桌面端           | Electron 41 + electron-builder 26        |
| 样式            | CSS Variables + 原生 CSS                   |
| Markdown / 数学 | marked + highlight.js + katex            |
| 桌面端关键能力       | `file://` 协议拦截 + SSE 流透传 + 单窗口架构 + autoEnter 启动引导 |
| 特性            | 流式 SSE、主题切换、响应式布局、网页预览                   |

## 工作流

```
用户输入 → input_parse_node → context_assembly_node
                                    ↓
                              agent_node ──→ tool_execution_node (循环)
                                    ↓
                              final_node → END
```

| 节点                      | 职责                                                                              |
| ----------------------- | ------------------------------------------------------------------------------- |
| `input_parse_node`      | 输入预处理、文件解析（docling / VL）、输入优化，给 `imp_ipt` 打 `additional_kwargs.imp_ipt=True` 标记 |
| `context_assembly_node` | 上下文组装 + **ReAct 流程压缩** + 中断检查                                                   |
| `agent_node`            | AI 决策，决定调用工具或结束；工具调用超过 20 次会注入 SystemMessage 提示停止                               |
| `tool_execution_node`   | 工具执行（搜索 / MCP / Docker 沙盒）；`PermissionedToolNode` 在官方 `ToolNode` 基础上包 `_awrap_tool_call` hook，`cmd` / `code` 执行前走 LangGraph `interrupt()` 弹审批，Redis 存 `permission:{sid}` hash 跨 SSE 流复用 |
| `final_node`            | 最终回复生成（独立 LLM），用 dynamic system prompt 把 `imp_ipt` 注入 system 层，输出带 SUMMARY 标记   |

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

# 启动主服务（端口 8211，stdio 模式下会 fork MCP 子进程）
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
# 容器池默认 2 个常驻容器，SandboxPool（mcps/sandbox/pool.py）自动按需取用
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
    "version": "v0.1.7",
    "host": "127.0.0.1",
    "port": 8211
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
│   │   │   │   ├── server.py             # FastMCP 入口（CLI: chatme_mcp）
│   │   │   │   ├── session.py            # MCP stdio session
│   │   │   │   ├── tools/                # 工具实现
│   │   │   │   │   ├── code_fingerprint.py
│   │   │   │   │   ├── deprecated.py     # (sub_agent 废弃保留)
│   │   │   │   │   └── platforms/        # 跨平台 adapter（darwin/linux/windows）
│   │   │   │   ├── sandbox/              # 沙盒基础设施
│   │   │   │   │   └── pool.py           # Docker 容器池
│   │   │   │   └── permissions/          # 权限系统
│   │   │   │       └── core.py           # PermissionedToolNode + 中断审批
│   │   │   └── Memory/                   # 长期记忆
│   │   ├── APIRouter/
│   │   │   ├── main.py                   # /chat 前缀主对话路由 + 会话树
│   │   │   ├── static_file.py            # /static 静态文件 + 文件树接口
│   │   │   ├── data_export.py            # /export/artifacts + /export/turn（DataAnalysis ZIP/HTML 预览 + 对话历史导出）
│   │   │   ├── scheduled_tasks.py        # /admin/scheduled-tasks CRUD + 立即运行
│   │   │   ├── checkpoint_janitor.py     # /admin/checkpoints/prune（v0.1.5 新增；checkpoint prune HTTP 层）
│   │   │   ├── admin_config.py           # /admin/config GET / PUT + /admin/restart + /admin/health（v0.1.5 新增）
│   │   │   ├── message_queue.py          # /chat/{sid}/queue 排队消息 FIFO
│   │   │   └── timed_clean / model_vl
│   │   ├── LoggingManager/               # 异步日志
│   │   └── test/
│   ├── skills/
│   │   ├── DataAnalysis/                  # 数据分析 skill（mount: rw）
│   │   │   ├── SKILL.md                  # 主规范（生成图表 / 报告 / CSV 等）
│   │   │   ├── format/                   # ChatDataAnalysisFormat（拆分为 base / artifacts / manifest / database）
│   │   │   ├── database/                 # 数据库分析（MySQL/SQLite/PostgreSQL/MongoDB 只读查询 + 跨会话配置；lazy skill）
│   │   │   └── fonts/                    # matplotlib 中文字体（v0.1.6 起随 skill 进 git，自动 mount 到容器 /skills/DataAnalysis/fonts/）
│   │   ├── Scheduler/                    # 定时任务 skill（APScheduler + RedisJobStore；models/handlers/registry/core 四层）
│   │   ├── Memory/                       # 跨会话记忆 skill（v0.1.5 新增；remember/recall）
│   │   ├── SkillForge/                   # 动态创建 skill skill（v0.1.5 新增；create_skill/list_skills/read_skill）
│   │   ├── Exa/                          # 搜索 skill
│   │   ├── Tavily/                       # 搜索 skill
│   │   └── ImageParser/                  # 图片解析 skill
│   ├── ChatMe/ChatWorkflow/
│   │   ├── skills/                       # SkillRegistry（v0.1.5 起扫描 SKILL.md frontmatter + find_skill 工具 prompt）
│   │   ├── CheckpointJanitor.py          # checkpoint prune 业务（v0.1.5 起 hook 进 _save_round_checkpoint 自动 prune）
│   │   └── ...（其余业务节点）
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

- **必须 `local=True`**：4 个函数内部走 HTTP 调 `127.0.0.1:8211/admin/scheduled-tasks/*`，沙盒网络不可靠且缺 `apscheduler` / `redis` 包
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
# 输出: dist/ChatMe-0.1.7-py3-none-any.whl
```

### 安装 wheel

```bash
uv pip install dist/ChatMe-0.1.7-py3-none-any.whl
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

桌面端通过 `electron-builder` 打包，应用信息（应用名「灵析」、identifier `com.chatme.app`、版本 0.1.7）在 `frontend/electron/electron.config.js` 中配置。

**输出位置**：`../release/electron-builder/`（项目根，与 Vite 的 `dist/` / `frontend/` 区分开）：

- `mac-arm64/灵析.app` — 直接打开
- `mac/` — x64 .app
- `灵析-0.1.7-arm64-mac.zip` / `灵析-0.1.7-mac.zip` — 分发包
- `linux-unpacked/` — Linux 解压目录
- `灵析-0.1.7.AppImage` — Linux 便携版（需 FUSE，见下文）
- `灵析-0.1.7.deb` — Debian / Ubuntu 安装包
- `灵析-0.1.7.rpm` — Fedora / RHEL 安装包
- `win-unpacked.exe` — Windows 安装器

## 开发注意事项

启动 Redis / 后端 / 前端 / 构建沙盒镜像的命令见 [快速开始](#快速开始)。开发侧的额外约定与踩坑（unstructured NLTK 下载、配置脱敏提交规范、流式 SSE 事件类型、桌面端 DMG 镜像绕坑等）见 [`docs/contributing.md`](docs/contributing.md)。

## 许可证

本项目为内部项目，许可证信息请参考项目根目录 LICENSE 文件（如有）。