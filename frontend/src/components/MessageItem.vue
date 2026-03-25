<template>
  <div :class="['message', message.role === 'user' ? 'user-message' : 'ai-message']">
    <div class="message-content">
      <!-- 文件附件显示 -->
      <div v-if="message.files && message.files.length > 0" class="message-files">
        <div
          v-for="(file, index) in message.files"
          :key="index"
          class="file-attachment"
          @click="handleFileClick(file)"
        >
          <!-- 图片预览 -->
          <img
            v-if="file.preview && isImageFile(file)"
            :src="file.preview"
            :alt="file.name"
            class="file-attachment-img"
          />
          <!-- 文本文件预览（有内容） -->
          <div v-else-if="isTextFile(file) && file.content" class="file-text-preview">
            <div class="file-text-icon">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <line x1="10" y1="9" x2="8" y2="9"/>
              </svg>
            </div>
            <div class="file-text-content">{{ truncateText(file.content, 50) }}</div>
            <div class="file-attachment-name">{{ file.name }}</div>
          </div>
          <!-- 普通文件图标（包括没有预览的图片和文本文件） -->
          <div v-else class="file-attachment-icon">
            <!-- 根据文件类型显示不同图标 -->
            <svg v-if="isImageFile(file)" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
              <circle cx="8.5" cy="8.5" r="1.5"/>
              <polyline points="21 15 16 10 5 21"/>
            </svg>
            <svg v-else-if="isTextFile(file)" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <line x1="10" y1="9" x2="8" y2="9"/>
            </svg>
            <svg v-else-if="isDocumentFile(file)" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10 9 9 9 8 9"/>
            </svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
              <polyline points="13 2 13 9 20 9"/>
            </svg>
            <div class="file-attachment-name">{{ file.name }}</div>
          </div>
        </div>
      </div>

      <!-- 搜索结果显示 -->

      <!-- 思考过程区块 -->
      <div v-if="message.role === 'ai' && hasThinking" class="thinking-section" :class="{ 'thinking-active': !message.thinkingDone, 'thinking-collapsed': thinkingCollapsed }">
        <div class="thinking-header" @click="toggleThinking">
          <div class="thinking-header-left">
            <span class="thinking-status-dot" :class="{ 'dot-active': !message.thinkingDone }"></span>
            <span class="thinking-label">{{ message.thinkingDone ? '思考过程' : '正在思考...' }}</span>
            <span v-if="message.toolCalls && message.toolCalls.length" class="tool-badge">
              {{ message.toolCalls.length }} 个工具调用
            </span>
          </div>
          <svg class="thinking-chevron" :class="{ rotated: !thinkingCollapsed }" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
        </div>
        <div class="thinking-body" v-show="!thinkingCollapsed">
          <!-- 工具调用列表 -->
          <div v-if="message.toolCalls && message.toolCalls.length" class="tool-calls">
            <div v-for="(tool, i) in message.toolCalls" :key="i" class="tool-call-item" :class="{ 'tool-done': tool.result !== null }">
              <div class="tool-call-header" @click="toggleTool(i)" :style="tool.result !== null ? 'cursor:pointer' : ''">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                </svg>
                <span class="tool-name">{{ tool.name }}</span>
                <span v-if="tool.result !== null" class="tool-check">✓</span>
                <span v-else class="tool-running-dot"></span>
                <svg v-if="tool.result !== null" class="tool-expand-chevron" :class="{ rotated: expandedTools[i] }" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
              </div>
              <div v-if="tool.args && hasArgs(tool.args)" class="tool-args">{{ formatArgs(tool.args) }}</div>
              <div v-if="tool.result !== null && expandedTools[i]" class="tool-result">{{ tool.result }}</div>
            </div>
          </div>
          <!-- 推理文本 -->
          <div v-if="message.reasoning" class="reasoning-text">{{ message.reasoning }}</div>
        </div>
      </div>

      <!-- 消息文本 -->
      <div v-if="message.content" class="message-text" v-html="renderedContent"></div>

      <!-- 复制按钮 -->
      <button
        v-if="message.role === 'ai' && message.content"
        class="copy-button"
        @click="copyMessage"
        :title="copied ? '已复制' : '复制'"
      >
        <svg v-if="!copied" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </button>

      <!-- 响应时间显示 -->
      <div v-if="message.role === 'ai' && message.responseTime" class="response-time" :class="{ 'time-live': message.streaming !== false }">
        <span v-if="message.streaming !== false" class="time-live-dot"></span>
        <svg v-else xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
        </svg>
        {{ formatResponseTime(message.responseTime) }}
      </div>
    </div>

    <!-- 文件预览模态框 -->
    <FilePreviewModal
      :visible="showPreview"
      :file="previewFile"
      @close="closePreview"
    />
  </div>
