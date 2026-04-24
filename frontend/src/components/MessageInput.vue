<template>
  <div class="input-area">
    <!-- 文件列表显示区域 - 横向紧凑布局 -->
    <div v-if="selectedFiles.length > 0" class="file-list-container">
      <div class="file-list-scroll">
        <div
          v-for="(file, index) in selectedFiles"
          :key="index"
          class="file-item"
          :class="{ 'file-error': file.error, 'file-uploading': file.uploading }"
        >
          <!-- 图片预览或文件图标 -->
          <div class="file-preview-wrapper">
            <img
              v-if="isImageFile(file) && file.preview"
              :src="file.preview"
              class="file-preview-img"
              :alt="file.name"
            />
            <div v-else class="file-icon-compact">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
                <polyline points="13 2 13 9 20 9"/>
              </svg>
            </div>

            <div v-if="file.uploading" class="uploading-overlay">
              <svg class="spinner-small" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 2 A10 10 0 0 1 22 12"/>
              </svg>
            </div>

            <!-- 删除按钮 -->
            <button
              type="button"
              class="remove-button-overlay"
              @click="removeFile(index)"
              :title="'删除 ' + file.name"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <!-- 文件名称（悬停显示完整信息） -->
          <div class="file-name-compact" :title="`${file.name} (${formatFileSize(file.size)})`">
            {{ truncateFileName(file.name, 12) }}
          </div>

          <!-- 错误提示 -->
          <div v-if="file.error" class="file-error-badge" :title="file.error">!</div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-wrapper">
      <!-- 文件上传按钮 -->
      <button
        type="button"
        class="upload-button"
        @click="triggerFileInput"
        :disabled="isLoading"
        title="上传文件"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
        </svg>
      </button>

      <!-- 隐藏的文件输入 -->
      <input
        ref="fileInput"
        type="file"
        multiple
        :accept="acceptedTypes"
        @change="handleFileSelect"
        style="display: none"
      />

      <textarea
        v-model="inputText"
        @keydown.enter="handleEnterKey"
        @input="autoResize"
        @paste="handlePaste"
        placeholder="输入消息..."
        rows="1"
        ref="textarea"
      ></textarea>

      <!-- 优化按钮 -->
      <button
        type="button"
        class="optimize-button"
        :class="{ 'optimizing': isOptimizing }"
        @click="optimizeInput"
        :disabled="!inputText.trim() || isLoading || isOptimizing"
        :title="isOptimizing ? '优化中...' : '优化输入'"
      >

        <svg v-if="!isOptimizing" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M12 1v6m0 6v6m5.2-13.2l-4.2 4.2m0 6l4.2 4.2M23 12h-6m-6 0H1m18.2 5.2l-4.2-4.2m0-6l4.2-4.2"/>
        </svg>
        <svg v-else class="spinner" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 2 A10 10 0 0 1 22 12"/>
        </svg>
      </button>

      <button
        @click="handleSend"
        :disabled="(!inputText.trim() && selectedFiles.filter(f => !f.error && !f.uploading).length === 0) || isLoading || hasUploadingFiles"
        class="send-btn"
        :title="hasUploadingFiles ? '文件上传中，请等待' : ''"
      >
        发送
      </button>
    </div>

    <!-- 拖拽区域遮罩 -->
    <div
      v-if="isDragging"
      class="drag-overlay"
      @drop.prevent="handleDrop"
      @dragover.prevent
      @dragleave="isDragging = false"
    >
      <div class="drag-content">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
        <p>释放文件以上传</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'MessageInput',
  props: {
    isLoading: {
      type: Boolean,
      default: false
    }
  },
  emits: ['send'],
  data() {
    return {
      inputText: '',
      selectedFiles: [],
      isDragging: false,
      isOptimizing: false,
      fileConfig: null,
      loadingConfig: false,
      processedOutputs: [],
      // 上传队列控制
      uploadQueue: [],      // 待处理的文件队列
      isUploadQueueProcessing: false  // 队列是否正在处理中
    }
  },
  computed: {
    maxFileSize() {
      return this.fileConfig?.maxFileSize || 25 * 1024 * 1024
    },
    allowedImageTypes() {
      const types = this.fileConfig?.imageTypes?.suffixes
      return types && types.length > 0 ? types : ['.png', '.jpg', '.jpeg', '.gif']
    },
    allowedTextTypes() {
      const types = this.fileConfig?.textTypes?.suffixes
      return types && types.length > 0 ? types : ['.txt', '.md', '.csv', '.xml', '.json']
    },
    allowedDocumentTypes() {
      const types = this.fileConfig?.documentTypes?.suffixes
      return types && types.length > 0 ? types : ['.pdf', '.docx', '.pptx', '.xlsx']
    },
    acceptedTypes() {
      return [...this.allowedImageTypes, ...this.allowedTextTypes, ...this.allowedDocumentTypes].join(',')
    },
    allowedExtensions() {
      return [...this.allowedImageTypes, ...this.allowedTextTypes, ...this.allowedDocumentTypes]
    },
    // 检查是否有文件正在上传
    hasUploadingFiles() {
      return this.selectedFiles.some(f => f.uploading) || this.uploadQueue.length > 0 || this.isUploadQueueProcessing
    }
  },
  mounted() {
    this.fetchFileConfig()
    // 监听全局拖拽事件
    window.addEventListener('dragenter', this.handleDragEnter)
    window.addEventListener('dragover', this.handleDragOver)
    window.addEventListener('drop', this.handleWindowDrop)
  },
  beforeUnmount() {
    // 清理事件监听
    window.removeEventListener('dragenter', this.handleDragEnter)
    window.removeEventListener('dragover', this.handleDragOver)
    window.removeEventListener('drop', this.handleWindowDrop)

    // 清理预览 URL
    this.selectedFiles.forEach(file => {
      if (file.preview) {
        URL.revokeObjectURL(file.preview)
      }
    })
  },
  methods: {
    async fetchFileConfig() {
      if (this.loadingConfig) return
      this.loadingConfig = true
      try {
        const response = await fetch('/chat/file-config')
        if (response.ok) {
          this.fileConfig = await response.json()
        }
      } catch (error) {
        console.error('获取文件配置失败:', error)
      } finally {
        this.loadingConfig = false
      }
    },

    handlePaste(e) {
      const items = e.clipboardData?.items
      if (!items) return

      const files = []
      for (const item of items) {
        if (item.kind === 'file') {
          const file = item.getAsFile()
          if (file) files.push(file)
        }
      }

      if (files.length > 0) {
        e.preventDefault()
        this.addFiles(files)
      }
    },

    handleEnterKey(e) {
      // 如果正在输入法输入中（如拼音、日文等），不处理 Enter
      if (e.isComposing || e.keyCode === 229) {
        return
      }

      // Ctrl+Enter 换行，Enter 发送
      if (e.ctrlKey) {
        // Ctrl+Enter: 插入换行符
        const textarea = e.target
        const start = textarea.selectionStart
        const end = textarea.selectionEnd
        const value = textarea.value

        this.inputText = value.substring(0, start) + '\n' + value.substring(end)

        // 恢复光标位置
        this.$nextTick(() => {
          textarea.selectionStart = textarea.selectionEnd = start + 1
          this.autoResize()
        })
      } else {
        // Enter: 发送消息
        e.preventDefault()
        this.handleSend()
      }
    },

    autoResize() {
      const textarea = this.$refs.textarea
      if (!textarea) return

      // 先隐藏滚动条再测量，避免滚动条宽度变化引起的抖动
      textarea.style.overflowY = 'hidden'
      textarea.style.height = 'auto'
      const newHeight = Math.min(Math.max(textarea.scrollHeight, 52), 200)
      textarea.style.height = newHeight + 'px'
      // 达到最大高度才显示滚动条
      textarea.style.overflowY = newHeight >= 200 ? 'auto' : 'hidden'
    },

    handleSend() {
      const validFiles = this.selectedFiles.filter(f => !f.error && !f.uploading)

      if ((!this.inputText.trim() && validFiles.length === 0) || this.isLoading) {
        return
      }

      this.$emit('send', {
        message: this.inputText.trim(),
        files: validFiles,
        processedOutputs: [...this.processedOutputs]
      })

      console.log('发送消息，processedOutputs 数量:', this.processedOutputs.length)

      this.inputText = ''
      this.clearFiles()

      this.$nextTick(() => {
        const textarea = this.$refs.textarea
        if (textarea) {
          textarea.style.height = '52px'
        }
      })
    },

    async optimizeInput() {
      if (!this.inputText.trim() || this.isOptimizing) return

      this.isOptimizing = true

      try {
        const response = await fetch('/chat/improve_input', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            input_text: this.inputText.trim()
          })
        })

        if (!response.ok) {
          throw new Error('优化请求失败')
        }

        const data = await response.json()

        // 更新输入框内容
        if (data.improved_text) {
          this.inputText = data.improved_text
          // 触发自动调整高度
          this.$nextTick(() => {
            this.autoResize()
          })
        }
      } catch (error) {
        console.error('优化输入失败:', error)
      } finally {
        this.isOptimizing = false
      }
    },

    triggerFileInput() {
      this.$refs.fileInput.click()
    },

    handleFileSelect(event) {
      const selectedFiles = Array.from(event.target.files)
      this.addFiles(selectedFiles)
      // 清空 input，允许重复选择同一文件
      event.target.value = ''
    },

    handleDragEnter(e) {
      e.preventDefault()
      if (this.isLoading) return

      // 检查是否包含文件
      if (e.dataTransfer.types.includes('Files')) {
        this.isDragging = true
      }
    },

    handleDragOver(e) {
      e.preventDefault()
    },

    handleWindowDrop(e) {
      e.preventDefault()
      this.isDragging = false
    },

    handleDrop(e) {
      this.isDragging = false
      if (this.isLoading) return

      const droppedFiles = Array.from(e.dataTransfer.files)
      this.addFiles(droppedFiles)
    },

    async addFiles(newFiles) {
      if (!newFiles || newFiles.length === 0) return

      const validatedFiles = newFiles.map(file => {
        const fileObj = {
          name: file.name,
          size: file.size,
          type: file.type,
          file: file,
          error: null,
          preview: null,
          fileId: null,
          uploading: false
        }

        const validation = this.validateFile(file)
        if (!validation.valid) {
          fileObj.error = validation.error
        } else if (this.isImageFile(fileObj)) {
          fileObj.preview = URL.createObjectURL(file)
        }

        return fileObj
      })

      const validFiles = validatedFiles.filter(f => !f.error)
      const invalidFiles = validatedFiles.filter(f => f.error)

      this.selectedFiles.push(...invalidFiles)

      if (validFiles.length > 0) {
        // 将有效文件添加到队列
        this.uploadQueue.push(...validFiles)

        // 如果队列未在处理，则开始处理
        if (!this.isUploadQueueProcessing) {
          this.processUploadQueue()
        }
      }
    },

    async processUploadQueue() {
      if (this.uploadQueue.length === 0) {
        this.isUploadQueueProcessing = false
        return
      }

      this.isUploadQueueProcessing = true

      // 取出队列中的所有文件
      const filesToUpload = [...this.uploadQueue]
      this.uploadQueue = []

      // 标记为上传中
      filesToUpload.forEach(fileObj => {
        fileObj.uploading = true
      })
      this.selectedFiles.push(...filesToUpload)
      this.$forceUpdate()

      // 整批文件一次性上传
      await this.uploadFilesBatch(filesToUpload)

      // 这一批完成后，继续处理下一批
      this.processUploadQueue()
    },

    async uploadFilesBatch(fileObjs) {
      const formData = new FormData()

      // 添加所有文件
      fileObjs.forEach(fileObj => {
        formData.append('files', fileObj.file)
      })

      // 携带当前已处理的文件列表
      formData.append('processed_outputs', JSON.stringify(this.processedOutputs))

      console.log('上传文件批次:', {
        fileCount: fileObjs.length,
        fileNames: fileObjs.map(f => f.name),
        processedOutputsLength: this.processedOutputs.length
      })

      try {
        const response = await fetch('/chat/upload_file', {
          method: 'POST',
          body: formData
        })

        if (!response.ok) {
          const errorText = await response.text()
          console.error('文件上传失败:', response.status, errorText)
          throw new Error(`文件上传失败: ${response.status}`)
        }

        const data = await response.json()

        if (data.code === 200) {
          // 更新全局 processedOutputs
          this.processedOutputs = data.processed_outputs || []
          console.log('批次上传成功，processedOutputs 数量:', this.processedOutputs.length)

          // 更新每个文件的信息
          fileObjs.forEach(fileObj => {
            const output = this.processedOutputs.find(
              op => op.name === fileObj.name
            )

            if (output) {
              fileObj.fileId = output.file_id
              if (output.preview) {
                fileObj.preview = output.preview
              }
              if (output.iframe_url) {
                fileObj.iframe_url = output.iframe_url
              }
            }
          })
        } else {
          throw new Error(data.msg || '文件上传失败')
        }
      } catch (error) {
        console.error('批次上传失败:', error)
        // 标记所有文件为失败
        fileObjs.forEach(fileObj => {
          fileObj.error = '上传失败'
        })
      } finally {
        fileObjs.forEach(fileObj => {
          fileObj.uploading = false
        })
        this.$forceUpdate()
      }
    },

    validateFile(file) {
      const extension = this.getFileExtension(file.name)

      // 检查文件大小
      if (file.size > this.maxFileSize) {
        return {
          valid: false,
          error: `文件大小超过 ${this.formatFileSize(this.maxFileSize)} 限制`
        }
      }

      // 检查文件扩展名
      const isAllowed = this.allowedExtensions.some(
        allowedExt => allowedExt.toLowerCase() === extension.toLowerCase()
      )

      if (!isAllowed) {
        return {
          valid: false,
          error: `不支持的文件类型 ${extension}`
        }
      }

      return { valid: true }
    },

    async removeFile(index) {
      const file = this.selectedFiles[index]

      // 如果文件还在队列中未上传，先从队列移除
      if (file.uploading === false && file.fileId === null) {
        const queueIndex = this.uploadQueue.findIndex(f => f === file)
        if (queueIndex !== -1) {
          this.uploadQueue.splice(queueIndex, 1)
        }
      }

      // 如果文件已上传，调用后端取消
      if (file.fileId && this.processedOutputs.length > 0) {
        try {
          const response = await fetch('/chat/cancel_upload_file', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              file_id: file.fileId,
              processed_outputs: this.processedOutputs
            })
          })

          if (response.ok) {
            const data = await response.json()
            this.processedOutputs = data.processed_outputs || []
          }
        } catch (error) {
          console.error('取消文件上传失败:', error)
        }
      }

      if (file.preview) {
        URL.revokeObjectURL(file.preview)
      }
      this.selectedFiles.splice(index, 1)
    },

    clearFiles() {
      this.selectedFiles.forEach(file => {
        if (file.preview) {
          URL.revokeObjectURL(file.preview)
        }
      })
      this.selectedFiles = []
      this.processedOutputs = []
      this.uploadQueue = []
    },

    getFileExtension(filename) {
      if (!filename || !filename.includes('.')) return ''
      return '.' + filename.split('.').pop().toLowerCase()
    },

    isImageFile(fileObj) {
      const extension = this.getFileExtension(fileObj.name)
      return this.allowedImageTypes.includes(extension)
    },

    formatFileSize(bytes) {
      if (bytes === 0) return '0 B'
      const k = 1024
      const sizes = ['B', 'KB', 'MB', 'GB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
    },

    truncateFileName(filename, maxLength) {
      if (filename.length <= maxLength) return filename
      const extension = this.getFileExtension(filename)
      const nameWithoutExt = filename.substring(0, filename.length - extension.length)
      const truncatedName = nameWithoutExt.substring(0, maxLength - 3 - extension.length)
      return truncatedName + '...' + extension
    },
  }
}
</script>

