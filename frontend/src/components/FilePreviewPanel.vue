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
          <!-- 文件列表切换：仅在有 session 时显示 -->
          <button
            v-if="sessionId"
            @click.stop="toggleFileTree"
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
        <!-- 内部文件树浮层下拉（toggleable） -->
        <transition name="tree-fade">
          <div v-if="showFileTree" ref="innerFileTree" class="inner-file-tree" @click.stop>
            <div class="inner-tree-header">
              <span class="inner-tree-title">📁 文件列表</span>
              <button class="tool-btn tool-btn-mini" @click="showFileTree = false" title="关闭">×</button>
            </div>
            <div class="inner-tree-body">
              <div v-if="treeLoading" class="inner-tree-empty">加载中…</div>
              <div v-else-if="!treeRootNode || !treeRootNode.children || treeRootNode.children.length === 0" class="inner-tree-empty">
                暂无文件
              </div>
              <div v-else class="inner-tree-list">
                <div
                  v-for="child in treeRootChildren"
                  :key="child.name + '_' + child.type"
                >
                  <DataTreeNode
                    :node="child"
                    :depth="0"
                    @file-click="onInnerFileClick"
                  />
                </div>
              </div>
            </div>
          </div>
        </transition>
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

        <!-- 图片：直接渲染（不取文本，避免把二进制塞 content） -->
        <div
          v-else-if="isImageFile"
          class="content-body image-preview"
        >
          <img :src="fileUrl" :alt="fileName" />
        </div>

        <!-- HTML 文件：原文 / 渲染 tab 切换（v-show 替代 v-if 链，避免 Vue 在不同元素类型上 v-if/v-else-if 的边界情况） -->
        <div v-if="isHtmlFile" class="html-render-area">
          <!-- 渲染效果 tab：iframe 始终在 DOM，v-show 控制可见性 -->
          <iframe
            v-show="viewTab === 'rendered'"
            :key="fileUrl || 'no-url'"
            :src="fileUrl || 'about:blank'"
            class="html-preview-iframe"
            sandbox="allow-scripts allow-popups allow-same-origin"
            referrerpolicy="no-referrer"
          />
          <!-- 原文 tab：v-show 控制可见性 -->
          <div v-show="viewTab === 'raw'" class="content-body html-raw-content">
            <pre v-if="htmlRawDisplay" class="plain-text-content">{{ htmlRawDisplay }}</pre>
            <div v-else-if="htmlRawLoading" class="loading-hint">加载中…</div>
            <div v-else-if="htmlRawError" class="error-hint">[加载失败] {{ htmlRawError }}</div>
            <div v-else class="content-empty">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
              <p>暂无内容</p>
            </div>
          </div>
        </div>

        <!-- 非编辑模式：显示内容 -->
        <div
          v-else-if="content"
          class="content-body"
          :class="{ 'mermaid-zoom-container': isMermaidFile && viewTab === 'rendered' }"
          :style="isMermaidFile && viewTab === 'rendered' ? { '--mermaid-scale': mermaidZoomScale } : {}"
          ref="mermaidContainer"
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
    </aside>
  </transition>
</template>

<script>
import { marked } from 'marked'
import hljs from 'highlight.js'
import { sanitizeHtml, passthroughTrustedSvg } from '@/utils/sanitize.js'
import DataTreeNode from './DataTreeNode.vue'

