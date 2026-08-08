<template>
  <!--
    双路径（按 isElectron 分流）+ 初始 gate（按 _isInitializing 分流）：
    - _isInitializing 期间（首次 servicesReady IPC 还没回，约 5-50ms）：只渲染空白底色占位，
      既不显示主界面也不显示 SetUpView——避免「已知 warm 还要闪一下 SetUpView / 已知 cold 还要闪一下空主界面」。
    - 拿到结果后：
      - Electron cold（servicesReady=false）：主界面灰显 + SetUpView 叠加 → bootstrap 完成 → 解除 disabled + SetUpView 淡出
      - Electron warm（servicesReady=true）/ Web：主界面直接挂载，不再有任何闪烁
  -->
  <div v-if="_isInitializing" class="app-loading-bg"></div>
  <template v-else>
  <div
    :class="['app-container', { 'dark-theme': isDarkTheme, 'app-disabled': isElectron && !appReady }]"
  >
    <div class="main-layout">
      <Sidebar
        :collapsed="sidebarCollapsed"
        :conversations="conversations"
        :active-session-id="currentSessionId"
        :mobile-open="sidebarMobileOpen"
        :active-streaming-sessions="_activeStreamingSessions"
        :completed-sessions="_completedSessions"
        :approval-pending-sessions="_approvalPendingSessions"
        :error-sessions="_errorSessions"
        :load-error="conversationsLoadError"
        @toggle="toggleSidebar"
        @new-chat="createNewChat"
        @select-conversation="loadConversation"
        @delete-conversation="deleteConversation"
        @update-title="updateConversationTitle"
        @refresh-conversation="refreshConversation"
      />

      <!-- 移动端侧边栏遮罩 -->
      <div
        v-if="sidebarMobileOpen"
        class="sidebar-overlay"
        @click="closeMobileSidebar"
      />

      <main class="chat-area">
        <ChatHeader
          :has-session="!!currentSessionId"
          @open-settings="settingsVisible = true"
          @toggle-checkpoints="toggleCheckpoints"
          @toggle-sidebar="toggleMobileSidebar"
          @refresh="refreshPage"
        >
          <template v-if="currentSessionId" #extra-actions>
            <DataAnalysisTree
              ref="dataAnalysisTree"
              :session-id="currentSessionId"
              @file-click="onDataAnalysisFileClick"
            />
          </template>
        </ChatHeader>

        <MessageList
          ref="messageList"
          :messages="messages"
          :is-loading="isLoading"
          :is-interrupted="isInterrupted"
          :is-interrupted-session-id="isInterruptedSessionId"
          :current-session-id="currentSessionId"
          :has-received-init="hasReceivedInit"
          :pending-interrupt-session-id="_pendingInterruptSessionId"
          :pending-tool-approval="pendingToolApproval"
          :submitting-tool-decision="submittingToolDecision"
          @tool-decide="onToolDecision"
          @restore="restoreCheckpoint"
          @restream="handleRestream"
          @open-link="openWebPreview"
          @preview-file="previewFile"
          @interrupt="handleInterrupt"
          @resume="handleResume"
          @quote="handleQuote"
        />

        <MessageInput
          ref="messageInput"
          :is-loading="isLoading"
          :session-id="currentSessionId"
          :permission-resume-in-flight="permissionResumeInFlight"
          v-model:quote="currentQuote"
          @send="sendMessage"
          @files-selected-need-session="handleFilesSelectedNeedSession"
        />
      </main>

      <CheckpointPanel
        :visible="showCheckpoints"
        :messages="messages"
        @close="showCheckpoints = false"
        @restore="restoreCheckpoint"
      />

      <WebPreviewPanel
        :visible="showWebPreview"
        :url="webPreviewUrl"
        @close="showWebPreview = false"
        @resizing="isResizingWebPreview = $event"
      />

      <!-- 点击空白区域关闭网页预览面板 -->
      <div
        v-if="showWebPreview && !isResizingWebPreview"
        class="web-preview-overlay"
        @click="showWebPreview = false"
      />

      <!-- 图片预览弹窗 -->
      <div
        v-if="showImagePreview"
        class="image-preview-overlay"
        @click="showImagePreview = false"
      >
        <div class="image-preview-content" @click.stop>
          <button class="image-preview-close" @click="showImagePreview = false">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
          <img :src="imagePreviewUrl" alt="预览图片" class="image-preview-img" />
        </div>
      </div>

      <!-- 文件预览面板 -->
      <FilePreviewPanel
        :visible="showFilePreview"
        :tabs="filePreviewTabs"
        :active-tab-id="activeFilePreviewTabId"
        :session-id="currentSessionId"
        @close="showFilePreview = false"
        @activate-tab="activateFilePreviewTab"
        @close-tab="closeFilePreviewTab"
        @reload="reloadPreview"
        @file-select="onDataAnalysisFileClick"
      />

      <!-- 点击空白区域关闭文件预览面板 -->
      <div
        v-if="showFilePreview"
        class="file-preview-overlay"
        @click="showFilePreview = false"
      />

      <!-- 点击空白区域关闭历史记录面板 -->
      <div
        v-if="showCheckpoints"
        class="checkpoint-overlay"
        @click="showCheckpoints = false"
      />

      <!-- 后端失联 banner：主进程每 10s 探一次 /health + MCP ready，
           仅在状态变化时推 backend-health-changed。失联时显示顶部条 + 重新连接按钮，
           用户点「重新连接」后由主进程 kill + restart mcp/backend，banner 自动消失。 -->
      <div
        v-if="backendHealth === false"
        class="backend-health-banner"
        role="alert"
      >
        <span class="banner-icon">⚠️</span>
        <span class="banner-text">后端服务已断开连接，部分功能不可用</span>
        <button
          class="banner-action"
          :disabled="restartingBackend"
          @click="handleRestartBackend"
        >{{ restartingBackend ? '重新连接中...' : '重新连接' }}</button>
      </div>
    </div>

    <ConfirmDialog
      :visible="showRestoreConfirm"
      title="恢复历史版本"
      message="恢复到此版本后，之后的消息将被删除，确定要继续吗？"
      confirm-text="确定恢复"
      cancel-text="取消"
      @confirm="confirmRestore"
      @cancel="cancelRestore"
    />

    <!-- 续接输入弹窗 -->
    <div v-if="showResumeInput" class="resume-input-overlay" @click="cancelResume">
      <div class="resume-input-dialog" @click.stop>
        <div class="resume-input-title">继续对话</div>
        <div class="resume-input-desc">添加续接消息，或留空直接继续</div>
        <textarea
          v-model="resumeInputText"
          class="resume-input-textarea"
          placeholder="输入续接内容（可选）..."
          rows="3"
        ></textarea>
        <div class="resume-input-buttons">
          <button class="resume-input-cancel" @click="cancelResume">取消</button>
          <button class="resume-input-confirm" @click="confirmResume">继续</button>
        </div>
      </div>
    </div>

    <!-- 设置弹窗 -->
    <SettingsDialog
      :visible="settingsVisible"
      :is-dark-theme="isDarkTheme"
      @close="settingsVisible = false"
      @theme-change="setTheme"
    />
  </div>

  <!--
    启动浮窗：仅 Electron 路径 + 主界面还没启用（!appReady）时挂载。
    包含 3 种状态：
      - cold start：servicesReady=false，SetUpView 显示「启动应用」按钮
      - cold start 完成后未勾自动进：servicesReady=true && appReady=false，SetUpView 显示「进入应用」
      - warm start：appReady=true，SetUpView 不挂载（不闪一下）
    当后端从 health→crash 时 appReady 重置为 false，SetUpView 重新显示「启动应用」。
    v-if 切换走淡入淡出过渡，不直接 v-show（v-show 会让 .setup-overlay 的 animation 反复触发）。
  -->
  <transition name="setup-fade">
    <SetUpView
      v-if="isElectron && !appReady"
      :services-ready="servicesReady === true"
      @enter-app="onEnterApp"
    />
  </transition>
  </template>
</template>

<script>
import Sidebar from './components/Sidebar.vue'
import ChatHeader from './components/ChatHeader.vue'
import MessageList from './components/MessageList.vue'
import MessageInput from './components/MessageInput.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import SetUpView from './components/SetUpView.vue'
import CheckpointPanel from './components/CheckpointPanel.vue'
import WebPreviewPanel from './components/WebPreviewPanel.vue'
import FilePreviewPanel from './components/FilePreviewPanel.vue'
import DataAnalysisTree from './components/DataAnalysisTree.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import mermaid from 'mermaid'
import {
  MAX_TEXT_PREVIEW_BYTES,
  buildFilePreviewSourceKey,
  fetchTextPreview,
  getFileSuffix,
  isHtmlPreviewFile,
  isImagePreviewFile,
  isOfficePreviewFile,
  truncateTextToBytes
} from './utils/filePreview.js'

