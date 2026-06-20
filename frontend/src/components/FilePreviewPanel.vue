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
          <!-- 编辑模式：只显示一个保存按钮 -->
          <template v-if="isEditing">
            <button @click="saveFile" class="tool-btn tool-btn-primary" title="保存">
              <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 21 6 20 7"/>
                <path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
              </svg>
            </button>
          </template>
          <!-- 非编辑模式 -->
          <template v-else>
            <button v-if="isEditableFile" @click="startEdit" class="tool-btn" title="编辑">
              <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
              </svg>
            </button>
            <button @click="reload" class="tool-btn" title="刷新">
              <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            </button>
            <button @click="downloadFile" class="tool-btn" title="下载">
              <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </button>
          </template>
          <button @click="isEditing ? cancelEdit() : $emit('close')" class="tool-btn" :title="isEditing ? '返回' : '关闭'">
            <svg v-if="isEditing" xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="19" y1="12" x2="5" y2="12"/>
              <polyline points="12 19 5 12 12 5"/>
            </svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="content-container">
        <!-- 可渲染文件（md/mmd）：Tab 切换 + 缩放控制 -->
        <div v-if="isRenderableFile && !isEditing" class="render-tabs">
          <button
            :class="['tab-btn', { active: viewTab === 'raw' }]"
            @click="viewTab = 'raw'"
          >原文</button>
          <button
            :class="['tab-btn', { active: viewTab === 'rendered' }]"
            @click="viewTab = 'rendered'"
          >渲染效果</button>
          <span class="zoom-controls" v-if="viewTab === 'rendered' && isMermaidFile">
            <button class="zoom-btn" @click="mermaidZoomScale = Math.max(0.3, mermaidZoomScale - 0.1)" title="缩小">−</button>
            <span class="zoom-label">{{ Math.round(mermaidZoomScale * 100) }}%</span>
            <button class="zoom-btn" @click="mermaidZoomScale = Math.min(3, mermaidZoomScale + 0.1)" title="放大">+</button>
            <button class="zoom-btn" @click="mermaidZoomScale = 1" title="重置">↺</button>
          </span>
        </div>

        <!-- 编辑模式：显示文本框 -->
        <div v-if="isEditing" class="edit-area">
          <textarea
            v-model="editedContent"
            class="edit-textarea"
            placeholder="编辑文件内容..."
            spellcheck="false"
          ></textarea>
        </div>

        <!-- 非编辑模式：显示内容 -->
        <div
          v-else-if="content"
          class="content-body"
          :class="{ 'mermaid-zoom-container': isMermaidFile && viewTab === 'rendered' }"
          :style="isMermaidFile && viewTab === 'rendered' ? { '--mermaid-scale': mermaidZoomScale } : {}"
          ref="mermaidContainer"
          @wheel.prevent="onMermaidWheel"
        >
          <div v-html="renderedContent"></div>
        </div>
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
    content: { type: String, default: '' },
    fileUrl: { type: String, default: '' },
    renderedSvg: { type: String, default: '' }
  },
  emits: ['close'],
  data() {
    return {
      panelWidth: 480,
      isResizing: false,
      startX: 0,
      startWidth: 0,
      viewTab: 'rendered',
      mermaidZoomScale: 1,
      isEditing: false,
      editedContent: ''
    }
  },
  watch: {
    visible(val) {
      if (val) {
        this.viewTab = 'rendered'
        this.mermaidZoomScale = 1
        this.isEditing = false
        this.editedContent = ''
      }
    }
  },
  methods: {
    onMermaidWheel(e) {
      const delta = e.deltaY > 0 ? -0.1 : 0.1
      this.mermaidZoomScale = Math.min(3, Math.max(0.3, this.mermaidZoomScale + delta))
    }
  },
  computed: {
    // 可渲染文件（md/mmd）：有渲染效果且支持原文/渲染切换
    isRenderableFile() {
      return this.isMarkdownFile || this.isMermaidFile
    },
    // 只有 .md / .markdown 走 marked 渲染
    isMarkdownFile() {
      const name = (this.fileName || '').toLowerCase()
      return name.endsWith('.md') || name.endsWith('.markdown')
    },
    isMermaidFile() {
      const name = (this.fileName || '').toLowerCase()
      return name.endsWith('.mmd')
    },
    // 可编辑文件：所有文本类文件（md, txt, mmd, py, json, csv, sh 等）
    isEditableFile() {
      const name = (this.fileName || '').toLowerCase()
      const editableExts = [
        '.md', '.markdown', '.mmd', '.txt', '.py', '.js', '.ts', '.json',
        '.csv', '.tsv', '.xml', '.yml', '.yaml', '.sh', '.bash', '.log',
        '.html', '.css', '.ini', '.toml', '.conf'
      ]
      return editableExts.some(ext => name.endsWith(ext))
    },
    renderedContent() {
      if (!this.content) return ''
      if (!this.isMarkdownFile && !this.isMermaidFile) {
        // 代码 / 纯文本：用 <pre> 保留换行和缩进，HTML 转义防注入
        return `<pre class="plain-text-content">${this.escapeHtml(this.content)}</pre>`
      }
      // 可渲染文件（md/mmd）支持原文 / 渲染切换
      if (this.viewTab === 'raw') {
        return `<pre class="plain-text-content">${this.escapeHtml(this.content)}</pre>`
      }
      if (this.isMermaidFile) {
        const svg = this.renderedSvg || '<p style="color:#888;">加载中...</p>'
        return `<div class="mermaid-zoom-inner">${svg}</div>`
      }
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
    startEdit() {
      this.editedContent = this.content
      this.isEditing = true
    },
    cancelEdit() {
      this.isEditing = false
      this.editedContent = ''
    },
    async saveFile() {
      if (!this.fileUrl) {
        console.warn('[FilePreviewPanel] 无文件URL，无法保存')
        return
      }
      try {
        const response = await fetch(this.fileUrl, {
          method: 'PUT',
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          body: this.editedContent
        })
        if (response.ok) {
          this.isEditing = false
          // 刷新内容
          this.$emit('reload')
        } else {
          console.error('[FilePreviewPanel] 保存失败:', response.status)
        }
      } catch (e) {
        console.error('[FilePreviewPanel] 保存异常:', e)
      }
    },
    downloadFile() {
      console.log('[FilePreviewPanel] fileUrl:', this.fileUrl)
      console.log('[FilePreviewPanel] fileName:', this.fileName)
      console.log('[FilePreviewPanel] content length:', this.content ? this.content.length : 0)
      if (!this.fileUrl) {
        console.warn('[FilePreviewPanel] 无下载URL')
        // 如果有 content 但没有 fileUrl，尝试用 content 作为 data URL 下载
        if (this.content && this.content.length > 0) {
          console.log('[FilePreviewPanel] 使用 content 作为下载数据')
        }
        return
      }
      const a = document.createElement('a')
      a.href = this.fileUrl
      a.download = this.fileName || 'download'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
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

.tool-btn-primary {
  background: var(--button-bg) !important;
  color: white !important;
}

.tool-btn-primary:hover {
  background: var(--button-hover) !important;
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

/* 纯文本/代码文件预览：无 Markdown 渲染，等宽字体、保留缩进换行 */
.content-body :deep(pre.plain-text-content) {
  background: var(--code-block-bg);
  padding: 16px;
  border-radius: 8px;
  border: 1px solid var(--code-block-border);
  font-family: 'SF Mono', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: var(--code-block-text);
  white-space: pre;
  overflow-x: auto;
  margin: 0;
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

/* Mermaid 文件预览 */
.render-tabs {
  display: flex;
  gap: 4px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 12px;
  flex-shrink: 0;
}

.render-tabs .tab-btn {
  padding: 5px 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.render-tabs .tab-btn:hover {
  background: var(--bg-hover);
}

.render-tabs .tab-btn.active {
  background: var(--button-bg);
  color: white;
  border-color: var(--button-bg);
}

.zoom-controls {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

.content-body :deep(.mermaid-zoom-inner) {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  width: 100%;
  padding: 8px 0;
}

.content-body :deep(.mermaid-zoom-inner svg) {
  max-width: 100%;
  max-height: 400px;
  height: auto;
  cursor: grab;
}

.content-body :deep(.mermaid-zoom-inner svg:active) {
  cursor: grabbing;
}

.content-body :deep(.plain-text-content) {
  margin: 0;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* 编辑区域 */
.edit-area {
  width: 100%;
  height: 100%;
  display: flex;
}

.edit-textarea {
  width: 100%;
  height: 100%;
  min-height: 300px;
  padding: 12px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  resize: both;
  box-sizing: border-box;
}

.edit-textarea:focus {
  outline: none;
  border-color: var(--button-bg);
}

.zoom-btn {
  width: 24px;
  height: 24px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.zoom-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.zoom-label {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 40px;
  text-align: center;
}

/* Mermaid 渲染缩放（滚轮或按钮控制） */
.content-body.mermaid-zoom-container {
  overflow: auto;
  padding: 8px;
}

.content-body.mermaid-zoom-container :deep(.mermaid-zoom-inner) {
  display: flex;
  justify-content: center;
}

.content-body.mermaid-zoom-container :deep(svg) {
  width: calc(var(--mermaid-scale, 1) * 100%);
  max-width: none;
  height: auto;
  cursor: grab;
  transition: width 0.1s ease;
}

.content-body.mermaid-zoom-container :deep(svg:active) {
  cursor: grabbing;
}
</style>
