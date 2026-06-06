import { app, BrowserWindow, Menu, shell, ipcMain } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const configModule = await import('./electron.config.js')
const config = configModule.default

let mainWindow
let previewWindow = null

// 判断是否为开发环境
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged

// 判断是否为测试环境
const isTest = process.env.NODE_ENV === 'test'

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
      preload: path.join(__dirname, config.paths.preload)
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

// ==================== 应用生命周期 ====================
app.whenReady().then(async () => {
  await createWindow()
  setupSecurityPolicies()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
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