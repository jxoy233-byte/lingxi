<template>
  <div class="input-area">
    <!-- 引用块（用户从历史消息中引用内容时显示） -->
    <div v-if="quote" class="quote-block">
      <div class="quote-block-bar"></div>
      <div class="quote-block-content">
        <div class="quote-block-label">
          <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V20c0 1 0 1 1 1z"/>
            <path d="M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3c0 1 0 1 1 1z"/>
          </svg>
          <span>引用</span>
        </div>
        <div class="quote-block-text" v-html="renderedQuote"></div>
      </div>
      <button
        type="button"
        class="quote-block-close"
        @click="onCloseQuote"
        title="移除引用"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <!-- 排队卡片列表（流式响应中用户继续发的消息会进入 Redis 队列等待上轮结束自动 drain）。
         每条显示排队顺序号 + 消息预览（>120 字截断）+ 引文标记 + ✕ 删除单条。
         队列非空时，输入框顶部还显示「排队中 (N)」徽章 + 🗑 清空全部按钮。 -->
    <div v-if="queue.length > 0" class="queue-list-container">
      <div class="queue-list-header">
        <div class="queue-list-badge">
          <span class="queue-list-badge-dot"></span>
          <span>排队中 ({{ queue.length }})</span>
        </div>
        <button
          type="button"
          class="queue-list-clear"
          @click="onQueueClear"
          title="清空排队"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
            <path d="M10 11v6"/>
            <path d="M14 11v6"/>
            <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>
          </svg>
          <span>清空</span>
        </button>
      </div>
      <div class="queue-list-scroll">
        <div
          v-for="(item, idx) in queue"
          :key="`${item.queued_at || idx}-${idx}`"
          class="queue-item"
        >
          <div class="queue-item-index">#{{ idx + 1 }}</div>
          <div class="queue-item-body">
            <div v-if="item.quote" class="queue-item-quote" :title="item.quote">
              <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V20c0 1 0 1 1 1z"/>
                <path d="M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3c0 1 0 1 1 1z"/>
              </svg>
              <span>引用</span>
            </div>
            <div class="queue-item-text">{{ truncateForCard(item.message) }}</div>
          </div>
          <button
            type="button"
            class="queue-item-remove"
            @click="onQueueItemRemove(idx)"
            :title="`删除 #${idx + 1}`"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- 文件拖拽上传警告：拖入不被支持的文件类型时，列出文件名 + 原因 + ✕ 手动关闭。
         5s 自动消失；与 file-list-container 内每个 file-error 红点是两套不同信号：
           - 红点：错误文件**已添加**到 selectedFiles（混合拖拽时与合法文件共存）
           - 本 banner：拖入**完全不被接受**的文件（含 all-invalid 早返场景）——
             让用户清楚「拖进来但没生效」的原因，不会以为丢进去没反应。
         文件树区域上传不限类型（Sidebar._uploadSystemFiles 无 validateFile），
         只在对话框（AI 处理链路）才走这个警告路径。 -->
    <transition name="drag-drop-warning">
      <div v-if="dragDropWarning" class="drag-drop-warning">
        <svg class="drag-drop-warning-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span class="drag-drop-warning-text">{{ dragDropWarning }}</span>
        <button
          type="button"
          class="drag-drop-warning-close"
          @click="_dismissDragDropWarning"
          title="关闭"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    </transition>

    <!-- 文件列表显示区域 - 横向紧凑布局 -->
    <div v-if="selectedFiles.length > 0" class="file-list-container">
      <div class="file-list-scroll">
        <div
          v-for="(file, index) in selectedFiles"
          :key="index"
          class="file-item"
          :class="{ 'file-error': file.error, 'file-uploading': file.uploading }"
        >
          <!-- 图片预览或文件图标 -->
          <div class="file-preview-wrapper">
            <img
              v-if="isImageFile(file) && file.preview"
              :src="file.preview"
              class="file-preview-img"
              :alt="file.name"
            />
            <div v-else class="file-icon-compact">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
                <polyline points="13 2 13 9 20 9"/>
              </svg>
            </div>

            <div v-if="file.uploading" class="uploading-overlay">
              <svg class="spinner-small" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 2 A10 10 0 0 1 22 12"/>
              </svg>
            </div>

            <!-- 删除按钮 -->
            <button
              type="button"
              class="remove-button-overlay"
              @click="removeFile(index)"
              :title="'删除 ' + file.name"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <!-- 文件名称（悬停显示完整信息） -->
          <div class="file-name-compact" :title="`${file.name} (${formatFileSize(file.size)})`">
            {{ truncateFileName(file.name, 12) }}
          </div>

          <!-- 错误提示 -->
          <div v-if="file.error" class="file-error-badge" :title="file.error">!</div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-wrapper">
      <!-- 文件上传按钮 -->
      <button
        type="button"
        class="upload-button"
        @click="triggerFileInput"
        :disabled="isLoading"
        title="上传文件"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
        </svg>
      </button>

      <!-- 隐藏的文件输入 -->
      <input
        ref="fileInput"
        type="file"
        multiple
        :accept="acceptedTypes"
        @change="handleFileSelect"
        style="display: none"
      />

      <!-- 输入列：chip 与 textarea 同排（chip 在最左侧占视觉锚点），
           后跟的文本内容在 textarea 里继续输入。chip 用绝对定位浮在 textarea 第一行
           文本起始位置之上（textarea padding 同步预留 chip 宽度），textarea 永远不出现
           `/[xxx]` 原文，handleSend 时再还原成前缀。 -->
      <div ref="composer" class="composer">
        <transition name="slash-chip-pop">
          <span
            v-if="activeSlashCommand"
            ref="slashChip"
            class="slash-chip"
            :title="activeSlashCommand.description"
          >
            <span class="slash-chip-slash">/</span>
            <span class="slash-chip-name">{{ activeSlashCommand.name }}</span>
            <button
              type="button"
              class="slash-chip-remove"
              @click="clearSlashCommand"
              title="移除命令（或把光标移到开头按 Backspace）"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </span>
        </transition>

        <textarea
          v-model="inputText"
          @keydown="handleKeydown"
          @input="onInputChange"
          @compositionstart="onCompositionStart"
          @compositionend="onCompositionEnd"
          @paste="handlePaste"
          :class="{ 'composer-textarea--with-chip': activeSlashCommand }"
          :placeholder="activeSlashCommand ? `告诉 AI 怎么用 ${activeSlashCommand.name}` : '输入消息...'"
          rows="1"
          ref="textarea"
        ></textarea>
      </div>

      <!-- 优化按钮 -->
      <button
        type="button"
        class="optimize-button"
        :class="{ 'optimizing': isOptimizing }"
        @click="optimizeInput"
        :disabled="!inputText.trim() || isLoading || isOptimizing"
        :title="isOptimizing ? '优化中...' : '优化输入'"
      >

        <svg v-if="!isOptimizing" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M12 1v6m0 6v6m5.2-13.2l-4.2 4.2m0 6l4.2 4.2M23 12h-6m-6 0H1m18.2 5.2l-4.2-4.2m0-6l4.2-4.2"/>
        </svg>
        <svg v-else class="spinner" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 2 A10 10 0 0 1 22 12"/>
        </svg>
      </button>

      <button
        @click="handleSend"
        :disabled="(!inputText.trim() && selectedFiles.filter(f => !f.error && !f.uploading).length === 0) || hasUploadingFiles || permissionResumeInFlight"
        class="send-btn"
        :title="hasUploadingFiles ? '文件上传中，请等待' : permissionResumeInFlight ? '权限决策处理中，请等待' : ''"
      >
        发送
      </button>
    </div>

    <!-- 拖拽逻辑保留在 MessageInput 内部处理（isDragging state + window-level drag/over/drop），
         但视觉 overlay 不在这里渲染 —— 提到 App.vue 的 .chat-area 子元素渲染。
         这样在 sidebarView === 'files' 时，chat 区域的 overlay 只覆盖 chat 区不盖 sidebar，
         与 sidebar 的 system-drag-overlay 真正做到「两片地方分开」。 -->

    <!-- Slash 命令面板：行首输入 `/` 时弹出，Codex 风格 -->
    <SlashPalette
      :visible="slashPalette.visible"
      :query="slashPalette.query"
      :commands="filteredSlashCommands"
      :selected-index.sync="slashPalette.selectedIndex"
      @select="onSlashCommandSelect"
      @close="closeSlashPalette"
    />
  </div>
</template>

<script>
import { marked } from 'marked'
import SlashPalette from './SlashPalette.vue'

