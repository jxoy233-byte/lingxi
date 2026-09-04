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

  // ===== 启动引导相关（BootstrapView 用）=====
  // 单窗口架构：始终一个 BrowserWindow，渲染层根据 servicesReady 决定显示 BootstrapView 还是主界面。
  // 不再区分引导窗口 / 主窗口（也不需要 isSetupWindow 标志）。

  // 探测 3 项基础环境（projectRoot / python / docker）。uv/redis/sandbox/venv
  // 不在 UI 暴露，bootstrap 阶段自动搞定。
  probeAll: () => ipcRenderer.invoke('startup:probe-all'),

  // 当前项目根路径（null 表示尚未定位到）
  getProjectRoot: () => ipcRenderer.invoke('startup:get-project-root'),

  // 弹目录选择框手动指定项目根，返回 { ok, projectRoot?, error? }
  pickProjectRoot: () => ipcRenderer.invoke('startup:pick-project-root'),

  // 弹目录选择框选「clone 父目录」，只返回 targetDir 不触发 clone。
  // BootstrapView 克隆确认卡片走这个 → 拿目录后再 invoke autoClone。
  pickCloneTarget: () => ipcRenderer.invoke('startup:pick-clone-target'),

  // 返回默认 clone 父目录（os.homedir()）。BootstrapView 卡片显示用。
  // 用户看到的是父目录（git 会按仓库名自动创建 lingxi/ 子目录），不是 ~/lingxi/。
  getDefaultCloneTarget: () => ipcRenderer.invoke('startup:get-default-clone-target'),

  // 自动 git clone 项目到 ~/lingxi。已存在且合法 → 复用；不存在 → 拉；
  // 已存在但不是 lingxi → 拒绝；git 未装会返回 ok=false 含 stderr 错误。
  // onLog 推送走 'startup:log' 通道（onStartupLog 订阅）。
  autoClone: (opts = {}) => ipcRenderer.invoke('startup:auto-clone', opts),

  // 手动启动 Docker Desktop（probe-all 检测到 docker 已装但 daemon 没跑时用）。
  // 跨平台由 main 端 startDockerDesktop 负责；调用后 UI 自己 recheck 直到 daemon up 或超时。
  startDocker: () => ipcRenderer.invoke('startup:start-docker'),

  // 一键 bootstrap：uv → redis → sandbox → venv → mcp → backend 串行执行。
  // 完成后主进程 broadcast servicesReady=true，App.vue 翻 appReady=true → BootstrapView 自动消失。
  bootstrap: (options = {}) => ipcRenderer.invoke('startup:bootstrap', options),

  getStartupPreferences: () => ipcRenderer.invoke('startup:get-preferences'),
  setAutoEnterFrontend: (value) => ipcRenderer.invoke('startup:set-auto-enter', value === true),

  // 订阅实时日志（bootstrap 期间 stdout/stderr 流）
  onStartupLog: (callback) => {
    const handler = (_event, data) => callback(data)
    ipcRenderer.on('startup:log', handler)
  },

  // 服务就绪状态：renderer 首次 mount 拉一次（避免订阅前错过事件），
  // 之后订阅 onServicesReadyChange 接收后续变更（bootstrap 完成 / 进程重启）。
  //   - getServicesReady：返 bool（warm path 拉快照够用）
  //   - onServicesReadyChange：返 { ready, autoEnterFrontend? }；
  //     cold start 完成时 main 带 autoEnterFrontend 让 renderer 决定是否立刻翻 appReady；
  //     autoEnterFrontend=undefined 时 BootstrapView 不需要重渲染按钮（warm / false 都是 noop）。
  getServicesReady: () => ipcRenderer.invoke('startup:get-services-ready'),
  onServicesReadyChange: (callback) => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('startup:services-ready-changed', handler)
  },

  // ===== 健康监测（5s 轮询）=====
  // 拉一次当前状态（首次 mount 用，避免等下一个 5s 周期）
  getHealth: () => ipcRenderer.invoke('startup:get-health'),

  // 订阅状态变化推送（仅在状态切换时触发，避免每秒无效事件）
  onHealthChange: (callback) => {
    const handler = (_event, data) => callback(data)
    ipcRenderer.on('backend-health-changed', handler)
  },

  // 用户在 banner 上点「重新连接」：杀 mcp/backend 后串行重启
  restartBackend: () => ipcRenderer.invoke('startup:restart-backend'),

  // ===== 安装向导 SetupView 用 =====
  // 探测本地 LibreOffice：返 { installed, version?, path? }。
  // 已装 → UI 显示绿✓ + 版本号；未装 → 显示说明 + 通用下载链接到 libreoffice.org/download。
  probeLibreOffice: () => ipcRenderer.invoke('setup:probe-libreoffice'),

  // 头部 ↻ 刷新按钮：走主进程 webContents.reload()，比 window.location.reload() 更可靠
  // （file:// + protocol.handle 拦截器下 JS 级 reload 偶尔没可见反馈）
  refreshPage: () => ipcRenderer.invoke('app:refresh-page'),
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
