<template>
  <div :class="['message', message.role === 'user' ? 'user-message' : 'ai-message', (message.role === 'user' && message.additional_kwargs?.is_file && message.files?.length) ? 'files-only-message' : '']">
    <div :class="['message-wrapper', message.role === 'user' ? 'user-wrapper' : 'ai-wrapper', (message.role === 'user' && message.additional_kwargs?.is_file && message.files?.length) ? 'user-file-wrapper' : '']">
      <!-- 用户消息的复制按钮 — 气泡左侧 -->
      <div v-if="message.role === 'user' && message.content && !(message.additional_kwargs?.is_file && parsedFiles.length > 0)" class="user-message-copy">
        <button
          class="user-copy-button"
          :class="{ 'copy-success': userCopied }"
          @click="copyUserMessage"
          :title="userCopied ? '已复制' : '复制'"
        >
          <svg v-if="!userCopied" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </button>
      </div>

      <!-- 用户文件消息：独立显示 -->
      <div
        v-if="message.role === 'user' && message.additional_kwargs?.is_file && message.files?.length"
        class="user-files-display"
      >
        <!-- 图片文件：直接显示缩略图网格 -->
        <div v-if="imageFiles.length" class="file-images-grid">
          <div
            v-for="(file, index) in imageFiles"
            :key="index"
            class="file-image-item"
            @click="handleFileCardClick(file, index)"
          >
            <img
              v-if="getFilePreview(file)"
              :src="getFilePreview(file)"
              :alt="file.name"
              class="file-image-preview"
            />
            <div v-else class="file-image-placeholder">
              <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                <circle cx="8.5" cy="8.5" r="1.5"/>
                <polyline points="21 15 16 10 5 21"/>
              </svg>
            </div>
          </div>
        </div>

        <!-- 其他文件：水平排列的附件列表 -->
        <div v-if="otherFiles.length" class="file-attachments-list">
          <div
            v-for="(file, index) in otherFiles"
            :key="index"
            class="file-attachment-item"
            :class="getFileTypeClass(file)"
            @click="handleFileCardClick(file, index)"
          >
            <div class="file-attachment-icon">
              <!-- 文本文件图标 -->
              <svg v-if="isTextFileType(file)" xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
              <!-- PDF文件图标 -->
              <svg v-else-if="isPdfFileType(file)" xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
              <!-- 通用文件图标 -->
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
                <polyline points="13 2 13 9 20 9"/>
              </svg>
            </div>
            <div class="file-attachment-info">
              <span class="file-attachment-name">{{ file.name || `文件${index + 1}` }}</span>
              <span v-if="file.size_human" class="file-attachment-size">{{ file.size_human }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 普通消息内容区域（AI消息或非文件用户消息） -->
      <div v-else class="message-content">
        <!-- 文件附件显示（仅AI消息或非文件用户消息） -->
        <div v-if="message.files && message.files.length > 0" class="message-files">
          <div
            v-for="(file, index) in message.files"
            :key="index"
            class="file-attachment"
            @click="handleFileClick(file)"
          >
            <!-- 图片预览 -->
            <img
              v-if="(file.preview || file.iframe_url || file.preview_url) && isImageFile(file)"
              :src="file.preview || file.iframe_url || file.preview_url"
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
            <!-- 普通文件图标 -->
            <div v-else class="file-attachment-icon">
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
                <polyline points="10 9 9 9 8 9"/>
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

        <!-- 思考过程区块 -->
        <div v-if="message.role === 'ai' && hasThinking" class="thinking-section" :class="{ 'thinking-active': !message.thinkingDone, 'thinking-collapsed': thinkingCollapsed, 'thinking-interrupted': isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId) }">
          <div class="thinking-header" @click="toggleThinking">
            <div class="thinking-header-left">
              <span class="thinking-status-dot" :class="{ 'dot-active': !message.thinkingDone, 'dot-interrupted': isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId) }"></span>
              <span class="thinking-label">{{ isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId) ? '思考已中断' : (message.thinkingDone ? '思考过程' : '正在思考...') }}</span>
              <span v-if="isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId)" class="interrupt-reason-hint" @click.stop="toggleInterruptReason">
                {{ interruptReasonExpanded ? '隐藏原因' : '查看原因' }}
              </span>
              <span v-if="message.toolCalls && message.toolCalls.length" class="tool-badge">
                {{ message.toolCalls.length }} 个工具调用
              </span>
            </div>
            <svg class="thinking-chevron" :class="{ rotated: !thinkingCollapsed }" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </div>
          <div class="thinking-body" v-show="!thinkingCollapsed">
            <!-- 中断原因显示 -->
            <div v-if="isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId) && interruptReasonExpanded" class="interrupt-reason-inline">
              <span class="interrupt-reason-text">{{ displayInterruptReason }}</span>
            </div>
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
            <div v-if="message.reasoning" class="reasoning-text">{{ message.reasoning }}</div>
          </div>
        </div>

        <!-- 消息文本（文件消息不显示content） -->
        <div v-if="message.content && !message.additional_kwargs?.is_file" class="message-text" :class="{ 'collapsed': isUserMessageCollapsed }" v-html="isUserMessageCollapsed ? collapsedContent : renderedContent" @click.capture="handleLinkClick"></div>
        <button v-if="message.role === 'user' && message.content && isContentCollapsed" class="collapse-toggle" @click="toggleUserContent">
          {{ isUserMessageCollapsed ? '展开' : '收起' }}
        </button>

        <!-- 操作按钮组：AI 消息下方，hover 显示 -->
        <div v-if="message.role === 'ai'" class="action-buttons">
          <button v-if="message.streaming && hasReceivedInit && isLatestAiMessage && !isInterrupted" class="action-button interrupt-action" @click.stop="handleInterrupt" title="中断当前对话">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
            </svg>
          </button>
          <template v-else>
            <button class="action-button" @click="handleRestore" title="回溯到此对话">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="1 4 1 10 7 10"/>
                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
              </svg>
            </button>
            <button v-if="isLatestAiMessage && !isFirstAiMessage" class="action-button" @click="handleRestream" title="重新生成">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 2v6h-6"/>
                <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
                <path d="M3 22v-6h6"/>
                <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
              </svg>
            </button>
            <button class="action-button" @click="copyMessage" :title="copied ? '已复制' : '复制'">
              <svg v-if="!copied" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </button>
            <button v-if="isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId)" class="action-button resume-action" @click="$emit('resume')" title="续接对话">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3"/>
              </svg>
            </button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'