export default {
  name: 'FilePreviewPanel',
  components: { DataTreeNode },
  props: {
    visible: { type: Boolean, default: false },
    fileName: { type: String, default: '' },
    content: { type: String, default: '' },
    fileUrl: { type: String, default: '' },
    renderedSvg: { type: String, default: '' },
    sessionId: { type: String, default: '' }
  },
  emits: ['close', 'file-select'],
  data() {
    return {
      panelWidth: 480,
      isResizing: false,
      startX: 0,
      startWidth: 0,
      viewTab: 'rendered',
      mermaidZoomScale: 1,
      isEditing: false,
      editedContent: '',
      // 内部文件树
      showFileTree: false,
      treeFiles: [],
      treeRootPath: '',
      treeRootNode: null,
      treeLoading: false,
      // HTML 原文 tab 异步加载状态（仅在 content 为空且 viewTab='raw' 时启用）
      htmlRawContent: '',
      htmlRawLoading: false,
      htmlRawError: ''
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
    },
    // HTML 文件切换时，清掉上一份 HTML 原文缓存，并强制回到渲染效果 tab
    // （防止用户先前停在「原文」tab、切新文件后看不到 iframe）
    fileName() {
      if (this.isHtmlFile) {
        this.viewTab = 'rendered'
        this.htmlRawContent = ''
        this.htmlRawError = ''
      }
    },
    // 用户切到 HTML「原文」tab 且没拿到 content 时，按需 fetch fileUrl
    viewTab(val) {
      if (val === 'raw' && this.isHtmlFile && !this.content && !this.htmlRawContent && !this.htmlRawLoading && this.fileUrl) {
        this.loadHtmlRawContent()
      }
    },
    sessionId: {
      immediate: false,
      handler(newVal) {
        // 切换会话时重置内部文件树状态
        if (newVal) {
          this.showFileTree = false
          this.treeFiles = []
          this.treeRootNode = null
        }
      }
    }
  },
  computed: {
    // 内部文件树根节点的 children（按目录优先 + 字典序排序）
    treeRootChildren() {
      if (!this.treeRootNode || !this.treeRootNode.children) return []
      return [...this.treeRootNode.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    },
    // 可渲染文件（md/mmd/html）：有渲染效果且支持原文/渲染切换
    isRenderableFile() {
      return this.isMarkdownFile || this.isMermaidFile || this.isHtmlFile
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
    // HTML 文件：原文 + 渲染效果（iframe 跑 Plotly/ECharts 等）
    isHtmlFile() {
      const name = (this.fileName || '').toLowerCase()
      return name.endsWith('.html') || name.endsWith('.htm')
    },
    isImageFile() {
      const name = (this.fileName || '').toLowerCase()
      return /\.(png|jpe?g|gif|webp|svg)$/.test(name)
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
        // mermaid SVG 走 trusted 库输出路径：DOMPurify 会剥 <foreignObject> 内容破坏图渲染
        // 安全前提：prop renderedSvg 由 mermaid.render() 生成，library 解析阶段已拒绝恶意标签
        return passthroughTrustedSvg(`<div class="mermaid-zoom-inner">${svg}</div>`)
      }
      try {
        // v-html 注入前过 DOMPurify（挡 <script>、内联事件；iframe 强制 sandbox）
        return sanitizeHtml(marked(this.content))
      } catch (e) {
        console.warn('Markdown 渲染失败:', e)
        return this.escapeHtml(this.content)
      }
    },
    // HTML「原文」tab 用的显示文本：优先 content prop，否则用 fetch 缓存的 htmlRawContent
    htmlRawDisplay() {
      return this.content || this.htmlRawContent || ''
    }
  },
  methods: {
    // 只有 mermaid 渲染态才拦截滚轮做缩放；其他情况让滚轮正常滚动 .content-container
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
    // HTML 原文 fetch：处理 [[xxx.html]] inline 渲染后用户点开 panel 但 App.vue 没传 text_content 的场景
    async loadHtmlRawContent() {
      if (!this.fileUrl) {
        this.htmlRawError = '无文件 URL'
        return
      }
      // data: URL 同步解码
      if (this.fileUrl.startsWith('data:text/html')) {
        try {
          const idx = this.fileUrl.indexOf(',')
          if (idx < 0) {
            this.htmlRawError = 'data: URL 格式错误'
            return
          }
          const meta = this.fileUrl.slice(0, idx)
          const payload = this.fileUrl.slice(idx + 1)
          if (meta.includes(';base64')) {
            const bin = atob(payload)
            const bytes = new Uint8Array(bin.length)
            for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
            this.htmlRawContent = new TextDecoder('utf-8').decode(bytes)
          } else {
            this.htmlRawContent = decodeURIComponent(payload)
          }
        } catch (e) {
          this.htmlRawError = (e && e.message) || String(e)
        }
        return
      }
      this.htmlRawLoading = true
      this.htmlRawError = ''
      try {
        const resp = await fetch(this.fileUrl)
        if (!resp.ok) throw new Error('HTTP ' + resp.status)
        this.htmlRawContent = await resp.text()
      } catch (e) {
        console.warn('[FilePreviewPanel] fetch HTML 原文失败:', e)
        this.htmlRawError = (e && e.message) || String(e)
      } finally {
        this.htmlRawLoading = false
      }
    },
    async toggleFileTree() {
      this.showFileTree = !this.showFileTree
      if (this.showFileTree && (!this.treeRootNode || this.treeFiles.length === 0)) {
        await this.loadFileTree()
      }
    },
    async loadFileTree() {
      if (!this.sessionId) return
      this.treeLoading = true
      try {
        const resp = await fetch(`/chat/${this.sessionId}/data-analysis/tree`)
        if (!resp.ok) {
          this.treeFiles = []
          this.treeRootNode = null
          return
        }
        const data = await resp.json()
        this.treeRootPath = data.root_path || ''
        this.treeFiles = data.files || []
        this.buildTreeNode()
      } catch (e) {
        console.error('[FilePreviewPanel] loadFileTree failed:', e)
        this.treeFiles = []
        this.treeRootNode = null
      } finally {
        this.treeLoading = false
      }
    },
    buildTreeNode() {
      const root = { name: 'data_analysis', type: 'directory', children: [] }
      const basePrefix = this.treeRootPath.endsWith('/') ? this.treeRootPath : this.treeRootPath + '/'
      for (const file of this.treeFiles) {
        const rel = file.path.startsWith(basePrefix)
          ? file.path.slice(basePrefix.length)
          : file.path
        const parts = rel.split('/').filter(Boolean)
        if (parts.length === 0) continue
        let current = root
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i]
          const isFile = i === parts.length - 1
          if (isFile) {
            current.children.push({
              name: part,
              type: 'file',
              path: file.path,
              size: file.size,
              modified_at: file.modified_at
            })
          } else {
            let dir = current.children.find(c => c.name === part && c.type === 'directory')
            if (!dir) {
              dir = { name: part, type: 'directory', children: [] }
              current.children.push(dir)
            }
            current = dir
          }
        }
      }
      this.treeRootNode = root
    },
    onInnerFileClick(node) {
      // 内部文件树点击：保持侧栏打开，方便连续切换预览文件
      this.$emit('file-select', node)
    },
    onInnerTreeOutsideClick(e) {
      if (!this.showFileTree) return
      const tree = this.$refs.innerFileTree
      if (tree && tree.contains(e.target)) return
      this.showFileTree = false
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
      // mermaid 文件的"渲染效果"tab：下载渲染后的 SVG（而不是源 .mmd 文本）
      if (this.isMermaidFile && this.viewTab === 'rendered' && this.renderedSvg) {
        const baseName = (this.fileName || 'diagram').replace(/\.mmd$/i, '')
        const blob = new Blob([this.renderedSvg], { type: 'image/svg+xml;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = baseName + '.svg'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        return
      }

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
  },
  mounted() {
    document.addEventListener('click', this.onInnerTreeOutsideClick)
  },
  beforeUnmount() {
    document.removeEventListener('click', this.onInnerTreeOutsideClick)
  }
}
</script>

<style scoped>
.file-preview-panel {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  height: 100vh;
  background: var(--bg-primary);
  border-left: 1px solid var(--border-color);
  z-index: 100;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.1);
  min-width: 320px;
  max-width: 800px;
  will-change: width;
  display: flex;
  flex-direction: column;
  overflow: hidden;
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
.tool-btn.active {
  background: var(--button-bg);
  color: #fff;
}
.tool-btn-mini {
  width: 22px;
  height: 22px;
  font-size: 14px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.tool-btn-mini:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* 内部文件树浮层（从 content-container 顶部展开的下拉菜单） */
.inner-file-tree {
  position: absolute;
  top: 12px;
  left: 12px;
  width: 320px;
  max-width: calc(100% - 24px);
  max-height: 60vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  z-index: 20;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.inner-tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}
.inner-tree-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}
.inner-tree-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.inner-tree-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 12px;
}
.inner-tree-list {
  font-size: 12.5px;
}
.tree-fade-enter-active,
.tree-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.tree-fade-enter-from,
.tree-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.tool-btn-primary {
  background: var(--button-bg) !important;
  color: white !important;
}

.tool-btn-primary:hover {
  background: var(--button-hover) !important;
}

.content-container {
  flex: 1 1 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px;
  min-height: 0;
  position: relative;
  /* 显式约束高度，overflow 滚动一定生效，不依赖 flex 传递 */
  height: calc(100vh - 64px);
  -webkit-overflow-scrolling: touch;
  /* 让滚动条常驻可见，macOS overlay 模式下用户感知不到能滚动 */
  scrollbar-gutter: stable;
}
.content-container::-webkit-scrollbar {
  width: 8px;
}
.content-container::-webkit-scrollbar-track {
  background: transparent;
}
.content-container::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.18);
  border-radius: 4px;
}
.content-container::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.32);
}
/* 深色主题 */
:global(.dark-theme) .content-container::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
}
:global(.dark-theme) .content-container::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.32);
}