export default {
  name: 'MessageInput',
  components: { SlashPalette },
  expose: ['clearInput', 'getSessionId', 'setSessionId', 'checkAndUploadPendingFiles', 'setInputText', 'focusTextarea', 'clearDynamicSkills'],
  props: {
    isLoading: {
      type: Boolean,
      default: false
    },
    sessionId: {
      type: String,
      default: null
    },
    quote: {
      type: Object,
      default: null
    },
    // 权限 resume 流期间为 true（用户点完审批按钮、后端正在执行 Command(resume)）。
    // 此期间禁用发送按钮防止并发请求；待审核状态本身不阻塞发送（用户可在审批期间编辑/发送新消息）。
    permissionResumeInFlight: {
      type: Boolean,
      default: false
    },
    // 当前会话的排队消息列表（per session FIFO）；空数组时不渲染。
    // App.vue 的 queueForCurrentSession 计算属性下传。
    queue: {
      type: Array,
      default: () => []
    }
  },
  emits: ['send', 'files-selected-need-session', 'update:quote', 'remove-queue-item', 'clear-queue', 'front-action', 'chat-drag-state'],
  data() {
    return {
      inputText: '',
      selectedFiles: [],
      isDragging: false,
      isOptimizing: false,
      fileConfig: null,
      loadingConfig: false,
      processedOutputs: [],
      // 上传队列控制
      uploadQueue: [],      // 待处理的文件队列
      isUploadQueueProcessing: false,  // 队列是否正在处理中
      // 会话 ID（优先使用 prop，其次使用 localStorage）
      currentSessionId: null,
      // Slash 命令面板状态：
      // - visible: 当前是否应该显示面板
      // - query: `/` 后面用户已输入的过滤文本（不含 `/` 也不含 `[`）
      // - triggerStart: 输入框中触发字符 `/` 的位置（用于选中时替换）
      // - selectedIndex: 当前高亮的候选项下标
      slashPalette: {
        visible: false,
        query: '',
        triggerStart: -1,
        selectedIndex: 0
      },
      // IME 输入法合成中标记。中文/日文/韩文等输入法敲 `/` + 选候选时，
      // 每次候选变更都会触发 input 事件 —— 此时不应跑 slash 检测 / chip 提取，
      // 等 compositionend 落地后再统一检测一次。
      isComposing: false,
      // 当前挂在输入框上的 slash 命令（整个 cmd 对象，含 description 供 tooltip 用）。
      // 命令选中后不留在 inputText 里 —— 由这个字段 + chip UI 承载，
      // handleSend 时才还原成 `/[name] ` 前缀发给后端。单条消息只允许一个。
      activeSlashCommand: null,
      // chip 视觉宽度（含 padding / border），用于 textarea 的左 padding 偏移。
      // 命令切换时重新测量，让 chip 与首字符无缝拼接。
      chipMinWidth: '0px',
      // 静态 action 命令清单（永远在前，不依赖后端返回）：
      // 这些是纯前端动作（打开弹窗 / 刷新页面），name 不会发往后端，无命名约束。
      // kind: 'action' → emit front-action 给 App.vue，不发后端。
      staticActionCommands: [
        { name: 'backtrack', kind: 'action', description: '打开历史版本面板' },
        { name: 'settings',  kind: 'action', description: '打开设置弹窗' },
        { name: 'setup',     kind: 'action', description: '打开安装 / 配置向导（首启推荐）' },
        { name: 'reload',    kind: 'action', description: '刷新当前会话' },
        { name: 'worktree',  kind: 'action', description: '打开当前会话工作树' },
        { name: 'help',      kind: 'action', description: '显示本项目功能速览' }
      ],
      // 动态 skill 列表（从 /chat/skills 拉的），每个含 {name, description, lazy}。
      // name 严格对应 backend/skills/ 下的**文件夹名**（PascalCase，如
      // `DataAnalysis` / `Exa`），发送时 chip 还原成 `/[DataAnalysis] args`，
      // agent 收到后直接 `cat /skills/DataAnalysis/SKILL.md` 加载契约。
      // kind 由 computed 自动标记为 'skill'（chip → /chat 流）。
      // 失败兜底：fetch 异常时维持空数组，至少 action 命令仍可用。
      dynamicSkills: [],
      // Skill 描述前端覆盖：key = /chat/skills 返回的目录名（PascalCase），缺省 fallback 后端 description
      skillDescriptionOverrides: {
        Memory:       '把反复出现的精确事实 / 用户偏好记下来，下次对话自动加载到上下文',
        ImageParser:  '解析图片中的文字、表格、界面元素与场景（支持截图、照片、URL、base64）',
        SkillForge:   '动态创建新技能：写一段 Python 包装 + 描述，AI 后续对话会自动识别并使用',
        BochaSearch:  '博查中文实时网页搜索：新闻 / 时效性 / 国内站点 / 按时间筛选；少量多次'
      },
      // refetch 节流：slash 面板「关闭 → 打开」时触发后台 refetch；面板已
      // 打开期间的连续打字不重复请求。
      _slashPaletteWasVisible: false,
      // 文件拖拽上传警告：拖入不被支持的文件类型时显示（仅对话框区域）。
      // 文件树区域（Sidebar._uploadSystemFiles）不限类型，不会触发这条警告。
      dragDropWarning: null,
      _dragDropWarningTimer: null
    }
  },
  computed: {
    // 全量 slash 命令 = 静态 action + 动态 skill。
    // - action 永远在前（高频且稳定，弹窗打第一眼就能看到）
    // - skill 跟随 /chat/skills 返回的顺序（按 name 字母序），所以新装 skill
    //   字母靠后就排后面，靠前就自动顶到 action 之后
    // - 不做 dedup：action name（backtrack / settings / reload / worktree / help）
    //   故意不和任何 skill 文件夹撞名，万一撞了走「action 优先」语义
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
    // Slash 命令面板：按 query 过滤的候选列表
    filteredSlashCommands() {
      const q = (this.slashPalette.query || '').toLowerCase().trim()
      if (!q) return this.slashCommands
      return this.slashCommands.filter(cmd => {
        const name = (cmd.name || '').toLowerCase()
        const desc = (cmd.description || '').toLowerCase()
        return name.includes(q) || desc.includes(q)
      })
    },
    maxFileSize() {
      return this.fileConfig?.maxFileSize || 25 * 1024 * 1024
    },
    allowedImageTypes() {
      const types = this.fileConfig?.imageTypes?.suffixes
      return types && types.length > 0 ? types : ['.png', '.jpg', '.jpeg', '.gif']
    },
    allowedTextTypes() {
      const types = this.fileConfig?.textTypes?.suffixes
      return types && types.length > 0 ? types : ['.txt', '.md', '.csv', '.xml', '.json']
    },
    allowedDocumentTypes() {
      const types = this.fileConfig?.documentTypes?.suffixes
      return types && types.length > 0 ? types : ['.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls']
    },
    acceptedTypes() {
      return [...this.allowedImageTypes, ...this.allowedTextTypes, ...this.allowedDocumentTypes].join(',')
    },
    allowedExtensions() {
      return [...this.allowedImageTypes, ...this.allowedTextTypes, ...this.allowedDocumentTypes]
    },
    // 检查是否有文件正在上传
    hasUploadingFiles() {
      return this.selectedFiles.some(f => f.uploading) || this.uploadQueue.length > 0 || this.isUploadQueueProcessing
    },
    // 引用块内容渲染成 markdown HTML（链接、代码、加粗、公式等都能正确显示）
    renderedQuote() {
      if (!this.quote || !this.quote.content) return ''
      try {
        return marked.parse(this.quote.content, { breaks: true, gfm: true })
      } catch (e) {
        console.error('引用块 Markdown 渲染失败:', e)
        return this.escapeHtml(this.quote.content)
      }
    }
  },
  methods: {
    escapeHtml(text) {
      if (!text) return ''
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
    }
  },
  watch: {
    // 把 isDragging state 推到 App.vue，由 App.vue 在 .chat-area 子元素渲染 overlay
    // —— 这样在 sidebarView === 'files' 时，chat overlay 只覆盖 chat 区，
    // 与 sidebar 的 system-drag-overlay 真正做到「两片地方分开」。
    isDragging(newVal) {
      this.$emit('chat-drag-state', newVal)
    },
    // chip 命令变化时重新测宽度。**不能用 immediate: true** —— immediate 触发
    // 时组件还在 created 生命周期，`this.$el` 还没就绪，`$el.querySelector` 直接
    // 抛 TypeError 把整个组件挂载砸掉。改成在 mounted + $nextTick 跑首次测量，
    // 后续变化也走 nextTick 等 DOM 更新完。
    activeSlashCommand() {
      this.$nextTick(this.measureChipMinWidth)
    },
    sessionId: {
      handler(newVal, oldVal) {
        this.currentSessionId = newVal
        // 切换会话时清空动态 skill 缓存，下一次 `/` 进面板时若缓存为空
        // 会触发 refetch —— 让 SkillForge 中途新增的 skill 在切/刷会话后能看到。
        // 跳过 immediate 首次调用（oldVal === undefined），避免冷启动清掉
        // mounted 时刚拉到的数据。
        if (oldVal !== undefined && newVal !== oldVal) {
          this.dynamicSkills = []
        }
        // 如果有 sessionId 且有待上传文件，自动触发上传
        if (newVal) {
          this.$nextTick(() => {
            this.checkAndUploadPendingFiles()
          })
        }
      },
      immediate: true
    }
  },
  mounted() {
    this.fetchFileConfig()
    // 后台拉取动态 skill 列表（mounted 首次 + 后续 slash 面板关闭→打开时再触发）
    this.fetchSkills()
    // 首次测量 chip 宽度（watch 不能 immediate，created 阶段 $el 未就绪 → 见 watch 注释）
    this.$nextTick(this.measureChipMinWidth)
    // 监听全局拖拽事件
    window.addEventListener('dragenter', this.handleDragEnter)
    window.addEventListener('dragover', this.handleDragOver)
    window.addEventListener('drop', this.handleWindowDrop)
    // 拖拽状态兜底清理：drag 在浏览器外结束（drop 在外部、Esc 取消、dragend 等）
    // 不会触发 window drop，需要 dragend / dragleave(relatedTarget=null) 兜底重置 isDragging，
    // 否则 overlay 一直显示，状态不灵敏。
    window.addEventListener('dragend', this.handleDragEnd)
    document.addEventListener('dragleave', this.handleDocumentDragLeave)
  },
  beforeUnmount() {
    // 清理事件监听
    window.removeEventListener('dragenter', this.handleDragEnter)
    window.removeEventListener('dragover', this.handleDragOver)
    window.removeEventListener('drop', this.handleWindowDrop)
    window.removeEventListener('dragend', this.handleDragEnd)
    document.removeEventListener('dragleave', this.handleDocumentDragLeave)

    // 清理拖拽警告定时器，避免组件卸载后 setTimeout 回调仍尝试写已销毁的 data
    if (this._dragDropWarningTimer) {
      clearTimeout(this._dragDropWarningTimer)
      this._dragDropWarningTimer = null
    }

    // 清理预览 URL
    this.selectedFiles.forEach(file => {
      if (file.preview) {
        URL.revokeObjectURL(file.preview)
      }
    })
  },
  methods: {
    getSessionId() {
      return this.currentSessionId
    },
    setSessionId(sessionId) {
      this.currentSessionId = sessionId
    },
    checkAndUploadPendingFiles() {
      // 检查是否有待上传的文件（从 sessionStorage 恢复）
      this.$nextTick(() => {
        const pendingFiles = sessionStorage.getItem('pendingUploadFiles')
        const pendingSid = localStorage.getItem('pendingSessionId')

        console.log('[checkAndUploadPendingFiles] checking - pendingFiles:', !!pendingFiles, 'pendingSid:', pendingSid)

        // 如果有待上传的文件和 sessionId，则触发上传
        if (pendingFiles && pendingSid) {
          console.log('[checkAndUploadPendingFiles] Found pending files, processing...')
          try {
            const files = JSON.parse(pendingFiles)
            if (files && files.length > 0) {
              // 重建 File 对象
              const fileObjs = []
              for (const fileData of files) {
                if (fileData.needsReselect) {
                  // 文件太大无法存储，标记需要重新选择
                  fileObjs.push({
                    name: fileData.name,
                    size: fileData.size,
                    type: fileData.type,
                    file: null,
                    error: '文件较大，请在当前页面重新选择',
                    preview: null,
                    fileId: null,
                    uploading: false
                  })
                } else if (fileData.buffer) {
                  // 从 buffer 重建 File 对象
                  const buffer = new Uint8Array(fileData.buffer).buffer
                  const blob = new Blob([buffer], { type: fileData.type })
                  const file = new File([blob], fileData.name, { type: fileData.type })
                  const fileObj = {
                    name: file.name,
                    size: file.size,
                    type: file.type,
                    file: file,
                    error: null,
                    preview: URL.createObjectURL(file),
                    fileId: null,
                    uploading: false
                  }
                  fileObjs.push(fileObj)
                }
              }
              console.log('[checkAndUploadPendingFiles] Reconstructed', fileObjs.length, 'files, adding to uploadQueue')
              // 添加到队列并触发上传
              this.uploadQueue.push(...fileObjs)
              if (!this.isUploadQueueProcessing) {
                this.processUploadQueue()
              }
              // 清理（不管成功失败，pending 文件只使用一次）
              sessionStorage.removeItem('pendingUploadFiles')
              localStorage.removeItem('pendingSessionId')
            }
          } catch (e) {
            console.error('恢复待上传文件失败:', e)
            // 清理避免残留
            sessionStorage.removeItem('pendingUploadFiles')
            localStorage.removeItem('pendingSessionId')
          }
        } else {
          console.log('[checkAndUploadPendingFiles] No pending files or sid found')
        }
      })
    },
    async fetchFileConfig() {
      if (this.loadingConfig) return
      this.loadingConfig = true
      try {
        const response = await fetch('/chat/file-config')
        if (response.ok) {
          this.fileConfig = await response.json()
        }
      } catch (error) {
        console.error('获取文件配置失败:', error)
      } finally {
        this.loadingConfig = false
      }
    },

    /**
     * 后台拉取动态 skill 列表。registry 内部 `_maybe_rescan()` 自动检测
     * SKILL.md mtime —— SkillForge 写新 skill 后无需重启后端，下次 GET
     * 即拿到新列表。
     *
     * 调用时机（**只在缓存为空时才发请求**）：
     *  - mounted 首次拉取（冷启动兜底）
     *  - slash 面板打开且缓存为空时拉一次（同会话内反复打开面板不重复请求；
     *    切/刷会话清空缓存后下个 `/` 才重新拉）
     *
     * 失败兜底：dynamicSkills 维持上次状态（或首次的空数组），至少
     * staticActionCommands 仍可用，输入框不会卡住。
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
        console.warn('[MessageInput] fetchSkills 失败，维持当前动态列表:', error?.message || error)
      }
    },

    handlePaste(e) {
      const items = e.clipboardData?.items
      if (!items) return

      const files = []
      for (const item of items) {
        if (item.kind === 'file') {
          const file = item.getAsFile()
          if (file) files.push(file)
        }
      }

      if (files.length > 0) {
        e.preventDefault()
        this.addFiles(files)
      }
    },

    handleEnterKey(e) {
      // 如果正在输入法输入中（如拼音、日文等），不处理 Enter
      if (e.isComposing || e.keyCode === 229) {
        return
      }

      // Ctrl+Enter 换行，Enter 发送
      if (e.ctrlKey) {
        // Ctrl+Enter: 插入换行符
        const textarea = e.target
        const start = textarea.selectionStart
        const end = textarea.selectionEnd
        const value = textarea.value

        this.inputText = value.substring(0, start) + '\n' + value.substring(end)

        // 恢复光标位置
        this.$nextTick(() => {
          textarea.selectionStart = textarea.selectionEnd = start + 1
          this.autoResize()
        })
      } else {
        // Enter: 发送消息
        e.preventDefault()
        this.handleSend()
      }
    },

    /**
     * 统一键盘入口：先处理 Slash 命令面板的导航键，再走原有的 Enter/Ctrl+Enter 逻辑。
     * 之所以拆出来而不是用 @keydown.enter，是因为面板要拦截 Enter / Tab / Esc / Arrow。
     */
    handleKeydown(e) {
      // Slash 面板打开时，截走 ↑↓ / Tab / Enter / Esc
      if (this.slashPalette.visible) {
        const items = this.filteredSlashCommands

        if (e.key === 'ArrowDown' || e.key === 'Tab') {
          // Tab = ↓：选中下移（Codex 风格）。无 Shift 走下移；Shift+Tab 走上移（对齐 ↑↓ 对称）。
          e.preventDefault()
          if (items.length > 0) {
            const step = e.key === 'Tab' && e.shiftKey ? -1 : 1
            const next = this.slashPalette.selectedIndex + step
            this.slashPalette.selectedIndex = Math.max(0, Math.min(next, items.length - 1))
          }
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          if (items.length > 0) {
            this.slashPalette.selectedIndex = Math.max(0, this.slashPalette.selectedIndex - 1)
          }
          return
        }
        if (e.key === 'Enter') {
          // 仅当面板有匹配项时拦截 Enter（空列表让 Enter 走正常发送）
          if (items.length > 0) {
            e.preventDefault()
            e.stopPropagation()
            this.onSlashCommandSelect(items[this.slashPalette.selectedIndex])
          }
          return
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          this.closeSlashPalette()
          return
        }
      }

      // Backspace 停在最开头且无选区时，先吃掉 slash chip（Codex 行为：
      // 光标退到命令位置时，退格删的是命令本身而不是前一个字符）
      if (
        e.key === 'Backspace' &&
        this.activeSlashCommand &&
        e.target.selectionStart === 0 &&
        e.target.selectionEnd === 0
      ) {
        e.preventDefault()
        this.clearSlashCommand()
        return
      }

      // 其他情况：走原有的 Enter/Ctrl+Enter 逻辑
      if (e.key === 'Enter') {
        this.handleEnterKey(e)
      }
    },

    /**
     * 输入变化时同步 slash 面板状态：
     * - 行首 `/` 触发显示
     * - 行首 `/xxx`（xxx 是 query）触发过滤
     * - 一旦离开「行首 / 可选 [ + 字母/数字/-/_」的形式就关闭面板
     */
    onInputChange() {
      this.autoResize()
      // IME 合成中跳过 slash 检测 —— 中文输入法敲 `/` 候选时会疯狂触发 input 事件，
      // 此时拿到的 inputText 是带候选框临时内容的伪结果，检测会误判。等
      // compositionend 才走真正的「用户已确认输入」路径。
      if (this.isComposing) return
      this.extractTypedSlashCommand()
      this.updateSlashPalette()
    },

    /**
     * IME 合成结束。中文 / 日文 / 韩文等输入法敲完选词后才触发，此时 inputText
     * 已经是用户确认的最终文本，slash 检测可以放心跑。
     */
    onCompositionEnd() {
      this.isComposing = false
      this.autoResize()
      this.extractTypedSlashCommand()
      this.updateSlashPalette()
    },

    /**
     * IME 合成开始。中文输入法敲 `/` 后打开候选框时关闭已存在的 slash 面板，
     * 避免「候选框临时 input 触发 slash 面板弹出 → 选完词后面板残留」的闪烁。
     */
    onCompositionStart() {
      this.isComposing = true
      this.closeSlashPalette()
    },

    /**
     * 用户手敲 / 粘贴出完整的 `/[xxx] ` 或 `/xxx ` 前缀时也收编成 chip，
     * 保证输入框里永远不出现 `/[xxx]` 原文。
     * 只收编 slashCommands 里的已知技能名，避免把 "/usr/bin 下的文件" 这类正常文本吃掉。
     */
    extractTypedSlashCommand() {
      if (this.activeSlashCommand) return
      const m = this.inputText.match(/^\/(?:\[([\w-]+)\]|([\w-]+))[ \t]/)
      if (!m) return
      const known = this.slashCommands.find(c => c.name === (m[1] || m[2]))
      if (!known) return

      const ta = this.$refs.textarea
      const caret = ta ? ta.selectionStart : 0
      this.inputText = this.inputText.slice(m[0].length)
      this.activeSlashCommand = known

      this.$nextTick(() => {
        if (ta) {
          const newCaret = Math.max(0, caret - m[0].length)
          ta.setSelectionRange(newCaret, newCaret)
        }
        this.autoResize()
      })
    },

    updateSlashPalette() {
      const ta = this.$refs.textarea
      if (!ta) {
        this.closeSlashPalette()
        return
      }
      const caret = ta.selectionStart
      const before = this.inputText.slice(0, caret)
      const lineStart = before.lastIndexOf('\n') + 1
      const linePrefix = before.slice(lineStart)

      // Codex 风格检测规则：
      //   - 仅行首 `/` 或 `/xxx`（仅命令名字符，**不含**空格/换行）时才进 slash 模式
      //   - 用户敲了空格就退出检测回到纯文本模式（`/xxx args` 中的 args 不再触发匹配）
      //   - 命令名查 slashCommands 后还有 ≥1 个匹配 → 显示面板（即便过滤后 0 条也仍显示「无匹配」空状态）
      //   - 0 个匹配 → 关闭面板，纯文本
      const openMatch = linePrefix.match(/^\/(?:\[([\w-]*)\]?|([\w-]+))?$/)
      if (openMatch) {
        const query = (openMatch[1] || openMatch[2] || '').toLowerCase().trim()
        // 关闭 → 打开 转换时仅在缓存为空时才 refetch：缓存命中直接复用，
        // 不浪费一次 HTTP。缓存会在 session 切换 / 刷新时被清空（见
        // sessionId watcher + App.vue refreshConversation），所以同会话内
        // 反复打开面板不会重新请求。
        if (!this.slashPalette.visible && this.dynamicSkills.length === 0) {
          this.fetchSkills()
        }
        // 命令面板始终保持可见（含 0 匹配时的「无匹配」空状态），让用户清楚当前不是纯文本模式
        this.slashPalette.visible = true
        this.slashPalette.query = query
        this.slashPalette.triggerStart = lineStart
        if (this.slashPalette.selectedIndex >= this.filteredSlashCommands.length) {
          this.slashPalette.selectedIndex = 0
        }
        return
      }
      this.closeSlashPalette()
    },

    closeSlashPalette() {
      this.slashPalette.visible = false
      this.slashPalette.query = ''
      this.slashPalette.triggerStart = -1
      this.slashPalette.selectedIndex = 0
    },

    /**
     * 选中 slash 命令后，把输入框中 `/` 起头的那一段**摘掉**（不留 `/[xxx]` 原文），
     * 命令改由 activeSlashCommand chip 承载，光标停在原位继续输入任务内容。
     * `kind === 'action'` 的命令（/backtrack /settings /reload /worktree /help）
     * 跳过 chip 直接 emit front-action —— 这些是纯前端动作，不发往后端。
     */
    onSlashCommandSelect(cmd) {
      if (!cmd) return
      const ta = this.$refs.textarea
      if (!ta) return
      const caret = ta.selectionStart
      const triggerStart = this.slashPalette.triggerStart
      const before = this.inputText.slice(0, triggerStart)
      const after = this.inputText.slice(caret)

      // 1. 先擦掉输入框里那一段 `/` 起头的内容（既不留原文也不挂 chip）
      this.inputText = before + after
      this.closeSlashPalette()

      // 2. action 命令 → 立刻触发前端动作，清空输入框
      if (cmd.kind === 'action') {
        this.$emit('front-action', cmd)
        this.$nextTick(() => {
          this.clearInput()
        })
        return
      }

      // 3. skill 命令 → 挂 chip，光标回到原位继续输入
      this.activeSlashCommand = cmd
      this.$nextTick(() => {
        ta.focus()
        ta.setSelectionRange(before.length, before.length)
        this.autoResize()
      })
    },

    clearSlashCommand() {
      this.activeSlashCommand = null
      this.$nextTick(() => {
        const ta = this.$refs.textarea
        if (ta) ta.focus()
        this.autoResize()
      })
    },

    /**
     * 把 chip 的「视觉宽度」量出来写到 composer 的 --chip-min-width CSS 变量上，
     * textarea 用这个变量做 padding-left，保证 chip 与正文在 textarea 第一行
     * 恰好无缝拼接（chip 右沿 ↔ 文本左沿贴齐，不重叠）。
     *
     * 关键：chip 自身绝对定位 `left: 16px`（与 textarea 原 padding-left 对齐，
     * 给视觉留 16px 呼吸距离），所以 textarea padding-left 必须包含：
     *   chipLeftOffset(16) + chipWidth + gap(2)
     * 否则 chip 的右半段会盖到文本起始位置（视觉上 chip 和首字符重叠）。
     */
    measureChipMinWidth() {
      const composerEl = this.$refs.composer || this.$el.querySelector('.composer')
      if (!composerEl) {
        this.chipMinWidth = '0px'
        return
      }
      if (!this.activeSlashCommand) {
        composerEl.style.setProperty('--chip-min-width', '0px')
        this.chipMinWidth = '0px'
        return
      }
      const chipEl = this.$refs.slashChip
      if (chipEl) {
        const chipLeftOffset = 16   // 与 .slash-chip CSS left 同步
        const gap = 2                // chip 右沿 ↔ 首字符的视觉气口
        const w = chipLeftOffset + chipEl.offsetWidth + gap
        composerEl.style.setProperty('--chip-min-width', w + 'px')
        this.chipMinWidth = w + 'px'
      }
    },

    autoResize() {
      const textarea = this.$refs.textarea
      if (!textarea) return

      // 先隐藏滚动条再测量，避免滚动条宽度变化引起的抖动
      textarea.style.overflowY = 'hidden'
      textarea.style.height = 'auto'
      const newHeight = Math.min(Math.max(textarea.scrollHeight, 52), 200)
      textarea.style.height = newHeight + 'px'
      // 达到最大高度才显示滚动条
      textarea.style.overflowY = newHeight >= 200 ? 'auto' : 'hidden'
    },

    handleSend() {
      const validFiles = this.selectedFiles.filter(f => !f.error && !f.uploading)

      // 关键：isLoading 不再阻止发送 —— busy 时点击走 App.vue 的入队路径，把消息存到 Redis + 渲染排队卡。
      // permissionResumeInFlight 仍阻止（审批决策中不应入队，避免和 resume 流抢顺序）。
      if ((!this.inputText.trim() && validFiles.length === 0) || this.permissionResumeInFlight) {
        return
      }
      if (this.hasUploadingFiles) {
        return
      }

      // 前端动作命令（kind === 'action'）拦截：用户敲了 `/backtrack` `/reload`
      // `/help` 等「只命令 + 无后续内容」时，不发往后端，直接走 front-action。
      // 若用户敲了 `/backtrack 解释一下` 之类的「命令 + 文本」，按普通消息处理。
      const rawText = this.inputText.trim()
      const onlyCmdMatch = rawText.match(/^\/([\w-]+)\s*$/)
      if (onlyCmdMatch) {
        const cmd = this.slashCommands.find(c => c.name === onlyCmdMatch[1] && c.kind === 'action')
        if (cmd) {
          this.$emit('front-action', cmd)
          // 用 clearInput 走完整清理路径（输入框 + chip + 文件 + 引用）
          this.clearInput()
          return
        }
      }

      // 如果有引用，把引用内容拼到 message 前面（<quote>...</quote> 标记）
      let finalMessage = this.inputText.trim()

      // Slash 命令包装：chip（activeSlashCommand）或行首 `/xxx` → `/[xxx]`
      // 方括号是"结构化指令"边界，与自然文本里的 `/xxx` 引用
      // （如"我看 /data-analysis 的文档"）做语义区分。后端通过
      // `/[<command-name>]` 字面量识别这是真命令。
      // 包装在 quote 拼接之前（不依赖输入顺序）—— quote 块始终拼在最前，
      // 最终顺序：<quote>...</quote>\n\n/[xxx] args。
      // 单条消息只识别一个 slash 命令，args 中再出现的 `/[xxx]` 视为字面量。
      if (this.activeSlashCommand) {
        // chip 里的命令没进正文，发送时还原成前缀
        finalMessage = `/[${this.activeSlashCommand.name}] ${finalMessage}`
      } else {
        // 没收编成 chip 的字面量（未知技能名 / 换行后手敲）仍按原规则归一化
        const slashMatch = finalMessage.match(/^\/(?:\[([\w-]+)\]|([\w-]+))\s+/)
        if (slashMatch) {
          const cmdName = slashMatch[1] || slashMatch[2]
          finalMessage = `/[${cmdName}] ${finalMessage.slice(slashMatch[0].length)}`
        }
      }

      if (this.quote && this.quote.content) {
        finalMessage = `<quote>\n${this.quote.content}\n</quote>\n\n${finalMessage}`
      }

      this.$emit('send', {
        message: finalMessage,
        files: validFiles,
        processedOutputs: [...this.processedOutputs]
      })

      console.log('发送消息，processedOutputs 数量:', this.processedOutputs.length)

      this.inputText = ''
      this.activeSlashCommand = null
      this.clearFiles()
      // 发送后清空引用
      this.$emit('update:quote', null)

      this.$nextTick(() => {
        const textarea = this.$refs.textarea
        if (textarea) {
          textarea.style.height = '52px'
        }
      })
    },

    /**
     * 排队卡片截断：去掉开头的 <quote>...</quote> 块再按字符截断到 120 字。
     * 后端的 title 派生逻辑也有类似的 _clean_message_for_title，但这里是 UI 渲染，
     * 复刻同样的剥 quote 行为保持视觉一致。
     */
    truncateForCard(text) {
      if (!text) return ''
      // 剥掉 <quote>...</quote> 块（DOTALL）
      const noQuote = String(text).replace(/<quote>[\s\S]*?<\/quote>/g, '').trim()
      if (noQuote.length <= 120) return noQuote
      return noQuote.slice(0, 120) + '…'
    },

    /**
     * 单条排队 ✕ 按钮：emit 到 App.vue 调 DELETE /chat/{sid}/queue?idx=N。
     * App.vue 收到后会调 _removeQueueItem → DELETE 后端 → _loadQueueForSession 同步本地。
     */
    onQueueItemRemove(idx) {
      if (idx === undefined || idx === null) return
      this.$emit('remove-queue-item', idx)
    },

    /**
     * 队列头 🗑 清空按钮：emit 到 App.vue 调 DELETE /chat/{sid}/queue（无 idx）。
     * 与单条 ✕ 同样走后端权威删除，App.vue onClearQueue 接收。
     */
    onQueueClear() {
      this.$emit('clear-queue')
    },

    async optimizeInput() {
      if (!this.inputText.trim() || this.isOptimizing) return

      this.isOptimizing = true

      try {
        const response = await fetch('/chat/improve_input', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            input_text: this.inputText.trim()
          })
        })

        if (!response.ok) {
          throw new Error('优化请求失败')
        }

        const data = await response.json()

        // 更新输入框内容
        if (data.improved_text) {
          this.inputText = data.improved_text
          // 触发自动调整高度
          this.$nextTick(() => {
            this.autoResize()
          })
        }
      } catch (error) {
        console.error('优化输入失败:', error)
      } finally {
        this.isOptimizing = false
      }
    },

    triggerFileInput() {
      this.$refs.fileInput.click()
    },

    handleFileSelect(event) {
      const selectedFiles = Array.from(event.target.files)
      this.addFiles(selectedFiles)
      // 清空 input，允许重复选择同一文件
      event.target.value = ''
    },

    /**
     * 检测当前 drag 事件的目标是否落在 Sidebar 的 .files-tree 区域。
     * 在该区域内 → Sidebar 自己 @drop.stop.prevent 处理（不上传到 chat），MessageInput 不接管。
     * 返回 true 表示「drag 在文件树里」，MessageInput 不应显示自己的 overlay / 处理 drop。
     */
    _isDragOverFilesTree(e) {
      // pointer-events: none 后 e.target 是穿透后的真实元素；用 contains 反查 .files-tree
      let node = e && e.target
      while (node && node !== document) {
        if (node.classList && node.classList.contains('files-tree')) return true
        node = node.parentNode
      }
      return false
    },

    handleDragEnter(e) {
      e.preventDefault()
      if (this.isLoading) return

      // 非文件类型（内部 drag / 文本等）→ 不显示 overlay
      if (!e.dataTransfer.types.includes('Files')) return

      // 在 .files-tree 区域 → Sidebar 自己处理，不显示 chat overlay（避免双 overlay 抢视觉）
      if (this._isDragOverFilesTree(e)) {
        this.isDragging = false
        return
      }

      this.isDragging = true
    },

    handleDragOver(e) {
      // 非文件 drag → 不 preventDefault（让浏览器走默认行为，比如文本 drag）
      if (!e.dataTransfer.types || !e.dataTransfer.types.includes('Files')) return
      // 在 .files-tree 区域 → 不 preventDefault，让 Sidebar 的 @dragover.stop.prevent 处理
      if (this._isDragOverFilesTree(e)) return
      // 其他区域 → preventDefault 启用 drop
      e.preventDefault()
    },

    /**
     * window-level drop：所有 drop 都会冒泡到这里，除非被某个子元素 stopPropagation 拦截。
     * Sidebar 的 .files-tree 有 @drop.stop.prevent → 文件树 drop 不会到这里（已被 Sidebar 拦截）。
     * 所以这里的 e.target 一定不在 .files-tree 内（防御兜底再判断一次），放心走 addFiles。
     */
    handleWindowDrop(e) {
      e.preventDefault()
      this.isDragging = false
      if (this.isLoading) return
      if (!e.dataTransfer.types || !e.dataTransfer.types.includes('Files')) return
      // 防御兜底：万一未来 Sidebar 改了 stopPropagation 策略，这里再检查一次
      if (this._isDragOverFilesTree(e)) return
      const droppedFiles = Array.from(e.dataTransfer.files || [])
      if (droppedFiles.length) this.addFiles(droppedFiles)
    },

    /**
     * 拖拽在浏览器外部结束 / Esc 取消时不会触发 window drop，
     * 用 dragend 兜底重置 isDragging，避免 overlay 卡死。
     */
    handleDragEnd() {
      this.isDragging = false
    },

    /**
     * 拖拽离开文档（relatedTarget 为 null）→ 视为放弃拖拽，重置 isDragging。
     * 注意：dragleave 在文件树 / 对话区 / 子元素间穿梭时会疯狂触发，
     * 只在真正离开文档（relatedTarget === null）时才动作，避免误判。
     */
    handleDocumentDragLeave(e) {
      if (!e.relatedTarget) this.isDragging = false
    },

    handleDrop(e) {
      // 旧实现保留作 no-op（事件已穿透 overlay，由 handleWindowDrop 接管）
      this.isDragging = false
    },

    /**
     * 设置拖拽上传警告横幅：5s 自动消失，手动 ✕ 立即关闭。
     * 与 Sidebar 的 _flash 不同 —— 本警告只在输入框附近显示，且只服务
     * 「对话框文件上传不被接受」这一种语义，作用域更窄。
     */
    _setDragDropWarning(message) {
      this.dragDropWarning = message
      if (this._dragDropWarningTimer) {
        clearTimeout(this._dragDropWarningTimer)
      }
      this._dragDropWarningTimer = setTimeout(() => {
        this.dragDropWarning = null
        this._dragDropWarningTimer = null
      }, 5000)
    },

    _dismissDragDropWarning() {
      this.dragDropWarning = null
      if (this._dragDropWarningTimer) {
        clearTimeout(this._dragDropWarningTimer)
        this._dragDropWarningTimer = null
      }
    },

    async addFiles(newFiles) {
      if (!newFiles || newFiles.length === 0) return

      // 先验证文件是否合法（复用现有的验证逻辑）
      const validationResults = newFiles.map(file => {
        const validation = this.validateFile(file)
        return {
          file,
          valid: validation.valid,
          error: validation.error
        }
      })

      // 收集无效文件并显示警告横幅（让用户清楚「拖进来但没生效」的原因）
      const invalidItems = validationResults.filter(r => !r.valid)
      if (invalidItems.length > 0) {
        console.warn('以下文件不符合要求:', invalidItems.map(r => `${r.file.name}: ${r.error}`))
        // 拼简短文案：最多列 3 个文件名 + 「等 N 个」+ 第一条原因
        // 文件名可能很长（Windows 路径 / Unicode），按 30 字截断避免横幅撑爆
        const truncateName = (n) => (n && n.length > 30 ? n.slice(0, 27) + '…' : n)
        const names = invalidItems.slice(0, 3).map(r => truncateName(r.file.name)).join('、')
        const more = invalidItems.length > 3 ? ` 等 ${invalidItems.length} 个` : ''
        const firstReason = invalidItems[0].error || '不支持的文件类型'
        this._setDragDropWarning(`不支持：${names}${more}（${firstReason}）`)
        // 如果所有文件都无效，直接返回（已弹警告，无需再走后续会话创建 / 入队逻辑）
        if (invalidItems.length === validationResults.length) {
          return
        }
      }

      // 检查是否需要创建新会话
      // 如果当前 URL 没有 sessionId（即在新会话页面），则创建新会话
      // 必须读 hash 不用 pathname：vue-router 已切到 hash 模式（file:// + reload 兼容），
      // pathname 始终是 index.html 的磁盘路径，从来没有 sid 信息。
      const urlHash = window.location.hash  // 例: "#/<sid>" / "#/" / ""
      const urlHasSessionId = urlHash && urlHash !== '#/' && urlHash !== '#'

      console.log('[addFiles] urlHash:', urlHash, 'urlHasSessionId:', urlHasSessionId)

      if (!urlHasSessionId) {
        // 生成新的 session_id
        const sessionId = crypto.randomUUID().replace(/-/g, '').slice(0, 12)
        localStorage.setItem('currentSessionId', sessionId)
        localStorage.setItem('pendingSessionId', sessionId)

        // 尝试读取文件内容并存入 sessionStorage（用于页面跳转后恢复）
        try {
          const pendingFiles = []
          for (const file of newFiles) {
            // 只存储通过验证的文件
            const validation = this.validateFile(file)
            if (!validation.valid) continue

            const buffer = await file.arrayBuffer()
            pendingFiles.push({
              name: file.name,
              size: file.size,
              type: file.type,
              buffer: Array.from(new Uint8Array(buffer)) // 转为普通数组以便 JSON 序列化
            })
          }
          sessionStorage.setItem('pendingUploadFiles', JSON.stringify(pendingFiles))
        } catch (e) {
          console.warn('存储文件内容失败（文件可能较大），将在新页面提示重新选择:', e)
          // 只存储通过验证的文件（无效文件不需要重新选择）
          const validOnly = newFiles.filter(file => this.validateFile(file).valid)
          sessionStorage.setItem('pendingUploadFiles', JSON.stringify(validOnly.map(f => ({
            name: f.name,
            size: f.size,
            type: f.type,
            needsReselect: true
          }))))
        }

        // 跳转到新会话页面
        console.log('[addFiles] Created new session:', sessionId, 'navigating to /', sessionId)
        this.$emit('files-selected-need-session', newFiles)
        return
      }

      const validatedFiles = newFiles.map(file => {
        const fileObj = {
          name: file.name,
          size: file.size,
          type: file.type,
          file: file,
          error: null,
          preview: null,
          fileId: null,
          uploading: false
        }

        const validation = this.validateFile(file)
        if (!validation.valid) {
          fileObj.error = validation.error
        } else if (this.isImageFile(fileObj)) {
          fileObj.preview = URL.createObjectURL(file)
        }

        return fileObj
      })

      const validFiles = validatedFiles.filter(f => !f.error)
      const invalidFiles = validatedFiles.filter(f => f.error)

      this.selectedFiles.push(...invalidFiles)

      if (validFiles.length > 0) {
        // 将有效文件添加到队列
        this.uploadQueue.push(...validFiles)

        // 如果队列未在处理，则开始处理
        if (!this.isUploadQueueProcessing) {
          this.processUploadQueue()
        }
      }
    },

    async processUploadQueue() {
      if (this.uploadQueue.length === 0) {
        this.isUploadQueueProcessing = false
        return
      }

      this.isUploadQueueProcessing = true

      // 取出队列中的所有文件
      const filesToUpload = [...this.uploadQueue]
      this.uploadQueue = []

      // 标记为上传中
      filesToUpload.forEach(fileObj => {
        fileObj.uploading = true
      })
      this.selectedFiles.push(...filesToUpload)
      this.$forceUpdate()

      // 整批文件一次性上传
      await this.uploadFilesBatch(filesToUpload)

      // 这一批完成后，继续处理下一批
      this.processUploadQueue()
    },

    async uploadFilesBatch(fileObjs) {
      const formData = new FormData()

      // 添加所有文件
      fileObjs.forEach(fileObj => {
        formData.append('files', fileObj.file)
      })

      // 携带当前已处理的文件列表
      formData.append('processed_outputs', JSON.stringify(this.processedOutputs))

      // 构建上传 URL（确保有 sessionId）
      // 优先从 URL 直接获取 sessionId，这是最可靠的（路由已完成导航）
      // 改读 hash：hash 模式下 pathname 是 index.html，永远没有 sid
      const hashParts = window.location.hash.split('/')  // 例: ["#", "<sid>"] 或 ["", ""]
      const urlSessionId = hashParts.length >= 2 && hashParts[1] ? hashParts[1] : null
      // 尝试多种方式获取 sessionId：prop > URL > localStorage
      const currentSid = this.currentSessionId || urlSessionId || localStorage.getItem('pendingSessionId') || localStorage.getItem('currentSessionId')
      const uploadUrl = currentSid
        ? `/chat/${currentSid}/upload_file`
        : '/chat/upload_file'  // 兜底

      console.log('[uploadFilesBatch] hash:', window.location.hash, 'hashParts:', hashParts, 'urlSessionId:', urlSessionId, 'currentSid:', currentSid, 'this.currentSessionId:', this.currentSessionId)

      console.log('上传文件批次:', {
        fileCount: fileObjs.length,
        fileNames: fileObjs.map(f => f.name),
        processedOutputsLength: this.processedOutputs.length,
        sessionId: currentSid
      })

      try {
        const response = await fetch(uploadUrl, {
          method: 'POST',
          body: formData
        })

        if (!response.ok) {
          const errorText = await response.text()
          console.error('文件上传失败:', response.status, errorText)
          throw new Error(`文件上传失败: ${response.status}`)
        }

        const data = await response.json()

        if (data.code === 200) {
          // 更新全局 processedOutputs
          this.processedOutputs = data.processed_outputs || []
          console.log('批次上传成功，processedOutputs 数量:', this.processedOutputs.length)

          // 更新每个文件的信息
          fileObjs.forEach(fileObj => {
            const output = this.processedOutputs.find(
              op => op.name === fileObj.name
            )

            if (output) {
              fileObj.fileId = output.file_id
              if (output.preview) {
                fileObj.preview = output.preview
              }
              if (output.iframe_url) {
                fileObj.iframe_url = output.iframe_url
              }
            }
          })
        } else {
          throw new Error(data.msg || '文件上传失败')
        }
      } catch (error) {
        console.error('批次上传失败:', error)
        // 标记所有文件为失败
        fileObjs.forEach(fileObj => {
          fileObj.error = '上传失败'
        })
      } finally {
        fileObjs.forEach(fileObj => {
          fileObj.uploading = false
        })
        this.$forceUpdate()
      }
    },

    validateFile(file) {
      const extension = this.getFileExtension(file.name)

      // 检查文件大小
      if (file.size > this.maxFileSize) {
        return {
          valid: false,
          error: `文件超过 ${this.formatFileSize(this.maxFileSize)} 限制，到文件树处查看指引来上传`
        }
      }

      // 检查文件扩展名
      const isAllowed = this.allowedExtensions.some(
        allowedExt => allowedExt.toLowerCase() === extension.toLowerCase()
      )

      if (!isAllowed) {
        return {
          valid: false,
          error: `不支持的文件类型 ${extension}`
        }
      }

      return { valid: true }
    },

    async removeFile(index) {
      const file = this.selectedFiles[index]

      // 如果文件还在队列中未上传，先从队列移除
      if (file.uploading === false && file.fileId === null) {
        const queueIndex = this.uploadQueue.findIndex(f => f === file)
        if (queueIndex !== -1) {
          this.uploadQueue.splice(queueIndex, 1)
        }
      }

      // 如果文件已上传，调用后端取消
      if (file.fileId && this.processedOutputs.length > 0) {
        try {
          const response = await fetch('/chat/cancel_upload_file', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              file_id: file.fileId,
              processed_outputs: this.processedOutputs
            })
          })

          if (response.ok) {
            const data = await response.json()
            this.processedOutputs = data.processed_outputs || []
          }
        } catch (error) {
          console.error('取消文件上传失败:', error)
        }
      }

      if (file.preview) {
        URL.revokeObjectURL(file.preview)
      }
      this.selectedFiles.splice(index, 1)
    },

    clearFiles() {
      this.selectedFiles.forEach(file => {
        if (file.preview) {
          URL.revokeObjectURL(file.preview)
        }
      })
      this.selectedFiles = []
      this.processedOutputs = []
      this.uploadQueue = []
    },

    /**
     * 清空动态 skill 缓存。App.vue 在切/刷会话时调（`$refs.messageInput.clearDynamicSkills()`），
     * sessionId 变化由本组件的 watcher 内部处理。这里仅暴露给外部 sid 不变的
     * 场景（典型：`refreshConversation(sid)` —— sid 不变但消息被重拉）。
     *
     * 下次打开 slash 面板时由于 `dynamicSkills.length === 0`，会触发
     * `fetchSkills()` 重新拉一次，覆盖 SkillForge 中途新增的 skill。
     *
     * 暴露在 `expose` 数组里供父组件调用。
     */
    clearDynamicSkills() {
      this.dynamicSkills = []
    },

    // 清理输入框内容（切换/删除对话时调用）
    clearInput() {
      this.inputText = ''
      this.activeSlashCommand = null
      this.closeSlashPalette()
      this.clearFiles()
      // 清理引用状态
      this.$emit('update:quote', null)
      // 撤回文本的 localStorage 同步清掉（与 sendMessage 路径一致，
      // 避免下次切回同会话误恢复已被用户主动清空的文本）
      const sid = this.sessionId
      if (sid) localStorage.removeItem(`chatme-withdraw-pending:${sid}`)
    },

    // 撤回按钮调用：把原用户消息文本回填到输入框
    // files / processedOutputs 暂不恢复（v1 边界，用户需重传附件）
    setInputText(text) {
      const value = typeof text === 'string' ? text : ''
      this.inputText = value
      this.clearFiles()
      this.$emit('update:quote', null)
      this.$nextTick(() => {
        this.autoResize()
        // 把光标放到末尾，方便用户继续编辑
        const ta = this.$refs.textarea
        if (ta) {
          ta.focus()
          ta.setSelectionRange(value.length, value.length)
        }
      })
    },
    /**
     * 暴露给 App.vue 的「归还焦点」入口。任何弹窗 / 面板 / 审批 / 刷新
     * 完成事件回调里调一下，光标自动回到输入框，光标位置放末尾让用户
     * 接着打字。用 $nextTick 等 DOM 更新完再 focus，避免和 v-if 等过渡冲突。
     *
     * 暴露在 `expose` 数组里（首行）供父组件 this.$refs.messageInput.focusTextarea() 调用。
     */
    focusTextarea() {
      this.$nextTick(() => {
        const ta = this.$refs.textarea
        if (!ta || typeof ta.focus !== 'function') return
        ta.focus()
        try {
          // 光标放末尾（用户在「先做完别的事再回来输入」的场景下，期望从尾继续）
          const len = (this.inputText || '').length
          ta.setSelectionRange(len, len)
        } catch (_) { /* read-only 场景（如表单 readonly）静默吞 */ }
      })
    },

    // 关闭引用块（用户点击 × 按钮）
    onCloseQuote() {
      this.$emit('update:quote', null)
    },

    getFileExtension(filename) {
      if (!filename || !filename.includes('.')) return ''
      return '.' + filename.split('.').pop().toLowerCase()
    },

    isImageFile(fileObj) {
      const extension = this.getFileExtension(fileObj.name)
      return this.allowedImageTypes.includes(extension)
    },

    formatFileSize(bytes) {
      if (bytes === 0) return '0 B'
      const k = 1024
      const sizes = ['B', 'KB', 'MB', 'GB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
    },

    truncateFileName(filename, maxLength) {
      if (filename.length <= maxLength) return filename
      const extension = this.getFileExtension(filename)
      const nameWithoutExt = filename.substring(0, filename.length - extension.length)
      const truncatedName = nameWithoutExt.substring(0, maxLength - 3 - extension.length)
      return truncatedName + '...' + extension
    },
  }
}
</script>

