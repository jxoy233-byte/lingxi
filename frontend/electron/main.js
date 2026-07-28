import { app, BrowserWindow, Menu, shell, ipcMain, protocol, net, dialog } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'
import { promises as fs } from 'fs'
import { spawn, exec, spawnSync } from 'child_process'
import { promisify } from 'util'
import fsSync from 'fs'
import os from 'os'
import http from 'http'

import {
  IS_WIN, IS_MAC, ARCH,
  venvPythonPath, resolvePythonForBackend, getShellCmd, mcpReadyFilePath,
  discoverProjectRoot, isValidProjectRoot, saveProjectRoot,
  persistProjectRootToShell, execInUserShell, readStartupPreferences,
  saveStartupPreferences
} from './platform.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const configModule = await import('./electron.config.js')
const config = configModule.default

let mainWindow
let previewWindow = null

// 后端 / MCP 子进程引用（封装在 mcpProcRef / backendProcRef 里，配合 killChild 用）
// 项目根（app.whenReady 时算，因为 app.isPackaged 需要 ready）
let PROJECT_ROOT = null
let startupPreferences = { autoEnterFrontend: false }

// 后端 + MCP 是否就绪。主进程单方面维护，broadcast 给 renderer 驱动 view 切换。
// true → 渲染层翻 appReady=true，SetUpView 自动消失，主界面 mount 跑 initConversationState。
// false → SetUpView 显示，按钮可点。
let servicesReady = false

// ==================== 后端健康监测 ====================
//
// 主窗口起来后每 10s 探一次后端 /health + MCP ready 文件：
// - 仅在状态变化时推 IPC 给 renderer（10s → 6 次/分钟，对 localhost
//   几乎零开销，rAF 渲染 + SSE 才是真正大头）
// - renderer 收到 backend=false 时顶部出 banner + 「重新连接」按钮
// - 「重新连接」调 IPC 主动 kill + restart mcp/backend（不重启 app）

let healthMonitorInterval = null
let lastBackendHealth = null   // null = 还没探过
let lastMCPHealth = null

function startHealthMonitor() {
  if (healthMonitorInterval) return
  console.log('[health] monitor started (10s interval)')
  // 立即跑一次（不等 10s），首屏状态更快落到 UI
  runHealthCheck()
  healthMonitorInterval = setInterval(runHealthCheck, 10_000)
}

function stopHealthMonitor() {
  if (!healthMonitorInterval) return
  clearInterval(healthMonitorInterval)
  healthMonitorInterval = null
  console.log('[health] monitor stopped')
}

/**
 * 单次健康检查：并发探 backend + MCP；只有状态变了才推 IPC，避免
 * 每 10s 一次无意义的事件风暴（main → renderer）。
 */
async function runHealthCheck() {
  const [backendOk, mcpOk] = await Promise.all([checkBackendHealth(), checkMCPHealth()])
  if (backendOk === lastBackendHealth && mcpOk === lastMCPHealth) return
  lastBackendHealth = backendOk
  lastMCPHealth = mcpOk
  console.log(`[health] changed: backend=${backendOk} mcp=${mcpOk}`)
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('backend-health-changed', { backend: backendOk, mcp: mcpOk })
  }
}

// 判断是否为开发环境：严格按 NODE_ENV 判定（去掉 || !app.isPackaged，
// 否则 electron . 永远走 dev 分支，导致 electron:prod 加载不到 dist/）
const isDev = process.env.NODE_ENV === 'development'

// 判断是否为测试环境
const isTest = process.env.NODE_ENV === 'test'

// file:// 协议拦截器 MIME 表（处理相对路径资源时需要正确 Content-Type）
const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.mjs':  'application/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif':  'image/gif',
  '.svg':  'image/svg+xml',
  '.ico':  'image/x-icon',
  '.woff': 'font/woff',
  '.woff2':'font/woff2',
  '.ttf':  'font/ttf'
}

/**
 * file:// 协议拦截器：
 * - /chat/*、/static/*、/admin/* 转发到后端（等价于 dev 模式下 Vite proxy）
 * - 其他 file:// 请求直接从磁盘读盘返回（避开 net.fetch(file://) 在协议回调里可能的循环 / MIME 问题）
 *
 * 必须在 app.whenReady() 里调用（内部访问 session.defaultSession 要求 ready），
 * 且要在 createWindow 之前注册，否则首屏 file:// 请求会绕过拦截器。
 */
function registerFileProtocolInterceptor() {
  // 白名单基准目录：所有静态文件请求必须落在 dist/ 内，防止 fetch(/etc/passwd) 类 path traversal
  // dev 模式下指向源码 dist/；打包后指向 app.asar 内 dist/（Electron 的 fs patch 支持）
  const distDir = path.resolve(__dirname, '../dist')

  protocol.handle('file', async (request) => {
    const url = new URL(request.url)
    const pathname = url.pathname

    // API 路径转发到后端
    // 必须转发 method / headers / body —— 否则 POST /chat/ 会变成 GET，
    // 流式响应（SSE）的请求体也会被丢。
    // SSE 响应（text/event-stream）需要 duplex: 'half' 才能正确转发流式请求体；
    // 同时显式重建 Response 把 body stream 透传，避免 protocol.handle buffer。
    if (pathname.startsWith('/chat/') || pathname.startsWith('/static/') || pathname.startsWith('/admin/')) {
      const backendUrl = `${config.backend.apiUrl}${pathname}${url.search}`
      console.log('[proxy]', request.method, request.url, '→', backendUrl)

      const init = {
        method: request.method,
        headers: request.headers,
        ...(request.body && { body: request.body, duplex: 'half' })
      }
      const upstream = await net.fetch(backendUrl, init)

      // 显式重建 Response：确保 body 是 ReadableStream（不是 buffer）+ headers 全透传。
      // SSE 场景必须这样，否则 Electron 会等全部响应收完才一次性吐给 renderer，
      // 流式"打字机效果"就退化成"一次性出现"。
      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: upstream.headers
      })
    }

    // 静态资源：先做白名单校验，再读盘
    try {
      const filePath = decodeURIComponent(pathname)
      const resolvedPath = path.resolve(filePath)

      // 白名单：必须在 distDir 之下（用 + path.sep 防止 /dist-evil/ 这种前缀撞库）
      if (!resolvedPath.startsWith(distDir + path.sep) && resolvedPath !== distDir) {
        console.warn('[file] blocked non-dist read:', resolvedPath)
        return new Response('Forbidden', { status: 403 })
      }

      const data = await fs.readFile(resolvedPath)
      const ext = path.extname(resolvedPath).toLowerCase()
      const mime = MIME_TYPES[ext] || 'application/octet-stream'
      return new Response(data, {
        headers: {
          'Content-Type': mime,
          'Content-Length': String(data.length),
          // index.html 不缓存，hashed assets 永久缓存
          'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=31536000, immutable'
        }
      })
    } catch (e) {
      console.error('[file] read fail:', pathname, e.message)
      return new Response(`Not found: ${pathname}`, { status: 404 })
    }
  })
}

