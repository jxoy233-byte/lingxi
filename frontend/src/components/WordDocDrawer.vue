<!--
  WordDocDrawer.vue —— AI 调用 WordEditor 时右侧自动弹出的实时预览抽屉。

  数据流：
  - App.vue 检测到 tool_call_name 含 `from skills.WordEditor import` + WordDoc.create/open()
    → 抽 filePath，version++ → 这个组件 watch version（带 200ms debounce）→ fetch + mammoth 渲染
  - 每次 tool_call_result 抵达时 App.vue 再 version++ → 自动刷新（同一波只 render 一次）
  - isStreaming=false 后抽屉保持打开（对标 CheckpointPanel，不自动关）

  v1 只做只读预览。后续 v2 加 contenteditable + 结构化 diff 保存。

  已知限制（v1 范围外）：
  - mammoth 通过 dynamic import 懒加载，第一次打开抽屉时拉 ~150KB chunk
  - 跨 session 背景流（snapshot path）：若用户切到 B 但 A 还在流式，A 的 WordEditor 调用也会开抽屉，
    显示 404 → 用户手关。原因是 hook 在 14 个 SSE 站点无差别调用，无法拿到 requestSessionId。
    v2 加 sessionId 透传时一并修。
-->
<template>
  <transition name="slide">
    <aside
      v-if="visible"
      class="word-doc-drawer"
      tabindex="-1"
      ref="drawerEl"
      :style="{ width: panelWidth + 'px' }"
      @keydown="handleKeydown"
    >
      <div class="resize-handle" @mousedown="startResize" />

      <header class="drawer-header">
        <span class="drawer-title">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="9" y1="13" x2="15" y2="13"/>
            <line x1="9" y1="17" x2="15" y2="17"/>
          </svg>
          写作面板
        </span>
        <span v-if="isStreaming" class="drawer-streaming">
          <span class="streaming-dot" />
          AI 正在写入…
        </span>
        <span v-else class="drawer-idle">已就绪</span>

        <span class="drawer-spacer" />

        <button
          class="drawer-reload"
          :disabled="loading || !filePath"
          title="手动刷新"
          @click="reloadNow"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
        </button>
        <button class="drawer-close" title="关闭（Esc）" @click="$emit('close')">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </header>

      <div class="drawer-content">
        <div v-if="loading && !html" class="drawer-loading">
          <div class="loading-spinner" />
          加载中…
        </div>

        <div v-else-if="error" class="drawer-error">
          <div class="error-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
          </div>
          <div class="error-text">{{ error }}</div>
          <button class="error-retry" @click="reloadNow">重试</button>
        </div>

        <div v-else-if="!filePath" class="drawer-empty">
          <p>等待 AI 开始写入文档…</p>
        </div>

        <article v-show="html" class="docx-preview" v-html="sanitizedHtml" />
      </div>
    </aside>
  </transition>
</template>

<script>
import DOMPurify from 'dompurify'