<style scoped>
.input-area {
  position: relative;
  padding: 16px;
  background-color: var(--bg-primary);
  border-top: 1px solid var(--border-color);
}

/* 引用块（ChatGPT 风格） */
.quote-block {
  max-width: 900px;
  margin: 0 auto 10px;
  display: flex;
  align-items: stretch;
  gap: 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
}

.quote-block-bar {
  flex-shrink: 0;
  width: 3px;
  background: var(--button-bg);
}

.quote-block-content {
  flex: 1;
  min-width: 0;
  padding: 8px 4px 8px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quote-block-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--button-bg);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.quote-block-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  word-wrap: break-word;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 5;
  line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.quote-block-text :deep(p) {
  margin: 0 0 4px 0;
  white-space: pre-wrap;
}

.quote-block-text :deep(p:last-child) {
  margin-bottom: 0;
}

.quote-block-text :deep(a) {
  color: var(--button-bg);
  text-decoration: none;
  word-break: break-all;
}

.quote-block-text :deep(a:hover) {
  text-decoration: underline;
}

.quote-block-text :deep(code) {
  background: var(--hover-bg);
  color: var(--text-primary);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.quote-block-text :deep(pre) {
  background: var(--hover-bg);
  color: var(--text-primary);
  padding: 6px 8px;
  border-radius: 4px;
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  margin: 0 0 4px 0;
  white-space: pre-wrap;
}

.quote-block-text :deep(pre:last-child) {
  margin-bottom: 0;
}

.quote-block-text :deep(strong) {
  font-weight: 600;
  color: var(--text-primary);
}

.quote-block-text :deep(em) {
  font-style: italic;
}

.quote-block-text :deep(ul),
.quote-block-text :deep(ol) {
  margin: 0 0 4px 0;
  padding-left: 20px;
}

.quote-block-text :deep(ul:last-child),
.quote-block-text :deep(ol:last-child) {
  margin-bottom: 0;
}

.quote-block-text :deep(li) {
  margin: 0;
}

.quote-block-text :deep(blockquote) {
  border-left: 3px solid var(--border-color);
  padding-left: 8px;
  margin: 0 0 4px 0;
  color: var(--text-secondary);
}

.quote-block-text :deep(h1),
.quote-block-text :deep(h2),
.quote-block-text :deep(h3),
.quote-block-text :deep(h4),
.quote-block-text :deep(h5),
.quote-block-text :deep(h6) {
  margin: 0 0 4px 0;
  font-weight: 600;
  font-size: 13px;
  line-height: 1.4;
}

.quote-block-text :deep(h1:last-child),
.quote-block-text :deep(h2:last-child),
.quote-block-text :deep(h3:last-child),
.quote-block-text :deep(h4:last-child),
.quote-block-text :deep(h5:last-child),
.quote-block-text :deep(h6:last-child) {
  margin-bottom: 0;
}

.quote-block-text :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 4px;
}

