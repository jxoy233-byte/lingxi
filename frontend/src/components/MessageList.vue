<template>
  <div class="messages-container" ref="messagesContainer">
    <div class="messages-column">
      <div v-if="messages.length === 0" class="welcome-message">
        <h2>你好！我是 ChatMe 智能助手</h2>
        <p>有什么我可以帮助你的吗？</p>
      </div>

      <MessageItem
        v-for="(msg, index) in flattenedMessages"
        :key="msg._key || index"
        :message="msg"
        :is-first-ai-message="isFirstAiMessage(index)"
        :is-latest-ai-message="index === latestAiMessageIndex"
        :is-interrupted="isInterrupted"
        :is-interrupted-session-id="isInterruptedSessionId"
        :current-session-id="currentSessionId"
        :has-received-init="hasReceivedInit"
        @restore="$emit('restore', $event)"
        @restream="$emit('restream', $event)"
        @open-link="$emit('open-link', $event)"
        @preview-file="$emit('preview-file', $event)"
        @interrupt="$emit('interrupt', $event)"
        @resume="$emit('resume', $event)"
      />

      <div v-if="isLoading" class="loading-message" :class="{ 'interrupted': isInterrupted && isInterruptedSessionId === currentSessionId }">
        <div class="typing-indicator" :class="{ 'interrupted': isInterrupted && isInterruptedSessionId === currentSessionId }">
          <span></span><span></span><span></span>
        </div>
        <div class="loading-text">{{ isInterrupted && isInterruptedSessionId === currentSessionId ? '思考已中断' : 'AI酱 正在思考中...' }}</div>
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
    },
    isInterrupted: {
      type: Boolean,
      default: false
    },
    isInterruptedSessionId: {
      type: String,
      default: null
    },
    currentSessionId: {
      type: String,
      default: null
    },
    hasReceivedInit: {
      type: Boolean,
      default: false
    }
  },
  emits: ['restore', 'restream', 'open-link', 'preview-file', 'interrupt', 'resume'],
  data() {
    return {
      userInterrupted: false,   // 用户主动介入，打断自动滚动
      isAutoScrolling: false,   // 当前是否在自动滚动中
      rafId: null               // requestAnimationFrame id
    }
  },
  computed: {
    // 将消息列表直接传递给 MessageItem，不拆分
    // MessageItem 内部会处理文件消息和文本消息的显示
    flattenedMessages() {
      const result = []
      let keyIndex = 0

      for (const msg of this.messages) {
        result.push({
          ...msg,
          _key: `msg_${keyIndex++}`
        })
      }

      return result
    },
    // 最新一轮对话的 AI 消息索引（最后一个 AI 消息）
    latestAiMessageIndex() {
      let lastAiIndex = -1
      for (let i = 0; i < this.messages.length; i++) {
        if (this.messages[i].role === 'ai') {
          lastAiIndex = i
        }
      }
      return lastAiIndex
    }
  },
  methods: {
    // 判断指定索引的AI消息是否是该会话的第一轮AI消息
    isFirstAiMessage(index) {
      // 使用 flattenedMessages 来判断
      const flattened = this.flattenedMessages
      // 向前遍历找到第一个AI消息
      for (let i = 0; i < index; i++) {
        if (flattened[i] && flattened[i].role === 'ai') {
          return false
        }
      }
      return true
    },

    // 平滑滚动到底部，duration 根据距离动态计算
    scrollToBottom(force = false) {
      const container = this.$refs.messagesContainer
      if (!container) return
      if (force) this.userInterrupted = false
      if (this.userInterrupted) return

      this.$nextTick(() => {
        const distance = container.scrollHeight - container.scrollTop - container.clientHeight
        if (distance <= 0) return

        // 距离越长速度越快：基础 300ms，每 500px 多加 80ms，上限 800ms
        const duration = Math.min(300 + Math.floor(distance / 500) * 80, 800)

        this.smoothScroll(container, container.scrollTop + distance, duration)
      })
    },

    // 静默刷新消息，不触发自动滚动
    suppressNextScroll() {
      this._suppressScroll = true
    },

    smoothScroll(container, targetTop, duration) {
      if (this.rafId) cancelAnimationFrame(this.rafId)

      const startTop = container.scrollTop
      const diff = targetTop - startTop
      const startTime = performance.now()

      this.isAutoScrolling = true

      const step = (now) => {
        if (this.userInterrupted) {
          this.isAutoScrolling = false
          return
        }
        const elapsed = now - startTime
        const progress = Math.min(elapsed / duration, 1)
        // easeOutCubic
        const ease = 1 - Math.pow(1 - progress, 3)
        container.scrollTop = startTop + diff * ease

        if (progress < 1) {
          this.rafId = requestAnimationFrame(step)
        } else {
          this.isAutoScrolling = false
        }
      }

      this.rafId = requestAnimationFrame(step)
    },

    // 用户主动滚动（wheel / touchstart）时打断自动滚动
    handleUserScroll() {
      if (this.isAutoScrolling) {
        this.userInterrupted = true
        if (this.rafId) {
          cancelAnimationFrame(this.rafId)
          this.rafId = null
        }
        this.isAutoScrolling = false
      }
    },

    // 用户滚回底部时恢复自动跟随
    handleScroll() {
      const container = this.$refs.messagesContainer
      if (!container) return
      const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50
      if (isAtBottom) {
        this.userInterrupted = false
      }
    }
  },
  watch: {
    messages: {
      handler() {
        if (this._suppressScroll) {
          this._suppressScroll = false
          return
        }
        if (!this.userInterrupted) {
          this.scrollToBottom()
        }
      },
      deep: true,
      immediate: false
    },
    isLoading(newVal) {
      if (newVal) {
        // 发送消息时重置打断状态，强制滚到底部
        this.scrollToBottom(true)
      }
    }
  },
  mounted() {
    const container = this.$refs.messagesContainer
    if (container) {
      container.addEventListener('scroll', this.handleScroll, { passive: true })
      container.addEventListener('wheel', this.handleUserScroll, { passive: true })
      container.addEventListener('touchstart', this.handleUserScroll, { passive: true })
    }
  },
  beforeUnmount() {
    const container = this.$refs.messagesContainer
    if (container) {
      container.removeEventListener('scroll', this.handleScroll)
      container.removeEventListener('wheel', this.handleUserScroll)
      container.removeEventListener('touchstart', this.handleUserScroll)
    }
    if (this.rafId) cancelAnimationFrame(this.rafId)
  }
}
</script>

