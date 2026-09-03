<template>
  <div v-if="visible" class="modal-overlay" @click="close">
    <div class="modal-content" @click.stop>
      <button ref="closeBtn" class="close-button" @click="close" title="关闭">
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>

      <div class="modal-header">
        <h3>{{ file.name }}</h3>
        <div class="file-info">
          <span class="file-type">{{ getFileTypeLabel(file) }}</span>
          <span v-if="file.size_human" class="file-size">{{ file.size_human }}</span>
        </div>
      </div>

      <div class="modal-body">
        <!-- HTML 文件：原文 / 渲染效果 tab 切换（与 FilePreviewPanel 同款） -->
        <div v-if="isHtmlFile && (file.preview_url || file.iframe_url)" class="html-preview">
          <div class="html-tabs">
            <button
              :class="['tab-btn', { active: htmlTab === 'raw' }]"
              @click="htmlTab = 'raw'"
            >原文</button>
            <button
              :class="['tab-btn', { active: htmlTab === 'rendered' }]"
              @click="htmlTab = 'rendered'"
            >渲染效果</button>
          </div>
          <iframe
            v-if="htmlTab === 'rendered'"
            :key="iframeKey"
            :src="file.iframe_url || file.preview_url"
            class="html-preview-iframe"
            sandbox="allow-scripts allow-popups"
            referrerpolicy="no-referrer"
          />
          <div v-else class="preview-text">
            <pre>{{ htmlRawContent }}</pre>
          </div>
        </div>

        <!-- iframe 预览方式（PDF 和其他支持 iframe 预览的文件） -->
        <iframe
          v-else-if="file.preview_method === 'iframe' && (file.preview_url || file.iframe_url) && !isImageFile(file)"
          :src="file.iframe_url || file.preview_url"
          class="preview-iframe"
          frameborder="0"
        />

        <!-- 图片预览 -->
        <img
          v-else-if="isImageFile(file) && file.preview_url"
          :src="file.preview_url"
          :alt="file.name"
          class="preview-image"
        />

        <!-- Office 文档预览方式 -->
        <div v-else-if="file.preview_method === 'iframe_office'" class="office-preview">
          <div class="office-preview-content">
            <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10 9 9 9 8 9"/>
            </svg>
            <p>{{ file.preview_hint || 'Office 文档预览' }}</p>
            <p class="preview-hint">建议使用 Office Online 或下载后查看</p>
          </div>
        </div>

        <!-- 文本文件预览：使用解码后的 content 字段 -->
        <div v-else-if="isTextFile(file) && file.content" class="preview-text">
          <pre>{{ file.content }}</pre>
        </div>

        <!-- Mermaid 图表预览：原文 / 渲染切换 -->
        <div v-else-if="file.preview_method === 'mermaid'" class="mermaid-preview">
          <div class="mermaid-tabs">
            <button
              :class="['tab-btn', { active: mermaidTab === 'raw' }]"
              @click="mermaidTab = 'raw'"
            >原文</button>
            <button
              :class="['tab-btn', { active: mermaidTab === 'rendered' }]"
              @click="mermaidTab = 'rendered'"
            >渲染效果</button>
          </div>
          <div v-if="mermaidTab === 'raw'" class="preview-text">
            <pre>{{ file.raw_content }}</pre>
          </div>
          <div v-else class="mermaid-rendered" v-html="file.rendered_svg"></div>
        </div>

        <!-- 不支持预览的文件 -->
        <div v-else class="preview-placeholder">
          <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
            <polyline points="13 2 13 9 20 9"/>
          </svg>
          <p>{{ file.preview_hint || '无法预览此文件类型' }}</p>
          <p class="preview-hint">请下载后查看</p>
        </div>
      </div>

      <div v-if="canDownload" class="modal-footer">
        <a
          href="javascript:void(0)"
          @click.stop="downloadFile"
          class="download-button"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          下载文件
        </a>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FilePreviewModal',
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    file: {
      type: Object,
      default: () => ({})
    }
  },
  emits: ['close'],
  watch: {
    // 弹窗打开时焦点抢到关闭按钮，Esc 已走 document 兜底，这里只让 Tab / ↑↓ 立刻能用
    visible(val) {
      if (val) {
        this.$nextTick(() => {
          const btn = this.$refs.closeBtn
          if (btn && btn.focus) btn.focus()
        })
      }
    }
  },
  data() {
    return {
      mermaidTab: 'rendered', // 'raw' | 'rendered'
      htmlTab: 'rendered',    // 'raw' | 'rendered'
      // HTML 原文（异步加载，data:text/html 直接解 / http 走 fetch）
      htmlRawContent: '',
      htmlRawLoading: false,
      htmlRawError: '',
      // iframe key：用于在切换文件时强制重新挂载（避免浏览器缓存 + 显示陈旧内容）
      iframeKey: 0
    }
  },
  watch: {
    visible(val) {
      if (val) {
        this.mermaidTab = 'rendered'
        this.htmlTab = 'rendered'
        this.htmlRawContent = ''
        this.htmlRawError = ''
        this.iframeKey++
      }
    },
    'file.preview_url': {
      immediate: false,
      handler() {
        // 切换文件时强制重置原始 HTML 缓存，并刷新 iframe
        this.htmlRawContent = ''
        this.htmlRawError = ''
        this.iframeKey++
      }
    },
    htmlTab(val) {
      // 切到原文 tab 时按需异步加载
      if (val === 'raw' && this.isHtmlFile && !this.htmlRawContent && !this.htmlRawLoading) {
        this.loadHtmlRawContent()
      }
    }
  },
  methods: {
    close() {
      this.$emit('close')
    },
    isImageFile(file) {
      if (!file) return false
      // 检查大写的 file_type（如 "IMAGE"）和 type（如 "image/png"）
      if (file.file_type === 'IMAGE' || file.type === 'IMAGE') return true
      return file.type && file.type.startsWith('image/')
    },

    isTextFile(file) {
      if (!file) return false
      // 检查大写的 file_type（如 "TEXT"）和 type（如 "text/plain"）
      if (file.file_type === 'TEXT' || file.type === 'TEXT') return true
      return file.type && (file.type.startsWith('text/') ||
             file.type === 'application/json' ||
             file.type === 'text/csv' ||
             file.type === 'text/xml')
    },

    /**
     * 弹窗可见时响应 Esc → 关闭。监听 document 而不是 overlay div 的
     * @keydown.esc（div 无 tabindex 时收不到键盘事件；预览中有时焦点在 iframe
     * / 文档内，document 监听最稳）。
     */
    handleKeydown(e) {
      if (!this.visible) return
      if (e.key === 'Escape') {
        e.preventDefault()
        this.close()
      }
    },

    getFileTypeLabel(file) {
      if (!file) return '未知类型'

      const fileType = file.file_type || file.type || ''
      const mimeType = file.type || ''
      const suffix = file.suffix || (file.name ? '.' + file.name.split('.').pop().toLowerCase() : '')

      // 统一转大写比较，兼容后端返回的大写 file_type
      const upperFileType = fileType.toUpperCase()
      const upperMimeType = mimeType.toLowerCase()

      if (upperFileType === 'IMAGE' || upperMimeType.startsWith('image/')) return '图片文件'
      if (upperFileType === 'TEXT' || upperMimeType.startsWith('text/')) return '文本文件'
      if (suffix === '.pdf' || upperMimeType === 'application/pdf') return 'PDF 文档'
      if (suffix === '.docx' || upperMimeType.includes('document')) return 'Word 文档'
      if (suffix === '.pptx' || upperMimeType.includes('presentation')) return 'PPT 演示文稿'
      if (suffix === '.xlsx' || upperMimeType.includes('spreadsheet')) return 'Excel 表格'
      if (upperMimeType === 'application/json') return 'JSON 文件'

      return fileType || '文件'
    },

    // 点击下载：和渲染走不同的 URL
    //  - http(s)：后端 /static/ 接口需 ?download=true 才会返回 attachment 头
    //  - data:  ：浏览器对超长 data URL 的 download 兼容性差，转成 blob
    //  - 其他   ：原样打开
    downloadFile() {
      const url = this.file && this.file.preview_url
      if (!url) return
      const name = this.file.name || 'download'

      if (url.startsWith('http://') || url.startsWith('https://')) {
        // 本地静态资源走 /static/... → 加 ?download=true；OSS 已是签名 URL，加参数会失效，但 OSS 服务器默认支持下载
        const sep = url.includes('?') ? '&' : '?'
        const downloadUrl = url.includes('/static/') ? `${url}${sep}download=true` : url
        const a = document.createElement('a')
        a.href = downloadUrl
        a.download = name
        a.target = '_blank'
        a.rel = 'noopener noreferrer'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        return
      }

      if (url.startsWith('data:')) {
        try {
          const [meta, b64] = url.split(',')
          const mimeMatch = meta.match(/data:([^;]+)/)
          const mime = mimeMatch ? mimeMatch[1] : 'application/octet-stream'
          const bin = atob(b64)
          const len = bin.length
          const buf = new Uint8Array(len)
          for (let i = 0; i < len; i++) buf[i] = bin.charCodeAt(i)
          const blob = new Blob([buf], { type: mime })
          const blobUrl = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = blobUrl
          a.download = name
          document.body.appendChild(a)
          a.click()
          document.body.removeChild(a)
          // 异步释放，浏览器需要时间读取 blob
          setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
          return
        } catch (e) {
          console.warn('data URL 下载失败:', e)
        }
      }

      // 兜底：原样打开
      window.open(url, '_blank')
    },
    // 异步加载 HTML 原文：http/https URL 走 fetch；data: URL 同步解码
    async loadHtmlRawContent() {
      if (!this.file) return
      const url = this.file.preview_url || ''
      if (!url) return
      // data URL 直接同步解码
      if (url.startsWith('data:text/html')) {
        this.htmlRawContent = this._decodeDataHtml(url)
        return
      }
      this.htmlRawLoading = true
      this.htmlRawError = ''
      try {
        const resp = await fetch(url)
        if (!resp.ok) throw new Error('HTTP ' + resp.status)
        const text = await resp.text()
        this.htmlRawContent = text
      } catch (e) {
        console.warn('[FilePreviewModal] fetch HTML 原文失败:', e)
        this.htmlRawError = (e && e.message) || String(e)
      } finally {
        this.htmlRawLoading = false
      }
    },
    _decodeDataHtml(url) {
      const idx = url.indexOf(',')
      if (idx < 0) return ''
      const meta = url.slice(0, idx)
      const payload = url.slice(idx + 1)
      try {
        if (meta.includes(';base64')) {
          const bin = atob(payload)
          const bytes = new Uint8Array(bin.length)
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
          return new TextDecoder('utf-8').decode(bytes)
        }
        return decodeURIComponent(payload)
      } catch (e) {
        console.warn('[FilePreviewModal] 解码 data: URL 失败:', e)
        return ''
      }
    }
  },
  mounted() {
    document.addEventListener('keydown', this.handleKeydown)
  },
  beforeDestroy() {
    document.removeEventListener('keydown', this.handleKeydown)
  },
  computed: {
    // 是否显示下载按钮：覆盖所有有 preview_url 的文件类型（含图片）
    canDownload() {
      if (!this.file) return false
      const method = this.file.preview_method
      if (method === 'download' || method === 'iframe_office') return !!this.file.preview_url
      if (method === 'mermaid') return !!this.file.preview_url
      if (this.isImageFile(this.file)) return !!this.file.preview_url
      return false
    },
    // 判断 HTML 文件：文件名后缀 / file_type / MIME，三处任意命中即可
    isHtmlFile() {
      if (!this.file) return false
      const name = (this.file.name || '').toLowerCase()
      if (name.endsWith('.html') || name.endsWith('.htm')) return true
      const fileType = (this.file.file_type || '').toUpperCase()
      if (fileType === 'HTML') return true
      const mime = (this.file.type || '').toLowerCase()
      if (mime === 'text/html') return true
      return false
    },
    // 原文 tab 用的 HTML 源码：
    //  - 优先用已 fetch 的 htmlRawContent（http URL 由 watch → loadHtmlRawContent 填充）
    //  - data: text/html URL 同步解码
    //  - 否则根据 loading/error 状态返回提示
    rawHtmlContent() {
      if (this.htmlRawContent) return this.htmlRawContent
      const url = this.file && this.file.preview_url
      if (url && url.startsWith('data:text/html')) {
        return this._decodeDataHtml(url)
      }
      if (this.htmlRawError) return '[加载失败] ' + this.htmlRawError
      if (this.htmlRawLoading) return '加载中...'
      return ''
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.modal-content {
  background: var(--bg-primary);
  border-radius: 12px;
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  position: relative;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  animation: slideUp 0.3s;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.close-button {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 40px;
  height: 40px;
  border: none;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  z-index: 1;
}

.close-button:hover {
  background: var(--bg-hover);
  transform: scale(1.1);
}

.modal-header {
  padding: 24px 24px 16px;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0 0 8px;
  font-size: 18px;
  color: var(--text-primary);
  word-break: break-word;
  padding-right: 50px;
}

.file-info {
  display: flex;
  gap: 12px;
  align-items: center;
}

.file-type {
  font-size: 13px;
  color: var(--text-secondary);
  padding: 4px 10px;
  background: var(--bg-secondary);
  border-radius: 4px;
}

.modal-body {
  flex: 1;
  overflow: auto;
  padding: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 8px;
}

.preview-iframe {
  width: 100%;
  height: 70vh;
  border: none;
  border-radius: 8px;
}

/* HTML 文件预览（与 FilePreviewPanel 同款）：tabs + iframe + 原文 */
.html-preview {
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.html-tabs {
  display: flex;
  gap: 4px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 12px;
  flex-shrink: 0;
}
.html-preview-iframe {
  width: 100%;
  flex: 1;
  border: none;
  border-radius: 8px;
  background: var(--bg-primary);
  /* 撑满 modal-body 剩余高度 */
  min-height: 60vh;
}
.html-preview .preview-text {
  flex: 1;
  max-height: none;
}

.office-preview {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.office-preview-content {
  text-align: center;
  color: var(--text-secondary);
  padding: 24px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.office-preview-content svg {
  margin-bottom: 12px;
  opacity: 0.6;
}

.office-preview-content p {
  margin: 8px 0;
  font-size: 14px;
}

.preview-hint {
  font-size: 13px !important;
  color: var(--text-secondary);
  opacity: 0.8;
}

.modal-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border-color);
  display: flex;
  justify-content: flex-end;
}

.download-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: var(--button-bg);
  color: white;
  text-decoration: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;
}

.download-button:hover {
  background: var(--button-hover);
  transform: translateY(-1px);
}

.preview-text {
  width: 100%;
  max-height: 70vh;
  overflow: auto;
}

.preview-text pre {
  margin: 0;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  font-family: 'Courier New', monospace;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-wrap: break-word;
}

.preview-placeholder {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px;
}

.preview-placeholder svg {
  margin-bottom: 16px;
  opacity: 0.5;
}

.preview-placeholder p {
  margin: 0;
  font-size: 16px;
}

/* Mermaid 图表预览 */
.mermaid-preview {
  width: 100%;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.mermaid-tabs {
  display: flex;
  gap: 4px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 12px;
  flex-shrink: 0;
}

.tab-btn {
  padding: 6px 16px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-hover);
}

.tab-btn.active {
  background: var(--button-bg);
  color: white;
  border-color: var(--button-bg);
}

.mermaid-rendered {
  flex: 1;
  overflow: auto;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 8px 0;
}

.mermaid-rendered svg {
  max-width: 100%;
  height: auto;
  cursor: grab;
}
</style>