.quote-block-text :deep(table) {
  border-collapse: collapse;
  font-size: 12px;
  margin: 0 0 4px 0;
}

.quote-block-text :deep(th),
.quote-block-text :deep(td) {
  border: 1px solid var(--border-color);
  padding: 2px 6px;
}

.quote-block-text :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-color);
  margin: 4px 0;
}

.quote-block-close {
  flex-shrink: 0;
  align-self: flex-start;
  margin: 6px 8px 0 0;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.quote-block-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
/* 拖拽上传警告横幅：仅在对话框（MessageInput）内显示，文件树区域不限类型不上警告。
   amber 色 + ⚠ 图标，与现有 file-error 红点错开（红点是「已加入但上传失败」，
   本 banner 是「拖进来但根本不被接受」）。5s 自动消失 + ✕ 手动关闭。 */
.drag-drop-warning {
  max-width: 900px;
  margin: 0 auto 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 6px;
  color: rgb(180, 83, 9);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 600px) {
  .drag-drop-warning {
    max-width: 100%;
  }
}

.drag-drop-warning-icon {
  flex-shrink: 0;
  color: rgb(217, 119, 6);
}

.drag-drop-warning-text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

.drag-drop-warning-close {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  border-radius: 4px;
  opacity: 0.6;
  transition: opacity 0.12s, background 0.12s;
}

.drag-drop-warning-close:hover {
  opacity: 1;
  background: rgba(217, 119, 6, 0.12);
}

.drag-drop-warning-enter-active,
.drag-drop-warning-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.drag-drop-warning-enter-from,
.drag-drop-warning-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* 文件列表容器 - 横向紧凑布局 */
.file-list-container {
  max-width: 900px;
  margin: 0 auto 12px;
  overflow: hidden;
}

@media (max-width: 600px) {
  .file-list-container {
    max-width: 100%;
    margin-bottom: 8px;
  }
}

.file-list-scroll {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 4px 0;
  scrollbar-width: thin;
  scrollbar-color: var(--border-color) transparent;
}

.file-list-scroll::-webkit-scrollbar {
  height: 6px;
}

.file-list-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.file-list-scroll::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

.file-list-scroll::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

.file-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  width: 80px;
}

