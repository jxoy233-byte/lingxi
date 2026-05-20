<template>
  <div :class="['app-container', { 'dark-theme': isDarkTheme }]">
    <div class="main-layout">
      <Sidebar
        :collapsed="sidebarCollapsed"
        :conversations="conversations"
        :active-session-id="currentSessionId"
        :display-count="displayCount"
        :mobile-open="sidebarMobileOpen"
        @toggle="toggleSidebar"
        @new-chat="createNewChat"
        @select-conversation="loadConversation"
        @delete-conversation="deleteConversation"
        @update-title="updateConversationTitle"
        @load-more="loadMoreConversations"
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
          :is-dark-theme="isDarkTheme"
          :has-session="!!currentSessionId"
          @toggle-theme="toggleTheme"
          @toggle-checkpoints="toggleCheckpoints"
          @toggle-sidebar="toggleMobileSidebar"
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
          @restore="restoreCheckpoint"
          @restream="handleRestream"
          @open-link="openWebPreview"
          @preview-file="previewFile"
          @interrupt="handleInterrupt"
          @resume="handleResume"
        />

        <MessageInput
          ref="messageInput"
          :is-loading="isLoading"
          @send="sendMessage"
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
        :file-name="filePreviewName"
        :content="filePreviewContent"
        @close="showFilePreview = false"
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
    </div>

    <ConfirmDialog
      :visible="showDeleteConfirm"
      title="ChatMe 显示"
      message="确定要删除这个对话吗？"
      confirm-text="确定"
      cancel-text="取消"
      @confirm="confirmDelete"
      @cancel="cancelDelete"
    />

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
  </div>
</template>

<script>
import Sidebar from './components/Sidebar.vue'
import ChatHeader from './components/ChatHeader.vue'
import MessageList from './components/MessageList.vue'
import MessageInput from './components/MessageInput.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import CheckpointPanel from './components/CheckpointPanel.vue'
import WebPreviewPanel from './components/WebPreviewPanel.vue'
import FilePreviewPanel from './components/FilePreviewPanel.vue'

