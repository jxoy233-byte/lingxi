<template>
  <div v-if="visible" class="modal-overlay" @click="close">
    <div class="modal-content" @click.stop>
      <button class="close-button" @click="close" title="关闭">
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
        <!-- iframe 预览方式（PDF 和其他支持 iframe 预览的文件） -->
        <iframe
          v-if="file.preview_method === 'iframe' && (file.preview_url || file.iframe_url) && !isImageFile(file)"
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

      <div v-if="file.preview_method === 'download' || file.preview_method === 'iframe_office'" class="modal-footer">
        <a
          v-if="file.preview_url"
          :href="file.preview_url"
          :download="file.name"
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
</style>