.file-item.file-error .file-preview-wrapper {
  border-color: #ef4444;
}

.file-item.file-uploading .file-preview-wrapper {
  border-color: var(--button-bg);
  opacity: 0.7;
}

.file-preview-wrapper {
  position: relative;
  width: 80px;
  height: 80px;
  border: 2px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  background: var(--message-bg);
  transition: all 0.2s;
}

.file-preview-wrapper:hover {
  border-color: var(--primary-color);
}

.file-preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-icon-compact {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  background: var(--hover-bg);
}

.file-name-compact {
  font-size: 11px;
  color: var(--text-primary);
  text-align: center;
  width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 2px;
}

.file-error-badge {
  position: absolute;
  top: 4px;
  left: 4px;
  width: 20px;
  height: 20px;
  background: #ef4444;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
  cursor: help;
}

.remove-button-overlay {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 24px;
  height: 24px;
  border: none;
  background: rgba(0, 0, 0, 0.6);
  color: white;
  cursor: pointer;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.2s;
}

.file-preview-wrapper:hover .remove-button-overlay {
  opacity: 1;
}

.remove-button-overlay:hover {
  background: #ef4444;
  transform: scale(1.1);
}

.uploading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}

.spinner-small {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 输入区域 */
.input-wrapper {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

@media (max-width: 600px) {
  .input-wrapper {
    max-width: 100%;
    padding: 0;
    gap: 8px;
  }
  .input-area {
    padding: 12px;
  }
}

.upload-button {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 12px;
  transition: all 0.2s;
}

.upload-button:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.upload-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.optimize-button {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 12px;
  transition: all 0.3s ease;
  border: 1px solid var(--border-color);
  position: relative;
  overflow: hidden;
}

.optimize-button::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  border-radius: 50%;
  background: var(--button-bg);
  opacity: 0;
  transform: translate(-50%, -50%);
  transition: width 0.6s, height 0.6s, opacity 0.6s;
}

.optimize-button.optimizing::before {
  width: 100%;
  height: 100%;
  opacity: 0.1;
  animation: pulse 1.5s ease-in-out infinite;
}

.optimize-button:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--button-bg);
  border-color: var(--button-bg);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(16, 163, 127, 0.2);
}