.content-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  word-wrap: break-word;
  overflow-wrap: anywhere;
  min-height: 0;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.content-body.image-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  background: var(--bg-secondary, #f9fafb);
}
.content-body.image-preview img {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

/* HTML 渲染：把渲染/原文两个区域统一在一个 fixed-height 容器里切显示，避免互相 reflow。
   contain: layout paint style 让 iframe 的内部绘制不冒泡到祖先（少一次 paint pass） */
.html-render-area {
  position: relative;
  display: block;
  width: 100%;
  /* 撑满 content-container 的可视高度：减掉顶栏(64) + tabs(56) + content-container padding(32) */
  height: calc(100vh - 64px - 56px - 32px);
  overflow: hidden;
  isolation: isolate;
  contain: layout paint style;
}
.html-preview-iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 6px;
  background: var(--bg-primary);
  /* GPU compositor：v-show 切显示时不需要重新 paint ancestor */
  transform: translateZ(0);
}
.html-raw-content {
  /* 撑满父区域；超过就内部滚动 */
  width: 100%;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  box-sizing: border-box;
}
.html-raw-content pre.plain-text-content {
  width: 100%;
  margin: 0;
}
.loading-hint,
.error-hint {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}
.error-hint {
  color: #d9534f;
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

/* 纯文本/代码文件预览：等宽字体、长行换行、纵向滚动由外层 .content-container 承担 */
.content-body :deep(pre.plain-text-content) {
  background: var(--code-block-bg);
  padding: 16px;
  border-radius: 8px;
  border: 1px solid var(--code-block-border);
  font-family: 'SF Mono', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: var(--code-block-text);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  margin: 0;
  max-width: 100%;
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
  width: 100%;          /* 跟随面板宽度自适应 */
  max-width: 100%;
  max-height: 65vh;     /* 不超过视口高度的 65% */
  height: auto;
  cursor: grab;
}

.content-body :deep(.mermaid-zoom-inner svg:active) {
  cursor: grabbing;
}

/* .plain-text-content 样式已统一在上面 :deep(pre.plain-text-content) 处定义 */

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