export default {
  name: 'App',
  components: {
    Sidebar,
    ChatHeader,
    MessageList,
    MessageInput,
    ConfirmDialog,
    SetUpView,
    CheckpointPanel,
    WebPreviewPanel,
    FilePreviewPanel,
    DataAnalysisTree,
    SettingsDialog
  },
  data() {
    return {
      isDarkTheme: false,
      sidebarCollapsed: false,
      conversations: [],
      // 加载会话失败时的错误消息（用户可见），空字符串 = 成功或尚未加载
      conversationsLoadError: '',
      // 是否在 Electron 环境运行（仅有 electronAPI）；web 永远 false
      // 控制是否走 servicesReady 状态机 + 渲染 SetUpView 浮窗
      isElectron: false,
      // 后端服务就绪状态：null = 首次 IPC 还没回（gate 期间不渲染任何东西，避免闪烁）；
      // true = 后端可用；false = 后端未启动（cold start，需要走 bootstrap + SetUpView 浮窗）
      servicesReady: null,
      // 启动引导完成标志（区分 servicesReady：appReady 表示「主界面启用 + 会话已初始化」，
      // 后端重启可能让 appReady 重置但 servicesReady 翻 true 时同样需要重 init）
      appReady: false,
      // 首次 servicesReady 检查还没回来时为 true，期间不渲染主界面也不渲染 SetUpView。
      // Electron IPC 单次往返通常 < 10ms，最多 50ms 左右，体感几乎不可见；
      // 但换来「warm start 不闪浮窗 / cold start 不闪空主界面」的干净体验。
      _isInitializing: true,
      currentSessionId: null,
      messages: [],
      isLoading: false,
      showCheckpoints: false,
      showRestoreConfirm: false,
      restoreTargetId: null,
      showWebPreview: false,
      webPreviewUrl: '',
      isResizingWebPreview: false,
      showImagePreview: false,
      imagePreviewUrl: '',
      showFilePreview: false,
      filePreviewTabs: [],
      activeFilePreviewTabId: null,
      _previewLoadControllers: new Map(),
      _previewTabSequence: 0,
      responseStartTime: null,
      responseTimerInterval: null,
      currentResponseTime: 0,
      currentAiMessageIndex: null,
      isRestreaming: false,
      isInterrupted: false,  // 当前会话是否处于中断状态
      isInterruptedSessionId: null,  // 最近一次中断的会话ID
      hasReceivedInit: false,  // 流式响应是否已收到 init 消息
      _pendingInterruptSessionId: null,  // 临时存储流式响应中的 session_id
      isMobile: false,
      sidebarMobileOpen: false,
      interruptReason: '',  // 中断原因
      showResumeInput: false,  // 显示续接输入框
      resumeInputText: '',  // 续接输入文本
      currentQuote: null,  // 当前引用内容：{ content: string }
      settingsVisible: false,  // 设置弹窗可见性
      // 工具调用级别的内嵌审批：标记具体 AI 消息 + tool call，让 MessageItem 高亮该 tool 并渲染内嵌按钮
      pendingToolApproval: null,  // { messageIndex, toolIndex, command, action, sessionId }
      submittingToolDecision: false,
      // 权限 resume 流期间为 true（用户点完审批按钮、后端正在执行 Command(resume)）——
      // 此期间禁用发送按钮防止用户并发发起新请求。仅此一处使用，与 submittingToolDecision
      // 不同：后者语义是"提交决策中"（瞬时），前者覆盖整个 resume 流生命周期。
      permissionResumeInFlight: false,
      _sessionHadError: new Set(),  // 处于「出错保护态」的 session_id 集合；保护态下不重拉 messages，避免覆盖错误气泡
      // —— 侧栏状态点跟踪（绿/黄/红）——
      _completedSessions: new Set(),       // 流式 clean done 后待用户回看（绿点）
      _approvalPendingSessions: new Set(),  // 等用户审批（黄点）
      _errorSessions: new Set(),           // 出错待用户回看（红点；与 _sessionHadError 并行，UI 保护职责留给后者）
      // —— 流式会话状态保存（用户切走后 SSE 继续推进 + 切回时恢复 in-progress）——
      _activeStreamingSessions: new Set(),  // 正在流式的 session_id 集合；驱动侧栏小点 + loadConversation 分支判断
      _streamingMessages: new Map(),       // session_id -> 当前 messages 数组引用（与 this.messages 同源）
      _streamingMeta: new Map(),           // session_id -> { aiIndex, responseStartTime, userMessage, lastUserMessage }
      _streamTimers: new Map(),            // session_id -> setInterval id；本地读秒（每 250ms 重算 elapsedMs），让 SSE 事件间隙数字也能跳
      // —— 后端健康监测 —— null = 还没拉过；true = 健康；false = 失联 → 显示 banner
      backendHealth: null,
      restartingBackend: false,  // 用户点「重新连接」期间 disable 按钮，避免重复触发
      // appReady 从 false→true 触发的 initConversationState 只跑一次，避免 servicesReady
      // 反复变化时（比如重启后端）重复初始化会话
      _conversationInited: false
    }
  },
  mounted() {
    // 单窗口架构（Electron）：主界面永远 mount，SetUpView 浮窗叠加在 .app-disabled 主界面上方。
    // Web 端：根本不渲染 SetUpView（直接进主界面），不走 servicesReady 状态机。
    //        isElectron = !!window.electronAPI 控制两套路径分流。
    const savedTheme = localStorage.getItem('chatme-theme')
    if (savedTheme) {
      this.isDarkTheme = savedTheme === 'dark'
    }

    // 检测移动端
    this.isMobile = window.innerWidth <= 600
    window.addEventListener('resize', this.handleResize)

    if (window.electronAPI?.getServicesReady) {
      // ===== Electron 路径 =====
      this.isElectron = true
      // 拉一次 servicesReady 快照（避免订阅前错过早期事件），然后订阅后续变更。
      // 路径分流：
      //   - ready=true（warm）：servicesReady=true，直接 init，SetUpView 永远不渲染（不闪）
      //   - ready=false（cold）：servicesReady=false，SetUpView 浮窗渲染，主界面灰显
      window.electronAPI.getServicesReady().then(ready => {
        this.servicesReady = !!ready
        this._isInitializing = false
        if (ready && !this._conversationInited) {
          this._conversationInited = true
          this.appReady = true
          this.$nextTick(() => this.initConversationState())
        }
      })
      // 后续变更：bootstrap 完成 / 后端重启。
      // payload = { ready, autoEnterFrontend? }：cold 完成时主进程带 autoEnterFrontend，
      // =true 立刻翻 appReady，=false 保留 SetUpView 等用户点「进入应用」。
      // warm / restart / crash-to-false 这几条路径只读 ready 字段。
      window.electronAPI.onServicesReadyChange((payload) => {
        const ready = !!(payload && payload.ready)
        const autoEnter = !!(payload && payload.autoEnterFrontend)
        const wasReady = !!this.servicesReady
        this.servicesReady = ready
        // cold start 完成 → ready 翻 true
        if (ready && !wasReady && !this._conversationInited) {
          if (autoEnter) {
            // 勾了自动进：立即翻 appReady 让主界面接管
            this._conversationInited = true
            this.appReady = true
            this.$nextTick(() => this.initConversationState())
          } else {
            // 没勾自动进：保持 appReady=false，SetUpView 显示「进入应用」等用户点
            this.appReady = false
          }
        }
        // 后端从 true 变 false（重启中）：主界面回退到 disabled，SetUpView 重新显示
        if (!ready && wasReady) {
          this.appReady = false
        }
      })
    } else {
      // ===== Web 路径 =====
      this.isElectron = false
      this.servicesReady = true
      this.appReady = true
      this._isInitializing = false
      // Web 直接调 initConversationState——不绕道 watcher（避免时序坑）
      if (!this._conversationInited) {
        this._conversationInited = true
        this.$nextTick(() => this.initConversationState())
      }
    }

    // 订阅后端健康监测：主进程 10s 探一次，仅在状态变化时推 backend-health-changed；
    // 首次 mount 拉一次 get-health 拿到「没在推事件」时的当前状态（如一直健康从未变化）。
    if (window.electronAPI?.getHealth) {
      window.electronAPI.getHealth().then(h => {
        if (h && typeof h.backend === 'boolean') this.backendHealth = h.backend
      })
      window.electronAPI.onHealthChange(({ backend }) => {
        this.backendHealth = backend
      })
    }
  },
  watch: {
    '$route.params.sessionId'(newSessionId) {
      // 监听 URL 变化
      if (newSessionId && newSessionId !== this.currentSessionId && newSessionId.trim() !== '') {
        this.loadConversation(newSessionId)
      } else if (!newSessionId || newSessionId.trim() === '') {
        this.createNewChat()
      }
    },
    // appReady 从 false → true 时主界面从 disabled 变可交互，需要初始化会话状态。
    // 仅 Electron 路径用：web 在 mounted 里已经直接调过 initConversationState，避免 Vue 3
    // reactivity 时机问题导致 web 端刷新后 conversations 不加载。
    // _conversationInited 防反复触发（bootstrap 完成后 servicesReady 反复广播也只 init 一次）。
    appReady: {
      handler(ready) {
        if (ready && !this._conversationInited && this.isElectron) {
          this._conversationInited = true
          this.initConversationState()
        }
      },
      immediate: false
    }
  },
  methods: {
    setTheme(isDark) {
      this.isDarkTheme = !!isDark
      localStorage.setItem('chatme-theme', this.isDarkTheme ? 'dark' : 'light')
    },
    /**
     * 用户在 SetUpView 上点「进入应用」：
     * 翻 appReady=true 触发 .app-disabled 解除 + initConversationState。
     * 与 warm path / cold autoEnter=true 同路径（自动翻 + init），只是入口从 IPC 广播
     * 变成 SetUpView 的主动 emit。
     */
    onEnterApp() {
      if (!this.appReady) {
        this._conversationInited = true
        this.appReady = true
        this.$nextTick(() => this.initConversationState())
      }
    },
    /**
     * 用户点 banner 上的「重新连接」：调 IPC 让主进程 kill mcp/backend 后串行重启。
     * 完成后主进程会主动推 backend-health-changed，banner 自动消失；
     * 失败用 alert 提示（重启通常意味着后端进程死掉，原因多样，没必要做精细错误分类）。
     */
    async handleRestartBackend() {
      if (this.restartingBackend) return
      this.restartingBackend = true
      try {
        const r = await window.electronAPI.restartBackend()
        if (!r?.ok) {
          alert('重新连接失败：' + (r?.error || '未知错误'))
        }
      } finally {
        this.restartingBackend = false
      }
    },
    /**
     * 会话状态初始化：拉会话列表 + 按 URL 决定进历史会话还是新对话。
     * 仅主窗口调用；引导窗不会初始化会话状态。
     */
    initConversationState() {
      this.loadConversations()
      this.$nextTick(() => {
        const initialSessionId = this.$route.params.sessionId
        if (initialSessionId) {
          this.loadConversation(initialSessionId)
        } else {
          this.createNewChat()
        }
      })
    },
    refreshPage() {
      // Electron app：走主进程 webContents.reload() 整页硬刷，比 window.location.reload()
      // 可靠（file:// + protocol.handle 拦截器下，JS 级 reload 偶尔没可见反馈）。
      // web 端没有 electronAPI → 退回 location.reload()。
      if (window.electronAPI?.refreshPage) {
        window.electronAPI.refreshPage()
      } else {
        // 浏览器/Electron 通用：location.reload() 会重新走 protocol.handle 拦截器，
        // 把 /chat/* 重新代理到后端，所有 Vue state 重置
        window.location.reload()
      }
    },
    /**
     * 把后端流式事件携带的 elapsed_ms / token_usage 写到 AI 消息上（in-place，Vue 2 响应式）。
     * 适用于 this.messages[aiIndex] 和 snap[meta.aiIndex] 两种场景；调用前确保目标 message 引用已替换。
     * 同时把权威 elapsed_ms 同步到 responseTime 字段，让 UI 展示/历史回放都拿到后端 wall-clock。
     */
    writeStreamMetrics(msg, data) {
      if (!msg || !data) return
      if (data.elapsed_ms !== undefined && data.elapsed_ms !== null) {
        msg.elapsedMs = data.elapsed_ms
        msg.responseTime = data.elapsed_ms / 1000
      }
      if (data.token_usage !== undefined && data.token_usage !== null) {
        msg.tokenUsage = data.token_usage
      }
    },
    /**
     * 启动本地读秒 interval，每 250ms 用前端 Date.now() 重算 msg.elapsedMs，
     * 让数字在 SSE 事件间隙也能跳（不依赖后端事件频率）。
     * 同一 session 只允许一个活跃 timer，先 stopStreamTimer 防重复。
     * 后端 done/error/interrupt 给的权威 elapsed_ms 会在终态事件里通过 writeStreamMetrics 覆盖。
     *
     * 注意：SSE 事件用 spread 写法 `this.messages[i] = { ...this.messages[i], ... }` 会替换数组里的
     * message 对象为新 plain 对象。Vue 2 数组索引 setter 拦截新值时会自动 observe 新对象，
     * 所以 spread 出去的"新对象"仍是响应式的；但旧对象引用已被替换，timer 必须动态取最新对象
     * 才能持续触发重渲染，否则会写到已脱离 Vue 树的对象上。
     */
    startStreamTimer(sessionId, msg) {
      this.stopStreamTimer(sessionId)
      if (!msg) return
      msg.startTs = Date.now()
      const meta = this._streamingMeta.get(sessionId)
      const timer = setInterval(() => {
        const arr = this._streamingMessages.get(sessionId)
        const cur = arr && meta && arr[meta.aiIndex]
        if (cur && cur.startTs) {
          cur.elapsedMs = Date.now() - cur.startTs
        }
      }, 250)
      this._streamTimers.set(sessionId, timer)
    },
    /**
     * 清除本地读秒 timer。SSE 循环异常断开（abort / 网络断开）场景由 done/error/interrupt 三处兜底。
     */
    stopStreamTimer(sessionId) {
      const timer = this._streamTimers.get(sessionId)
      if (timer !== undefined) {
        clearInterval(timer)
        this._streamTimers.delete(sessionId)
      }
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },
    handleResize() {
      this.isMobile = window.innerWidth <= 600
      if (!this.isMobile) {
        this.sidebarMobileOpen = false
      }
    },
    toggleMobileSidebar() {
      this.sidebarMobileOpen = !this.sidebarMobileOpen
    },
    closeMobileSidebar() {
      this.sidebarMobileOpen = false
    },
    async handleFilesSelectedNeedSession(files) {
      // MessageInput 已经存储了文件内容和 sessionId 到 sessionStorage
      // 这里只需要导航到对应的 sessionId，并等待导航完成
      const pendingSid = localStorage.getItem('pendingSessionId')
      const targetSid = pendingSid || crypto.randomUUID().replace(/-/g, '').slice(0, 12)

      console.log('[handleFilesSelectedNeedSession] files count:', files.length, 'pendingSid:', pendingSid, 'targetSid:', targetSid)

      if (!pendingSid) {
        localStorage.setItem('pendingSessionId', targetSid)
        console.log('[handleFilesSelectedNeedSession] Stored new pendingSid:', targetSid)
      }

      // 使用 await 确保路由导航完成
      try {
        await this.$router.push(`/${targetSid}`)
        console.log('[handleFilesSelectedNeedSession] Navigation complete to /', targetSid)
        // 设置 currentSessionId，这样后续 sendMessage 的 sessionChanged 检查才能通过
        this.currentSessionId = targetSid
        // 等待足够长时间，确保：
        // 1. Vue 组件完全更新
        // 2. MessageInput 的 sessionId prop 更新
        // 3. watch 触发 checkAndUploadPendingFiles
        await new Promise(resolve => setTimeout(resolve, 1000))
        console.log('[handleFilesSelectedNeedSession] Done waiting, triggering file upload')
        // 直接调用 MessageInput 的 checkAndUploadPendingFiles 方法
        this.$refs.messageInput?.checkAndUploadPendingFiles()
      } catch (e) {
        console.error('[handleFilesSelectedNeedSession] Navigation failed:', e)
      }
    },
    toggleCheckpoints() {
      this.showCheckpoints = !this.showCheckpoints
    },
    async handleInterrupt() {
      // 优先使用 currentSessionId，如果为空则使用流式响应中的 session_id
      let sessionId = this.currentSessionId || this._pendingInterruptSessionId
      if (!sessionId) {
        return
      }
      const url = `/chat/${sessionId}/interrupt`
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ interrupt_reason: 'user_initiated' })
        })
        if (!response.ok) {
          console.error('中断请求失败:', response.status)
        }
      } catch (error) {
        console.error('中断请求异常:', error)
      }
    },
    async handleResume(message = null) {
      if (!this.currentSessionId || this.isLoading) return

      // 如果没有传入消息，显示续接输入弹窗
      if (message === null) {
        this.showResumeInput = true
        this.resumeInputText = ''
        return
      }

      // 用户主动续接 → 视为恢复，清掉旧错误保护态
      this._sessionHadError.delete(this.currentSessionId)
      this.markSessionErrorResolved(this.currentSessionId)

      // 有消息则直接执行续接
      this.isInterrupted = false
      this.isLoading = true

      // 构建续接消息
      let resumeMessage = message && message.trim() ? message : 'CONTINUE'

      try {
        const response = await fetch(`/chat/${this.currentSessionId}/invoke_interrupted/${encodeURIComponent(resumeMessage)}`, {
          method: 'POST'
        })
        if (!response.ok) {
          throw new Error(`续接失败: ${response.status}`)
        }
        const reader = response.body.getReader()
        const decoder = new TextDecoder()

        // 锁定发起续接时的 session id（SSE 消费期间如果用户切换走，要按原始 sid 处理）
        const requestSessionId = this.currentSessionId

        // 找到最后一个 AI 消息，用它的索引续接
        let aiMessageIndex = -1
        for (let i = this.messages.length - 1; i >= 0; i--) {
          if (this.messages[i].role === 'ai') {
            aiMessageIndex = i
            break
          }
        }
        // 如果没有找到 AI 消息，创建新的
        if (aiMessageIndex === -1) {
          aiMessageIndex = this.messages.length
          this.messages.push({
            role: 'ai',
            content: '',
            reasoning: '',
            toolCalls: [],
            thinkingDone: false,
            streaming: true,
            responseTime: 0
          })
        } else {
          // 复用最后一个 AI 消息，继续输出
          this.messages[aiMessageIndex] = {
            ...this.messages[aiMessageIndex],
            streaming: true,
            thinkingDone: false
          }
        }
        this.currentAiMessageIndex = aiMessageIndex
        this.startResponseTimer()
        // 预先取最后一个用户消息，给 error 兜底分支用（避免 SSE 上来就 error 时 lastUserMessage 未定义）
        const lastUserMessage = this.messages.filter(m => m.role === 'user').pop()?.content || ''
        // —— 注册流式会话快照（用户切走时 SSE 增量写到 snapshot，切回时直接恢复 this.messages）——
        this._activeStreamingSessions.add(this.currentSessionId)
        this._streamingMessages.set(this.currentSessionId, this.messages)
        this._streamingMeta.set(this.currentSessionId, {
          aiIndex: aiMessageIndex,
          responseStartTime: this.responseStartTime,
          userMessage: lastUserMessage,
          lastUserMessage
        })
        this.startStreamTimer(this.currentSessionId, this.messages[aiMessageIndex])
        this._activeStreamingSessions = new Set(this._activeStreamingSessions)
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const part of parts) {
            const line = part.trim()
            if (!line) continue
            try {
              const data = JSON.parse(line)

              // 检查用户是否已切换走（续接中的会话切走，行为同 sendMessage：增量写 snapshot）
              const sessionChanged = this.currentSessionId !== requestSessionId
              if (sessionChanged) {
                const snap = this._streamingMessages.get(requestSessionId)
                const meta = this._streamingMeta.get(requestSessionId)
                if (snap && meta) {
                  if (data.type === 'content') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: snap[meta.aiIndex].content + data.content,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'reasoning') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      reasoning: snap[meta.aiIndex].reasoning + data.content,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_name') {
                    snap[meta.aiIndex] = this.mergeToolCallStart(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_result') {
                    snap[meta.aiIndex] = this.mergeToolCallResult(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'done') {
                    this.stopResponseTimer()
                    const wasError = snap[meta.aiIndex]?.error === true
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      role: 'ai',
                      content: wasError ? snap[meta.aiIndex].content : data.full_response,
                      reasoning: snap[meta.aiIndex].reasoning,
                      toolCalls: snap[meta.aiIndex].toolCalls,
                      thinkingDone: true,
                      streaming: false,
                      responseTime: this.currentResponseTime,
                      checkpointId: data.checkpoint_id || null,
                      error: wasError || undefined
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    // 绿点：clean done 才标记（已计算 wasError）
                    if (!wasError) this.markSessionCompleted(requestSessionId)
                    // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation（避免并发 N 个 done 时反复重拉）
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, lastUserMessage)
                    }
                  } else if (data.type === 'error') {
                    this._sessionHadError.add(requestSessionId)
                    this.markSessionErrored(requestSessionId)
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: `续接失败：${data.error}`,
                      error: true,
                      errorMessage: data.error,
                      streaming: false,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, lastUserMessage)
                    }
                  } else if (data.type === 'interrupt') {
                    this.stopResponseTimer()
                    const reason = data.reason || '用户主动中断'
                    snap[meta.aiIndex] = { ...snap[meta.aiIndex], streaming: false, interruptReason: reason }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation（避免并发 N 个 done 时反复重拉）
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, lastUserMessage)
                    }
                  } else if (data.type === 'permission_request') {
                    this.handlePermissionRequest(data, requestSessionId)
                  }
                }
                continue
              }

              if (data.type === 'init') {
                this.hasReceivedInit = true
                if (data.session_id) {
                  this._pendingInterruptSessionId = data.session_id
                }
              } else if (data.type === 'content') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: this.messages[aiMessageIndex].content + data.content,
                  thinkingDone: true,
                  responseTime: this.currentResponseTime
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_name') {
                this.messages[aiMessageIndex] = this.mergeToolCallStart(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_result') {
                this.messages[aiMessageIndex] = this.mergeToolCallResult(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'done') {
                this.stopResponseTimer()
                this.messages[aiMessageIndex] = {
                  role: 'ai',
                  content: data.full_response,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: this.currentResponseTime,
                  checkpointId: data.checkpoint_id || null
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                // lastUserMessage 已在 SSE 循环前预先取出
                await this.updateTitleAndRefresh(this.currentSessionId, lastUserMessage)
                // 清理快照
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                // 绿点：用户正在当前会话，无条件标记（用户在 done 时已经在看）
                this.markSessionCompleted(requestSessionId)
              } else if (data.type === 'error') {
                console.error('续接响应错误:', data.error)
                this._sessionHadError.add(this.currentSessionId)
                this.markSessionErrored(requestSessionId)
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: `续接失败：${data.error}`,
                  error: true,
                  errorMessage: data.error,
                  streaming: false,
                  thinkingDone: true
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                // 仅更新标题，不重拉 messages
                if (this.currentSessionId) {
                  await this.updateTitleOnly(this.currentSessionId, lastUserMessage)
                }
                // 清理快照
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              } else if (data.type === 'interrupt') {
                this.stopResponseTimer()
                const reason = data.reason || '用户主动中断'
                this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], streaming: false, interruptReason: reason }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                this.isInterrupted = true
                this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
                this.interruptReason = reason
                // 清理快照
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              } else if (data.type === 'permission_request') {
                this.handlePermissionRequest(data, requestSessionId)
              }
            } catch (e) {
              console.error('解析 SSE 消息失败:', e, '原始内容:', line)
            }
          }
        }
        if (buffer.trim()) {
          try {
            const data = JSON.parse(buffer.trim())
            const sessionChanged = this.currentSessionId !== requestSessionId
            if (sessionChanged) {
              const snap = this._streamingMessages.get(requestSessionId)
              const meta = this._streamingMeta.get(requestSessionId)
              if (snap && meta) {
                if (data.type === 'content') {
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    content: snap[meta.aiIndex].content + data.content,
                    thinkingDone: true,
                    responseTime: this.currentResponseTime
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'reasoning') {
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    reasoning: snap[meta.aiIndex].reasoning + data.content,
                    responseTime: this.currentResponseTime
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'tool_call_name') {
                  snap[meta.aiIndex] = this.mergeToolCallStart(snap[meta.aiIndex], data)
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'tool_call_result') {
                  snap[meta.aiIndex] = this.mergeToolCallResult(snap[meta.aiIndex], data)
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'done') {
                  this.stopResponseTimer()
                  const wasError = snap[meta.aiIndex]?.error === true
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    role: 'ai',
                    content: wasError ? snap[meta.aiIndex].content : data.full_response,
                    reasoning: snap[meta.aiIndex].reasoning,
                    toolCalls: snap[meta.aiIndex].toolCalls,
                    thinkingDone: true,
                    streaming: false,
                    responseTime: this.currentResponseTime,
                    checkpointId: data.checkpoint_id || null,
                    error: wasError || undefined
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                  this.stopStreamTimer(requestSessionId)
                  this._activeStreamingSessions.delete(requestSessionId)
                  this._streamingMessages.delete(requestSessionId)
                  this._streamingMeta.delete(requestSessionId)
                  this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                  // 绿点：clean done 才标记（buffer-tail sessionChanged 分支，已计算 wasError）
                  if (!wasError) this.markSessionCompleted(requestSessionId)
                  // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation
                  if (requestSessionId) {
                    await this.updateTitleOnly(requestSessionId, lastUserMessage)
                  }
                } else if (data.type === 'error') {
                  this._sessionHadError.add(requestSessionId)
                  this.markSessionErrored(requestSessionId)
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    content: `续接失败：${data.error}`,
                    error: true,
                    errorMessage: data.error,
                    streaming: false,
                    thinkingDone: true,
                    responseTime: this.currentResponseTime
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                  this.stopStreamTimer(requestSessionId)
                  this._activeStreamingSessions.delete(requestSessionId)
                  this._streamingMessages.delete(requestSessionId)
                  this._streamingMeta.delete(requestSessionId)
                  this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                  if (requestSessionId) {
                    await this.updateTitleOnly(requestSessionId, lastUserMessage)
                  }
                } else if (data.type === 'permission_request') {
                  this.handlePermissionRequest(data, requestSessionId)
                }
              }
            } else if (data.type === 'reasoning') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                responseTime: this.currentResponseTime
              }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'tool_call_name') {
              this.messages[aiMessageIndex] = this.mergeToolCallStart(this.messages[aiMessageIndex], data)
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'tool_call_result') {
              this.messages[aiMessageIndex] = this.mergeToolCallResult(this.messages[aiMessageIndex], data)
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'content') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                content: this.messages[aiMessageIndex].content + data.content,
                thinkingDone: true,
                responseTime: this.currentResponseTime
              }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'done') {
              this.stopResponseTimer()
              this.messages[aiMessageIndex] = {
                role: 'ai',
                content: data.full_response,
                reasoning: this.messages[aiMessageIndex].reasoning,
                toolCalls: this.messages[aiMessageIndex].toolCalls,
                thinkingDone: true,
                streaming: false,
                responseTime: this.currentResponseTime,
                checkpointId: data.checkpoint_id || null
              }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              // 清理快照
              this.stopStreamTimer(requestSessionId)
              this._activeStreamingSessions.delete(requestSessionId)
              this._streamingMessages.delete(requestSessionId)
              this._streamingMeta.delete(requestSessionId)
              this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              // 绿点：buffer-tail in-session done
              this.markSessionCompleted(requestSessionId)
            } else if (data.type === 'interrupt') {
              this.stopResponseTimer()
              const reason = data.reason || '用户主动中断'
              this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], streaming: false, interruptReason: reason }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              this.isInterrupted = true
              this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
              this.interruptReason = reason
              // 清理快照
              this.stopStreamTimer(requestSessionId)
              this._activeStreamingSessions.delete(requestSessionId)
              this._streamingMessages.delete(requestSessionId)
              this._streamingMeta.delete(requestSessionId)
              this._activeStreamingSessions = new Set(this._activeStreamingSessions)
            } else if (data.type === 'permission_request') {
              this.handlePermissionRequest(data, requestSessionId)
            }
          } catch (e) {
            console.error('解析缓冲区剩余数据失败:', e)
          }
        }
      } catch (error) {
        console.error('续接异常:', error)
      } finally {
        this.isLoading = false
        this.stopResponseTimer()
      }
    },
    cancelResume() {
      this.showResumeInput = false
      this.resumeInputText = ''
    },
    confirmResume() {
      const message = this.resumeInputText.trim()
      this.showResumeInput = false
      this.resumeInputText = ''
      // 直接调用 handleResume 并传入消息
      this.handleResume(message)
    },
    openWebPreview(url) {
      this.webPreviewUrl = url
      this.showWebPreview = true
    },
    // 处理引用事件：把用户从历史消息选中的内容存到 currentQuote
    handleQuote(quoteData) {
      if (quoteData && quoteData.content) {
        this.currentQuote = { content: quoteData.content }
      }
    },
    async previewFile(file) {
      const suffix = getFileSuffix(file)
      let url = file.url || file.preview || file.preview_url || file.iframe_url || ''

      if (isImagePreviewFile(file)) {
        if (!url && file.image_content) {
          if (typeof file.image_content === 'string') {
            url = file.image_content
          } else if (Array.isArray(file.image_content) && file.image_content.length > 0) {
            const first = file.image_content[0]
            url = typeof first === 'string' ? first : (first?.url || '')
          }
        }
        if (!url) return
        await this.openFilePreviewTab({ file, url, suffix, kind: 'image' })
        return
      }

      if (isOfficePreviewFile(file)) {
        const content = '此文件类型暂不支持在线预览。\n\n文件名：' + (file.name || '未知') + '\n文件大小：' + (file.size_human || '未知') + '\n\n请下载后使用本地应用程序查看。'
        await this.openFilePreviewTab({ file, url, suffix, kind: 'unsupported', content })
        return
      }

      const suppliedContent = file.text_content || file.content || ''
      const isMermaid = suffix === '.mmd' || String(file.type || '').includes('mermaid')
      if (isHtmlPreviewFile(file)) {
        await this.openFilePreviewTab({ file, url, suffix, kind: 'html', content: suppliedContent })
        return
      }

      if (suppliedContent || isMermaid || String(file.file_type || '').toUpperCase() === 'TEXT') {
        await this.openFilePreviewTab({ file, url, suffix, kind: 'text', content: suppliedContent })
        return
      }

      const otherPreviewUrl = file.preview_url || file.iframe_url
      if (otherPreviewUrl) {
        this.webPreviewUrl = otherPreviewUrl
        this.showWebPreview = true
        return
      }

      const content = '无法预览此文件。\n\n文件名：' + (file.name || '未知') + '\n文件类型：' + (suffix ? suffix.replace('.', '') : '未知') + '\n\n请下载后查看。'
      await this.openFilePreviewTab({ file, url, suffix, kind: 'unsupported', content })
    },
    async onDataAnalysisFileClick(fileNode) {
      const url = `/static/${fileNode.path}`
      const suffix = getFileSuffix(fileNode)
      let kind = 'text'
      if (isImagePreviewFile(fileNode)) kind = 'image'
      else if (isHtmlPreviewFile(fileNode)) kind = 'html'
      else if (isOfficePreviewFile(fileNode)) kind = 'unsupported'

      const content = kind === 'unsupported'
        ? '此文件类型暂不支持在线预览。\n\n文件名：' + (fileNode.name || '未知') + '\n\n请下载后使用本地应用程序查看。'
        : ''
      await this.openFilePreviewTab({ file: fileNode, url, suffix, kind, content })
    },
    async openFilePreviewTab({ file, url = '', suffix = '', kind = 'text', content = '' }) {
      const sourceKey = buildFilePreviewSourceKey(file, this.currentSessionId || '', url)
      const existing = this.filePreviewTabs.find(tab => tab.sourceKey === sourceKey)
      if (existing) {
        this.activeFilePreviewTabId = existing.id
        this.showFilePreview = true
        return existing
      }

      const id = `file-preview-${++this._previewTabSequence}`
      const size = Number(file.size ?? file.file_size ?? 0) || 0
      const initialText = truncateTextToBytes(content)
      const tab = {
        id,
        sourceKey,
        sessionId: this.currentSessionId || '',
        name: file.name || '文件预览',
        suffix: suffix || getFileSuffix(file),
        fileType: file.file_type || file.type || '',
        kind,
        url,
        sourceFile: file,
        size,
        content: initialText.text,
        renderedSvg: '',
        renderVersion: 0,
        loading: false,
        error: '',
        truncated: initialText.truncated || (!!content && size > MAX_TEXT_PREVIEW_BYTES),
        totalBytes: size || initialText.totalBytes
      }

      this.filePreviewTabs.push(tab)
      this.activeFilePreviewTabId = id
      this.showFilePreview = true

      if (kind === 'text' && (url || !content)) {
        const shouldFetch = !content || size > MAX_TEXT_PREVIEW_BYTES
        if (shouldFetch && url) await this.loadFilePreviewTab(id)
        else if (tab.suffix === '.mmd' && tab.content) await this.renderMermaidPreview(tab.id)
      }
      return tab
    },
    activateFilePreviewTab(tabId) {
      if (!this.filePreviewTabs.some(tab => tab.id === tabId)) return
      this.activeFilePreviewTabId = tabId
      this.showFilePreview = true
    },
    closeFilePreviewTab(tabId) {
      const index = this.filePreviewTabs.findIndex(tab => tab.id === tabId)
      if (index < 0) return
      this._previewLoadControllers.get(tabId)?.abort()
      this._previewLoadControllers.delete(tabId)
      this.filePreviewTabs.splice(index, 1)

      if (this.activeFilePreviewTabId === tabId) {
        const next = this.filePreviewTabs[index] || this.filePreviewTabs[index - 1] || null
        this.activeFilePreviewTabId = next?.id || null
      }
      if (this.filePreviewTabs.length === 0) this.showFilePreview = false
    },
    clearFilePreviewTabs() {
      for (const controller of this._previewLoadControllers.values()) controller.abort()
      this._previewLoadControllers.clear()
      this.filePreviewTabs = []
      this.activeFilePreviewTabId = null
      this.showFilePreview = false
    },
    async reloadPreview(tabId = this.activeFilePreviewTabId) {
      const tab = this.filePreviewTabs.find(item => item.id === tabId)
      if (!tab) return
      if (tab.kind === 'image' || tab.kind === 'unsupported') {
        tab.error = ''
        return
      }
      await this.loadFilePreviewTab(tabId, { loadHtmlSource: tab.kind === 'html' })
    },
    async loadFilePreviewTab(tabId, { loadHtmlSource = false } = {}) {
      const tab = this.filePreviewTabs.find(item => item.id === tabId)
      if (!tab || !tab.url || (tab.kind === 'html' && !loadHtmlSource)) return

      this._previewLoadControllers.get(tabId)?.abort()
      const controller = new AbortController()
      this._previewLoadControllers.set(tabId, controller)
      tab.loading = true
      tab.error = ''

      try {
        const result = await fetchTextPreview(tab.url, {
          signal: controller.signal,
          sizeHint: tab.size
        })
        if (this._previewLoadControllers.get(tabId) !== controller) return
        const currentTab = this.filePreviewTabs.find(item => item.id === tabId)
        if (!currentTab) return
        currentTab.content = result.text
        currentTab.truncated = result.truncated
        currentTab.totalBytes = result.totalBytes
        if (currentTab.suffix === '.mmd' && currentTab.content) {
          await this.renderMermaidPreview(tabId)
        }
      } catch (e) {
        if (e?.name !== 'AbortError') {
          const currentTab = this.filePreviewTabs.find(item => item.id === tabId)
          if (currentTab) currentTab.error = e?.message || String(e)
        }
      } finally {
        if (this._previewLoadControllers.get(tabId) === controller) {
          this._previewLoadControllers.delete(tabId)
          const currentTab = this.filePreviewTabs.find(item => item.id === tabId)
          if (currentTab) currentTab.loading = false
        }
      }
    },
    async renderMermaidPreview(tabId) {
      const tab = this.filePreviewTabs.find(item => item.id === tabId)
      if (!tab || !tab.content) return
      const renderVersion = ++tab.renderVersion
      const content = tab.content
      try {
        const renderId = `panel-${tabId}-${++this._previewTabSequence}`
        const { svg } = await mermaid.render(renderId, content)
        const currentTab = this.filePreviewTabs.find(item => item.id === tabId)
        if (currentTab && currentTab.renderVersion === renderVersion) {
          currentTab.renderedSvg = svg
        }
      } catch (e) {
        const currentTab = this.filePreviewTabs.find(item => item.id === tabId)
        if (currentTab && currentTab.renderVersion === renderVersion) {
          currentTab.renderedSvg = '<p style="color:red;padding:12px;">渲染失败: ' + (e?.message || e) + '</p>'
        }
      }
    },
    async restoreCheckpoint(checkpointId) {
      this.restoreTargetId = checkpointId
      this.showRestoreConfirm = true
    },
    mergeToolCallStart(message, data) {
      const toolCalls = [...(message.toolCalls || [])]
      // 1. 精确匹配：_pendingApproval && name===data.content.name
      //    （正常路径——前端 handlePermissionRequest 已按 tool_call_name 精确标过位）
      let pendingIdx = toolCalls.findIndex(
        toolCall => toolCall._pendingApproval && toolCall.name === data.content.name
      )
      // 2. 容错匹配：找到 _pendingApproval 但 name 不匹配 → 极可能是 sequencing 错位
      //    （老 backend 或异常情况下，pending UI 标到了别的 entry 上），修正它
      if (pendingIdx === -1) {
        pendingIdx = toolCalls.findIndex(toolCall => toolCall._pendingApproval)
      }
      // 3. 同 id 去重：resume / LangGraph 内部 ToolNode 重执行场景下，
      //    on_tool_start 可能再次触发（run_id 复用或同 tc.id）；如果已有同 id entry，
      //    命中后只更新 args/name 而不 push（防止 duplicate entry）。
      if (pendingIdx === -1 && data.id) {
        pendingIdx = toolCalls.findIndex(toolCall => toolCall.id === data.id)
      }
      if (pendingIdx !== -1) {
        // 任何命中路径都覆盖 id/name/args——确保 resume 后即便 run_id 变了，已有 entry
        // 的 id 也会被刷成最新的（mergeToolCallResult 按 id 查找才能命中）。
        toolCalls[pendingIdx] = {
          ...toolCalls[pendingIdx],
          id: data.id,
          name: data.content.name,
          args: data.content.args,
          _pendingApproval: false,
        }
      } else {
        toolCalls.push({
          name: data.content.name,
          args: data.content.args,
          id: data.id,
          result: null,
        })
      }
      return { ...message, toolCalls, responseTime: this.currentResponseTime }
    },
    mergeToolCallResult(message, data) {
      const toolCalls = [...(message.toolCalls || [])]
      let toolIndex = toolCalls.findIndex(toolCall => toolCall.id === data.id)
      if (toolIndex === -1) {
        toolIndex = toolCalls.findIndex(toolCall => toolCall._pendingApproval)
      }
      if (toolIndex !== -1) {
        toolCalls[toolIndex] = {
          ...toolCalls[toolIndex],
          id: data.id || toolCalls[toolIndex].id,
          result: data.content,
          _pendingApproval: false,
        }
      }
      return { ...message, toolCalls, responseTime: this.currentResponseTime }
    },
    // —— 侧栏状态点 helper（绿/黄/红）——
    // 全部幂等：add 前 has 检查、delete 前 .delete 返回值检查；mutate 后整 Set 替换触发 Vue 2 响应式
    markSessionCompleted(sessionId) {
      if (!sessionId) return
      if (this._completedSessions.has(sessionId)) return
      this._completedSessions.add(sessionId)
      this._completedSessions = new Set(this._completedSessions)
      // 防御性：完成同时清掉残留的 approval / error 状态（罕见但保证一致性）
      if (this._approvalPendingSessions.delete(sessionId)) {
        this._approvalPendingSessions = new Set(this._approvalPendingSessions)
      }
      if (this._errorSessions.delete(sessionId)) {
        this._errorSessions = new Set(this._errorSessions)
      }
    },
    markSessionApprovalPending(sessionId) {
      if (!sessionId) return
      if (this._approvalPendingSessions.has(sessionId)) return
      this._approvalPendingSessions.add(sessionId)
      this._approvalPendingSessions = new Set(this._approvalPendingSessions)
    },
    markSessionApprovalResolved(sessionId) {
      if (!sessionId) return
      if (!this._approvalPendingSessions.delete(sessionId)) return
      this._approvalPendingSessions = new Set(this._approvalPendingSessions)
    },
    markSessionErrored(sessionId) {
      if (!sessionId) return
      if (this._errorSessions.has(sessionId)) return
      this._errorSessions.add(sessionId)
      this._errorSessions = new Set(this._errorSessions)
    },
    markSessionErrorResolved(sessionId) {
      if (!sessionId) return
      if (!this._errorSessions.delete(sessionId)) return
      this._errorSessions = new Set(this._errorSessions)
    },
    /**
     * permission_request 事件统一处理：找到当前 AI 消息的待审批 tool call + 高亮 + 渲染内嵌按钮
     *
     * 在每个 SSE 循环的 'interrupt' 分支后挂 `} else if (data.type === 'permission_request') { ... }` 调用本方法
     */
    handlePermissionRequest(data, requestSessionId) {
      const sessionId = data.session_id || requestSessionId || ''
      // 黄点跟踪（独立于 singleton pendingToolApproval），必须在 early-return 之前：
      // singleton 是 UI 渲染状态（一时刻只能让用户对一个工具做决策），黄点是侧栏可见性标记（多 session 并行跟踪）。
      this.markSessionApprovalPending(sessionId)

      // 已有 pending 时忽略（singleton：每 sid 最多一个）
      if (this.pendingToolApproval) {
        // 跨会话泄漏守卫：现有 pending 指向别的 session，新 event 来自当前 session，
        // 必须清掉旧 pending 才能让当前 session 的 UI 正常显示（否则用户在切到新会话
        // 后看不到审批按钮）。同 session 的重复事件继续 drop。
        if (this.pendingToolApproval.sessionId !== sessionId) {
          this.pendingToolApproval = null
        } else {
          return
        }
      }

      // 幂等去重：F5 / 刷新会话后 processConversationMessages 会重建历史 toolCalls entry
      // （_pendingApproval 标志会丢，因为 history 里只是 AIMessage(REASONING) 的 tool_calls
      // 字段，不带前端运行时标志）。如果此时再调 handlePermissionRequest，扫描+合成路径
      // 会**再 push 一个新 entry**——同一个 tool 出现两条 entry：
      //   - 第一条是 processConversationMessages 重建的（无 _pendingApproval，看着像正常）
      //   - 第二条是 handlePermissionRequest 合成的（_pendingApproval=true）
      // 同一 tool_call_name + result===null 的 entry 视为重复——标 _pendingApproval=true
      // 而不是 push 新 entry。注意：deny/feedback 后 _pendingApproval 会被 onToolDecision
      // 置 false 并写 synthetic result，所以此守卫只在「未决 + 已被 processConversationMessages
      // 重建过」的边界 case 生效。
      if (data.tool_call_name) {
        const targets = []
        if (this._streamingMessages.has(requestSessionId)) {
          targets.push(this._streamingMessages.get(requestSessionId))
        }
        if (requestSessionId === this.currentSessionId) {
          targets.push(this.messages)
        }
        for (const arr of targets) {
          for (let i = arr.length - 1; i >= 0; i--) {
            const m = arr[i]
            if (m.role !== 'ai' || !m.toolCalls) continue
            for (let j = m.toolCalls.length - 1; j >= 0; j--) {
              if (m.toolCalls[j].name === data.tool_call_name && m.toolCalls[j].result === null) {
                // 找到重复 entry——标 _pendingApproval=true 并设置 pendingToolApproval，不 push
                const updatedToolCalls = [...m.toolCalls]
                updatedToolCalls[j] = { ...updatedToolCalls[j], _pendingApproval: true }
                arr[i] = { ...m, toolCalls: updatedToolCalls }
                this.pendingToolApproval = {
                  messageIndex: i,
                  toolIndex: j,
                  command: data.command || '',
                  action: data.action || 'write',
                  sessionId,
                }
                this.stopResponseTimer()
                return
              }
            }
            // 只看最新 AI message 上的 entry；旧 AI message 的同名 entry 是历史轮次，不能复用
            break
          }
        }
      }

      // 找到当前 AI 消息的最后一个无 result 的 tool call —— 这就是等待审批的工具调用
      // 优先级：this.messages（当前会话） > _streamingMessages snapshot（切走会话）
      const targets = []
      if (this._streamingMessages.has(requestSessionId)) {
        targets.push({ arr: this._streamingMessages.get(requestSessionId), isSnapshot: true })
      }
      if (requestSessionId === this.currentSessionId) {
        targets.push({ arr: this.messages, isSnapshot: false })
      }

      let aiMessageIndex = -1
      let toolIndex = -1
      let targetArr = null

      // 优先按 tool_call_name 精确匹配：permission_request SSE 事件携带了需要审批的工具名
      // （后端 _permission_target_for 返回），并发场景下 on_tool_start 的 arrival sequencing
      // 未必稳定（按"倒序找 result===null"会错位到 ctime 等非审批工具上——它们也 result===null
      // 只是永远不会变成 string 因为被 LangGraph gather cancel），按 name 精确匹配才能保证
      // pending UI 挂到正确的 tool_call entry 上。
      //
      // **必须再加 `result === null` 守卫**：resume 流里 LLM 决定调用新工具（code3）时，
      // 如果新工具又被 permission 中断，on_tool_start 不发 → 没有 tool_call_name(code3) SSE →
      // 此时 toolCalls 里只有上一轮 code2 (done)。如果只按 name 匹配 `name==='code'` 会命中
      // code2 已完成的 entry，把 _pendingApproval=true 覆盖到已完成 entry 上——表现为
      // 「已完成的 tool 又弹审批 UI」、「新工具请求没出现」。加上 `result === null` 过滤后，
      // code2 (done) 被跳过，synthesize 新 entry → 新工具请求正确显示为新 entry。
      //
      // round-after-loop 例外：如果倒序遍历命中的 entry 在**非最新** AIMessage 上（旧
      // AIMessage 留有上一轮 tool entry，新 AIMessage 上 tool_call_name event 还没来所以
      // 没有 entry），不能复用——要保留旧 entry（已完成/被拒绝的历史）不变，synthesize 新
      // entry 到最新 AIMessage 上。检测方式：i 之后还有 AIMessage → 不是最新。
      if (data.tool_call_name) {
        outer_name: for (const { arr } of targets) {
          for (let i = arr.length - 1; i >= 0; i--) {
            const m = arr[i]
            if (m.role !== 'ai' || !m.toolCalls) continue
            for (let j = m.toolCalls.length - 1; j >= 0; j--) {
              if (m.toolCalls[j].name === data.tool_call_name && m.toolCalls[j].result === null) {
                // 检查 i 是否对应最新 AIMessage
                let isLatestAi = true
                for (let k = i + 1; k < arr.length; k++) {
                  if (arr[k].role === 'ai') {
                    isLatestAi = false
                    break
                  }
                }
                if (isLatestAi) {
                  // 当前 round：采纳这个 entry
                  aiMessageIndex = i
                  toolIndex = j
                  targetArr = arr
                }
                // 不是最新 AIMessage 上的 entry → round-after-loop → 不采纳，
                // aiMessageIndex 保持 -1，下方 synthesize 路径会在最新 AIMessage 上 push 新 entry
                break outer_name
              }
            }
          }
        }
      }

      // 没找到精确匹配 entry 时，直接合成占位（旧版 fallback 路径"找 result===null"已删除——
      // 会标错到 ctime 那样的"result 永远=null"的非审批工具上）。
      // 合成时优先用 data.tool_call_name 作为 entry.name，比之前从 data.action 推断
      // （'code' → 'code' / 其他 → 'cmd'）更精确（兼容 tool_call_name='cmd' / 'code' 的
      // 实际 MCP 工具名）。
      if (aiMessageIndex === -1) {
        const toolName = data.tool_call_name || (data.action === 'code' ? 'code' : 'cmd')
        const command = data.command || ''
        let toolArgs
        if (toolName === 'code') {
          try {
            const parsedArgs = JSON.parse(command)
            toolArgs = parsedArgs && typeof parsedArgs === 'object'
              ? parsedArgs
              : { code: command }
          } catch {
            toolArgs = { code: command }
          }
        } else {
          toolArgs = { command }
        }
        outer: for (const { arr } of targets) {
          for (let i = arr.length - 1; i >= 0; i--) {
            const m = arr[i]
            if (m.role !== 'ai') continue
            const toolCalls = [...(m.toolCalls || [])]
            toolCalls.push({
              id: `pending-${sessionId}-${Date.now()}`,
              name: toolName,
              args: toolArgs,
              result: null,
              _pendingApproval: true,
            })
            arr[i] = { ...m, toolCalls }
            aiMessageIndex = i
            toolIndex = toolCalls.length - 1
            targetArr = arr
            break outer
          }
        }
      } else {
        // 历史里已有 AIMessage(REASONING) 留下的 toolCalls 条目（result=null），
        // 标记 _pendingApproval=true 让 resume 流来的 tool_call_name 事件能匹配上
        // mergeToolCallStart（按 _pendingApproval && name===data.content.name 匹配），
        // 避免重复 push 新条目导致冗余显示。merge 后 _pendingApproval 会被置回 false。
        //
        // round-after-loop 已被上方 matching 阶段排除（倒序命中非最新 AIMessage 上的
        // entry 时不采纳），所以走到这里的 entry 一定是当前 round 的、id/args 已经正确的，
        // 不需要再覆盖 args/result。
        const updatedToolCalls = [...targetArr[aiMessageIndex].toolCalls]
        updatedToolCalls[toolIndex] = {
          ...updatedToolCalls[toolIndex],
          _pendingApproval: true,
        }
        targetArr[aiMessageIndex] = {
          ...targetArr[aiMessageIndex],
          toolCalls: updatedToolCalls,
        }
      }

      this.pendingToolApproval = {
        messageIndex: aiMessageIndex,
        toolIndex,
        command: data.command || '',
        action: data.action || 'write',
        sessionId,
        // 不再缓存 targetArr 引用：onToolDecision 时按 sessionId + messageIndex/toolIndex
        // 重新解析（snapshot 优先 → 当前 messages 兜底），避免 stale 引用导致写错位置
      }

      // 停响应计时器 + 清理流式快照（pending 状态下不再产生增量事件）
      this.stopResponseTimer()
      this.stopStreamTimer(requestSessionId)
      this._activeStreamingSessions.delete(requestSessionId)
      this._streamingMessages.delete(requestSessionId)
      this._streamingMeta.delete(requestSessionId)
      this._activeStreamingSessions = new Set(this._activeStreamingSessions)
    },
    async onToolDecision(decision) {
      // decision: 'approve' | 'this-time-only' | 'deny' | 'feedback:<text>'
      // 后端 permissions.request_approval 看到 'feedback:' 前缀会返回 ("feedback", text)，
      // 由 _permission_wrap 包成 ToolMessage 让 LLM 看到用户指引并重新尝试调用。
      if (!this.pendingToolApproval) return
      const { sessionId } = this.pendingToolApproval
      if (!sessionId) {
        this.pendingToolApproval = null
        return
      }

      // deny / feedback 时：先把当前 entry 在前端本地标记为已拒绝 / 已反馈。
      // 根因：gate 返回 synthetic denied ToolMessage 时 LangGraph 不发 on_tool_end 事件，
      // ChatService 的 tool_call_result SSE 永远到不了前端，entry 会停在
      // _pendingApproval=true / result=null。如果不立刻更新，后续同 fingerprint 的
      // permission_request 会走 handlePermissionRequest 的 `name && result === null`
      // 匹配命中这条旧 entry，把 _pendingApproval 再次标 true —— 表现为"覆盖"而不是追加。
      //
      // 文案严格对齐后端 permissions.py:_rejected_tool_result / _feedback_tool_result
      // 的模板（permissions.py:507 / :520），保证前端展示与后端注入到 LangGraph state
      // 的 ToolMessage content 完全一致（LLM 看到什么，前端 UI 就展示什么）。
      // approve / this-time-only 不走这条路径：gate 真正执行 execute(request)，on_tool_start
      // + on_tool_end 会正常发，mergeToolCallStart / mergeToolCallResult 会正确写 result。
      if (decision === 'deny' || (typeof decision === 'string' && decision.startsWith('feedback:'))) {
        const { messageIndex, toolIndex, sessionId } = this.pendingToolApproval
        // 按需解析目标数组：snapshot 优先（用户可能切走过原 session，this.messages 已
        // 被替换成别的 session 的数组），当前 messages 兜底（in-session 决策场景）。
        const arr = this._streamingMessages.get(sessionId) || this.messages
        if (arr && arr[messageIndex] && arr[messageIndex].toolCalls && arr[messageIndex].toolCalls[toolIndex]) {
          const toolEntry = arr[messageIndex].toolCalls[toolIndex]
          const toolName = toolEntry.name || 'tool'
          const argsSummary = JSON.stringify(toolEntry.args || {}).slice(0, 200)
          let syntheticResult
          if (decision === 'deny') {
            syntheticResult =
              `User rejected this ${toolName} call (${argsSummary}); ` +
              `the ${toolName} was not executed and no side effects occurred. ` +
              `Think about possible alternative approaches, ` +
              `or use the interrupt tool to ask the user how to proceed.`
          } else {
            const feedbackText = decision.slice('feedback:'.length).trim()
            syntheticResult =
              `User has provided guidance for this ${toolName} call (${argsSummary}); ` +
              `the ${toolName} was not executed and no side effects occurred. ` +
              `User guidance: ${feedbackText}. ` +
              `Re-attempt the call considering this feedback.`
          }
          const updatedToolCalls = [...arr[messageIndex].toolCalls]
          updatedToolCalls[toolIndex] = {
            ...updatedToolCalls[toolIndex],
            result: syntheticResult,
            _pendingApproval: false,
          }
          arr[messageIndex] = { ...arr[messageIndex], toolCalls: updatedToolCalls }
        }
      }

      // 立刻 disable 按钮，防止用户连点 / 重复 /resume
      this.submittingToolDecision = true
      // 标记 resume 流开始——此期间禁用发送按钮（待审核时不禁用，见 MessageInput prop）
      this.permissionResumeInFlight = true
      try {
        // 第 1 步：写决策到 redis hash
        const decideResp = await fetch(`/chat/${sessionId}/permission/decide`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision }),
        })
        if (!decideResp.ok) {
          throw new Error(`decide failed: ${decideResp.status}`)
        }
        // 第 2 步：触发 Command(resume=decision) 让 LangGraph 继续
        const resumeResp = await fetch(`/chat/${sessionId}/permission/resume`, {
          method: 'POST',
        })
        if (!resumeResp.ok) {
          throw new Error(`resume failed: ${resumeResp.status}`)
        }
        // 清掉审批标记（tool_call_result 到达时也会清，这里先清掉按钮）
        this.pendingToolApproval = null
        // 黄点立即清除：用户做了决定 = 审批状态解除（不依赖后续 resume done 兜底）
        this.markSessionApprovalResolved(sessionId)
        // 走 SSE 流：复用 handleResume 的 SSE 处理逻辑（content / reasoning / tool_call / done）
        await this.handlePermissionResumeStream(resumeResp)
      } catch (error) {
        console.error('tool decision resume error:', error)
        this.pendingToolApproval = null
        // 出错也清黄点（用户已经提交了决定 = 状态解除）
        this.markSessionApprovalResolved(sessionId)
      } finally {
        this.submittingToolDecision = false
        // resume 流无论成功 / 异常都已结束，清掉 in-flight 标志恢复发送按钮
        this.permissionResumeInFlight = false
      }
    },
    /**
     * 处理 /permission/resume 端点的 SSE 流，沿用偏好 20 的 handleResume 模式：
     *   - 注册 snapshot 三件套 + startStreamTimer（用户切走不丢增量）
     *   - SSE 循环 sessionChanged + in-session 双分支
     *   - 终态用 wasError 守护 + updateTitleAndRefresh / updateTitleOnly
     *   - buffer-tail 兜底
     */
    async handlePermissionResumeStream(response) {
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      // 锁定发起 resume 时的 session id（用户切走要按原始 sid 处理）
      const requestSessionId = this.currentSessionId
      let buffer = ''
      // 找到/创建 AI 消息（与 handleResume 一致）
      let aiMessageIndex = -1
      for (let i = this.messages.length - 1; i >= 0; i--) {
        if (this.messages[i].role === 'ai') {
          aiMessageIndex = i
          break
        }
      }
      if (aiMessageIndex === -1) {
        aiMessageIndex = this.messages.length
        this.messages.push({
          role: 'ai', content: '', streaming: true, thinkingDone: false,
          responseStartTime: Date.now(), toolCalls: [],
        })
      } else {
        this.messages[aiMessageIndex] = {
          ...this.messages[aiMessageIndex],
          streaming: true, thinkingDone: false, responseStartTime: Date.now(),
        }
      }
      this.currentAiMessageIndex = aiMessageIndex
      this.isLoading = true
      this.startResponseTimer()
      this.hasReceivedInit = true
      // 预先取最后一个用户消息，给 error/done 兜底分支用
      const lastUserMessage = this.messages.filter(m => m.role === 'user').pop()?.content || ''
      // 注册流式会话快照三件套（用户切走时 SSE 增量写到 snapshot，切回时直接恢复 this.messages）
      this._activeStreamingSessions.add(requestSessionId)
      this._streamingMessages.set(requestSessionId, this.messages)
      this._streamingMeta.set(requestSessionId, {
        aiIndex: aiMessageIndex,
        responseStartTime: this.responseStartTime,
        userMessage: lastUserMessage,
        lastUserMessage,
      })
      this.startStreamTimer(requestSessionId, this.messages[aiMessageIndex])
      this._activeStreamingSessions = new Set(this._activeStreamingSessions)
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let idx
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const raw = buffer.slice(0, idx)
            buffer = buffer.slice(idx + 2)
            const line = raw.trim()
            if (!line) continue
            try {
              const data = JSON.parse(line)
              const sessionChanged = this.currentSessionId !== requestSessionId

              // ---- sessionChanged 分支（写 snapshot，与 handleResume 完全同构）----
              if (sessionChanged) {
                const snap = this._streamingMessages.get(requestSessionId)
                const meta = this._streamingMeta.get(requestSessionId)
                if (snap && meta) {
                  if (data.type === 'content') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: snap[meta.aiIndex].content + data.content,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime,
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'reasoning') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      reasoning: snap[meta.aiIndex].reasoning + data.content,
                      responseTime: this.currentResponseTime,
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_name') {
                    snap[meta.aiIndex] = this.mergeToolCallStart(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_result') {
                    snap[meta.aiIndex] = this.mergeToolCallResult(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'done') {
                    this.stopResponseTimer()
                    const wasError = snap[meta.aiIndex]?.error === true
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      role: 'ai',
                      content: wasError ? snap[meta.aiIndex].content : (data.full_response ?? snap[meta.aiIndex].content),
                      reasoning: snap[meta.aiIndex].reasoning,
                      toolCalls: snap[meta.aiIndex].toolCalls,
                      thinkingDone: true,
                      streaming: false,
                      responseTime: this.currentResponseTime,
                      checkpointId: data.checkpoint_id || null,
                      error: wasError || undefined,
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    // 绿点：clean done 才标记（已计算 wasError）
                    if (!wasError) this.markSessionCompleted(requestSessionId)
                    // 已切走：仅更新侧栏标题，不重拉 messages（避免覆盖快照）
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, lastUserMessage)
                    }
                  } else if (data.type === 'error') {
                    this._sessionHadError.add(requestSessionId)
                    this.markSessionErrored(requestSessionId)
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: `resume 失败：${data.error}`,
                      error: true,
                      errorMessage: data.error,
                      streaming: false,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime,
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, lastUserMessage)
                    }
                  } else if (data.type === 'interrupt') {
                    this.stopResponseTimer()
                    const reason = data.reason || '用户主动中断'
                    snap[meta.aiIndex] = { ...snap[meta.aiIndex], streaming: false, interruptReason: reason }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, lastUserMessage)
                    }
                  } else if (data.type === 'permission_request') {
                    this.handlePermissionRequest(data, requestSessionId)
                  }
                }
                continue
              }

              // ---- in-session 分支（写 this.messages[aiIndex]，与 handleResume 完全同构）----
              if (data.type === 'init') {
                this.hasReceivedInit = true
                if (data.session_id) this._pendingInterruptSessionId = data.session_id
              } else if (data.type === 'content') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: this.messages[aiMessageIndex].content + data.content,
                  thinkingDone: true,
                  responseTime: this.currentResponseTime,
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: (this.messages[aiMessageIndex].reasoning || '') + data.content,
                  responseTime: this.currentResponseTime,
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_name') {
                this.messages[aiMessageIndex] = this.mergeToolCallStart(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_result') {
                this.messages[aiMessageIndex] = this.mergeToolCallResult(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'done') {
                this.stopResponseTimer()
                this.messages[aiMessageIndex] = {
                  role: 'ai',
                  content: data.full_response ?? this.messages[aiMessageIndex].content,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: this.currentResponseTime,
                  checkpointId: data.checkpoint_id || null,
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                // 当前会话：调 updateTitleAndRefresh（更新标题 + 刷侧栏）
                await this.updateTitleAndRefresh(this.currentSessionId, lastUserMessage)
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                // 绿点：in-session done
                this.markSessionCompleted(requestSessionId)
              } else if (data.type === 'error') {
                this.stopResponseTimer()
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: `resume 失败：${data.error}`,
                  error: true,
                  errorMessage: data.error,
                  streaming: false,
                  thinkingDone: true,
                  responseTime: this.currentResponseTime,
                }
                this._sessionHadError.add(this.currentSessionId)
                this.markSessionErrored(requestSessionId)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                // 错误路径：updateTitleOnly（仅更新标题，不重拉 messages，避免错误气泡被覆盖）
                if (this.currentSessionId) {
                  await this.updateTitleOnly(this.currentSessionId, lastUserMessage)
                }
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              } else if (data.type === 'interrupt') {
                this.stopResponseTimer()
                const reason = data.reason || '用户主动中断'
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  streaming: false,
                  interruptReason: reason,
                  responseTime: this.currentResponseTime,
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                this.isInterrupted = true
                this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
                this.interruptReason = reason
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              } else if (data.type === 'permission_request') {
                this.handlePermissionRequest(data, requestSessionId)
              }
            } catch (e) {
              console.error('permission resume SSE parse error:', e, 'raw:', line)
            }
          }
        }

        // buffer-tail 兜底（流关闭后剩余 buffer 同处理，与 handleResume 同构）
        if (buffer.trim()) {
          try {
            const data = JSON.parse(buffer.trim())
            const sessionChanged = this.currentSessionId !== requestSessionId
            if (sessionChanged) {
              const snap = this._streamingMessages.get(requestSessionId)
              const meta = this._streamingMeta.get(requestSessionId)
              if (snap && meta) {
                if (data.type === 'content') {
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    content: snap[meta.aiIndex].content + data.content,
                    thinkingDone: true,
                    responseTime: this.currentResponseTime,
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'reasoning') {
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    reasoning: snap[meta.aiIndex].reasoning + data.content,
                    responseTime: this.currentResponseTime,
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'tool_call_name') {
                  snap[meta.aiIndex] = this.mergeToolCallStart(snap[meta.aiIndex], data)
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'tool_call_result') {
                  snap[meta.aiIndex] = this.mergeToolCallResult(snap[meta.aiIndex], data)
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'done') {
                  this.stopResponseTimer()
                  const wasError = snap[meta.aiIndex]?.error === true
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    role: 'ai',
                    content: wasError ? snap[meta.aiIndex].content : (data.full_response ?? snap[meta.aiIndex].content),
                    reasoning: snap[meta.aiIndex].reasoning,
                    toolCalls: snap[meta.aiIndex].toolCalls,
                    thinkingDone: true,
                    streaming: false,
                    responseTime: this.currentResponseTime,
                    checkpointId: data.checkpoint_id || null,
                    error: wasError || undefined,
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                  this.stopStreamTimer(requestSessionId)
                  this._activeStreamingSessions.delete(requestSessionId)
                  this._streamingMessages.delete(requestSessionId)
                  this._streamingMeta.delete(requestSessionId)
                  this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                  // 绿点：buffer-tail sessionChanged done（已计算 wasError）
                  if (!wasError) this.markSessionCompleted(requestSessionId)
                  if (requestSessionId) {
                    await this.updateTitleOnly(requestSessionId, lastUserMessage)
                  }
                } else if (data.type === 'error') {
                  this._sessionHadError.add(requestSessionId)
                  this.markSessionErrored(requestSessionId)
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    content: `resume 失败：${data.error}`,
                    error: true,
                    errorMessage: data.error,
                    streaming: false,
                    thinkingDone: true,
                    responseTime: this.currentResponseTime,
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                  this.stopStreamTimer(requestSessionId)
                  this._activeStreamingSessions.delete(requestSessionId)
                  this._streamingMessages.delete(requestSessionId)
                  this._streamingMeta.delete(requestSessionId)
                  this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                  if (requestSessionId) {
                    await this.updateTitleOnly(requestSessionId, lastUserMessage)
                  }
                } else if (data.type === 'permission_request') {
                  this.handlePermissionRequest(data, requestSessionId)
                }
              }
            } else if (data.type === 'reasoning') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                reasoning: (this.messages[aiMessageIndex].reasoning || '') + data.content,
                responseTime: this.currentResponseTime,
              }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'tool_call_name') {
              this.messages[aiMessageIndex] = this.mergeToolCallStart(this.messages[aiMessageIndex], data)
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'tool_call_result') {
              this.messages[aiMessageIndex] = this.mergeToolCallResult(this.messages[aiMessageIndex], data)
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'content') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                content: this.messages[aiMessageIndex].content + data.content,
                thinkingDone: true,
                responseTime: this.currentResponseTime,
              }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
            } else if (data.type === 'done') {
              this.stopResponseTimer()
              this.messages[aiMessageIndex] = {
                role: 'ai',
                content: data.full_response ?? this.messages[aiMessageIndex].content,
                reasoning: this.messages[aiMessageIndex].reasoning,
                toolCalls: this.messages[aiMessageIndex].toolCalls,
                thinkingDone: true,
                streaming: false,
                responseTime: this.currentResponseTime,
                checkpointId: data.checkpoint_id || null,
              }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              await this.updateTitleAndRefresh(this.currentSessionId, lastUserMessage)
              this.stopStreamTimer(requestSessionId)
              this._activeStreamingSessions.delete(requestSessionId)
              this._streamingMessages.delete(requestSessionId)
              this._streamingMeta.delete(requestSessionId)
              this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              // 绿点：buffer-tail in-session done
              this.markSessionCompleted(requestSessionId)
            } else if (data.type === 'interrupt') {
              this.stopResponseTimer()
              const reason = data.reason || '用户主动中断'
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                streaming: false,
                interruptReason: reason,
                responseTime: this.currentResponseTime,
              }
              this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              this.isInterrupted = true
              this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
              this.interruptReason = reason
              this.stopStreamTimer(requestSessionId)
              this._activeStreamingSessions.delete(requestSessionId)
              this._streamingMessages.delete(requestSessionId)
              this._streamingMeta.delete(requestSessionId)
              this._activeStreamingSessions = new Set(this._activeStreamingSessions)
            } else if (data.type === 'permission_request') {
              this.handlePermissionRequest(data, requestSessionId)
            }
          } catch (e) {
            console.error('解析 buffer 剩余数据失败:', e)
          }
        }
      } catch (error) {
        console.error('permission resume stream error:', error)
      } finally {
        this.isLoading = false
        this.stopResponseTimer()
      }
    },
    async handleRestream(checkpointId, aiMessage) {
      // 防止重复点击
      if (this.isRestreaming) {
        return
      }
      this.isRestreaming = true

      // 清理中断状态（重新对话会发起新请求，不应继承之前的中断状态）
      this.isInterrupted = false
      this.isInterruptedSessionId = null

      // 如果没有传入 aiMessage，直接返回
      if (!aiMessage) {
        return
      }

      // 找到对应消息的索引
      const aiIndex = this.messages.findIndex(
        (msg, idx) => msg === aiMessage
      )
      if (aiIndex === -1) {
        return
      }

      // 获取当前标题
      const currentTitle = this.conversations.find(c => c.session_id === this.currentSessionId)?.title || '新对话'

      // 获取 checkpoint：
      // 1. 优先使用 last_checkpoint_id
      // 2. 如果没有，fallback 到上一轮 AI 消息的 checkpointId
      let restreamCheckpointId = aiMessage.additional_kwargs?.last_checkpoint_id
      if (!restreamCheckpointId) {
        // 找上一轮 AI 消息
        for (let i = aiIndex - 1; i >= 0; i--) {
          if (this.messages[i].role === 'ai') {
            restreamCheckpointId = this.messages[i].checkpointId || null
            if (restreamCheckpointId) {
              break
            }
          }
        }
      }
      if (!restreamCheckpointId) {
        return
      }

      // 检查是否是最新一轮对话
      let latestAiIndex = this.messages.length - 1
      while (latestAiIndex >= 0 && this.messages[latestAiIndex].role !== 'ai') {
        latestAiIndex--
      }
      if (aiIndex !== latestAiIndex) {
        console.error('只能对最新一轮对话进行重新对话')
        this.isRestreaming = false
        return
      }

      // 找到用户消息，保存 content 和 files
      // 注意：flattenedMessages 可能将用户消息拆分为文件消息(_isFilesOnly)和文本消息(_isTextOnly)
      // 需要找到包含 files 的那个消息
      let userMessageIndex = aiIndex - 1
      let userMessage = null
      let restreamMessage = ''
      let restreamProcessedOutputs = []

      // 向前查找用户消息
      while (userMessageIndex >= 0) {
        const msg = this.messages[userMessageIndex]
        if (msg.role === 'user') {
          // 优先找有文件的消息
          if (msg.files && msg.files.length > 0) {
            userMessage = msg
            restreamProcessedOutputs = msg.files || []
            // 尝试找相邻的文本消息（content 有内容且没有文件）
            if (userMessageIndex + 1 < this.messages.length &&
                this.messages[userMessageIndex + 1].role === 'user' &&
                !this.messages[userMessageIndex + 1].files?.length &&
                this.messages[userMessageIndex + 1].content?.trim()) {
              restreamMessage = (this.messages[userMessageIndex + 1].content || '').trim()
            } else {
              restreamMessage = (msg.content || '').trim()
            }
            break
          }
          // 如果消息没有文件但有内容（纯文本消息），继续往前找文件消息
          if (msg.content && msg.content.trim() && (!msg.files || msg.files.length === 0)) {
            restreamMessage = (msg.content || '').trim()
            // 往前找一个有 files 的消息
            let fileMsgIndex = userMessageIndex - 1
            while (fileMsgIndex >= 0) {
              const fileMsg = this.messages[fileMsgIndex]
              if (fileMsg.role === 'user' && fileMsg.files && fileMsg.files.length > 0) {
                userMessage = fileMsg
                restreamProcessedOutputs = fileMsg.files || []
                break
              }
              if (fileMsg.role === 'user' && fileMsg.content && fileMsg.content.trim()) {
                // 遇到有内容的用户消息停止
                break
              }
              fileMsgIndex--
            }
            if (userMessage) break
            // 如果没找到文件消息，使用当前的纯文本消息
            userMessage = msg
            restreamProcessedOutputs = []
            break
          }
        }
        userMessageIndex--
      }

      if (!userMessage) {
        return
      }

      const requestSessionId = this.currentSessionId

      try {
        // 1. 调用 backtrack API
        const backtrackResponse = await fetch(`/chat/${requestSessionId}/backtrack`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            backtrack_id: restreamCheckpointId
          })
        })

        if (!backtrackResponse.ok) {
          throw new Error('回溯失败')
        }

        // 2. 调用 get_conversation 获取回溯后的历史消息
        const convResponse = await fetch(`/chat/${requestSessionId}/conversation`)
        if (!convResponse.ok) {
          throw new Error('获取回溯后状态失败')
        }
        const conversation = await convResponse.json()
        this.$refs.messageList?.suppressNextScroll()
        this.messages = this.processConversationMessages(conversation.messages)
        // 同步文件树（AI 回溯后 cached 下的文件可能变化）
        this.$refs.dataAnalysisTree?.reload()

        // 3. 清除中断状态（backtrack 后后端已清除，前端保持同步）
        if (conversation.interrupted_info?.reason) {
          this.isInterrupted = true
          this.isInterruptedSessionId = requestSessionId
          this.interruptReason = conversation.interrupted_info.reason
          const lastAiMsg = this.messages.filter(m => m.role === 'ai').pop()
          if (lastAiMsg) lastAiMsg.interruptReason = conversation.interrupted_info.reason
        } else {
          this.isInterrupted = false
          this.isInterruptedSessionId = null
          this.interruptReason = ''
        }

        // 4. 将用户消息添加回 messages（backtrack 后的对话不包含当前输入）
        // 注意：文件消息和文本消息分开推送，与 sendMessage 保持一致
        if (restreamProcessedOutputs.length > 0) {
          this.messages.push({
            role: 'user',
            content: '',
            files: restreamProcessedOutputs,
            additional_kwargs: { is_file: true }
          })
        }
        if (restreamMessage) {
          this.messages.push({
            role: 'user',
            content: restreamMessage,
            files: [],
            additional_kwargs: {}
          })
        }

        // 5. 添加 AI 消息占位
        this.isLoading = true
        this.currentResponseTime = 0

        const aiMessageIndex = this.messages.length

        this.messages.push({
          role: 'ai',
          content: '',
          reasoning: '',
          toolCalls: [],
          thinkingDone: false,
          streaming: true,
          responseTime: 0
        })

        this.startResponseTimer()
        this.$refs.messageList?.scrollToBottom({ force: true })

        // —— 注册流式会话快照（行为同 sendMessage）——
        this._activeStreamingSessions.add(requestSessionId)
        this._streamingMessages.set(requestSessionId, this.messages)
        this._streamingMeta.set(requestSessionId, {
          aiIndex: aiMessageIndex,
          responseStartTime: this.responseStartTime,
          userMessage: restreamMessage,
          lastUserMessage: restreamMessage
        })
        this.startStreamTimer(this.currentSessionId, this.messages[aiMessageIndex])
        this._activeStreamingSessions = new Set(this._activeStreamingSessions)

        // 5. 调用 message_stream
        const streamResponse = await fetch('/chat/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            message: restreamMessage,
            session_id: requestSessionId,
            processed_outputs: restreamProcessedOutputs
          })
        })

        if (!streamResponse.ok) {
          throw new Error(`请求失败: ${streamResponse.status}`)
        }

        const reader = streamResponse.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''

          for (const part of parts) {
            const line = part.trim()
            if (!line) continue

            try {
              const data = JSON.parse(line)

              // sessionChanged 分支：restream 时如果用户切走，增量写到 snapshot
              const sessionChanged = this.currentSessionId !== requestSessionId
              if (sessionChanged) {
                const snap = this._streamingMessages.get(requestSessionId)
                const meta = this._streamingMeta.get(requestSessionId)
                if (snap && meta) {
                  if (data.type === 'content') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: snap[meta.aiIndex].content + data.content,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'reasoning') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      reasoning: snap[meta.aiIndex].reasoning + data.content,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_name') {
                    snap[meta.aiIndex] = this.mergeToolCallStart(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_result') {
                    snap[meta.aiIndex] = this.mergeToolCallResult(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'done') {
                    this.stopResponseTimer()
                    const wasError = snap[meta.aiIndex]?.error === true
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      role: 'ai',
                      content: wasError ? snap[meta.aiIndex].content : data.full_response,
                      reasoning: snap[meta.aiIndex].reasoning,
                      toolCalls: snap[meta.aiIndex].toolCalls,
                      thinkingDone: true,
                      streaming: false,
                      responseTime: this.currentResponseTime,
                      checkpointId: data.checkpoint_id || null,
                      error: wasError || undefined
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    // 绿点：clean done 才标记（已计算 wasError）
                    if (!wasError) this.markSessionCompleted(requestSessionId)
                    // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, restreamMessage)
                    }
                  } else if (data.type === 'error') {
                    this._sessionHadError.add(requestSessionId)
                    this.markSessionErrored(requestSessionId)
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: `重新对话失败：${data.error}`,
                      error: true,
                      errorMessage: data.error,
                      streaming: false,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, restreamMessage)
                    }
                  } else if (data.type === 'interrupt') {
                    this.stopResponseTimer()
                    const reason = data.reason || '用户主动中断'
                    snap[meta.aiIndex] = { ...snap[meta.aiIndex], streaming: false, interruptReason: reason }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, restreamMessage)
                    }
                  } else if (data.type === 'permission_request') {
                    this.handlePermissionRequest(data, requestSessionId)
                  }
                }
                continue
              }

              if (data.type === 'init') {
                this.hasReceivedInit = true
                if (data.session_id) {
                  this._pendingInterruptSessionId = data.session_id
                }
              } else if (data.type === 'content') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: this.messages[aiMessageIndex].content + data.content,
                  thinkingDone: true,
                  responseTime: this.currentResponseTime
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_name') {
                this.messages[aiMessageIndex] = this.mergeToolCallStart(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_result') {
                this.messages[aiMessageIndex] = this.mergeToolCallResult(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'done') {
                this.stopResponseTimer()
                this.messages[aiMessageIndex] = {
                  role: 'ai',
                  content: data.full_response,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: this.currentResponseTime,
                  checkpointId: data.checkpoint_id || null
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)

                // 恢复标题
                if (currentTitle && currentTitle !== '新对话' && requestSessionId) {
                  await this.updateConversationTitle({ sessionId: requestSessionId, title: currentTitle })
                }

                // 4. 最后刷新会话
                await this.refreshCurrentConversation()
                // 清理快照
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                // 绿点：handleRestream in-session done
                this.markSessionCompleted(requestSessionId)
              } else if (data.type === 'interrupt') {
                this.stopResponseTimer()
                const reason = data.reason || '用户主动中断'
                this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], streaming: false, interruptReason: reason }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                this.isInterrupted = true
                this.isInterruptedSessionId = data.session_id || requestSessionId || this._pendingInterruptSessionId
                this.interruptReason = reason
                // 清理快照
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              } else if (data.type === 'permission_request') {
                this.handlePermissionRequest(data, requestSessionId)
              }
            } catch (e) {
              console.error('解析消息失败:', e)
            }
          }

          this.$refs.messageList?.scrollToBottom({ force: true })
        }
      } catch (error) {
        console.error('重新对话失败:', error)
      } finally {
        this.isLoading = false
        this.isRestreaming = false
      }
    },
    async confirmRestore() {
      if (!this.restoreTargetId || !this.currentSessionId) return

      try {
        const response = await fetch(`/chat/${this.currentSessionId}/backtrack`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            backtrack_id: this.restoreTargetId
          })
        })

        if (response.ok) {
          // 重新加载对话界面
          const convResponse = await fetch(`/chat/${this.currentSessionId}/conversation`)
          if (convResponse.ok) {
            const conversation = await convResponse.json()
            this.$refs.messageList?.suppressNextScroll()
            this.messages = this.processConversationMessages(conversation.messages)
            // 同步文件树（恢复检查点后 cached 下的文件可能变化）
            this.$refs.dataAnalysisTree?.reload()

            // 清除中断状态（后端已清除，前端保持同步）
            if (conversation.interrupted_info?.reason) {
              this.isInterrupted = true
              this.isInterruptedSessionId = this.currentSessionId
              this.interruptReason = conversation.interrupted_info.reason
              const lastAiMsg = this.messages.filter(m => m.role === 'ai').pop()
              if (lastAiMsg) lastAiMsg.interruptReason = conversation.interrupted_info.reason
            } else {
              this.isInterrupted = false
              this.isInterruptedSessionId = null
              this.interruptReason = ''
            }
          }
          this.showCheckpoints = false
        } else {
          console.error('恢复检查点失败')
        }
      } catch (error) {
        console.error('恢复检查点失败:', error)
      } finally {
        this.showRestoreConfirm = false
        this.restoreTargetId = null
      }
    },
    cancelRestore() {
      this.showRestoreConfirm = false
      this.restoreTargetId = null
    },
    async loadConversations() {
      try {
        const response = await fetch('/chat/conversations')
        if (response.ok) {
          const data = await response.json()
          // 后端返回完整会话列表，前端一次性展示，CSS 溢出时显示滚动条
          this.conversations = data
          this.conversationsLoadError = ''
        } else {
          // 非 2xx：留个话到 UI 提示用户「后端没起」/「端口被占」等常见原因（否则静默失败用户一脸懵）
          this.conversationsLoadError = `HTTP ${response.status} ${response.statusText}`
          console.warn('[conversations] 接口返回非 OK:', this.conversationsLoadError)
        }
      } catch (error) {
        // 网络层失败（CORS / fetch 本身失败 / JSON 解析错误）—— 静默吞 console 用户看不到
        this.conversationsLoadError = error?.message || '网络请求失败'
        console.error('加载对话列表失败:', error)
      }
    },
    createNewChat() {
      // 关闭 SSE 连接，停止接收任何流式事件
      if (this.eventSource) {
        this.eventSource.close()
        this.eventSource = null
      }
      // 清理正在加载的状态
      this.cleanupLoadingState()
      // 清理输入框和文件
      this.$refs.messageInput?.clearInput()

      this.clearFilePreviewTabs()
      this.currentSessionId = null
      this.messages = []
      // 清理引用状态
      this.currentQuote = null
      // 清理中断状态
      this.isInterrupted = false
      this.isInterruptedSessionId = null
      // 更新 URL 到根路径
      if (this.$route.path !== '/') {
        this.$router.push('/')
      }
    },
    cleanupLoadingState() {
      // 停止计时器
      this.stopResponseTimer()

      // ⚠️ 不要 pop 流式 AI 消息：
      //   _streamingMessages 与 this.messages 是引用同源，pop 会污染 snapshot，
      //   导致后续 SSE 切走分支写到错位的 aiIndex 上。
      // - 切到非流式会话：this.messages 会被 loadConversation 整体替换
      // - 切到流式会话：this.messages = snapshot（自带 in-progress AI 消息）
      // - createNewChat：this.messages = []
      // - confirmDelete：当前会话被删除
      // 三条路径下原 pop 都多余且有害。

      this.isLoading = false
      this.isRestreaming = false
      this.currentAiMessageIndex = null
    },
    async loadConversation(sessionId) {
      // 防止加载无效的 sessionId
      if (!sessionId || sessionId.trim() === '') {
        return
      }

      // 移动端选择会话后关闭侧边栏
      if (this.isMobile) {
        this.closeMobileSidebar()
      }

      // 防止重复加载同一个会话
      if (sessionId === this.currentSessionId && this.messages.length > 0) {
        return
      }

      // 切换会话时清理旧会话文件标签，避免跨 session 混用路径和内容
      if (this.currentSessionId && this.currentSessionId !== sessionId) {
        this.clearFilePreviewTabs()
      }

      // —— 检查目标会话是否正在流式响应 —— 是的话走 snapshot 恢复分支
      const isTargetStreaming = this._activeStreamingSessions.has(sessionId)
      const snapshot = this._streamingMessages.get(sessionId)
      const meta = this._streamingMeta.get(sessionId)

      if (!isTargetStreaming) {
        // 切到非流式会话：清理旧状态
        this.cleanupLoadingState()
        // 用户进入会话 = "看到了完成 / 错误结果"，清绿/红点（在 fetch 之前做，避免 fetch 期间新 done 事件被错误清除的竞态）
        // 不清 _approvalPendingSessions（用户可能只是切进去看，审批待办还要保留）
        // 不清 _sessionHadError（UI 保护职责与显示无关）
        this._completedSessions.delete(sessionId)
        this._completedSessions = new Set(this._completedSessions)
        this._errorSessions.delete(sessionId)
        this._errorSessions = new Set(this._errorSessions)
        // 清理输入框和文件
        this.$refs.messageInput?.clearInput()
        // 清理引用状态
        this.currentQuote = null
      }
      // 切到流式会话：不调 cleanupLoadingState，保留 isLoading=true + 当前 responseTimer + 计时基准
      // 流式中的会话不会有绿/红点（流式接管视觉），无需清除

      this.currentSessionId = sessionId
      if (this.$route.params.sessionId !== sessionId) {
        this.$router.push(`/${sessionId}`)
      }

      if (isTargetStreaming && snapshot) {
        // —— 恢复流式状态（不走 get_conversation，否则会覆盖 in-progress 消息）——
        this.messages = snapshot
        this.isLoading = true
        if (meta) {
          this.currentAiMessageIndex = meta.aiIndex
          this.responseStartTime = meta.responseStartTime
          // 重启 timer 用同一个 responseStartTime（让 currentResponseTime 继续推进）
          this.startResponseTimer()
        }
        // 流式中的会话不应该处于中断态，但保险起见清掉
        this.isInterrupted = false
        this.isInterruptedSessionId = null
        this.interruptReason = ''
      } else {
        try {
          const response = await fetch(`/chat/${sessionId}/conversation`)
          if (response.ok) {
            const conversation = await response.json()
            this.messages = this.processConversationMessages(conversation.messages)

            // 检查是否处于中断状态（interrupted_info 存在表示有中断原因）
            const interruptedReason = conversation.interrupted_info?.reason
            if (interruptedReason) {
              this.isInterrupted = true
              this.isInterruptedSessionId = sessionId
              this.interruptReason = interruptedReason
              // 将中断原因写入最后一条 AI 消息
              const lastAiMsg = this.messages.filter(m => m.role === 'ai').pop()
              if (lastAiMsg) {
                lastAiMsg.interruptReason = interruptedReason
              }
            } else {
              this.isInterrupted = false
              this.isInterruptedSessionId = null
              this.interruptReason = ''
            }

            // 同步 pending tool approval —— F5 / 刷新会话后立刻高亮对应 tool + 内嵌审批按钮，
            // 不必等 SSE 流连上来才看到
            if (conversation.pending_permission) {
              this.handlePermissionRequest({
                session_id: sessionId,
                command: conversation.pending_permission.command,
                action: conversation.pending_permission.action,
                tool_call_name: conversation.pending_permission.tool_call_name,  // 让幂等去重守卫生效
              }, sessionId)
            }
          } else if (response.status === 404) {
            // 会话不存在（可能是新会话通过 URL 进入），当作新会话处理
            this.messages = []
          }
        } catch (error) {
          console.error('加载对话失败:', error)
        }
      }
    },

    // 静默刷新消息内容，不触发自动滚动（用于对话结束后同步 checkpointId）
    async refreshMessagesOnly() {
      if (!this.currentSessionId) return
      try {
        const response = await fetch(`/chat/${this.currentSessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()
          this.$refs.messageList?.suppressNextScroll()
          this.messages = this.processConversationMessages(conversation.messages)
          // 同步文件树
          this.$refs.dataAnalysisTree?.reload()
          // 同步中断状态
          const reason = conversation.interrupted_info?.reason
          if (reason) {
            this.isInterrupted = true
            this.isInterruptedSessionId = this.currentSessionId
            this.interruptReason = reason
            const lastAiMsg = this.messages.filter(m => m.role === 'ai').pop()
            if (lastAiMsg) lastAiMsg.interruptReason = reason
          } else {
            this.isInterrupted = false
            this.isInterruptedSessionId = null
            this.interruptReason = ''
          }
          // 同步 pending permission —— 用户在已加载会话上右键刷新也能立刻看到审批弹窗
          if (conversation.pending_permission) {
            this.handlePermissionRequest({
              session_id: this.currentSessionId,
              command: conversation.pending_permission.command,
              action: conversation.pending_permission.action,
              tool_call_name: conversation.pending_permission.tool_call_name,  // 让幂等去重守卫生效
            }, this.currentSessionId)
          }
        }
      } catch (error) {
        console.error('刷新消息失败:', error)
      }
    },
    // 右键刷新指定会话
    async refreshConversation(sessionId) {
      // 流式中的会话跳过 messages 重拉，避免覆盖 in-progress 状态（只刷侧栏）
      if (this._activeStreamingSessions.has(sessionId)) {
        console.log(`[流式保护] 跳过流式中会话的 messages 刷新: ${sessionId}`)
        await this.refreshSession(sessionId)
        return
      }
      try {
        // 出错保护态：跳过 messages 刷新，只更新侧边栏
        if (this._sessionHadError.has(sessionId)) {
          console.log(`[会话出错保护] 跳过会话刷新: ${sessionId}`)
          // 此时侧边栏的标题/时间已经在 loadConversations 拉过，无需再处理
          return
        }

        const response = await fetch(`/chat/${sessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()
          if (sessionId === this.currentSessionId) {
            // 如果是当前会话，静默刷新
            this.$refs.messageList?.suppressNextScroll()
            this.messages = this.processConversationMessages(conversation.messages)
            // 同步文件树
            this.$refs.dataAnalysisTree?.reload()
            // 同步中断状态
            const reason = conversation.interrupted_info?.reason
            if (reason) {
              this.isInterrupted = true
              this.isInterruptedSessionId = this.currentSessionId
              this.interruptReason = reason
              const lastAiMsg = this.messages.filter(m => m.role === 'ai').pop()
              if (lastAiMsg) lastAiMsg.interruptReason = reason
            } else {
              this.isInterrupted = false
              this.isInterruptedSessionId = null
              this.interruptReason = ''
            }
          }
          // 更新侧边栏的标题和时间
          const conv = this.conversations.find(c => c.session_id === sessionId)
          if (conv) {
            conv.title = conversation.title
            conv.updated_at = conversation.updated_at
          }
        }
      } catch (error) {
        console.error('刷新会话失败:', error)
      }
    },
    async deleteConversation(sessionId) {
      if (!sessionId) return

      const isDeletingCurrent = this.currentSessionId === sessionId

      // 只有删除当前会话时才关闭 SSE 和清理加载状态
      if (isDeletingCurrent) {
        if (this.eventSource) {
          this.eventSource.close()
          this.eventSource = null
        }
        this.cleanupLoadingState()
        this.createNewChat()
      }

      try {
        const response = await fetch(`/chat/${sessionId}/clear`, {
          method: 'DELETE'
        })
        if (response.ok) {
          this.conversations = this.conversations.filter(c => c.session_id !== sessionId)
        }
      } catch (error) {
        console.error('删除对话失败:', error)
      } finally {
        // 清理 snapshot 引用 + 读秒 timer（无论后端删除是否成功，前端不再持有该 session 的状态）
        this.stopStreamTimer(sessionId)
        this._activeStreamingSessions.delete(sessionId)
        this._streamingMessages.delete(sessionId)
        this._streamingMeta.delete(sessionId)
        this._activeStreamingSessions = new Set(this._activeStreamingSessions)
        // 清理侧栏状态点（防孤儿 ID；ConversationItem 已 unmount，渲染上看不到残留）
        this._completedSessions.delete(sessionId)
        this._completedSessions = new Set(this._completedSessions)
        this._approvalPendingSessions.delete(sessionId)
        this._approvalPendingSessions = new Set(this._approvalPendingSessions)
        this._errorSessions.delete(sessionId)
        this._errorSessions = new Set(this._errorSessions)
      }
    },
    async updateConversationTitle({ sessionId, title }) {
      try {
        const response = await fetch(`/chat/${sessionId}/title`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ title })
        })

        if (response.ok) {
          const conv = this.conversations.find(c => c.session_id === sessionId)
          if (conv) {
            conv.title = title
          }
        }
      } catch (error) {
        console.error('修改标题失败:', error)
      }
    },
    async sendMessage(data) {
      const message = typeof data === 'string' ? data : data.message
      const files = typeof data === 'object' ? data.files : []
      const processedOutputs = typeof data === 'object' ? data.processedOutputs : []

      // 构建文件消息（只包含 files 信息）
      if (files && files.length > 0) {
        const fileMessage = {
          role: 'user',
          content: '',
          additional_kwargs: { is_file: true },
          files: files.map((file, index) => {
            // 合并原始文件信息和处理结果
            const processed = processedOutputs && processedOutputs[index] ? processedOutputs[index] : {}
            // 直接使用后端返回的 OutputFormat 扁平结构
            const fileInfo = {
              name: file.name || file.file_name || file.filename || processed.name,
              size: file.size || file.file_size || 0,
              type: file.type || file.file_type || file.content_type || processed.type,
              preview: file.preview || file.preview_url || processed.preview || null,
              iframe_url: file.iframe_url || processed.iframe_url || null,
              content: file.content || processed.content || null,
              fileId: file.file_id || file.fileId || processed.file_id || null,
              file_type: file.type || file.file_type || processed.file_type || null,
              preview_method: file.preview_method || processed.preview_method || 'download',
              preview_hint: file.preview_hint || processed.preview_hint || null,
              size_human: file.size_human || file.file_size_human || processed.size_human || null,
              suffix: file.suffix || processed.suffix || null,
              is_previewable: file.is_previewable !== undefined ? file.is_previewable : (processed.is_previewable !== undefined ? processed.is_previewable : true),
              // 后端处理后的字段
              text_content: processed.text_content || null,
              image_content: processed.image_content || null,
              is_oss: processed.is_oss || false
            }

            // 如果没有 preview，图片类型则创建本地预览
            if (!fileInfo.preview && file.type && file.type.startsWith('image/')) {
              if (file.file) {
                try {
                  fileInfo.preview = URL.createObjectURL(file.file)
                } catch (e) {
                  console.warn('创建图片预览失败:', e)
                }
              }
            }

            return fileInfo
          })
        }
        this.messages.push(fileMessage)
      }

      // 构建文本消息（只包含用户输入的文本）
      if (message && message.trim()) {
        const textMessage = {
          role: 'user',
          content: message.trim(),
          additional_kwargs: {},
          files: []
        }
        this.messages.push(textMessage)
      }

      this.isLoading = true

      this.$refs.messageList?.scrollToBottom({ force: true })

      this.responseStartTime = Date.now()
      this.currentResponseTime = 0

      // 如果当前没有 sessionId，先创建并跳转到新会话页面，再发送请求
      if (!this.currentSessionId && !this.$route.params.sessionId) {
        const newSid = crypto.randomUUID().replace(/-/g, '').slice(0, 12)
        this.currentSessionId = newSid
        await this.$router.push(`/${newSid}`)
      }

      // 保存发起请求时的会话 ID，用于跟踪请求属于哪个会话
      // 优先使用 currentSessionId，回退到 URL path
      const requestSessionId = this.currentSessionId || this.$route.params.sessionId || ''

      // 用户主动发起新一轮请求 → 视为恢复，清掉旧错误保护态
      this._sessionHadError.delete(requestSessionId)
      this.markSessionErrorResolved(requestSessionId)

      // 立即把当前会话加入侧边栏顶部，让用户马上看到「最新对话」
      // 占位标题「新对话」会在 AI 回复后由 updateTitleAndRefresh 校正
      if (requestSessionId && !this.conversations.find(c => c.session_id === requestSessionId)) {
        this.conversations.unshift({
          session_id: requestSessionId,
          title: '新对话',
          updated_at: new Date().toISOString()
        })
      }

      try {
        const requestBody = {
          message: message,
          session_id: requestSessionId,
          processed_outputs: processedOutputs
        }

        console.log('发送 /chat/ 请求:', {
          message: message,
          session_id: requestSessionId || '',
          processed_outputs_count: processedOutputs?.length,
          processed_outputs: processedOutputs
        })

        const response = await fetch('/chat/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(requestBody)
        })

        if (!response.ok) {
          throw new Error(`请求失败: ${response.status} ${response.statusText}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()

        const aiMessageIndex = this.messages.length
        this.currentAiMessageIndex = aiMessageIndex
        this.messages.push({
          role: 'ai',
          content: '',
          reasoning: '',
          toolCalls: [],
          thinkingDone: false,
          streaming: true,
          responseTime: 0
        })

        this.startResponseTimer()

        // —— 注册流式会话快照（用户切走时 SSE 增量写到 snapshot，切回时直接恢复 this.messages）——
        this._activeStreamingSessions.add(requestSessionId)
        this._streamingMessages.set(requestSessionId, this.messages)
        this._streamingMeta.set(requestSessionId, {
          aiIndex: aiMessageIndex,
          responseStartTime: this.responseStartTime,
          userMessage: message,
          lastUserMessage: message
        })
        // 整 Set 替换一次触发子组件响应式（Vue 2 不监听 Set 内部变化）
        this.startStreamTimer(this.currentSessionId, this.messages[aiMessageIndex])
        this._activeStreamingSessions = new Set(this._activeStreamingSessions)

        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          const parts = buffer.split('\n\n')

          buffer = parts.pop() || ''

          for (const part of parts) {
            const line = part.trim()
            if (!line) continue

            try {
              const data = JSON.parse(line)
              console.log('[SSE Received] type:', data.type, 'currentSessionId:', this.currentSessionId, 'requestSessionId:', requestSessionId)

              // 检查用户是否已切换会话
              const sessionChanged = this.currentSessionId !== requestSessionId
              console.log('[SSE] sessionChanged:', sessionChanged)

              if (sessionChanged) {
                // 会话已切换：SSE 增量只写到 snapshot（不碰 this.messages，它是别的会话数组）
                const snap = this._streamingMessages.get(requestSessionId)
                const meta = this._streamingMeta.get(requestSessionId)
                if (snap && meta) {
                  if (data.type === 'content') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: snap[meta.aiIndex].content + data.content,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'reasoning') {
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      reasoning: snap[meta.aiIndex].reasoning + data.content,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_name') {
                    snap[meta.aiIndex] = this.mergeToolCallStart(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'tool_call_result') {
                    snap[meta.aiIndex] = this.mergeToolCallResult(snap[meta.aiIndex], data)
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                  } else if (data.type === 'done') {
                    this.stopResponseTimer()
                    const wasError = snap[meta.aiIndex]?.error === true
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      role: 'ai',
                      content: wasError ? snap[meta.aiIndex].content : data.full_response,
                      reasoning: snap[meta.aiIndex].reasoning,
                      toolCalls: snap[meta.aiIndex].toolCalls,
                      thinkingDone: true,
                      streaming: false,
                      responseTime: this.currentResponseTime,
                      checkpointId: data.checkpoint_id || null,
                      error: wasError || undefined
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    // 清理快照：小点消失；后续切回该会话走 get_conversation 拿后端最终态
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    // 绿点：clean done 才标记（已计算 wasError）
                    if (!wasError) this.markSessionCompleted(requestSessionId)
                    // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation（避免并发 N 个 done 时反复重拉）
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, message)
                    }
                  } else if (data.type === 'error') {
                    console.error('AI响应错误（原会话）:', data.error)
                    this._sessionHadError.add(requestSessionId)
                    this.markSessionErrored(requestSessionId)
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      content: `抱歉，出现了一些问题：${data.error}`,
                      error: true,
                      errorMessage: data.error,
                      streaming: false,
                      thinkingDone: true,
                      responseTime: this.currentResponseTime
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, meta.lastUserMessage || message)
                    }
                  } else if (data.type === 'interrupt') {
                    this.stopResponseTimer()
                    const reason = data.reason || '用户主动中断'
                    snap[meta.aiIndex] = {
                      ...snap[meta.aiIndex],
                      streaming: false,
                      interruptReason: reason
                    }
                    this.writeStreamMetrics(snap[meta.aiIndex], data)
                    this.stopStreamTimer(requestSessionId)
                    this._activeStreamingSessions.delete(requestSessionId)
                    this._streamingMessages.delete(requestSessionId)
                    this._streamingMeta.delete(requestSessionId)
                    this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                    // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation
                    if (requestSessionId) {
                      await this.updateTitleOnly(requestSessionId, message)
                    }
                  } else if (data.type === 'permission_request') {
                    this.handlePermissionRequest(data, requestSessionId)
                  }
                }
                continue
              }

              if (data.type === 'init') {
                // 收到 init 后标记，并存储 session_id
                this.hasReceivedInit = true
                if (data.session_id) {
                  this._pendingInterruptSessionId = data.session_id
                }
              } else if (data.type === 'content') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: this.messages[aiMessageIndex].content + data.content,
                  thinkingDone: true,
                  responseTime: this.currentResponseTime
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_name') {
                this.messages[aiMessageIndex] = this.mergeToolCallStart(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_result') {
                this.messages[aiMessageIndex] = this.mergeToolCallResult(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'done') {
                this.stopResponseTimer()
                const responseTime = this.currentResponseTime

                // 检查用户是否已切换到其他会话
                const sessionChanged = this.currentSessionId !== requestSessionId

                if (sessionChanged) {
                  console.log('会话已切换，跳过本地消息更新，请求归属会话:', requestSessionId)
                }

                // 防御：如果此前已标记 error，则 done 不能覆盖错误气泡
                const wasError = this.messages[aiMessageIndex]?.error === true
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  role: 'ai',
                  content: wasError ? this.messages[aiMessageIndex].content : data.full_response,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: responseTime,
                  checkpointId: data.checkpoint_id || null,
                  error: wasError || undefined
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                // 流式结束：清理快照（this.messages 与 snapshot 同源，下一次切换走 get_conversation）
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                // 绿点：in-session done（sendMessage）。仅在 clean 时标记，避免覆盖错误后又被错误 done 复活。
                if (!wasError) this.markSessionCompleted(requestSessionId)

                // 如果是新建会话（没有 session_id）
                if (!requestSessionId && data.session_id) {
                  // 更新为正确的 session_id
                  if (this.currentSessionId !== data.session_id) {
                    this.currentSessionId = data.session_id
                    if (this.$route.params.sessionId !== data.session_id) {
                      this.$router.push(`/${data.session_id}`)
                    }
                  }

                  if (this.currentSessionId) {
                    await this.updateTitleAndRefresh(this.currentSessionId, message)
                  }
                  // 清理本地存储的待上传文件信息
                  localStorage.removeItem('pendingSessionId')
                  sessionStorage.removeItem('pendingUploadFiles')
                  localStorage.removeItem('currentSessionId')
                } else if (!sessionChanged && this.currentSessionId) {
                  // 会话未切换，正常更新
                  await this.updateTitleAndRefresh(this.currentSessionId, message)
                } else if (sessionChanged && requestSessionId) {
                  // 会话已切换：只 PUT 标题到 server + 同步侧栏，不调 get_conversation
                  // （避免并发 N 个 done 时反复重拉，且确保 title 已落库）
                  console.log('更新请求归属的会话标题:', requestSessionId)
                  await this.updateTitleOnly(requestSessionId, message)
                }
              } else if (data.type === 'error') {
                console.error('AI响应错误:', data.error)
                this._sessionHadError.add(requestSessionId)
                this.markSessionErrored(requestSessionId)
                if (!sessionChanged) {
                  this.messages[aiMessageIndex] = {
                    ...this.messages[aiMessageIndex],
                    content: `抱歉，出现了一些问题：${data.error}`,
                    error: true,
                    errorMessage: data.error,
                    streaming: false,
                    thinkingDone: true,
                    responseTime: this.currentResponseTime
                  }
                  this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                }
                // 流式结束：清理快照
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                // 仅更新标题，不重拉 messages（保护错误气泡）
                if (requestSessionId) {
                  await this.updateTitleOnly(requestSessionId, message)
                }
              } else if (data.type === 'interrupt') {
                this.stopResponseTimer()
                const reason = data.reason || '用户主动中断'
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  streaming: false,
                  interruptReason: reason
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
                this.isInterrupted = true
                this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
                this.interruptReason = reason
                // 中断：清理快照（后端已落中断状态，下次切回走 get_conversation 看到完整中断态）
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
              } else if (data.type === 'permission_request') {
                this.handlePermissionRequest(data, requestSessionId)
              }
            } catch (e) {
              console.error('解析 SSE 消息失败:', e, '原始内容:', line)
            }
          }
        }

        if (buffer.trim()) {
          try {
            const data = JSON.parse(buffer.trim())
            const sessionChanged = this.currentSessionId !== requestSessionId

            if (sessionChanged) {
              // 会话已切换：把 buffer 尾部事件也应用到 snapshot
              const snap = this._streamingMessages.get(requestSessionId)
              const meta = this._streamingMeta.get(requestSessionId)
              if (snap && meta) {
                if (data.type === 'content') {
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    content: snap[meta.aiIndex].content + data.content,
                    thinkingDone: true,
                    responseTime: this.currentResponseTime
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'reasoning') {
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    reasoning: snap[meta.aiIndex].reasoning + data.content,
                    responseTime: this.currentResponseTime
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'tool_call_name') {
                  snap[meta.aiIndex] = this.mergeToolCallStart(snap[meta.aiIndex], data)
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'tool_call_result') {
                  snap[meta.aiIndex] = this.mergeToolCallResult(snap[meta.aiIndex], data)
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                } else if (data.type === 'done') {
                  const wasError = snap[meta.aiIndex]?.error === true
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    role: 'ai',
                    content: wasError ? snap[meta.aiIndex].content : data.full_response,
                    reasoning: snap[meta.aiIndex].reasoning,
                    toolCalls: snap[meta.aiIndex].toolCalls,
                    thinkingDone: true,
                    streaming: false,
                    responseTime: this.currentResponseTime,
                    checkpointId: data.checkpoint_id || null,
                    error: wasError || undefined
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                  this.stopStreamTimer(requestSessionId)
                  this._activeStreamingSessions.delete(requestSessionId)
                  this._streamingMessages.delete(requestSessionId)
                  this._streamingMeta.delete(requestSessionId)
                  this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                  // 绿点：buffer-tail sessionChanged done（已计算 wasError）
                  if (!wasError) this.markSessionCompleted(requestSessionId)
                  // 会话已切换：只 PUT 标题 + 同步侧栏，不调 get_conversation
                  if (requestSessionId) {
                    await this.updateTitleOnly(requestSessionId, message)
                  }
                } else if (data.type === 'error') {
                  console.error('AI响应错误（buffer，原会话）:', data.error)
                  this._sessionHadError.add(requestSessionId)
                  this.markSessionErrored(requestSessionId)
                  snap[meta.aiIndex] = {
                    ...snap[meta.aiIndex],
                    content: `抱歉，出现了一些问题：${data.error}`,
                    error: true,
                    errorMessage: data.error,
                    streaming: false,
                    thinkingDone: true,
                    responseTime: this.currentResponseTime
                  }
                  this.writeStreamMetrics(snap[meta.aiIndex], data)
                  this.stopStreamTimer(requestSessionId)
                  this._activeStreamingSessions.delete(requestSessionId)
                  this._streamingMessages.delete(requestSessionId)
                  this._streamingMeta.delete(requestSessionId)
                  this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                  if (requestSessionId) {
                    await this.updateTitleOnly(requestSessionId, message)
                  }
                } else if (data.type === 'permission_request') {
                  this.handlePermissionRequest(data, requestSessionId)
                }
              }
            } else {
              if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_name') {
                this.messages[aiMessageIndex] = this.mergeToolCallStart(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'tool_call_result') {
                this.messages[aiMessageIndex] = this.mergeToolCallResult(this.messages[aiMessageIndex], data)
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'content') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: this.messages[aiMessageIndex].content + data.content,
                  thinkingDone: true
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)
              } else if (data.type === 'done') {
                this.stopResponseTimer()
                const responseTime = this.currentResponseTime

                // 防御：如果此前已标记 error，则 done 不能覆盖错误气泡
                const wasError = this.messages[aiMessageIndex]?.error === true
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  role: 'ai',
                  content: wasError ? this.messages[aiMessageIndex].content : data.full_response,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: responseTime,
                  checkpointId: data.checkpoint_id || null,
                  error: wasError || undefined
                }
                this.writeStreamMetrics(this.messages[aiMessageIndex], data)

                if (!this.currentSessionId && data.session_id) {
                  this.currentSessionId = data.session_id

                  if (this.$route.params.sessionId !== data.session_id) {
                    this.$router.push(`/${data.session_id}`)
                  }
                }

                if (this.currentSessionId) {
                  await this.updateTitleAndRefresh(this.currentSessionId, message)
                }
                // 清理快照
                this.stopStreamTimer(requestSessionId)
                this._activeStreamingSessions.delete(requestSessionId)
                this._streamingMessages.delete(requestSessionId)
                this._streamingMeta.delete(requestSessionId)
                this._activeStreamingSessions = new Set(this._activeStreamingSessions)
                // 绿点：buffer-tail in-session done（已计算 wasError）
                if (!wasError) this.markSessionCompleted(requestSessionId)
              } else if (data.type === 'permission_request') {
                this.handlePermissionRequest(data, requestSessionId)
              }
            }
          } catch (e) {
            console.error('解析缓冲区剩余数据失败:', e)
          }
        }
      } finally {
        this.isLoading = false
        this.stopResponseTimer()
      }
    },
    async updateTitleOnly(sessionId, userMessage) {
      // 只更新会话标题（含侧边栏同步），不重拉 messages。
      // 出错后调用，避免覆盖前端的错误气泡。
      if (!sessionId || !userMessage) return
      const title = userMessage.substring(0, 12) + (userMessage.length > 12 ? '...' : '')
      try {
        await fetch(`/chat/${sessionId}/title`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title })
        })
      } catch (error) {
        console.error('更新标题失败:', error)
      }
      // 同步侧边栏
      const conv = this.conversations.find(c => c.session_id === sessionId)
      if (conv) {
        conv.title = title
      } else {
        // 新会话首次出现，插入侧边栏顶部（无 updated_at，用当前时间）
        this.conversations.unshift({
          session_id: sessionId,
          title,
          updated_at: new Date().toISOString()
        })
      }
    },
    async updateTitleAndRefresh(sessionId, userMessage) {
      // 1. 用用户消息更新标题
      const title = userMessage.substring(0, 12) + (userMessage.length > 12 ? '...' : '')
      try {
        await fetch(`/chat/${sessionId}/title`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title })
        })
      } catch (error) {
        console.error('更新标题失败:', error)
      }

      // 出错保护态：仅同步侧边栏标题，跳过 messages 刷新（避免覆盖错误气泡）
      if (this._sessionHadError.has(sessionId)) {
        console.log(`[会话出错保护] 跳过 messages 刷新: ${sessionId}`)
        const conv = this.conversations.find(c => c.session_id === sessionId)
        if (conv) {
          conv.title = title
        } else {
          this.conversations.unshift({
            session_id: sessionId,
            title,
            updated_at: new Date().toISOString()
          })
        }
        return
      }

      // 2. 获取最新对话内容（含更新后的标题 + 历史记录）
      try {
        const response = await fetch(`/chat/${sessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()
          // 静默刷新消息，不触发自动滚动
          this.$refs.messageList?.suppressNextScroll()
          this.messages = this.processConversationMessages(conversation.messages)
          // 同步工作树（AI 跑完一轮可能新写文件到 cached/{sid}/ 任意位置，包括 data_analysis/ 子目录之外的中间产物）
          this.$refs.dataAnalysisTree?.reload()
          // 同步侧边栏标题和更新时间
          const conv = this.conversations.find(c => c.session_id === sessionId)
          if (conv) {
            conv.title = conversation.title
            conv.updated_at = conversation.updated_at
          } else {
            // 新对话首次出现，插入侧边栏顶部
            this.conversations.unshift({
              session_id: sessionId,
              title: conversation.title,
              updated_at: conversation.updated_at
            })
          }
        }
      } catch (error) {
        console.error('刷新对话失败:', error)
      }
    },
    async refreshCurrentConversation() {
      if (!this.currentSessionId) return

      // 出错保护态：跳过刷新（避免覆盖错误气泡）
      if (this._sessionHadError.has(this.currentSessionId)) {
        console.log(`[会话出错保护] 跳过当前会话刷新: ${this.currentSessionId}`)
        return
      }

      try {
        const response = await fetch(`/chat/${this.currentSessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()

          this.$refs.messageList?.suppressNextScroll()
          this.messages = this.processConversationMessages(conversation.messages)
          // 同步文件树
          this.$refs.dataAnalysisTree?.reload()

          // 更新侧边栏中的对话时间
          const conv = this.conversations.find(c => c.session_id === this.currentSessionId)
          if (conv && conversation.updated_at) {
            conv.updated_at = conversation.updated_at
          }
        }
      } catch (error) {
        console.error('刷新当前对话失败:', error)
      }
    },
    // 静默刷新指定会话，不更新当前显示的消息
    async refreshSession(sessionId) {
      if (!sessionId) return

      try {
        const response = await fetch(`/chat/${sessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()

          // 更新侧边栏中的对话时间
          const conv = this.conversations.find(c => c.session_id === sessionId)
          if (conv) {
            conv.title = conversation.title
            conv.updated_at = conversation.updated_at
          }
          console.log('会话已更新:', sessionId, '标题:', conversation.title)
        }
      } catch (error) {
        console.error('刷新会话失败:', error)
      }
    },
    startResponseTimer() {
      this.stopResponseTimer()
      this.responseTimerInterval = setInterval(() => {
        if (this.responseStartTime) {
          this.currentResponseTime = Math.floor((Date.now() - this.responseStartTime) / 100) / 10
          // ⚠️ 不要在这里直接写 this.messages[currentAiMessageIndex].responseTime：
          //   用户切到别的会话后 this.messages 是别的数组，currentAiMessageIndex 仍指原会话 AI 下标，
          //   会把别人的消息 responseTime 写脏。
          //   改由 SSE handler 在每个 content/reasoning/tool_call 事件里同步写入
          //   this.messages[aiIndex]（用户当前看的会话）或 snap[meta.aiIndex]（切走的会话），
          //   这样切走期间 SSE handler 也会把最新 currentResponseTime 写到正确位置。
        }
      }, 100)
    },
    stopResponseTimer() {
      if (this.responseTimerInterval) {
        clearInterval(this.responseTimerInterval)
        this.responseTimerInterval = null
      }
    },

    // 将后端返回的扁平消息列表处理成前端所需的结构
    // 后端消息类型（通过 additional_kwargs.type 区分）：
    //   role:"user"                        → 用户消息
    //   role:"ai" + type:"REASONING"       → agent 推理文本（AIMessage）或 工具调用结果（ToolMessage）
    //   role:"ai" + type:"SUMMARY"         → AI 最终回答
    //
    // 重建 toolCalls 的策略：
    //   AIMessage(REASONING) 的 additional_kwargs.tool_calls 包含工具名和参数
    //   紧随其后的 ToolMessage(REASONING) 包含对应的工具结果
    //   通过顺序配对来还原完整的 toolCalls 结构
    processConversationMessages(rawMessages) {
      const result = []
      let i = 0

      while (i < rawMessages.length) {
        const msg = rawMessages[i]

        if (msg.role === 'user') {
          const processedMsg = { ...msg }
          // 确保 is_file 标志正确设置（如果有文件就设为 true，不论是否有文本内容）
          if (msg.files && msg.files.length > 0) {
            processedMsg.additional_kwargs = { ...processedMsg.additional_kwargs, is_file: true }
            processedMsg.files = msg.files.map(file => {
              // 直接使用后端返回的 OutputFormat 扁平结构
              const fileInfo = {
                name: file.name || file.file_name || file.filename,
                size: file.size || file.file_size || 0,
                type: file.type || file.file_type || file.content_type,
                preview: file.preview || file.preview_url || null,
                iframe_url: file.iframe_url || null,
                content: file.content || null,
                fileId: file.file_id || file.fileId || null,
                file_type: file.type || file.file_type || null,
                preview_method: file.preview_method || 'download',
                preview_hint: file.preview_hint || '不支持在线预览，请下载后查看',
                size_human: file.size_human || file.file_size_human || null,
                suffix: file.suffix || null,
                is_previewable: file.is_previewable !== undefined ? file.is_previewable : true,
                // 后端需要的字段
                text_content: file.text_content || null,
                image_content: file.image_content || null,
                is_oss: file.is_oss || false
              }

              // 处理文本文件 content
              if (!fileInfo.content && file.text_content) {
                fileInfo.content = file.text_content
              }

              // 文档文件（DOCUMENT）的 iframe_office 方法处理
              if (fileInfo.preview_method === 'iframe_office') {
                if (file.iframe_url) {
                  fileInfo.iframe_url = file.iframe_url
                }
              }

              return fileInfo
            })
          }
          result.push(processedMsg)
          i++
        } else if (msg.role === 'ai') {
          // 将连续的 AI 消息合并为一个带思考过程的消息对象
          const aiTurn = {
            role: 'ai',
            content: '',
            reasoning: '',
            toolCalls: [],
            thinkingDone: true,
            streaming: false,
            checkpointId: null,  // 添加 checkpoint_id 字段
            additional_kwargs: {}  // 保存原始 additional_kwargs
          }

          // 配对队列：AIMessage 推入工具名/参数，ToolMessage 填入结果
          const pendingToolCallIndices = []

          while (i < rawMessages.length && rawMessages[i].role === 'ai') {
            const aiMsg = rawMessages[i]
            const msgType = aiMsg.additional_kwargs?.type
            const isTool = aiMsg.additional_kwargs?.isTool === true

            if (msgType === 'SUMMARY') {
              if (typeof aiMsg.content === 'string') {
                aiTurn.content = aiMsg.content
              } else if (Array.isArray(aiMsg.content)) {
                aiTurn.content = aiMsg.content
                  .filter(c => c.type === 'text')
                  .map(c => c.text || '')
                  .join('\n')
              }
              // 提取 checkpoint_id 和 additional_kwargs
              if (aiMsg.additional_kwargs?.checkpoint_id) {
                aiTurn.checkpointId = aiMsg.additional_kwargs.checkpoint_id
              }
              // 保存完整的 additional_kwargs（包含 last_checkpoint_id）
              if (aiMsg.additional_kwargs) {
                aiTurn.additional_kwargs = aiMsg.additional_kwargs
              }
              // 2.1 提取历史指标（后端落盘在 SUMMARY 的 additional_kwargs 上）：
              //     elapsed_ms / token_usage — 刷新页面后仍可见
              if (aiMsg.additional_kwargs?.elapsed_ms !== undefined) {
                aiTurn.elapsedMs = aiMsg.additional_kwargs.elapsed_ms
                if (!aiTurn.responseTime) {
                  aiTurn.responseTime = aiMsg.additional_kwargs.elapsed_ms / 1000
                }
              }
              if (aiMsg.additional_kwargs?.token_usage) {
                aiTurn.tokenUsage = aiMsg.additional_kwargs.token_usage
              }
            } else if (msgType === 'REASONING') {
              if (isTool) {
                // ToolMessage：content = "name: {tool_name}\ncontent:{tool_result}"
                // 解析出工具名和结果，配对填入对应 toolCall
                const raw = typeof aiMsg.content === 'string' ? aiMsg.content : ''
                const nameMatch = raw.match(/^name:\s*(.+)/m)
                const contentMatch = raw.match(/^content:([\s\S]*)$/m)
                const toolName = nameMatch ? nameMatch[1].trim() : '工具调用'
                const resultText = contentMatch ? contentMatch[1].trim() : raw

                if (pendingToolCallIndices.length > 0) {
                  // 有对应的 AIMessage toolCall 等待结果，填入名字和结果
                  const targetIdx = pendingToolCallIndices.shift()
                  aiTurn.toolCalls[targetIdx].name = toolName
                  aiTurn.toolCalls[targetIdx].result = resultText
                } else {
                  // 没有对应的 AIMessage，独立构造一个完整 toolCall
                  aiTurn.toolCalls.push({ name: toolName, args: null, result: resultText })
                }
              } else {
                // AIMessage(REASONING)：推理文本 + 工具调用信息
                // 1. 推理文本放入 reasoning（对应流式的 reasoning 事件）
                const reasoningText = typeof aiMsg.content === 'string' ? aiMsg.content?.trim() : ''
                if (reasoningText) {
                  aiTurn.reasoning += (aiTurn.reasoning ? '\n\n' : '') + reasoningText
                }
                // 2. 提取 checkpoint_id
                if (aiMsg.additional_kwargs?.checkpoint_id) {
                  aiTurn.checkpointId = aiMsg.additional_kwargs.checkpoint_id
                }
                // 3. 保存完整的 additional_kwargs（包含 last_checkpoint_id）
                if (aiMsg.additional_kwargs) {
                  aiTurn.additional_kwargs = aiMsg.additional_kwargs
                }
                // 4. tool_calls 放入 toolCalls 队列等待 ToolMessage 填入结果（对应流式的 tool_call_name 事件）
                const backendToolCalls = aiMsg.additional_kwargs?.tool_calls
                if (backendToolCalls && backendToolCalls.length > 0) {
                  for (const tc of backendToolCalls) {
                    const idx = aiTurn.toolCalls.length
                    aiTurn.toolCalls.push({
                      name: tc.name || '工具调用',
                      args: tc.args || null,
                      result: null
                    })
                    pendingToolCallIndices.push(idx)
                  }
                }
              }
            }
            i++
          }

          result.push(aiTurn)
        } else {
          i++
        }
      }

      return result
    }
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.handleResize)
    for (const controller of this._previewLoadControllers.values()) controller.abort()
    this._previewLoadControllers.clear()
  },
  watch: {
    isLoading(newVal) {
      // 当加载状态结束时，清理当前 AI 消息索引
      if (!newVal) {
        this.currentAiMessageIndex = null
      }
    }
  }
}
</script>