<style scoped>
.input-area {
  position: relative;
  padding: 16px;
  background-color: var(--bg-primary);
  border-top: 1px solid var(--border-color);
}

/* 文件列表容器 - 横向紧凑布局 */
.file-list-container {
  max-width: 900px;
  margin: 0 auto 12px;
  overflow: hidden;
}

.file-list-scroll {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 4px 0;
  scrollbar-width: thin;
  scrollbar-color: var(--border-color) transparent;
}

.file-list-scroll::-webkit-scrollbar {
  height: 6px;
}

.file-list-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.file-list-scroll::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

.file-list-scroll::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

.file-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  width: 80px;
}

.file-item.file-error .file-preview-wrapper {
  border-color: #ef4444;
}

.file-item.file-uploading .file-preview-wrapper {
  border-color: var(--button-bg);
  opacity: 0.7;
}

.file-preview-wrapper {
  position: relative;
  width: 80px;
  height: 80px;
  border: 2px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  background: var(--message-bg);
  transition: all 0.2s;
}

.file-preview-wrapper:hover {
  border-color: var(--primary-color);
}

.file-preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-icon-compact {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  background: var(--hover-bg);
}

.file-name-compact {
  font-size: 11px;
  color: var(--text-primary);
  text-align: center;
  width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 2px;
}

