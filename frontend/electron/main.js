import { app, BrowserWindow, Menu, shell, ipcMain, protocol, net, dialog } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'
import { promises as fs } from 'fs'
import { spawn, exec, spawnSync } from 'child_process'
import { promisify } from 'util'
import fsSync from 'fs'
import os from 'os'
import http from 'http'
import nodeNet from 'net'

import {
  IS_WIN, IS_MAC, ARCH,
  venvPythonPath, resolvePythonForBackend, getShellCmd,
  discoverProjectRoot, isValidProjectRoot, saveProjectRoot,
  persistProjectRootToShell, execInUserShell, readStartupPreferences,
  saveStartupPreferences,
  autoCloneProject,
  setLastCloneTarget,
  startDockerDesktop,
  LINGXI_REPO_URL,
} from './platform.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const configModule = await import('./electron.config.js')
const config = configModule.default

let mainWindow
let previewWindow = null

// 项目根（app.whenReady 时算，因为 app.isPackaged 需要 ready）
let PROJECT_ROOT = null
let startupPreferences = { autoEnterFrontend: false }

// 后端是否就绪。主进程单方面维护，broadcast 给 renderer 驱动 view 切换。
// true → 渲染层翻 appReady=true，BootstrapView 自动消失，主界面 mount 跑 initConversationState。
// false → BootstrapView 显示，按钮可点。
//
// 注：MCP server 在 stdio 模式下作为 chatme_main 的子进程被 fork，跟着 backend
// 一起 ready / 死掉，不再单独探。
let servicesReady = false

// ==================== 后端健康监测 ====================
//
// 主窗口起来后每 10s 探一次后端 /health：
// - 仅在状态变化时推 IPC 给 renderer（10s → 6 次/分钟，对 localhost
//   几乎零开销，rAF 渲染 + SSE 才是真正大头）
// - renderer 收到 backend=false 时顶部出 banner + 「重新连接」按钮
// - 「重新连接」调 IPC 主动 kill + restart backend（不重启 app）

let healthMonitorInterval = null
let lastBackendHealth = null   // null = 还没探过

function startHealthMonitor() {
  if (healthMonitorInterval) return
  console.log('[health] monitor started (5s interval)')
  // 立即跑一次（不等 5s），首屏状态更快落到 UI
  runHealthCheck()
  healthMonitorInterval = setInterval(runHealthCheck, 5_000)
}

function stopHealthMonitor() {
  if (!healthMonitorInterval) return
  clearInterval(healthMonitorInterval)
  healthMonitorInterval = null
  console.log('[health] monitor stopped')
}

/**
 * 单次健康检查：探 backend；只有状态变了才推 IPC，避免
 * 每 5s 一次无意义的事件风暴（main → renderer）。
 */
