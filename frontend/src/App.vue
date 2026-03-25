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
          @toggle-theme="toggleTheme"
        />

        <MessageList
          ref="messageList"
          :messages="messages"
          :is-loading="isLoading"
        />

        <MessageInput
          :is-loading="isLoading"
          @send="sendMessage"
        />
      </main>
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
  </div>
</template>

<script>
import Sidebar from './components/Sidebar.vue'
import ChatHeader from './components/ChatHeader.vue'
import MessageList from './components/MessageList.vue'
import MessageInput from './components/MessageInput.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'

export default {
  name: 'App',
  components: {
    Sidebar,
    ChatHeader,
    MessageList,
    MessageInput,
    ConfirmDialog
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
    async loadConversations() {
      try {
        const response = await fetch('/chat/conversations?limit=50')
        if (response.ok) {
          this.conversations = await response.json()
          // // 后端已经按updated_at排序，但前端再次确保
          // this.conversations = conversations.sort((a, b) => {
          //   return new Date(b.updated_at) - new Date(a.updated_at)
          // })
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
      // data 可以是字符串（向后兼容）或对象 { message, files }
      const message = typeof data === 'string' ? data : data.message
      const files = typeof data === 'object' ? data.files : []

      // 为用户消息添加文件附件信息
      const userMessage = {
        role: 'user',
        content: message
      }

      // 如果有文件，添加文件信息用于显示
      if (files && files.length > 0) {
        userMessage.files = files.map(file => ({
          name: file.name,
          size: file.size,
          type: file.type,
          preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : null
        }))
      }

      this.messages.push(userMessage)

      this.isLoading = true
      const isNewConversation = !this.currentSessionId

      // 发送消息时重置打断状态，强制滚到底部
      this.$refs.messageList?.scrollToBottom(true)

      // 开始响应计时
      this.responseStartTime = Date.now()
      this.currentResponseTime = 0

      try {
        // 构建 FormData
        const formData = new FormData()

        // 添加 chatRequest 字段（JSON 字符串）
        formData.append('chatRequest', JSON.stringify({
          message: message,
          session_id: this.currentSessionId || ''
        }))

        // 添加文件（如果有）
        if (files && files.length > 0) {
          files.forEach(file => {
            formData.append('files', file)
          })
        }

        const response = await fetch('/chat/', {
          method: 'POST',
          // 不设置 Content-Type，让浏览器自动设置 multipart/form-data 和 boundary
          body: formData
        })

        if (!response.ok) {
          throw new Error(`请求失败: ${response.status} ${response.statusText}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()

        // 初始化 AI 消息并添加到消息列表
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

        // 开始响应计时，需要在消息添加后启动
        this.startResponseTimer()

        let buffer = '' // 用于处理跨块的不完整 JSON

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          // 解码当前块并添加到缓冲区
          buffer += decoder.decode(value, { stream: true })

          // 按 \n\n 分割 SSE 消息
          const parts = buffer.split('\n\n')

          // 保留最后一个可能不完整的部分
          buffer = parts.pop() || ''

          for (const part of parts) {
            const line = part.trim()
            if (!line) continue

            try {
              const data = JSON.parse(line)

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

                this.messages[aiMessageIndex] = {
                  role: 'ai',
                  content: data.full_response,
                  reasoning: this.messages[aiMessageIndex].reasoning,
                  toolCalls: this.messages[aiMessageIndex].toolCalls,
                  thinkingDone: true,
                  streaming: false,
                  responseTime: responseTime
                }

                // 处理新会话 ID
                if (!this.currentSessionId && data.session_id) {
                  this.currentSessionId = data.session_id

                  if (this.$route.params.sessionId !== data.session_id) {
                    this.$router.push(`/${data.session_id}`)
                  }

                  if (isNewConversation) {
                    this.autoGenerateTitle(data.session_id, message)
                  }
                }

                if (this.currentSessionId) {
                  this.updateConversationTime()
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

        // 处理缓冲区中剩余的数据
        if (buffer.trim()) {
          try {
            const data = JSON.parse(buffer.trim())
            if (data.type === 'content') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                content: this.messages[aiMessageIndex].content + data.content,
                thinkingDone: true
              }
            } else if (data.type === 'done') {
              this.messages[aiMessageIndex] = {
                ...this.messages[aiMessageIndex],
                content: data.full_response,
                thinkingDone: true,
                streaming: false
              }
            }
          } catch (e) {
            console.error('解析缓冲区剩余数据失败:', e)
          }
        }
      } catch (error) {
        console.error('发送消息失败:', error)

        // 创建新的错误消息
        this.messages.push({
          role: 'ai',
          content: '抱歉，发送消息时出现错误，请稍后重试。'
        })
      } finally {
        this.isLoading = false
        this.stopResponseTimer()
      }
    },
    async autoGenerateTitle(sessionId, message) {
      // 取用户消息前6个字作为标题
      const title = message.substring(0, 6) + (message.length > 6 ? '...' : '')

      try {
        await fetch(`/chat/${sessionId}/title`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ title })
        })

        // 添加新对话到列表
        this.conversations.unshift({
          session_id: sessionId,
          title: title,
          updated_at: new Date().toISOString()
        })
      } catch (error) {
        console.error('自动生成标题失败:', error)
      }
    },
    async refreshCurrentConversation() {
      if (!this.currentSessionId) return

      try {
        const response = await fetch(`/chat/${this.currentSessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()

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
    async updateConversationTime() {
      if (!this.currentSessionId) return

      try {
        const response = await fetch(`/chat/${this.currentSessionId}/conversation`)
        if (response.ok) {
          const conversation = await response.json()

          // 只更新侧边栏中的对话时间
          const conv = this.conversations.find(c => c.session_id === this.currentSessionId)
          if (conv && conversation.updated_at) {
            conv.updated_at = conversation.updated_at
          }
        }
      } catch (error) {
        console.error('更新对话时间失败:', error)
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
                name: file.filename,
                type: file.content_type,
                preview: null,
                content: null
              }
              if (file.content_type && file.content_type.startsWith('image/')) {
                fileInfo.preview = file.base64_data
              } else if (file.content_type && (
                file.content_type.startsWith('text/') ||
                file.content_type === 'application/json' ||
                file.content_type === 'text/csv' ||
                file.content_type === 'text/xml'
              )) {
                try {
                  const base64Content = file.base64_data.split(',')[1]
                  fileInfo.content = atob(base64Content)
                } catch (e) {
                  console.error('解码文本文件失败:', e)
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
            streaming: false
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
  --bg-secondary: #f7f7f8;
  --bg-hover: #ececf1;
  --text-primary: #1a1a1a;
  --text-secondary: #6e6e80;
  --border-color: #e5e5e5;
  --user-msg-bg: #f7f7f8;
  --ai-msg-bg: #ffffff;
  --button-bg: #10a37f;
  --button-hover: #0d8c6d;
  --sidebar-bg: #ffffff;
  --header-bg: #ffffff;
}

.dark-theme {
  --bg-primary: #1a1a1a;
  --bg-secondary: #2d2d2d;
  --bg-hover: #3d3d3d;
  --text-primary: #ececec;
  --text-secondary: #b4b4b4;
  --border-color: #3d3d3d;
  --user-msg-bg: #2d2d2d;
  --ai-msg-bg: #1a1a1a;
  --button-bg: #10a37f;
  --button-hover: #0d8c6d;
  --sidebar-bg: #0a0a0a;
  --header-bg: #2d2d2d;
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
  display: flex;
  flex-direction: column;
  background-color: var(--bg-primary);
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
