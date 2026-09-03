<template>
  <!--
    双路径（按 isElectron 分流）+ 初始 gate（按 _isInitializing 分流）：
    - _isInitializing 期间（首次 servicesReady IPC 还没回，约 5-50ms）：只渲染空白底色占位，
      既不显示主界面也不显示 BootstrapView——避免「已知 warm 还要闪一下 BootstrapView / 已知 cold 还要闪一下空主界面」。
    - 拿到结果后：
      - Electron cold（servicesReady=false）：主界面灰显 + BootstrapView 叠加 → bootstrap 完成 → 解除 disabled + BootstrapView 淡出
      - Electron warm（servicesReady=true）/ Web：主界面直接挂载，不再有任何闪烁
  -->
  <div v-if="_isInitializing" class="app-loading-bg"></div>
  <template v-else>
  <div
    :class="['app-container', { 'dark-theme': isDarkTheme, 'app-disabled': isElectron && !appReady }]"
  >
    <div class="main-layout">
      <Sidebar
        ref="sidebar"
        :collapsed="sidebarCollapsed"
        :conversations="conversations"
        :active-session-id="currentSessionId"
        :mobile-open="sidebarMobileOpen"
        :active-view="sidebarView"
        :active-streaming-sessions="_activeStreamingSessions"
        :completed-sessions="_completedSessions"
        :approval-pending-sessions="_approvalPendingSessions"
        :error-sessions="_errorSessions"
        :scheduled-tasks-map="scheduledTasksMap"
        :scheduled-tasks-busy="_scheduledTasksRefreshing"
        :load-error="conversationsLoadError"
        @toggle="toggleSidebar"
        @new-chat="createNewChat"
        @select-conversation="loadConversation"
        @delete-conversation="deleteConversation"
        @update-title="updateConversationTitle"
        @refresh-conversation="refreshConversation"
        @scheduled-task-toggle="onScheduledTaskToggle"
        @scheduled-task-run="onScheduledTaskRun"
        @scheduled-task-delete="onScheduledTaskDelete"
        @update:activeView="sidebarView = $event"
        @file-click="onDataAnalysisFileClick"
        @reload-files="onSidebarReloadFiles"
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
          @open-setup="setupVisible = true"
          @toggle-checkpoints="toggleCheckpoints"
          @toggle-sidebar="toggleMobileSidebar"
          @refresh="refreshPage"
        />

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
          @restart-session="restartConversation"
          @quote="handleQuote"
          @withdraw="handleWithdraw"
          @insert-suggestion="handleInsertSuggestion"
        />

        <MessageInput
          ref="messageInput"
          :is-loading="isLoading"
          :session-id="currentSessionId"
          :permission-resume-in-flight="permissionResumeInFlight"
          :queue="queueForCurrentSession"
          @send="sendMessage"
          @front-action="runFrontAction"
          @remove-queue-item="onRemoveQueueItem"
          @clear-queue="onClearQueue"
          @files-selected-need-session="handleFilesSelectedNeedSession"
          @chat-drag-state="onChatDragState"
          v-model:quote="currentQuote"
        />

        <!-- 拖拽遮罩：v0.2.x 起放在 .chat-area 子元素渲染（position: absolute），
             只覆盖 chat 区不盖 sidebar，与 sidebar 的 system-drag-overlay 真正「两片分开」。
             拖拽逻辑由 MessageInput 内部处理（_isDragOverFilesTree 区分），
             isDragging state 通过 @chat-drag-state 上报到这里。 -->
        <transition name="chat-drag-fade">
          <div v-if="chatDragging" class="chat-drag-overlay">
            <div class="chat-drag-content">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="17 8 12 3 7 8"/>
                <line x1="12" y1="3" x2="12" y2="15"/>
              </svg>
              <p>释放文件以上传到对话</p>
            </div>
          </div>
        </transition>
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

    <!-- 帮助弹窗（由 /help 命令触发） -->
    <HelpDialog
      :visible="helpVisible"
      :commands="slashCommands"
      @close="helpVisible = false"
    />

    <!-- 配置向导浮窗（顶栏 🪄 按钮 + /setup 命令共用）
         非阻塞：主界面 `.app-disabled` 不加上，用户看到浮窗时仍可点底栏。
         z-index 由 SetupView 内部样式控制，与 BootstrapView 同档位。组件自管 v-if + transition，外部一直挂载。 -->
    <SetupView
      :visible="setupVisible"
      @close="setupVisible = false"
    />

    <!-- 通用简洁提示弹窗（slash 命令前置条件不满足时用） -->
    <ToastDialog
      :visible="toast.visible"
      :title="toast.title"
      :message="toast.message"
      @close="closeToast"
    />
  </div>

  <!--
    启动浮窗：仅 Electron 路径 + 主界面还没启用（!appReady）时挂载。
    包含 3 种状态：
      - cold start：servicesReady=false，BootstrapView 显示「启动应用」按钮
      - cold start 完成后未勾自动进：servicesReady=true && appReady=false，BootstrapView 显示「进入应用」
      - warm start：appReady=true，BootstrapView 不挂载（不闪一下）
    当后端从 health→crash 时 appReady 重置为 false，BootstrapView 重新显示「启动应用」。
    v-if 切换走淡入淡出过渡，不直接 v-show（v-show 会让 .bootstrap-overlay 的 animation 反复触发）。
  -->
  <transition name="bootstrap-fade">
    <BootstrapView
      v-if="isElectron && !appReady"
      :services-ready="servicesReady === true"
      @enter-app="onEnterApp"
    />
  </transition>

  <!--
    NotFound 浮层：访问不存在的 URL 时浮现 10 秒，倒计时 + 进度条 + 像素鹿跳动。
    z-index 1800（NotFoundView 内部样式）比 BootstrapView 1500 高，确保盖住所有 UI。
    任何点击 → _navigateHome → hide + location.replace('/')，跳回主页并清理 pathname。
  -->
  <transition name="not-found-fade">
    <NotFoundView
      v-if="_notFoundActive"
      :remaining="_notFoundRemaining"
      @click-anywhere="_navigateHome"
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
import BootstrapView from './components/BootstrapView.vue'
import CheckpointPanel from './components/CheckpointPanel.vue'
import WebPreviewPanel from './components/WebPreviewPanel.vue'
import FilePreviewPanel from './components/FilePreviewPanel.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import HelpDialog from './components/HelpDialog.vue'
import ToastDialog from './components/ToastDialog.vue'
import NotFoundView from './components/NotFoundView.vue'
import SetupView from './components/SetupView.vue'
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
    BootstrapView,
    CheckpointPanel,
    WebPreviewPanel,
    FilePreviewPanel,
    SettingsDialog,
    HelpDialog,
    ToastDialog,
    NotFoundView,
    SetupView
  },
  data() {
    return {
      isDarkTheme: false,
      sidebarCollapsed: false,
      // chat 区拖拽 overlay 状态：由 MessageInput 通过 @chat-drag-state 上报。
      // v0.2.x 起 chat overlay 不再 fixed 全屏，改在 .chat-area 子元素渲染，
      // 在 sidebarView === 'files' 时与 sidebar 的 system-drag-overlay 视觉分离。
      chatDragging: false,
      // 侧栏视图：'sessions' | 'files'，持久化到 localStorage（用户偏好）
      sidebarView: (() => {
        try {
          const v = localStorage.getItem('lingxi.sidebarView')
          return v === 'files' ? 'files' : 'sessions'
        } catch { return 'sessions' }
      })(),
      conversations: [],
      // 加载会话失败时的错误消息（用户可见），空字符串 = 成功或尚未加载
      conversationsLoadError: '',
      // 是否在 Electron 环境运行（仅有 electronAPI）；web 永远 false
      // 控制是否走 servicesReady 状态机 + 渲染 BootstrapView 浮窗
      isElectron: false,
      // 后端服务就绪状态：null = 首次 IPC 还没回（gate 期间不渲染任何东西，避免闪烁）；
      // true = 后端可用；false = 后端未启动（cold start，需要走 bootstrap + BootstrapView 浮窗）
      servicesReady: null,
      // 启动引导完成标志（区分 servicesReady：appReady 表示「主界面启用 + 会话已初始化」，
      // 后端重启可能让 appReady 重置但 servicesReady 翻 true 时同样需要重 init）
      appReady: false,
      // 首次 servicesReady 检查还没回来时为 true，期间不渲染主界面也不渲染 BootstrapView。
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
      // handleWithdraw 等待 SSE interrupt 事件到达的 resolver（仅单 in-flight withdraw）
      _withdrawInterruptResolver: null,
      isMobile: false,
      sidebarMobileOpen: false,
      interruptReason: '',  // 中断原因
      showResumeInput: false,  // 显示续接输入框
      resumeInputText: '',  // 续接输入文本
      currentQuote: null,  // 当前引用内容：{ content: string }
      settingsVisible: false,  // 设置弹窗可见性
      helpVisible: false,  // /help 弹窗可见性
      setupVisible: false,  // 配置向导浮窗可见性（顶栏 🪄 按钮 + /setup 共用）
      // 简洁提示弹窗（slash 命令前置条件不满足时用，例如「/backtrack 当前没有会话」）
      toast: { visible: false, title: '', message: '' },
      // 静态 action 命令清单（永远在前，不依赖后端）：
      // 纯前端动作（打开弹窗 / 刷新页面），name 不会发往后端，无命名约束。
      // 这份副本驱动 HelpDialog「命令」段渲染；input 输入框走 MessageInput.staticActionCommands（独立副本），
      // 两边必须保持一致，否则 /help 弹窗里看不到新增的 action 命令。
      staticActionCommands: [
        { name: 'backtrack', kind: 'action', description: '打开历史版本面板' },
        { name: 'settings',  kind: 'action', description: '打开设置弹窗' },
        { name: 'setup',     kind: 'action', description: '打开安装 / 配置向导（首启推荐）' },
        { name: 'reload',    kind: 'action', description: '刷新当前会话' },
        { name: 'worktree',  kind: 'action', description: '打开当前会话工作树' },
        { name: 'help',      kind: 'action', description: '显示本项目功能速览' }
      ],
      // Skill 描述前端覆盖：key = /chat/skills 返回的目录名（PascalCase），缺省 fallback 后端 description
      skillDescriptionOverrides: {
        Memory:       '把反复出现的精确事实 / 用户偏好记下来，下次对话自动加载到上下文',
        ImageParser:  '解析图片中的文字、表格、界面元素与场景（支持截图、照片、URL、base64）',
        SkillForge:   '动态创建新技能：写一段 Python 包装 + 描述，AI 后续对话会自动识别并使用'
      },
      // 动态 skill 列表（从 /chat/skills 拉的），每个含 {name, description, lazy}。
      // 由 computed `slashCommands` 与 staticActionCommands 拼接暴露给 HelpDialog。
      dynamicSkills: [],
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
      // —— 消息队列（per session 排队发送）——
      // session_id -> QueueEntry[]，FIFO 顺序；与后端 Redis db1 queue:{sid} 双向同步
      // QueueEntry: { message, quote, queued_at }（与后端 JSON 字段一致）
      _pendingQueue: new Map(),
      // 已从后端拉过队列的 sid 集合（避免每次切会话都重复 GET）
      _queueLoaded: new Set(),
      // 等用户切回再 drain 的 sid 集合：
      // - stream 结束时若用户不在该 sid 上，drain 推迟到 currentSessionId 切回时
      // - 用 Set 包装：Vue 2 必须整 Set 替换才能触发响应式（add/delete 静默）
      _queueDrainDeferred: new Set(),
      // 已经乐观 slice 但 DELETE Redis 还没发出的 sid 集合（per-session，最多 1 个 head）。
      // 作用：_loadQueueForSession 拿到 Redis 返回时跳过这些 head，
      // 避免「乐观 slice 把 head 从本地移除 → 并发 _enqueueMessage / _removeQueueItem 触发
      // reload → Redis 镜像带回 head → 下一次 drain 递归又把 head 重新 send 一次」
      // （实测会触发同一条 queue 消息发两次的 bug）。
      // drain 进入时 add，DELETE Redis 发出时 delete；与 _drainInFlight 同生命周期但语义不同：
      // _drainInFlight 是「drain 函数本身还在跑」（防并发 drain），
      // _drainedNotDeleted 是「Redis 还有 head 但本地不应该显示」（防 reload 镜像回来）。
      _drainedNotDeleted: new Set(),
      // 同 sid 并发 sendMessage 防护锁：session_id -> bool
      // sendMessage 入口 set true（防 race），finally 块 set false。
      // 防止用户在 fetch 还没返回时再次点发送 → 两个 SSE 并发跑。
      _sendingLock: new Map(),
      // —— 后端健康监测 —— null = 还没拉过；true = 健康；false = 失联 → 显示 banner
      backendHealth: null,
      restartingBackend: false,  // 用户点「重新连接」期间 disable 按钮，避免重复触发
      // appReady 从 false→true 触发的 initConversationState 只跑一次，避免 servicesReady
      // 反复变化时（比如重启后端）重复初始化会话
      _conversationInited: false,
      // —— 定时任务缓存（per session） ——
      // session_id -> ScheduledTask[]；空数组 = 该 session 无任务（面板不渲染）
      scheduledTasksMap: new Map(),
      // 整图 refreshing 标记（驱动面板 ↻ 旋转）
      _scheduledTasksRefreshing: false,
      // —— NotFoundView 浮层（不存在的 URL 触发的 10s 动画）——
      _notFoundActive: false,        // 浮层是否显示
      _notFoundTimer: null,          // 10s 自动跳转 setTimeout handle
      _notFoundTickInterval: null,   // 100ms tick interval 驱动进度条
      _notFoundRemaining: 10,        // 倒计时剩余秒数（驱动模板 + 进度条）
      // —— 双击 `/` 快捷键 —— 上一次 `/` 按下的时间戳。
      // 双击窗口 500ms 内（macOS 双击阈值）且用户当前不在输入框 → 聚焦输入框；
      // 在输入框里则不拦截，让 `//` 正常输入（用户主动输入字面量 //）。
      _lastSlashTime: 0,
    }
  },
  mounted() {
    // 单窗口架构（Electron）：主界面永远 mount，BootstrapView 浮窗叠加在 .app-disabled 主界面上方。
    // Web 端：根本不渲染 BootstrapView（直接进主界面），不走 servicesReady 状态机。
    //        isElectron = !!window.electronAPI 控制两套路径分流。
    const savedTheme = localStorage.getItem('chatme-theme')
    if (savedTheme) {
      this.isDarkTheme = savedTheme === 'dark'
    }

    // 检测移动端
    this.isMobile = window.innerWidth <= 600
    window.addEventListener('resize', this.handleResize)
    // 弹层 Esc/Enter 全局快捷键：image-preview / resume-input 弹层打开时
    // 监听 document（div 无 tabindex 时 @keydown.esc 收不到事件）
    window.addEventListener('keydown', this.handleOverlayKeydown)
    // 全局快捷键 双击 `/` → 聚焦输入框。监听独立挂载，不并入 handleOverlayKeydown，
    // 因为「双击 /」是「全局跳转」语义，弹层打开时也需要短路。
    window.addEventListener('keydown', this.handleDoubleSlashFocus)

    if (window.electronAPI?.getServicesReady) {
      // ===== Electron 路径 =====
      this.isElectron = true
      // 拉一次 servicesReady 快照（避免订阅前错过早期事件），然后订阅后续变更。
      // 路径分流：
      //   - ready=true（warm）：servicesReady=true，直接 init，BootstrapView 永远不渲染（不闪）
      //   - ready=false（cold）：servicesReady=false，BootstrapView 浮窗渲染，主界面灰显
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
      // =true 立刻翻 appReady，=false 保留 BootstrapView 等用户点「进入应用」。
      // warm / restart / crash-to-false 这几条路径只读 ready 字段。
      window.electronAPI.onServicesReadyChange((payload) => {
        const ready = !!(payload && payload.ready)
        const autoEnter = !!(payload && payload.autoEnterFrontend)
        const wasReady = !!this.servicesReady
        this.servicesReady = ready
        if (ready && autoEnter) {
          // 勾了自动进：立即翻 appReady=true 让主界面接管（idempotent）。
          // 【关键】这里**不**用 wasReady / _conversationInited 作 gate：
          //   1) idempotent — 多次 broadcast 重复设 appReady=true 是无害的（Vue 3 reactivity 去重）；
          //   2) 防 race — first broadcast 因订阅时序 / stale state 被旧分支条件跳过后，
          //      后续 broadcast 也能补翻 appReady；
          //   3) 防 main 早返回 — 主进程 setServicesReady 有「servicesReady === ready 则早返回」
          //      去重，若第一次 bootstrap 的 broadcast 被 renderer 错过，第二次 bootstrap 不会
          //      重发 broadcast。这里 idempotent 等价于「只要看到 ready=true && autoEnter=true
          //      就翻 appReady」，覆盖这种 dead lock。
          // _conversationInited 仅用来 gate initConversationState（避免重复 init）。
          this.appReady = true
          if (!this._conversationInited) {
            this._conversationInited = true
            this.$nextTick(() => this.initConversationState())
          }
        } else if (ready && !wasReady) {
          // 没勾自动进 + cold start 完成：保持 appReady=false（默认），BootstrapView 显示「进入应用」等用户点
        }
        // 后端从 true 变 false（重启中）：主界面回退到 disabled，BootstrapView 重新显示
        if (!ready && wasReady) {
          this.appReady = false
          // _conversationInited 保持 true — 同一 session 内的 initConversationState 只跑一次语义不变
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

    // 启动后后台拉一次动态 skill 列表（registry 内部 _maybe_rescan 自动 mtime 检测）。
    // /help 弹窗打开时还会再 refetch 一次（watch.helpVisible），覆盖 SkillForge
    // 中途新增的场景。失败兜底维持空数组，至少 action 命令仍可用。
    this.fetchSkills()
  },
  watch: {
    // /help 弹窗「关闭 → 打开」时仅在缓存为空时才 refetch（与 MessageInput 的
    // slashPalette 转换同语义）。缓存命中时直接复用 dynamicSkills 数据，
    // 不浪费一次 HTTP。缓存由 sessionId 变化（切会话）+ refreshConversation
    // 入口清空（MessageInput.clearDynamicSkills 暴露给 App.vue）。
    helpVisible(visible) {
      if (visible && this.dynamicSkills.length === 0) this.fetchSkills()
    },
    // 侧栏视图切换持久化（跨 F5 恢复）
    sidebarView(newVal) {
      try { localStorage.setItem('lingxi.sidebarView', newVal) } catch { /* 静默 */ }
    },
    '$route.params.sessionId'(newSessionId) {
      // 监听 URL 变化
      // 格式不合法（非 12/32 位 hex，如 #/garbage、#/abc、#/12345）
      // → 立即触发动画，不进 loadConversation（避免后端再走一圈 404）
      if (newSessionId && !this.isValidSessionId(newSessionId)) {
        this.showNotFound()
        return
      }
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
    },
    // —— 消息队列：流式结束 → 触发 drain（用户切走则推迟） ——
    // SSE done / error / interrupt 三处都已把 sid 从 _activeStreamingSessions 移除并 new Set() 整体替换，
    // 这里的 watcher 会拿到 oldSet（移除前）和 newSet（移除后），用 oldSet - newSet 算出"刚流式完的 sid"。
    // 行为：刚流式完的 sid 若队列非空 → 立即 drain（前提：用户在 sid 上）或推迟（用户不在 sid 上）。
    // 不用在 15+ done 处理器里各自手写 drain 的原因：watcher 是统一触发点，加新 SSE 入口不必改这里。
    '_activeStreamingSessions': {
      handler(newSet, oldSet) {
        if (!oldSet || oldSet === undefined) return
        for (const sid of oldSet) {
          if (newSet.has(sid)) continue
          // sid 刚离开流式 → 检查是否有排队消息需要 drain
          // 兜底：watcher 可能不触发（Vue 2 + Set 反应式），所以 done/error/interrupt handler
          // 也显式调 _tryDrainQueue；watcher 是 belt-and-suspenders，双保险。
          this._tryDrainQueue(sid)
        }
      }
    },
    // 用户切会话时检查新会话是否有待 drain 的排队（覆盖 stream 结束时用户不在该 sid 的延迟场景）
    currentSessionId: {
      handler(newSid) {
        if (newSid && this._queueDrainDeferred.has(newSid)) {
          this._queueDrainDeferred.delete(newSid)
          this._queueDrainDeferred = new Set(this._queueDrainDeferred)
          this.$nextTick(() => this._tryDrainQueue(newSid))
        }
      }
    }
  },
  computed: {
    /**
     * 当前会话的定时任务列表（侧栏 ConversationItem 用 scheduledTasksMap.get(id) 拿）
     * - 仍保留这个 computed 备用，部分老代码可能还在引用；侧栏已切到 Map 直查
     * - 无 session 时返 []（避免 map.get 返 undefined）
     */
    scheduledTasksForCurrentSession() {
      if (!this.currentSessionId) return []
      return this.scheduledTasksMap.get(this.currentSessionId) || []
    },
    /**
     * 当前会话的排队消息列表（用于 MessageInput 渲染卡片）
     * - 无 session 时返 []
     * - loadConversation 会拉一次（首次访问 / 切会话都拉）
     */
    queueForCurrentSession() {
      if (!this.currentSessionId) return []
      return this._pendingQueue.get(this.currentSessionId) || []
    },
    /**
     * 全量 slash 命令 = 静态 action + 动态 skill，供 HelpDialog 渲染。
     * - action 永远在前（高频且稳定）
     * - skill 顺序由 /chat/skills 返回值决定（按 name 字母序）
     * - runSlashCommandFromHelp 用 find() 取第一个，action 优先语义自然生效
     */
    slashCommands() {
      return [
        ...this.staticActionCommands,
        ...this.dynamicSkills.map(s => ({
          name: s.name,
          kind: 'skill',
          description: this.skillDescriptionOverrides[s.name] || s.description || `${s.name} skill`
        }))
      ]
    },
  },
  methods: {
    /**
     * MessageInput 上报的拖拽状态：isDragging 变化时 emit 'chat-drag-state' 过来。
     * 这里只接 state 不接逻辑（窗口级 drag/over/drop 监听还在 MessageInput 内部，
     * 它通过 _isDragOverFilesTree 区分 chat 区 vs sidebar 文件树，
     * 在 .files-tree 内主动 isDragging=false 把控制权交回 Sidebar）。
     */
    onChatDragState(isDragging) {
      this.chatDragging = !!isDragging
    },
    setTheme(isDark) {
      this.isDarkTheme = !!isDark
      localStorage.setItem('chatme-theme', this.isDarkTheme ? 'dark' : 'light')
    },
    /**
     * 后台拉取动态 skill 列表。registry 内部 `_maybe_rescan()` 自动检测
     * SKILL.md mtime —— SkillForge 写新 skill 后无需重启后端，下次 GET
     * 即拿到新列表。
     *
     * 调用时机（**只在缓存为空时才发请求**）：
     *  - mounted 首次拉取（冷启动兜底）
     *  - /help 弹窗打开且缓存为空时拉一次（同会话内反复打开 /help 不重复请求；
     *    切/刷会话清空缓存后下次开 /help 才重新拉）
     *
     * 失败兜底：dynamicSkills 维持上次状态，HelpDialog 至少渲染 action 命令。
     */
    async fetchSkills() {
      try {
        const response = await fetch('/chat/skills')
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data = await response.json()
        const raw = Array.isArray(data?.skills) ? data.skills : []
        // 后端已过滤 lazy=true，这里再守一层防止 schema 变动
        this.dynamicSkills = raw.filter(s => s && typeof s.name === 'string' && s.name && !s.lazy)
      } catch (error) {
        console.warn('[App] fetchSkills 失败，维持当前动态列表:', error?.message || error)
      }
    },
    /**
     * 用户在 BootstrapView 上点「进入应用」：
     * 翻 appReady=true 触发 .app-disabled 解除 + initConversationState。
     * 与 warm path / cold autoEnter=true 同路径（自动翻 + init），只是入口从 IPC 广播
     * 变成 BootstrapView 的主动 emit。
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
        // —— 检测 pathname 形式的坏 URL ——
        // Electron/Vite protocol.handle fallback：不存在的 /<anything> 路径会被
        // serve index.html，但 URL bar 的 pathname 残留 /<anything>。hash 留空 →
        // Vue Router 走 createNewChat() → URL 变成 /<anything>#/ → 用户看到主页，
        // 意识不到自己访问的是坏 URL。
        // 这里主动检测：pathname 不是根也不是 index.html（即 Vite SPA fallback 留下的
        // 单 segment），就视为坏 URL → 直接触发动画。
        // 用 endsWith('/index.html') 而不是 === '/index.html'：Electron 打包后
        // win.loadFile(dist/index.html) 不会把 pathname 规范化成 /index.html，
        // 而是完整绝对路径（macOS 如 /Applications/灵析.app/Contents/Resources/
        // app.asar/dist/index.html），prod 启动每次都会撞这条误触发动画。
        // / 单独保留：dev 模式 loadURL('http://localhost:18211/') 的 pathname 就是 /。
        const path = window.location.pathname
        const isIndexHtmlEntry = path === '/' || path.endsWith('/index.html')
        if (!isIndexHtmlEntry && !initialSessionId) {
          this.showNotFound()
          return
        }
        // App 启动时 URL 就是非法 hash → 直接触发动画，不进 loadConversation
        // （启动时不会经过 watcher，所以这里必须显式校验）
        if (initialSessionId && !this.isValidSessionId(initialSessionId)) {
          this.showNotFound()
          return
        }
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
     * 后端 done/error/interrupt 给的权威 elapsed_ms 会在终态事件里通过 writeStreamMetrics 覆盖；
     * 但下一次 timer tick 又会用本地 wall-clock 重写——这是设计选择：timer 启动时刻 ≈ round
     * start 时刻（sendMessage 流入口），所以前端 elapsedMs 与后端 elapsed_ms 差异固定且很小，
     * 用户视觉上看不到跳变，且 SSE 暂停时数字持续累加。
     *
     * startTs 必须闭包捕获；timer body 不读对象上的 startTs，spread 多少次 timer 都能持续
     * 写到 arr[meta.aiIndex] 最新对象上。
     */
    startStreamTimer(sessionId, msg) {
      this.stopStreamTimer(sessionId)
      if (!msg) return
      const startTs = Date.now()
      const meta = this._streamingMeta.get(sessionId)
      const aiIndex = meta ? meta.aiIndex : -1
      const timer = setInterval(() => {
        const arr = this._streamingMessages.get(sessionId)
        if (!arr || aiIndex < 0 || aiIndex >= arr.length) return
        const cur = arr[aiIndex]
        if (cur) {
          cur.elapsedMs = Date.now() - startTs
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
        // 续接完成（正常 / 中断 / 异常 都涵盖在 finally）→ 焦点还给输入框
        this.focusInput()
      }
    },
    cancelResume() {
      this.showResumeInput = false
      this.resumeInputText = ''
      // 取消续接 → 焦点还给输入框（用户回到正常输入态）
      this.focusInput()
    },
    confirmResume() {
      const message = this.resumeInputText.trim()
      this.showResumeInput = false
      this.resumeInputText = ''
      // 直接调用 handleResume 并传入消息
      this.handleResume(message)
      // handleResume 末尾会再 focusInput（异步流程）；这里再调一次保险
      this.focusInput()
    },
    /**
     * App.vue 持有的 overlay 弹层（image-preview / resume-input）开 Esc/Enter 全局快捷键。
     * 监听 document 而不是 overlay div 上的 @keydown.esc —— 后者 div 无 tabindex 时
     * 收不到 keyboard 事件。
     *
     * - image-preview：Esc 关闭
     * - resume-input：Esc 取消；Enter 仅在焦点不在 textarea（用户没在输入续接内容）时
     *   才确认。textarea 里的 Enter 仍走原生换行，不 hijack。
     */
    handleOverlayKeydown(e) {
      if (this.showImagePreview) {
        if (e.key === 'Escape') {
          e.preventDefault()
          this.showImagePreview = false
        }
        return
      }
      if (this.showResumeInput) {
        if (e.key === 'Escape') {
          e.preventDefault()
          this.cancelResume()
        } else if (e.key === 'Enter' && !e.isComposing) {
          const t = e.target
          const inTextarea = t && (t.tagName === 'TEXTAREA' || t.isContentEditable)
          if (!inTextarea) {
            e.preventDefault()
            this.confirmResume()
          }
        }
      }
    },
    /**
     * 全局快捷键 双击 `/` → 聚焦消息输入框。
     *
     * 行为矩阵：
     * - 用户已在输入框（textarea / input / contenteditable）：
     *   单 `/` 正常输入；双 `//` 也正常输入（用户可能故意输入注释符号、URL、Python 注释等）。
     *   不拦截、不抢焦点。
     * - 用户不在输入框（侧栏 / 消息列表 / 任意非输入态）：
     *   单 `/` `preventDefault` 阻止 Firefox quick-find 等浏览器自带行为；
     *   双 `//`（500ms 内连按两次）→ `preventDefault` + 聚焦输入框。
     *
     * 设计要点：
     * - 双击而不是单字符：避免和「用户在输入框打 / 调 slash 命令」撞键，
     *   也避免误触（输入框里 `//` 是合法字面量，不应被吞）。
     * - 500ms 阈值：参考 macOS 双击默认（~500ms），够快不累赘、又不至于和正常输入节奏混淆。
     * - 第一次 `/` 也 `preventDefault`：用户不在输入框时按的 `/` 没有「应该出现的」目标，
     *   让浏览器做任何反应（quick-find / dev console / iframe focus）都是意外的。
     * - 弹窗（Settings/Help/Confirm 等）打开时短路：弹窗有自己的 keydown 处理器，
     *   强抢焦点会把焦点偷到被遮的 textarea 上，破坏弹窗自身的快捷键回路。
     *   用户先 Esc 关闭弹窗再双击 `/`。
     * - 不和 shift/alt/meta/ctrl 同按：避免和未来扩展（如 Shift+/ = ?）撞键；
     *   中文 IME 组合输入期 `e.isComposing` 跳过，组合完成后才判断。
     */
    handleDoubleSlashFocus(e) {
      if (e.key !== '/') return
      if (e.isComposing) return
      if (e.shiftKey || e.altKey || e.metaKey || e.ctrlKey) return

      const active = document.activeElement
      const isInInput = active && (
        active.tagName === 'TEXTAREA' ||
        active.tagName === 'INPUT' ||
        active.isContentEditable === true
      )

      if (isInInput) {
        // 在输入框内 —— 不拦截，让 / 和 // 都正常输入；
        // 同时清掉双击窗口，防止「按 / 切走再切回输入框」误触双击。
        this._lastSlashTime = 0
        return
      }

      // 弹窗（Settings / Help / Confirm 等）打开时短路：弹窗有自己的 keydown 处理器，
      // 强抢焦点会把焦点偷到被遮的 textarea 上，破坏弹窗自身的快捷键回路。
      // 用户先 Esc 关闭弹窗再双击 `/`。
      if (this.settingsVisible || this.helpVisible || this.showRestoreConfirm
          || this.showImagePreview || this.showWebPreview || this.showFilePreview
          || this.showCheckpoints || this.showResumeInput) {
        return
      }

      // 不在输入框也不在弹窗 —— 拦截 /，检测双击
      e.preventDefault()
      const now = Date.now()
      const DOUBLE_TAP_WINDOW = 500
      if (this._lastSlashTime && (now - this._lastSlashTime) < DOUBLE_TAP_WINDOW) {
        this._lastSlashTime = 0
        // force=true：双击 / 是用户明确要把焦点切到输入框，绕过 files 视图的短路
        this.focusInput(true)
      } else {
        this._lastSlashTime = now
      }
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

    /**
     * 欢迎区「试一试」chip 点击事件。MessageList 把候选文本（目前只有 `/help`）emit 上来，
     * App.vue 同时做两件事：
     *   1. 把文本写到 MessageInput 输入框 + focus + 光标置末尾 —— 让用户看到「已敲入」
     *   2. 直接调对应 front-action，弹 HelpDialog
     * 第 2 步是关键：用户点 chip 的目的是「快速了解功能」而不是手动敲命令 + 回车，
     * 一步到位更顺手。
     */
    handleInsertSuggestion(text) {
      if (!text) return
      this.$refs.messageInput?.setInputText(text)
      // 模拟一次回车：fillText 后直接派发对应 front-action
      const cmd = this.slashCommands.find(c => c.name === text.replace(/^\//, ''))
      if (cmd) {
        this.runFrontAction(cmd)
      }
    },

    /**
     * 前端动作命令分发器。MessageInput 在用户输入「命令 + 空白（或仅命令）」按回车时
     * emit `front-action` 上来，App.vue 根据 name 派发到对应的前端操作。
     *
     * 关键不变量：
     * 1. 不走 /chat SSE 流 —— 这些是纯前端动作（无 AI 处理）
     * 2. MessageInput 端已校验：用户只敲了 `/cmd ` + 空白（或就 `/cmd`），任何额外文本
     *    都会走 send（自动回退到普通消息路径）
     * 3. 前置条件不满足时弹 ToastDialog 提示（如「/backtree 当前没有可用会话」）
     *
     * 与 ChatHeader 按钮完全等价：
     *   /backtrack ↔ ChatHeader ⏱ 按钮（toggleCheckpoints → CheckpointPanel）
     *   /settings   ↔ ChatHeader ⚙ 按钮（settingsVisible = true）
     *   /setup     ↔ ChatHeader 🪄 按钮（setupVisible = true）
     *   /worktree   ↔ DataAnalysisTree 触发按钮（openPanel()）
     *   /reload     刷新当前会话（refreshConversation，重拉 messages）
     *   /help       独立弹窗（HelpDialog）
     */
    async runFrontAction(cmd) {
      if (!cmd || !cmd.name) return
      const sid = this.currentSessionId

      switch (cmd.name) {
        case 'backtrack': {
          // 打开历史版本面板（与 ChatHeader ⏱ 按钮同路径），用户从面板里点具体版本恢复
          if (!sid) {
            this.showToast('当前没有可用会话', '请先新建或选择一个会话，再查看历史版本。')
            return
          }
          this.showCheckpoints = true
          return
        }
        case 'settings':
          this.settingsVisible = true
          return
        case 'setup':
          // 非阻塞浮窗：不需要 sid，无前置条件
          this.setupVisible = true
          return
        case 'reload':
          if (!sid) {
            this.showToast('当前没有可用会话', '请先新建或选择一个会话，再刷新会话内容。')
            return
          }
          await this.refreshConversation(sid)
          return
        case 'worktree':
          if (!sid) {
            this.showToast('当前没有可用会话', '工作树与具体会话绑定，请先新建或选择一个会话。')
            return
          }
          this.sidebarView = 'files'
          return
        case 'help':
          this.helpVisible = true
          return
        default:
          console.warn('[runFrontAction] 未知的前端动作命令:', cmd.name)
      }
    },

    /**
     * 简洁提示弹窗：用于 slash 命令前置条件不满足（如无 sid）等轻量提示场景。
     * 与 ConfirmDialog 不同 —— 单按钮「知道了」直接关闭，不阻塞业务流程。
     */
    showToast(title, message = '') {
      this.toast = { visible: true, title, message }
    },
    closeToast() {
      this.toast.visible = false
      // 简洁提示弹窗关闭 → 把焦点还给输入框（用户看完提示应当能继续打字）
      this.focusInput()
    },
    /**
     * 全局「归还焦点到输入框」入口。dialog / panel / refresh / tool approval
     * / resume 等事件回调里调一下，光标自动回到 MessageInput 的 textarea。
     * 走 $nextTick 等 DOM 更新完再 focus，避免和 v-if 过渡 / input 状态变更撞车。
     * `?.` 链式调用防御 $refs.messageInput 不可用的情况（冷启动未挂载等）。
     *
     * 文件视图（sidebarView === 'files'）下短路：不抢焦点 —— 文件树快捷键（Cmd+C/V/D/X 等）
     * 要求焦点留在文件树上，否则 `_shortcutGuard` 检测到 textarea 会拒绝响应，
     * 让用户的复制 / 粘贴 / 删除等操作全部失效。
     *
     * 例外：`force=true` 强制抢焦点 —— 用于「双击 /」快捷键（用户明确要把焦点切到输入框），
     * 此时即便在 files 视图也要抢。
     */
    focusInput(force = false) {
      if (!force && this.sidebarView === 'files') return
      this.$nextTick(() => {
        const mi = this.$refs.messageInput
        if (mi && typeof mi.focusTextarea === 'function') mi.focusTextarea()
      })
    },
    /**
     * 弹窗 / 面板关闭 → 把焦点还给输入框。复用同一段逻辑避免每个组件 @close
     * 都包一层调用（escape / overlay click / ×按钮三条路径都要覆盖）。
     *
     * 注意：是「close 后焦点归还」而不是「open 时抢占」—— 因为 MessageInput 的
     * 初始 focus 已经在用户开始输入时自然发生，弹窗 open 反而是借焦点出去。
     *
     * 例外：showRestoreConfirm（恢复历史版本）→ 用户做完决定后**不应**抢焦点，
     *   因为会立即触发新一轮流程；cancelRestore / confirmRestore 自己显式处理。
     *   这里不监听 showRestoreConfirm。
     */
    onPanelClosed() {
      this.focusInput()
    },

    /**
     * 撤回用户消息：
     * 1. 找「此用户消息之前最近的 AI 消息」的 checkpointId 作为回溯目标
     * 2. POST /interrupt → 让后台 workflow 立即停（astream 中段会 1-2s 内感知）
     * 3. 等 SSE interrupt 事件到达（timeout 3s 兜底）→ astream 真的 raise GraphInterrupt
     * 4. POST /backtrack → langgraph 指针回溯（CheckpointJanitor.retarget_to）
     * 5. 拉 get_conversation → messages 数组刷新（这条用户消息和后面的 AI 都消失）
     * 6. 把原 message.content 写到 MessageInput 输入框（files v1 不恢复）
     *
     * /backtrack slash 命令复用同一个底层（runBacktrack），区别只是「找最近 AI 消息」
     * 而不是「找 userMessage 之前的 AI 消息」。
     */
    async handleWithdraw(userMessage) {
      if (!userMessage || !this.currentSessionId) return
      const msgIndex = this.messages.findIndex(m => m === userMessage)
      if (msgIndex === -1) return

      let backtrackCid = null
      for (let i = msgIndex - 1; i >= 0; i--) {
        const prev = this.messages[i]
        if (prev && prev.role === 'ai') {
          backtrackCid = prev.additional_kwargs?.last_checkpoint_id || prev.checkpointId
          if (backtrackCid) break
        }
      }
      if (!backtrackCid) {
        console.warn('[handleWithdraw] 没有前一轮 checkpoint，无法撤回')
        return
      }

      await this.runBacktrack({
        sid: this.currentSessionId,
        backtrackCid,
        withdrawText: userMessage.content || '',
        withdrawSid: this.currentSessionId
      })
    },

    /**
     * 通用回溯执行器。handleWithdraw（用户点 ↶ 按钮）和 /backtrack slash 命令都走这里。
     * withdrawText 为 null 表示不回填输入框（slash 命令路径，撤回整轮对话但保留输入框当前内容）。
     */
    async runBacktrack({ sid, backtrackCid, withdrawText, withdrawSid }) {
      try {
        // 2. 设置 SSE interrupt resolver（必须先于 POST /interrupt 注册：避免 race —
        //    后端 astream 一旦感知到 Redis hash 就会立刻 yield interrupt 事件，
        //    若 resolver 还没挂上、SSE handler 检查 this._withdrawInterruptResolver 为 null 就直接吞掉事件，
        //    然后 handleWithdraw 在这干等 5s 超时 —— 撤回失败）。
        let _interruptArrived
        const _interruptPromise = new Promise((resolve, reject) => {
          let done = false
          const finish = (err) => {
            if (done) return
            done = true
            clearTimeout(timer)
            this._withdrawInterruptResolver = null
            if (err) reject(err)
            else resolve()
          }
          // timeout 5s 兜底：astream 卡在 tool_execution_node 太久（tool 执行慢）时强制继续 backtrack
          const timer = setTimeout(() => finish(new Error('等 SSE interrupt 事件超时（5s）')), 5000)
          // SSE interrupt handler 调用 resolver 时触发 resolve
          this._withdrawInterruptResolver = () => finish()
        })
        _interruptArrived = _interruptPromise

        // 3. POST /interrupt — fire-and-forget（不 await：触发 backtrack 的唯一信号是 SSE interrupt 事件，
        //    不是这个 API 是否返回 200；写 Redis hash 是后端 astream 感知中断的前置条件，
        //    但「hash 写完」≠「astream 已 raise GraphInterrupt」，
        //    真正的状态权威在 SSE 事件上）。
        fetch(`/chat/${sid}/interrupt`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ interrupt_reason: 'user_withdraw_message' })
        }).catch(err => {
          console.warn('[handleWithdraw] POST /interrupt 发送失败（不影响撤回，后端 SSE 也会兜底）:', err)
        })

        // 4. 等 SSE interrupt 事件真的到达 —— 这是触发 backtrack 的唯一信号
        // 必须等 astream 真的 raise GraphInterrupt 否则:
        //   - backtrack 清掉 interrupt:{sid} hash + retarget_to 覆写 LATEST_POINTER
        //   - astream 继续跑完 → _save_round_checkpoint 写新 cid → LangGraph 自动覆盖 LATEST_POINTER
        //   - 撤回失败：刷新看到完整本轮对话
        try {
          await _interruptArrived
        } catch (e) {
          console.warn('[handleWithdraw] SSE interrupt 未在 5s 内到达，强制 backtrack（astream 可能卡在 tool 执行）:', e.message)
        }

        // 5. 回溯
        const btResp = await fetch(`/chat/${sid}/backtrack`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ backtrack_id: backtrackCid })
        })
        if (!btResp.ok) throw new Error('回溯失败')

        // 5. 拉新 conversation（这条 user message 和后续 AI/工具消息都消失）
        const convResp = await fetch(`/chat/${sid}/conversation`)
        if (!convResp.ok) throw new Error('获取回溯后状态失败')
        const conv = await convResp.json()
        this.$refs.messageList?.suppressNextScroll()
        this.messages = this.processConversationMessages(conv.messages)

        // 同步文件树 + 侧栏
        this.$refs.sidebar?.reloadFiles?.()

        // 6. 把原消息文本回填到输入框 + 持久化到 localStorage（跨 F5 存活）
        //    loadConversation 时会检测 entry 自动 setInputText；用户发送 / 主动清空时清掉
        //    withdrawText === null 走 /backtrack 路径，不回填（输入框当前内容视为"还想保留"）
        const storageKey = withdrawSid || sid
        if (withdrawText !== null && withdrawText !== undefined) {
          this.$refs.messageInput?.setInputText(withdrawText)
        }
        const withdrawnText = withdrawText || ''
        if (withdrawnText) {
          localStorage.setItem(`chatme-withdraw-pending:${storageKey}`, withdrawnText)
        } else {
          localStorage.removeItem(`chatme-withdraw-pending:${storageKey}`)
        }

        // 5.5 【按后端响应同步中断状态】—— 与 handleRestream 模式一致
        //     防御 SSE 第二个 interrupt 事件在 handleWithdraw 重置后再次置 true：
        //     backtrack 已清掉 redis hash，后端 interrupted_info 反映权威状态
        if (conv.interrupted_info?.reason) {
          this.isInterrupted = true
          this.isInterruptedSessionId = sid
          this.interruptReason = conv.interrupted_info.reason
          const lastAiMsg = this.messages.filter(m => m.role === 'ai').pop()
          if (lastAiMsg) lastAiMsg.interruptReason = conv.interrupted_info.reason
        } else {
          this.isInterrupted = false
          this.isInterruptedSessionId = null
          this.interruptReason = ''
        }

        // 清掉流式相关状态（消息已变）
        this.isLoading = false
        // _pendingQueue 是 Map<sid, QueueEntry[]>（见 data() 声明），
        // 切 session 时由 loadConversation 的 _loadQueueForSession 负责重拉；这里不能赋 [] 破坏类型
        this._activeStreamingSessions.delete(sid)
        this._streamingMessages.delete(sid)
        this._streamingMeta.delete(sid)
        this._activeStreamingSessions = new Set(this._activeStreamingSessions)
        this.cleanupLoadingState()

        // 侧栏 sync（直接复用 step 5 的 conv，不再发一次 GET /conversation；
        //     backtrack 已经带了 refresh 会话的效果，再刷一次纯属浪费）
        const sidebarConv = this.conversations.find(c => c.session_id === sid)
        if (sidebarConv && conv.title) {
          sidebarConv.title = conv.title
          sidebarConv.updated_at = conv.updated_at
        }

        this.$nextTick(() => {
          this.$refs.messageList?.scrollToBottom()
        })
      } catch (err) {
        console.error('[runBacktrack] 回溯失败:', err)
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
    // Sidebar @reload-files 兜底：当前 sidebar 内部已经自管数据，这里主要是占位
    onSidebarReloadFiles() { /* sidebar 内部已 fetch */ },
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
      // 隐藏 `done` 工具调用:它是新 graph 的"思维链结束标记",无信息价值,
      // 显示在思考链里只会增加噪声(final_node 的回复本身就是"链结束"的视觉信号)。
      // 后端 context_assembly_node 已用 RemoveMessage 把它从 messages 里删了,
      // 这里再过滤一次确保流式响应过程中不会闪一下再消失。
      if (data.content?.name === 'done') {
        return message
      }
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
                  // 不再缓存 executionEnv —— MessageItem 直接读 toolCall.args.local 渲染
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
        // 不再缓存 executionEnv —— MessageItem 直接读 toolCall.args.local 渲染
        sessionId,
        // 不再缓存 targetArr 引用：onToolDecision 时按 sessionId + messageIndex/toolIndex
        // 重新解析（snapshot 优先 → 当前 messages 兜底），避免 stale 引用导致写错位置
      }

      // 停响应计时器。streamTimer / _streamingMessages / _streamingMeta 全部保留：
      //   - streamTimer 跨 approval 持续累加 elapsedMs，handlePermissionResumeStream 用
      //     `if (!has)` 检查跳过重启，闭包 startTs 保持 sendMessage 时刻
      //   - _streamingMessages / _streamingMeta 必须保留，否则 timer body `arr = get(...)` 返回
      //     undefined，timer 停止写 elapsedMs，数字又会冻结
      //   - _activeStreamingSessions.delete 保留：approval 等待时 SSE 流已停，无新事件进入，
      //     不再走 sessionChanged 分支
      this.stopResponseTimer()
      this._activeStreamingSessions.delete(requestSessionId)
      this._activeStreamingSessions = new Set(this._activeStreamingSessions)
    },
    async onToolDecision(decision) {
      // decision: 'approve' | 'this-time-only' | 'deny' | 'feedback:<text>'
      // 后端 permissions.request_approval 看到 'feedback:' 前缀会返回 ("feedback", text)，
      // 由 _permission_wrap 包成 ToolMessage 让 LLM 看到用户指引并重新尝试调用。
      // 防止快速双击 / 连点导致跑两次 onToolDecision：第二次会再起一个 resume 流，
      // 那个流推过来的 tool_call_name 跟第一条 entry 对不上（_pendingApproval 已被第一条
      // 置 false / id 是另一条 run_id），merge 会再 push 一条新 entry → 重复显示。
      // :disabled 是 Vue 异步刷 DOM 的，同一 tick 内的连点挡不住，必须在 JS 层再加一道。
      if (this.submittingToolDecision || this.permissionResumeInFlight) return
      if (!this.pendingToolApproval) return
      const { sessionId } = this.pendingToolApproval
      if (!sessionId) {
        this.pendingToolApproval = null
        return
      }

      // deny / feedback 时：先把当前 entry 在前端本地写入 synthetic result，
      // 让用户点完按钮后立刻能看到「rejected / feedback」文案，不必等 resume SSE 几百毫秒延迟。
      // 后端 resume_permission_stream 走 _build_intercepted_tool_call_events（on_chain_end 兜底）
      // 会为所有决策（含 deny / feedback）都 emit tool_call_name + tool_call_result，
      // 其 tool_call_result 会用后端合成的 ToolMessage content 覆盖本地的 result（两者文案对齐）。
      //
      // 文案严格对齐后端 permissions.py:_rejected_tool_result / _feedback_tool_result
      // 的模板，保证前端展示与后端注入到 LangGraph state 的 ToolMessage content
      // 完全一致（LLM 看到什么，前端 UI 就展示什么）。
      //
      // ⚠️ 关键：这里必须**保留** _pendingApproval: true（绝对不能置 false）！
      // resume 流的 tool_call_name 进 mergeToolCallStart 时需要按 step 1
      // (_pendingApproval && name === data.content.name) 命中这条 entry 原地更新，
      // 把 id 刷成后端真实 tc_id、_pendingApproval 置 false。如果这里把 _pendingApproval
      // 置成 false，step 1 失配 → step 2/3 fallback 也都找不到 → 最终 push 一条新 entry
      // → 重复显示（同 permission 请求会看到两条相同 tool 的结果）。
      //
      // approve / this-time-only 不走这条本地写入：gate 真正执行 execute(request)，
      // on_tool_start + on_tool_end 会正常发，mergeToolCallStart / mergeToolCallResult
      // 会按正常路径更新 entry，状态完全由 resume 流接管。
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
            // 必须保留 _pendingApproval: true（不能置 false）——resume 流到达时
            // mergeToolCallStart step 1 (_pendingApproval && name) 要命中这条 entry
            // 原地更新；若置 false 会被 fallback push 一条新 entry → 重复显示。
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
        // 焦点还给输入框（用户做了决策 = 已不再需要与审批 UI 交互）。
        // resume 流仍在后台跑，但 permissionResumeInFlight 守门，发送按钮禁用，
        // 用户可以先在输入框打字准备后续消息，等 resume 完成自动接上。
        this.focusInput()
        // 走 SSE 流：复用 handleResume 的 SSE 处理逻辑（content / reasoning / tool_call / done）
        await this.handlePermissionResumeStream(resumeResp)
      } catch (error) {
        console.error('tool decision resume error:', error)
        this.pendingToolApproval = null
        // 出错也清黄点（用户已经提交了决定 = 状态解除）
        this.markSessionApprovalResolved(sessionId)
        // 出错路径也要归还焦点（用户已经把决策交了 = 该回主输入流）
        this.focusInput()
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
        // 不动 startTs：timer 用闭包 startTs（sendMessage 时刻），跨审批等待持续累加；
        // spread 后对象上 startTs 丢失不影响 timer body（它直接读闭包变量）。
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
      // 已有 timer（审批等待期间一直跑着）就不重置 startTs，让 elapsed 继续累加
      if (!this._streamTimers.has(requestSessionId)) {
        this.startStreamTimer(requestSessionId, this.messages[aiMessageIndex])
      }
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
        this.$refs.sidebar?.reloadFiles?.()

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
            this.$refs.sidebar?.reloadFiles?.()

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
          // 并行拉每个会话的定时任务，写入 scheduledTasksMap
          // ——侧栏每行的 ⏰ 指示靠这个 Map 渲染，单拉当前会话不够
          // 失败静默由 fetchScheduledTasks 内部 console.warn 兜底
          await Promise.all(
            data.map(c => this.fetchScheduledTasks(c.session_id))
          )
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
    /**
     * 校验 sessionId 是否合法（同时接受新版 12 位 hex 和旧版 32 位 hex）。
     * 与 backend/ChatMe/APIRouter/static_file.py 的 SESSION_ID_PATTERN 保持一致，
     * 避免前端用一套正则、后端用另一套导致"前端认为合法、后端 404"的撕裂场景。
     */
    isValidSessionId(sid) {
      if (!sid || typeof sid !== 'string') return false
      const s = sid.trim()
      return /^[0-9a-f]{12}$/i.test(s) || /^[0-9a-f]{32}$/i.test(s)
    },
    /**
     * 显示 NotFoundView 浮层 + 启动 10s 自动跳转 timer + 100ms 进度条 tick。
     * 幂等：已显示时直接 return，避免重复触发多个 setTimeout。
     */
    showNotFound() {
      if (this._notFoundActive) return
      this._notFoundActive = true
      this._notFoundRemaining = 10

      // 100ms tick 驱动进度条（不用 1s tick —— 进度条平滑收缩比阶跃好看）
      this._notFoundTickInterval = setInterval(() => {
        this._notFoundRemaining = Math.max(0, this._notFoundRemaining - 0.1)
      }, 100)

      // 10s 后强制跳主页（不依赖 hideNotFound cleanup —— 浮层可能因其他原因被 hide）
      this._notFoundTimer = setTimeout(() => {
        this._navigateHome()
      }, 10000)
    },
    /**
     * 隐藏 NotFoundView 浮层 + 清理所有 timer。
     * 调用方：用户点击触发 _navigateHome / watcher 主动取消 / beforeUnmount。
     */
    hideNotFound() {
      if (this._notFoundTimer) {
        clearTimeout(this._notFoundTimer)
        this._notFoundTimer = null
      }
      if (this._notFoundTickInterval) {
        clearInterval(this._notFoundTickInterval)
        this._notFoundTickInterval = null
      }
      this._notFoundActive = false
      this._notFoundRemaining = 10
    },
    /**
     * 关闭浮层 + 跳主页（/）。被 showNotFound 10s 后自动调，或用户点击触发。
     *
     * 用 location.replace 而不是 $router.push —— 清除 Electron/Vite 残留的 /<sid>
     * 路径，避免下次 reload 又触发 fallback 显示动画（用户明明已经「回主页」了
     * 再 reload 应该看到主页，不应该再看到动画）。整个 SPA 状态全部重置，代价
     * 是页面会闪一下；考虑到 NotFound 浮层期间用户没法做任何交互，这点代价可接受。
     *
     * 协议分流：
     * - dev (http://localhost:18211/<sid>) → 直接跳 /，Vite SPA fallback 会 serve index.html
     * - prod (file:///path/to/dist/<sid>) → 必须保留 dirname，把 basename 替换为
     *   index.html（file:/// 直接跳是文件系统根，浏览器/渲染进程找不到 app）
     */
    _navigateHome() {
      this.hideNotFound()
      if (window.location.pathname !== '/') {
        if (window.location.protocol === 'file:') {
          const newPath = window.location.pathname.replace(/[^/]+$/, 'index.html')
          window.location.replace(window.location.origin + newPath)
        } else {
          // http/https：直接跳根，URL bar 干干净净显示 <origin>/
          window.location.replace('/')
        }
      } else if (this.$route.path !== '/') {
        this.$router.push('/')
      }
    },
    /**
     * 中断态专属：回溯到最近一段已完成 checkpoint + 重新发送触发该轮的用户消息。
     *
     * 与 MessageItem 上「重新生成」按钮的语义完全一致：复用 handleRestream 的标准流程
     *   1. POST /chat/{sid}/backtrack 把 LangGraph state 回退到上一轮 checkpoint
     *   2. 重新拉取历史 messages
     *   3. 把触发中断的用户消息 push 回 messages
     *   4. 走 /chat/ 重新生成
     *
     * 调用时机：MessageItem @restart-session（仅在 isCurrentSessionInterrupted 可见）。
     */
    restartConversation() {
      if (!this.currentSessionId || this.isLoading) return
      // 找到被中断的最新 AI 消息 —— handleRestream 会自动 fallback 到上一轮 AI 的 checkpointId
      let interruptedAiMessage = null
      for (let i = this.messages.length - 1; i >= 0; i--) {
        const msg = this.messages[i]
        if (msg.role === 'ai') {
          interruptedAiMessage = msg
          break
        }
      }
      if (!interruptedAiMessage) return
      // 复用 handleRestream：它会自动找上一轮 checkpoint + 找到 user message + backtrack + 重新生成
      this.handleRestream(undefined, interruptedAiMessage)
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

    // ===== 消息队列：拉取 + 入队 + 删 + 清空 + drain =====
    // 与后端 /chat/{sid}/queue 端点对齐（FIFO LIST，db1 queue:{sid}）。
    // local 是 source of truth，但 _pendingQueue 始终以 server 返回的 items 覆盖（避免乐观更新与服务端顺序错位）。

    /**
     * 拉取指定 session 的排队消息；结果写入 _pendingQueue。
     * 切会话时由 loadConversation 调一次；enqueue / remove / clear 后也会 re-fetch 同步本地。
     */
    async _loadQueueForSession(sid) {
      if (!sid) return
      try {
        const r = await fetch(`/chat/${sid}/queue`)
        if (r.ok) {
          const data = await r.json()
          let items = data.items || []
          // —— 关键：过滤掉乐观 slice 出去的 in-flight head ——
          // 乐观 slice 后本地已经没有 head，但 Redis 暂时还有（DELETE 没发出）；
          // 此时 _enqueueMessage / _removeQueueItem 触发 reload，如果不过滤，
          // 会把 head 镜像回本地 → 下次 drain 递归把同一条 head 再 send 一次。
          // per-session 最多 1 个 in-flight head（_drainInFlight 串行化），slice(1) 即可。
          if (this._drainedNotDeleted?.has(sid) && items.length > 0) {
            items = items.slice(1)
          }
          const m = new Map(this._pendingQueue)
          m.set(sid, items)
          this._pendingQueue = m
          this._queueLoaded.add(sid)
        }
      } catch (e) {
        console.warn('[queue] load failed:', e)
      }
    },

    /**
     * 把一条消息追加到 sid 的队列尾部（后端 RPUSH + 本地 re-fetch）。
     * MessageInput.handleSend emit 'send' 之前已清空 inputText / files / quote，本方法只做"加排队卡"一件事。
     */
    async _enqueueMessage(sid, payload) {
      try {
        const r = await fetch(`/chat/${sid}/queue`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: payload.message,
            quote: payload.quote ?? null,
          }),
        })
        if (!r.ok) {
          const err = await r.json().catch(() => ({}))
          console.warn('[queue] enqueue failed:', err.detail || `HTTP ${r.status}`)
          return false
        }
        // 用服务端权威顺序覆盖本地（避免本地 pending 顺序与 Redis 不一致）
        await this._loadQueueForSession(sid)
        return true
      } catch (e) {
        console.warn('[queue] enqueue error:', e)
        return false
      }
    },

    /**
     * MessageInput 卡片 × 按钮：按 idx 删单条。idx 是 FIFO 顺序（0 = 最先入队）。
     */
    async _removeQueueItem(sid, idx) {
      if (!sid || idx === undefined || idx === null) return
      try {
        const r = await fetch(`/chat/${sid}/queue?idx=${idx}`, { method: 'DELETE' })
        if (!r.ok) {
          console.warn('[queue] remove failed:', r.status)
          return
        }
        await this._loadQueueForSession(sid)
      } catch (e) {
        console.warn('[queue] remove error:', e)
      }
    },

    /**
     * MessageInput 顶部「全部清空」：DELETE /chat/{sid}/queue（无 idx → 整 key 删除）。
     */
    async _clearQueue(sid) {
      if (!sid) return
      try {
        const r = await fetch(`/chat/${sid}/queue`, { method: 'DELETE' })
        if (!r.ok) {
          console.warn('[queue] clear failed:', r.status)
          return
        }
        const m = new Map(this._pendingQueue)
        m.set(sid, [])
        this._pendingQueue = m
      } catch (e) {
        console.warn('[queue] clear error:', e)
      }
    },

    /**
     * 弹队列头并送出去。
     * 行为：
     *   1. **乐观 slice**：先从 _pendingQueue[sid] slice(1) 出去 → MessageInput 立刻
     *      看到 queue.length -= 1（UI 在「发送的那一刻」就响应减少，不等 SSE 流跑完）
     *   2. await sendMessage(head.message) → 拿到 fetch 是否 200
     *   3. 成功 → DELETE /chat/{sid}/queue?idx=0（不 await；与 SSE 同时进行）；本地不再重复 slice
     *   4. 失败 → reload 从 Redis 拉回 head（DELETE 还没发出去，Redis 还有 head）
     *
     * 为什么要乐观 slice（v0.1.7+ 改）：
     *   旧实现在 await sendMessage 之后才 slice，N 条排队时要等 N 轮完整流式才逐条减少，
     *   UI 反馈延迟到「第二个发完」才响应，与用户期望不符。改为入口立即 slice，
     *   失败靠 catch 块 reload 兜底。
     *
     * 为什么要 await sendMessage：
     *   sendMessage + DELETE 都 fire-and-forget 的旧实现，fetch 失败时（网络断 / 后端 500），
     *   消息已经从 UI 卡上消失、Redis 里也被 DELETE，真丢了。
     *   现在改为先 await 验证 sendMessage 启动成功再 DELETE；失败 catch 块从 Redis 拉回 head 兜底。
     */
    /**
     * SSE 流结束（done / error / interrupt）后清理 per-session 流式状态。
     * 集中在一个 helper 里，避免散在 4 个 SSE 分支各写一遍漏一处。
     * 必须保证：
     *   - _activeStreamingSessions.delete + new Set 触发侧栏状态点 watcher / drain watcher
     *   - _sendingLock.delete + new Map（关键！SSE 循环期间 sendMessage 不 return，finally 永不跑，锁要主动释放）
     *   - snapshot 引用清理（_streamingMessages / _streamingMeta）让下一次切回走 get_conversation
     */
    _finishStreamingSession(sid) {
      if (!sid) return
      // _activeStreamingSessions 清理（触发 watcher）
      this._activeStreamingSessions.delete(sid)
      this._activeStreamingSessions = new Set(this._activeStreamingSessions)
      // _sendingLock 释放（sendMessage 在 SSE 循环期间永不 return，finally 不可靠）
      if (this._sendingLock.has(sid)) {
        const m = new Map(this._sendingLock)
        m.delete(sid)
        this._sendingLock = m
      }
      // 流式 timer + snapshot 清理
      this.stopStreamTimer(sid)
      this._streamingMessages.delete(sid)
      this._streamingMeta.delete(sid)
    },

    async _drainQueueAndSend(sid) {
      const queue = this._pendingQueue.get(sid) || []
      if (queue.length === 0) return
      const head = queue[0]
      // 同 sid 防并发：drain / done handler / currentSessionId watcher 各自都可能触发
      // _tryDrainQueue(sid)，导致同一 head 在 M1 正在 fetch 时，M2 也进入本函数。
      // 用 _drainInFlight set 守住：M1 进入时 set(sid)，M2 看见 set 里有自己就 early return；
      // M1 finally 块清理掉，允许下一轮 head 由 SSE done handler 的 _tryDrainQueue 再次触发。
      // 这层是 _sendingLock 的补充（_sendingLock 在 sendMessage 内部 acquire/finally release，
      // 不知道 drain 还没完成；这里在 drain 粒度上再加一道）。
      if (!this._drainInFlight) this._drainInFlight = new Set()
      if (this._drainInFlight.has(sid)) {
        console.log(`[queue] drain already in flight for ${sid}, skip`)
        return
      }
      try {
        const s = new Set(this._drainInFlight)
        s.add(sid)
        this._drainInFlight = s

        // —— 乐观 slice：UI 在发送那一刻就减少（用户期望 head 立刻从排队卡消失）——
        // sendMessage 还没发出去就先 slice 本地队列 → Vue 响应式立刻让 MessageInput
        // 看到 queue.length -= 1（v-if="queue.length > 0" 自动隐藏 / 徽章 -1）。
        // 此时 Redis 暂时还有 head（要等 sendMessage 成功后才 DELETE），
        // 必须把 sid 记到 _drainedNotDeleted，让后续 _loadQueueForSession 跳过这个 head，
        // 否则并发 _enqueueMessage / _removeQueueItem 触发 reload 会把 head 镜像回本地，
        // 下次 drain 递归把同一条 head 重新 send —— 实测会发两次。
        if (!this._drainedNotDeleted) this._drainedNotDeleted = new Set()
        if (!this._drainedNotDeleted.has(sid)) {
          const ds = new Set(this._drainedNotDeleted)
          ds.add(sid)
          this._drainedNotDeleted = ds
        }
        const m = new Map(this._pendingQueue)
        const cur = this._pendingQueue.get(sid) || []
        // slice(1) 时如果别的 enqueue 在中间又加了新消息（比如用户同时点了 ✕ 又敲了新文本入队），
        // 也只丢已 send 的 head，新入队仍在 cur[1:]
        m.set(sid, cur.slice(1))
        this._pendingQueue = m

        await this.sendMessage({
          message: head.message,
          files: [],
          processedOutputs: [],
        })
        // sendMessage 成功（其内部 finally 已释放 _sendingLock，本函数不再碰） →
        // 删 Redis idx=0（与本地 slice 一致；fire-and-forget DELETE，失败仅 warn）
        fetch(`/chat/${sid}/queue?idx=0`, { method: 'DELETE' })
          .catch(e => console.warn('[queue] drain delete failed:', e))
        // DELETE 已发出 → Redis 即将少 head，_loadQueueForSession 不再需要过滤这个 head。
        // 立即从 in-flight 集合移除（不等 DELETE 网络返回，因为 load 看到 head 仍可能短暂存在；
        // 万一 DELETE 真失败，下次 drain 仍会从 Redis 取到 head 重发——这是 server-side 一致性兜底）。
        if (this._drainedNotDeleted?.has(sid)) {
          const ds = new Set(this._drainedNotDeleted)
          ds.delete(sid)
          this._drainedNotDeleted = ds
        }
        // head 已在入口处乐观 slice 掉，这里不再重复 slice。
        // 队列还有 → 触发下一轮 drain。
        // 不在本函数递归（会让 stack 太深 + SSE done handler 已经会调 _tryDrainQueue，双 trigger 容易失控），
        // 走 $nextTick 异步调度，让 Vue 微任务队列清完再发起下一轮。
        if ((this._pendingQueue.get(sid) || []).length > 0 && !this._activeStreamingSessions.has(sid)) {
          this.$nextTick(() => this._tryDrainQueue(sid))
        }
      } catch (e) {
        // sendMessage 失败（网络断 / 后端 500 / 用户主动中断后端拒绝）→
        // 本地已经乐观 slice 出去，但 Redis 还有 head（DELETE 没发出去）→
        // reload 从 Redis 拉回 head 回 UI（_loadQueueForSession 是 server-authoritative 同步点；
        // 此处 sid 仍在 _drainedNotDeleted → 过滤掉 head → reload 看不到 head，似乎矛盾？
        // 不矛盾：catch 在 DELETE 之前 fail，DELETE 没发出，Redis 还有 head。
        // 我们希望 catch reload 把 head 还回 UI，所以 catch 里要先清理 _drainedNotDeleted 再 reload，
        // 才能让 head 重新进 local（否则会被 slice 掉再次过滤）。
        console.warn(`[queue] drain failed for ${sid}, restoring head from Redis:`, e)
        if (this._drainedNotDeleted?.has(sid)) {
          const ds = new Set(this._drainedNotDeleted)
          ds.delete(sid)
          this._drainedNotDeleted = ds
        }
        this.showToast('排队发送失败', '该消息仍在排队中，下次流式结束后会自动重试。')
        await this._loadQueueForSession(sid)
      } finally {
        // 无论成功失败，离开 drain 临界区 — 下一条 head（若存在）由 SSE done handler 触发 _tryDrainQueue。
        if (this._drainInFlight?.has(sid)) {
          const s = new Set(this._drainInFlight)
          s.delete(sid)
          this._drainInFlight = s
        }
      }
    },

    /**
     * drain 的统一入口。
     * - sid 不在 _activeStreamingSessions（即流式已结束）且队列非空 → 准备 drain
     * - 用户当前在 sid 上 → 立即 drain
     * - 用户不在 sid 上 → 推迟到 currentSessionId 切回时（currentSessionId watcher 处理）
     * 被 _activeStreamingSessions watcher 与 currentSessionId watcher 共用。
     */
    _tryDrainQueue(sid) {
      if (!sid) return
      // 仍在流式（极端 race：调用方与新发起 sendMessage 之间）→ 不 drain
      if (this._activeStreamingSessions.has(sid)) return
      const queue = this._pendingQueue.get(sid) || []
      if (queue.length === 0) return
      if (sid !== this.currentSessionId) {
        // 用户不在该 sid 上 → 推迟（currentSessionId 切回时 watcher 会处理）
        this._queueDrainDeferred.add(sid)
        this._queueDrainDeferred = new Set(this._queueDrainDeferred)
        return
      }
      this.$nextTick(() => this._drainQueueAndSend(sid))
    },

    /** MessageInput 卡片 × 按钮 → 当前会话删 idx */
    async onRemoveQueueItem(idx) {
      if (!this.currentSessionId) return
      await this._removeQueueItem(this.currentSessionId, idx)
    },

    /** MessageInput 顶部「全部清空」 → 当前会话清空 */
    async onClearQueue() {
      if (!this.currentSessionId) return
      await this._clearQueue(this.currentSessionId)
    },

    // ===== 定时任务：拉取 + CRUD 转发 =====

    /**
     * 拉取指定 session 的定时任务列表；结果写入 scheduledTasksMap
     * - 切会话时由 loadConversation 调用
     * - 面板 ↻ 按钮触发（让用户主动刷新）
     * - 失败静默（网络抖动不该让 UI 红屏）
     */
    async fetchScheduledTasks(sessionId) {
      if (!sessionId) return
      this._scheduledTasksRefreshing = true
      try {
        const { listScheduledTasks } = await import('./utils/api.js')
        const data = await listScheduledTasks(sessionId)
        const tasks = data.tasks || []
        // 新 Map 触发响应式（Vue 2 Set/Map 必须整替换）
        const next = new Map(this.scheduledTasksMap)
        next.set(sessionId, tasks)
        this.scheduledTasksMap = next
      } catch (e) {
        console.warn('[scheduled-tasks] fetch failed:', e)
      } finally {
        this._scheduledTasksRefreshing = false
      }
    },

    /**
     * 找出 task_id 所属的 session_id（用于 toggle/run/delete 的本地乐观更新 +
     * 失败回滚重拉）。侧栏展开后用户可能在任意会话的任务上点 ⏸/▶/⚡/🗑，不能用 currentSessionId 推断。
     */
    _findSessionForTask(taskId) {
      for (const [sid, tasks] of this.scheduledTasksMap.entries()) {
        if (tasks && tasks.some(t => t.task_id === taskId)) return sid
      }
      return null
    },

    /** 行内 ⏸/▶ 切换 enabled */
    async onScheduledTaskToggle(taskId, newEnabled) {
      const { updateScheduledTask } = await import('./utils/api.js')
      try {
        await updateScheduledTask(taskId, { enabled: newEnabled })
        // 本地乐观更新：找到 task 所属 session，更新那条 list
        const sessionId = this._findSessionForTask(taskId)
        if (sessionId) {
          const cur = this.scheduledTasksMap.get(sessionId) || []
          const next = cur.map(t =>
            t.task_id === taskId ? { ...t, enabled: newEnabled } : t
          )
          const m = new Map(this.scheduledTasksMap)
          m.set(sessionId, next)
          this.scheduledTasksMap = m
        }
      } catch (e) {
        console.error('[scheduled-tasks] toggle failed:', e)
        const sessionId = this._findSessionForTask(taskId)
        if (sessionId) await this.fetchScheduledTasks(sessionId)
      }
    },

    /** ⚡ 立即运行一次 */
    async onScheduledTaskRun(taskId) {
      const { runScheduledTask } = await import('./utils/api.js')
      try {
        await runScheduledTask(taskId)
        // 给一个简短反馈（不弹 toast，保持简洁）
        console.info(`[scheduled-tasks] 触发任务 ${taskId.slice(0, 8)}`)
        // 触发后任务状态可能改变（status / last_run），重拉该 session 让 UI 跟上
        const sessionId = this._findSessionForTask(taskId)
        if (sessionId) await this.fetchScheduledTasks(sessionId)
      } catch (e) {
        console.error('[scheduled-tasks] run failed:', e)
      }
    },

    /** 🗑 删除（小红叉二次确认后由 ScheduledTaskItem emit） */
    async onScheduledTaskDelete(taskId) {
      const { deleteScheduledTask } = await import('./utils/api.js')
      try {
        await deleteScheduledTask(taskId)
        // 本地立即移除（不 reload）
        const sessionId = this._findSessionForTask(taskId)
        if (sessionId) {
          const cur = this.scheduledTasksMap.get(sessionId) || []
          const next = cur.filter(t => t.task_id !== taskId)
          const m = new Map(this.scheduledTasksMap)
          m.set(sessionId, next)
          this.scheduledTasksMap = m
        }
      } catch (e) {
        console.error('[scheduled-tasks] delete failed:', e)
        const sessionId = this._findSessionForTask(taskId)
        if (sessionId) await this.fetchScheduledTasks(sessionId)
      }
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
                // 不再透传 execution_env —— 前端按 toolCall.args.local 在 MessageItem 渲染时直接判断
              }, sessionId)
            }
          } else if (response.status === 404) {
            // 会话不存在（用户主动导航到一个已删除 / 不存在的会话）
            // 触发 NotFoundView 浮层 —— 10s 后自动跳主页（或用户点击立即跳）。
            // 注意：refreshConversation 走另一条路径，404 时仅 console.error，
            //       不会进这条分支 → 「正常对话中临时 404」不会被误踢回主页。
            this.showNotFound()
            this.messages = []
          }
        } catch (error) {
          console.error('加载对话失败:', error)
        }
      }

      // 拉取当前会话的定时任务（不阻塞主流程；面板会基于 Map 渲染）
      this.fetchScheduledTasks(sessionId)
      // 拉取当前会话的排队消息（不阻塞；UI 卡片基于 _pendingQueue 渲染）
      this._loadQueueForSession(sessionId)

      // —— 恢复撤回后保留的输入文本（跨 F5 持久化）——
      //    用户撤回时把文本写进 localStorage[chatme-withdraw-pending:{sid}]；
      //    加载会话时检测 entry 自动回填，让用户接着编辑 / 发送
      const pendingWithdraw = localStorage.getItem(`chatme-withdraw-pending:${sessionId}`)
      if (pendingWithdraw) {
        this.$nextTick(() => {
          this.$refs.messageInput?.setInputText(pendingWithdraw)
        })
      }

      // 切换/刷新会话后 → 焦点还给输入框（用户预期：看完历史直接接着输入）
      this.focusInput()
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
          this.$refs.sidebar?.reloadFiles?.()
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
              // 不再透传 execution_env —— 前端按 toolCall.args.local 在 MessageItem 渲染时直接判断
            }, this.currentSessionId)
          }
        }
      } catch (error) {
        console.error('刷新消息失败:', error)
      }
    },
    // 右键刷新指定会话
    async refreshConversation(sessionId) {
      // 刷新会话（sid 不变，但消息被重拉）→ 清空 MessageInput 的动态 skill 缓存，
      // 下次用户敲 `/` 时面板会自动 refetch，让 SkillForge 中途新增的 skill 可见。
      // 切会话走 sessionId watcher（MessageInput.vue），不需要这里重复处理。
      this.$refs.messageInput?.clearDynamicSkills()

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
            this.$refs.sidebar?.reloadFiles?.()
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
          // 刷新完（无论是当前会话还是其他会话的侧栏刷新）→ 焦点还给输入框，
          // 用户接着打字。流式中的会话已在前面 early return，不走到这里。
          this.focusInput()
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
        // 清理队列 map + 延迟 drain 标记（避免孤儿 ID 引用）
        this._pendingQueue.delete(sessionId)
        this._pendingQueue = new Map(this._pendingQueue)
        this._queueDrainDeferred.delete(sessionId)
        this._queueDrainDeferred = new Set(this._queueDrainDeferred)
        // 清理侧栏状态点（防孤儿 ID；ConversationItem 已 unmount，渲染上看不到残留）
        this._completedSessions.delete(sessionId)
        this._completedSessions = new Set(this._completedSessions)
        this._approvalPendingSessions.delete(sessionId)
        this._approvalPendingSessions = new Set(this._approvalPendingSessions)
        this._errorSessions.delete(sessionId)
        this._errorSessions = new Set(this._errorSessions)
        // 释放 sendMessage 并发锁（避免删除会话后锁卡住）
        this._sendingLock.delete(sessionId)
        this._sendingLock = new Map(this._sendingLock)
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

      // —— 消息队列守卫 ——
      // 如果目标 session 正在流式响应（_activeStreamingSessions）或 AI 正在等用户审批
      // （_approvalPendingSessions；interrupt 已清理 streaming 但 approval 还没解决），
      // 把消息入队持久化到 Redis（db1，queue:{sid}），UI 显示卡片。
      // 注意：**不要**把 _drainInFlight 加到 isBusy 里 —— drain 自己调 sendMessage 时，
      // sid 已经在 _drainInFlight（drain 在 await sendMessage 前先 add），如果 guard 命中，
      // drain 这次 sendMessage 走 _enqueueMessage → POST + GET 一下、又返回 success，
      // drain 继续 DELETE idx=0 + slice + 递归 $nextTick → 递归的 sendMessage 又命中 guard
      // → 再 enqueue 一条 → POST + GET + DELETE + 递归 → **死循环**（POST / GET / DELETE
      // 一直打 /queue）。所以 _drainInFlight 只用于 _drainQueueAndSend 顶端的 dedup 检查，
      // 不能泄露到 sendMessage 内部。
      // 输入框已由 MessageInput.handleSend 在 emit 前清空，currentQuote 也已由 update:quote 清空，
      // 所以入队路径只需 POST + re-fetch。
      // 为什么不在 isLoading 上做判断：isLoading 可能因 race / 时序 false（切走前的 stream 已被别的代码清过），
      // 用 _activeStreamingSessions / _approvalPendingSessions 检查更稳——只要 SSE 还在跑或 AI 在等审批就算忙。
      // （drain 自己调 sendMessage 不走这层判断，busy 由 _drainInFlight 顶端 dedup 保证不会和别的 drain 并发）
      const sid = this.currentSessionId
      const isBusy =
        sid &&
        (this._activeStreamingSessions.has(sid) || this._approvalPendingSessions.has(sid))
      if (isBusy) {
        await this._enqueueMessage(sid, {
          message: message,
          quote: this.currentQuote?.content || null,
        })
        return
      }

      // —— 同 sid 并发 sendMessage 防护 ——
      // 极端 case：用户在前一次 sendMessage 的 fetch 还没返回时再次点击发送，
      // 此时 _activeStreamingSessions 尚未 add(sid)（add 在 fetch 200 之后才发生），
      // 第二次 sendMessage 会绕过上面的 busy 检查走两次正常路径，导致两个 SSE 并发跑。
      // 用 _sendingLock Map 兜底：第一次进入 sendMessage 时 set true，函数结尾 finally 块清理；
      // 第二次进入 fallback 到 _enqueueMessage 入队（不静默 return 丢消息）——
      // 用户的二次点击变成排队卡，等上一轮 SSE done 后 drain 自动发送。
      // 这样既避免了两个 SSE 并发跑（_sendingLock 仍挡住了），又保证用户消息不丢。
      if (sid && this._sendingLock.has(sid)) {
        console.warn(`[sendMessage] 拒绝并发 sendMessage: sid=${sid}, fallback enqueue`)
        await this._enqueueMessage(sid, {
          message: message,
          quote: this.currentQuote?.content || null,
        })
        return
      }
      if (sid) {
        const m = new Map(this._sendingLock)
        m.set(sid, true)
        this._sendingLock = m
      }

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

      // 撤回文本不再 pending —— 用户已发送，清掉 localStorage
      // （下次切回该会话不该自动恢复这条已发出的消息）
      localStorage.removeItem(`chatme-withdraw-pending:${this.currentSessionId}`)

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

      // 用户主动发起新一轮请求 → 清掉旧审批状态：
      //   后端新 message_stream 已经清理了对应 permission 逻辑（不再等用户决定），
      //   但前端不主动清会让旧审批 UI + 旧黄点一直挂着，
      //   且下次新流再来 permission_request 会被 pendingToolApproval singleton 挡掉（早返）。
      //   只清当前会话的 pending；跨 session 切走的 pending 等 loadConversation 那边处理。
      if (this.pendingToolApproval && this.pendingToolApproval.sessionId === requestSessionId) {
        const oldMessageIndex = this.pendingToolApproval.messageIndex
        const oldToolIndex = this.pendingToolApproval.toolIndex
        if (this.messages[oldMessageIndex] && this.messages[oldMessageIndex].toolCalls && this.messages[oldMessageIndex].toolCalls[oldToolIndex]) {
          const oldToolCalls = [...this.messages[oldMessageIndex].toolCalls]
          const oldToolEntry = oldToolCalls[oldToolIndex]
          const toolName = oldToolEntry.name || 'tool'
          const argsSummary = JSON.stringify(oldToolEntry.args || {}).slice(0, 200)
          oldToolCalls[oldToolIndex] = {
            ...oldToolEntry,
            _pendingApproval: false,
            // 用户发了新消息离开这个审批决策——给个明确的本地占位 result，
            // 让 tool UI 从「awaiting-approval」转成「tool-done」（显示 ✓ 而不是 running dot）
            result: oldToolEntry.result || (
              `User sent a new message without approving this ${toolName} call (${argsSummary}); ` +
              `the ${toolName} was not executed and no side effects occurred. ` +
              `Continue with the new request.`
            )
          }
          this.messages[oldMessageIndex] = {
            ...this.messages[oldMessageIndex],
            toolCalls: oldToolCalls
          }
        }
        this.pendingToolApproval = null
      }
      if (this._approvalPendingSessions.delete(requestSessionId)) {
        this._approvalPendingSessions = new Set(this._approvalPendingSessions)
      }
      // 重置 in-flight 标志（用户已离开审批态，按钮不必再卡）
      this.submittingToolDecision = false
      this.permissionResumeInFlight = false

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
                    this._tryDrainQueue(requestSessionId)
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
                    this._tryDrainQueue(requestSessionId)
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
                    this._tryDrainQueue(requestSessionId)
                    // 通知 handleWithdraw：SSE interrupt 事件已到达，可以发 backtrack 了
                    if (this._withdrawInterruptResolver) {
                      const r = this._withdrawInterruptResolver
                      this._withdrawInterruptResolver = null
                      r()
                    }
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
                // drain 必须在 refresh 之后：
                // refresh 会 `this.messages = processConversationMessages(...)`，覆盖整数组。
                // 如果 drain 提前推了占位 AI message，refresh 一覆盖，drain 后续 SSE 的
                // `this.messages[aiMessageIndex].reasoning` 就炸 `Cannot read of undefined`。
                // 在所有 refresh / update 完成后触发 → 占位消息被 refresh 的下一轮 fetch 自然吸收。
                this._tryDrainQueue(requestSessionId)
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
                this._tryDrainQueue(requestSessionId)
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
                this._tryDrainQueue(requestSessionId)
                // 通知 handleWithdraw：SSE interrupt 事件已到达，可以发 backtrack 了
                if (this._withdrawInterruptResolver) {
                  const r = this._withdrawInterruptResolver
                  this._withdrawInterruptResolver = null
                  r()
                }
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
                // 与 main-loop in-session done 同样的 race 防护：
                // drain 必须在 refresh 之后，避免 placeholder 被 messages 整体重写。
                this._tryDrainQueue(requestSessionId)
              } else if (data.type === 'permission_request') {
                this.handlePermissionRequest(data, requestSessionId)
              }
            }
          } catch (e) {
            console.error('解析缓冲区剩余数据失败:', e)
          }
        }
      } finally {
        // —— 释放同 sid 并发 sendMessage 防护锁 ——
        // 必须走 new Map() 整体替换以触发响应式（虽然本字段没绑定到视图，但保持一致风格避免隐患）。
        if (sid && this._sendingLock.has(sid)) {
          const m = new Map(this._sendingLock)
          m.delete(sid)
          this._sendingLock = m
        }
        this.isLoading = false
        this.stopResponseTimer()
      }
    },
    async updateTitleOnly(sessionId, userMessage) {
      // 只更新会话标题（含侧边栏同步），不重拉 messages。
      // 出错后调用，避免覆盖前端的错误气泡。
      // 标题派生下沉到后端：传空 title 由后端从最新 HumanMessage 自动筛掉 <quote> + /[xxx] 后截断到 12 字符。
      if (!sessionId || !userMessage) return
      let title = userMessage.substring(0, 12) + (userMessage.length > 12 ? '...' : '')
      try {
        const resp = await fetch(`/chat/${sessionId}/title`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})  // 空 → 后端自动派生（剥 quote / pill + 截断）
        })
        if (resp.ok) {
          const data = await resp.json().catch(() => ({}))
          // 后端派生的标题优先（剥了 quote / pill 的干净版本）；失败 fallback 到前端兜底
          if (data && typeof data.new_title === 'string' && data.new_title) {
            title = data.new_title
          }
        }
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
      // 1. 用用户消息更新标题（后端自动剥 <quote> + /[xxx] + 截断到 12 字符）
      let title = userMessage.substring(0, 12) + (userMessage.length > 12 ? '...' : '')
      try {
        const resp = await fetch(`/chat/${sessionId}/title`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})  // 空 → 后端自动派生
        })
        if (resp.ok) {
          const data = await resp.json().catch(() => ({}))
          if (data && typeof data.new_title === 'string' && data.new_title) {
            title = data.new_title
          }
        }
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
          this.$refs.sidebar?.reloadFiles?.()
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
          this.$refs.sidebar?.reloadFiles?.()

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
                    // 兜底:后端 RemoveMessage 已保证 messages 里不会有 done,
                    // 这里再防一道(老 checkpoint / 跨版本迁移场景的安全网)
                    if (tc.name === 'done') continue
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
    window.removeEventListener('keydown', this.handleOverlayKeydown)
    for (const controller of this._previewLoadControllers.values()) controller.abort()
    this._previewLoadControllers.clear()
    // NotFoundView timer 清理：避免组件卸载后 setTimeout / setInterval 仍在跑
    // （Electron 单窗口架构下基本不会触发，但规范做法）
    if (this._notFoundTimer) clearTimeout(this._notFoundTimer)
    if (this._notFoundTickInterval) clearInterval(this._notFoundTickInterval)
    window.removeEventListener('keydown', this.handleDoubleSlashFocus)
  },
  watch: {
    isLoading(newVal) {
      // 当加载状态结束时，清理当前 AI 消息索引
      if (!newVal) {
        this.currentAiMessageIndex = null
      }
    },
    // —— 弹窗 / 面板关闭 → 焦点还给输入框（统一处理）——
    // slash 命令 /backtrack /settings /help /worktree 等开的弹层关掉后，
    // 用户应当能直接继续打字。Esc / × / overlay click 三条关闭路径都覆盖。
    // showRestoreConfirm（恢复历史版本）故意不监听：那是 destructive 操作，
    // 用户做了决定后焦点归还反而干扰（会立即开始一轮新流程）。
    showCheckpoints(newVal, oldVal) { if (oldVal && !newVal) this.onPanelClosed() },
    showWebPreview(newVal, oldVal)  { if (oldVal && !newVal) this.onPanelClosed() },
    showImagePreview(newVal, oldVal){ if (oldVal && !newVal) this.onPanelClosed() },
    showFilePreview(newVal, oldVal) { if (oldVal && !newVal) this.onPanelClosed() },
    settingsVisible(newVal, oldVal) { if (oldVal && !newVal) this.onPanelClosed() },
    helpVisible(newVal, oldVal)     { if (oldVal && !newVal) this.onPanelClosed() }
    // ToastDialog 走 closeToast() 方法自己处理（不监听 toast.visible，
    // 因为 toast 内的「知道了」按钮和自动消失是两套时机，混在一起易抖）。
    // Resume 弹窗走 cancelResume / confirmResume 自己处理（用户正在做决策）。
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
 * cold path 也只是一闪——比「warm 时 BootstrapView 弹一下再消失」「cold 时先露空主界面再叠浮窗」都干净。
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
 * 但不能点；BootstrapView 浮窗叠在上方（z-index 1000），bootstrap 完成后 BootstrapView 淡出、
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
  /* 子元素 .chat-drag-overlay 用 absolute 覆盖整个 chat 区，
     不再 fixed 全屏（v0.2.x 之前 fixed + z-index 9999 会盖住 sidebar 的 system-drag-overlay）。
     —— 「文件树 / 对话框两片地方分开显示」的核心重构。 */
}

