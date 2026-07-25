<template>
  <div class="preview-tab-pane">
    <div class="panel-toolbar">
      <div class="file-info">
        <svg class="file-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <span class="file-name" :title="tab.name">{{ tab.name }}</span>
      </div>
      <div class="toolbar-actions">
        <button
          v-if="sessionId"
          @click.stop="$emit('toggle-file-tree')"
          class="tool-btn"
          :class="{ active: showFileTree }"
          title="文件列表"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3h18v4H3z"/>
            <path d="M3 11h18v4H3z"/>
            <path d="M3 19h18v2H3z"/>
          </svg>
        </button>
        <template v-if="isEditing">
          <button @click="saveFile" class="tool-btn tool-btn-primary" title="保存">
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 21 6 20 7"/>
              <path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
            </svg>
          </button>
        </template>
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
        <button @click="isEditing ? cancelEdit() : $emit('close-panel')" class="tool-btn" :title="isEditing ? '返回' : '关闭'">
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

    <div class="content-container" ref="contentContainer">
      <div v-if="displayTruncation" class="truncation-notice">
        <span>内容超过 2 MiB，仅显示前 2 MiB；请下载查看完整文件。截断预览不可编辑。</span>
        <button @click="downloadFile">下载完整文件</button>
      </div>

      <div v-if="isRenderableFile && !isEditing" class="render-tabs">
        <button :class="['tab-btn', { active: viewTab === 'raw' }]" @click="viewTab = 'raw'">原文</button>
        <button :class="['tab-btn', { active: viewTab === 'rendered' }]" @click="viewTab = 'rendered'">渲染效果</button>
        <span class="zoom-controls" v-if="viewTab === 'rendered' && isMermaidFile">
          <button class="zoom-btn" @click="mermaidZoomScale = Math.max(0.3, mermaidZoomScale - 0.1)" title="缩小">−</button>
          <span class="zoom-label">{{ Math.round(mermaidZoomScale * 100) }}%</span>
          <button class="zoom-btn" @click="mermaidZoomScale = Math.min(3, mermaidZoomScale + 0.1)" title="放大">+</button>
          <button class="zoom-btn" @click="mermaidZoomScale = 1" title="重置">↺</button>
        </span>
      </div>

      <div v-if="tab.loading" class="loading-hint">加载中…</div>
      <div v-else-if="tab.error" class="error-hint">[加载失败] {{ tab.error }}</div>
      <div v-else-if="isEditing" class="edit-area">
        <textarea v-model="editedContent" class="edit-textarea" placeholder="编辑文件内容..." spellcheck="false"></textarea>
      </div>
      <div v-else-if="isImageFile" class="content-body image-preview">
        <img :src="tab.url" :alt="tab.name" />
      </div>
      <div v-else-if="isHtmlFile" class="html-render-area">
        <iframe
          v-show="viewTab === 'rendered'"
          :key="tab.url || 'no-url'"
          :src="tab.url || 'about:blank'"
          class="html-preview-iframe"
          sandbox="allow-scripts allow-popups allow-same-origin"
          referrerpolicy="no-referrer"
        />
        <div v-show="viewTab === 'raw'" class="content-body html-raw-content">
          <pre v-if="htmlRawDisplay" class="plain-text-content">{{ htmlRawDisplay }}</pre>
          <div v-else-if="htmlRawLoading" class="loading-hint">加载中…</div>
          <div v-else-if="htmlRawError" class="error-hint">[加载失败] {{ htmlRawError }}</div>
          <div v-else class="content-empty"><p>暂无内容</p></div>
        </div>
      </div>
      <div
        v-else-if="tab.content"
        class="content-body"
        :class="{ 'mermaid-zoom-container': isMermaidFile && viewTab === 'rendered' }"
        :style="isMermaidFile && viewTab === 'rendered' ? { '--mermaid-scale': mermaidZoomScale } : {}"
        @wheel="onWheel"
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
  </div>
</template>

<script>
import { marked } from 'marked'
import { sanitizeHtml, passthroughTrustedSvg } from '@/utils/sanitize.js'
import { fetchTextPreview } from '@/utils/filePreview.js'

