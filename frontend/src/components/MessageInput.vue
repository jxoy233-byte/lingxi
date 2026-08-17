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

    <!-- 排队机制保留在 App.vue 后端（流式中点击发送 → 入 Redis → 上轮结束自动 drain），
         此处不渲染任何排队卡 / "排队中(N)" 头 / 进度提示 —— 走 ChatGPT/Codex 风格：
         用户点完「发送」消息透明吸收，看起来就像即时发送，下轮响应自然接上。 -->

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

      <textarea
        v-model="inputText"
        @keydown.enter="handleEnterKey"
        @input="autoResize"
        @paste="handlePaste"
        placeholder="输入消息..."
        rows="1"
        ref="textarea"
      ></textarea>

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

    <!-- 拖拽区域遮罩 -->
    <div
      v-if="isDragging"
      class="drag-overlay"
      @drop.prevent="handleDrop"
      @dragover.prevent
      @dragleave="isDragging = false"
    >
      <div class="drag-content">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
        <p>释放文件以上传</p>
      </div>
    </div>
  </div>
</template>

<script>
import { marked } from 'marked'

export default {
  name: 'MessageInput',
  expose: ['clearInput', 'getSessionId', 'setSessionId', 'checkAndUploadPendingFiles', 'setInputText'],
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
  emits: ['send', 'files-selected-need-session', 'update:quote', 'remove-queue-item', 'clear-queue'],
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
      currentSessionId: null
    }
  },
  computed: {
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
    sessionId: {
      handler(newVal) {
        this.currentSessionId = newVal
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
    // 监听全局拖拽事件
    window.addEventListener('dragenter', this.handleDragEnter)
    window.addEventListener('dragover', this.handleDragOver)
    window.addEventListener('drop', this.handleWindowDrop)
  },
  beforeUnmount() {
    // 清理事件监听
    window.removeEventListener('dragenter', this.handleDragEnter)
    window.removeEventListener('dragover', this.handleDragOver)
    window.removeEventListener('drop', this.handleWindowDrop)

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

      // 如果有引用，把引用内容拼到 message 前面（<quote>...</quote> 标记）
      let finalMessage = this.inputText.trim()
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

    handleDragEnter(e) {
      e.preventDefault()
      if (this.isLoading) return

      // 检查是否包含文件
      if (e.dataTransfer.types.includes('Files')) {
        this.isDragging = true
      }
    },

    handleDragOver(e) {
      e.preventDefault()
    },

    handleWindowDrop(e) {
      e.preventDefault()
      this.isDragging = false
    },

    handleDrop(e) {
      this.isDragging = false
      if (this.isLoading) return

      const droppedFiles = Array.from(e.dataTransfer.files)
      this.addFiles(droppedFiles)
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

      // 收集无效文件并显示错误
      const invalidCount = validationResults.filter(r => !r.valid).length
      if (invalidCount > 0) {
        // 显示错误提示
        console.warn('以下文件不符合要求:', validationResults.filter(r => !r.valid).map(f => `${f.file.name}: ${f.error}`))
        // 如果所有文件都无效，直接返回
        const validOnly = validationResults.filter(r => r.valid)
        if (validOnly.length === 0) {
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

    // 清理输入框内容（切换/删除对话时调用）
    clearInput() {
      this.inputText = ''
      this.clearFiles()
      // 清理引用状态
      this.$emit('update:quote', null)
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
  flex: 1;
  min-height: 52px;
  max-height: 200px;
  height: 52px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  outline: none;
  transition: border-color 0.2s;
  overflow-y: hidden;
  line-height: 1.5;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.1) transparent;
}

.input-wrapper textarea::-webkit-scrollbar {
  width: 6px;
}

.input-wrapper textarea::-webkit-scrollbar-track {
  background: transparent;
}

.input-wrapper textarea::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.1);
  border-radius: 3px;
}

.input-wrapper textarea::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.15);
}

/* 暗色主题下的滚动条 */
.dark-theme .input-wrapper textarea {
  scrollbar-color: rgba(255, 255, 255, 0.1) transparent;
}

.dark-theme .input-wrapper textarea::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
}

.dark-theme .input-wrapper textarea::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}

.input-wrapper textarea:focus {
  border-color: var(--button-bg);
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

/* 拖拽遮罩 */
.drag-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
}

.drag-content {
  text-align: center;
  color: white;
  pointer-events: none;
}

.drag-content svg {
  margin-bottom: 16px;
  animation: bounce 1s infinite;
}

.drag-content p {
  font-size: 18px;
  font-weight: 500;
}

@keyframes bounce {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}
</style>
