<template>
  <div class="messages-container" ref="messagesContainer">
    <div v-if="messages.length === 0" class="welcome-message">
      <h2>你好！我是 ChatMe 智能助手</h2>
      <p>有什么我可以帮助你的吗？</p>
    </div>

    <MessageItem
      v-for="(msg, index) in messages"
      :key="index"
      :message="msg"
    />

  <div v-if="isLoading" class="message ai-message">
    <div class="message-content loading-content">
      <div class="typing-indicator">
        <span></span><span></span><span></span>
      </div>
      <div class="loading-text">AI酱 正在思考中...</div>
    </div>
  </div>

  </div>
</template>

<script>
import MessageItem from './MessageItem.vue'

export default {
  name: 'MessageList',
  components: {
    MessageItem
  },
  props: {
    messages: {
      type: Array,
      default: () => []
    },
    isLoading: {
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      isUserScrolling: false,
      scrollTimeout: null,
      scrollDebounceTimer: null
    }
  },
  methods: {
    scrollToBottom(smooth = false) {
      // 清除之前的防抖定时器
      if (this.scrollDebounceTimer) {
        clearTimeout(this.scrollDebounceTimer)
      }

      // 使用防抖，避免频繁滚动
      this.scrollDebounceTimer = setTimeout(() => {
        this.$nextTick(() => {
          const container = this.$refs.messagesContainer
          if (container) {
            container.scrollTo({
              top: container.scrollHeight,
              behavior: smooth ? 'smooth' : 'auto'
            })
          }
        })
      }, 10) // 10ms 防抖，既保证流畅又不会过于频繁
    },
    handleScroll() {
      // 检测用户是否手动滚动
      const container = this.$refs.messagesContainer
      if (container) {
        const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50
        this.isUserScrolling = !isAtBottom

        // 清除之前的定时器
        if (this.scrollTimeout) {
          clearTimeout(this.scrollTimeout)
        }

        // 如果用户滚动到底部,重置标志
        if (isAtBottom) {
          this.scrollTimeout = setTimeout(() => {
            this.isUserScrolling = false
          }, 100)
        }
      }
    }
  },
  watch: {
    messages: {
      handler(newMessages, oldMessages) {
        // 自动滚动到底部，除非用户手动向上滚动
        if (!this.isUserScrolling) {
          // 如果是新增消息或内容更新,使用平滑滚动
          const isNewMessage = newMessages.length > oldMessages?.length
          this.scrollToBottom(isNewMessage)
        }
      },
      deep: true,
      immediate: false
    },
    isLoading(newVal) {
      // 加载状态变化时自动滚动
      if (newVal && !this.isUserScrolling) {
        this.scrollToBottom(true)
      }
    }
  },
  mounted() {
    // 添加滚动事件监听
    const container = this.$refs.messagesContainer
    if (container) {
      container.addEventListener('scroll', this.handleScroll)
    }
  },
  beforeUnmount() {
    // 清理事件监听和定时器
    const container = this.$refs.messagesContainer
    if (container) {
      container.removeEventListener('scroll', this.handleScroll)
    }
    if (this.scrollTimeout) {
      clearTimeout(this.scrollTimeout)
    }
    if (this.scrollDebounceTimer) {
      clearTimeout(this.scrollDebounceTimer)
    }
  }
}
</script>

<style scoped>
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  scroll-behavior: smooth;
}

.welcome-message {
  text-align: center;
  margin-top: 100px;
  color: var(--text-secondary);
}

.welcome-message h2 {
  font-size: 28px;
  margin-bottom: 12px;
  color: var(--text-primary);
}

.message {
  display: flex;
  margin-bottom: 24px;
  width: 100%;
}

.ai-message {
  justify-content: flex-start;
}

.message-content {
  max-width: 75%;
  padding: 12px 16px;
  border-radius: 12px;
}

.ai-message .message-content {
  background-color: var(--ai-msg-bg);
  border: 1px solid var(--border-color);
}

.loading-content {
  display: flex;
  align-items: center;
  gap: 12px;
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 0;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background-color: var(--button-bg);
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  30% {
    opacity: 1;
    transform: scale(1.2);
  }
}

.loading-text {
  font-size: 13px;
  color: var(--text-secondary);
  animation: pulse-text 2s ease-in-out infinite;
}

@keyframes pulse-text {
  0%, 100% {
    opacity: 0.6;
  }
  50% {
    opacity: 1;
  }
}
</style>