async function runHealthCheck() {
  const backendOk = await checkBackendHealth()
  if (backendOk === lastBackendHealth) return
  lastBackendHealth = backendOk
  console.log(`[health] changed: backend=${backendOk}`)
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('backend-health-changed', { backend: backendOk })
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
 * Python 下载页 URL，按平台分流：
 * - macOS  → 官方自动检测 Apple Silicon / Intel，给 .pkg
 * - Windows → 官方自动检测，给 .exe
 * - Linux  → 源码下载页（Linux 走 apt，不该走到这里）
 */
function pythonDownloadUrl() {
  if (IS_MAC) return 'https://www.python.org/downloads/macos/'
  if (IS_WIN) return 'https://www.python.org/downloads/windows/'
  return 'https://www.python.org/downloads/source/'
}

/**
 * Docker Desktop 下载页 URL。
 * - macOS / Windows → Docker Desktop 自动检测平台
 * - Linux → engine install 指引（apt/yum/dnf 三选一）
 */
function dockerDownloadUrl() {
  if (IS_MAC) return 'https://www.docker.com/products/docker-desktop/'
  if (IS_WIN) return 'https://www.docker.com/products/docker-desktop/'
  return 'https://docs.docker.com/engine/install/'
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

  // Windows 上 Electron 的 asar FUSE 虚拟化在不同版本下行为不一致：
  // 渲染层拿到的 file:// URL 有时含 `app.asar` 段、有时被 FUSE 剥离，导致
  // resolvedPath 形如 `C:\...\resources\dist\index.html` 而 distDir 是
  // `C:\...\resources\app.asar\dist`，startsWith 检查失败 → 整个页面返回 403 Forbidden。
  // 比较时把两边都把 `app.asar` 段剥掉，等价于「在 distDir 范围内」，但 fs.readFile
  // 仍用原路径（Electron 的 fs patch 对含 app.asar 的路径透明读盘）。
  //
  // Windows 文件系统大小写不敏感但 JS 字符串 startsWith 大小写敏感——NSIS 安装
  // 路径大小写 / Windows 8.3 短路径 / 用户名大小写差异都可能让 startsWith 误判，
  // Win 上额外走 toLowerCase；Mac/Linux 保持原样（HFS+/APFS/ext4 是大小写敏感）。
  const stripAsarForCompare = (p) => p.replace(/[\\/]app\.asar(\.unpacked)?[\\/]/g, path.sep)
  const normalizeForCompare = (p) =>
    IS_WIN ? stripAsarForCompare(p).toLowerCase() : stripAsarForCompare(p)
  const distDirCompare = normalizeForCompare(distDir)

  // ⚠️ 临时诊断：把白名单基准和实际场景打印出来，定位为什么 startsWith 失败。
  // 修完 Forbidden 问题后可以删除这段。
  console.log('[file:debug] distDir =', distDir)
  console.log('[file:debug] distDirCompare =', distDirCompare)

  /**
   * 候选读盘路径：穷举 3 种形态，按顺序 fs.readFile 试，第一个成功的用。
   *
   * 为什么穷举而不是启发式：Win 上 Electron asar FUSE 行为不稳定（不同版本 / 不同路径编码
   * 形态都不一样），用一个 startsWith 启发式猜不准。三个候选覆盖了所有已知情况：
   *   - 原路径：URL 自带 app.asar 段（最常见，mac / 部分 win）
   *   - 插入 app.asar：URL 被 FUSE 剥掉（win-unpacked / 部分 NSIS 安装）
   *   - 剥掉 app.asar：用户传了带 app.asar 路径但 fs patch 当时不识别（罕见）
   *
   * 替换之前的 ensureAsarPath（那段靠 FIRST \resources\ 后是不是 app.asar 启发式判断，
   * 在 unpacked / 长路径 / 短名场景下不稳定）。
   */
  const tryReadCandidates = async (origPath) => {
    const candidates = [origPath]
    const resourcesSeg = path.sep + 'resources' + path.sep

    if (origPath.includes(resourcesSeg)) {
      const idx = origPath.indexOf(resourcesSeg)
      const after = origPath.substring(idx + resourcesSeg.length)

      // 候选 2：插入 app.asar 段（URL 被 FUSE 剥掉）
      if (!after.startsWith('app.asar')) {
        candidates.push(
          origPath.substring(0, idx + resourcesSeg.length) +
          'app.asar' + path.sep +
          after
        )
      }
      // 候选 3：剥掉 app.asar 段（URL 自带但 fs patch 不识别）
      if (after.startsWith('app.asar' + path.sep) || after.startsWith('app.asar.unpacked' + path.sep)) {
        const stripped = origPath.substring(0, idx + resourcesSeg.length) +
                         after.replace(/^app\.asar(\.unpacked)?[\\/]/, '')
        candidates.push(stripped)
      }
    }

    console.log(`[file] try ${candidates.length} candidate(s) for: ${origPath}`)
    for (let i = 0; i < candidates.length; i++) {
      try {
        const data = await fs.readFile(candidates[i])
        if (i > 0) {
          console.log(`[file] ✓ candidate[${i}] hit:`, candidates[i])
        }
        return { ok: true, data, usedPath: candidates[i] }
      } catch (err) {
        console.log(`[file] ✗ candidate[${i}]: ${err.code || err.message} ${candidates[i]}`)
      }
    }
    return { ok: false }
  }

  /**
   * 第二道白名单（Windows 兜底）：严格 startsWith 失败时，路径里只要包含
   * `resources\dist\` 或 `resources\app.asar(.unpacked)?\dist\` 段也算合法。
   *
   * 兜底以下边缘场景（这些场景下严格的 startsWith 会误判 403，但实际读盘合法）：
   *   - Electron asar FUSE 虚拟化在 Win / 不同 Electron 版本下行为不一致，渲染层
   *     拿到的 URL 有时含 app.asar、有时被剥离
   *   - Win 长路径前缀 `\\?\C:\...`
   *   - Win 8.3 短名（PROGRA~1 之类）
   *   - 大小写差异（已用 toLowerCase 兜底，本 helper 是双保险）
   *   - decodeURIComponent 抛出 URIError 时（URL 含非法 %xx 编码）
   *
   * 安全边界：必须同时满足「含 dist/ 段」+「在 app 包内（resources/ 或 frontend/dist）」
   * ——避免误放过 `C:\Users\foo\evil-project\resources\dist\evil.html` 这类非本 app 的路径。
   */
  const isInAppDistFallback = (p) => {
    const hasDistSegment =
      p.includes(path.sep + 'dist' + path.sep) || p.endsWith(path.sep + 'dist')
    if (!hasDistSegment) return false
    return (
      p.includes(path.sep + 'resources' + path.sep) ||
      p.includes('frontend' + path.sep + 'dist')
    )
  }

  /**
   * Electron 的 asar FUSE 虚拟化在 Windows 上行为不一致——渲染层拿到的 file:// URL
   * 有时被剥离 `app.asar` 段（路径变成 `...resources\dist\...`），而 distDir 仍含 app.asar。
   * 白名单（已 strip app.asar）能通过，但 fs.readFile 直接读不带 app.asar 的路径
   * 不走 asar patch，返回 ENOENT → 404 Not found。
   *
   * 修法：在 tryReadCandidates 里穷举 3 种路径形态（原 / 插入 asar / 剥掉 asar），
   * 第一个能 fs.readFile 成功的就用。这里不再做路径形态判断。
   */
  // (旧 ensureAsarPath 函数已删除，由 tryReadCandidates 取代)

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

      // 兜底：net.fetch reject（ECONNREFUSED / ENOTFOUND / 监听中但未响应）时，
      // Electron protocol.handle 默认行为是返回 403 Forbidden，跟我们想表达的
      // 「后端不可达」语义不符，前端 banner 会显示"加载对话列表失败 HTTP 403"误导用户。
      // 改成显式 502 Bad Gateway + JSON body，让前端能按 status 区分文案。
      let upstream
      try {
        upstream = await net.fetch(backendUrl, init)
      } catch (e) {
        const errMsg = (e?.message || String(e)).slice(0, 200)
        console.error('[proxy] backend fetch failed:', backendUrl, errMsg)
        return new Response(
          JSON.stringify({
            detail: `后端不可达 (${backendUrl}): ${errMsg}`,
            proxy_error: 'backend_unreachable',
          }),
          {
            status: 502,
            statusText: 'Bad Gateway',
            headers: { 'Content-Type': 'application/json; charset=utf-8' },
          }
        )
      }

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
      // decodeURIComponent 在 URL 含非法 %xx 编码时会抛 URIError，加 try/catch
      // 兜底走原始 pathname，避免一个非法 URL 把整个静态资源链路炸了
      let filePath
      try {
        filePath = decodeURIComponent(pathname)
      } catch (decodeErr) {
        console.warn('[file] decodeURIComponent failed, using raw pathname:', decodeErr.message)
        filePath = pathname
      }

      // 🔧 Win 上 file:// URL 的 pathname 是 `/D:/foo/bar`（带前导 `/`），
      // 但 Node.js path.resolve('/D:/foo') 在 Win 上返回 `\D:\foo`（盘符相对路径，
      // 前导反斜杠）而不是 `D:\foo`，fs.readFile 找不到 → 404 NotFound。
      // 测试：mac 上跑 path.win32.resolve('/D:/foo') → '\D:\foo'（错的）。
      // 解法：URL pathname 头部的 `/盘符:/` 剥成 `盘符:/`，resolve 才返回正确盘符绝对路径。
      // Mac / Linux 上 `/foo` 是真 Unix 绝对路径，不能剥。
      if (IS_WIN && /^\/[A-Za-z]:\//.test(filePath)) {
        filePath = filePath.substring(1)  // `/D:/foo` → `D:/foo`
      }
      const resolvedPath = path.resolve(filePath)
      const resolvedCompare = normalizeForCompare(resolvedPath)

      // 第一道白名单：必须在 distDir 之下（用 + path.sep 防止 /dist-evil/ 这种前缀撞库）。
      // 比较用 stripped 版本（见上方 helper 注释），读盘用原 resolvedPath。
      // 标准路径（dev + 打包后正常 asar 路径）都走这条。
      const strictPass =
        resolvedCompare.startsWith(distDirCompare + path.sep) ||
        resolvedCompare === distDirCompare

      // 第二道白名单：严格比较失败时，路径只要包含
      // `resources\dist\` 或 `resources\app.asar(.unpacked)?\dist\` 段也放行。
      // 兜底 Win 上 asar FUSE / 长路径（\\?\）/ 短名 / 大小写等 startsWith 失效的边缘场景。
      const fallbackPass = !strictPass && isInAppDistFallback(resolvedCompare)

      if (!strictPass && !fallbackPass) {
        console.warn('[file] blocked non-dist read:', JSON.stringify({
          rawUrl: request.url,
          pathname,
          filePath,
          resolvedPath,
          resolvedCompare,
          distDir,
          distDirCompare,
          startsWithCheck: resolvedCompare.startsWith(distDirCompare + path.sep),
          equalsCheck: resolvedCompare === distDirCompare,
          fallbackCheck: fallbackPass,
        }, null, 2))
        return new Response('Forbidden', { status: 403 })
      }

      if (fallbackPass) {
        // 兜底命中时打日志，未来想回收成 strictPass 时知道哪些路径走 fallback
        console.warn('[file] used fallback dist match:', resolvedPath)
      }

      // Win 上 Electron asar FUSE 行为不稳定（不同版本 URL 里 app.asar 段可能被剥掉），
      // 启发式猜不准 → 穷举 3 种候选（原 / 插入 / 剥掉），第一个能读的就用。
      const result = await tryReadCandidates(resolvedPath)
      if (!result.ok) {
        console.error('[file] all candidates failed:', resolvedPath)
        return new Response(`Not found: ${pathname}`, { status: 404 })
      }
      const data = result.data
      const readPath = result.usedPath
      const ext = path.extname(readPath).toLowerCase()
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
  // 生产模式去掉整个菜单栏（窗口顶部不再显示「灵析 / 编辑 / 视图」），
  // dev / test 保留菜单（开发者需要 reload / 开发者工具等入口）。
  if (isDev || isTest) {
    createMenu(envConfig)
  } else {
    Menu.setApplicationMenu(null)
  }

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
    const req = http.get(`http://127.0.0.1:${currentBackendPort}/health`, res => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(1500, () => { req.destroy(); resolve(false) })
  })
}

