<template>
  <transition name="slide">
    <aside v-if="visible" class="web-preview-panel" :style="{ width: panelWidth + 'px' }">
      <!-- 拖拽调整宽度的手柄 -->
      <div class="resize-handle" @mousedown="startResize"></div>

      <!-- 顶栏 -->
      <div class="panel-toolbar">
        <div class="url-bar">
          <svg class="url-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
          <span class="url-text" :title="url">{{ displayUrl }}</span>
        </div>
        <div class="toolbar-actions">
          <button @click="reload" class="tool-btn" title="刷新">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"/>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
          </button>
          <button @click="openExternal" class="tool-btn" title="在浏览器中打开">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
              <polyline points="15 3 21 3 21 9"/>
              <line x1="10" y1="14" x2="21" y2="3"/>
            </svg>
          </button>
          <button @click="$emit('close')" class="tool-btn" title="关闭">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- iframe 区域 -->
      <div class="iframe-container">
        <div v-if="loading" class="iframe-loading">
          <div class="loading-spinner"></div>
          <p>加载中...</p>
        </div>

        <div v-if="blocked" class="iframe-blocked">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
          </svg>
          <p>该网站不支持内嵌预览</p>
          <button class="open-btn" @click="openExternal">在浏览器中打开</button>
        </div>

        <iframe
          v-show="!blocked"
          ref="iframe"
          :src="url"
          :key="iframeKey"
          @load="onLoad"
          @error="onError"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          referrerpolicy="no-referrer"
        />
      </div>
    </aside>
  </transition>
</template>

<script>
export default {
  name: 'WebPreviewPanel',
  props: {
    visible: { type: Boolean, default: false },
    url: { type: String, default: '' }
  },
  emits: ['close'],
  data() {
    return {
      loading: false,
      blocked: false,
      iframeKey: 0,
      panelWidth: 420,
      isResizing: false,
      startX: 0,
      startWidth: 0,
      rafId: null
    }
  },
  emits: ['close', 'resizing'],
  computed: {
    displayUrl() {
      try {
        const u = new URL(this.url)
        return u.hostname + (u.pathname !== '/' ? u.pathname : '')
      } catch {
        return this.url
      }
    }
  },
  watch: {
    url(newUrl) {
      if (newUrl) {
        this.loading = true
        this.blocked = false
        this.iframeKey++
      }
    }
  },
  methods: {
    onLoad() {
      // 尝试访问 iframe contentDocument，若被跨域拦截则认为正常加载完成
      // 真正被 X-Frame-Options 拒绝时 iframe 会触发 error 或内容为空
      this.loading = false
      // 检测是否加载失败（部分浏览器 load 也会触发但内容为空）
      try {
        const doc = this.$refs.iframe?.contentDocument
        if (doc && doc.body && doc.body.innerHTML === '') {
          this.blocked = true
        }
      } catch {
        // 跨域访问报错属正常，说明页面实际加载了
        this.loading = false
      }
    },
    onError() {
      this.loading = false
      this.blocked = true
    },
    reload() {
      this.loading = true
      this.blocked = false
      this.iframeKey++
    },
    openExternal() {
      window.open(this.url, '_blank', 'noopener,noreferrer')
    },
    startResize(e) {
      e.preventDefault()
      e.stopPropagation()
      this.isResizing = true
      this.startX = e.clientX
      this.startWidth = this.panelWidth

      window.addEventListener('mousemove', this.handleResize, { passive: true })
      window.addEventListener('mouseup', this.stopResize, { passive: false })

      document.body.style.cursor = 'ew-resize'
      document.body.style.userSelect = 'none'
      document.body.style.pointerEvents = 'none'

      this.$emit('resizing', true)
    },
    handleResize(e) {
      if (!this.isResizing) return

      // 使用 requestAnimationFrame 节流，避免频繁重绘
      if (this.rafId) return

      this.rafId = requestAnimationFrame(() => {
        const deltaX = this.startX - e.clientX
        const newWidth = this.startWidth + deltaX
        const maxWidth = Math.min(1200, window.innerWidth * 0.8)
        this.panelWidth = Math.max(320, Math.min(newWidth, maxWidth))
        this.rafId = null
      })
    },
    stopResize(e) {
      if (!this.isResizing) return
      e.preventDefault()

      this.isResizing = false

      if (this.rafId) {
        cancelAnimationFrame(this.rafId)
        this.rafId = null
      }

      window.removeEventListener('mousemove', this.handleResize)
      window.removeEventListener('mouseup', this.stopResize)

      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.body.style.pointerEvents = ''

      this.$emit('resizing', false)
    }
  },
  beforeUnmount() {
    if (this.isResizing) {
      this.stopResize({ preventDefault: () => {} })
    }
    if (this.rafId) {
      cancelAnimationFrame(this.rafId)
    }
  }
}
</script>

<style scoped>
.web-preview-panel {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  background: var(--bg-primary);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  z-index: 100;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.1);
  min-width: 320px;
  max-width: 1200px;
  will-change: width;
}

.resize-handle {
  position: absolute;
  left: -15px;
  top: 0;
  bottom: 0;
  width: 20px;
  cursor: ew-resize;
  z-index: 10;
  user-select: none;
}

.resize-handle::before {
  content: '';
  position: absolute;
  left: 15px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: transparent;
  transition: background 0.15s;
  pointer-events: none;
}

.resize-handle:hover::before {
  background: var(--button-bg);
  opacity: 0.4;
}

.resize-handle:active::before {
  background: var(--button-bg);
  opacity: 0.7;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.url-bar {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 5px 10px;
  min-width: 0;
}

.url-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.url-text {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.toolbar-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.tool-btn {
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.tool-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.iframe-container {
  flex: 1;
  position: relative;
  overflow: hidden;
}

iframe {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}

.iframe-loading,
.iframe-blocked {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  text-align: center;
  padding: 24px;
}

.loading-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--border-color);
  border-top-color: var(--button-bg);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.iframe-blocked svg {
  opacity: 0.4;
}

.iframe-blocked p {
  font-size: 14px;
  margin: 0;
}

.open-btn {
  margin-top: 4px;
  padding: 8px 20px;
  background: var(--button-bg);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
}

.open-btn:hover {
  background: var(--button-hover);
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.25s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>