.optimize-button:active:not(:disabled) {
  transform: translateY(0);
}

.optimize-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.optimize-button.optimizing {
  border-color: var(--button-bg);
  color: var(--button-bg);
}

.optimize-button .spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%, 100% {
    opacity: 0.1;
    transform: translate(-50%, -50%) scale(1);
  }
  50% {
    opacity: 0.2;
    transform: translate(-50%, -50%) scale(1.1);
  }
}

.input-wrapper textarea {
  /* textarea 已搬到 .composer 里，下面的样式在 .composer textarea 块中重新定义 */
}

/* Slash chip —— 输入框里"挂"在 textarea 上方的命令胶囊。
   Codex CLI 风格：紫底浅色 + monospace 名称 + 右侧 × 移除。
   chip 只承载"已选命令"的事实，textarea 永远不出现 `/[xxx]` 原文。 */
.composer {
  flex: 1;
  position: relative;
  display: flex;
  align-items: stretch;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background-color: var(--bg-secondary);
  transition: border-color 0.2s;
  overflow: hidden;
  /* chip 宽度（measureChipMinWidth 写入），textarea padding-left 读这个变量对齐首字符 */
  --chip-min-width: 0px;
}

.composer:focus-within {
  border-color: var(--button-bg);
}

.composer textarea {
  width: 100%;
  min-height: 52px;
  max-height: 200px;
  height: 52px;
  padding: 14px 16px;
  border: none;
  border-radius: 0;
  background: transparent;
  color: var(--text-primary);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  outline: none;
  line-height: 1.5;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.1) transparent;
  overflow-y: hidden;
  text-indent: 0;
}