/**
 * 获取当前环境的配置
 */
function getEnvironmentConfig() {
  if (isDev) {
    return {
      mode: 'development',
      label: 'DEV',
      color: '#ff4757',
      loadUrl: config.devServer.url,
      devTools: true
    }
  } else if (isTest) {
    return {
      mode: 'test',
      label: 'TEST',
      color: '#ffa502',
      loadUrl: config.devServer.url,
      devTools: true
    }
  } else {
    return {
      mode: 'production',
      label: null,
      color: null,
      loadUrl: null,
      devTools: false
    }
  }
}

/**
 * 创建主窗口
 */
async function createWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (!mainWindow.isVisible()) mainWindow.show()
    mainWindow.focus()
    return mainWindow
  }

  const envConfig = getEnvironmentConfig()
  const win = new BrowserWindow({
    width: config.window.width,
    height: config.window.height,
    minWidth: config.window.minWidth,
    minHeight: config.window.minHeight,
    backgroundColor: config.window.backgroundColor,
    titleBarStyle: config.window.titleBarStyle,
    title: config.app.title,
    icon: config.paths.icon,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      // ⚠️ 关键：preload.js 用 ESM（package.json "type": "module"），
      // sandboxed renderer 不支持 ESM preload（必须 CommonJS）。
      sandbox: false,
      devTools: envConfig.devTools,
      preload: config.paths.preload
    },
    show: false,
    center: true
  })
  mainWindow = win

  let readyTimeout
  const readyPromise = new Promise((resolve, reject) => {
    readyTimeout = setTimeout(() => reject(new Error('主窗口加载超时')), 30_000)
    win.once('ready-to-show', () => {
      clearTimeout(readyTimeout)
      if (!win.isDestroyed()) win.show()
      resolve(win)
    })
    win.webContents.once('render-process-gone', (_event, details) => {
      clearTimeout(readyTimeout)
      reject(new Error(`主窗口渲染进程退出：${details.reason || 'unknown'}`))
    })
  })

  win.webContents.once('did-fail-load', (_event, errorCode, errorDescription) => {
    console.error('[window] 主窗口加载失败:', errorCode, errorDescription)
  })

  try {
    const loadPromise = envConfig.loadUrl
      ? win.loadURL(envConfig.loadUrl)
      : win.loadFile(config.paths.indexHtml)
    await Promise.all([loadPromise, readyPromise])
    if (envConfig.loadUrl && isDev) win.webContents.openDevTools()
  } catch (err) {
    clearTimeout(readyTimeout)
    if (!win.isDestroyed()) win.destroy()
    if (mainWindow === win) mainWindow = null
    throw err
  }

  win.on('closed', () => {
    if (mainWindow === win) mainWindow = null
  })

  // 兜底：主窗口加载完成后若 renderer 崩溃（GPU process 撤离 / OOM 等），
  // 自动 reload 一次恢复；用过 3 次还崩就放弃，避免无限循环。
  // 触发后 BrowserWindow 会被销毁，必须 recreate，新主窗口通过 app.activate / 用户再次触发。
  let mainWindowReloadAttempts = 0
  win.webContents.on('render-process-gone', (_event, details) => {
    console.error('[window] 主窗口 renderer 崩溃:', details)
    if (mainWindow === win && mainWindowReloadAttempts < 3 &&
        (details.reason === 'crashed' || details.reason === 'oom' || details.reason === 'abnormal-exit')) {
      mainWindowReloadAttempts++
      console.log(`[window] 尝试 reload 恢复 (${mainWindowReloadAttempts}/3)`)
      setTimeout(() => {
        if (!win.isDestroyed()) win.reload()
      }, 1000)
    }
  })

  if (!isDev && !isTest) disableDeveloperFeatures(win)
  createMenu(envConfig)

  console.log('\n🚀 ' + config.app.title + ' 已启动')
  console.log('📍 运行模式:', envConfig.mode)
  console.log('🌐 访问地址:', envConfig.loadUrl || '本地文件')
  console.log('🔌 后端地址:', config.backend.apiUrl)
  console.log('📦 端口:', config.devServer.port)
  console.log('')
  return win
}


/**
 * 禁用开发者相关功能（生产环境）
 */
function disableDeveloperFeatures(window) {
  // 禁用右键菜单
  window.webContents.on('context-menu', () => {})

  // 拦截键盘事件，阻止 DevTools 快捷键
  window.webContents.on('before-input-event', (event, input) => {
    const { key, control, shift, meta } = input

    // 检查是否在阻止列表中
    if (config.security.blockedShortcuts.includes(key)) {
      event.preventDefault()
      return
    }

    // 特殊处理组合键
    if ((control || meta) && shift) {
      if (['I', 'i', 'C', 'c', 'J', 'j'].includes(key)) {
        event.preventDefault()
      }
    }
  })
}

/**
 * 创建菜单栏
 */
function createMenu(envConfig) {
  const template = [
    {
      label: config.app.name,
      submenu: [
        {
          label: '关于',
          click: () => {
            const { dialog } = require('electron')
            dialog.showMessageBox({
              type: 'info',
              title: config.app.title,
              message: config.app.title,
              detail: `版本：${config.app.version}\n模式：${envConfig.mode}\n© 2026 灵析`,
              buttons: ['确定']
            })
          }
        },
        { type: 'separator' },
        {
          label: '新建对话',
          accelerator: config.shortcuts.newChat,
          click: () => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.send('new-chat')
            }
          }
        },
        { type: 'separator' },
        {
          label: '退出',
          accelerator: config.shortcuts.quit,
          click: () => app.quit()
        }
      ]
    },
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectAll', label: '全选' }
      ]
    },
    {
      label: '视图',
      submenu: [
        { role: 'reload', label: '刷新', accelerator: config.shortcuts.reload },
        { role: 'togglefullscreen', label: '全屏' },
        { type: 'separator' },
        { role: 'resetZoom', label: '实际大小' },
        { role: 'zoomIn', label: '放大' },
        { role: 'zoomOut', label: '缩小' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '切换全屏', accelerator: config.shortcuts.fullscreen }
      ]
    }
  ]

  // 只在开发和测试环境添加开发者工具菜单
  if (isDev || isTest) {
    template.push({
      label: '开发',
      submenu: [
        {
          label: '打开开发者工具',
          accelerator: config.shortcuts.toggleDevTools,
          click: () => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.openDevTools()
            }
          }
        },
        {
          label: '刷新页面',
          accelerator: config.shortcuts.reload,
          click: () => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.reload()
            }
          }
        }
      ]
    })
  }

  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}

/**
 * 设置安全策略
 */
