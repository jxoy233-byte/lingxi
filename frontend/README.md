# ChatMe 前端（灵析 Lingxi）

Vue 3 + Vite 单页应用，提供 **Web 端** 和 **Electron 桌面端** 两种运行形态。SSE 流式对接后端 LangGraph 工作流，支持多模态文件、代码沙盒预览、对话回溯/中断、长期记忆等能力。

> 后端架构与工作流详见仓库根目录的 [`README.md`](../README.md) 和 [`CLAUDE.md`](../CLAUDE.md)。

## 目录

- [项目特性](#项目特性)
- [技术栈](#技术栈)
- [运行形态](#运行形态)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [组件说明](#组件说明)
- [路由](#路由)
- [API 接口](#api-接口)
- [SSE 事件协议](#sse-事件协议)
- [Electron 启动命令](#electron-启动命令)
- [Electron 配置](#electron-配置)
- [Electron `file://` 协议拦截](#electron-file-协议拦截)
- [桌面端打包](#桌面端打包)
- [常见问题](#常见问题)

## 项目特性

- **左 AI 右用户布局**：AI 消息居左、用户消息居右，对话气泡风格
- **流式 SSE 对接**：实时接收 `content` / `reasoning` / `tool_call_*` / `memory_wait_*` 事件，思考过程与正文分离渲染
- **多模态文件**：图片（OSS / base64）、文本（CSV / JSON / MD / TXT / XML）、文档（PDF / Word / PPT / Excel）上传与预览
- **Markdown / 数学 / 图表**：marked + highlight.js + katex + mermaid，AI 回复内的代码块、公式、流程图直接渲染
- **主题切换**：浅色 / 深色双主题，CSS Variables 实现，自动持久化用户偏好
- **对话管理**：侧边栏列表、新建 / 删除 / 双击编辑标题、智能相对时间显示、自动生成标题（取前 5 字）
- **回溯 / 中断 / 续接**：Checkpoint 面板展示历史节点，支持回溯到任意一轮；执行中可中断后从断点续接
- **网页预览窗口**：通过 Electron IPC 在独立窗口打开外部链接（生产环境受限）
- **错误气泡保护**：SSE `error` 事件触发时整条消息渲染为红色错误框，`done` 事件不会复活 AI 内容，避免报错堆栈被当 markdown
- **头部刷新按钮**：↻ 按钮 + `Cmd/Ctrl+R` + 菜单 → 视图 → 刷新，触发 `window.location.reload()` 走完整重载
- **Electron 多环境**：开发 / 测试 / 正式三套配置，菜单栏与窗口标题栏上以颜色徽章区分
- **file:// 协议拦截**：Electron 桌面端用 `protocol.handle('file', ...)` 把 `/chat/*` 和 `/static/*` 转发到后端，等价于 Vite dev 模式的代理

## 技术栈

| 模块 | 选型 |
|------|------|
| 框架 | Vue 3（Composition API + `<script setup>`） |
| 构建 | Vite 5 |
| 路由 | vue-router 4 |
| 桌面端 | Electron 41 + electron-builder 26 |
| Markdown | marked 17 |
| 代码高亮 | highlight.js 11 |
| 数学公式 | katex 0.16 |
| 流程图 | mermaid 11 |
| 样式 | CSS Variables + 原生 CSS |
| 状态管理 | Vue ref/reactive（无 Pinia / Vuex） |

## 运行形态

```
┌─────────────────────────────────────────────────────────────┐
│  Web 端：浏览器访问 http://localhost:18211                    │
│  ─────────                                                 │
│  npm run dev          启动 Vite dev server                   │
│  npm run build        输出到 dist/                          │
│  npm run preview      本地预览构建产物                       │
│                                                              │
│  Electron 桌面端：独立窗口                                   │
│  ─────────                                                 │
│  npm run electron:dev:all  Vite + Electron 联调（开发）     │
│  npm run electron:prod     加载本地 dist/（需先 build）     │
│  npm run electron:build    electron-builder 打包安装包       │
└─────────────────────────────────────────────────────────────┘
```

Web 端走 Vite dev server，Electron 端在窗口内嵌同一个 URL 或 `file://` 加载 `dist/index.html`。

## 快速开始

### 1. 准备后端

```bash
# 启动 Redis（端口 6024，密码 123456）
docker-compose up -d redis

# 启动主服务（端口 8211，stdio 模式下自动 fork MCP 子进程）
cd backend
uv run chatme_main

# 开发模式单独起 MCP（仅手动调试用，正常运行不需要）
uv run chatme_mcp
```

详见根目录 [`README.md`](../README.md)。

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 选择运行方式

| 场景 | 命令 |
|------|------|
| 仅浏览器调试 | `npm run dev` → 访问 `http://localhost:18211` |
| Electron 联调（含热更新） | `npm run electron:dev:all` |
| 桌面端预览构建产物 | `npm run build && npm run electron:prod` |
| 打包安装包 | `npm run electron:build` 或 `electron:build:mac` / `:win` / `:linux` |

## 项目结构

```
frontend/
├── index.html                  # HTML 入口（Vite 引用根）
├── package.json                # 依赖 + npm scripts + electron-builder 配置
├── vite.config.js              # Vite 配置（同时导出 viteServerConfig / viteBuildConfig 给 Electron 复用）
├── build/                      # 应用图标（electron-builder buildResources）
│   ├── icon.icns               # macOS
│   ├── icon.ico                # Windows
│   └── icon.png                # Linux + Dock 通用
├── public/                     # 静态资源（构建时原样拷贝到 dist/）
│   └── favicon.ico             # 浏览器标签页图标
├── electron/                   # Electron 桌面端
│   ├── main.js                 # 主进程：窗口、菜单、IPC、file:// 协议拦截、安全策略
│   ├── preload.js              # 预加载脚本：contextBridge 暴露 electronAPI / electron
│   ├── electron.config.js      # 桌面端配置（窗口、安全、快捷键、图标路径）
│   └── public/favicon.png      # 跨平台窗口图标
├── src/
│   ├── main.js                 # 应用入口：创建 Vue 实例、注册路由
│   ├── App.vue                 # 根组件：全局状态、SSE 连接、错误气泡保护、刷新页面
│   ├── router/index.js         # 路由表
│   └── components/             # 业务组件
│       ├── ChatHeader.vue      # 顶部条（含 ↻ 刷新按钮）
│       ├── CheckpointPanel.vue
│       ├── ConfirmDialog.vue
│       ├── ConversationItem.vue
│       ├── DataAnalysisTree.vue    # 内含 reload ↻ 按钮（与 ChatHeader 同款 SVG）
│       ├── DataTreeNode.vue
│       ├── FilePreviewModal.vue
│       ├── FilePreviewPanel.vue
│       ├── MessageInput.vue
│       ├── MessageItem.vue
│       ├── MessageList.vue
│       ├── SearchResults.vue
│       ├── Sidebar.vue
│       └── WebPreviewPanel.vue
├── tips/                       # 用户提示插图（img.png 等）
└── dist/                       # vite build 产物（被 .gitignore 忽略）
```

## 组件说明

| 组件 | 职责 |
|------|------|
| `App.vue` | 全局状态中心；维护 SSE 连接、错误气泡保护集合 `_sessionHadError: Set<session_id>`、当前会话切换；`refreshPage()` 触发 `window.location.reload()` |
| `Sidebar.vue` | 会话列表容器，支持新建 / 删除 / 切换会话 |
| `ConversationItem.vue` | 单个会话项：双击编辑标题、悬停显示删除按钮、相对时间显示（分钟/小时/天数） |
| `ChatHeader.vue` | 顶部条：主题切换、Checkpoint 面板、**↻ 刷新页面按钮**（与 `DataAnalysisTree` 同款 SVG），新对话按钮 |
| `MessageList.vue` | 消息列表容器：自动滚动控制（入场 easeInOut + 流式 ramp + 100ms 打断防抖 + 用户 wheel/touch 让出控制权） |
| `MessageItem.vue` | 单条消息渲染：Markdown / 代码高亮 / 数学公式 / 流程图；`message.error=true` 时渲染为红色错误框 |
| `MessageInput.vue` | 输入框：Enter 发送、Shift+Enter 换行、文件上传、语音输入 |
| `CheckpointPanel.vue` | 回溯面板：展示历史 checkpoint 节点列表，支持回溯到指定轮 |
| `ConfirmDialog.vue` | 通用确认弹窗（删除对话、关闭会话等） |
| `FilePreviewPanel.vue` / `FilePreviewModal.vue` | 文件预览面板 / 弹窗（图片、文本、表格） |
| `DataAnalysisTree.vue` / `DataTreeNode.vue` | 数据分析生成的目录树（递归节点），面板头部含 reload 按钮 |
| `SearchResults.vue` | 搜索结果列表渲染 |
| `WebPreviewPanel.vue` | Electron 内嵌网页预览窗口（IPC `open-web-preview`） |

### 全局状态（App.vue）

```js
// 错误气泡保护态：SSE error 事件触发时把 session_id 加入此集合
_sessionHadError: Set<session_id>

// 保护态下的行为：
// - SSE done 事件不会用 AI 内容覆盖错误气泡
// - refreshConversation / updateTitleAndRefresh 跳过 messages 重拉，只更新侧边栏
// - 用户主动发起新一轮请求或中断续接时清掉保护态
```

### 刷新页面

```vue
<!-- ChatHeader.vue -->
<button @click="$emit('refresh')" class="refresh-btn" title="刷新页面 (Ctrl/⌘+R)">
  <svg ...><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
</button>
```

```js
// App.vue
refreshPage() {
  window.location.reload()  // 浏览器/Electron 通用，重新走 file:// → protocol.handle → 后端
}
```

三种触发方式：
1. 点击头部 ↻ 按钮
2. `Cmd+R` / `Ctrl+R`
3. 菜单 → 视图 → 刷新

## 路由

`src/router/index.js` 定义 vue-router 路由表。Web 端通过不同路径访问对话工作台、历史会话等页面。

## API 接口

Vite dev server 通过代理把 `/chat` 和 `/static` 转发到 `http://127.0.0.1:8211`，因此前端调用 `/chat/xxx` 与直接访问后端等价。

### 聊天接口（`/chat` 前缀）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/chat/` | POST | 流式对话（无 session_id 则新建） |
| `/chat/conversations` | GET | 会话列表 |
| `/chat/{session_id}/conversation` | GET | 会话详情 |
| `/chat/{session_id}/title` | GET / PUT | 获取 / 修改会话标题 |
| `/chat/{session_id}/clear` | DELETE | 删除会话（含聊天记录） |
| `/chat/{session_id}/backtrack` | POST | 回溯会话到指定轮 |
| `/chat/{session_id}/interrupt` | POST | 中断当前对话 |
| `/chat/{session_id}/invoke_interrupted/{msg}` | POST | 中断续接对话 |
| `/chat/{session_id}/upload_file` | POST | 上传文件 |
| `/chat/cancel_upload_file` | POST | 取消已上传文件 |
| `/chat/improve_input` | POST | 优化用户输入 |
| `/chat/file-config` | GET | 获取文件上传配置 |

### 其它接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/static/cached/{file_path:path}` | GET | 访问后端 cached 目录静态文件 |
| `/api/v1/chat/completions` | POST | 视觉语言模型服务（本地 Qwen3-VL） |
| `/admin/cleanup` | POST | 手动触发清理任务 |
| `/admin/cleanup/status` | GET | 获取清理状态 |

## SSE 事件协议

`/chat/` 流式响应按以下事件类型下发，前端 `App.vue` 集中分发：

| 事件 | 说明 |
|------|------|
| `content` | AI 正文字流（Markdown 增量） |
| `reasoning` | AI 思考过程（被 `<thinking>` 标签包裹的内容） |
| `tool_call_start` | 工具调用开始（带 tool_name / args 预览） |
| `tool_call_result` | 工具调用结果 |
| `tool_call_error` | 工具调用失败 |
| `memory_wait_start` | 上一轮记忆后台任务还在跑，开始等待 |
| `memory_wait_done` | 记忆后台任务结束，恢复对话 |
| `interrupt` | 对话被中断（携带 `memory_status`） |
| `done` | 对话正常结束（携带 `memory_status`，字段：`idle` / `pending` / `done` / `failed`） |
| `error` | 异常结束（前端把整条消息标 `error=true` 并加入 `_sessionHadError` 保护态） |

后端用 `_filter_thinking_content` 过滤 AI 输出中的 `<thinking>` 等思考标签，前端 `MessageItem.vue` 二次过滤兜底，避免标签残留在 UI 出现。

## Electron 启动命令

`package.json` 里 8 个脚本按用途分三类：

### 开发 / 调试

| 命令 | 等价操作 | 用途 |
|------|----------|------|
| `npm run dev` | `vite` | 仅启动 Vite dev server（端口 18211），浏览器访问 |
| `npm run electron:dev` | `NODE_ENV=development electron .` | 仅启动 Electron 主进程，要求 Vite 已先起 |
| `npm run electron:dev:all` | concurrently 起 vite + 等 18211 起来后再 electron | 联调推荐入口，一行命令搞定 Vite + Electron |
| `npm run preview` | `vite preview` | 本地预览 `dist/` 产物（不走 Electron） |

> `electron:dev` 模式下：Electron 加载 `http://localhost:18211`，DevTools 自动开启，菜单栏出现「开发」子菜单。

### 正式构建 / 打包

| 命令 | 等价操作 | 产物 |
|------|----------|------|
| `npm run build` | `vite build` | 仅产出 `dist/`，不打包桌面端 |
| `npm run electron:prod` | `NODE_ENV=production electron .` | 见下方「`electron:prod` 实际行为」说明 |
| `npm run electron:build` | `vite build && electron-builder` | 当前平台安装包（默认 electron-builder 配置） |
| `npm run electron:build:mac` | `vite build && electron-builder --mac` | macOS DMG + ZIP（arm64 + x64） |
| `npm run electron:build:win` | `vite build && electron-builder --win` | Windows NSIS |
| `npm run electron:build:linux` | `vite build && electron-builder --linux` | Linux AppImage |

### 三种环境在 UI 上的差异

| 环境 | `NODE_ENV` | 加载内容 | DevTools | 菜单栏「开发」 | 危险快捷键拦截 |
|------|-----------|----------|----------|---------------|---------------|
| 开发 | `development` | `http://localhost:18211`（Vite dev） | 开启（启动时自动打开） | 显示 | 不拦截 |
| 测试 | `test` | `http://localhost:18211`（Vite dev） | 开启 | 显示 | 不拦截 |
| 正式 | `production` 或未设 | `dist/index.html`（本地文件） | 关闭 | 隐藏 | 拦截 `F12` / `CmdOrCtrl+Shift+I/C/J` |

> `getEnvironmentConfig()` 内部还计算了 `label`（`DEV` / `TEST`）和 `color`（红 / 黄）字段，但当前 `main.js` 没有把它们显示到窗口标题栏上（仅「关于」弹窗展示 `mode`），属于预留位。如需在标题栏显示徽章，需要在 `createWindow` 里改写 `title` 字段。

### `electron:prod` 实际行为

`main.js` 顶部的判定是：

```js
const isDev = process.env.NODE_ENV === 'development'
const isTest = process.env.NODE_ENV === 'test'
```

完全按 `NODE_ENV` 严格走，**不再**被 `!app.isPackaged` 拖累。三种模式的实际行为：

- `NODE_ENV=development`（`electron:dev` / `electron:dev:all`）：加载 `http://localhost:18211`，自动开 DevTools，显示「开发」菜单
- `NODE_ENV=test`（手动 `NODE_ENV=test electron .`）：加载 `http://localhost:18211`，DevTools 开启但不自动打开，显示「开发」菜单
- `NODE_ENV=production` 或未设（`electron:prod` / 打包后运行）：加载 `dist/index.html`，关闭 DevTools，拦截危险快捷键

## Electron 配置

`electron/electron.config.js` 是桌面端的单一配置源，被 `main.js` import 进来：

| 配置项 | 当前值 | 说明 |
|--------|--------|------|
| `app.name` | `灵析` | 应用名（菜单栏第一项、`app.getName()`） |
| `app.title` | `灵析——数据分析智能助手` | 窗口标题 / 关于弹窗 |
| `app.identifier` | `com.chatme.app` | bundle identifier |
| `app.version` | `0.0.4` | 同步后端版本号 |
| `window.width × height` | `1100 × 720` | 主窗口尺寸 |
| `window.minWidth × minHeight` | `650 × 480` | 最小尺寸 |
| `devServer.url` | 从 Vite 导入的 `http://localhost:18211` | Electron 开发时加载的 URL |
| `backend.apiUrl` | `http://127.0.0.1:8211`（从 Vite 代理读取） | 后端地址 |
| `paths.indexHtml` | `dist/index.html`（asar 内） | Electron 正式模式加载的入口 HTML |
| `paths.preload` | `electron/preload.js`（asar 内） | preload 脚本路径 |
| `paths.icon` | dev: `electron/public/favicon.png`<br>packaged: `process.resourcesPath/build/icon.png` | 跨平台窗口图标 |
| `paths.iconMac` | dev: `build/icon.png`<br>packaged: `process.resourcesPath/build/icon.png` | macOS Dock 图标，必须是 **PNG** |
| `security.blockedShortcuts` | `['F12', 'CmdOrCtrl+Shift+I', 'CmdOrCtrl+Shift+C', 'CmdOrCtrl+Shift+J']` | 生产环境禁用 DevTools |
| `shortcuts.newChat` | `CmdOrCtrl+N` | 新建对话 |
| `shortcuts.reload` | `CmdOrCtrl+R` | 刷新页面（与菜单绑定） |

### 路径双形态（asar 内 vs asar 外）

`electron.config.js` 用 `app.isPackaged` 区分两条路径来源：

```js
// asar 内的文件（如 preload、index.html）：用 __dirname，asar patch 支持读取
indexHtml: path.join(__dirname, '../dist/index.html')

// 图标：必须放在 asar 外（nativeImage 不读 asar 内文件）
iconMac: app.isPackaged
  ? path.join(process.resourcesPath, 'build', 'icon.png')   // packaged: 包外 Resources/build/
  : path.join(__dirname, '../build/icon.png')                // dev: 源码 build/
```

`build/` 通过 `package.json` 的 `extraResources: [{ from: "build", to: "build" }]` 自动复制到 `app/Contents/Resources/build/`（macOS）/ `app/resources/build/`（Windows）/ `app/build/`（Linux），运行时用 `process.resourcesPath` 取真实路径。

### IPC 通道

| 通道 | 方向 | 说明 |
|------|------|------|
| `new-chat` | main → renderer | 菜单「新建对话」或快捷键触发，前端 `App.vue` 监听 |
| `open-web-preview` | renderer → main | 在 Electron 独立窗口打开外部链接 |

`preload.js` 通过 `contextBridge` 暴露两个对象：

- `window.electronAPI`：`onNewChat` / `getEnvironment` / `isDevelopment` / `isTest`
- `window.electron`：`openExternal` / `openWebPreview` / `onNewChat`

## Electron `file://` 协议拦截

`main.js` 在 `app.whenReady()` 内注册 `protocol.handle('file', ...)`，等价于 Vite dev 模式下的 proxy。**必须在 createWindow 之前注册**（内部访问 `session.defaultSession` 要求 ready）。

### 行为分流

| `pathname` 前缀 | 处理 |
|----------------|------|
| `/chat/*` | 转发到后端 `${config.backend.apiUrl}${pathname}${search}`（`net.fetch`） |
| `/static/*` | 转发到后端（同上） |
| 其他 | 当成 `dist/` 内的静态文件读盘 |

### API 转发（`/chat/*`、`/static/*`）

```js
const init = {
  method: request.method,
  headers: request.headers,
  ...(request.body && { body: request.body, duplex: 'half' })
}
const upstream = await net.fetch(backendUrl, init)
return new Response(upstream.body, {
  status: upstream.status,
  statusText: upstream.statusText,
  headers: upstream.headers
})
```

关键点：
- **必须显式转发 method / headers / body**：只传 URL 等于 GET 请求，POST `/chat/` 的 body 会被丢
- **SSE 流必须显式重建 Response**：`net.fetch` 返回的 `Response` 直接给 `protocol.handle`，body 会被 buffer，SSE "打字机效果"退化成一次性出现。包成新 Response 透传 `body` stream + status + headers 后才正确流式
- **`duplex: 'half'`** 是 Node 18+ fetch 转发流式请求体的要求

### 静态文件读盘（其他 `file://`）

```js
// 1. 白名单校验：resolvedPath 必须在 distDir 之下
if (!resolvedPath.startsWith(distDir + path.sep) && resolvedPath !== distDir) {
  return new Response('Forbidden', { status: 403 })
}

// 2. 读盘 + MIME 推断 + 缓存策略
const data = await fs.readFile(resolvedPath)
return new Response(data, {
  headers: {
    'Content-Type': MIME_TYPES[ext] || 'application/octet-stream',
    'Content-Length': String(data.length),
    'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=31536000, immutable'
  }
})
```

**白名单是安全关键**：如果不校验，渲染层一句 `fetch('/etc/passwd')` 就能读任意磁盘路径。

## 桌面端打包

### 前置条件

- 应用图标已就位（`build/icon.icns` / `icon.ico` / `icon.png`，`directories.buildResources: "build"`）
- macOS 打包需要 Xcode Command Line Tools；Windows 打包需要 Wine 或在 Windows 上跑；Linux 打包一般在 Linux 上跑（AppImage 跨平台有限制）
- 国内网络下 Electron 二进制下载慢，参考 [常见问题](#常见问题) 第 4 条

### 打包命令

```bash
# 当前平台
npm run electron:build

# 明确指定平台
npm run electron:build:mac      # 输出到 ../release/electron-builder/：*.dmg + *.zip
npm run electron:build:win      # 输出 *.exe（NSIS 安装器）
npm run electron:build:linux    # 输出 *.AppImage
```

`electron-builder` 的输出目录是 `../release/electron-builder/`（项目根，与 Vite 的 `dist/` / `frontend/` 区分开）。

### macOS 公证

如需分发到其他 Mac，目前默认不会做 Apple 公证。需要在 `package.json` 的 `build.mac` 里补 `notarize` 配置，或用 `electron-builder notarize` 后置脚本。

### DMG 镜像问题

DMG 阶段需要 `dmgbuild-bundle-arm64-*.tar.gz` 包，npmmirror 当前缺这个。绕过方案：
- 只打 zip：`npx electron-builder --mac zip --arm64 --x64`
- DMG 走 GitHub 直链：`ELECTRON_BUILDER_BINARIES_MIRROR=https://github.com npx electron-builder --mac dmg`

### 打开 .app

打包产物位置：
```
release/electron-builder/
├── mac-arm64/
│   └── 灵析.app          ← 直接打开
├── 灵析-0.0.1-arm64-mac.zip
└── 灵析-0.0.1-mac.zip
```

打开方式：
```bash
# Finder 双击
open ~/coding/projects/ChatMe/release/electron-builder/mac-arm64/灵析.app

# 命令行（直接执行）
"~/coding/projects/ChatMe/release/electron-builder/mac-arm64/灵析.app/Contents/MacOS/灵析"

# 解压 zip 后再打开
unzip 灵析-0.0.1-arm64-mac.zip -d ~/Downloads
open ~/Downloads/灵析.app
```

**前置依赖**：必须先启动后端（`uv run chatme_main`，端口 8211），否则前端 `/chat/*` 请求全部失败。

## 常见问题

### 1. Electron 启动后窗口是空白的

- 检查后端 Redis 是否启动（端口 6024）
- 检查 MCP 子进程是否随主服务拉起（stdio 模式：MCP 由 chatme_main 自动 fork，`ps -ef | grep chatme` 应见父子两进程）
- 检查主服务是否启动（端口 8211）
- Vite 代理 `/chat` 和 `/static` 到 8211；如改了后端端口，需同步 `vite.config.js` 的 `proxy`

### 2. macOS Dock 显示的图标不是准备好的图标

**原因**：`BrowserWindow` 的 `icon` 选项在 macOS 上只影响窗口标题栏，**不改变 Dock 图标**。

**修复方案**：
1. **开发模式也能看到正确图标**：在 `main.js` 启动后调用 `app.dock.setIcon(config.paths.iconMac)`（仅 macOS 生效）。**关键约束**：传入路径必须是 **PNG**——`app.dock.setIcon` 内部走 `nativeImage.createFromPath`，**不认 `.icns`**
2. **打包后正确显示**：`package.json` 的 `build.mac.icon` 指向 `build/icon.icns`；`extraResources` 把 `build/` 复制到 `app/Contents/Resources/build/`；`paths.iconMac` 通过 `app.isPackaged` 判断从 `process.resourcesPath` 取 PNG

### 3. Vite 代理提示 404 / 后端接口调用失败

检查 `vite.config.js` 的 `proxy` 配置：`/chat` 与 `/static` 都代理到 `http://127.0.0.1:8211`，没有 `changeOrigin` 设置的话跨域 header 会丢。

### 4. npm install 时 electron 下载慢

Electron 二进制走 GitHub release，国内网络经常卡。可以在 `~/.npmrc` 加：

```ini
electron_mirror=https://npmmirror.com/mirrors/electron/
electron_builder_binaries_mirror=https://npmmirror.com/mirrors/electron-builder-binaries/
```

### 5. 修改 vite.config.js 后 Electron 没生效

`electron/electron.config.js` 是 `await import('../vite.config.js')` 动态加载的，启动 Electron 时只加载一次。修改端口 / 代理后需要重启 `electron:dev`。

### 6. 打包后流式响应（SSE）只刷一次不持续

`protocol.handle` 没显式重建 Response，body 被 buffer。确认 `main.js` 用的是：
```js
return new Response(upstream.body, { status, statusText, headers })
```
而不是直接 `return net.fetch(backendUrl, init)`。

### 7. 打包后 POST `/chat/` 失败（405 / 空响应）

`protocol.handle` 没转发 method/body。确认 `main.js` 用的是 `method: request.method, headers: request.headers, ...(request.body && { body: request.body, duplex: 'half' })`，而不是只传 URL。

### 8. 打包后图标仍是 Electron 默认 logo

`build/` 没打进包。`package.json` 必须有 `extraResources: [{ from: "build", to: "build" }]`。运行时 `paths.iconMac` / `paths.icon` 用 `process.resourcesPath/build/icon.png` 读取。

---

如需补充更多章节（性能优化、国际化、可访问性），按项目实际进展追加。