/* 拖拽遮罩：覆盖整个 .chat-area，不盖 sidebar。
   与 sidebar 的 .system-drag-overlay（fixed inset:0, z-index 9998）视觉上完全独立，
   用户在 sidebarView === 'files' 时从 Finder 拖文件，落到 chat 区只显示这块 overlay，
   落到 .files-tree 只显示 sidebar 自己的 overlay —— 真正两片地方独立上传。 */
.chat-drag-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;  /* 不挡 drop 事件，由 window-level MessageInput handleWindowDrop 接管 */
  z-index: 100;          /* chat-area 局部层级，只需高过 ChatHeader/MessageList/MessageInput 即可 */
}

.chat-drag-content {
  text-align: center;
  color: #ffffff;
  pointer-events: none;
}

.chat-drag-content svg {
  margin-bottom: 16px;
  animation: chat-drag-bounce 1s infinite;
}

.chat-drag-content p {
  font-size: 18px;
  font-weight: 500;
  letter-spacing: 0.5px;
}

@keyframes chat-drag-bounce {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(-10px); }
}

.chat-drag-fade-enter-active,
.chat-drag-fade-leave-active { transition: opacity 0.15s ease; }
.chat-drag-fade-enter-from,
.chat-drag-fade-leave-to   { opacity: 0; }

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
 * BootstrapView 浮窗淡入淡出：appReady 翻 true 时整组淡出，避免 v-if 突然消失的硬切。
 * BootstrapView 内部已经有 .bootstrap-overlay 自己的 fade-in animation，
 * 这里用 Vue transition 钩子同步 enter/leave 曲线。
 */
.bootstrap-fade-enter-active,
.bootstrap-fade-leave-active {
  transition: opacity 0.25s ease-out;
}
.bootstrap-fade-enter,
.bootstrap-fade-leave-to {
  opacity: 0;
}
</style>
