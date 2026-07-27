import { contextBridge, ipcRenderer, shell } from 'electron/renderer'

// 暴露安全的 IPC 通道给渲染进程
contextBridge.exposeInMainWorld('electronAPI', {
  // 监听新对话事件
  onNewChat: (callback) => {
    ipcRenderer.on('new-chat', callback)
  },

  // 获取当前环境
  getEnvironment: () => process.env.NODE_ENV || 'production',

  // 检查是否为开发环境
  isDevelopment: () => process.env.NODE_ENV === 'development',

  // 检查是否为测试环境
  isTest: () => process.env.NODE_ENV === 'test',

  // ===== 启动引导相关（SetUpView 用）=====
  // 探测全部 6 项环境（python/uv/docker/redis/sandbox/venv）
  probeAll: () => ipcRenderer.invoke('startup:probe-all'),

  // 单项修复（uv/redis/sandbox/venv），返回 { ok, error? }；日志通过 onStartupLog 推流
  fixItem: (item) => ipcRenderer.invoke('startup:fix-item', item),

  // 启动后端（MCP 先 → backend 后），返回 { ok, error? }；成功后会触发 onStartupReady
  launch: () => ipcRenderer.invoke('startup:launch'),

  // 订阅实时日志（fix 期间 stdout/stderr 流）
  onStartupLog: (callback) => {
    const handler = (_event, data) => callback(data)
    ipcRenderer.on('startup:log', handler)
  },

  // 订阅启动完成事件（main 进程后端 ready 后触发，App.vue 切到主界面）
  onStartupReady: (callback) => {
    const handler = () => callback()
    ipcRenderer.on('startup:ready', handler)
  }
})

// 暴露 Electron 相关功能
contextBridge.exposeInMainWorld('electron', {
  // 在外部浏览器打开链接
  openExternal: (url) => shell.openExternal(url),

  // 在 Electron 独立窗口打开网页
  openWebPreview: (url) => ipcRenderer.invoke('open-web-preview', url),

  // 监听新对话事件
  onNewChat: (callback) => ipcRenderer.on('new-chat', callback)
})