export default {
  name: 'WordDocDrawer',
  props: {
    visible: { type: Boolean, default: false },
    filePath: { type: String, default: '' },
    version: { type: Number, default: 0 },
    isStreaming: { type: Boolean, default: false }
  },
  emits: ['close'],
  data() {
    return {
      html: null,
      error: null,
      loading: false,
      panelWidth: 540,
      isResizing: false,
      startX: 0,
      startWidth: 0,
      // 防止过期请求覆盖更新结果（每个 reload +1，response 回来时校验是否还是当前 token）
      _reloadToken: 0,
      // debounce 定时器：version/filePath 变化 200ms 内合并成一次 fetch
      _reloadTimer: null,
      _lastRenderedVersion: -1,    // 上次实际 fetch 的 version；reload 早退避
      _mammoth: null               // dynamic import 缓存
    }
  },
  computed: {
    sanitizedHtml() {
      // mammoth 输出含 inline style；DOMPurify 默认允许 style 属性（mammoth 自身已转 inline style，
      // 但仍要过 DOMPurify 一遍防 XSS）。ALLOWED_TAGS 加 <u>/<s> 等 docx 常见标签。
      if (!this.html) return ''
      return DOMPurify.sanitize(this.html, {
        ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','strong','em','u','s','sub','sup',
                       'ul','ol','li','a','table','thead','tbody','tr','th','td','br','img','span'],
        ALLOWED_ATTR: ['href','src','style','colspan','rowspan'],
        ALLOW_DATA_ATTR: false
      })
    }
  },
  watch: {
    version() { this._scheduleReload() },
    filePath() {
      // filePath 变 → 立即重置 html（避免显示旧文件的最后渲染）+ 立即 reload（不 debounce，路径已变）
      this.html = null
      this.error = null
      this._lastRenderedVersion = -1
      this._scheduleReload({ immediate: true })
    }
  },
  mounted() {
    // 抽屉打开后聚焦，方便 Esc 关闭
    this.$nextTick(() => {
      if (this.visible && this.$refs.drawerEl) {
        this.$refs.drawerEl.focus()
      }
    })
  },
  methods: {
    /**
     * 把多次 version++ 合并到一次 fetch。AI 一轮内连续 add_paragraph/add_table 产生多个 tool_call_result，
     * 如果每个都 fetch+mammoth 会让 CPU 抖动；200ms 窗口足够合并一波写入。
     *
     * filePath 变化也走 debounce（带 immediate=true），因为路径变了原来的 html 必须作废。
     */
    _scheduleReload(opts = {}) {
      if (this._reloadTimer) {
        clearTimeout(this._reloadTimer)
        this._reloadTimer = null
      }
      if (opts.immediate) {
        this.reloadNow()
        return
      }
      this._reloadTimer = setTimeout(() => {
        this._reloadTimer = null
        this.reloadNow()
      }, 200)
    },
    /**
     * 用户点 ↻ 按钮 / 重试按钮 → 立即 reload，不走 debounce。
     */
    reloadNow() {
      this.reload()
    },
    async reload() {
      if (!this.filePath) return
      // 早退避：version 跟上一次 render 相同就不重做
      if (this.version === this._lastRenderedVersion) return
      const token = ++this._reloadToken
      this.loading = true
      this.error = null
      try {
        const resp = await fetch(this.filePath + '?t=' + Date.now())
        if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`)
        const buf = await resp.arrayBuffer()
        // 防止过期请求覆盖更新结果
        if (token !== this._reloadToken) return

        // 懒加载 mammoth —— 第一次打开抽屉才拉 ~150KB chunk
        if (!this._mammoth) {
          const mod = await import('mammoth/mammoth.browser.js')
          this._mammoth = mod.default || mod
        }
        // 再校验一次：mammoth 加载期间又来了新 version？
        if (token !== this._reloadToken) return

        const result = await this._mammoth.convertToHtml({ arrayBuffer: buf })
        if (token !== this._reloadToken) return
        this.html = result.value
        this._lastRenderedVersion = this.version
        if (result.messages && result.messages.length) {
          // mammoth 警告不阻塞；常见：未支持图片样式、内嵌字体
          console.debug('[WordDocDrawer] mammoth messages:', result.messages.slice(0, 3))
        }
      } catch (e) {
        if (token !== this._reloadToken) return
        if (this.html) {
          // 已有内容时仅 console.warn，不擦掉原 HTML —— 容忍中途 404
          console.warn('[WordDocDrawer] reload 失败，保留旧预览:', e.message)
          this.error = null
        } else {
          this.error = `加载失败: ${e.message}`
        }
      } finally {
        if (token === this._reloadToken) this.loading = false
      }
    },
    handleKeydown(e) {
      if (e.key === 'Escape' && !this.isResizing) {
        this.$emit('close')
      }
    },
    startResize(e) {
      this.isResizing = true
      this.startX = e.clientX
      this.startWidth = this.panelWidth
      document.addEventListener('mousemove', this.onResize)
      document.addEventListener('mouseup', this.stopResize)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    onResize(e) {
      if (!this.isResizing) return
      // 抽屉从右往左增长：deltaX 负值 = 加宽
      const delta = this.startX - e.clientX
      const next = Math.max(360, Math.min(window.innerWidth * 0.7, this.startWidth + delta))
      this.panelWidth = next
    },
    stopResize() {
      this.isResizing = false
      document.removeEventListener('mousemove', this.onResize)
      document.removeEventListener('mouseup', this.stopResize)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  },
  beforeUnmount() {
    this.stopResize()
    if (this._reloadTimer) {
      clearTimeout(this._reloadTimer)
      this._reloadTimer = null
    }
  }
}
</script>

<style scoped>
.word-doc-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  background: var(--bg-primary, #ffffff);
  border-left: 1px solid var(--border-color, #e5e7eb);
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  z-index: 100;
  outline: none;
}

.resize-handle {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 1;
}
.resize-handle:hover {
  background: rgba(99, 102, 241, 0.15);
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px 12px 18px;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  background: var(--bg-secondary, #f9fafb);
  flex-shrink: 0;
  font-size: 13px;
  user-select: none;
}

.drawer-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.drawer-title svg {
  color: var(--text-secondary, #6b7280);
}

.drawer-streaming {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #f59e0b;
  font-size: 12px;
  font-weight: 500;
}
.streaming-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f59e0b;
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

.drawer-idle {
  color: var(--text-tertiary, #9ca3af);
  font-size: 12px;
}

.drawer-spacer {
  flex: 1;
}

.drawer-reload,
.drawer-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s, color 0.15s;
}
.drawer-reload:hover:not(:disabled),
.drawer-close:hover {
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-primary, #111827);
}
.drawer-reload:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.drawer-content {
  flex: 1;
  overflow: auto;
  background: var(--bg-primary, #ffffff);
  position: relative;
}

.drawer-loading,
.drawer-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--text-tertiary, #9ca3af);
  font-size: 13px;
}
.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-color, #e5e7eb);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.drawer-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  padding: 32px;
  text-align: center;
}
.error-icon {
  color: var(--text-tertiary, #9ca3af);
}
.error-text {
  color: var(--text-secondary, #6b7280);
  font-size: 13px;
  line-height: 1.5;
  max-width: 320px;
}
.error-retry {
  padding: 6px 16px;
  border: 1px solid var(--border-color, #d1d5db);
  background: var(--bg-primary, #ffffff);
  border-radius: 5px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary, #111827);
}
.error-retry:hover {
  background: var(--bg-hover, #f3f4f6);
}

/* mammoth 输出 → docx 样式回放 */
.docx-preview {
  padding: 28px 40px;
  max-width: 760px;
  margin: 0 auto;
  line-height: 1.7;
  color: var(--text-primary, #111827);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  font-size: 14px;
}
.docx-preview :deep(h1) {
  font-size: 24px;
  font-weight: bold;
  margin: 1.2em 0 0.5em;
  line-height: 1.3;
}
.docx-preview :deep(h2) {
  font-size: 20px;
  font-weight: bold;
  margin: 1em 0 0.4em;
  line-height: 1.3;
}
.docx-preview :deep(h3) {
  font-size: 17px;
  font-weight: bold;
  margin: 0.8em 0 0.4em;
}
.docx-preview :deep(h4) {
  font-size: 15px;
  font-weight: bold;
  margin: 0.6em 0 0.3em;
}
.docx-preview :deep(p) {
  margin: 0.6em 0;
}
.docx-preview :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
  font-size: 13px;
}
.docx-preview :deep(th),
.docx-preview :deep(td) {
  border: 1px solid var(--border-color, #d1d5db);
  padding: 6px 10px;
  text-align: left;
  vertical-align: top;
}
.docx-preview :deep(th) {
  background: var(--bg-secondary, #f9fafb);
  font-weight: 600;
}
.docx-preview :deep(ul),
.docx-preview :deep(ol) {
  margin: 0.6em 0;
  padding-left: 2em;
}
.docx-preview :deep(li) {
  margin: 0.2em 0;
}
.docx-preview :deep(a) {
  color: #6366f1;
  text-decoration: underline;
}

/* mammoth 内嵌图片通常是 base64，max-width 防溢出 */
.docx-preview :deep(img) {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1em auto;
}

/* slide 入场动画 — 从右往左滑入 */
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}
</style>