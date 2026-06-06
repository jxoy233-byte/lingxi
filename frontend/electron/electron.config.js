import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const viteConfig = await import('../vite.config.js')
const { viteServerConfig, viteBuildConfig } = viteConfig

export default {
  // 应用基本信息
  app: {
    name: '灵析',
    title: '灵析——数据分析智能助手',
    identifier: 'com.chatme.app',
    version: '1.0.0'
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

  // 从 Vite 自动导入的配置
  devServer: {
    url: `http://localhost:${viteServerConfig.port}`,
    port: viteServerConfig.port,
    strictPort: viteServerConfig.strictPort
  },

  backend: {
    apiUrl: viteServerConfig.proxy?.['/chat']?.target || 'http://127.0.0.1:8211',
    proxyPath: '/chat'
  },

  // 路径配置
  paths: {
    indexHtml: path.join(__dirname, '../index.html'),
    preload: path.join(__dirname, 'preload.js'),
    icon: path.join(__dirname, 'public/favicon.ico')
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