// ==================== 子进程生命周期管理 ====================
//
// 设计：execStream（fixUv/fixRedis/fixSandbox/fixVenv）启动的子进程
// 走 shell exec 路径，**调用方不持有 child 引用**，没法在 will-quit 里 kill。
// 用户中途关引导窗 / app 异常退出时，docker build / uv sync 这种几分钟的
// 任务会变孤儿继续跑、占 CPU 内存 IO，下次启动 app 也清理不掉。
//
// 解决：execStream 内部把 child 加进全局 Set，所有退出路径兜底 kill。
// 注意：这里跟踪的是「shell exec 类的子进程」，backend 用 spawn
// 走 backendProcRef 那条线，不混在 Set 里。

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
 * 用于 startBackend 这种必须用 spawn 的场景——它内部 spawn 出的 Python
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
  // 三步探测：(1) docker 命令存在 → (2) docker daemon 在跑 → (3) 拿版本号展示。
  // 原来一次性 Promise.all 只看 docker info，但 docker info 在 daemon 没起时失败，
  // catch 块返「Docker 未启动或未安装」—— 没区分「daemon 没起」vs「命令找不到」。
  // 改成 3 步串联：先确认 docker 命令在 PATH 里（cmd 能跑 Docker Desktop 装的 docker.exe），
  // 再确认 daemon 在跑（Docker Desktop 启动了 → docker info 能拿到）。
  // 任何一步失败都把具体原因暴露给 BootstrapView，便于排查。

  // 1) docker --version（验命令存在，不验 daemon）
  let version = ''
  try {
    version = (await execInUserShell('docker --version', { timeout: 5_000 })).trim()
  } catch (err) {
    console.error('[probe-docker] docker --version 失败:', err.message)
    return {
      ok: false,
      detail: `Docker 命令不可用（${err.message.trim().slice(0, 200)}）。请确认 Docker Desktop 已安装且 PATH 含其安装目录`,
      hint: 'install',
    }
  }
  console.log('[probe-docker] docker --version:', version)

  // 2) docker info（验 daemon）
  try {
    await execInUserShell('docker info', { timeout: 5_000 })
    return { ok: true, detail: version || 'Docker daemon 运行中' }
  } catch (err) {
    console.error('[probe-docker] docker info 失败:', err.message)
    return {
      ok: false,
      detail: `Docker 已安装但 daemon 未运行（${version}）。请启动 Docker Desktop 后重试`,
      hint: 'start-daemon',
    }
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

// ====== Redis 容器状态字符串归一化 ======
//
// docker inspect / ps 输出的 State 字符串在某些环境下会带引号（Windows cmd 偶发包裹 /
// 多容器名匹配），导致 `inspectOut === 'running'` 严格相等判断 miss → fixRedis 把
// 已运行的容器当成 stopped → 调 `docker start` → 触发 Docker daemon 端口重绑逻辑失败。
//
// 归一化：trim 空白 → 去首尾成对引号 → 小写，让 `running` / `"running"` / `'RUNNING'` 都映射成 `running`。
function normalizeDockerStatus(s) {
  return (s || '').toString().trim().replace(/^["']+|["']+$/g, '').toLowerCase()
}

/**
 * 快速 ping Redis（docker exec redis-cli ping）。
 * 返回 true = 容器在跑且 Redis 健康 → 不用做任何恢复动作。
 *
 * 3s timeout 短到不会拖慢 probe 路径；失败返回 false。
 * 跨平台：Windows 用 2>nul，Unix 用 2>/dev/null。
 */
async function tryRedisPing(root) {
  try {
    const out = await execInUserShell(
      `docker exec chatme-redis redis-cli -a 123456 --no-auth-warning ping ${IS_WIN ? '2>nul' : '2>/dev/null'}`,
      { cwd: root, timeout: 3000 }
    )
    // 容错：归一化后比较（Windows cmd 偶尔把 PONG 包成 "PONG"）
    return normalizeDockerStatus(out).toUpperCase() === 'PONG'
  } catch {
    return false
  }
}

/**
 * 探测 LibreOffice 是否已装。
 * 用途：SetupView「旧版文件解析」step 显示已装 / 未装状态 + 引导下载。
 * 检测：跨平台统一跑 `soffice --version`（soffice 是 LibreOffice 标准可执行文件名；
 *   macOS/Windows 安装器默认装的就是这个，Linux 包名 `libreoffice` 但二进制也是 soffice）。
 *
 * 返回 { installed: bool, version?: string, path?: string }：
 *   - installed=true 时附 version 字符串给 SetupView 显示（"LibreOffice 24.2.7.2"）
 *   - path 是 soffice 完整路径，让用户在 detail 里知道装在哪（macOS /Applications/...）
 */
async function probeLibreOffice() {
  // 1) 命令是否存在（避免 --version 找不到时输出空字符串误判已装）
  const whichCmd = IS_WIN ? 'where soffice' : 'which soffice'
  let execPath = ''
  try {
    const out = await execInUserShell(whichCmd, { timeout: 3_000 })
    // 提取首个有效行（mac/linux which 只返一条；win where 可能多条，去首个；
    //   顺手过滤 zsh "Restored session" 噪音）
    const firstLine = out.split(/\r?\n/).map(l => l.trim()).find(l => l && !/Restored session/i.test(l))
    if (!firstLine) return { installed: false }
    execPath = firstLine
  } catch {
    return { installed: false }
  }

  // 2) 拿版本号
  try {
    const out = await execInUserShell(`"${execPath}" --version`, { timeout: 5_000 })
    // soffice --version 输出形如 "LibreOffice 24.2.7.2" 或含路径噪音
    const m = out.match(/LibreOffice\s+([\d.]+)/i)
    const version = m ? m[1] : (out.trim().split(/\s+/).slice(-1)[0] || '')
    return { installed: true, version, path: execPath }
  } catch {
    // 命令存在但 --version 失败（极少数损坏安装） → 仍算「装了但可能有问题」
    return { installed: true, version: '', path: execPath }
  }
}

async function probeRedisContainer() {
  try {
    // 用 `docker ps -a` 同时看运行 + exited 容器——区分 3 种状态给 fixRedis 用
    const out = await execInUserShell(
      `docker ps -a --filter name=chatme-redis --format "{{.Names}}\t{{.State}}"`
    )
    if (!out) return { ok: false, detail: '容器不存在' }
    const [, state] = out.split('\t')
    const normalized = normalizeDockerStatus(state)
    // 只 running 才算 ok；其他状态（exited/created/paused/restarting）交给 fixRedis 拉起来
    if (normalized === 'running') return { ok: true, detail: '运行中' }
    return { ok: false, detail: `容器存在但未运行（${normalized || state}）` }
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
    // 持久化到用户环境：只改 process.env.PATH 不够——后续 spawn 的 cmd.exe
    // 子进程不继承父进程瞬时改动（且 cmd.exe 启动也不重读 PATH），所以 setx
    // 把 cargoBin 追加到用户 PATH，bootstrap 后续步骤（probeUv / uv sync）才能找到 uv。
    // 用 `setx PATH "%PATH%;..."` 而不是 setx 单变量是为了复用当前 session 的 PATH。
    // 失败不抛——改 process.env.PATH 已经是兜底，本进程内再 exec 能找到。
    await execStream(
      `setx PATH "%PATH%;${cargoBin}"`,
      { onLog, shell: true }
    ).catch(err => {
      onLog?.(`[uv] ⚠️ setx PATH 失败（当前进程仍可用）：${err.message}\n`)
    })
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

  // 1. ping 先：Redis 已经响应 → 完全跳过（用户核心诉求：已经在跑就别折腾）
  //    ping 是 Redis 可用的**唯一权威信号**——状态字符串是 Docker daemon 的二手数据，
  //    会受 daemon 状态混乱 / Windows 输出编码 / cmd 包裹等因素干扰。
  if (await tryRedisPing(root)) {
    onLog?.('[redis] ✅ Redis 已在运行（响应 PONG），跳过\n')
    return
  }

  // 2. ping 失败 → 看 docker 状态决定下一步
  const inspectOut = await execInUserShell(
    `docker inspect chatme-redis --format "{{.State.Status}}" ${IS_WIN ? '2>nul' : '2>/dev/null'}`
  ).catch(() => '')
  let status = normalizeDockerStatus(inspectOut)

  // 3. 容器卡在 "created" 状态自愈
  //    典型原因：上次 compose up 拉到一半因端口冲突失败（host 端口被外部进程占用），
  //    Docker daemon 已经建好容器元数据但 start 阶段 fail → 容器卡在 Created 既不
  //    跑也不死。`docker start` 在 Created 状态下也会再失败（端口冲突依旧）。
  //    直接 `docker rm -f` 清掉 + 走 compose up 重新创建，让 Docker daemon 重新分配。
  if (status === 'created') {
    onLog?.('[redis] 容器卡在 created 状态（可能上次端口冲突残留），清理重建...\n')
    try {
      await execStream('docker rm -f chatme-redis', { cwd: root, onLog })
    } catch { /* 容器可能已被外部删掉 */ }
    status = ''  // fall through to compose up
  }

  // 4. host 端口预杀（仅当容器没在用这些端口时）
  //    docker-compose.yml 把 6024 (Redis) / 28001 (RedisInsight UI) 暴露到 host，
  //    如果有外部进程监听 → compose up 的端口绑定会 WSAEACCES (Windows) / EACCES (Unix) 失败。
  //    这两个端口是 Redis 专用，没有合法第三方用途，直接杀。**不动 Docker 自身的 NAT
  //    进程**——只在容器没跑时扫，避开 `com.docker.backend.exe` 这种 Docker 自己绑的 PID。
  if (status !== 'running' && status !== 'restarting') {
    const externalListeners = await findExternalPortListeners([6024, 28001], root)
    if (externalListeners.size > 0) {
      const desc = [...externalListeners].map(([port, pid]) => `${port}(pid=${pid})`).join(', ')
      onLog?.(`[redis] ⚠️ host 端口被外部进程占用：${desc}，强制清理...\n`)
      for (const [, pid] of externalListeners) {
        try { killPid(pid) } catch { /* 单个 PID 杀失败不阻塞 */ }
      }
      // 给 OS 释放端口时间
      await new Promise(r => setTimeout(r, 500))
    }
  }

  // 5a. 容器在跑（按 Docker 视角），但 ping 失败 → 大概率 daemon 状态混乱
  //     **不要**调 docker start（会触发端口重绑 / 加剧混乱）→ 靠 waitForRedisReady 继续探
  if (status === 'running' || status === 'restarting') {
    onLog?.(`[redis] 容器状态 ${status}（ping 失败），等待就绪...\n`)
    await waitForRedisReady(root, onLog)
    return
  }

  // 5b. 存在但 stopped/paused/dead → start 拉起来（保留数据卷，避免 compose up 报 name conflict）
  //     docker start 即便失败也不立刻 throw——容器可能实际在跑，只是 docker CLI 报端口冲突；
  //     让 waitForRedisReady 探一下，能连上就当修复成功。
  if (status) {
    onLog?.(`[redis] 容器存在但状态 ${status}，尝试 start...\n`)
    try {
      await execStream('docker start chatme-redis', { cwd: root, onLog })
    } catch (e) {
      onLog?.(`[redis] ⚠️ docker start 失败：${(e?.message || '').slice(0, 200)}\n`)
      onLog?.('[redis] 改用 ping 检测（容器可能已在跑）...\n')
    }
    await waitForRedisReady(root, onLog)
    return
  }

  // 5c. 不存在（或刚被清理）→ compose 创建
  //     不主动 `docker rm`：避免误删用户手动配置的容器或旧版残留（数据可能还在数据卷里）。
  //     第 3 步只清理 Created 状态这种已知「卡死」状态，其他状态保留。
  await execStream(
    `docker compose -f "${composeFile}" up -d redis`,
    { cwd: root, onLog }
  )
  await waitForRedisReady(root, onLog)
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
        `docker exec chatme-redis redis-cli -a 123456 --no-auth-warning ping ${IS_WIN ? '2>nul' : '2>/dev/null'}`
      )
      // 归一化比较：容错 Windows cmd 偶尔把 PONG 包成 "PONG"
      if (normalizeDockerStatus(out).toUpperCase() === 'PONG') {
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

/**
 * will-quit 兜底清理 Lingxi 管理的 Docker 容器。
 *
 * 为什么需要这个:Windows 走 taskkill /F 强杀 backend,lifespan cleanup 跑不到 →
 * chatme-redis + chatme-python-sandbox-* 全部残留。Mac 走 SIGTERM 软退时
 * backend 自己 `_shutdown_resources()` 已经清了,但跑这条仍幂等 no-op,作为兜底。
 *
 * 分两步:
 *   1. docker stop chatme-redis (单命令,跨平台一致)
 *   2. docker ps -q --filter name=chatme-python-sandbox → docker stop <ids>
 *      拆成两步避免 cmd `for /f` in `cmd /c` 上下文里的解析边角情况,
 *      也避免空 stdin 时 docker stop 报 "requires at least 1 argument"。
 *
 * 永远不抛——best-effort 兜底,失败只 warn。已停止的容器 docker stop 返回
 * 非零 exit 码也吞掉(容器不存在比残留无害)。
 */
async function stopLingxiContainers() {
  const nul = IS_WIN ? '2>nul' : '2>/dev/null'
  const quietShell = (cmd, timeoutMs) =>
    execInUserShell(cmd, { timeout: timeoutMs }).catch(() => '')

  try {
    // 1. Redis。--time 5 比默认 10s 短,空闲容器秒停。
    await quietShell(`docker stop --time 5 chatme-redis ${nul}`, 8_000)

    // 2. sandbox 容器。先列再停,空列表直接跳过 docker stop 调用。
    const listOut = await quietShell(
      `docker ps -q --filter "name=chatme-python-sandbox"`,
      5_000
    )
    const ids = listOut.trim().split(/\r?\n/).filter(Boolean)
    if (ids.length > 0) {
      // 单行 docker stop <id1> <id2> ... 比逐个 stop 快(并行 SIGTERM + SIGKILL)。
      // 多个 id 加在一起 5s + 余量,3 个容器最多 ~7s。
      const totalTimeout = Math.min(8_000 + ids.length * 2_000, 20_000)
      await quietShell(`docker stop --time 5 ${ids.join(' ')} ${nul}`, totalTimeout)
    }

    console.log(`[cleanup] Lingxi 容器已停止 (chatme-redis + ${ids.length} sandbox 容器)`)
  } catch (e) {
    console.warn(`[cleanup] stopLingxiContainers 兜底失败(容器可能已停):`, (e?.message || '').slice(0, 200))
  }
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

// ---------- 启动后端 ----------
//
// MCP server 在 stdio 模式下作为 chatme_main 的子进程由其内部 fork，
// Electron 不再单独起 MCP。

/**
 * 检查指定 host 端口是否被外部进程监听（不含 Docker 自身的 NAT 进程）。
 * 返回 Map<port, pid> —— 只有当确实有外部进程占着时才非空。
 *
 * ⚠️ Docker Desktop on Windows 通过 `com.docker.backend.exe` 用 NAT 绑 host 端口
 * 转发到容器。如果 chatme-redis 容器在跑，netstat/lsof 会显示 Docker 进程的 PID——
 * 调用方必须先用 docker inspect 确认容器是否在用这些端口，不要把 Docker 进程杀掉。
 * fixRedis 调用本函数前已经知道 chatme-redis 状态，所以只看「容器没在跑时」是否还有外部占用。
 *
 * 跨平台：
 *   - Win: netstat -ano | findstr :PORT → 提取 LISTENING 行的 PID
 *   - Unix: lsof -ti:PORT -sTCP:LISTEN → 提取 PID
 */
async function findExternalPortListeners(ports, root) {
  const result = new Map()  // port → pid
  try {
    if (IS_WIN) {
      for (const port of ports) {
        const out = await execInUserShell(
          `netstat -ano | findstr :${port}`,
          { cwd: root, timeout: 5000 }
        )
        out.split('\n').forEach(line => {
          if (!line.toUpperCase().includes('LISTENING')) return
          const m = line.match(/LISTENING\s+(\d+)/i)
          if (m && !result.has(port)) result.set(port, m[1])
        })
      }
    } else {
      for (const port of ports) {
        const out = await execInUserShell(
          `lsof -ti:${port} -sTCP:LISTEN 2>/dev/null || true`,
          { cwd: root, timeout: 5000 }
        )
        const pids = out.trim().split('\n').filter(Boolean)
        if (pids.length > 0 && !result.has(port)) result.set(port, pids[0])
      }
    }
  } catch { /* ignore */ }
  return result
}

/**
 * 杀单个 PID（跨平台）。失败不抛——只是 best-effort。
 */
function killPid(pid) {
  if (IS_WIN) {
    spawnSync('taskkill', ['/F', '/PID', String(pid)], { windowsHide: true })
  } else {
    spawnSync('kill', ['-9', String(pid)])
  }
}

/**
 * 后端 fallback 端口列表。
 *
 * - 第 1 项（38211）是 canonical 端口；config.json / vite.config.js / electron.config.js
 *   全部默认指向它。所有「正常启动」路径走这个端口。
 * - 后续候选是 Windows Hyper-V 端口预留冲突的兜底：
 *   Windows 把 8000-9000 段划给 Hyper-V / ICS / WSL 等系统服务（excludedportrange），
 *   用户偶发遇到 WSAEACCES (10013) bind 失败；连续 9 个候选覆盖大多数冲突场景。
 * - 选定端口后会同步：① 写 config.json.app.port ② 更新 config.backend.apiUrl 端口段
 *   ③ 通知 renderer 重新解析（避免 vite proxy / Electron 转发错位）。
 *
 * 注意：fallback 端口只用于「canonical 端口被外部占用」的兜底；本应用残留进程会被
 * killPortIfListening 杀掉后复用 38211，不进 fallback。
 */
const BACKEND_PORT_FALLBACK = [38211, 38212, 38213, 38214, 38215, 38216, 38217, 38218, 38219]

/**
 * 实际启动后端用的端口（模块级可变，startBackend 选定后写一次，protocol.handle 用此值）。
 * 默认 38211；startBackend 失败 fallback 后更新。
 */
let currentBackendPort = 38211

/**
 * 探测端口是否「空闲」（没人 LISTEN）。
 * 用 net.createServer().listen(port) 试 bind：成功 → 空闲；EADDRINUSE → 被占用。
 * bound 后立刻 close 释放——避免对 OS 端口状态造成中间抖动。
 */
function isPortFree(port) {
  return new Promise(resolve => {
    const tester = nodeNet.createServer()
      .once('error', err => {
        // EADDRINUSE = 占用；其他错误（权限 / 协议）按占用处理，保守优先
        resolve(false)
        tester.close?.()
      })
      .once('listening', () => {
        tester.close(() => resolve(true))
      })
      .listen(port, '127.0.0.1')
  })
}

/**
 * 在 BACKEND_PORT_FALLBACK 中找第一个空闲端口。返回端口号；都失败抛错。
 * 被占用且能 kill 的本应用残留进程会被杀 + 等 500ms 让 OS 回收，然后复用同一个端口
 * （不进 fallback 链，保持 canonical 端口语义）。
 */
async function pickBackendPort() {
  for (const port of BACKEND_PORT_FALLBACK) {
    if (await isPortFree(port)) {
      console.log(`[backend] 端口 ${port} 空闲`)
      return port
    }
    const killed = await killPortIfListening(port)
    if (killed) {
      // 给 OS 释放端口时间（lsof/kill 异步；Windows taskkill 也可能有残留）
      await new Promise(r => setTimeout(r, 800))
      if (await isPortFree(port)) {
        console.log(`[backend] 端口 ${port} 清理了残留进程，复用`)
        return port
      }
    }
    console.log(`[backend] 端口 ${port} 被外部占用，尝试下一个候选`)
  }
  throw new Error(
    `BACKEND_PORT_FALLBACK ${BACKEND_PORT_FALLBACK.join(',')} 全部被占用，` +
    `请检查系统服务（Hyper-V / ICS / WSL 经常占 8000-9000 段）`
  )
}

/**
 * 检测指定端口是否有进程在监听；若有则杀。返回 true 表示杀了 ≥1 个进程。
 *
 * 跨平台：
 *   - Win: netstat -ano | findstr :PORT → 提取 LISTENING 行的 PID → taskkill /F /PID
 *   - Unix: lsof -ti:PORT -sTCP:LISTEN → kill -9
 *
 * 用于 startBackend 之前清理 BACKEND_PORT_FALLBACK 任一端口上残留的旧 backend 进程（异常退出 / 孤儿进程等场景）：
 *   旧进程占着端口 → 新 spawn 静默 EADDRINUSE → /health 探测会错连旧实例返回 200 →
 *   用户看到"成功"但实际是旧版 backend（checkpoint / 配置全错位）。
 * 只针对本应用专用端口做，不会误杀同名其他服务。
 */
async function killPortIfListening(port) {
  try {
    if (IS_WIN) {
      const out = await execInUserShell(
        `netstat -ano | findstr :${port}`,
        { timeout: 5000 }
      )
      const pids = new Set()
      out.split('\n').forEach(line => {
        // 格式示例：TCP    0.0.0.0:38211    0.0.0.0:0    LISTENING    1234
        const m = line.match(/LISTENING\s+(\d+)/i) || line.match(/\s(\d+)\s*$/)
        if (m) pids.add(m[1])
      })
      for (const pid of pids) {
        try {
          spawnSync('taskkill', ['/F', '/PID', pid], { windowsHide: true })
        } catch { /* 单个 PID 杀失败不阻塞其他 */ }
      }
      return pids.size > 0
    } else {
      const out = await execInUserShell(
        `lsof -ti:${port} -sTCP:LISTEN 2>/dev/null || true`,
        { timeout: 5000 }
      )
      const pids = out.trim().split('\n').filter(Boolean)
      if (pids.length === 0) return false
      try {
        spawnSync('kill', ['-9', ...pids])
      } catch { /* kill 失败仍走 OS 端口回收时间 */ }
      // 给 OS 释放端口时间
      await new Promise(r => setTimeout(r, 500))
      return true
    }
  } catch {
    return false
  }
}

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
const backendProcRef = { value: null }  // 替 backendProcess 存引用，封装 kill

async function startBackend(onLog) {
  const root = requireProjectRoot()
  const [pythonExe] = resolvePythonForBackend(root)
  const backendDir = path.join(root, 'backend')
  // 保证后端及其间接启动的命令继承用户 shell 的完整 PATH。
  await getShellAugmentedPath()

  // 选端口：canonical 38211 被外部占 → 走 BACKEND_PORT_FALLBACK 顺序；
  // 本应用残留会被 killPortIfListening 杀掉后复用 canonical 端口，不进 fallback。
  const port = await pickBackendPort()
  currentBackendPort = port
  // 同步到 config.backend.apiUrl，protocol.handle /chat /static /admin 转发用此值
  config.backend.apiUrl = `http://127.0.0.1:${port}`

  // 把实际端口写进 config.json.app.port，后端启动时会读这个值（避免硬编码端口错位）
  const configPath = path.join(root, 'backend', '.chatme', 'config.json')
  try {
    const cfg = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
    cfg.app = cfg.app || {}
    cfg.app.port = port
    fs.writeFileSync(configPath, JSON.stringify(cfg, null, 4))
    console.log(`[backend] config.json.app.port 同步为 ${port}`)
  } catch (e) {
    console.warn('[backend] 同步 config.json 端口失败（继续启动）:', e.message)
  }

  console.log('[backend] starting:', pythonExe, 'main.py', 'on port', port)

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

  // 轮询 /health（最多 120s；docling + QwenVL 首次加载可能慢）
  const deadline = Date.now() + 120_000
  try {
    while (Date.now() < deadline) {
      try {
        await new Promise((resolve, reject) => {
          const req = http.get(`http://127.0.0.1:${port}/health`, res => {
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
 *                  false → App.vue 保持 appReady=false（BootstrapView 仍挂载，展示「进入应用」按钮等用户点）。
 * warm path（app.whenReady 已健康）无需等用户点，固定传 true。
 *
 * ready=false（后端挂掉）不带 autoEnterFrontend 字段；renderer 只看 ready 决定 BootstrapView 渲染。
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
  // 健康检查同步更新 banner（之前 backend false，现在应都 true）
  if (ready) runHealthCheck()
}

// ---------- 注册 startup IPC ----------
/**
 * 主动重启 backend（用户在 banner 上点「重新连接」时调用）。
 * - 先 SIGKILL 旧子进程（含 taskkill /T /F 杀整个进程树）
 * - 再走 startBackend 重启；MCP 子进程跟着 chatme_main 一起重新 fork
 * - 完成后推 servicesReady(true) 给 renderer；autoEnterFrontend=true 是因为用户
 *   已经在 app 里（被踢回 disabled），重启恢复后直接交回交互权，不必再弹「进入应用」按钮。
 *   注意 setServicesReady 内部会去重 + 只在状态翻转时推，重复 restart 不会刷屏。
 * - 失败抛错，由 IPC 兜底返回 { ok: false, error } 让前端给用户反馈
 */
async function restartBackend() {
  killChild(backendProcRef, 'backend')
  // 给 OS 回收旧 socket / 释放端口的时间（FastAPI 软关闭可能 1-2s 没收完）
  await new Promise(r => setTimeout(r, 500))
  await startBackend()
  // 推 servicesReady 状态（让 renderer 翻 appReady=true + initConversation）+
  // 即时健康检查（让 banner 立即消失）。两者独立：前者解除 disabled，后者驱动 banner。
  setServicesReady(true, { autoEnterFrontend: true })
  runHealthCheck()
}

function registerStartupIpc() {
  /**
   * BootstrapView 显示用的 3 项检查：项目根 / python / docker。
   * uv/redis/sandbox/venv 都是「docker 在 + python 在」之后自动配的，
   * 暴露给用户只会增加操作成本（要按 4 次"配置"按钮）。
   */
  ipcMain.handle('startup:probe-all', async () => {
    return {
      projectRoot: await probeProjectRoot(),
      python: { ...await probePython(), downloadUrl: pythonDownloadUrl() },
      docker: { ...await probeDocker(), downloadUrl: dockerDownloadUrl() },
    }
  })

  /**
   * SetupView「旧版文件解析」step 用：探测本地 LibreOffice。
   * 返回 { installed, version?, path? } —— 装了就返版本 + 路径，未装只返 installed: false。
   * 失败一律走 false（不抛），前端根据 ok 字段渲染已装 / 下载按钮。
   */
  ipcMain.handle('setup:probe-libreoffice', async () => {
    return await probeLibreOffice()
  })

  /**
   * 手动启动 Docker Desktop（probe-all 检测到 daemon 没跑时的兜底动作）。
   * 调用后不验证 daemon 是否就绪——启动是异步的，UI 端拿 ok=true 后用
   * probe-all 轮询直到 docker.ok=true 或超时（BootstrapView 控制 30s 上限）。
   * daemon 已起的情况下再调也无害（open -a / spawn 已运行进程 / systemctl 幂等）。
   */
  ipcMain.handle('startup:start-docker', async () => {
    return await startDockerDesktop()
  })

  // 当前项目根（引导页头部展示用）
  ipcMain.handle('startup:get-project-root', async () => PROJECT_ROOT)

  /**
   * 返回默认 clone 父目录（os.homedir()）。
   * BootstrapView 克隆确认卡片用这个显示给用户看 —— 用户看到的是「父目录」，
   * 不是最终 lingxi/ 路径（lingxi/ 由 git 按仓库名自动创建，不在用户选择范围内）。
   */
  ipcMain.handle('startup:get-default-clone-target', async () => {
    return { targetDir: os.homedir() }
  })

  /**
   * 仅弹目录选择框返回「父目录」——不直接触发 clone。
   * BootstrapView 的「克隆确认卡片」走这条路径：用户先看到默认目标 + 自定义按钮，
   * 选完目录后再单独 invoke startup:auto-clone 触发实际 clone。
   *
   * 与 startup:pick-project-root 的区别：
   *   - pick-project-root 选的是「项目根」（内含 backend/），并立即持久化
   *   - pick-clone-target 选的是「父目录」（git 会按仓库名建子目录），只返回不写盘
   */
  ipcMain.handle('startup:pick-clone-target', async (e) => {
    const dialogOpts = {
      title: '选择 lingxi 项目的父目录',
      message: 'git clone 会把仓库拉到所选目录下',
      defaultPath: os.homedir(),
      buttonLabel: '选择此处',
      properties: ['openDirectory', 'createDirectory'],
    }
    const win = BrowserWindow.fromWebContents(e.sender) || mainWindow
    const { canceled, filePaths } = win && !win.isDestroyed()
      ? await dialog.showOpenDialog(win, dialogOpts)
      : await dialog.showOpenDialog(dialogOpts)
    if (canceled || !filePaths?.length) return { ok: false, canceled: true }
    return { ok: true, targetDir: filePaths[0] }
  })

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
    setLastCloneTarget(dir)  // 手动选的新路径取代旧 clone 路径（discoverProjectRoot 第 1.5 级命中这个）
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
   * 4) uv sync 装 python 依赖 → 5) 起后端 → setServicesReady(true)
   *
   * MCP server 在 stdio 模式下由 chatme_main 内部 fork，无需单独起。
   *
   * setServicesReady 触发 renderer 翻 appReady=true，BootstrapView 自动消失。
   * 单窗口架构下不再需要「切主窗口」步骤，GPU/renderer 资源完全稳定。
   *
   * 任一步抛错：杀掉所有已起的子进程（不漏 backend 孤儿）+ 错误回给前端
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

      // 5. backend
      await startBackend((m) => onLog('backend', m))
      onLog('backend', '✅ 后端就绪\n')

      onLog('startup', '✅ 后端已就绪\n')
      // 广播 servicesReady=true。autoEnterFrontend=true 让 renderer 立即翻 appReady=true +
      // initConversationState；=false 时 renderer 不翻 appReady，BootstrapView 保留挂载并显示
      // 「进入应用」按钮等用户主动点。
      setServicesReady(true, { autoEnterFrontend })
      return { ok: true }
    } catch (err) {
      // 失败兜底：杀掉所有已起的子进程，避免 backend 泄漏
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
   * - restart-backend：用户在 banner 上点「重新连接」时主动 kill + restart backend
   * 状态变化走 mainWindow.webContents.send('backend-health-changed', ...) push，无需 renderer 轮询
   */
  ipcMain.handle('startup:get-health', async () => {
    const backend = await checkBackendHealth()
    lastBackendHealth = backend
    return { backend }
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

  /**
   * BootstrapView 触发入口：从渲染层主动调 auto-clone（用户点「确认克隆」或「选择其他目录...」）。
   * onLog 通过 IPC 推到 renderer，BootstrapView 已订阅 startup:log 流。
   * 成功后同步更新主进程 PROJECT_ROOT；失败返回 { ok: false, error } 让 UI 展示。
   *
   * ⚠️ 现在只由 BootstrapView 调用，调用时**必须**传 opts.skipDirPicker=true 和 opts.targetDir
   * （BootstrapView 已经走完 picker 步骤）。不再有 silent auto-clone 路径——app 启动时不主动改用户文件。
   * 下面 if (!opts.skipDirPicker) 分支保留是防御兜底（其他 caller 调用时仍能正常弹框）。
   *
   * 流程：
   *   1) caller 必传 targetDir（BootstrapView 路径：用户看到默认 ~/ 或自定义父目录）
   *   2) caller 传 skipDirPicker=true 时不再弹框，直接用 targetDir
   *   3) cloneIntoDir = 用户最终决定的「父目录」——git 会按仓库名建子目录
   *      （如 ~/lingxi/、D:\work\lingxi\——lingxi/ 不由 caller 拼，由 git 从 URL 提取）
   */
  ipcMain.handle('startup:auto-clone', async (e, opts = {}) => {
    const onLog = (msg) => e.sender.send('startup:log', { item: 'clone', msg })

    let cloneIntoDir = opts.targetDir || os.homedir()

    // 防御兜底：非 BootstrapView caller 没传 skipDirPicker 时弹框选父目录
    if (!opts.skipDirPicker) {
      const defaultHome = os.homedir()
      const dialogOpts = {
        title: '选择 lingxi 项目的父目录',
        message: 'git clone 会把仓库拉到所选目录下',
        defaultPath: defaultHome,
        buttonLabel: '在此处 clone',
        properties: ['openDirectory', 'createDirectory'],
      }
      const win = BrowserWindow.fromWebContents(e.sender) || mainWindow
      const { canceled, filePaths } = win && !win.isDestroyed()
        ? await dialog.showOpenDialog(win, dialogOpts)
        : await dialog.showOpenDialog(dialogOpts)
      if (!canceled && filePaths?.length) {
        cloneIntoDir = filePaths[0]  // 用户选的目录（不带 lingxi/，git 会自动建子目录）
        onLog(`[clone] 用户选择目录: ${cloneIntoDir}\n`)
      } else {
        // 取消 → fallback 到默认 ~/（git 会建 ~/lingxi/）
        cloneIntoDir = defaultHome
        onLog(`[clone] 用户取消，使用默认: ~/\n`)
      }
    }

    onLog(`[clone] clone 目标: ${cloneIntoDir}/\n`)

    try {
      // 传「父目录」即可，git clone 会自动按仓库名建子目录。
      // autoCloneProject 内部从 URL 提取仓库名拼出最终 projectRoot 返回。
      const result = await autoCloneProject(app, { ...opts, targetDir: cloneIntoDir, onLog })
      if (result.ok) {
        // 同步更新主进程 PROJECT_ROOT（renderer 不该直接改 main 状态）
        PROJECT_ROOT = result.projectRoot
        // clone 完显式重检测一次：
        // autoCloneProject 已 setLastCloneTarget + saveProjectRoot，
        // 所以 discoverProjectRoot 第 1.5 级（clone temp）会命中；
        // 同时给 IPC 日志一个清晰的「✅ 探测到 lingxi/」信号。
        const recheck = discoverProjectRoot(app)
        if (recheck.root && isValidProjectRoot(recheck.root)) {
          PROJECT_ROOT = recheck.root
          onLog(`[clone] ✅ 重检测确认 lingxi/: ${PROJECT_ROOT}（${recheck.source}）\n`)
        } else {
          // 极端情况：lastCloneTarget + saved 都没命中但 clone 路径合法
          onLog(`[clone] ⚠️ 重检测未命中有效 lingxi 根，使用 clone 返回路径: ${PROJECT_ROOT}\n`)
        }
      }
      return result
    } catch (err) {
      return { ok: false, error: err.message }
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
  //
  // ⚠️ 这里**不**做 silent auto-clone——BootstrapView 的克隆确认卡片才是触发 clone 的唯一入口。
  // silent 路径的代价：① 用户没确认就在 ~/ 下写盘（~50MB git clone），违反「不主动改用户文件」原则；
  // ② 等 BootstrapView mount 时 clone 已完成，卡片不显示，用户不知道发生了什么。
  // 改完后：发现路径失败 → BootstrapView 显示「未找到 lingxi 项目目录」+ 「确认克隆 / 选择其他目录」栈按钮，
  // 用户点哪个才走对应路径。
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
  // 直接进主界面，BootstrapView 不会渲染。autoEnterFrontend 现在由 BootstrapView 消费，
  // 用来自动触发 bootstrap；这里不再分流到 setup 窗口。
  const backendOk = await checkBackendHealth()
  lastBackendHealth = backendOk
  console.log(
    `[setup] 后端状态 backend=${backendOk}, ` +
    `autoEnter=${startupPreferences.autoEnterFrontend}`
  )

  // 单窗口架构：始终一个主窗口，渲染层根据 servicesReady 决定显示 BootstrapView 还是主界面。
  // 注册 IPC 必须在 createWindow 之前——renderer 加载 index.html 后会立即
  // 调 getServicesReady / getHealth / getStartupPreferences；handlers 没注册就抛错。
  registerStartupIpc()
  await createWindow()
  startHealthMonitor()

  // 服务已健康 → 同步置 servicesReady=true，触发 BootstrapView 消失。
  // 这必须在 registerStartupIpc() 之后（renderer 已能收到事件），且在 createWindow 之后（renderer 已挂载）。
  // warm path 总是 autoEnter=true（用户已经在 app 里了，无需等点「进入应用」）。
  if (backendOk) {
    setServicesReady(true, { autoEnterFrontend: true })
  }
})

app.on('window-all-closed', () => {
  // 本应用后端会常驻 VL 模型并占用大量内存；关闭所有窗口即视为退出，
  // macOS 也不保留无窗口的后台主进程，确保 before-quit 清理我们启动的服务。
  app.quit()
})

/**
 * 退出清理:杀我们 spawn 的后端子进程 + tracked shell 子进程
 * ⚠️ 只杀我们自己起的进程;端口已被占(外部进程)的情况**不**杀
 * MCP 子进程是 chatme_main 的子进程,跟着 backend 一起收尸,不需要单独处理。
 *
 * 关键:必须给 backend 发 SIGTERM(软退出)而不是 SIGKILL(强杀),
 * 否则 chatme_main 没机会跑 lifespan cleanup → MCP subprocess / sandbox / redis 全残留。
 * 但 Windows 没有等价于 SIGTERM 的优雅信号(taskkill /F 强杀、taskkill 不带 /F
 * 对 console 进程无效),所以 backend 'exit' 后还要跑 stopLingxiContainers()
 * 兜底清掉 Lingxi 管的 Docker 容器(MCP subprocess 仍残留,用户下次启动会被覆盖)。
 */
app.on('will-quit', (event) => {
  // 0. 停止健康监测定时器，避免跑空检查 + IPC 到已销毁的 webContents
  stopHealthMonitor()

  // 1. tracked shell 子进程(docker build / uv sync / redis up)—— SIGKILL 强杀
  killTrackedChildren('will-quit')

  // 2. 不管 backend 是不是还活着,都先 preventDefault,等 docker 兜底完才真退。
  //    - backend 还活着:走 SIGTERM/taskkill 等它死 → docker 兜底 → app.exit
  //    - backend 已死(早崩了 / 用户 bootstrap 中途取消):跳过 kill 直接 docker 兜底
  //    两条路径都覆盖 Lingxi 管的 Docker 容器清理,Windows 强杀路径必跑。
  event.preventDefault()

  /**
   * will-quit 收尾:docker 兜底停 Lingxi 容器,然后 app.exit。
   * 抽出来给两条路径共用(backend 还活着 / backend 已死)。
   * 内部 try/catch 永不让 app.exit 跑不到。
   */
  const finishQuit = async () => {
    try {
      await stopLingxiContainers()
    } catch (e) {
      // stopLingxiContainers 自己 try/catch,理论上 catch 不到;保险。
      console.warn('[cleanup] finishQuit docker stop 异常:', (e?.message || '').slice(0, 200))
    }
    app.exit(0)
  }

  // 3. spawn 出来的 backend —— SIGTERM 软退出,等真正退出再 finishQuit
  const proc = backendProcRef.value
  if (proc) {
    try {
      if (IS_WIN) {
        exec(`taskkill /pid ${proc.pid} /T /F`, () => {})
      } else {
        proc.kill('SIGTERM')
      }
      console.log(`[cleanup] sent SIGTERM to backend (pid=${proc.pid})`)
      // 等 backend 退出(最长 8s),超时强杀。
      // 8s = uvicorn timeout_graceful_shutdown(3s) + lifespan teardown(~1s) + 4s 缓冲,
      // 确保活跃 SSE 流被强制关闭 + MCP stdio subprocess / APScheduler job / sandbox 容器全部清理完。
      // 原来 5s 不够 —— uvicorn 等不到 3s SSE 超时就被 SIGKILL,cleanup 链全跳过 → 子进程残留。
      const exitTimeout = setTimeout(() => {
        try { proc.kill('SIGKILL') } catch {}
      }, 8000)
      proc.once('exit', () => {
        clearTimeout(exitTimeout)
        console.log('[cleanup] backend exited')
        backendProcRef.value = null
        finishQuit()
      })
    } catch (e) {
      console.error(`[cleanup] failed to kill backend:`, e.message)
      finishQuit()
    }
    return  // 已 preventDefault,后续不跑到
  }

  // 4. backend 不在跑(早崩了 / 用户 bootstrap 中途取消)—— 直接 docker 兜底退出
  finishQuit()
})

/**
 * before-quit:用户触发退出(Cmd+Q / app.quit)时第一时间杀 tracked shell 子进程,
 * 不等 will-quit,避免在 will-quit 之前子进程已经把父进程当 orphan 处理掉。
 *
 * 注意:这里**不**杀 backend —— 留给 will-quit 的 SIGTERM 软退出路径,
 * 让 chatme_main 有机会跑 lifespan cleanup(MCP subprocess / sandbox / redis)。
 */
app.on('before-quit', () => {
  killTrackedChildren('before-quit')
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
 *     BootstrapView 会瞬间出现再被 servicesReady=true 隐藏，体感上是真正的「整页硬刷」
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