// 配置 marked
const renderer = new marked.Renderer()

// 自定义链接渲染器，修复 URL 识别问题
// marked v5+ 接收 token 对象
renderer.link = function(token) {
  const href = token.href || ''
  const title = token.title || ''
  const text = token.text || ''

  // 清理 URL 末尾的非法字符（中文标点、括号等）
  let cleanHref = href.replace(/[，。、；：？！""''（）【】《》…——]+$/, '')
  // 移除末尾不匹配的右括号
  cleanHref = cleanHref.replace(/\)+$/, (match) => {
    const openCount = (cleanHref.match(/\(/g) || []).length
    const closeCount = match.length
    if (closeCount > openCount) {
      return ')'.repeat(openCount)
    }
    return match
  })

  const titleAttr = title ? ` title="${title}"` : ''
  return `<a href="${cleanHref}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`
}

// 自定义图片渲染器，支持懒加载和路径处理
renderer.image = function(token) {
  let src = token.href || ''
  const alt = token.text || ''
  const title = token.title || ''

  if (!src) return alt || ''

  // 处理相对路径，拼接服务器基础 URL
  if (src.startsWith('./')) {
    // 相对路径：拼接当前域名 + /chat/static/ 前缀
    src = `${window.location.origin}/chat/static/${src.slice(2)}`
  } else if (src.startsWith('/Users/jx')) {
    // macOS 本地路径：/Users/jx/coding/projects/ChatMe/backend/cached/...
    // 转换成 /chat/static/cached/...
    src = src.replace('/Users/jx/coding/projects/ChatMe/backend', '/chat/static')
    src = `${window.location.origin}${src}`
  } else if (src.startsWith('/')) {
    // 其他以 / 开头的绝对路径
    src = `${window.location.origin}${src}`
  } else if (src.startsWith('http')) {
    // 已经是完整 URL（OSS 等），直接使用
  }

  const titleAttr = title ? ` title="${title}"` : ''
  // 添加 loading="lazy" 实现懒加载
  return `<img src="${src}" alt="${alt}"${titleAttr} loading="lazy" class="markdown-image" onclick="window.markdownImageClick && window.markdownImageClick(this)" />`
}

renderer.code = function(token) {
  // marked v5+ 接收 token 对象
  const code = token.text || ''
  const lang = token.lang || ''

  // 去除 infostring 中可能包含的元数据（如 {meta}）
  const langParts = lang.split(/\s+/)
  const cleanLang = langParts[0]

  // 检测并获取有效的高亮语言
  const language = cleanLang && hljs.getLanguage(cleanLang) ? cleanLang : 'plaintext'

  try {
    // 使用 highlight 方法，传入语言和配置
    const highlighted = hljs.highlight(code, { language }).value
    return `<pre><code class="hljs ${language}">${highlighted}</code></pre>`
  } catch (error) {
    // 高亮失败时返回纯文本
    console.warn('代码高亮失败:', error, '语言:', language)
    const escapedCode = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;')
    return `<pre><code class="hljs">${escapedCode}</code></pre>`
  }
}