export default {
  name: 'FilePreviewTabPane',
  props: {
    tab: { type: Object, required: true },
    sessionId: { type: String, default: '' },
    showFileTree: { type: Boolean, default: false }
  },
  emits: ['close-panel', 'toggle-file-tree', 'reload'],
  data() {
    return {
      viewTab: 'rendered',
      mermaidZoomScale: 1,
      isEditing: false,
      editedContent: '',
      htmlRawContent: '',
      htmlRawLoading: false,
      htmlRawError: '',
      htmlRawTruncated: false,
      htmlRawController: null
    }
  },
  computed: {
    suffix() {
      return String(this.tab.suffix || '').toLowerCase()
    },
    isMarkdownFile() {
      return this.suffix === '.md' || this.suffix === '.markdown'
    },
    isMermaidFile() {
      return this.suffix === '.mmd'
    },
    isHtmlFile() {
      return this.tab.kind === 'html' || this.suffix === '.html' || this.suffix === '.htm'
    },
    isImageFile() {
      return this.tab.kind === 'image' || ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'].includes(this.suffix)
    },
    isRenderableFile() {
      return this.isMarkdownFile || this.isMermaidFile || this.isHtmlFile
    },
    displayTruncation() {
      return !!this.tab.truncated || (this.isHtmlFile && this.viewTab === 'raw' && this.htmlRawTruncated)
    },
    isEditableFile() {
      if (this.tab.truncated || this.htmlRawTruncated) return false
      const editableExts = [
        '.md', '.markdown', '.mmd', '.txt', '.py', '.js', '.ts', '.json',
        '.csv', '.tsv', '.xml', '.yml', '.yaml', '.sh', '.bash', '.log',
        '.html', '.css', '.ini', '.toml', '.conf'
      ]
      return editableExts.includes(this.suffix)
    },
    htmlRawDisplay() {
      return this.tab.content || this.htmlRawContent || ''
    },
    renderedContent() {
      if (!this.tab.content) return ''
      if (!this.isMarkdownFile && !this.isMermaidFile) {
        return `<pre class="plain-text-content">${this.escapeHtml(this.tab.content)}</pre>`
      }
      if (this.viewTab === 'raw') {
        return `<pre class="plain-text-content">${this.escapeHtml(this.tab.content)}</pre>`
      }
      if (this.isMermaidFile) {
        const svg = this.tab.renderedSvg || '<p style="color:#888;">加载中...</p>'
        return passthroughTrustedSvg(`<div class="mermaid-zoom-inner">${svg}</div>`)
      }
      try {
        return sanitizeHtml(marked(this.tab.content))
      } catch (e) {
        console.warn('Markdown 渲染失败:', e)
        return this.escapeHtml(this.tab.content)
      }
    }
  },
  watch: {
    viewTab(value) {
      if (value === 'raw' && this.isHtmlFile && !this.tab.content && !this.htmlRawContent && !this.htmlRawLoading && this.tab.url) {
        this.loadHtmlRawContent()
      }
    }
  },
  methods: {
    onWheel(e) {
      if (this.isMermaidFile && this.viewTab === 'rendered') {
        e.preventDefault()
        const delta = e.deltaY > 0 ? -0.1 : 0.1
        this.mermaidZoomScale = Math.min(3, Math.max(0.3, this.mermaidZoomScale + delta))
      }
    },
    escapeHtml(text) {
      const div = document.createElement('div')
      div.textContent = text
      return div.innerHTML
    },
    async loadHtmlRawContent() {
      this.htmlRawController?.abort()
      this.htmlRawController = new AbortController()
      this.htmlRawLoading = true
      this.htmlRawError = ''
      try {
        const result = await fetchTextPreview(this.tab.url, {
          signal: this.htmlRawController.signal,
          sizeHint: this.tab.size || 0
        })
        this.htmlRawContent = result.text
        this.htmlRawTruncated = result.truncated
      } catch (e) {
        if (e?.name !== 'AbortError') {
          this.htmlRawError = e?.message || String(e)
        }
      } finally {
        this.htmlRawLoading = false
      }
    },
    startEdit() {
      if (!this.isEditableFile) return
      this.editedContent = this.tab.content
      this.isEditing = true
    },
    cancelEdit() {
      this.isEditing = false
      this.editedContent = ''
    },
    async saveFile() {
      if (!this.tab.url || !this.isEditableFile) return
      try {
        const response = await fetch(this.tab.url, {
          method: 'PUT',
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          body: this.editedContent
        })
        if (!response.ok) {
          console.error('[FilePreviewTabPane] 保存失败:', response.status)
          return
        }
        this.isEditing = false
        this.$emit('reload', this.tab.id)
      } catch (e) {
        console.error('[FilePreviewTabPane] 保存异常:', e)
      }
    },
    reload() {
      this.htmlRawController?.abort()
      this.htmlRawContent = ''
      this.htmlRawError = ''
      this.htmlRawTruncated = false
      this.$emit('reload', this.tab.id)
    },
    downloadFile() {
      if (!this.tab.url) return
      if (this.isMermaidFile && this.viewTab === 'rendered' && this.tab.renderedSvg) {
        const baseName = (this.tab.name || 'diagram').replace(/\.mmd$/i, '')
        const blob = new Blob([this.tab.renderedSvg], { type: 'image/svg+xml;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${baseName}.svg`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        return
      }
      const a = document.createElement('a')
      a.href = this.tab.url
      a.download = this.tab.name || 'download'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    }
  },
  beforeUnmount() {
    this.htmlRawController?.abort()
  }
}
</script>

<style scoped>
.preview-tab-pane { height: 100%; min-height: 0; display: flex; flex-direction: column; }
.panel-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-bottom: 1px solid var(--border-color); background: var(--bg-secondary); flex-shrink: 0; }
.file-info { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; }
.file-icon { color: var(--button-bg); flex-shrink: 0; }
.file-name { font-size: 14px; font-weight: 500; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.toolbar-actions { display: flex; gap: 2px; flex-shrink: 0; }
.tool-btn { width: 32px; height: 32px; border: none; background: transparent; color: var(--text-secondary); border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.15s, color 0.15s; }
.tool-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.tool-btn.active, .tool-btn-primary { background: var(--button-bg); color: #fff; }
.content-container { flex: 1 1 0; overflow-y: auto; overflow-x: hidden; padding: 16px; min-height: 0; position: relative; -webkit-overflow-scrolling: touch; scrollbar-gutter: stable; }
.content-container::-webkit-scrollbar { width: 8px; }
.content-container::-webkit-scrollbar-track { background: transparent; }
.content-container::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.18); border-radius: 4px; }
:global(.dark-theme) .content-container::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.18); }
.truncation-notice { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; padding: 9px 12px; border: 1px solid #f59e0b; border-radius: 6px; color: #92400e; background: rgba(245, 158, 11, 0.12); font-size: 12px; }
.truncation-notice button { flex-shrink: 0; border: none; background: transparent; color: var(--button-bg); cursor: pointer; font-weight: 500; }
.content-body { font-size: 14px; line-height: 1.7; color: var(--text-primary); word-wrap: break-word; overflow-wrap: anywhere; min-height: 0; width: 100%; max-width: 100%; box-sizing: border-box; }
.content-body.image-preview { display: flex; align-items: center; justify-content: center; padding: 12px; background: var(--bg-secondary, #f9fafb); }
.content-body.image-preview img { max-width: 100%; max-height: 70vh; object-fit: contain; border-radius: 4px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08); }
.html-render-area { position: relative; width: 100%; height: calc(100vh - 150px); overflow: hidden; isolation: isolate; contain: layout paint style; }
.html-preview-iframe { display: block; width: 100%; height: 100%; border: none; border-radius: 6px; background: var(--bg-primary); transform: translateZ(0); }
.html-raw-content { width: 100%; height: 100%; overflow-y: auto; overflow-x: hidden; box-sizing: border-box; }
.loading-hint, .error-hint { padding: 24px; text-align: center; color: var(--text-secondary); font-size: 13px; }
.error-hint { color: #d9534f; }
.content-body :deep(h1) { font-size: 1.6em; font-weight: 700; margin: 24px 0 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border-color); }
.content-body :deep(h2) { font-size: 1.4em; font-weight: 600; margin: 20px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border-color); }
.content-body :deep(h3) { font-size: 1.2em; font-weight: 600; margin: 16px 0 10px; }
.content-body :deep(h4), .content-body :deep(h5), .content-body :deep(h6) { font-size: 1em; font-weight: 600; margin: 12px 0 8px; }
.content-body :deep(p) { margin: 12px 0; }
.content-body :deep(strong), .content-body :deep(b) { font-weight: 700; color: var(--text-primary); }
.content-body :deep(code) { background: var(--code-inline-bg); padding: 2px 6px; border-radius: 4px; font-family: 'SF Mono', 'Monaco', 'Consolas', monospace; font-size: 0.9em; color: var(--code-inline-color); }
.content-body :deep(pre) { background: var(--code-block-bg); padding: 16px; border-radius: 8px; overflow-x: auto; margin: 16px 0; border: 1px solid var(--code-block-border); }
.content-body :deep(pre.plain-text-content) { font-family: 'SF Mono', 'Monaco', 'Consolas', monospace; font-size: 13px; line-height: 1.6; color: var(--code-block-text); white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; margin: 0; max-width: 100%; }
.content-body :deep(pre code) { background: transparent; padding: 0; font-size: 13px; color: var(--code-block-text); }
.content-body :deep(ul), .content-body :deep(ol) { margin: 12px 0; padding-left: 24px; }
.content-body :deep(blockquote) { border-left: 4px solid var(--button-bg); padding: 12px 16px; margin: 16px 0; color: var(--text-secondary); background: var(--bg-secondary); border-radius: 0 6px 6px 0; }
.content-body :deep(a) { color: var(--button-bg); text-decoration: none; }
.content-body :deep(table) { border-collapse: collapse; width: 100%; margin: 16px 0; overflow-x: auto; display: block; }
.content-body :deep(th), .content-body :deep(td) { border: 1px solid var(--border-color); padding: 10px 14px; text-align: left; }
.content-body :deep(th), .content-body :deep(tr:nth-child(even)) { background: var(--bg-secondary); }
.content-body :deep(img) { max-width: 100%; height: auto; border-radius: 6px; margin: 12px 0; }
.content-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-secondary); gap: 12px; }
.content-empty svg { opacity: 0.3; }
.content-empty p { font-size: 14px; margin: 0; }
.render-tabs { display: flex; gap: 4px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color); margin-bottom: 12px; flex-shrink: 0; }
.render-tabs .tab-btn { padding: 5px 14px; border: 1px solid var(--border-color); background: var(--bg-secondary); color: var(--text-secondary); border-radius: 6px; cursor: pointer; font-size: 13px; }
.render-tabs .tab-btn.active { background: var(--button-bg); color: white; border-color: var(--button-bg); }
.zoom-controls { display: flex; align-items: center; gap: 4px; margin-left: auto; }
.zoom-btn { width: 24px; height: 24px; border: 1px solid var(--border-color); background: var(--bg-secondary); color: var(--text-secondary); border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.zoom-label { font-size: 12px; color: var(--text-secondary); min-width: 40px; text-align: center; }
.content-body :deep(.mermaid-zoom-inner) { display: flex; justify-content: center; width: 100%; padding: 8px 0; }
.content-body.mermaid-zoom-container { overflow: auto; padding: 8px; }
.content-body.mermaid-zoom-container :deep(svg) { width: calc(var(--mermaid-scale, 1) * 100%); max-width: none; height: auto; cursor: grab; transition: width 0.1s ease; }
.edit-area { width: 100%; height: 100%; display: flex; }
.edit-textarea { width: 100%; height: 100%; min-height: 300px; padding: 12px; background: var(--bg-secondary); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 8px; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.6; resize: both; box-sizing: border-box; }
.edit-textarea:focus { outline: none; border-color: var(--button-bg); }
</style>
