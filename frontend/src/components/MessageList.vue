<template>
  <div class="messages-container" ref="messagesContainer">
    <div class="messages-column" ref="messagesColumn">
      <div v-if="messages.length === 0" class="welcome-message">
        <h2>你好！我是灵析——数据分析智能助手</h2>
        <p>有什么我可以帮助你的吗？</p>
        <p class="welcome-hint">
          初次使用？试试
          <button type="button" class="welcome-chip" @click="$emit('insert-suggestion', '/help')">/help</button>
          了解所有功能，或
          <button type="button" class="welcome-chip" @click="$emit('insert-suggestion', '/setup')">进入配置向导</button>
        </p>
      </div>

      <MessageItem
        v-for="(msg, index) in flattenedMessages"
        :key="msg._key || index"
        :message="msg"
        :message-index="index"
        :is-first-ai-message="isFirstAiMessage(index)"
        :is-latest-ai-message="index === latestAiMessageIndex"
        :is-interrupted="isInterrupted"
        :is-interrupted-session-id="isInterruptedSessionId"
        :current-session-id="currentSessionId"
        :has-received-init="hasReceivedInit"
        :pending-interrupt-session-id="pendingInterruptSessionId"
        :pending-tool-approval="pendingToolApproval"
        :submitting-tool-decision="submittingToolDecision"
        :can-withdraw="canWithdrawFor(index)"
        @restore="$emit('restore', $event)"
        @restream="(...args) => $emit('restream', ...args)"
        @open-link="$emit('open-link', $event)"
        @preview-file="$emit('preview-file', $event)"
        @interrupt="$emit('interrupt', $event)"
        @resume="$emit('resume', $event)"
        @restart-session="$emit('restart-session', $event)"
        @quote="$emit('quote', $event)"
        @tool-decide="(decision) => $emit('tool-decide', decision)"
        @withdraw="$emit('withdraw', $event)"
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

// —— 会话滚动位置缓存（localStorage，一个会话一个 key）——
// 只在「用户主动滚开过」时才有值：停在底部 = 无需记忆（下次默认就滑到底），
// 所以缓存天然自清理，只会为"读历史读一半就切走"的会话留记录。
const SCROLL_POS_PREFIX       = 'chatme-scroll-pos:'
const SCROLL_CACHE_MAX        = 60                      // 最多保留多少个会话（超出按 ts 淘汰最旧）
const SCROLL_CACHE_TTL_MS     = 30 * 24 * 3600 * 1000   // 30 天没再进入过的会话位置直接丢
const SCROLL_SAVE_DEBOUNCE_MS = 600
const AT_BOTTOM_RATIO         = 0.995                   // 进度 ≥ 此值视为"在底部"，不写缓存

function _easeOutCubic(t) { return 1 - Math.pow(1 - t, 3) }
function _easeInCubic(t)  { return t * t * t }
function _easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