<style scoped>
.messages-container {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.messages-column {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 16px 16px;
  min-width: 0;
}

.welcome-message {
  text-align: center;
  margin-top: 120px;
  color: var(--text-secondary);
}

.welcome-message h2 {
  font-size: 26px;
  margin-bottom: 12px;
  color: var(--text-primary);
  font-weight: 600;
}

.loading-message {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 0;
}

.typing-indicator span {
  width: 7px;
  height: 7px;
  background-color: var(--button-bg);
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
  opacity: 0.5;
}

.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30%            { opacity: 1;   transform: scale(1.2); }
}

/* 中断状态的红色样式 */
.loading-message.interrupted .typing-indicator span {
  background-color: #ef4444;
  animation: typing-interrupted 1.4s infinite ease-in-out;
}

.loading-message.interrupted .loading-text {
  color: #ef4444;
  animation: none;
}

@keyframes typing-interrupted {
  0%, 60%, 100% { opacity: 0.4; transform: scale(0.8); }
  30%            { opacity: 1;   transform: scale(1.2); }
}

.loading-text {
  font-size: 13px;
  color: var(--text-secondary);
  animation: pulse-text 2s ease-in-out infinite;
}

@keyframes pulse-text {
  0%, 100% { opacity: 0.6; }
  50%       { opacity: 1;   }
}
</style>