</template>

<script>
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'
import FilePreviewModal from './FilePreviewModal.vue'

// 配置 marked
const renderer = new marked.Renderer()
renderer.code = function(code, lang) {
  const language = hljs.getLanguage(lang) ? lang : 'plaintext'
  const highlighted = hljs.highlight(code, { language }).value
  return `<pre><code class="hljs ${language}">${highlighted}</code></pre>`
}

marked.setOptions({
  breaks: true,
  gfm: true,
  renderer: renderer
})

export default {
  name: 'MessageItem',
  components: {
    FilePreviewModal
  },
  props: {
    message: {
      type: Object,
      required: true
    }
  },
  data() {
    return {
      copied: false,
      showPreview: false,
      previewFile: {},
      // 如果消息已完成（thinkingDone: true），默认折叠思考区块
      thinkingCollapsed: this.message.thinkingDone === true,
      expandedTools: {}
    }
  },
  computed: {
    renderedContent() {
      if (!this.message.content) return ''
      if (this.message.role === 'ai') {
        return marked(this.message.content)
      }
      return this.escapeHtml(this.message.content)
    },
    hasThinking() {
      return (this.message.reasoning && this.message.reasoning.length > 0) ||
             (this.message.toolCalls && this.message.toolCalls.length > 0)
    }
  },
  watch: {
    'message.content': {
      handler() {
        this.$nextTick(() => {
          this.highlightCode()
        })
      },
      immediate: true
    },
    // 主内容开始输出时折叠思考区块
    'message.thinkingDone'(newVal) {
      if (newVal) {
        this.thinkingCollapsed = true
      }
    },
    // 新消息开始流式输出时展开思考区块
    'message.streaming'(newVal) {
      if (newVal === true) {
        this.thinkingCollapsed = false
      }
    }
  },
  methods: {
    highlightCode() {
      const codeBlocks = this.$el.querySelectorAll('pre code')
      codeBlocks.forEach(block => {
        if (!block.classList.contains('hljs')) {
          hljs.highlightElement(block)
        }
      })
    },
    escapeHtml(text) {
      const div = document.createElement('div')
      div.textContent = text
      return div.innerHTML.replace(/\n/g, '<br>')
    },

    async copyMessage() {
      try {
        await navigator.clipboard.writeText(this.message.content)
        this.copied = true
        setTimeout(() => {
          this.copied = false
        }, 2000)
      } catch (err) {
        console.error('复制失败:', err)
      }
    },

    handleFileClick(file) {
      // 打开预览模态框
      this.previewFile = file
      this.showPreview = true
    },

    closePreview() {
      this.showPreview = false
      this.previewFile = {}
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

    isDocumentFile(file) {
      if (!file.name) return false
      const extension = this.getFileExtension(file.name)
      const documentExtensions = ['.docx', '.doc', '.pdf']
      return documentExtensions.includes(extension)
    },

    getFileExtension(filename) {
      if (!filename || !filename.includes('.')) return ''
      return '.' + filename.split('.').pop().toLowerCase()
    },

    truncateText(text, maxLength) {
      if (!text) return ''
      if (text.length <= maxLength) return text
      return text.substring(0, maxLength) + '...'
    },
    formatResponseTime(seconds) {
      if (seconds < 60) {
        return `${seconds.toFixed(1)}s`
      } else {
        const minutes = Math.floor(seconds / 60)
        const remainingSeconds = (seconds % 60).toFixed(1)
        return `${minutes}m ${remainingSeconds}s`
      }
    },
    toggleThinking() {
      this.thinkingCollapsed = !this.thinkingCollapsed
    },
    toggleTool(index) {
      this.expandedTools = {
        ...this.expandedTools,
        [index]: !this.expandedTools[index]
      }
    },
    hasArgs(args) {
      if (!args) return false
      return Object.keys(args).length > 0
    },
    formatArgs(args) {
      try {
        return JSON.stringify(args, null, 2)
      } catch {
        return String(args)
      }
    }
  }
}
</script>

<style scoped>
.message {
  display: flex;
  margin-bottom: 24px;
  width: 100%;
}

.user-message {
  justify-content: flex-end;
}

.ai-message {
  justify-content: flex-start;
}

.message-content {
  max-width: 75%;
  padding: 12px 16px;
  border-radius: 14px;
  position: relative;
}

.ai-message .message-content {
  background-color: var(--ai-msg-bg);
  border: 1px solid var(--border-color);
}

.user-message .message-content {
  background-color: var(--user-msg-bg);
  border: 1px solid var(--border-color);
}

/* 文件附件样式 */
.message-files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.file-attachment {
  position: relative;
  width: 100px;
  height: 100px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  cursor: pointer;
  transition: all 0.2s;
}

.file-attachment:hover {
  border-color: var(--primary-color);
  transform: scale(1.02);
}

.file-attachment-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-text-preview {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.file-text-icon {
  color: var(--button-bg);
}

.file-text-content {
  font-size: 10px;
  text-align: center;
  line-height: 1.3;
  max-height: 40px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  color: var(--text-secondary);
}

.file-attachment-icon {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  background: var(--hover-bg);
  color: var(--text-secondary);
}

.file-attachment-name {
  font-size: 11px;
  text-align: center;
  word-break: break-word;
  line-height: 1.3;
  max-height: 3em;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.message-text {
  line-height: 1.7;
  word-wrap: break-word;
  font-size: 15px;
}

/* Markdown 样式 */
.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3),
.message-text :deep(h4),
.message-text :deep(h5),
.message-text :deep(h6) {
  margin: 20px 0 12px;
  font-weight: 700;
  line-height: 1.4;
  color: var(--text-primary);
}

.message-text :deep(h1) { font-size: 1.7em; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }
.message-text :deep(h2) { font-size: 1.45em; border-bottom: 1px solid var(--border-color); padding-bottom: 6px; }
.message-text :deep(h3) { font-size: 1.25em; }
.message-text :deep(h4) { font-size: 1.1em; }
.message-text :deep(h5) { font-size: 1em; }
.message-text :deep(h6) { font-size: 0.9em; color: var(--text-secondary); }

.message-text :deep(p) {
  margin: 10px 0;
}

.message-text :deep(strong),
.message-text :deep(b) {
  font-weight: 700;
  color: var(--text-primary);
}

.message-text :deep(em),
.message-text :deep(i) {
  font-style: italic;
}

.message-text :deep(code) {
  background: var(--bg-secondary);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', 'Courier New', monospace;
  font-size: 0.88em;
  color: #e06c75;
}

.message-text :deep(pre) {
  background: #282c34;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 16px 0;
  border: 1px solid var(--border-color);
  position: relative;
}

.message-text :deep(pre code) {
  background: transparent;
  padding: 0;
  color: #abb2bf;
  font-size: 0.9em;
  line-height: 1.6;
}

.message-text :deep(pre code.hljs) {
  background: transparent !important;
}

.message-text :deep(ul),
.message-text :deep(ol) {
  margin: 12px 0;
  padding-left: 28px;
}

.message-text :deep(ul) {
  list-style-type: disc;
}

.message-text :deep(ol) {
  list-style-type: decimal;
}

.message-text :deep(li) {
  margin: 6px 0;
  padding-left: 4px;
}

.message-text :deep(ul ul),
.message-text :deep(ol ol),
.message-text :deep(ul ol),
.message-text :deep(ol ul) {
  margin: 6px 0;
  padding-left: 24px;
}

.message-text :deep(blockquote) {
  border-left: 4px solid var(--button-bg);
  padding: 12px 16px;
  margin: 16px 0;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border-radius: 0 6px 6px 0;
}

.message-text :deep(blockquote p) {
  margin: 0;
}

.message-text :deep(a) {
  color: var(--button-bg);
  text-decoration: none;
  transition: color 0.2s;
}

.message-text :deep(a:hover) {
  text-decoration: underline;
  color: var(--button-hover);
}

.message-text :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 16px 0;
  overflow-x: auto;
  display: block;
}

.message-text :deep(th),
.message-text :deep(td) {
  border: 1px solid var(--border-color);
  padding: 10px 14px;
  text-align: left;
}

.message-text :deep(th) {
  background: var(--bg-secondary);
  font-weight: 700;
  color: var(--text-primary);
}

.message-text :deep(tr:nth-child(even)) {
  background: var(--bg-secondary);
}

.message-text :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-color);
  margin: 24px 0;
}

