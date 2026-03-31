import { contextBridge, ipcRenderer } from 'electron/renderer'

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

console.log('✅ Electron Preload 已加载')
