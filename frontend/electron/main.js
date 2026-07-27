import { app, BrowserWindow, Menu, shell, ipcMain, protocol, net } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'
import { promises as fs } from 'fs'
import { spawn, exec } from 'child_process'
import { promisify } from 'util'
import netLib from 'net'
import fsSync from 'fs'
import os from 'os'
import http from 'http'

import {
  IS_WIN, IS_MAC, ARCH,
  venvPythonPath, getProjectRoot, getShellCmd, mcpReadyFilePath
} from './platform.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const configModule = await import('./electron.config.js')
const config = configModule.default

let mainWindow
let previewWindow = null

// 后端 / MCP 子进程引用（用于退出清理）
let backendProcess = null
let mcpProcess = null
// 项目根（app.whenReady 时算，因为 app.isPackaged 需要 ready）
let PROJECT_ROOT = null

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
  const envConfig = getEnvironmentConfig()

  mainWindow = new BrowserWindow({
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
      devTools: envConfig.devTools,
      preload: config.paths.preload
    },
    show: false,
    center: true
  })

  // 根据环境加载不同内容
  if (envConfig.loadUrl) {
    mainWindow.loadURL(envConfig.loadUrl)

    if (isDev) {
      mainWindow.webContents.openDevTools()
    }
  } else {
    mainWindow.loadFile(config.paths.indexHtml)
  }

  // 页面准备好后再显示窗口
  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

  // 窗口关闭事件
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // 生产环境禁用开发者功能
  if (!isDev && !isTest) {
    disableDeveloperFeatures(mainWindow)
  }

  // 设置菜单栏
  createMenu(envConfig)

  // 启动日志
  console.log('\n🚀 ' + config.app.title + ' 已启动')
  console.log('📍 运行模式:', envConfig.mode)
  console.log('🌐 访问地址:', envConfig.loadUrl || '本地文件')
  console.log('🔌 后端地址:', config.backend.apiUrl)
  console.log('📦 端口:', config.devServer.port)
  console.log('')
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
            title: `网页预览 - ${parsedUrl.hostname}`,
            icon: config.paths.icon,
            webPreferences: {
              nodeIntegration: false,
              contextIsolation: true,
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
 * 端口检测：返回 true 表示端口被占用（说明服务在跑）
 */
function isPortInUse(port) {
  return new Promise(resolve => {
    const server = netLib.createServer()
    server.once('error', () => resolve(true))
    server.once('listening', () => { server.close(); resolve(false) })
    server.listen(port, '127.0.0.1')
  })
}

/**
 * 流式 exec：把 stdout/stderr 实时回调给渲染层
 */
function execStream(cmd, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = exec(cmd, { ...opts, maxBuffer: 10 * 1024 * 1024 })
    if (opts.onLog) {
      child.stdout?.on('data', d => opts.onLog(d.toString()))
      child.stderr?.on('data', d => opts.onLog(d.toString()))
    }
    child.on('close', code => code === 0 ? resolve() : reject(new Error(`exit ${code}: ${cmd}`)))
    child.on('error', reject)
  })
}

const execAsync = promisify(exec)

// ---------- 单项探测 ----------
async function probePython() {
  // win 上 `python3` 不存在，用 `python`
  const cmd = getShellCmd('python3')
  try {
    const { stdout } = await execAsync(`${cmd} --version`)
    const m = stdout.match(/Python (\d+)\.(\d+)/)
    if (m && Number(m[1]) >= 3 && Number(m[2]) >= 12) {
      return { ok: true, detail: stdout.trim() }
    }
    return { ok: false, detail: `需要 Python 3.12+（当前 ${stdout.trim()}）` }
  } catch {
    return { ok: false, detail: 'Python 未安装' }
  }
}

async function probeUv() {
  try {
    const { stdout } = await execAsync('uv --version')
    return { ok: true, detail: stdout.trim() }
  } catch {
    return { ok: false, detail: 'uv 未安装' }
  }
}

