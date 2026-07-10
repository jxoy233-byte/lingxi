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
  isTest: () => process.env.NODE_ENV === 'test'
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