/* chip 在场时 textarea 左侧 padding 留出 chip 空间，文本仍从左到右自然书写 */
.composer textarea.composer-textarea--with-chip {
  padding-left: var(--chip-min-width, 0px);
}

.composer textarea::-webkit-scrollbar {
  width: 6px;
}

.composer textarea::-webkit-scrollbar-track {
  background: transparent;
}

.composer textarea::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.1);
  border-radius: 3px;
}

.composer textarea::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.15);
}

.dark-theme .composer textarea::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
}

.dark-theme .composer textarea::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}

.composer textarea::placeholder {
  color: var(--text-secondary);
  opacity: 0.6;
}

/* slash chip —— 绝对定位浮在 textarea 第一行起始位置之上。
   textarea padding-top = 14px（首行顶部），line-height: 1.5 × font-size 15px ≈ 22.5px。
   chip 自身高度 ≈ 22px（border + padding + content），把 top 设到首行顶部位置
   再用 translateY 微调到 baseline 视觉对齐。 */
.slash-chip {
  position: absolute;
  top: 14px;
  left: 16px;
  transform: translateY(-1px);
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px 4px 3px 9px;
  background: rgba(59, 130, 246, 0.14);
  color: rgb(59, 130, 246);
  border: 1px solid rgba(59, 130, 246, 0.28);
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1;
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  letter-spacing: 0.01em;
  /* chip 整体不接收鼠标事件 —— 让 click 穿透到底层 textarea，
     用户点 chip 范围（除 ×按钮外）能正常定位光标到首字符位置。
     只有 ×按钮显式恢复 pointer-events: auto。 */
  pointer-events: none;
  z-index: 1;
  white-space: nowrap;
  max-width: calc(100% - 32px);
  overflow: hidden;
  text-overflow: ellipsis;
}