.file-error-badge {
  position: absolute;
  top: 4px;
  left: 4px;
  width: 20px;
  height: 20px;
  background: #ef4444;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
  cursor: help;
}

.remove-button-overlay {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 24px;
  height: 24px;
  border: none;
  background: rgba(0, 0, 0, 0.6);
  color: white;
  cursor: pointer;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.2s;
}

.file-preview-wrapper:hover .remove-button-overlay {
  opacity: 1;
}

.remove-button-overlay:hover {
  background: #ef4444;
  transform: scale(1.1);
}

.uploading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}

.spinner-small {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 输入区域 */
.input-wrapper {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.upload-button {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 12px;
  transition: all 0.2s;
}

.upload-button:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.upload-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.optimize-button {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 12px;
  transition: all 0.3s ease;
  border: 1px solid var(--border-color);
  position: relative;
  overflow: hidden;
}

.optimize-button::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  border-radius: 50%;
  background: var(--button-bg);
  opacity: 0;
  transform: translate(-50%, -50%);
  transition: width 0.6s, height 0.6s, opacity 0.6s;
}

.optimize-button.optimizing::before {
  width: 100%;
  height: 100%;
  opacity: 0.1;
  animation: pulse 1.5s ease-in-out infinite;
}

.optimize-button:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--button-bg);
  border-color: var(--button-bg);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(16, 163, 127, 0.2);
}