function setupSecurityPolicies() {
  app.on('web-contents-created', (event, contents) => {

    // 限制导航
    contents.on('will-navigate', (event, navigationUrl) => {
      const parsedUrl = new URL(navigationUrl)

      // 开发和测试环境不限制
      if (isDev || isTest) return

      // 生产环境：主窗口阻止外部导航
      const currentUrl = contents.getURL()
      const isMainWindow = currentUrl.startsWith('file://') ||
                          currentUrl.includes(`localhost:${config.devServer.port}`)

      if (isMainWindow) {
        if (!parsedUrl.origin.includes('localhost') &&
            !parsedUrl.origin.startsWith('file://')) {
          event.preventDefault()
          shell.openExternal(navigationUrl)
        }
      }
    })

    // 允许打开新窗口（用于网页预览）
    contents.setWindowOpenHandler(({ url }) => {
      const parsedUrl = new URL(url)

      // 开发和测试环境允许所有
      if (isDev || isTest) {
        return { action: 'allow' }
      }

      // 生产环境：外部链接在新窗口打开
      const currentUrl = contents.getURL()
      const isMainWindow = currentUrl.startsWith('file://') ||
                          currentUrl.includes(`localhost:${config.devServer.port}`)

      if (isMainWindow &&
          !parsedUrl.origin.includes('localhost') &&
          !parsedUrl.origin.startsWith('file://')) {

        return {
          action: 'allow',
          overrideBrowserWindowOptions: {
            width: config.security.previewWindow.width,
            height: config.security.previewWindow.height,
            minimizable: true,
            maximizable: true,
            closable: true,
            // 默认 resizable:true（不显式设），用户可缩放预览窗口
            title: `网页预览 - ${parsedUrl.hostname}`,
            icon: config.paths.icon,
            webPreferences: {
              nodeIntegration: false,
              contextIsolation: true,
              // 同主窗口：ESM preload 必须 sandbox:false
              sandbox: false,
              devTools: false,
              preload: config.paths.preload
            }
          }
        }
      }

      return { action: 'deny' }
    })

    // 为预览窗口添加额外的安全限制
    contents.on('did-create-window', (previewWindow) => {
      const previewUrl = previewWindow.webContents.getURL()

      if (!previewUrl.includes('localhost') &&
          !previewUrl.startsWith('file://')) {

        const previewOrigin = new URL(previewUrl).origin

        previewWindow.webContents.on('will-navigate', (event, navUrl) => {
          const navParsedUrl = new URL(navUrl)
          if (navParsedUrl.origin !== previewOrigin) {
            event.preventDefault()
            shell.openExternal(navUrl)
          }
        })

        previewWindow.webContents.setWindowOpenHandler(() => {
          return { action: 'deny' }
        })
      }
    })
  })
}

// ==================== 启动流程：探测 + 修复 + 启动后端 ====================

/**
 * 后端健康检查：直接探 /health。
 * 端口 listen ≠ 服务 ready（FastAPI 启动 + 注册路由后才认 200），
 * 用端口探测会把"已 bind 但还没响应"的中间态当成 OK，跳过引导后立刻 502。
 */
