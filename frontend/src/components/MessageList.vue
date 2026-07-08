<template>
  <div class="messages-container" ref="messagesContainer">
    <div class="messages-column">
      <div v-if="messages.length === 0" class="welcome-message">
        <h2>你好！我是灵析——数据分析智能助手</h2>
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
        :pending-interrupt-session-id="pendingInterruptSessionId"
        @restore="$emit('restore', $event)"
        @restream="(...args) => $emit('restream', ...args)"
        @open-link="$emit('open-link', $event)"
        @preview-file="$emit('preview-file', $event)"
        @interrupt="$emit('interrupt', $event)"
        @resume="$emit('resume', $event)"
        @quote="$emit('quote', $event)"
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
    },
    pendingInterruptSessionId: {
      type: String,
      default: null
    }
  },
  emits: ['restore', 'restream', 'open-link', 'preview-file', 'interrupt', 'resume', 'quote'],
  data() {
    return {
      isAutoScrolling: false,   // 当前是否在自动滚动中
      rafId: null,              // requestAnimationFrame id
      // 内容更新前用户是否处于底部（beforeUpdate 钩子捕获，用于跨过大块内容更新）
      _userAtBottomBeforeUpdate: true
    }
  },
  computed: {
    // 将消息列表直接传递给 MessageItem，不拆分
    // MessageItem 内部会处理文件消息和文本消息的显示
    flattenedMessages() {
      const result = []
      let keyIndex = 0

      for (const msg of this.messages) {
        result.push(msg)
        keyIndex++
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

    // 用户是否在底部（50px 容差）
    isAtBottom() {
      const c = this.$refs.messagesContainer
      if (!c) return true
      return c.scrollHeight - c.scrollTop - c.clientHeight < 50
    },

    // 滚动到底部
    // force: 强制无视 isAtBottom()，用于首屏加载等场景
    scrollToBottom({ force = false } = {}) {
      const container = this.$refs.messagesContainer
      if (!container) return

      // stick-to-bottom：用户不在底部就不跟随（除非强制）
      if (!force && !this.isAtBottom()) return

      this.$nextTick(() => {
        const distance = container.scrollHeight - container.scrollTop - container.clientHeight
        if (distance <= 0) return

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
        // 用户已不在底部 → 中断动画（stick-to-bottom）
        if (!this.isAtBottom()) {
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

    // 用户主动滚动（wheel / touchstart / scroll）时打断自动滚动
    // 不再维护 userInterrupted 锁；由 isAtBottom() 在 scrollToBottom 里持续探测
    handleUserScroll() {
      // 跳过两种情况：
      // 1. 自动滚动自身产生的 scroll 事件（否则 smoothScroll 会被自己打断）
      // 2. 流式期间 + 用户仍在底部 → 不打断（auto-follow 优先于微动）
      if (this.isAutoScrolling && this.isAtBottom()) return
      // 取消正在进行的平滑动画
      if (this.rafId) {
        cancelAnimationFrame(this.rafId)
        this.rafId = null
      }
      this.isAutoScrolling = false
    },
  },
  watch: {
    messages: {
      handler() {
        if (this._suppressScroll) {
          this._suppressScroll = false
          return
        }
        // 内容增加前用户处于底部 → 强制跟随（避免工具输出等大块内容撑高 scrollHeight 后 50px 容差失效）
        if (this._userAtBottomBeforeUpdate) {
          this.scrollToBottom({ force: true })
        } else {
          this.scrollToBottom()
        }
      },
      deep: true,
      immediate: false
    },
    isLoading(newVal) {
      if (newVal) {
        // 发送消息时不强制到底，沿用 isAtBottom() 判定
        this.scrollToBottom()
      }
    }
  },
  beforeUpdate() {
    // 在 Vue 把新内容 patch 到 DOM 之前，捕获用户是否处于底部。
    // 这样 watcher 触发时（即 DOM 已更新，scrollHeight 已被新内容撑高），
    // 仍能根据「更新前的状态」决定是否强制跟随——避免工具输出/大段文本一次性
    // 增加 scrollHeight 导致 isAtBottom() 因新距离 > 50px 返回 false 而失跟。
    this._userAtBottomBeforeUpdate = this.isAtBottom()
  },
  mounted() {
    const container = this.$refs.messagesContainer
    if (container) {
      // 修：原本挂的是 this.handleScroll（未定义），键盘/滚动条拖动/触摸板的滚动都不会触发打断。
      // 改挂 handleUserScroll，覆盖所有滚动方式，wheel/touchstart 留作冗余。
      container.addEventListener('scroll', this.handleUserScroll, { passive: true })
      container.addEventListener('wheel', this.handleUserScroll, { passive: true })
      container.addEventListener('touchstart', this.handleUserScroll, { passive: true })

      // 监听容器尺寸变化（图片/异步内容加载会让容器变高），
      // 如果用户在底部，就直接跟到新底部，避免卡在"图片还没加载时算出的旧底部"。
      this.resizeObserver = new ResizeObserver(() => {
        if (!this.isAtBottom()) return
        const c = this.$refs.messagesContainer
        if (!c) return
        // 取消正在进行的平滑动画，直接跳到新底部
        if (this.rafId) {
          cancelAnimationFrame(this.rafId)
          this.rafId = null
        }
        this.isAutoScrolling = false
        c.scrollTop = c.scrollHeight
      })
      this.resizeObserver.observe(container)
    }
  },
  beforeUnmount() {
    const container = this.$refs.messagesContainer
    if (container) {
      container.removeEventListener('scroll', this.handleUserScroll)
      container.removeEventListener('wheel', this.handleUserScroll)
      container.removeEventListener('touchstart', this.handleUserScroll)
    }
    if (this.rafId) cancelAnimationFrame(this.rafId)
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
    }
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
  width: 100%;
}

@media (max-width: 600px) {
  .messages-column {
    padding: 16px 12px 12px;
  }
  .welcome-message {
    margin-top: 60px;
  }
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