.optimize-button:active:not(:disabled) {
  transform: translateY(0);
}

.optimize-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.optimize-button.optimizing {
  border-color: var(--button-bg);
  color: var(--button-bg);
}

.optimize-button .spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%, 100% {
    opacity: 0.1;
    transform: translate(-50%, -50%) scale(1);
  }
  50% {
    opacity: 0.2;
    transform: translate(-50%, -50%) scale(1.1);
  }
}

.input-wrapper textarea {
  flex: 1;
  min-height: 52px;
  max-height: 200px;
  height: 52px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  outline: none;
  transition: border-color 0.2s;
  overflow-y: hidden;
  line-height: 1.5;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.1) transparent;
}

.input-wrapper textarea::-webkit-scrollbar {
  width: 6px;
}

.input-wrapper textarea::-webkit-scrollbar-track {
  background: transparent;
}

.input-wrapper textarea::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.1);
  border-radius: 3px;
}

.input-wrapper textarea::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.15);
}

/* 暗色主题下的滚动条 */
.dark-theme .input-wrapper textarea {
  scrollbar-color: rgba(255, 255, 255, 0.1) transparent;
}

.dark-theme .input-wrapper textarea::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
}

.dark-theme .input-wrapper textarea::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}

.input-wrapper textarea:focus {
  border-color: var(--button-bg);
}

.send-btn {
  flex-shrink: 0;
  height: 52px;
  padding: 0 24px;
  border: none;
  background: var(--button-bg);
  color: white;
  border-radius: 12px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 500;
  transition: background 0.2s;
}

.send-btn:hover:not(:disabled) {
  background: var(--button-hover);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 拖拽遮罩 */
.drag-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
}

.drag-content {
  text-align: center;
  color: white;
  pointer-events: none;
}

.drag-content svg {
  margin-bottom: 16px;
  animation: bounce 1s infinite;
}

.drag-content p {
  font-size: 18px;
  font-weight: 500;
}

@keyframes bounce {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}
</style>
