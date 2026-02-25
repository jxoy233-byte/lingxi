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
          <span class="file-type">{{ getFileTypeLabel(file.type) }}</span>
        </div>
      </div>

      <div class="modal-body">
        <!-- 图片预览 -->
        <img
          v-if="isImageFile(file)"
          :src="file.preview"
          :alt="file.name"
          class="preview-image"
        />

        <!-- 文本文件预览 -->
        <div v-else-if="isTextFile(file)" class="preview-text">
          <pre>{{ file.content }}</pre>
        </div>

        <!-- 其他文件类型 -->
        <div v-else class="preview-placeholder">
          <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
            <polyline points="13 2 13 9 20 9"/>
          </svg>
          <p>无法预览此文件类型</p>
        </div>
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
      if (!file.type) return false
      return file.type.startsWith('image/')
    },
    isTextFile(file) {
      if (!file.type) return false
      return file.type.startsWith('text/') ||
             file.type === 'application/json' ||
             file.type === 'text/csv' ||
             file.type === 'text/xml'
    },
    getFileTypeLabel(type) {
      if (!type) return '未知类型'
      if (type.startsWith('image/')) return '图片文件'
      if (type.startsWith('text/')) return '文本文件'
      if (type === 'application/json') return 'JSON 文件'
      if (type === 'text/csv') return 'CSV 文件'
      if (type === 'text/xml') return 'XML 文件'
      return type
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
