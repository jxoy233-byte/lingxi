import path from 'path'
import { fileURLToPath } from 'url'
import { app } from 'electron'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// ⚠️ 不能 import '../vite.config.js'：
// vite.config.js 自身 import 'vite'，而 asar 不打包 node_modules（5.6MB 控制要求），
// 启动时会报 ERR_MODULE_NOT_FOUND 'vite' 直接崩。
// 这里只复制 vite.config.js 里 viteServerConfig 的两个值——port 和 proxy target。
// 同步规则：改 vite.config.js 的 port / proxy target 时也要同步改这里。
const VITE_DEV_PORT = 18211
const VITE_PROXY_BACKEND = 'http://127.0.0.1:8211'

export default {
  // 应用基本信息
  app: {
    name: '灵析',
    title: '灵析——数据分析智能助手',
    identifier: 'com.chatme.app',
    version: '0.1.8'
  },

  // 窗口配置
  window: {
    width: 1100,
    height: 720,
    minWidth: 650,
    minHeight: 480,
    backgroundColor: '#ffffff',
    titleBarStyle: 'default'
  },

  // dev server 配置（和 vite.config.js viteServerConfig 对齐）
  devServer: {
    url: `http://localhost:${VITE_DEV_PORT}`,
    port: VITE_DEV_PORT,
    strictPort: true
  },

  backend: {
    apiUrl: VITE_PROXY_BACKEND,
    proxyPath: '/chat'
  },

  // 路径配置
  // 关键约束：asar 内的文件路径可读（preload / index.html），但 nativeImage 等原生 API
  // 不能读 asar 内部，所以图标必须放在 asar 外面（通过 package.json 的 extraResources
  // 复制到 app/Contents/Resources/build/，运行时用 process.resourcesPath 取）。
  paths: {
    // 正式模式加载 vite build 产物（dist/index.html）。
    // 源模板（../index.html）里引用 /src/main.js，在 file:// 下访问不到，会白屏。
    // __dirname 在 asar 内解析为 .../app.asar/electron，../dist 即 .../app.asar/dist，asar patch 支持。
    indexHtml: path.join(__dirname, '../dist/index.html'),
    preload: path.join(__dirname, 'preload.js'),
    // 窗口图标（macOS 标题栏 / Windows 标题栏 / Linux 任务栏）：打包后从包外取
    icon: app.isPackaged
      ? path.join(process.resourcesPath, 'build', 'icon.png')
      : path.join(__dirname, 'public/favicon.png'),
    // macOS Dock 图标（必须在 dev 模式下通过 app.dock.setIcon 显式设置，
    // 因为 BrowserWindow.icon 在 macOS 不影响 Dock）。
    // 必须是 PNG：app.dock.setIcon 内部走 nativeImage.createFromPath，不认 .icns。
    // 打包后的 .icns 由 package.json 的 build.mac.icon 提供给 OS。
    iconMac: app.isPackaged
      ? path.join(process.resourcesPath, 'build', 'icon.png')
      : path.join(__dirname, '../build/icon.png')
  },

  // 安全策略配置
  security: {
    allowExternalLinks: true,
    previewWindow: {
      width: 850,
      height: 620
    },
    blockedShortcuts: ['F12', 'CmdOrCtrl+Shift+I', 'CmdOrCtrl+Shift+C', 'CmdOrCtrl+Shift+J']
  },

  // 快捷键配置
  shortcuts: {
    newChat: 'CmdOrCtrl+N',
    quit: 'CmdOrCtrl+Q',
    reload: 'CmdOrCtrl+R',
    toggleDevTools: 'CmdOrCtrl+Shift+I',
    fullscreen: 'CmdOrCtrl+Shift+F'
  }
}