export default {
  name: 'MessageList',
  components: {
    MessageItem,
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
    },
    pendingToolApproval: {
      // 内嵌审批：标记具体 AI 消息 + tool call，让 MessageItem 高亮 + 渲染内嵌按钮
      // { messageIndex, toolIndex, command, action, sessionId } | null
      type: Object,
      default: null
    },
    submittingToolDecision: {
      type: Boolean,
      default: false
    },
  },
  emits: [
    'restore', 'restream', 'open-link', 'preview-file', 'interrupt', 'resume', 'restart-session', 'quote', 'tool-decide', 'withdraw', 'insert-suggestion',
  ],
  data() {
    return {
      isAutoScrolling: false,   // 当前是否在自动滚动中
      rafId: null,              // requestAnimationFrame id
      // 内容更新前用户是否处于底部（beforeUpdate 钩子捕获，用于跨过大块内容更新）
      _userAtBottomBeforeUpdate: true,
      // 用户主动 wheel/touch 过：置位后 watcher 一律不接管，直至他们滚回底部（含容差）清掉
      // ——对应 CLAUDE.md 偏好 4「wheel/touch 立即让出控制权」；
      // 单纯靠 isAtBottom() 的 50px 容差判定会被小幅上滚 + 内容撑高误导
      _userScrolledAway: false,

      // —— 滚动状态机 ——
      // 'entry'    会话入场/刷新：easeInOut 滑到底
      // 'ramping'  流式刚启动：双阶段（先慢后快）下滑
      // 'locked'   已锁定跟随：每次 append snappy 跟上
      // 'idle'     默认：stick-to-bottom
      scrollMode: 'idle',
      _rampStartedAt: 0,
      _suppressScroll: false,
      _snapScrollInFlight: false,
      _wasLoading: false,
      // 该会话的「入场」还没执行（会话切了但消息还没到位 / 首次挂载时还没有消息）——
      // 等 messages watcher 拿到真正属于该会话的内容后再入场，避免对着上一个会话的
      // 内容算位置、对着旧 scrollTop 起步
      _pendingEntry: false,
      _saveScrollTimer: null
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

    // 撤回按钮是否可点：
    // 必须存在「上一轮 AI 消息」且其 checkpointId/last_checkpoint_id 非空
    // （首条用户消息前面没有 AI，回溯无目标 → 禁用）
    canWithdrawFor(index) {
      const flattened = this.flattenedMessages
      const msg = flattened[index]
      if (!msg || msg.role !== 'user') return false
      // 向前找最近的 AI 消息
      for (let i = index - 1; i >= 0; i--) {
        const prev = flattened[i]
        if (prev && prev.role === 'ai') {
          const cid = prev.additional_kwargs?.last_checkpoint_id || prev.checkpointId
          return Boolean(cid)
        }
      }
      return false
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
          // 普通跟随：短 snappy easeOut（目标动态求值，跟随期间内容变高也追得上）
          this._runRaf({
            container,
            startTop: container.scrollTop,
            targetTop: (c) => c.scrollHeight - c.clientHeight,
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
    // - targetTop 可以是数字（固定目标）或函数（每帧重新求值）——后者用于「目标本身会动」的场景：
    //   图片 / 异步内容在动画期间加载会撑高 scrollHeight，固定目标会让动画停在旧底部
    _runRaf({ container, startTop, targetTop, duration, easing, onUpdate, onComplete }) {
      this._cancelRaf()
      const startTime = performance.now()
      this.isAutoScrolling = true
      // 上一帧我们设下去的值。用它判断「滚动条被谁动了」——方向无关：
      // 位置恢复动画本身可能向上走（目标在上方），那一帧的 scrollTop 比 startTop 小，
      // 但那是我们自己设的，不该被误判成用户打断。
      let lastSetTop = container.scrollTop

      const step = (now) => {
        // 检测「滚动条被外部动过」（用户 wheel / 内容整体替换导致浏览器 clamp）：
        //   - content 增长时 scrollTop 不变、scrollHeight 涨，原 !isAtBottom() 会误 bail
        //   - 用户主动 wheel/touchstart 主要被 _handleUserIntent 同步处理，这里是冗余安全网
        //   - 顺手把 mode 交回 idle，否则 entry/ramping 会永久卡住，
        //     后续 watcher / ResizeObserver 全被 mode 挡住（表现为"停在半路不动"）
        if (Math.abs(container.scrollTop - lastSetTop) > 1) {
          this.isAutoScrolling = false
          this._setMode('idle')
          return
        }
        const elapsed = now - startTime
        // ResizeObserver 回调和 rAF 在同一个渲染步里，前者跑在帧时间戳之后 →
        // 那种路径起步时 elapsed 可能为负，clamp 到 0 免得第一帧往回跳
        const t = Math.min(Math.max(elapsed / duration, 0), 1)
        const eased = this._easeFn(t, easing)
        // 函数目标：每帧重算当前物理底部，动画期间内容变高也能一路跟到底
        const target = typeof targetTop === 'function' ? targetTop(container) : targetTop
        // 防御：防止越过当前 scrollHeight
        const maxTop = container.scrollHeight - container.clientHeight
        const newTop = Math.min(startTop + (target - startTop) * eased, maxTop)
        container.scrollTop = newTop
        lastSetTop = newTop
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
        // 动态目标：图片 / 异步内容在入场动画期间陆续加载会撑高文档，
        // 固定目标会让入场停在"图片还没算进高度时"的旧底部
        targetTop: (c) => c.scrollHeight - c.clientHeight,
        duration: ENTRY_SCROLL_MS,
        easing: 'easeInOutCubic',
        onComplete: () => { this._setMode('idle') }
      })
    },

    // —— 会话入场 ——
    // 消息到位 / 首次挂载时走一次：有位置缓存就滑回上次离开的地方，否则滑到最新处。
    // 两种都是一段动画，用户 wheel/touch 随时可以打断（_handleUserIntent 取消 RAF）。
    _enterConversation() {
      const container = this.$refs.messagesContainer
      if (!container) return
      this._cancelRaf()

      // 流式中不做位置恢复（会跟跟随抢），直接滑到最新处
      const ratio = this.isLoading ? null : this._readScrollRatio(this.currentSessionId)
      if (ratio === null || ratio >= AT_BOTTOM_RATIO) {
        // 没缓存 / 上次就停在底部 → 滑到最新处（图片异步加载由 ResizeObserver 继续兜）
        this._userScrolledAway = false
        this._setMode('entry')
        this._startEntry()
        return
      }

      // 有缓存：滑回上次的位置。期间置 _userScrolledAway，别让 RO / watcher 抢着往底拖；
      // 真滑到底部会自动清掉（handleScrollEvent），恢复跟随。
      this._userScrolledAway = true
      this._setMode('entry')
      this._runRaf({
        container,
        startTop: container.scrollTop,
        // 动态目标：图片加载撑高文档时按同一比例跟，位置不会跑偏
        targetTop: (c) => ratio * (c.scrollHeight - c.clientHeight),
        duration: ENTRY_SCROLL_MS,
        easing: 'easeInOutCubic',
        onComplete: () => { this._setMode('idle') }
      })
    },

    // —— 滚动位置缓存 ——
    _readScrollRatio(sessionId) {
      if (!sessionId) return null
      try {
        const raw = localStorage.getItem(SCROLL_POS_PREFIX + sessionId)
        if (!raw) return null
        const entry = JSON.parse(raw)
        return typeof entry.r === 'number' ? entry.r : null
      } catch (e) {
        return null
      }
    },

    // 记录当前会话的滚动位置（比例，抗内容增减）。
    // 停在底部 → 删缓存（默认行为就是滑到底，不需要记）。
    _saveScrollPos(sessionId = this.currentSessionId) {
      const container = this.$refs.messagesContainer
      if (!sessionId || !container) return
      const max = container.scrollHeight - container.clientHeight
      const key = SCROLL_POS_PREFIX + sessionId
      try {
        if (max <= 0 || this.isAtBottom()) {
          localStorage.removeItem(key)
          return
        }
        localStorage.setItem(key, JSON.stringify({ r: container.scrollTop / max, ts: Date.now() }))
        this._pruneScrollCache()
      } catch (e) { /* 隐私模式 / 配额满：忽略，缓存不是关键路径 */ }
    },

    // 清缓存：先按 TTL 清过期的，再按 ts 从新到旧保留最近 SCROLL_CACHE_MAX 个
    _pruneScrollCache() {
      const now = Date.now()
      const items = []
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i)
        if (!key || !key.startsWith(SCROLL_POS_PREFIX)) continue
        let ts = 0
        try { ts = JSON.parse(localStorage.getItem(key)).ts || 0 } catch (e) { ts = 0 }
        items.push({ key, ts })
      }
      items.sort((a, b) => b.ts - a.ts)
      items.forEach((item, index) => {
        if (index >= SCROLL_CACHE_MAX || now - item.ts > SCROLL_CACHE_TTL_MS) {
          localStorage.removeItem(item.key)
        }
      })
    },

    _scheduleSaveScrollPos() {
      // 锁定 sessionId：600ms 内用户可能已经切走了，那时容器里是别人的内容
      const sid = this.currentSessionId
      if (this._saveScrollTimer) clearTimeout(this._saveScrollTimer)
      this._saveScrollTimer = setTimeout(() => {
        this._saveScrollTimer = null
        if (sid === this.currentSessionId) this._saveScrollPos(sid)
      }, SCROLL_SAVE_DEBOUNCE_MS)
    },

    // 内容异步变高（图片解码 / 字体 / 图表渲染）后直接贴底。
    // 只在用户没接管（_userScrolledAway=false）且没有动画在跑时调用。
    _snapToBottom(container) {
      const distance = container.scrollHeight - container.scrollTop - container.clientHeight
      if (distance <= 0) return
      this._cancelRaf()
      // 程序化贴底自产的 scroll 事件会被 handleScrollEvent 当成「用户意图」；
      // 而图片是连着加载的，此刻下一张可能已把内容撑高 → isAtBottom() 兜底失效
      // → _userScrolledAway 被误置 true → 后续图片不再跟随。吞掉这一次自产事件。
      this._snapScrollInFlight = true
      container.scrollTop = container.scrollHeight
      requestAnimationFrame(() => { this._snapScrollInFlight = false })
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
          // P2：加速到真正底部（目标动态求值，动画期间图片加载撑高也能追平）
          // easeOutCubic：slow start, fast end——从 P1 的匀速平滑加速到 snappy
          const remaining = (container.scrollHeight - container.clientHeight) - container.scrollTop
          if (remaining <= 0) {
            this._setMode('locked')
            return
          }
          this._runRaf({
            container,
            startTop: container.scrollTop,
            targetTop: (c) => c.scrollHeight - c.clientHeight,
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
        targetTop: (c) => c.scrollHeight - c.clientHeight,
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
      // 任何滚动都记一次当前位置（含我们自己的动画滚动——那也代表用户最终看到的位置）
      this._scheduleSaveScrollPos()
      if (this.isAutoScrolling) return
      // 自己贴底产生的那一次 scroll，不是用户意图
      if (this._snapScrollInFlight) return
      this._handleUserIntent()
      // 用户滚回底部（含 50px 容差）→ 清掉「已离开跟随」标记，watcher 恢复接管
      if (this.isAtBottom()) {
        this._userScrolledAway = false
      }
    },

    // 2. wheel / touchstart 事件：明确是用户输入
    //    关键：ramp 阶段不能再被 `isAutoScrolling && isAtBottom()` 早退吞掉，
    //    否则用户在 ramp P2（接近底部）阶段 wheel 就触发不了打断
    handleUserInput() {
      this._handleUserIntent()
    },

    // 统一的用户意图分发：按当前 scrollMode 决定处理
    _handleUserIntent() {
      // 任何 wheel/touch 都先打「用户已离开跟随」标记。
      // ——单单 gate isAtBottom() 不够：50px 容差里小幅上滚 + 大段内容追加
      // 仍会被 beforeUpdate 误判为「用户在底部」；sticky flag 才兜得住。
      this._userScrolledAway = true

      if (this.scrollMode === 'ramping') {
        // ramp 启动 < 100ms 的 wheel 视为触摸板惯性，吞掉不中断
        if (performance.now() - this._rampStartedAt < INTERRUPT_DEBOUNCE_MS) return
        this._userInterruptDuringRamp()
        return
      }

      if (this.scrollMode === 'locked') {
        // 任何 wheel/touch 立即让出控制权（CLAUDE.md 偏好 4）：
        // ——不再 gate isAtBottom() 的 50px 容差；小幅上滚意图也尊重。
        // ——后续 watcher 看到 _userScrolledAway=true 自动不再强制跟。
        this._cancelRaf()
        this._setMode('idle')
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
        // 该会话的入场还没做（会话切了，消息这时候才到位）→
        // 走入场（有位置缓存就滑回上次位置，否则滑到最新处），不走普通跟随
        if (this._pendingEntry) {
          this._pendingEntry = false
          this.$nextTick(() => this._enterConversation())
          return
        }
        // ramping / entry：让当前动画接管，watcher 不动
        if (this.scrollMode === 'ramping' || this.scrollMode === 'entry') return
        // 用户已主动离开跟随：locked 让出，idle 也不接管
        if (this._userScrolledAway) {
          if (this.scrollMode === 'locked') {
            this._setMode('idle')
          }
          return
        }
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
        // ——发新消息/重新生成 就是"用户想跟"的强信号，清掉 _userScrolledAway
        //   否则沿用旧 flag 会让首段 locked follow 被吞，跟不上
        this._userScrolledAway = false
        // 流式接管：不该再去做入场（恢复上次位置会跟流式抢）
        this._pendingEntry = false
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
        // 离开上一个会话前，把它当时的位置记下来（此刻 DOM 里还是旧会话的内容）
        if (oldVal) this._saveScrollPos(oldVal)
        // `_userScrolledAway` 描述的是「上一个会话」的滚动意图，绝不能跨会话泄漏：
        // 否则旧会话里滚上去留下的 true 会让新会话的图片加载 / 内容变高
        // 全被 ResizeObserver 挡掉（卡在半路）。切会话 = 明确的"带我去新会话"意图。
        this._userScrolledAway = false
        this._cancelRaf()
        // 入场推迟到「属于新会话的消息到位」那一刻（messages watcher）；
        // 这里 App.vue 往往还没 fetch 完，对着旧内容算位置会滑错地方
        this._pendingEntry = true
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

      // 监听「内容」高度变化（图片 / mermaid / 异步渲染加载完成后撑高文档），
      // 用户没接管就一直贴到新底部，避免卡在"图片还没加载时算出的旧底部"。
      // 必须观察 .messages-column（高度 = 内容高度）而不是 .messages-container：
      // 后者 flex:1，高度由布局决定，图片加载根本不会让它变尺寸 → 回调永不触发。
      this.resizeObserver = new ResizeObserver(() => {
        const c = this.$refs.messagesContainer
        if (!c) return
        // 用户已主动滚开：绝不抢控制权
        if (this._userScrolledAway) return
        // entry / ramping 动画自己的目标就是动态求值的，让它接管，别打架
        if (this.scrollMode === 'entry' || this.scrollMode === 'ramping') return
        // locked（流式中）：内容变高后 watcher 可能已不再触发，这里补一次 snappy 跟随。
        // 但流式期间这里几乎每帧都会被调用 —— 已经在跟随动画里就啥都别做：
        // 那个动画的 targetTop 是动态求值的，自己就会吸收掉这点增量；
        // 若在此 cancel + 重启，每帧都从 t=0 重新开始，跟随会彻底卡住。
        if (this.scrollMode === 'locked') {
          if (!this.isAutoScrolling) this._scheduleLockedFollow()
          return
        }
        this._snapToBottom(c)
      })
      const column = this.$refs.messagesColumn
      if (column) this.resizeObserver.observe(column)

      // 初次挂载：有会话就入场（有位置缓存滑回上次位置，否则滑到最新处）。
      // 消息还没到位就先挂 pending，等 messages watcher 拿到内容再入场。
      this.$nextTick(() => {
        if (!this.currentSessionId) return
        if (this.messages.length > 0) {
          this._enterConversation()
        } else {
          this._pendingEntry = true
        }
      })

      // 顺手清一遍过期位置缓存（TTL / 条数）
      this._pruneScrollCache()
    }
  },
  beforeUnmount() {
    // 组件卸载（F5 / 关窗）前把当前位置落盘，下次进来才能滑回原处
    if (this._saveScrollTimer) {
      clearTimeout(this._saveScrollTimer)
      this._saveScrollTimer = null
    }
    this._saveScrollPos()
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

.welcome-hint {
  margin-top: 18px;
  font-size: 13px;
  color: var(--text-secondary);
}

.welcome-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  margin: 0 2px;
  background: rgba(59, 130, 246, 0.14);
  color: rgb(59, 130, 246);
  border: 1px solid rgba(59, 130, 246, 0.28);
  border-radius: 7px;
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s, transform 0.08s;
  vertical-align: baseline;
  user-select: none;
}

.welcome-chip:hover {
  background: rgba(59, 130, 246, 0.22);
  border-color: rgba(59, 130, 246, 0.42);
}

.welcome-chip:active {
  transform: scale(0.97);
}

.dark-theme .welcome-chip {
  background: rgba(59, 130, 246, 0.18);
  color: rgb(59, 130, 246);
  border-color: rgba(59, 130, 246, 0.32);
}
.dark-theme .welcome-chip:hover {
  background: rgba(59, 130, 246, 0.28);
  border-color: rgba(59, 130, 246, 0.5);
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