marked.setOptions({
  breaks: true,
  gfm: true,
  renderer: renderer
})

export default {
  name: 'MessageItem',
  props: {
    message: {
      type: Object,
      required: true
    },
    isFirstAiMessage: {
      type: Boolean,
      default: false
    },
    isLatestAiMessage: {
      type: Boolean,
      default: false
    },
    isInterrupted: {
      type: Boolean,
      default: false
    },
    isInterruptedSessionId: {
      type: String,
      default: null
    },
    currentSessionId: {
      type: String,
      default: null
    },
    hasReceivedInit: {
      type: Boolean,
      default: false
    },
    pendingInterruptSessionId: {
      type: String,
      default: null
    }
  },
  emits: ['restore', 'restream', 'open-link', 'preview-file', 'interrupt', 'resume'],
  data() {
    return {
      copied: false,
      userCopied: false,
      // 如果消息已完成（thinkingDone: true），默认折叠思考区块
      thinkingCollapsed: this.message.thinkingDone === true,
      expandedTools: {},
      activeFileIndex: 0,
      isUserMessageCollapsed: false,
      interruptReasonExpanded: false
    }
  },
  computed: {
    renderedContent() {
      if (!this.message.content) return ''
      if (this.message.role === 'ai') {
        try {
          // 确保 content 是字符串
          let content = this.message.content
          if (typeof content !== 'string') {
            // 如果是对象，尝试提取内容
            if (content && typeof content === 'object') {
              if (content.text) {
                content = String(content.text)
              } else if (content.content) {
                content = String(content.content)
              } else {
                content = JSON.stringify(content)
              }
            } else {
              content = String(content)
            }
          }
          // 渲染 Markdown（先预处理清理 URL，防止 marked 错误匹配）
          let html = marked(this.preprocessContent(content))
          // 再渲染 LaTeX 数学公式
          html = this.renderLatex(html)
          return html
        } catch (error) {
          console.error('Markdown 渲染失败:', error, '原始内容:', this.message.content)
          // 降级处理，直接返回纯文本
          return this.escapeHtml(String(this.message.content))
        }
      }
      return this.escapeHtml(this.message.content)
    },
    hasThinking() {
      return (this.message.reasoning && this.message.reasoning.length > 0) ||
             (this.message.toolCalls && this.message.toolCalls.length > 0) ||
             (this.message.additional_kwargs?.type === 'REASONING')
    },
    displayInterruptReason() {
      const reason = this.message.interruptReason
      if (!reason) return '用户主动中断'
      // 映射技术 reason 字符串为友好中文
      const reasonMap = {
        'user_initiated_interrupt': '用户主动中断',
        'user_initiated': '用户主动中断',
        'max_tool_calls_exceeded': '工具调用次数超限',
        'timeout': '响应超时',
      }
      return reasonMap[reason] || reason
    },
    parsedFiles() {
      // 文件数据可能在 message.files 或 message.additional_kwargs.files 中
      const files = this.message.files || this.message.additional_kwargs?.files || []
      if (!Array.isArray(files)) return []
      return files
    },
    imageFiles() {
      // 图片类型文件
      const files = this.message.files || []
      return files.filter(f => this.isImageFileType(f))
    },
    otherFiles() {
      // 非图片类型文件
      const files = this.message.files || []
      return files.filter(f => !this.isImageFileType(f))
    },
    activeParsedFile() {
      // 直接从 message.files 或 additional_kwargs.files 获取
      const files = this.message.files || this.message.additional_kwargs?.files || []
      if (!Array.isArray(files) || files.length === 0) return null
      const idx = Math.min(this.activeFileIndex, files.length - 1)
      return files[idx] || null
    },
    isContentCollapsed() {
      // 用户消息超过8行则折叠
      if (this.message.role !== 'user') return false
      const lines = (this.message.content || '').split('\n').length
      return lines > 8
    },
    collapsedContent() {
      if (!this.isContentCollapsed) return this.message.content
      const lines = (this.message.content || '').split('\n')
      return lines.slice(0, 8).join('\n') + '\n...'
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
    // 预处理原始文本 - 只处理裸 URL，让 marked 原样处理 markdown 图片和链接
    preprocessContent(content) {
      if (typeof content !== 'string') return content

      // 策略：找到所有 markdown 图片和链接语法的位置，
      // 只处理不在这些语法内的裸 URL，避免破坏 markdown 语法

      // 找到所有需要跳过的 markdown 区域
      const skipRanges = []

      // 匹配图片 ![alt](url) 和链接 [text](url)
      // 使用括号计数找到正确的结束位置
      const findMarkdownRanges = (regex) => {
        let i = 0
        while (i < content.length) {
          const match = content.slice(i).match(regex)
          if (!match || match.index === undefined) break

          const start = i + match.index
          const firstParen = content.indexOf('(', start)
          if (firstParen === -1) break

          // 括号计数找到匹配的 )
          let depth = 1
          let j = firstParen + 1
          while (j < content.length && depth > 0) {
            if (content[j] === '(') depth++
            else if (content[j] === ')') depth--
            j++
          }
          const end = j

          skipRanges.push({ start, end })
          i = end
        }
      }

      findMarkdownRanges(/!?\[/)
      findMarkdownRanges(/(?<!!)\[/)

      // 去重并排序
      skipRanges.sort((a, b) => a.start - b.start)

      // 替换裸 URL（不在 markdown 语法内的）
      const urlRegex = /\b(https?|ftp|file):\/\/[^\s"'<>\[\]]+/gi
      let result = ''
      let lastEnd = 0

      for (const match of content.matchAll(urlRegex)) {
        const matchStart = match.index
        const matchEnd = match.index + match[0].length

        // 检查是否在需要跳过的区域内
        const inSkipRange = skipRanges.some(
          range => matchStart >= range.start && matchStart < range.end
        )

        if (inSkipRange) {
          continue
        }

        // 添加匹配前的文本
        result += content.slice(lastEnd, matchStart)
        // 添加转换后的 URL
        result += `<a href="${match[0]}" target="_blank" rel="noopener noreferrer">${match[0]}</a>`
        lastEnd = matchEnd
      }
      result += content.slice(lastEnd)

      return result
    },

    highlightCode() {
      const codeBlocks = this.$el.querySelectorAll('pre code')
      codeBlocks.forEach(block => {
        if (!block.classList.contains('hljs')) {
          hljs.highlightElement(block)
        }
      })

      // 为每个代码块的 pre 元素添加复制点击事件
      const preElements = this.$el.querySelectorAll('pre')
      preElements.forEach(pre => {
        pre.addEventListener('click', (e) => {
          const rect = pre.getBoundingClientRect()
          const x = e.clientX - rect.left
          const y = e.clientY - rect.top

          // 复制按钮区域：右上角
          if (x >= rect.width - 40 && y <= 30) {
            e.stopPropagation()
            const code = pre.querySelector('code')
            if (code) {
              navigator.clipboard.writeText(code.textContent).then(() => {
                // 添加 copied 类来改变图标
                pre.classList.add('copied')
                setTimeout(() => {
                  pre.classList.remove('copied')
                }, 2000)
              }).catch(err => {
                console.error('复制失败:', err)
              })
            }
          }
        })
      })
    },
    toggleUserContent() {
      this.isUserMessageCollapsed = !this.isUserMessageCollapsed
    },
    escapeHtml(text) {
      const div = document.createElement('div')
      div.textContent = text
      return div.innerHTML
    },

    renderLatex(html) {
      if (!html || typeof html !== 'string') return html

      // 渲染块级公式 $$...$$ （displayMode）
      html = html.replace(/\$\$([\s\S]+?)\$\$/g, (match, tex) => {
        try {
          return katex.renderToString(tex.trim(), {
            displayMode: true,
            throwOnError: false,
            errorColor: '#cc0000'
          })
        } catch (e) {
          console.warn('KaTeX block render failed:', e)
          return `<span class="katex-error" title="${this.escapeHtml(e.message)}">$$${tex}$$</span>`
        }
      })

      // 渲染行内公式 $...$ （非 displayMode）
      // 排除已处理的块级公式区域，以及 HTML 标签和代码块内的 $
      // 策略：找到所有 pre/code/span.katex 区域并保护起来，再处理剩余的 $
      const protectedRanges = []
      // 保护代码块
      let i = 0
      while (i < html.length) {
        const preMatch = html.slice(i).match(/<pre>[\s\S]*?<\/pre>/i)
        if (preMatch) {
          protectedRanges.push({ start: i + preMatch.index, end: i + preMatch.index + preMatch[0].length })
          i += preMatch.index + preMatch[0].length
        } else break
      }
      // 保护已有的 katex 渲染结果
      i = 0
      while (i < html.length) {
        const spanMatch = html.slice(i).match(/<span class="katex[^"]*"[^>]*>[\s\S]*?<\/span>/i)
        if (spanMatch) {
          protectedRanges.push({ start: i + spanMatch.index, end: i + spanMatch.index + spanMatch[0].length })
          i += spanMatch.index + spanMatch[0].length
        } else break
      }
      // 保护行内代码
      i = 0
      while (i < html.length) {
        const codeMatch = html.slice(i).match(/<code[^>]*>[\s\S]*?<\/code>/i)
        if (codeMatch) {
          protectedRanges.push({ start: i + codeMatch.index, end: i + codeMatch.index + codeMatch[0].length })
          i += codeMatch.index + codeMatch[0].length
        } else break
      }

      // 对非保护区域替换行内 $
      let result = ''
      let lastEnd = 0
      // 去重排序
      protectedRanges.sort((a, b) => a.start - b.start)
      // 简单检查重叠并合并
      const merged = []
      for (const r of protectedRanges) {
        if (merged.length === 0 || r.start > merged[merged.length - 1].end) {
          merged.push(r)
        } else {
          merged[merged.length - 1].end = Math.max(merged[merged.length - 1].end, r.end)
        }
      }

      const inlineMathRegex = /\$([^$\n]+?)\$/g
      let lastIndex = 0
      inlineMathRegex.lastIndex = 0
      let match

      while ((match = inlineMathRegex.exec(html)) !== null) {
        const matchStart = match.index
        const matchEnd = match.index + match[0].length
        // 检查是否在保护区域内
        const protected_ = merged.some(r => matchStart >= r.start && matchStart < r.end)
        if (protected_) continue
        // 添加匹配前的文本
        result += html.slice(lastIndex, matchStart)
        // 渲染 LaTeX
        const tex = match[1]
        try {
          result += katex.renderToString(tex.trim(), {
            displayMode: false,
            throwOnError: false,
            errorColor: '#cc0000'
          })
        } catch (e) {
          console.warn('KaTeX inline render failed:', e)
          result += `<span class="katex-error" title="${this.escapeHtml(e.message)}">$${tex}$</span>`
        }
        lastIndex = matchEnd
      }
      result += html.slice(lastIndex)

      return result
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

    async copyUserMessage() {
      try {
        await navigator.clipboard.writeText(this.message.content)
        this.userCopied = true
        setTimeout(() => {
          this.userCopied = false
        }, 2000)
      } catch (err) {
        console.error('复制失败:', err)
      }
    },

    handleLinkClick(e) {
      const anchor = e.target.closest('a')
      if (!anchor) return
      const href = anchor.getAttribute('href')
      if (!href || !href.startsWith('http')) return
      e.preventDefault()
      this.$emit('open-link', href)
    },

    handleRestore() {
      if (this.message.checkpointId) {
        this.$emit('restore', this.message.checkpointId)
      }
    },

    handleRestream() {
      // 直接传递整个消息对象，让 App.vue 处理 fallback 逻辑
      this.$emit('restream', null, this.message)
    },

    handleInterrupt(e) {
      e.stopPropagation()
      this.$emit('interrupt')
    },

    handleResume() {
      this.$emit('resume')
    },

    handleFileClick(file) {
      // 发送预览文件事件，让 App.vue 在 WebPreviewPanel 中打开
      this.$emit('preview-file', file)
    },

    isImageFile(file) {
      if (!file.type && !file.file_type) return false
      // 检查大写的 file_type（如 "IMAGE"）和 type（如 "image/png"）
      if (file.file_type === 'IMAGE' || file.type === 'IMAGE') return true
      return file.type && file.type.startsWith('image/')
    },

    isTextFile(file) {
      if (!file.type && !file.file_type) return false
      // 检查大写的 file_type（如 "TEXT"）和 type（如 "text/plain"）
      if (file.file_type === 'TEXT' || file.type === 'TEXT') return true
      return file.type && (file.type.startsWith('text/') ||
             file.type === 'application/json' ||
             file.type === 'text/csv' ||
             file.type === 'text/xml')
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
    toggleThinking() {
      this.thinkingCollapsed = !this.thinkingCollapsed
    },
    toggleInterruptReason() {
      this.interruptReasonExpanded = !this.interruptReasonExpanded
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
    },
    getFileTypeLabel(type) {
      if (!type) return '未知'
      const typeMap = {
        'image': '图片',
        'pdf': 'PDF',
        'doc': 'Word',
        'docx': 'Word',
        'text': '文本',
        'txt': '文本',
        'csv': 'CSV',
        'json': 'JSON',
        'markdown': 'Markdown',
        'md': 'Markdown'
      }
      const lowerType = (type || '').toLowerCase()
      for (const [key, label] of Object.entries(typeMap)) {
        if (lowerType.includes(key)) return label
      }
      return type || '未知'
    },
    renderFileContent(content) {
      if (!content) return ''
      // 使用 marked 渲染 markdown 内容
      try {
        return marked(content)
      } catch (e) {
        console.warn('文件内容 markdown 渲染失败:', e)
        return this.escapeHtml(content)
      }
    },
    handleImageClick(src) {
      // 触发图片预览事件
      if (src) {
        this.$emit('preview-file', { preview: src, url: src, name: '图片预览' })
      }
    },
    // 文件类型判断方法
    isImageFileType(file) {
      if (!file) return false
      const type = (file.type || file.file_type || '').toUpperCase()
      return type === 'IMAGE' || (file.type && file.type.startsWith('image/'))
    },
    isTextFileType(file) {
      if (!file) return false
      const type = (file.type || file.file_type || '').toUpperCase()
      return type === 'TEXT' || (file.type && file.type.startsWith('text/'))
    },
    isPdfFileType(file) {
      if (!file) return false
      const suffix = (file.suffix || '').toLowerCase()
      const type = (file.type || '').toLowerCase()
      return suffix === '.pdf' || type.includes('pdf')
    },
    getFilePreview(file) {
      if (!file) return null
      // 图片预览URL优先级
      if (file.preview) return file.preview
      if (file.preview_url) return file.preview_url
      if (file.image_content) {
        if (typeof file.image_content === 'string') return file.image_content
        if (Array.isArray(file.image_content)) {
          // 如果是数组，取第一个元素的url
          if (file.image_content.length > 0) {
            const first = file.image_content[0]
            if (typeof first === 'string') return first
            if (typeof first === 'object' && first.url) return first.url
          }
        }
      }
      return null
    },
    hasTextPreview(file) {
      // 检查文件是否有文本预览内容（TEXT类型且有text_content或content）
      if (!file) return false
      const isText = file.type === 'TEXT' || (file.type && file.type.startsWith('text/'))
      return isText && (file.text_content || file.content)
    },
    getFileTypeClass(file) {
      if (this.isTextFileType(file)) return 'file-type-text'
      if (this.isPdfFileType(file)) return 'file-type-pdf'
      return 'file-type-other'
    },
    handleFileCardClick(file, index) {
      // 记录当前选中的文件索引
      this.activeFileIndex = index

      // 根据文件类型决定处理方式
      const isImage = this.isImageFileType(file)
      const isText = this.isTextFileType(file)
      const isPdf = this.isPdfFileType(file)

      // 图片文件：直接弹出预览
      if (isImage) {
        const previewUrl = this.getFilePreview(file)
        if (previewUrl) {
          this.$emit('preview-file', {
            preview_url: previewUrl,
            url: previewUrl,
            name: file.name,
            type: file.type,
            file_type: file.file_type || file.type,
            suffix: file.suffix,
            image_content: file.image_content
          })
        }
      }
      // 文本文件：如果有内容则使用 FilePreviewPanel 渲染 markdown
      else if (isText) {
        const textContent = file.text_content || file.content
        if (typeof textContent === 'string' && textContent.trim().length > 0) {
          this.$emit('preview-file', {
            name: file.name,
            type: file.type,
            file_type: file.file_type,
            suffix: file.suffix,
            text_content: textContent,
            content: textContent
          })
        } else {
          const previewUrl = file.iframe_url || file.preview_url
          if (previewUrl) {
            this.$emit('preview-file', {
              preview_url: previewUrl,
              url: previewUrl,
              name: file.name,
              type: file.type,
              file_type: file.file_type,
              suffix: file.suffix,
              preview_method: file.preview_method
            })
          }
        }
      }
      // PDF 文件
      else if (isPdf) {
        const previewUrl = file.preview_url || file.iframe_url
        if (previewUrl) {
          this.$emit('preview-file', {
            preview_url: previewUrl,
            url: previewUrl,
            name: file.name,
            type: file.type,
            file_type: file.file_type,
            suffix: file.suffix,
            preview_method: file.preview_method
          })
        }
      }
      // Office 文档（.doc/.ppt/.xls 转换后的 .docx/.pptx/.xlsx 或原始上传）
      else {
        const previewUrl = file.preview_url || file.iframe_url
        if (previewUrl) {
          this.$emit('preview-file', {
            preview_url: previewUrl,
            url: previewUrl,
            name: file.name,
            type: file.type,
            file_type: file.file_type,
            suffix: file.suffix,
            preview_method: file.preview_method
          })
        }
      }
    }
  }
}
</script>

<style scoped>
.message {
  display: flex;
  flex-direction: column;
  margin-bottom: 28px;
  width: 100%;
}

.user-message {
  align-items: flex-end;
}

/* 仅文件消息的用户消息，宽度自适应内容 */
.files-only-message .user-wrapper {
  max-width: 80%;
}

/* 文件消息隐藏气泡框但保留内容显示 */
.files-only-message .message-content {
  background: transparent !important;
  border: none !important;
  padding: 0 !important;
  width: auto !important;
  max-width: 100% !important;
}

.ai-message {
  align-items: flex-start;
}

/* AI wrapper：全宽，无气泡 */
.ai-wrapper {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  align-items: flex-start;
}

/* User wrapper：右对齐，收缩气泡，relative 用于定位复制按钮 */
.user-wrapper {
  display: flex;
  flex-direction: row;
  max-width: 68%;
  align-items: flex-end;
  position: relative;
}

/* 用户文件消息 wrapper：全宽显示 */
.user-file-wrapper {
  max-width: 100%;
  align-items: flex-start;
}

.message-content {
  border-radius: 16px;
  position: relative;
}

/* AI：无气泡，必须显式填满宽度，否则 pre 的 max-width: 100% 无法正确参照 */
.ai-message .message-content {
  background: transparent;
  border: none;
  padding: 0;
  width: 100%;
}

/* User：圆角气泡（文件消息隐藏气泡背景） */
.user-message .message-content {
  background-color: var(--user-msg-bg);
  border: 1px solid var(--user-msg-border);
  padding: 10px 14px;
  width: fit-content;
  max-width: 100%;
  position: relative;
}

/* 文件用户消息隐藏气泡 */
.user-message.files-only-message .message-content,
.user-message:has(.user-files-display) .message-content {
  display: none;
}

/* 当message-wrapper包含user-files-display时，隐藏同级的message-content */
.user-message .message-wrapper:has(.user-files-display) > .message-content {
  display: none;
}

.user-message:hover .user-message-copy {
  opacity: 1;
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
  word-break: break-word;
  font-size: 15px;
  min-width: 0;
}

.user-message .message-text {
  white-space: pre-wrap;
}

.message-text.collapsed {
  max-height: 20em;
  overflow: hidden;
  position: relative;
}

.message-text.collapsed::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 60px;
  background: linear-gradient(transparent, var(--user-bubble-bg));
  pointer-events: none;
}

.collapse-toggle {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 2px 8px;
  cursor: pointer;
  margin-top: 2px;
}

.collapse-toggle:hover {
  color: var(--button-bg);
}

/* Markdown 样式 */
.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3),
.message-text :deep(h4),
.message-text :deep(h5),
.message-text :deep(h6) {
  margin: 20px 0 12px;
  font-weight: 1000;
  line-height: 1.4;
  color: var(--text-primary);
}

.message-text :deep(h1) { font-size: 1.7em; font-weight: 1000; color: #16a34a; }
.message-text :deep(h2) { font-size: 1.45em; font-weight: 900; color: #16a34a; }
.message-text :deep(h3) { font-size: 1.25em; font-weight: 900; color: #16a34a; }
.message-text :deep(h4) { font-size: 1.1em; color: var(--text-primary); }
.message-text :deep(h5) { font-size: 1em; color: var(--text-primary); }
.message-text :deep(h6) { font-size: 0.9em; color: var(--text-secondary); }

.message-text :deep(p) {
  margin: 10px 0;
}

.message-text :deep(strong),
.message-text :deep(b) {
  font-weight: 1000;
  color: var(--text-primary);
}

.message-text :deep(em),
.message-text :deep(i) {
  font-style: italic;
  color: var(--text-secondary);
}

.message-text :deep(code) {
  background: var(--code-inline-bg);
  padding: 3px 8px;
  border-radius: 6px;
  font-family: 'SF Mono', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.85em;
  color: var(--code-inline-color);
  font-weight: 400;
}

.message-text :deep(pre) {
  background: var(--code-block-bg);
  padding: 16px 20px;
  border-radius: 12px;
  overflow-x: auto;
  margin: 16px 0;
  border: 1px solid var(--code-block-border);
  position: relative;
  line-height: 1.6;
  box-shadow: var(--code-block-shadow);
}

.message-text :deep(pre code) {
  background: transparent;
  padding: 0;
  color: var(--code-block-text);
  font-size: 13.5px;
  line-height: 1.65;
  font-weight: 400;
  font-family: 'SF Mono', 'Monaco', 'Consolas', 'Courier New', monospace;
}

.message-text :deep(pre code.hljs) {
  background: transparent !important;
  color: var(--code-block-text);
}

.message-text :deep(pre[data-language])::before {
  content: attr(data-language);
  position: absolute;
  top: 8px;
  right: 50px;
  font-size: 11px;
  font-weight: 500;
  color: var(--code-lang-color);
  letter-spacing: 0.03em;
  pointer-events: none;
  background: var(--code-lang-bg);
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--code-lang-border);
}

.message-text :deep(pre)::after {
  content: '';
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='9' y='9' width='13' height='13' rx='2' ry='2'/%3E%3Cpath d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  background-color: var(--code-lang-bg);
  border: 1px solid var(--code-lang-border);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  opacity: 0;
}

.message-text :deep(pre:hover)::after {
  opacity: 1;
}

.message-text :deep(pre)::after:hover {
  background-color: var(--button-bg);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='9' y='9' width='13' height='13' rx='2' ry='2'/%3E%3Cpath d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/%3E%3C/svg%3E");
  border-color: var(--button-bg);
}

.message-text :deep(pre.copied)::after {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E");
  background-color: var(--code-lang-bg);
  border-color: var(--code-lang-border);
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

.message-text :deep(del),
.message-text :deep(s),
.message-text :deep(strike) {
  color: #1a1a1a;
  font-weight: 700;
  text-decoration: none;
  background: none;
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

/* Markdown 图片自适应大小（最大高度限制，保持比例） */
.message-text :deep(.markdown-image) {
  max-height: 150px;
  width: auto;
  height: auto;
  object-fit: contain;
}

/* 操作按钮组：AI 文本下方，hover 显示 */
.action-buttons {
  display: flex;
  gap: 1px;
  margin-top: 4px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.ai-wrapper:hover .action-buttons,
.action-buttons:hover,
.action-buttons.show-interrupt {
  opacity: 1;
}

.action-button {
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 5px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.action-button:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.action-button.copy-success,
.action-button.copy-success:hover {
  background: transparent;
  color: var(--text-secondary);
}

.interrupt-action {
  color: #ef4444;
}

.interrupt-action:hover {
  background: #fef2f2;
  color: #dc2626;
}

.resume-action {
  color: #10a37f;
}

.resume-action:hover {
  background: #ecfdf5;
  color: #059669;
}

/* 用户消息复制按钮 — 气泡左侧 */
.user-message-copy {
  display: flex;
  align-items: flex-end;
  padding-right: 6px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.user-message-copy > * {
  pointer-events: auto;
}

.user-message:hover .user-message-copy,
.user-message-copy:hover {
  opacity: 1;
}

.user-copy-button {
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 5px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.user-copy-button:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.user-copy-button.copy-success,
.user-copy-button.copy-success:hover {
  background: transparent;
  color: var(--text-secondary);
}

/* 用户文件消息显示区域 */
.user-files-display {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-start;
}

/* 用户文本消息（在文件下方显示） */
.user-message-text {
  width: 100%;
  margin-top: 8px;
  padding: 0;
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-wrap: break-word;
  word-break: break-word;
  min-width: 0;
}

/* 图片文件网格 */
.file-images-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.file-image-item {
  width: 120px;
  height: 120px;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  transition: all 0.15s;
}

.file-image-item:hover {
  border-color: var(--button-bg);
  transform: scale(1.03);
}

.file-image-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-image-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}

/* 文件附件列表 */
.file-attachments-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.file-attachment-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
  max-width: 300px;
  min-width: 180px;
}

.file-attachment-item:hover {
  border-color: var(--button-bg);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

/* 文件类型颜色 */
.file-attachment-item.file-type-text {
  border-left: 3px solid #667eea;
}

.file-attachment-item.file-type-pdf {
  border-left: 3px solid #ff6b6b;
}

.file-attachment-item.file-type-other {
  border-left: 3px solid var(--text-secondary);
}

.file-attachment-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  flex-shrink: 0;
}

.file-type-text .file-attachment-icon {
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
}

.file-type-pdf .file-attachment-icon {
  background: rgba(255, 107, 107, 0.1);
  color: #ff6b6b;
}

.file-type-other .file-attachment-icon {
  background: var(--bg-secondary);
  color: var(--text-secondary);
}

.file-attachment-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.file-attachment-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-attachment-size {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.preview-body {
  font-size: 13px;
  line-height: 1.6;
}

.preview-text-content {
  color: var(--text-primary);
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.preview-text-content :deep(pre) {
  background: var(--code-block-bg);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12px;
}

.preview-text-content :deep(code) {
  background: var(--code-inline-bg);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

.file-preview-iframe {
  width: 100%;
  height: 400px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
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

.thinking-section.thinking-interrupted {
  border-color: #ef4444;
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

.thinking-status-dot.dot-interrupted {
  background: #ef4444;
  opacity: 1;
  animation: none;
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
  padding: 1px 8px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--button-bg) 20%, transparent);
  font-weight: 500;
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

/* KaTeX 错误样式 */
.message-text :deep(.katex-error) {
  color: #cc0000;
  cursor: help;
}

/* KaTeX 块级公式样式 */
.message-text :deep(.katex-display) {
  margin: 16px 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
}

.message-text :deep(.katex) {
  font-size: 1.1em;
}
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

/* 中断原因提示 */
.interrupt-reason-hint {
  font-size: 11px;
  color: #ef4444;
  cursor: pointer;
  padding: 1px 8px;
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.1);
  transition: background 0.15s;
  border: 1px solid rgba(239, 68, 68, 0.2);
  font-weight: 500;
}

.interrupt-reason-hint:hover {
  background: rgba(239, 68, 68, 0.2);
}

/* 中断原因内联显示 */
.interrupt-reason-inline {
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  margin-bottom: 8px;
}

.interrupt-reason-text {
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