function checkBackendHealth() {
  return new Promise(resolve => {
    const req = http.get('http://127.0.0.1:8211/health', res => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(1500, () => { req.destroy(); resolve(false) })
  })
}

/**
 * MCP 健康检查：MCP server.py 在 sandbox pool 初始化完后写 ready 文件，
 * 读这个文件比探端口可靠——端口可能已 listen 但 pool 还没 ready。
 */
async function checkMCPHealth() {
  try {
    await fsSync.promises.access(mcpReadyFilePath())
    return true
  } catch {
    return false
  }
}

// ==================== 子进程生命周期管理 ====================
//
// 设计：execStream（fixUv/fixRedis/fixSandbox/fixVenv）启动的子进程
// 走 shell exec 路径，**调用方不持有 child 引用**，没法在 will-quit 里 kill。
// 用户中途关引导窗 / app 异常退出时，docker build / uv sync 这种几分钟的
// 任务会变孤儿继续跑、占 CPU 内存 IO，下次启动 app 也清理不掉。
//
// 解决：execStream 内部把 child 加进全局 Set，所有退出路径兜底 kill。
// 注意：这里跟踪的是「shell exec 类的子进程」，MCP / backend 用 spawn
// 走 mcpProcRef / backendProcRef 那条线，不混在 Set 里。

const trackedChildProcesses = new Set()
let isKillingTracked = false

// Electron 父进程的 PATH 不带用户 shell 配置；用 shell 真实 PATH 作为兜底。
// 失败时（极少数 zsh 配置异常）退回原 process.env.PATH。
let _shellAugmentedPath = null
async function getShellAugmentedPath() {
  if (_shellAugmentedPath) return _shellAugmentedPath
  try {
    const out = await execInUserShell('printenv PATH', { timeout: 3000 })
    // 防御性清洗：zsh -ilc 偶尔会输出 "Restored session" 等噪音到 stdout
    // PATH 只包含目录路径，过滤掉非 / 开头的行
    const lines = out.split('\n').filter(l => l.trim().startsWith('/'))
    _shellAugmentedPath = lines.join(':') || process.env.PATH || ''
    return _shellAugmentedPath
  } catch {
    return process.env.PATH || ''
  }
}

/**
 * 给 spawn 子进程的 env 加 PATH 增强（同步版本：假设已经 getShellAugmentedPath 跑过缓存了）。
 * 用于 startMCP / startBackend 这种必须用 spawn 的场景——它们内部 spawn 出的 Python
 * 还要再 spawn docker / uv 之类的命令，必须继承完整 PATH。
 */
function withAugmentedEnv(env = process.env) {
  if (!_shellAugmentedPath) return env
  const sep = IS_WIN ? ';' : ':'
  const merged = [...new Set([
    ..._shellAugmentedPath.split(sep),
    ...((env.PATH || '').split(sep)),
  ])].join(sep)
  return { ...env, PATH: merged }
}

/**
 * 流式 exec：把 stdout/stderr 实时回调给渲染层；返回的子进程自动登记到
 * trackedChildProcesses 供退出时兜底 kill。
 *
 * env.PATH 用用户 shell 真实 PATH 增强（先 await 一次，缓存复用），保证
 * docker compose / uv sync 等长命令能命中 pyenv shim / Homebrew 等用户目录。
 */
async function execStream(cmd, opts = {}) {
  const shellPath = await getShellAugmentedPath()
  const sep = IS_WIN ? ';' : ':'
  const merged = [...new Set([
    ...(shellPath ? shellPath.split(sep) : []),
    ...((opts.env?.PATH || process.env.PATH || '').split(sep)),
  ])].join(sep)
  const env = { ...(opts.env || process.env), PATH: merged }

  const child = exec(cmd, { ...opts, env, maxBuffer: 10 * 1024 * 1024 })
  trackedChildProcesses.add(child)
  // 进程退出后从 Set 里删掉（已死的进程不用再 kill）
  const unregister = () => trackedChildProcesses.delete(child)
  child.on('close', unregister)
  child.on('error', unregister)

  return new Promise((resolve, reject) => {
    if (opts.onLog) {
      child.stdout?.on('data', d => opts.onLog(d.toString()))
      child.stderr?.on('data', d => opts.onLog(d.toString()))
    }
    child.on('close', code => code === 0 ? resolve() : reject(new Error(`exit ${code}: ${cmd}`)))
    child.on('error', reject)
  })
}

/**
 * 兜底杀所有 tracked 子进程。
 * SIGKILL 而非 SIGTERM：docker build / uv sync 卡在 IO 时 SIGTERM 不一定响应。
 * 多次调用幂等（clear + isKillingTracked 守卫）。
 */
function killTrackedChildren(reason = 'cleanup') {
  if (isKillingTracked || trackedChildProcesses.size === 0) return
  isKillingTracked = true
  const count = trackedChildProcesses.size
  console.log(`[cleanup] killing ${count} tracked child process(es) (${reason})`)
  for (const child of trackedChildProcesses) {
    try {
      if (IS_WIN) {
        // win 杀整个进程树（docker build 会拉一堆子进程）
        exec(`taskkill /pid ${child.pid} /T /F`, () => {})
      } else {
        child.kill('SIGKILL')
      }
    } catch (e) {
      console.error(`[cleanup] failed to kill pid=${child.pid}:`, e.message)
    }
  }
  trackedChildProcesses.clear()
  isKillingTracked = false
}

const execAsync = promisify(exec)

// ---------- 单项探测 ----------
// 所有 probe 走 execInUserShell 而不是 execAsync：拿到跟用户终端一致的 PATH。
// 用户在 .zshrc / .bashrc 里 export 的 pyenv / nvm / Homebrew / conda init 全部生效。

async function probePython() {
  // win 上 `python3` 不存在，用 `python`
  const cmd = getShellCmd('python3')
  try {
    // execInUserShell 已经合并 stdout+stderr（Python 3.12+ --version 走 stderr）
    const out = await execInUserShell(`${cmd} --version`)
    const m = out.match(/Python (\d+)\.(\d+)/)
    if (m && Number(m[1]) >= 3 && Number(m[2]) >= 12) {
      return { ok: true, detail: out }
    }
    return { ok: false, detail: `需要 Python 3.12+（当前 ${out || '未知版本'}）` }
  } catch {
    return { ok: false, detail: 'Python 未安装（请确认 python3 / python 命令在终端可用）' }
  }
}

async function probeUv() {
  try {
    return { ok: true, detail: await execInUserShell('uv --version') }
  } catch {
    return { ok: false, detail: 'uv 未安装（bootstrap 会自动装）' }
  }
}

async function probeDocker() {
  try {
    // `docker --version` 不验证 daemon；用 `docker info` 真正探测
    // 同时拉 `docker --version` 拿客户端版本号展示给用户
    const [_, version] = await Promise.all([
      execInUserShell('docker info', { timeout: 5000 }),
      execInUserShell('docker --version').catch(() => ''),
    ])
    return { ok: true, detail: version || 'Docker daemon 运行中' }
  } catch {
    return { ok: false, detail: 'Docker 未启动或未安装（请确认 Docker Desktop 已启动）' }
  }
}

/**
 * 项目根探测：app 不打包 backend/，所有命令都要在用户本地的 lingxi/ 目录下跑，
 * 所以「找到项目目录」本身就是第一个检查项。没找到时其余项全部无法进行。
 */
async function probeProjectRoot() {
  if (!PROJECT_ROOT) {
    return { ok: false, detail: '未找到项目目录，请手动选择 lingxi/ 根目录' }
  }
  return { ok: true, detail: PROJECT_ROOT }
}

async function probeRedisContainer() {
  try {
    // 用 `docker ps -a` 同时看运行 + exited 容器——区分 3 种状态给 fixRedis 用
    const out = await execInUserShell(
      `docker ps -a --filter name=chatme-redis --format "{{.Names}}\t{{.State}}"`
    )
    if (!out) return { ok: false, detail: '容器不存在' }
    const [, state] = out.split('\t')
    // 只 running 才算 ok；其他状态（exited/created/paused）交给 fixRedis 拉起来
    if (state === 'running') return { ok: true, detail: '运行中' }
    return { ok: false, detail: `容器存在但未运行（${state}）` }
  } catch {
    return { ok: false, detail: 'Docker 不可用' }
  }
}

async function probeSandboxImage() {
  try {
    const out = await execInUserShell(
      `docker images chatme-python-sandbox:latest -q`
    )
    return { ok: !!out, detail: out ? '镜像就绪' : '镜像未构建' }
  } catch {
    return { ok: false, detail: 'Docker 不可用' }
  }
}

async function probeVenv() {
  if (!PROJECT_ROOT) return { ok: false, detail: '待确定项目目录' }
  const pyPath = venvPythonPath(PROJECT_ROOT)
  try {
    await fsSync.promises.access(pyPath)
    return { ok: true, detail: '依赖已安装' }
  } catch {
    // venv 不存在时，启动后端会用系统 python 兜底（详见 resolvePythonForBackend）。
    // 但依赖没装的话 startBackend 会因为 import 失败报错——所以这里仍然标 ok=false
    // 让 bootstrap 跑 fixVenv 自动 uv sync 一次。
    return { ok: false, detail: '需运行 uv sync' }
  }
}

// ---------- 修复动作（带 onLog 流） ----------
async function fixUv(onLog) {
  if (IS_WIN) {
    // win 装到 %USERPROFILE%\.cargo\bin
    await execStream(
      'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
      { onLog, shell: true }
    )
    const cargoBin = path.join(os.homedir(), '.cargo', 'bin')
    process.env.PATH = `${cargoBin}${path.delimiter}${process.env.PATH}`
  } else {
    // mac/linux 装到 ~/.local/bin
    await execStream(
      'sh -c "curl -LsSf https://astral.sh/uv/install.sh | sh"',
      { onLog, shell: true }
    )
    const localBin = path.join(os.homedir(), '.local', 'bin')
    process.env.PATH = `${localBin}${path.delimiter}${process.env.PATH}`
  }
}

/**
 * 所有依赖项目目录的修复 / 启动动作前置校验。
 * app 不打包 backend/，PROJECT_ROOT 为 null 时这些命令没有落点，必须早失败给出可读原因。
 */
function requireProjectRoot() {
  if (!PROJECT_ROOT) {
    throw new Error('尚未确定项目目录，请先在上方选择本地 lingxi/ 根目录')
  }
  return PROJECT_ROOT
}

async function fixRedis(onLog) {
  const root = requireProjectRoot()
  const composeFile = path.join(root, 'docker-compose.yml')

  // 三种状态分别处理：
  //   - running：什么都不做（probe 已经标记 ok，理论上不会进到这里）
  //   - exited/created/paused：`docker start` 原地启动（保留数据卷），避免 docker compose up 报 name conflict
  //   - 不存在：`docker compose up -d` 创建
  // 不主动 `docker rm`：避免误删用户手动配置的容器或旧版残留（数据可能还在数据卷里）
  try {
    const inspectOut = await execInUserShell(
      `docker inspect chatme-redis --format "{{.State.Status}}" 2>/dev/null`
    ).catch(() => '')
    if (inspectOut === 'running') {
      onLog?.('[redis] 容器已在运行，跳过\n')
      return
    }
    if (inspectOut) {
      // 存在但未运行 → start 拉起来
      onLog?.(`[redis] 容器存在但状态 ${inspectOut}，尝试 start...\n`)
      await execStream('docker start chatme-redis', { cwd: root, onLog })
      // 等 Redis ready
      await waitForRedisReady(root, onLog)
      return
    }
    // 不存在 → compose 创建
    await execStream(
      `docker compose -f "${composeFile}" up -d redis`,
      { cwd: root, onLog }
    )
    await waitForRedisReady(root, onLog)
  } catch (err) {
    throw new Error(`Redis 启动失败: ${err.message}`)
  }
}

/**
 * 等 Redis 实际可连接（容器 up ≠ Redis ready，redis-server 进程还要 init）。
 * docker-compose.yml 里 REDIS_ARGS=--requirepass 123456 → 必须带 AUTH 才能 ping 通。
 */
async function waitForRedisReady(root, onLog) {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    try {
      const out = await execInUserShell(
        `docker exec chatme-redis redis-cli -a 123456 --no-auth-warning ping 2>/dev/null`
      )
      if (out === 'PONG') {
        onLog?.('[redis] ✅ PONG\n')
        return
      }
    } catch {
      // exec 失败 / NOAUTH 都说明还没好
    }
    await new Promise(r => setTimeout(r, 500))
  }
  throw new Error('Redis 启动 30s 未就绪')
}

