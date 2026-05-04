<template>
  <transition name="slide">
    <aside v-if="visible" class="file-preview-panel" :style="{ width: panelWidth + 'px' }">
      <!-- 拖拽调整宽度的手柄 -->
      <div class="resize-handle" @mousedown="startResize"></div>

      <!-- 顶栏 -->
      <div class="panel-toolbar">
        <div class="file-info">
          <svg class="file-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <span class="file-name" :title="fileName">{{ fileName }}</span>
        </div>
        <div class="toolbar-actions">
          <button @click="reload" class="tool-btn" title="刷新">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="23 4 23 10 17 10"/>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
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

      <!-- 内容区域 -->
      <div class="content-container">
        <div
          v-if="content"
          class="content-body"
          v-html="renderedContent"
        ></div>
        <div v-else class="content-empty">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <p>暂无内容</p>
        </div>
      </div>
    </aside>
  </transition>
</template>

<script>
import { marked } from 'marked'
import hljs from 'highlight.js'

export default {
  name: 'FilePreviewPanel',
  props: {
    visible: { type: Boolean, default: false },
    fileName: { type: String, default: '' },
    content: { type: String, default: '' }
  },
  emits: ['close'],
  data() {
    return {
      panelWidth: 480,
      isResizing: false,
      startX: 0,
      startWidth: 0
    }
  },
  computed: {
    renderedContent() {
      if (!this.content) return ''
      try {
        return marked(this.content)
      } catch (e) {
        console.warn('Markdown 渲染失败:', e)
        return this.escapeHtml(this.content)
      }
    }
  },
  methods: {
    escapeHtml(text) {
      const div = document.createElement('div')
      div.textContent = text
      return div.innerHTML
    },
    reload() {
      // 强制重新渲染
      this.$forceUpdate()
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
    },
    handleResize(e) {
      if (!this.isResizing) return
      const deltaX = this.startX - e.clientX
      const newWidth = this.startWidth + deltaX
      const maxWidth = Math.min(800, window.innerWidth * 0.6)
      this.panelWidth = Math.max(320, Math.min(newWidth, maxWidth))
    },
    stopResize(e) {
      if (!this.isResizing) return
      e.preventDefault()
      this.isResizing = false
      window.removeEventListener('mousemove', this.handleResize)
      window.removeEventListener('mouseup', this.stopResize)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.body.style.pointerEvents = ''
    }
  }
}
</script>

<style scoped>
.file-preview-panel {
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
  max-width: 800px;
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
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.file-icon {
  color: var(--button-bg);
  flex-shrink: 0;
}

.file-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
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
  width: 32px;
  height: 32px;
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

.content-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.content-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  word-wrap: break-word;
}

/* Markdown 样式 */
.content-body :deep(h1) {
  font-size: 1.6em;
  font-weight: 700;
  margin: 24px 0 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.content-body :deep(h2) {
  font-size: 1.4em;
  font-weight: 600;
  margin: 20px 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-color);
}

.content-body :deep(h3) {
  font-size: 1.2em;
  font-weight: 600;
  margin: 16px 0 10px;
}

.content-body :deep(h4),
.content-body :deep(h5),
.content-body :deep(h6) {
  font-size: 1em;
  font-weight: 600;
  margin: 12px 0 8px;
}

.content-body :deep(p) {
  margin: 12px 0;
}

.content-body :deep(strong),
.content-body :deep(b) {
  font-weight: 700;
  color: var(--text-primary);
}

.content-body :deep(em),
.content-body :deep(i) {
  font-style: italic;
}

.content-body :deep(code) {
  background: var(--code-inline-bg);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.9em;
  color: var(--code-inline-color);
}

.content-body :deep(pre) {
  background: var(--code-block-bg);
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 16px 0;
  border: 1px solid var(--code-block-border);
}

.content-body :deep(pre code) {
  background: transparent;
  padding: 0;
  font-size: 13px;
  color: var(--code-block-text);
  line-height: 1.6;
}

.content-body :deep(ul),
.content-body :deep(ol) {
  margin: 12px 0;
  padding-left: 24px;
}

.content-body :deep(ul) {
  list-style-type: disc;
}

.content-body :deep(ol) {
  list-style-type: decimal;
}

.content-body :deep(li) {
  margin: 6px 0;
}

.content-body :deep(blockquote) {
  border-left: 4px solid var(--button-bg);
  padding: 12px 16px;
  margin: 16px 0;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border-radius: 0 6px 6px 0;
}

.content-body :deep(blockquote p) {
  margin: 0;
}

.content-body :deep(a) {
  color: var(--button-bg);
  text-decoration: none;
}

.content-body :deep(a:hover) {
  text-decoration: underline;
}

.content-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 16px 0;
  overflow-x: auto;
  display: block;
}

.content-body :deep(th),
.content-body :deep(td) {
  border: 1px solid var(--border-color);
  padding: 10px 14px;
  text-align: left;
}

.content-body :deep(th) {
  background: var(--bg-secondary);
  font-weight: 700;
}

.content-body :deep(tr:nth-child(even)) {
  background: var(--bg-secondary);
}

.content-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-color);
  margin: 24px 0;
}

.content-body :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
  margin: 12px 0;
}

.content-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
  gap: 12px;
}

.content-empty svg {
  opacity: 0.3;
}

.content-empty p {
  font-size: 14px;
  margin: 0;
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
