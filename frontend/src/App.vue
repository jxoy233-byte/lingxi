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
      deleteTargetId: null
    }
  },
  mounted() {
    const savedTheme = localStorage.getItem('chatme-theme')
    if (savedTheme) {
      this.isDarkTheme = savedTheme === 'dark'
    }

    this.loadConversations()
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
    },
    async loadConversation(sessionId) {
      try {
        const response = await fetch(`/chat/${sessionId}`)
        if (response.ok) {
          const conversation = await response.json()
          this.currentSessionId = sessionId
          this.messages = conversation.messages
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
    async sendMessage(message) {
      this.messages.push({
        role: 'user',
        content: message
      })

      this.isLoading = true
      const isNewConversation = !this.currentSessionId

      try {
        const response = await fetch('/chat/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            message: message,
            session_id: this.currentSessionId || ''
          })
        })

        if (!response.ok) {
          throw new Error('请求失败')
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let aiMessage = {
          role: 'ai',
          content: ''
        }
        this.messages.push(aiMessage)

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value, { stream: true })
          const lines = chunk.split('\n\n').filter(line => line.trim())

          for (const line of lines) {
            if (!line.trim()) continue

            try {
              const data = JSON.parse(line)

              if (data.type === 'content') {
                aiMessage.content += data.content
              } else if (data.type === 'done') {
                aiMessage.content = data.full_response

                if (!this.currentSessionId && data.session_id) {
                  this.currentSessionId = data.session_id

                  // 新对话自动生成标题（前5个字）
                  if (isNewConversation) {
                    this.autoGenerateTitle(data.session_id, message)
                  }
                }

                this.loadConversations()
              } else if (data.type === 'error') {
                console.error('AI响应错误:', data.error)
                aiMessage.content = '抱歉，出现了一些问题：' + data.error
              }
            } catch (e) {
              console.error('解析响应失败:', e, line)
            }
          }
        }
      } catch (error) {
        console.error('发送消息失败:', error)
        this.messages.push({
          role: 'ai',
          content: '抱歉，发送消息时出现错误，请稍后重试。'
        })
      } finally {
        this.isLoading = false
      }
    },
    async autoGenerateTitle(sessionId, message) {
      // 取用户消息前5个字作为标题
      const title = message.substring(0, 5) + (message.length > 5 ? '...' : '')

      try {
        await fetch(`/chat/${sessionId}/title`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ title })
        })
      } catch (error) {
        console.error('自动生成标题失败:', error)
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
