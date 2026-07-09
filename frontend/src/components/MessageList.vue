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

// 滚动相关 tuning 常量（统一在这里好调）
const ENTRY_SCROLL_MS       = 800
const RAMP_PHASE1_FRACTION  = 0.5    // P1 走 50% 距离
const RAMP_PHASE1_MS        = 600
const RAMP_PHASE2_MS        = 250
const LOCKED_FOLLOW_MS      = 150
const INTERRUPT_DEBOUNCE_MS = 100    // ramp 开始后这段时间内的 wheel 不算打断（吸收触摸板惯性）

function _easeOutCubic(t) { return 1 - Math.pow(1 - t, 3) }
function _easeInCubic(t)  { return t * t * t }
function _easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

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
      _userAtBottomBeforeUpdate: true,

      // —— 滚动状态机 ——
      // 'entry'   会话入场/刷新：easeInOut 滑到底
      // 'ramp'    流式刚启动：双阶段（先慢后快）下滑
      // 'locked'  已锁定跟随：每次 append snappy 跟上
      // 'idle'    默认：stick-to-bottom
      scrollMode: 'idle',
      _rampStartedAt: 0,
      _suppressScroll: false,
      _wasLoading: false
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
    // - force: 强制无视 isAtBottom()，用于首屏加载等场景（旧 API 兼容）
    // - profile: 'entry'（easeInOut ~500ms 平滑入场）| null（短 snappy 跟随）
    scrollToBottom({ force = false, profile = null } = {}) {
      const container = this.$refs.messagesContainer
      if (!container) return

      // 已经在 entry/ramping：让这两种模式接管，避免动画打架
      if (this.scrollMode === 'entry' || this.scrollMode === 'ramping') return

      // stick-to-bottom：用户不在底部就不跟随（除非强制）
      if (!force && !this.isAtBottom()) return

      this.$nextTick(() => {
        // 二次检查：跑 nextTick 时可能 scrollMode 又被改了
        if (this.scrollMode === 'entry' || this.scrollMode === 'ramping') return
        // isLoading 时让路给 ramp/locked；但如果用户原本就在底部（beforeUpdate 捕获的 _userAtBottomBeforeUpdate），
        // 即使新 token 推高了 scrollHeight 让 isAtBottom() 因 >50px 容差返回 false，也要 snappy 跟
        // ——beforeUpdate 的快照才是"用户意图"的真实信号；isAtBottom() 在新内容追加后会失真
        if (this.isLoading && profile !== 'entry' && !this._userAtBottomBeforeUpdate) return

        const distance = container.scrollHeight - container.scrollTop - container.clientHeight
        if (distance <= 0) return

        if (profile === 'entry') {
          this._setMode('entry')
          this._startEntry()
        } else {
          // 普通跟随：短 snappy easeOut
          this._runRaf({
            container,
            startTop: container.scrollTop,
            targetTop: container.scrollTop + distance,
            duration: LOCKED_FOLLOW_MS,
            easing: 'easeOutCubic'
          })
        }
      })
    },

    // 静默刷新消息，不触发自动滚动
    suppressNextScroll() {
      this._suppressScroll = true
    },

    // —— 状态机 ——
    _setMode(mode) {
      if (this.scrollMode === mode) return
      this.scrollMode = mode
    },

    _cancelRaf() {
      if (this.rafId) {
        cancelAnimationFrame(this.rafId)
        this.rafId = null
      }
      this.isAutoScrolling = false
    },

    // 通用 RAF stepper：duration ms 内把 container.scrollTop 从 startTop 走到 targetTop
    _runRaf({ container, startTop, targetTop, duration, easing, onUpdate, onComplete }) {
      this._cancelRaf()
      const diff = targetTop - startTop
      const startTime = performance.now()
      this.isAutoScrolling = true

      const step = (now) => {
        // 检测「用户主动往上滚」而非「是否在底部」：
        //   - content 增长时 scrollTop 不变，scrollHeight 涨，原本的 !isAtBottom() 误 bail
        //   - 用户主动 wheel/touchstart 才会让 scrollTop 减小（往上），这是真正要 bail 的信号
        //   - 用户中断主要被 _handleUserIntent 同步处理；这里是冗余安全网
        if (container.scrollTop < startTop - 1) {
          this.isAutoScrolling = false
          return
        }
        const elapsed = now - startTime
        const t = Math.min(elapsed / duration, 1)
        const eased = this._easeFn(t, easing)
        const newTop = startTop + diff * eased
        // 防御：防止越过当前 scrollHeight
        const maxTop = container.scrollHeight - container.clientHeight
        container.scrollTop = Math.min(newTop, maxTop)
        if (onUpdate) onUpdate(newTop, t)
        if (t < 1) {
          this.rafId = requestAnimationFrame(step)
        } else {
          this.isAutoScrolling = false
          if (onComplete) onComplete()
        }
      }

      this.rafId = requestAnimationFrame(step)
    },

    _easeFn(t, type) {
      switch (type) {
        case 'easeInOutCubic': return _easeInOutCubic(t)
        case 'easeInCubic':    return _easeInCubic(t)
        case 'easeOutCubic':   return _easeOutCubic(t)
        default:               return t
      }
    },

    smoothScroll(container, targetTop, duration, easing = 'easeOutCubic') {
      this._runRaf({
        container,
        startTop: container.scrollTop,
        targetTop,
        duration,
        easing,
        onComplete: () => { /* 由调用者决定 mode 切换 */ }
      })
    },

    // —— entry profile ——
    _startEntry() {
      const container = this.$refs.messagesContainer
      if (!container) return
      this._runRaf({
        container,
        startTop: container.scrollTop,
        targetTop: container.scrollHeight - container.clientHeight,
        duration: ENTRY_SCROLL_MS,
        easing: 'easeInOutCubic',
        onComplete: () => { this._setMode('idle') }
      })
    },

    // —— ramp profile（双阶段）——
    _startRamp() {
      const container = this.$refs.messagesContainer
      if (!container) return

      const startTop = container.scrollTop
      const scrollHeight = container.scrollHeight
      const clientHeight = container.clientHeight
      const fullDistance = scrollHeight - startTop - clientHeight

      if (fullDistance <= 0) {
        // 已经在底部，直接进 locked
        this._setMode('locked')
        return
      }

      // P1 target clamp：不超过物理底部
      const phase1Target = Math.min(
        startTop + fullDistance * RAMP_PHASE1_FRACTION,
        scrollHeight - clientHeight
      )
      this._rampStartedAt = performance.now()

      this._runRaf({
        container,
        startTop,
        targetTop: phase1Target,
        duration: RAMP_PHASE1_MS,
        // P1：linear 匀速慢动——给用户时间反应，符合"慢慢来"
        easing: 'linear',
        onComplete: () => {
          if (this.scrollMode !== 'ramping') return
          // P2：加速到真正底部（重新 snapshot 距离）
          // easeOutCubic：slow start, fast end——从 P1 的匀速平滑加速到 snappy
          const remaining = (container.scrollHeight - container.clientHeight) - container.scrollTop
          if (remaining <= 0) {
            this._setMode('locked')
            return
          }
          this._runRaf({
            container,
            startTop: container.scrollTop,
            targetTop: container.scrollTop + remaining,
            duration: RAMP_PHASE2_MS,
            easing: 'easeOutCubic',
            onComplete: () => {
              if (this.scrollMode === 'ramping') this._setMode('locked')
            }
          })
        }
      })
    },

    // —— locked follow（每次 append 短 snappy 到底）——
    _scheduleLockedFollow() {
      const container = this.$refs.messagesContainer
      if (!container) return
      const distance = container.scrollHeight - container.scrollTop - container.clientHeight
      if (distance <= 0) return
      this._runRaf({
        container,
        startTop: container.scrollTop,
        targetTop: container.scrollTop + distance,
        duration: LOCKED_FOLLOW_MS,
        easing: 'easeOutCubic',
        onComplete: () => { this._setMode('locked') }
      })
    },

    // 用户中断 ramp：停在当前位置
    _userInterruptDuringRamp() {
      this._cancelRaf()
      this._setMode('idle')
    },

    // —— 用户输入分两类监听 ——
    // 1. scroll 事件：可能是我们自己 RAF 产生的，也可能是用户 wheel 浏览器滚动引发的
    //    区分方式：isAutoScrolling=true 时是我们自己的 scroll，吞掉；否则走 _handleUserIntent
    handleScrollEvent() {
      if (this.isAutoScrolling) return
      this._handleUserIntent()
    },

    // 2. wheel / touchstart 事件：明确是用户输入
    //    关键：ramp 阶段不能再被 `isAutoScrolling && isAtBottom()` 早退吞掉，
    //    否则用户在 ramp P2（接近底部）阶段 wheel 就触发不了打断
    handleUserInput() {
      this._handleUserIntent()
    },

    // 统一的用户意图分发：按当前 scrollMode 决定处理
    _handleUserIntent() {
      if (this.scrollMode === 'ramping') {
        // ramp 启动 < 100ms 的 wheel 视为触摸板惯性，吞掉不中断
        if (performance.now() - this._rampStartedAt < INTERRUPT_DEBOUNCE_MS) return
        this._userInterruptDuringRamp()
        return
      }

      if (this.scrollMode === 'locked') {
        // 取消 in-flight follow 动画，避免和用户的手指打架
        if (this.rafId) {
          cancelAnimationFrame(this.rafId)
          this.rafId = null
        }
        this.isAutoScrolling = false
        // 检测离开底部：直接退 idle（简化的语义；不回锁）
        if (!this.isAtBottom()) {
          this._setMode('idle')
        }
        return
      }

      if (this.scrollMode === 'entry') {
        this._cancelRaf()
        this._setMode('idle')
        return
      }

      // 'idle'：取消任何 in-flight auto-scroll
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
          // 阻止浏览器 overflow-anchor 自动滚动：保存 scrollTop，DOM 更新后恢复
          const container = this.$refs.messagesContainer
          if (container) {
            const savedTop = container.scrollTop
            this.$nextTick(() => {
              // 只在确实发生自动滚动时恢复（容差 1px）
              if (Math.abs(container.scrollTop - savedTop) > 1) {
                container.scrollTop = savedTop
              }
            })
          }
          return
        }
        // ramping / entry：让当前动画接管，watcher 不动
        if (this.scrollMode === 'ramping' || this.scrollMode === 'entry') return
        // locked：每次新消息 snappy 跟上
        if (this.scrollMode === 'locked') {
          this._scheduleLockedFollow()
          return
        }
        // idle：原 sticky-bottom 行为
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
      const wasLoading = this._wasLoading
      this._wasLoading = newVal

      if (newVal && !wasLoading) {
        // 流式刚启动：总是开 ramp，给"自动往下滑"的趋势
        // 用户的控制权由 ramp 中的 wheel/touch 打断机制保证
        // 即使之前用户已滚开（上一轮流式时主动离开过底部），新一轮流式也要重新 ramp 一次
        this.$nextTick(() => {
          this._setMode('ramping')
          this._startRamp()
        })
        return
      }

      if (!newVal && wasLoading) {
        // 流式结束：ramping/locked → idle
        if (this.scrollMode === 'ramping' || this.scrollMode === 'locked') {
          this._cancelRaf()
          this._setMode('idle')
        }
      }
    },
    currentSessionId(newVal, oldVal) {
      if (newVal && newVal !== oldVal) {
        // 会话切换触发 entry 平滑入场（兜底；App.vue 也可能已经触发过）
        this.$nextTick(() => {
          if (this.messages.length > 0) {
            this._cancelRaf()
            this._setMode('entry')
            this._startEntry()
          }
        })
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
      // scroll 事件：自己 RAF 的 scroll 用 isAutoScrolling 早退吞掉；用户的 scroll 走 _handleUserIntent
      // wheel / touchstart：明确是用户输入，直接进 _handleUserIntent
      container.addEventListener('scroll', this.handleScrollEvent, { passive: true })
      container.addEventListener('wheel', this.handleUserInput, { passive: true })
      container.addEventListener('touchstart', this.handleUserInput, { passive: true })

      // 监听容器尺寸变化（图片/异步内容加载会让容器变高），
      // 如果用户在底部，就直接跟到新底部，避免卡在"图片还没加载时算出的旧底部"。
      // ramping / entry 阶段暂停：不要 yank 节奏。
      this.resizeObserver = new ResizeObserver(() => {
        const c = this.$refs.messagesContainer
        if (!c) return
        if (this.scrollMode === 'ramping' || this.scrollMode === 'entry') return
        if (!this.isAtBottom()) return
        if (this.rafId) {
          cancelAnimationFrame(this.rafId)
          this.rafId = null
        }
        this.isAutoScrolling = false
        c.scrollTop = c.scrollHeight
      })
      this.resizeObserver.observe(container)

      // 初次挂载：若已经有当前会话+消息，触发 entry 平滑入场
      // （覆盖页面刷新、首次进入等场景；App.vue 也会通过 scrollToBottom(true) 触发一次）
      this.$nextTick(() => {
        if (this.currentSessionId && this.messages.length > 0) {
          this._setMode('entry')
          this._startEntry()
        }
      })
    }
  },
  beforeUnmount() {
    const container = this.$refs.messagesContainer
    if (container) {
      container.removeEventListener('scroll', this.handleScrollEvent)
      container.removeEventListener('wheel', this.handleUserInput)
      container.removeEventListener('touchstart', this.handleUserInput)
    }
    this._cancelRaf()
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