async function fixSandbox(onLog) {
  const root = requireProjectRoot()
  await execStream(
    `docker compose -f "${path.join(root, 'docker-compose.yml')}" build sandbox`,
    { cwd: root, onLog }
  )
}

async function fixVenv(onLog) {
  const root = requireProjectRoot()
  await execStream(
    'uv sync --frozen',
    { cwd: path.join(root, 'backend'), onLog, shell: true }
  )
}

// ---------- 启动后端 + MCP ----------
/**
 * 杀子进程 + 清全局引用（用于失败兜底）。
 * SIGKILL 而非 SIGTERM——启动阶段进程可能卡在 import 链/IO 阻塞，SIGTERM 不一定响应。
 */
function killChild(procRef, name) {
  const proc = procRef.value
  if (!proc) return
  try {
    if (IS_WIN) {
      spawnSync('taskkill', ['/pid', String(proc.pid), '/T', '/F'], { windowsHide: true })
    } else {
      proc.kill('SIGKILL')
    }
    console.log(`[cleanup] killed ${name} (pid=${proc.pid})`)
  } catch (e) {
    console.error(`[cleanup] failed to kill ${name}:`, e.message)
  } finally {
    procRef.value = null
  }
}
const mcpProcRef = { value: null }      // 替 mcpProcess 存引用，封装 kill
const backendProcRef = { value: null }  // 替 backendProcess 存引用，封装 kill