<style>
:root {
  --bg-primary: #ffffff;
  --bg-secondary: #f0f0f0;
  --bg-hover: #e8e8e8;
  --text-primary: #1a1a1a;
  --text-secondary: #6b7280;
  --border-color: #e5e5e5;
  --user-msg-bg: #dcdcdc;
  --user-msg-border: #c0c0c0;
  --ai-msg-bg: transparent;
  --button-bg: #10a37f;
  --button-hover: #0d8c6d;
  --sidebar-bg: #f7f7f8;
  --header-bg: #ffffff;
  /* 数据分析产物面板 */
  --primary-color: #3b82f6;
  /* 代码块 */
  --code-block-bg: #f7f7f8;
  --code-block-border: rgba(234, 235, 236, 0.9);
  --code-block-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  --code-block-text: #1f2937;
  --code-inline-bg: rgba(234, 235, 236, 0.6);
  --code-inline-color: #d6336c;
  --code-lang-bg: rgba(255, 255, 255, 0.8);
  --code-lang-border: rgba(220, 222, 224, 0.9);
  --code-lang-color: #6b7280;
}

.dark-theme {
  --bg-primary: #212121;
  --bg-secondary: #2a2a2a;
  --bg-hover: #383838;
  --text-primary: #ececec;
  --text-secondary: #9ca3af;
  --border-color: #363636;
  --user-msg-bg: #2d2d2d;
  --user-msg-border: #404040;
  --ai-msg-bg: transparent;
  --button-bg: #10a37f;
  --button-hover: #0d8c6d;
  --sidebar-bg: #171717;
  --header-bg: #212121;
  /* 代码块 - 暗色主题 */
  --code-block-bg: #141414;
  --code-block-border: rgba(255, 255, 255, 0.1);
  --code-block-shadow: 0 2px 6px rgba(0, 0, 0, 0.5);
  --code-block-text: #e5e7eb;
  --code-inline-bg: rgba(255, 255, 255, 0.06);
  --code-inline-color: #f472b6;
  --code-lang-bg: rgba(0, 0, 0, 0.3);
  --code-lang-border: rgba(255, 255, 255, 0.08);
  --code-lang-color: #9ca3af;
}