.message-text :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
  margin: 12px 0;
}

/* 复制按钮 */
.copy-button {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 32px;
  height: 32px;
  border: none;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.2s;
}

.message-content:hover .copy-button {
  opacity: 1;
}

.copy-button:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.copy-button:active {
  transform: scale(0.95);
}

/* 响应时间样式 */
.response-time {
  position: absolute;
  bottom: 8px;
  right: 12px;
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.55;
  pointer-events: none;
  display: flex;
  align-items: center;
  gap: 4px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.response-time.time-live {
  opacity: 0.8;
  color: var(--button-bg);
}

.time-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--button-bg);
  animation: live-pulse 1.2s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes live-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.7); }
}

/* 思考过程区块 */
.thinking-section {
  margin-bottom: 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  font-size: 13px;
  transition: border-color 0.3s;
}

.thinking-section.thinking-active {
  border-color: color-mix(in srgb, var(--button-bg) 40%, var(--border-color));
}

.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  cursor: pointer;
  background: var(--bg-secondary);
  user-select: none;
  transition: background 0.15s;
}

.thinking-header:hover {
  background: var(--bg-hover);
}

.thinking-header-left {
  display: flex;
  align-items: center;
  gap: 7px;
}

.thinking-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-secondary);
  opacity: 0.5;
  flex-shrink: 0;
}