.dark-theme .slash-chip {
  background: rgba(59, 130, 246, 0.18);
  color: rgb(59, 130, 246);
  border-color: rgba(59, 130, 246, 0.32);
}

.slash-chip-slash {
  opacity: 0.6;
  font-weight: 400;
}

.slash-chip-name {
  font-weight: 600;
}

.slash-chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-left: 3px;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  border-radius: 4px;
  cursor: pointer;
  opacity: 0.55;
  transition: opacity 0.12s, background 0.12s;
  /* ×按钮恢复交互（覆盖父级 pointer-events: none） */
  pointer-events: auto;
}

.slash-chip-remove:hover {
  opacity: 1;
  background: rgba(59, 130, 246, 0.18);
}

.slash-chip-pop-enter-active,
.slash-chip-pop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.slash-chip-pop-enter-from,
.slash-chip-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.96);
}

.send-btn {
  flex-shrink: 0;
  height: 52px;
  padding: 0 24px;
  border: none;
  background: var(--button-bg);
  color: white;
  border-radius: 12px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 500;
  transition: background 0.2s;
}

.send-btn:hover:not(:disabled) {
  background: var(--button-hover);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 拖拽遮罩：v0.2.x 起 drag-overlay 不再在 MessageInput 内部渲染，
   由 App.vue 在 .chat-area 子元素渲染（position: absolute 覆盖 chat 区域），
   避免 sidebarView === 'files' 时 chat overlay 全屏遮住 sidebar 的 system-drag-overlay。
   —— 「两片地方分开」的核心重构。 */

/* ===== 排队卡（流式中继续发送时进入 Redis 队列的待发消息） ===== */
/* 走 lingxi 中性冷淡风格：全部 var(--*) 主题 token，无 brand 强调色；
   与引用块 / 文件列表视觉对齐，仅靠极简的左侧细条 + 灰底 + 数字标来区分。 */
.queue-list-container {
  margin-bottom: 8px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-secondary);
  overflow: hidden;
}

.queue-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-color);
  background: transparent;
}

.queue-list-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
}

.queue-list-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-secondary);
  opacity: 0.55;
  animation: queue-pulse 1.5s ease-in-out infinite;
}

@keyframes queue-pulse {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 0.9; }
}

.queue-list-clear {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.queue-list-clear:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
  color: var(--text-primary);
}

.queue-list-scroll {
  max-height: 110px;
  overflow-y: auto;
  padding: 4px;
}

.queue-list-scroll::-webkit-scrollbar {
  width: 6px;
}

.queue-list-scroll::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

.queue-list-scroll::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

.queue-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--bg-primary);
  border: 1px solid transparent;
  margin-bottom: 4px;
  transition: background 0.15s, border-color 0.15s;
}

.queue-item:last-child {
  margin-bottom: 0;
}

.queue-item:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
}

.queue-item-index {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 500;
  color: var(--text-secondary);
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 10px;
  min-width: 26px;
  text-align: center;
}

.queue-item-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.queue-item-quote {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--text-secondary);
}

.queue-item-text {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.queue-item-remove {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  opacity: 0;
}

.queue-item:hover .queue-item-remove {
  opacity: 1;
}

.queue-item-remove:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
  color: var(--text-primary);
}
</style>