export default {
  name: 'App',
  components: {
    Sidebar,
    ChatHeader,
    MessageList,
    MessageInput,
    ConfirmDialog,
    CheckpointPanel,
    WebPreviewPanel,
    FilePreviewPanel
  },
  data() {
    return {
      isDarkTheme: false,
      sidebarCollapsed: false,
      conversations: [],
      currentSessionId: null,
      messages: [],
      isLoading: false,
      showDeleteConfirm: false,
      deleteTargetId: null,
      showCheckpoints: false,
      showRestoreConfirm: false,
      restoreTargetId: null,
      showWebPreview: false,
      webPreviewUrl: '',
      isResizingWebPreview: false,
      showImagePreview: false,
      imagePreviewUrl: '',
      showFilePreview: false,
      filePreviewName: '',
      filePreviewContent: '',
      responseStartTime: null,
      responseTimerInterval: null,
      currentResponseTime: 0,
      currentAiMessageIndex: null,
      displayCount: 10,
      isRestreaming: false,
      isInterrupted: false,  // 当前会话是否处于中断状态
      isInterruptedSessionId: null,  // 最近一次中断的会话ID
      hasReceivedInit: false,  // 流式响应是否已收到 init 消息
      _pendingInterruptSessionId: null,  // 临时存储流式响应中的 session_id
      isMobile: false,
      sidebarMobileOpen: false,
      interruptReason: '',  // 中断原因
      showResumeInput: false,  // 显示续接输入框
      resumeInputText: ''  // 续接输入文本
    }
  },
  mounted() {
    const savedTheme = localStorage.getItem('chatme-theme')
    if (savedTheme) {
      this.isDarkTheme = savedTheme === 'dark'
    }

    // 检测移动端
    this.isMobile = window.innerWidth <= 600
    window.addEventListener('resize', this.handleResize)

    this.loadConversations()

    // 直接显示新对话界面，不调用 get_conversation 获取会话详情
    // 延迟初始化：确保 router 完全就绪后再处理 URL 参数
    this.$nextTick(() => {
      const initialSessionId = this.$route.params.sessionId
      if (initialSessionId) {
        this.loadConversation(initialSessionId)
      } else {
        this.createNewChat()
      }
    })
  },
  watch: {
    '$route.params.sessionId'(newSessionId) {
      // 监听 URL 变化
      if (newSessionId && newSessionId !== this.currentSessionId && newSessionId.trim() !== '') {
        this.loadConversation(newSessionId)
      } else if (!newSessionId || newSessionId.trim() === '') {
        this.createNewChat()
      }
    }
  },
  methods: {
    toggleTheme() {
      this.isDarkTheme = !this.isDarkTheme
      localStorage.setItem('chatme-theme', this.isDarkTheme ? 'dark' : 'light')
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
              } else if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_name') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                toolCalls.push({ name: data.content.name, args: data.content.args, id: data.id, result: null })
                this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], toolCalls, responseTime: this.currentResponseTime }
              } else if (data.type === 'tool_call_result') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                const idx = toolCalls.findIndex(tc => tc.id === data.id)
                if (idx !== -1) toolCalls[idx] = { ...toolCalls[idx], result: data.content }
                this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], toolCalls, responseTime: this.currentResponseTime }
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
                // 获取最后一个用户消息来更新标题
                const lastUserMessage = this.messages.filter(m => m.role === 'user').pop()?.content || ''
                await this.updateTitleAndRefresh(this.currentSessionId, lastUserMessage)
              } else if (data.type === 'error') {
                console.error('续接响应错误:', data.error)
                this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], content: `续接失败：${data.error}`, streaming: false }
              } else if (data.type === 'interrupt') {
                this.stopResponseTimer()
                const reason = data.reason || '用户主动中断'
                this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], streaming: false, interruptReason: reason }
                this.isInterrupted = true
                this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
                this.interruptReason = reason
              }
            } catch (e) {
              console.error('解析 SSE 消息失败:', e, '原始内容:', line)
            }
          }
        }
        if (buffer.trim()) {
          try {
            const data = JSON.parse(buffer.trim())
            if (data.type === 'reasoning') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                responseTime: this.currentResponseTime
              }
            } else if (data.type === 'tool_call_name') {
              const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
              toolCalls.push({ name: data.content.name, args: data.content.args, id: data.id, result: null })
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                toolCalls,
                responseTime: this.currentResponseTime
              }
            } else if (data.type === 'tool_call_result') {
              const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
              const idx = toolCalls.findIndex(tc => tc.id === data.id)
              if (idx !== -1) toolCalls[idx] = { ...toolCalls[idx], result: data.content }
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                toolCalls,
                responseTime: this.currentResponseTime
              }
            } else if (data.type === 'content') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                content: this.messages[aiMessageIndex].content + data.content,
                thinkingDone: true,
                responseTime: this.currentResponseTime
              }
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
            } else if (data.type === 'interrupt') {
              this.stopResponseTimer()
              const reason = data.reason || '用户主动中断'
              this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], streaming: false, interruptReason: reason }
              this.isInterrupted = true
              this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
              this.interruptReason = reason
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
    previewFile(file) {
      // 根据文件类型决定预览方式
      const fileType = (file.file_type || file.type || '').toUpperCase()
      const suffix = (file.suffix || (file.name ? '.' + file.name.split('.').pop().toLowerCase() : '')).toLowerCase()

      // 图片文件：使用专用图片预览
      if (fileType === 'IMAGE' || (file.type && file.type.startsWith('image/'))) {
        // 图片URL优先从preview_url获取，其次是image_content
        let imageUrl = file.preview_url || ''
        if (!imageUrl && file.image_content) {
          if (typeof file.image_content === 'string') {
            imageUrl = file.image_content
          } else if (Array.isArray(file.image_content) && file.image_content.length > 0) {
            const first = file.image_content[0]
            if (typeof first === 'string') {
              imageUrl = first
            } else if (typeof first === 'object' && first.url) {
              imageUrl = first.url
            }
          }
        }
        if (imageUrl) {
          this.imagePreviewUrl = imageUrl
          this.showImagePreview = true
        }
        return
      }

      // 如果文件有 text_content 或 content，优先使用文件预览面板展示
      const textContent = file.text_content || file.content || ''
      if (typeof textContent === 'string' && textContent.length > 0) {
        this.filePreviewName = file.name || '文件预览'
        this.filePreviewContent = textContent
        this.showFilePreview = true
        return
      }

      // Office 文档（docx, pptx, xlsx）：提示下载
      if (['.docx', '.pptx', '.xlsx'].includes(suffix)) {
        alert('Office 文档暂不支持在线预览，请下载后查看。\n文件名: ' + file.name)
        return
      }

      // 其他文件：使用 iframe 预览
      const otherPreviewUrl = file.preview_url || file.iframe_url
      if (otherPreviewUrl) {
        this.webPreviewUrl = otherPreviewUrl
        this.showWebPreview = true
      }
    },
    async restoreCheckpoint(checkpointId) {
      this.restoreTargetId = checkpointId
      this.showRestoreConfirm = true
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

        // 3. 将用户消息添加回 messages（backtrack 后的对话不包含当前输入）
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

        // 4. 添加 AI 消息占位
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
        this.$refs.messageList?.scrollToBottom(true)

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
              } else if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_name') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                toolCalls.push({ name: data.content.name, args: data.content.args, id: data.id, result: null })
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  toolCalls,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_result') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                const idx = toolCalls.findIndex(tc => tc.id === data.id)
                if (idx !== -1) toolCalls[idx] = { ...toolCalls[idx], result: data.content }
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  toolCalls,
                  responseTime: this.currentResponseTime
                }
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

                // 恢复标题
                if (currentTitle && currentTitle !== '新对话' && requestSessionId) {
                  await this.updateConversationTitle({ sessionId: requestSessionId, title: currentTitle })
                }

                // 4. 最后刷新会话
                await this.refreshCurrentConversation()
              } else if (data.type === 'interrupt') {
              this.stopResponseTimer()
              const reason = data.reason || '用户主动中断'
              this.messages[aiMessageIndex] = { ...this.messages[aiMessageIndex], streaming: false, interruptReason: reason }
              this.isInterrupted = true
              this.isInterruptedSessionId = data.session_id || requestSessionId || this._pendingInterruptSessionId
              this.interruptReason = reason
            }
            } catch (e) {
              console.error('解析消息失败:', e)
            }
          }

          this.$refs.messageList?.scrollToBottom(true)
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
          // 后端返回完整会话列表，前端进行冷加载处理
          this.conversations = data
        }
      } catch (error) {
        console.error('加载对话列表失败:', error)
      }
    },
    async loadMoreConversations() {
      // 冷加载：每次滚动到底部时增加显示数量
      this.displayCount += 10
    },
    createNewChat() {
      // 清理正在加载的状态
      this.cleanupLoadingState()
      // 清理输入框和文件
      this.$refs.messageInput?.clearInput()

      this.currentSessionId = null
      this.messages = []
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

      // 如果有正在思考的 AI 消息（正在流式输出），移除它
      if (this.isLoading && this.messages.length > 0) {
        const lastMsg = this.messages[this.messages.length - 1]
        if (lastMsg?.role === 'ai' && lastMsg?.streaming) {
          this.messages.pop()
        }
      }

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

      // 清理之前正在加载的状态
      this.cleanupLoadingState()
      // 清理输入框和文件
      this.$refs.messageInput?.clearInput()

      try {
        const response = await fetch(`/chat/${sessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()
          this.currentSessionId = sessionId

          if (this.$route.params.sessionId !== sessionId) {
            this.$router.push(`/${sessionId}`)
          }

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
        }
      } catch (error) {
        console.error('加载对话失败:', error)
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
      } catch (error) {
        console.error('刷新消息失败:', error)
      }
    },
    // 右键刷新指定会话
    async refreshConversation(sessionId) {
      try {
        const response = await fetch(`/chat/${sessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()
          if (sessionId === this.currentSessionId) {
            // 如果是当前会话，静默刷新
            this.$refs.messageList?.suppressNextScroll()
            this.messages = this.processConversationMessages(conversation.messages)
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
      this.deleteTargetId = sessionId
      this.showDeleteConfirm = true
    },
    async confirmDelete() {
      if (!this.deleteTargetId) return

      // 清理正在加载的状态
      this.cleanupLoadingState()

      try {
        const response = await fetch(`/chat/${this.deleteTargetId}/clear`, {
          method: 'DELETE'
        })
        if (response.ok) {
          this.conversations = this.conversations.filter(c => c.session_id !== this.deleteTargetId)
          if (this.currentSessionId === this.deleteTargetId) {
            this.createNewChat()
          }
        }
      } catch (error) {
        console.error('删除对话失败:', error)
      } finally {
        this.showDeleteConfirm = false
        this.deleteTargetId = null
      }
    },
    cancelDelete() {
      this.showDeleteConfirm = false
      this.deleteTargetId = null
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

      this.$refs.messageList?.scrollToBottom(true)

      this.responseStartTime = Date.now()
      this.currentResponseTime = 0

      // 保存发起请求时的会话 ID，用于跟踪请求属于哪个会话
      const requestSessionId = this.currentSessionId

      try {
        const requestBody = {
          message: message,
          session_id: requestSessionId || '',
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

              // 检查用户是否已切换会话
              const sessionChanged = this.currentSessionId !== requestSessionId

              if (sessionChanged) {
                // 会话已切换，继续消费流但不更新本地消息
                if (data.type === 'done') {
                  this.stopResponseTimer()
                  // 刷新原会话（不更新 this.messages）
                  if (requestSessionId) {
                    await this.refreshSession(requestSessionId)
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
              } else if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_name') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                toolCalls.push({ name: data.content.name, args: data.content.args, id: data.id, result: null })
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  toolCalls,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_result') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                const idx = toolCalls.findIndex(tc => tc.id === data.id)
                if (idx !== -1) toolCalls[idx] = { ...toolCalls[idx], result: data.content }
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  toolCalls,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'done') {
                this.stopResponseTimer()
                const responseTime = this.currentResponseTime

                // 检查用户是否已切换到其他会话
                const sessionChanged = this.currentSessionId !== requestSessionId

                if (sessionChanged) {
                  console.log('会话已切换，跳过本地消息更新，请求归属会话:', requestSessionId)
                }

                this.messages[aiMessageIndex] = {
                  role: 'ai',
                  content: data.full_response,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: responseTime,
                  checkpointId: data.checkpoint_id || null
                }

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
                } else if (!sessionChanged && this.currentSessionId) {
                  // 会话未切换，正常更新
                  await this.updateTitleAndRefresh(this.currentSessionId, message)
                } else if (sessionChanged && requestSessionId) {
                  // 会话已切换，刷新原会话但不更新当前显示的消息
                  console.log('刷新请求归属的会话:', requestSessionId)
                  // 静默刷新原会话（不更新 this.messages）
                  await this.refreshSession(requestSessionId)
                }
              } else if (data.type === 'error') {
                console.error('AI响应错误:', data.error)
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: `抱歉，出现了一些问题：${data.error}`,
                  streaming: false
                }
              } else if (data.type === 'interrupt') {
                this.stopResponseTimer()
                const reason = data.reason || '用户主动中断'
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  streaming: false,
                  interruptReason: reason
                }
                this.isInterrupted = true
                this.isInterruptedSessionId = data.session_id || this.currentSessionId || this._pendingInterruptSessionId
                this.interruptReason = reason
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
              // 会话已切换，刷新原会话
              if (data.type === 'done' && requestSessionId) {
                await this.refreshSession(requestSessionId)
              }
            } else {
              if (data.type === 'reasoning') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  reasoning: this.messages[aiMessageIndex].reasoning + data.content,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_name') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                toolCalls.push({ name: data.content.name, args: data.content.args, id: data.id, result: null })
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  toolCalls,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_result') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                const idx = toolCalls.findIndex(tc => tc.id === data.id)
                if (idx !== -1) toolCalls[idx] = { ...toolCalls[idx], result: data.content }
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  toolCalls,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'content') {
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  content: this.messages[aiMessageIndex].content + data.content,
                  thinkingDone: true
                }
              } else if (data.type === 'done') {
                this.stopResponseTimer()
                const responseTime = this.currentResponseTime

                this.messages[aiMessageIndex] = {
                  role: 'ai',
                  content: data.full_response,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: responseTime,
                  checkpointId: data.checkpoint_id || null
                }

                if (!this.currentSessionId && data.session_id) {
                  this.currentSessionId = data.session_id

                  if (this.$route.params.sessionId !== data.session_id) {
                    this.$router.push(`/${data.session_id}`)
                  }
                }

                if (this.currentSessionId) {
                  await this.updateTitleAndRefresh(this.currentSessionId, message)
                }
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

      // 2. 获取最新对话内容（含更新后的标题 + 历史记录）
      try {
        const response = await fetch(`/chat/${sessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()
          // 静默刷新消息，不触发自动滚动
          this.$refs.messageList?.suppressNextScroll()
          this.messages = this.processConversationMessages(conversation.messages)
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

      try {
        const response = await fetch(`/chat/${this.currentSessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()

          this.$refs.messageList?.suppressNextScroll()
          this.messages = this.processConversationMessages(conversation.messages)

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
          // 实时更新当前 AI 消息的响应时间
          if (this.currentAiMessageIndex !== null && this.messages[this.currentAiMessageIndex]) {
            this.messages[this.currentAiMessageIndex] = {
              ...this.messages[this.currentAiMessageIndex],
              responseTime: this.currentResponseTime
            }
          }
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
  --user-msg-bg: #ececec;
  --user-msg-border: #e0e0e0;
  --ai-msg-bg: transparent;
  --button-bg: #10a37f;
  --button-hover: #0d8c6d;
  --sidebar-bg: #f7f7f8;
  --header-bg: #ffffff;
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
</style>