/* 移动端侧边栏遮罩 */
.sidebar-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 99;
}

@media (max-width: 600px) {
  .sidebar-overlay {
    display: block;
  }
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen',
    'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.app-container {
  width: 100vw;
  height: 100vh;
  background-color: var(--bg-primary);
  color: var(--text-primary);
  overflow: hidden;
}

/*
 * 首次 servicesReady IPC 等待期间的占位背景色。
 * Electron IPC 单次往返通常 < 10ms，warm path 用户几乎感觉不到这一帧；
 * cold path 也只是一闪——比「warm 时 SetUpView 弹一下再消失」「cold 时先露空主界面再叠浮窗」都干净。
 * 暗色主题下也是这个浅色占位（几十 ms 内看不全，且避免主题判断的额外 IPC），
 * 主界面亮起时如果是暗色主题会立即接管，看起来跟主界面错位一帧——可接受。
 */
.app-loading-bg {
  position: fixed;
  inset: 0;
  background: var(--bg-primary, #f5f5f7);
}

/*
 * 启动期主界面灰显 + 禁用交互：后端未就绪时主界面已经在 DOM 里（用户能隐约看到布局），
 * 但不能点；SetUpView 浮窗叠在上方（z-index 1000），bootstrap 完成后 SetUpView 淡出、
 * app-disabled 解除，主界面自动 loadConversations。
 */
.app-container.app-disabled {
  pointer-events: none;
  user-select: none;
  filter: grayscale(0.3) brightness(0.92);
  transition: filter 0.3s ease-out;
}

.app-container:not(.app-disabled) {
  transition: filter 0.3s ease-out;
}

/* 后端失联 banner：fixed 贴顶，不挤占 layout 空间 */
.backend-health-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 10px 16px;
  background: rgba(255, 59, 48, 0.95);
  color: white;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  animation: bannerSlideDown 0.25s ease-out;
}

