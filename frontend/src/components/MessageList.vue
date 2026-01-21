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
    <div class="message-avatar">🤖</div>
    <div class="message-content">
      <div class="typing-indicator">
        <span></span><span></span><span></span>
      </div>
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
  methods: {
    scrollToBottom() {
      this.$nextTick(() => {
        const container = this.$refs.messagesContainer
        if (container) {
          container.scrollTop = container.scrollHeight
        }
      })
    }
  },
  watch: {
    messages: {
      handler() {
        this.scrollToBottom()
      },
      deep: true
    },
    isLoading() {
      this.scrollToBottom()
    }
  }
}
</script>

<style scoped>
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
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
  gap: 16px;
  margin-bottom: 24px;
  width: 100%;
}

.ai-message {
  justify-content: flex-start;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.message-content {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 12px;
}

.ai-message .message-content {
  background-color: var(--ai-msg-bg);
  border: 1px solid var(--border-color);
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 0;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background-color: var(--text-secondary);
  border-radius: 50%;
  animation: typing 1.4s infinite;
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
  }
  30% {
    opacity: 1;
  }
}
</style>