.thinking-status-dot.dot-active {
  background: var(--button-bg);
  opacity: 1;
  animation: live-pulse 1.2s ease-in-out infinite;
}

.thinking-label {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
}

.tool-badge {
  font-size: 11px;
  color: var(--button-bg);
  background: color-mix(in srgb, var(--button-bg) 12%, transparent);
  padding: 1px 6px;
  border-radius: 10px;
}

.thinking-chevron {
  color: var(--text-secondary);
  transition: transform 0.2s;
  flex-shrink: 0;
}

.thinking-chevron.rotated {
  transform: rotate(90deg);
}

.thinking-body {
  padding: 8px 10px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-primary);
}

/* 工具调用 */
.tool-calls {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}

.tool-call-item {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
  opacity: 0.75;
  transition: opacity 0.2s;
}

.tool-call-item.tool-done {
  opacity: 1;
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
}

.tool-name {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: var(--text-primary);
  flex: 1;
}

.tool-check {
  font-size: 11px;
  color: var(--button-bg);
  font-weight: 600;
}

.tool-running-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: live-pulse 1s ease-in-out infinite;
}

.tool-args {
  padding: 5px 8px;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 80px;
  overflow-y: auto;
  background: var(--bg-primary);
}

.tool-result {
  padding: 6px 8px;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  background: var(--bg-primary);
  border-top: 1px solid var(--border-color);
}

.tool-expand-chevron {
  margin-left: auto;
  color: var(--text-secondary);
  transition: transform 0.2s;
  flex-shrink: 0;
}

.tool-expand-chevron.rotated {
  transform: rotate(90deg);
}

/* 推理文本 */
.reasoning-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  opacity: 0.8;
  padding: 2px 0;
}
</style>