@keyframes bannerSlideDown {
  from { transform: translateY(-100%); opacity: 0; }
  to   { transform: translateY(0);     opacity: 1; }
}

.backend-health-banner .banner-icon {
  font-size: 16px;
}

.backend-health-banner .banner-text {
  flex: 0 1 auto;
}

.backend-health-banner .banner-action {
  margin-left: 8px;
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 600;
  color: #ff3b30;
  background: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: opacity 0.15s;
}

.backend-health-banner .banner-action:hover:not(:disabled) {
  opacity: 0.85;
}

.backend-health-banner .banner-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 暗色主题下用更柔和的红，避免刺眼 */
.app-container.dark-theme .backend-health-banner {
  background: rgba(180, 40, 30, 0.95);
}

.main-layout {
  display: flex;
  height: 100%;
}

.chat-area {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-primary);
  position: relative;
}

.checkpoint-overlay {
  position: fixed;
  inset: 0;
  z-index: 99;
}

/* 中断状态栏 */
.interrupted-bar {
  position: absolute;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  z-index: 50;
}

.interrupted-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.resume-btn {
  padding: 6px 16px;
  background: var(--button-bg);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.resume-btn:hover {
  background: var(--button-hover);
}

/* 续接输入弹窗 */
.resume-input-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.resume-input-dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 24px;
  width: 100%;
  max-width: 400px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.resume-input-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.resume-input-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

.resume-input-textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 14px;
  resize: none;
  font-family: inherit;
  margin-bottom: 16px;
}