async function startMCP(onLog) {
  const root = requireProjectRoot()
  const [pythonExe] = resolvePythonForBackend(root)
  const backendDir = path.join(root, 'backend')
  // MCP 进程内部还会直接调用 docker / docker-compose；确保它继承用户 shell 的完整 PATH。
  await getShellAugmentedPath()

  // 清理旧的 ready 文件
  try { fsSync.unlinkSync(mcpReadyFilePath()) } catch {}

  console.log('[mcp] starting:', pythonExe, '-m ChatMe.ChatWorkflow.mcps.server')
  onLog?.(`[mcp] starting: ${pythonExe} -m ChatMe.ChatWorkflow.mcps.server\n`)

  const proc = spawn(pythonExe, ['-m', 'ChatMe.ChatWorkflow.mcps.server'], {
    cwd: backendDir,
    env: withAugmentedEnv({ ...process.env, PYTHONUNBUFFERED: '1' }),
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  mcpProcRef.value = proc

  proc.stdout?.on('data', d => {
    const msg = d.toString().trimEnd()
    console.log('[mcp]', msg)
    onLog?.(msg + '\n')
  })
  proc.stderr?.on('data', d => {
    const msg = d.toString().trimEnd()
    console.error('[mcp]', msg)
    onLog?.(msg + '\n')
  })
  proc.on('exit', (code) => {
    console.log('[mcp] exited:', code)
    if (mcpProcRef.value === proc) mcpProcRef.value = null
  })

  // 等 ready 文件（最多 60s；Redis 起 + 沙盒池初始化可能慢）
  const deadline = Date.now() + 60_000
  try {
    while (Date.now() < deadline) {
      if (fsSync.existsSync(mcpReadyFilePath())) {
        console.log('[mcp] ready 文件已写入:', mcpReadyFilePath())
        return
      }
      if (mcpProcRef.value === null) {
        throw new Error('MCP 进程已退出，未生成 ready 文件')
      }
      await new Promise(r => setTimeout(r, 500))
    }
    throw new Error('MCP 启动超时（60s）')
  } catch (err) {
    // ⚠️ 失败兜底：杀掉子进程，避免泄漏
    killChild(mcpProcRef, 'mcp')
    throw err
  }
}

async function startBackend(onLog) {
  const root = requireProjectRoot()
  const [pythonExe] = resolvePythonForBackend(root)
  const backendDir = path.join(root, 'backend')
  // 保证后端及其间接启动的命令继承用户 shell 的完整 PATH。
  await getShellAugmentedPath()

  console.log('[backend] starting:', pythonExe, 'main.py')
  onLog?.(`[backend] starting: ${pythonExe} main.py\n`)

  const proc = spawn(pythonExe, ['main.py'], {
    cwd: backendDir,
    env: withAugmentedEnv({ ...process.env, PYTHONUNBUFFERED: '1' }),
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  backendProcRef.value = proc

  // stdout/stderr 推到引导页日志，让用户能看到 traceback / ImportError 等真实原因
  proc.stdout?.on('data', d => {
    const msg = d.toString().trimEnd()
    console.log('[backend]', msg)
    onLog?.(msg + '\n')
  })
  proc.stderr?.on('data', d => {
    const msg = d.toString().trimEnd()
    console.error('[backend]', msg)
    onLog?.(msg + '\n')
  })
  proc.on('exit', (code) => {
    console.log('[backend] exited:', code)
    if (backendProcRef.value === proc) backendProcRef.value = null
  })

  // 轮询 /health（最多 90s；docling + QwenVL 首次加载可能慢）
  const deadline = Date.now() + 90_000
  try {
    while (Date.now() < deadline) {
      try {
        await new Promise((resolve, reject) => {
          const req = http.get('http://127.0.0.1:8211/health', res => {
            res.resume()
            resolve(res.statusCode === 200)
          })
          req.on('error', reject)
          req.setTimeout(1500, () => req.destroy(new Error('timeout')))
        })
        console.log('[backend] /health OK')
        return
      } catch {
        if (backendProcRef.value === null) {
          throw new Error('后端进程已退出，未通过 /health 检查（看上方日志获取 traceback）')
        }
        await new Promise(r => setTimeout(r, 1000))
      }
    }
    throw new Error('后端启动超时（90s）/health 未通过')
  } catch (err) {
    // ⚠️ 失败兜底：杀掉子进程，避免泄漏
    killChild(backendProcRef, 'backend')
    throw err
  }
}

// ---------- 服务就绪状态广播 ----------
/**
 * 设置 servicesReady 并推送给 renderer。
 *
 * payload.autoEnterFrontend 是从 bootstrap options 透传下来的偏好——
 * cold start 完成时：true → App.vue 立即翻 appReady=true（自动进）；
 *                  false → App.vue 保持 appReady=false（SetUpView 仍挂载，展示「进入应用」按钮等用户点）。
 * warm path（app.whenReady 已健康）无需等用户点，固定传 true。
 *
 * ready=false（后端挂掉）不带 autoEnterFrontend 字段；renderer 只看 ready 决定 SetUpView 渲染。
 */
function setServicesReady(ready, payload = {}) {
  if (servicesReady === ready) return
  servicesReady = ready
  console.log(`[setup] servicesReady → ${ready}`, payload)
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('startup:services-ready-changed', {
      ready,
      autoEnterFrontend: payload.autoEnterFrontend,
    })
  }
  // 健康检查同步更新 banner（之前 backend/mcp 都 false，现在应都 true）
  if (ready) runHealthCheck()
}

// ---------- 注册 startup IPC ----------
/**
 * 主动重启 mcp + backend（用户在 banner 上点「重新连接」时调用）。
 * - 先 SIGKILL 旧子进程（含 taskkill /T /F 杀整个进程树）
 * - 再走 startMCP / startBackend 串行重启
 * - 完成后推 servicesReady(true) 给 renderer；autoEnterFrontend=true 是因为用户
 *   已经在 app 里（被踢回 disabled），重启恢复后直接交回交互权，不必再弹「进入应用」按钮。
 *   注意 setServicesReady 内部会去重 + 只在状态翻转时推，重复 restart 不会刷屏。
 * - 失败抛错，由 IPC 兜底返回 { ok: false, error } 让前端给用户反馈
 */
async function restartBackend() {
  killChild(mcpProcRef, 'mcp')
  killChild(backendProcRef, 'backend')
  // 给 OS 回收旧 socket / 释放端口的时间（FastAPI 软关闭可能 1-2s 没收完）
  await new Promise(r => setTimeout(r, 500))
  await startMCP()
  await startBackend()
  // 推 servicesReady 状态（让 renderer 翻 appReady=true + initConversation）+
  // 即时健康检查（让 banner 立即消失）。两者独立：前者解除 disabled，后者驱动 banner。
  setServicesReady(true, { autoEnterFrontend: true })
  runHealthCheck()
}

function registerStartupIpc() {
  /**
   * SetUpView 显示用的 3 项检查：项目根 / python / docker。
   * uv/redis/sandbox/venv 都是「docker 在 + python 在」之后自动配的，
   * 暴露给用户只会增加操作成本（要按 4 次"配置"按钮）。
   */
  ipcMain.handle('startup:probe-all', async () => {
    return {
      projectRoot: await probeProjectRoot(),
      python: await probePython(),
      docker: await probeDocker(),
    }
  })

  // 当前项目根（引导页头部展示用）
  ipcMain.handle('startup:get-project-root', async () => PROJECT_ROOT)

  /**
   * 手动选择项目根目录。
   * 自动定位（env → saved → dev → BFS）失败，或用户想换一个 checkout 时用。
   * 选中后校验结构（backend/pyproject.toml + docker-compose.yml），通过才持久化：
   *   - userData（app 自身下次启动用）
   *   - shell env（LINGXI_PROJECT_ROOT，CLI 启动用，rc 文件 / setx）
   */
  ipcMain.handle('startup:pick-project-root', async () => {
    const dialogOptions = {
      title: '选择 lingxi 项目根目录',
      message: '选择从 GitHub 拉取的项目根目录（内含 backend/ 和 docker-compose.yml）',
      properties: ['openDirectory'],
    }
    // 单窗口架构：用主窗口做 parent（modal 关系），没主窗口时退化为无 parent
    const { canceled, filePaths } = mainWindow && !mainWindow.isDestroyed()
      ? await dialog.showOpenDialog(mainWindow, dialogOptions)
      : await dialog.showOpenDialog(dialogOptions)
    if (canceled || !filePaths?.length) return { ok: false, error: '已取消' }

    const dir = filePaths[0]
    if (!isValidProjectRoot(dir)) {
      return {
        ok: false,
        error: `目录结构不匹配：${dir}\n需要同时存在 backend/pyproject.toml 和 docker-compose.yml`,
      }
    }

    PROJECT_ROOT = dir
    try {
      saveProjectRoot(app, dir)
    } catch (e) {
      console.error('[setup] userData 持久化失败:', e.message)
    }
    // shell env 写入是 best-effort——rc 文件没权限 / setx 失败都不阻塞
    persistProjectRootToShell(dir).then(r => {
      if (r.ok) {
        console.log('[setup] shell env:', r.skipped ? `${r.rcFile} 已存在，跳过` : `已写入 ${r.rcFile}`)
      } else {
        console.warn('[setup] shell env 写入失败:', r.error)
      }
    })
    console.log('[setup] 项目根已手动设置:', dir)
    return { ok: true, projectRoot: dir }
  })

  /**
   * 一键 bootstrap：用户点"启动应用"后跑这条链路。
   * 1) 装 uv（如果没装）→ 2) 起 redis 容器 → 3) 构沙盒镜像 →
   * 4) uv sync 装 python 依赖 → 5) 起 MCP → 6) 起后端 → setServicesReady(true)
   *
   * setServicesReady 触发 renderer 翻 appReady=true，SetUpView 自动消失。
   * 单窗口架构下不再需要「切主窗口」步骤，GPU/renderer 资源完全稳定。
   *
   * 任一步抛错：杀掉所有已起的子进程（不漏 mcp/backend 孤儿）+ 错误回给前端
   */
  ipcMain.handle('startup:bootstrap', async (e, options = {}) => {
    const autoEnterFrontend = options.autoEnterFrontend === true
    startupPreferences = { autoEnterFrontend }
    try { saveStartupPreferences(app, startupPreferences) } catch (err) {
      console.error('[setup] 启动偏好保存失败:', err.message)
    }
    const onLog = (item, msg) => e.sender.send('startup:log', { item, msg })
    try {
      // 1. uv
      if (!(await probeUv()).ok) {
        onLog('uv', '正在安装 uv 包管理器...\n')
        await fixUv((m) => onLog('uv', m))
      }
      onLog('uv', '✅ uv 就绪\n')

      // 2. redis
      if (!(await probeRedisContainer()).ok) {
        onLog('redis', '正在启动 Redis 容器...\n')
        await fixRedis((m) => onLog('redis', m))
      }
      onLog('redis', '✅ Redis 就绪\n')

      // 3. sandbox image
      if (!(await probeSandboxImage()).ok) {
        onLog('sandbox', '正在构建沙盒镜像（首次较慢，可能数分钟）...\n')
        await fixSandbox((m) => onLog('sandbox', m))
      }
      onLog('sandbox', '✅ 沙盒镜像就绪\n')

      // 4. python venv
      if (!(await probeVenv()).ok) {
        onLog('venv', '正在同步 Python 依赖（首次较慢）...\n')
        await fixVenv((m) => onLog('venv', m))
      }
      onLog('venv', '✅ Python 依赖就绪\n')

      // 5. MCP
      onLog('mcp', '正在启动 MCP 服务...\n')
      await startMCP((m) => onLog('mcp', m))
      onLog('mcp', '✅ MCP 就绪\n')

      // 6. backend
      onLog('backend', '正在启动后端服务（首次加载 docling/QwenVL 可能较慢）...\n')
      await startBackend((m) => onLog('backend', m))
      onLog('backend', '✅ 后端就绪\n')

      onLog('startup', '✅ 后端已就绪\n')
      // 广播 servicesReady=true。autoEnterFrontend=true 让 renderer 立即翻 appReady=true +
      // initConversationState；=false 时 renderer 不翻 appReady，SetUpView 保留挂载并显示
      // 「进入应用」按钮等用户主动点。
      setServicesReady(true, { autoEnterFrontend })
      return { ok: true }
    } catch (err) {
      // 失败兜底：杀掉所有已起的子进程，避免 mcp/backend 泄漏
      killChild(mcpProcRef, 'mcp')
      killChild(backendProcRef, 'backend')
      // 兜底：杀掉 tracked shell 子进程（理论上 fixXxx 失败时子进程已 close，
      // 杀不到；但保险起见再清一次，防止某步没正确 unregister）
      killTrackedChildren('bootstrap-failed')
      setServicesReady(false)
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('startup:get-preferences', async () => startupPreferences)

  ipcMain.handle('startup:set-auto-enter', async (_event, value) => {
    startupPreferences = { autoEnterFrontend: value === true }
    try {
      saveStartupPreferences(app, startupPreferences)
      return { ok: true, ...startupPreferences }
    } catch (err) {
      return { ok: false, error: err.message, ...startupPreferences }
    }
  })

  ipcMain.handle('startup:get-services-ready', async () => servicesReady)

  /**
   * 健康监测 IPC：
   * - get-health：renderer 首次 mount 时拉一次当前状态（避免等下一个 10s 周期才更新 banner）
   * - restart-backend：用户在 banner 上点「重新连接」时主动 kill + restart mcp/backend
   * 状态变化走 mainWindow.webContents.send('backend-health-changed', ...) push，无需 renderer 轮询
   */
  ipcMain.handle('startup:get-health', async () => {
    const [backend, mcp] = await Promise.all([checkBackendHealth(), checkMCPHealth()])
    lastBackendHealth = backend
    lastMCPHealth = mcp
    return { backend, mcp }
  })

  ipcMain.handle('startup:restart-backend', async () => {
    try {
      await restartBackend()
      return { ok: true }
    } catch (e) {
      console.error('[health] restart failed:', e)
      return { ok: false, error: e.message }
    }
  })
}

// ==================== 应用生命周期 ====================
app.whenReady().then(async () => {
  // file:// 协议拦截器（必须在 createWindow 之前注册）
  registerFileProtocolInterceptor()

  // 全局安全策略（app-level event，**只**在 app 启动时注册一次即可，
  // 两条进入主窗口的路径（端口都在用 / 引导完成）共用）。原代码在
  // createWindow() 之后再注册，逻辑上跟两条路径绑死、易漏。
  setupSecurityPolicies()

  // macOS: 显式设置 Dock 图标（BrowserWindow.icon 在 macOS 不影响 Dock，
  // 未打包时 Dock 默认显示 Electron logo，这里用 PNG 覆盖）。
  // 注意：setIcon 返回 Promise，必须 catch 否则会冒 unhandledRejection。
  if (process.platform === 'darwin' && app.dock) {
    try {
      const result = app.dock.setIcon(config.paths.iconMac)
      if (result && typeof result.catch === 'function') {
        result.catch(err => console.error('[icon] dock setIcon 失败:', err.message))
      }
    } catch (e) {
      console.error('[icon] dock setIcon 抛错:', e.message)
    }
  }

  // 定位用户本地的 lingxi/ 项目目录（app 内不打包 backend/，所有命令都在它下面跑）。
  // 没定位到时 PROJECT_ROOT 为 null，引导页会要求用户手动选目录。
  const discovered = discoverProjectRoot(app)
  PROJECT_ROOT = discovered.root
  console.log(
    '[setup] 项目根:', PROJECT_ROOT ?? '(未找到)',
    '| 来源:', discovered.source,
    '| 平台:', process.platform, ARCH,
    '| isPackaged:', app.isPackaged
  )

  startupPreferences = readStartupPreferences(app)

  // 探测当前服务状态。已健康时直接置 servicesReady=true，App.vue 翻 appReady=true
  // 直接进主界面，SetUpView 不会渲染。autoEnterFrontend 现在由 SetUpView 消费，
  // 用来自动触发 bootstrap；这里不再分流到 setup 窗口。
  const [backendOk, mcpOk] = await Promise.all([checkBackendHealth(), checkMCPHealth()])
  lastBackendHealth = backendOk
  lastMCPHealth = mcpOk
  console.log(
    `[setup] 后端状态 backend=${backendOk}, mcp=${mcpOk}, ` +
    `autoEnter=${startupPreferences.autoEnterFrontend}`
  )

  // 单窗口架构：始终一个主窗口，渲染层根据 servicesReady 决定显示 SetUpView 还是主界面。
  // 注册 IPC 必须在 createWindow 之前——renderer 加载 index.html 后会立即
  // 调 getServicesReady / getHealth / getStartupPreferences；handlers 没注册就抛错。
  registerStartupIpc()
  await createWindow()
  startHealthMonitor()

  // 服务已健康 → 同步置 servicesReady=true，触发 SetUpView 消失。
  // 这必须在 registerStartupIpc() 之后（renderer 已能收到事件），且在 createWindow 之后（renderer 已挂载）。
  // warm path 总是 autoEnter=true（用户已经在 app 里了，无需等点「进入应用」）。
  if (backendOk && mcpOk) {
    setServicesReady(true, { autoEnterFrontend: true })
  }
})

app.on('window-all-closed', () => {
  // 本应用后端会常驻 VL 模型并占用大量内存；关闭所有窗口即视为退出，
  // macOS 也不保留无窗口的后台主进程，确保 before-quit 清理我们启动的服务。
  app.quit()
})

/**
 * 退出清理：杀我们 spawn 的后端/MCP 子进程 + tracked shell 子进程
 * ⚠️ 只杀我们自己起的进程；端口已被占（外部进程）的情况**不**杀
 */
app.on('will-quit', () => {
  // 0. 停止健康监测定时器，避免跑空检查 + IPC 到已销毁的 webContents
  stopHealthMonitor()

  // 1. tracked shell 子进程（docker build / uv sync / redis up）—— SIGKILL 强杀
  killTrackedChildren('will-quit')

  // 2. spawn 出来的 mcp / backend —— SIGTERM 软退出 + 3s 后 SIGKILL
  for (const [name, ref] of [['mcp', mcpProcRef], ['backend', backendProcRef]]) {
    const proc = ref.value
    if (!proc) continue
    try {
      if (IS_WIN) {
        // win 不支持 SIGTERM，用 taskkill /T 杀整个进程树
        exec(`taskkill /pid ${proc.pid} /T /F`, () => {})
      } else {
        proc.kill('SIGTERM')
        // 给 3s 软退出，超时强杀
        setTimeout(() => { try { proc.kill('SIGKILL') } catch {} }, 3000)
      }
      console.log(`[cleanup] killed ${name} (pid=${proc.pid})`)
    } catch (e) {
      console.error(`[cleanup] failed to kill ${name}:`, e.message)
    }
  }
  // 清理 ready 文件
  try { fsSync.unlinkSync(mcpReadyFilePath()) } catch {}
})

/**
 * before-quit：用户触发退出（Cmd+Q / app.quit）时第一时间杀 tracked 子进程，
 * 不等 will-quit，避免在 will-quit 之前子进程已经把父进程当 orphan 处理掉。
 */
app.on('before-quit', () => {
  killTrackedChildren('before-quit')
  // 可控退出必须同步清掉由 App 启动的常驻服务。backend 会加载 VL 模型，不能在
  // macOS 无窗口状态下继续占内存；Windows 使用同步 taskkill，确保 Electron 退出前完成。
  killChild(mcpProcRef, 'mcp')
  killChild(backendProcRef, 'backend')
  try { fsSync.unlinkSync(mcpReadyFilePath()) } catch {}
})

/**
 * 异常退出兜底：uncaughtException / SIGINT / SIGTERM / exit
 * 全部走 killTrackedChildren，避免 docker build 等变成孤儿继续跑。
 * 多次调用幂等（killTrackedChildren 内部守卫）。
 */
process.on('uncaughtException', (err) => {
  console.error('[fatal] uncaughtException:', err)
  killTrackedChildren('uncaughtException')
  // 不阻止默认 handler：打印 stack 并以非 0 退出
  process.exit(1)
})

if (!IS_WIN) {
  // macOS / Linux：开发模式 `Ctrl+C` 走 SIGINT；外部 `kill <pid>` 走 SIGTERM
  process.on('SIGINT', () => {
    console.log('[signal] SIGINT received')
    killTrackedChildren('SIGINT')
    process.exit(130)
  })
  process.on('SIGTERM', () => {
    console.log('[signal] SIGTERM received')
    killTrackedChildren('SIGTERM')
    process.exit(143)
  })
}

/**
 * exit 同步兜底：kill 是异步的，process.exit 不会等，
 * 但 child 收到 SIGKILL 后会被 OS 终止，不会成为长期 orphan。
 * win 上 child.kill 在 child_process 里走的是 TerminateProcess，同步生效；
 * 之前 will-quit 已经 taskkill 过，这里再走一遍兜底。
 */
process.on('exit', (code) => {
  if (trackedChildProcesses.size > 0) {
    console.log(`[exit] code=${code}, ${trackedChildProcesses.size} child still tracked, sending SIGKILL`)
    for (const child of trackedChildProcesses) {
      try {
        if (IS_WIN) {
          // win 上 child.kill 走 TerminateProcess；但 execStream 启动的 child
          // 可能被 shell 包装了一层（cmd.exe /c ...），不一定真杀到孙进程。
          // 用同步 execSync + taskkill 强保险。
          const { execSync } = require('child_process')
          try { execSync(`taskkill /pid ${child.pid} /T /F`, { stdio: 'ignore' }) } catch {}
        } else {
          child.kill('SIGKILL')
        }
      } catch {}
    }
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})

// 证书错误处理（开发环境忽略）
app.on('certificate-error', (event, webContents, url, error, certificate, callback) => {
  if (isDev) {
    event.preventDefault()
    callback(true)
  } else {
    callback(false)
  }
})

// 允许不安全的 HTTPS（仅开发环境）
if (isDev) {
  app.commandLine.appendSwitch('ignore-certificate-errors')
}

// ==================== IPC 事件处理 ====================

/**
 * 渲染层点 ↻ 刷新按钮时调用。
 * 直接走 mainWindow.webContents.reload()，绕过 JS 级 window.location.reload()：
 *   - file:// + protocol.handle 拦截器下，window.location.reload() 偶尔会被拦截或
 *     没有可见 reload 反馈（页面状态刷新太快），用户感觉「点没反应」
 *   - webContents.reload() 是 BrowserWindow 原生能力，跨 win/mac/linux 都一致行为
 *   - 同时让 .app-disabled 重置：reload 后 mounted 重跑，appReady 重新从 false 起步，
 *     SetUpView 会瞬间出现再被 servicesReady=true 隐藏，体感上是真正的「整页硬刷」
 */
ipcMain.handle('app:refresh-page', async () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.reload()
  }
  return { ok: true }
})

ipcMain.handle('open-web-preview', async (event, url) => {
  if (previewWindow && !previewWindow.isDestroyed()) {
    previewWindow.focus()
    previewWindow.loadURL(url)
  } else {
    previewWindow = new BrowserWindow({
      width: config.security.previewWindow.width,
      height: config.security.previewWindow.height,
      minWidth: 600,
      minHeight: 500,
      title: `网页预览 - ${url}`,
      icon: config.paths.icon,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        // 同主窗口：ESM preload 必须 sandbox:false
        sandbox: false,
        devTools: isDev,
        preload: path.join(__dirname, 'preload.js')
      }
    })

    previewWindow.loadURL(url)

    previewWindow.on('closed', () => {
      previewWindow = null
    })
  }
  return true
})