async function probeDocker() {
  try {
    // `docker --version` 不验证 daemon；用 `docker info` 真正探测
    await execAsync('docker info', { timeout: 5000 })
    return { ok: true, detail: 'Docker daemon 运行中' }
  } catch {
    return { ok: false, detail: 'Docker 未启动或未安装' }
  }
}

async function probeRedisContainer() {
  try {
    const { stdout } = await execAsync(
      `docker ps --filter name=chatme-redis --format "{{.Names}}"`
    )
    const running = stdout.trim() === 'chatme-redis'
    return { ok: running, detail: running ? '运行中' : '容器未启动' }
  } catch {
    return { ok: false, detail: 'Docker 不可用' }
  }
}

async function probeSandboxImage() {
  try {
    const { stdout } = await execAsync(
      `docker images chatme-python-sandbox:latest -q`
    )
    return { ok: !!stdout.trim(), detail: stdout.trim() ? '镜像就绪' : '镜像未构建' }
  } catch {
    return { ok: false, detail: 'Docker 不可用' }
  }
}

async function probeVenv() {
  if (!PROJECT_ROOT) return { ok: false, detail: '项目根未初始化' }
  const pyPath = venvPythonPath(PROJECT_ROOT)
  try {
    await fsSync.promises.access(pyPath)
    return { ok: true, detail: '依赖已安装' }
  } catch {
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

async function fixRedis(onLog) {
  await execStream(
    `docker compose -f "${path.join(PROJECT_ROOT, 'docker-compose.yml')}" up -d redis`,
    { cwd: PROJECT_ROOT, onLog }
  )
}

async function fixSandbox(onLog) {
  await execStream(
    `docker compose -f "${path.join(PROJECT_ROOT, 'docker-compose.yml')}" build sandbox`,
    { cwd: PROJECT_ROOT, onLog }
  )
}

async function fixVenv(onLog) {
  await execStream(
    'uv sync --frozen',
    { cwd: path.join(PROJECT_ROOT, 'backend'), onLog, shell: true }
  )
}

// ---------- 启动后端 + MCP ----------
async function startMCP() {
  const pythonPath = venvPythonPath(PROJECT_ROOT)
  const backendDir = path.join(PROJECT_ROOT, 'backend')

  // 清理旧的 ready 文件
  try { fsSync.unlinkSync(mcpReadyFilePath()) } catch {}

  console.log('[mcp] starting:', pythonPath, '-m ChatMe.ChatWorkflow.mcps.server')

  mcpProcess = spawn(pythonPath, ['-m', 'ChatMe.ChatWorkflow.mcps.server'], {
    cwd: backendDir,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  mcpProcess.stdout?.on('data', d => console.log('[mcp]', d.toString().trimEnd()))
  mcpProcess.stderr?.on('data', d => console.error('[mcp]', d.toString().trimEnd()))
  mcpProcess.on('exit', (code) => {
    console.log('[mcp] exited:', code)
    mcpProcess = null
  })

  // 等 ready 文件（最多 60s；Redis 起 + 沙盒池初始化可能慢）
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    if (fsSync.existsSync(mcpReadyFilePath())) {
      console.log('[mcp] ready 文件已写入:', mcpReadyFilePath())
      return
    }
    if (mcpProcess === null) {
      throw new Error('MCP 进程已退出，未生成 ready 文件')
    }
    await new Promise(r => setTimeout(r, 500))
  }
  throw new Error('MCP 启动超时（60s）')
}

async function startBackend() {
  const pythonPath = venvPythonPath(PROJECT_ROOT)
  const backendDir = path.join(PROJECT_ROOT, 'backend')

  console.log('[backend] starting:', pythonPath, 'main.py')

  backendProcess = spawn(pythonPath, ['main.py'], {
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  backendProcess.stdout?.on('data', d => console.log('[backend]', d.toString().trimEnd()))
  backendProcess.stderr?.on('data', d => console.error('[backend]', d.toString().trimEnd()))
  backendProcess.on('exit', (code) => {
    console.log('[backend] exited:', code)
    backendProcess = null
  })

  // 轮询 /health（最多 90s；docling + QwenVL 首次加载可能慢）
  const deadline = Date.now() + 90_000
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
      if (backendProcess === null) {
        throw new Error('后端进程已退出，未通过 /health 检查')
      }
      await new Promise(r => setTimeout(r, 1000))
    }
  }
  throw new Error('后端启动超时（90s）/health 未通过')
}

// ---------- 引导窗口 ----------
function createSetupWindow() {
  const win = new BrowserWindow({
    width: 720,
    height: 560,
    resizable: false,
    minimizable: false,
    maximizable: false,
    title: '灵析 启动',
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      devTools: isDev,
      preload: path.join(__dirname, 'preload.js'),
    },
  })

  // 引导页路由：dev 走 Vite，prod 走 file:// dist/
  const envConfig = getEnvironmentConfig()
  if (envConfig.loadUrl) {
    // dev/test: Vite dev server，加载根路径，SetUpView 由 App.vue 条件渲染
    win.loadURL(envConfig.loadUrl)
  } else {
    // prod: 直接加载 dist/index.html，SetUpView 由 App.vue 条件渲染
    win.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  return win
}

// ---------- 注册 startup IPC ----------
function registerStartupIpc(setupWin) {
  ipcMain.handle('startup:probe-all', async () => {
    return {
      python: await probePython(),
      uv: await probeUv(),
      docker: await probeDocker(),
      redis: await probeRedisContainer(),
      sandbox: await probeSandboxImage(),
      venv: await probeVenv(),
    }
  })

  ipcMain.handle('startup:fix-item', async (e, item) => {
    const onLog = (msg) => e.sender.send('startup:log', { item, msg })
    try {
      switch (item) {
        case 'uv': await fixUv(onLog); break
        case 'redis': await fixRedis(onLog); break
        case 'sandbox': await fixSandbox(onLog); break
        case 'venv': await fixVenv(onLog); break
        default: throw new Error(`未知项: ${item}`)
      }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('startup:launch', async (e) => {
    try {
      await startMCP()
      await startBackend()
      // 通知渲染层切到主界面
      e.sender.send('startup:ready')
      // 关引导窗 + 开主窗口
      if (setupWin && !setupWin.isDestroyed()) setupWin.close()
      await createWindow()
      setupSecurityPolicies()
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })
}

// ==================== 应用生命周期 ====================
app.whenReady().then(async () => {
  // file:// 协议拦截器（必须在 createWindow 之前注册）
  registerFileProtocolInterceptor()

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

  // 算项目根（packaged 时 4 层上溯，dev 时 __dirname 上溯）
  PROJECT_ROOT = getProjectRoot(app)
  console.log('[setup] 项目根:', PROJECT_ROOT, '| 平台:', process.platform, ARCH, '| isPackaged:', app.isPackaged)

  // 1. 后端 + MCP 都已在跑？→ 直接进主窗口
  if (await isPortInUse(8211) && await isPortInUse(28211)) {
    console.log('[setup] 后端已在跑（端口 8211/28211 占用），跳过引导')
    await createWindow()
    setupSecurityPolicies()
    return
  }

  // 2. 缺后端 → 显示引导窗口
  const setupWin = createSetupWindow()

  // 注册 startup 相关 IPC
  registerStartupIpc(setupWin)

  setupWin.on('closed', () => {
    // 用户关引导窗且后端没起来 → 退出 app（避免主界面无后端的诡异状态）
    if (!backendProcess || backendProcess.killed) {
      console.log('[setup] 引导窗关闭且后端未启动 → app.quit()')
      app.quit()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

/**
 * 退出清理：杀我们 spawn 的后端/MCP 子进程
 * ⚠️ 只杀我们自己起的进程；端口已被占（外部进程）的情况**不**杀
 */
app.on('will-quit', () => {
  for (const [name, proc] of [['mcp', mcpProcess], ['backend', backendProcess]]) {
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