.resume-input-textarea:focus {
  outline: none;
  border-color: var(--button-bg);
}

.resume-input-textarea::placeholder {
  color: var(--text-secondary);
}

.resume-input-buttons {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.resume-input-cancel {
  padding: 8px 16px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.resume-input-cancel:hover {
  background: var(--bg-hover);
}

.resume-input-confirm {
  padding: 8px 16px;
  background: var(--button-bg);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
}

.resume-input-confirm:hover {
  background: var(--button-hover);
}

.web-preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 99;
}

/* 文件预览遮罩 */
.file-preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 99;
}

/* 图片预览弹窗 */
.image-preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.9);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  animation: fadeIn 0.2s;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.image-preview-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
  animation: scaleIn 0.2s;
}

@keyframes scaleIn {
  from { transform: scale(0.9); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.image-preview-close {
  position: absolute;
  top: -40px;
  right: 0;
  width: 36px;
  height: 36px;
  border: none;
  background: rgba(255, 255, 255, 0.1);
  color: white;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}

.image-preview-close:hover {
  background: rgba(255, 255, 255, 0.2);
}

.image-preview-img {
  max-width: 100%;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 8px;
}

::-webkit-scrollbar {
  width: 8px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

/*
 * SetUpView 浮窗淡入淡出：appReady 翻 true 时整组淡出，避免 v-if 突然消失的硬切。
 * SetUpView 内部已经有 .setup-overlay 自己的 fade-in animation，
 * 这里用 Vue transition 钩子同步 enter/leave 曲线。
 */
.setup-fade-enter-active,
.setup-fade-leave-active {
  transition: opacity 0.25s ease-out;
}
.setup-fade-enter,
.setup-fade-leave-to {
  opacity: 0;
}
</style>
