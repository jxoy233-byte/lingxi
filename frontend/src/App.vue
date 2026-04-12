<template>
  <div :class="['app-container', { 'dark-theme': isDarkTheme }]">
    <div class="main-layout">
      <Sidebar
        :collapsed="sidebarCollapsed"
        :conversations="conversations"
        :active-session-id="currentSessionId"
        @toggle="toggleSidebar"
        @new-chat="createNewChat"
        @select-conversation="loadConversation"
        @delete-conversation="deleteConversation"
        @update-title="updateConversationTitle"
      />

      <main class="chat-area">
        <ChatHeader
          :is-dark-theme="isDarkTheme"
          :has-session="!!currentSessionId"
          @toggle-theme="toggleTheme"
          @toggle-checkpoints="toggleCheckpoints"
        />

        <MessageList
          ref="messageList"
          :messages="messages"
          :is-loading="isLoading"
          @restore="restoreCheckpoint"
          @open-link="openWebPreview"
          @preview-file="previewFile"
        />

        <MessageInput
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

export default {
  name: 'App',
  components: {
    Sidebar,
    ChatHeader,
    MessageList,
    MessageInput,
    ConfirmDialog,
    CheckpointPanel,
    WebPreviewPanel
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
      responseStartTime: null,
      responseTimerInterval: null,
      currentResponseTime: 0,
      currentAiMessageIndex: null
    }
  },
  mounted() {
    const savedTheme = localStorage.getItem('chatme-theme')
    if (savedTheme) {
      this.isDarkTheme = savedTheme === 'dark'
    }

    this.loadConversations()

    // 从 URL 加载会话
    const sessionId = this.$route.params.sessionId
    if (sessionId) {
      this.loadConversation(sessionId)
    }
  },
  watch: {
    '$route.params.sessionId'(newSessionId) {
      // 监听 URL 变化
      if (newSessionId) {
        this.loadConversation(newSessionId)
      } else {
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
    toggleCheckpoints() {
      this.showCheckpoints = !this.showCheckpoints
    },
    openWebPreview(url) {
      this.webPreviewUrl = url
      this.showWebPreview = true
    },
    previewFile(file) {
      // 根据文件类型决定预览方式
      const fileType = (file.file_type || file.type || '').toUpperCase()
      // 优先使用 iframe_url，其次是 preview_url，最后是 iframe_url（通用）
      const previewUrl = file.iframe_url || file.preview_url || ''
      const suffix = (file.suffix || (file.name ? '.' + file.name.split('.').pop().toLowerCase() : '')).toLowerCase()

      // 图片文件：直接使用 preview_url（base64 data URL）
      if (fileType === 'IMAGE' || (file.type && file.type.startsWith('image/'))) {
        if (previewUrl) {
          this.webPreviewUrl = previewUrl
          this.showWebPreview = true
        }
        return
      }

      // PDF 文件：使用 iframe 预览
      if (suffix === '.pdf' || fileType === 'DOCUMENT') {
        if (previewUrl) {
          this.webPreviewUrl = previewUrl
          this.showWebPreview = true
        }
        return
      }

      // Office 文档（docx, pptx, xlsx）：提示下载
      if (['.docx', '.pptx', '.xlsx'].includes(suffix)) {
        alert('Office 文档暂不支持在线预览，请下载后查看。\n文件名: ' + file.name)
        return
      }

      // 文本文件：使用 iframe 或 content 显示
      if (fileType === 'TEXT' || (file.type && (file.type.startsWith('text/') || file.type === 'application/json'))) {
        if (previewUrl) {
          this.webPreviewUrl = previewUrl
          this.showWebPreview = true
        } else if (file.content) {
          // 如果有文本内容，创建一个 data URL
          const dataUrl = 'data:text/plain;charset=utf-8,' + encodeURIComponent(file.content)
          this.webPreviewUrl = dataUrl
          this.showWebPreview = true
        }
        return
      }

      // 其他文件：尝试使用 preview_url
      if (previewUrl) {
        this.webPreviewUrl = previewUrl
        this.showWebPreview = true
      }
    },
    async restoreCheckpoint(checkpointId) {
      this.restoreTargetId = checkpointId
      this.showRestoreConfirm = true
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
          await this.loadConversation(this.currentSessionId)
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
        const response = await fetch('/chat/conversations?limit=50')
        if (response.ok) {
          this.conversations = await response.json()
        }
      } catch (error) {
        console.error('加载对话列表失败:', error)
      }
    },
    createNewChat() {
      this.currentSessionId = null
      this.messages = []
      // 更新 URL 到根路径
      if (this.$route.path !== '/') {
        this.$router.push('/')
      }
    },
    async loadConversation(sessionId) {
      try {
        const response = await fetch(`/chat/${sessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()
          this.currentSessionId = sessionId

          if (this.$route.params.sessionId !== sessionId) {
            this.$router.push(`/${sessionId}`)
          }

          this.messages = this.processConversationMessages(conversation.messages)
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
        }
      } catch (error) {
        console.error('刷新消息失败:', error)
      }
    },
    async deleteConversation(sessionId) {
      this.deleteTargetId = sessionId
      this.showDeleteConfirm = true
    },
    async confirmDelete() {
      if (!this.deleteTargetId) return

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

      const userMessage = {
        role: 'user',
        content: message
      }

      if (files && files.length > 0) {
        userMessage.files = files.map(file => {
          // 优先使用后端返回的 preview_url（包含 base64 编码的 data URL）
          const previewUrl = file.preview || file.iframe_url || file.preview_url

          const fileInfo = {
            name: file.name,
            size: file.size,
            type: file.type,
            preview: previewUrl,  // 直接使用后端返回的 preview_url
            iframe_url: file.iframe_url || previewUrl,
            fileId: file.fileId,
            file_type: file.file_type || null,
            preview_method: file.preview_method || null,
            preview_hint: file.preview_hint || null,
            size_human: file.size_human || null,
            suffix: file.suffix || null,
            is_previewable: file.is_previewable !== undefined ? file.is_previewable : true
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

          // 文本文件：保存 content 用于预览
          if (file.type && (file.type.startsWith('text/') || file.type === 'application/json')) {
            if (file.content) {
              fileInfo.content = file.content
            }
          }

          return fileInfo
        })
      }

      this.messages.push(userMessage)

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

              if (data.type === 'content') {
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
                toolCalls.push({ name: data.content.name, args: data.content.args, result: null })
                this.messages[aiMessageIndex] = {
                  ...this.messages[aiMessageIndex],
                  toolCalls,
                  responseTime: this.currentResponseTime
                }
              } else if (data.type === 'tool_call_result') {
                const toolCalls = [...(this.messages[aiMessageIndex].toolCalls || [])]
                if (toolCalls.length > 0) {
                  toolCalls[toolCalls.length - 1] = { ...toolCalls[toolCalls.length - 1], result: data.content }
                }
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
              if (data.type === 'content') {
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
          if (msg.files && msg.files.length > 0) {
            processedMsg.files = msg.files.map(file => {
              const fileInfo = {
                name: file.file_name || file.filename,
                type: file.file_type || file.content_type,
                preview: file.preview_url || null,
                content: null,
                fileId: file.file_id || null,
                iframe_url: file.iframe_url || null,
                preview_method: file.preview_method || 'download',
                is_previewable: file.is_previewable !== undefined ? file.is_previewable : true,
                preview_hint: file.preview_hint || '不支持在线预览，请下载后查看',
                size: file.file_size || 0,
                size_human: file.file_size_human || ''
              }

              // 处理预览逻辑
              if (fileInfo.preview_method === 'iframe' && fileInfo.preview) {
                if (file.file_type === 'IMAGE' || (file.content_type && file.content_type.startsWith('image/'))) {
                  // 图片：确保 preview 是有效的 data URL
                  if (file.preview_url && file.preview_url.startsWith('data:')) {
                    fileInfo.preview = file.preview_url
                  } else if (file.base64_data) {
                    fileInfo.preview = `data:${file.content_type || 'image/png'};base64,${file.base64_data}`
                  }
                } else if (file.file_type === 'TEXT' || (file.content_type && (
                  file.content_type.startsWith('text/') ||
                  file.content_type === 'application/json' ||
                  file.content_type === 'text/csv' ||
                  file.content_type === 'text/xml'
                ))) {
                  // 文本：content 字段用于直接显示文本内容
                  // 如果 preview_url 是 data URL，提取实际文本内容
                  if (file.preview_url && file.preview_url.startsWith('data:')) {
                    try {
                      const base64Match = file.preview_url.match(/^data:[^;]+;base64,(.+)$/)
                      if (base64Match) {
                        fileInfo.content = atob(base64Match[1])
                      } else {
                        fileInfo.content = file.preview_url
                      }
                    } catch (e) {
                      fileInfo.content = file.preview_url
                    }
                  } else {
                    fileInfo.content = file.preview_url
                  }
                }
              }

              // 文档文件（DOCUMENT）的 iframe_office 方法处理
              if (fileInfo.preview_method === 'iframe_office') {
                // iframe_office 使用 iframe_url 作为预览源
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
            checkpointId: null  // 添加 checkpoint_id 字段
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
              // 提取 checkpoint_id
              if (aiMsg.additional_kwargs?.checkpoint_id) {
                aiTurn.checkpointId = aiMsg.additional_kwargs.checkpoint_id
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
                // 2. tool_calls 放入 toolCalls 队列等待 ToolMessage 填入结果（对应流式的 tool_call_name 事件）
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
}

.checkpoint-overlay {
  position: fixed;
  inset: 0;
  z-index: 99;
}

.web-preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 99;
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
