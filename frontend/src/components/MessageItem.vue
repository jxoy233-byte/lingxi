<template>
  <div :class="['message', message.role === 'user' ? 'user-message' : 'ai-message', (message.role === 'user' && message.additional_kwargs?.is_file && message.files?.length) ? 'files-only-message' : '']">
    <div :class="['message-wrapper', message.role === 'user' ? 'user-wrapper' : 'ai-wrapper', (message.role === 'user' && message.additional_kwargs?.is_file && message.files?.length) ? 'user-file-wrapper' : '']">
      <!-- 用户消息的复制 + 撤回按钮组 — 气泡左侧 -->
      <div v-if="message.role === 'user' && (message.content || (message.additional_kwargs?.is_file && parsedFiles.length > 0))" class="user-message-actions">
        <button
          v-if="message.content && !(message.additional_kwargs?.is_file && parsedFiles.length > 0)"
          class="user-action-button"
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
        <button
          v-if="canWithdraw"
          class="user-action-button user-withdraw-button"
          @click="withdrawUserMessage"
          title="撤回：中断当前工作流并回溯到上一轮，把这条消息的文本放回输入框"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7v6h6"/>
            <path d="M21 17a9 9 0 0 0-15-6.7L3 13"/>
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
            <span v-if="showMetrics" class="thinking-header-metrics">
              {{ formatElapsed(metricsElapsedSec) }} · {{ formatTokenCount(metricsTokenTotal) }}
            </span>
            <svg class="thinking-chevron" :class="{ rotated: !effectiveThinkingCollapsed }" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </div>
          <div class="thinking-body" v-show="!effectiveThinkingCollapsed">
            <!-- 中断原因显示 -->
            <div v-if="isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId) && interruptReasonExpanded" class="interrupt-reason-inline">
              <span class="interrupt-reason-text">{{ displayInterruptReason }}</span>
            </div>
            <div v-if="message.toolCalls && message.toolCalls.length" class="tool-calls">
              <div
                v-for="(tool, i) in message.toolCalls"
                :key="i"
                class="tool-call-item"
                :class="{
                  'tool-done': tool.result !== null,
                  'awaiting-approval': isToolAwaitingApproval(i)
                }"
              >
                <div class="tool-call-header" @click="toggleTool(i)" :style="tool.result !== null ? 'cursor:pointer' : ''">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                  </svg>
                  <span class="tool-name">{{ tool.name }}</span>
                  <span v-if="getToolExecutionEnv(tool.name, tool.args)" class="tool-env-label" :class="`env-${getToolExecutionEnv(tool.name, tool.args)}`">:: {{ getToolExecutionEnv(tool.name, tool.args) }}</span>
                  <span v-if="isToolAwaitingApproval(i)" class="tool-awaiting-badge">需要批准</span>
                  <span v-else-if="tool.result !== null" class="tool-check">✓</span>
                  <span v-else class="tool-running-dot"></span>
                  <svg v-if="tool.result !== null" class="tool-expand-chevron" :class="{ rotated: expandedTools[i] }" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="9 18 15 12 9 6"/>
                  </svg>
                </div>
                <div v-if="tool.args && hasArgs(tool.args, tool.name)" class="tool-args">{{ formatArgs(tool.args, tool.name) }}</div>
                <div v-if="tool.result !== null && expandedTools[i]" class="tool-result">{{ tool.result }}</div>

                <!-- 内嵌审批 UI：仅当此 tool 是当前 pending 审批目标时渲染 -->
                <div v-if="isToolAwaitingApproval(i)" class="tool-inline-approval" :class="`tool-inline-approval--${getToolExecutionEnv(tool.name, tool.args) || 'sandbox'}`">
                  <div class="tool-inline-approval-header">
                    <!-- local 时换成警告符号 ⚠️ 提醒用户走的是本机执行（不是沙盒隔离） -->
                    <svg v-if="getToolExecutionEnv(tool.name, tool.args) !== 'local'" class="tool-inline-approval-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M12 2L4 6v6c0 5 3.5 9.5 8 10 4.5-.5 8-5 8-10V6l-8-4z"
                        stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                      <path d="M9 12l2 2 4-4" stroke="currentColor" stroke-width="1.8"
                        stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span v-else class="tool-inline-approval-warn">⚠️</span>
                    <span>需要批准这个 {{ pendingToolApproval.action }} 操作吗？</span>
                  </div>
                  <!-- 默认 4 选项：取消 / 仅本次 / 告诉 AI 怎么做 / 批准 -->
                  <div v-if="!feedbackExpanded[i]" class="tool-inline-approval-actions">
                    <button
                      class="tool-btn-deny"
                      :disabled="submittingToolDecision"
                      @click.stop="emitToolDecision('deny')"
                    >取消</button>
                    <button
                      class="tool-btn-once"
                      :disabled="submittingToolDecision"
                      @click.stop="emitToolDecision('this-time-only')"
                    >仅本次</button>
                    <button
                      class="tool-btn-feedback"
                      :disabled="submittingToolDecision"
                      @click.stop="toggleFeedback(i)"
                    >告诉 AI 怎么做</button>
                    <button
                      class="tool-btn-approve"
                      :disabled="submittingToolDecision"
                      @click.stop="emitToolDecision('approve')"
                    >批准</button>
                  </div>
                  <!-- 反馈模式：textarea + 取消/发送 两个按钮 -->
                  <div v-else class="tool-inline-feedback">
                    <textarea
                      v-model="feedbackText[i]"
                      class="tool-feedback-textarea"
                      placeholder="例如：用 Python sandbox；先列出将删除的文件再删；不要递归 ..."
                      :disabled="submittingToolDecision"
                      rows="3"
                      @click.stop
                    ></textarea>
                    <div class="tool-inline-feedback-actions">
                      <button
                        class="tool-btn-deny"
                        :disabled="submittingToolDecision"
                        @click.stop="cancelFeedback(i)"
                      >取消</button>
                      <button
                        class="tool-btn-approve"
                        :disabled="submittingToolDecision || !(feedbackText[i] || '').trim()"
                        @click.stop="submitFeedback(i)"
                      >发送给 AI</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="message.reasoning" class="reasoning-text">{{ message.reasoning }}</div>
          </div>
        </div>

        <!-- 用户消息：可能包含引用块 + 正文 -->
        <div v-if="message.role === 'user' && message.content && !message.additional_kwargs?.is_file" class="user-message-body">
          <div v-if="parsedUserContent.quote" class="user-quote-block">
            <div class="quote-block-bar"></div>
            <div class="quote-block-content">
              <div class="quote-block-label">
                <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V20c0 1 0 1 1 1z"/>
                  <path d="M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3c0 1 0 1 1 1z"/>
                </svg>
                <span>引用</span>
              </div>
              <div class="quote-block-text" v-html="renderedQuote"></div>
            </div>
          </div>
          <div
            v-if="renderedUserText"
            class="message-text"
            :class="{ 'collapsed': effectiveUserCollapsed }"
            v-html="effectiveUserCollapsed ? collapsedUserText : renderedUserText"
            @click.capture="handleLinkClick"
            @click="handleMarkdownImageClick"
          ></div>
          <button v-if="isContentCollapsed" class="collapse-toggle" @click="toggleUserContent">
            {{ isUserMessageCollapsed ? '收起' : '展开' }}
          </button>
        </div>

        <!-- AI 错误消息：与正常文本渲染区分开，避免报错堆栈被当成 markdown -->
        <div v-else-if="message.error" class="message-error-box">
          <svg class="message-error-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <div class="message-error-content">{{ message.content }}</div>
        </div>

        <!-- AI 消息文本（文件消息不显示content） -->
        <div v-else-if="message.content && !message.additional_kwargs?.is_file" class="message-text" :class="{ 'collapsed': isUserMessageCollapsed }" v-html="isUserMessageCollapsed ? collapsedContent : renderedContent" @click.capture="handleLinkClick" @click="handleMarkdownImageClick"></div>

        <!-- 操作按钮组：AI 消息下方，hover 显示 -->
        <div v-if="message.role === 'ai'" class="action-buttons">
          <button v-if="message.streaming && hasReceivedInit && isLatestAiMessage && !isInterrupted" class="action-button interrupt-action" @click.stop="handleInterrupt" title="中断当前对话">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
            </svg>
          </button>
          <template v-else>
            <button v-if="canBacktrack" class="action-button" @click="handleRestore" title="回溯到此对话">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="1 4 1 10 7 10"/>
                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
              </svg>
            </button>
            <button v-if="canRestream" class="action-button" @click="handleRestream" title="重新生成">
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
            <button
              v-if="canExportTurn"
              class="action-button"
              :disabled="exporting"
              @click="exportTurn"
              :title="exporting ? '导出中…' : '导出到本轮为止的对话（OpenAI 格式 + 软件备份）'"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </button>
            <button v-if="isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId)" class="action-button resume-action" @click="$emit('resume')" title="续接对话">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3"/>
              </svg>
            </button>
            <button v-if="isInterrupted && isLatestAiMessage && (isInterruptedSessionId === currentSessionId || isInterruptedSessionId === pendingInterruptSessionId)" class="action-button" @click="$emit('restart-session')" title="重新对话">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            </button>
          </template>
        </div>
      </div>
    </div>

    <!-- 文件预览弹窗 -->
    <FilePreviewModal
      :visible="previewVisible"
      :file="previewFile"
      @close="closePreview"
    />

    <!-- 浮动引用按钮（用户选中文本后出现） -->
    <div
      v-if="quoteButtonVisible"
      class="quote-floating-btn"
      :style="{ top: quoteButtonPos.top + 'px', left: quoteButtonPos.left + 'px' }"
      @mousedown.prevent
      @click="handleQuoteClick"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
        <path d="M9.983 3v7.391c0 5.704-3.731 9.57-8.983 10.609l-.995-2.151c2.432-.917 3.995-3.638 3.995-5.849h-4v-10h9.983zm14.017 0v7.391c0 5.704-3.748 9.571-9 10.609l-.996-2.151c2.433-.917 3.996-3.638 3.996-5.849h-3.983v-10h9.983z"/>
      </svg>
      <span>引用</span>
    </div>
  </div>
</template>

<script>
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import mermaid from 'mermaid'
import FilePreviewModal from './FilePreviewModal.vue'
import { sanitizeHtml } from '@/utils/sanitize.js'

// 初始化 mermaid（可拖拽交互）
mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  flowchart: { htmlLabels: true, curve: 'basis', useMaxWidth: false },
  securityLevel: 'loose',
})

// 文本/代码类扩展名：双中括号 [[...]] 和 markdown 链接走「纯文本预览」分支
// 不含 .md/.markdown（走 Markdown 渲染）、不含 .html/.htm（走 iframe）
// 不含图片/pdf/office（走各自预览分支）
const TEXT_FILE_EXTS = new Set([
  // 数据 / 配置
  'csv', 'tsv', 'json', 'jsonl', 'xml', 'yml', 'yaml', 'toml', 'ini', 'env', 'conf', 'cfg', 'properties', 'log',
  // Python
  'py', 'pyw',
  // JavaScript / TypeScript / 前端
  'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'vue', 'css', 'scss', 'less',
  // Shell / 脚本
  'sh', 'bash', 'zsh', 'ps1', 'bat',
  // 其他常见语言
  'java', 'kt', 'go', 'rs', 'rb', 'php', 'swift', 'c', 'cpp', 'cc', 'h', 'hpp', 'cs',
  // 其他
  'sql', 'r', 'lua', 'dart', 'scala', 'pl', 'diff', 'dockerfile', 'makefile', 'txt',
])

// 配置 marked v17+：使用 extensions.renderers API（推荐写法）
marked.use({
  renderer: {
    // marked v17 把整个 token 对象作为参数传入
    link(token) {
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
    },
    image(token) {
      let src = token.href || ''
      const alt = token.text || ''
      const title = token.title || ''

      if (!src) return alt || ''

      // 处理相对路径，转成 /static/ 开头的绝对路径（不带 origin）。
// 不带 origin 是关键：vite dev 下浏览器解析成 http://localhost:18211/static/...
// 走 vite proxy → 8211；Electron file:// 下解析成 file:///static/... → file:// 协议
// 拦截器命中 pathname.startsWith('/static/') → net.fetch 转 backend。
// 若带 window.location.origin（file:// 时为 "null"），浏览器把 "null/..." 视作无效 URL
// 直接静默失败，<img> 不发请求——mmd/html 没这问题是因为它们直接用相对路径
// fetch/iframe src。
      if (src.startsWith('./')) {
        src = `/static/${src.slice(2)}`
      }

      const titleAttr = title ? ` title="${title}"` : ''
      return `<img src="${src}" alt="${alt}"${titleAttr} loading="lazy" class="markdown-image" data-markdown-image="true" />`
    },
    code(token) {
      // marked v17 接收整个 token 对象
      const code = token.text || ''
      const lang = token.lang || ''

      // 去除 infostring 中可能包含的元数据（如 {meta}）
      const langParts = lang.split(/\s+/)
      const cleanLang = langParts[0]

      // 检测并获取有效的高亮语言
      const language = cleanLang && hljs.getLanguage(cleanLang) ? cleanLang : 'plaintext'

      try {
        const highlighted = hljs.highlight(code, { language }).value
        return `<pre><code class="hljs ${language}">${highlighted}</code></pre>`
      } catch (error) {
        console.warn('代码高亮失败:', error, '语言:', lang)
        const escapedCode = code
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#039;')
        return `<pre><code class="hljs">${escapedCode}</code></pre>`
      }
    }
  },
  breaks: true,
  gfm: true
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
    },
    messageIndex: {
      // 当前消息在父 messages 数组中的索引；用于判断此消息是否含有待审批的 tool call
      type: Number,
      default: -1
    },
    pendingToolApproval: {
      // 内嵌审批：{ messageIndex, toolIndex, command, action, sessionId } | null
      type: Object,
      default: null
    },
    submittingToolDecision: {
      type: Boolean,
      default: false
    },
    canWithdraw: {
      // 撤回按钮是否可点：父级（App.vue）根据「是否有上一轮 AI 消息 + 该 AI 是否有 checkpointId」判断。
      // 首条用户消息无前一轮可回溯，禁用。
      type: Boolean,
      default: false
    }
  },
  emits: ['restore', 'restream', 'open-link', 'preview-file', 'interrupt', 'resume', 'restart-session', 'quote', 'tool-decide', 'withdraw'],
  components: {
    FilePreviewModal
  },
  data() {
    return {
      copied: false,
      userCopied: false,
      // 如果消息已完成（thinkingDone: true），默认折叠思考区块
      thinkingCollapsed: this.message.thinkingDone === true,
      expandedTools: {},
      // 工具调用 > 6 时记录"用户主动展开过"，避免被持续覆盖回折叠
      thinkingOverflowExpanded: false,
      activeFileIndex: 0,
      isUserMessageCollapsed: false,
      interruptReasonExpanded: false,
      // 文件预览弹窗
      previewVisible: false,
      previewFile: {},
      // 引用按钮浮动状态
      quoteButtonVisible: false,
      quoteButtonPos: { top: 0, left: 0 },
      // 导出本轮按钮：防连点
      exporting: false,
      // 内嵌审批的「告诉 AI 怎么做」反馈模式：按 tool index 独立记录展开态 + 文本
      feedbackExpanded: {},
      feedbackText: {}
    }
  },
  mounted() {
    // 暴露方法到 window，供 [[ ]] 语法中的 onclick 调用
    window.handleFileDownload = this.handleFileDownload.bind(this)
    window.previewMdFile = this.previewMdFile.bind(this)
    window.handleIframeFullscreen = this.handleIframePreview.bind(this)
    window.handleMermaidFullscreen = this.handleMermaidPreview.bind(this)
    window.handleMermaidPreview = this.handleMermaidPreview.bind(this)
    // 监听全局 mouseup，用于检测 AI 消息内的文本选区
    document.addEventListener('mouseup', this.handleTextSelection)
    document.addEventListener('selectionchange', this.handleSelectionChange)
  },
  beforeUnmount() {
    document.removeEventListener('mouseup', this.handleTextSelection)
    document.removeEventListener('selectionchange', this.handleSelectionChange)
  },
  computed: {
    /**
     * 是否展示 metrics 指标条：仅 AI 消息 + 非 error + 非中断 + 有任一指标
     * 流式中（streaming=true）也会展示，让数字随事件跳
     */
    showMetrics() {
      if (!this.message || this.message.role !== 'ai') return false
      if (this.message.error) return false
      return this.metricsElapsedSec > 0 || this.metricsTokenTotal > 0
    },
    /**
     * 是否显示「导出到本轮」按钮：仅 AI 消息 + 非流式中 + 有 checkpoint_id（说明后端已落盘）
     * 流式中 checkpoint 还没生成（done 事件才写），避免点了 404。
     */
    canExportTurn() {
      if (!this.message || this.message.role !== 'ai') return false
      if (this.message.streaming) return false
      if (this.message.error) return false
      return !!this.message.checkpointId
    },
    /**
     * 是否显示「回溯到此对话」按钮：仅 AI 消息 + 非流式 + 非 error + 有 checkpointId。
     * 异常对话段（permission_request 中断 / 主动中断）只有 REASONING AIMessage，没有 SUMMARY，
     * 后端 get_conversation 不会给它分配 cid —— 按钮显示点了也是 no-op，直接隐藏。
     */
    canBacktrack() {
      if (!this.message || this.message.role !== 'ai') return false
      if (this.message.streaming) return false
      if (this.message.error) return false
      return !!this.message.checkpointId
    },
    /**
     * 是否显示「重新生成」按钮：比 canBacktrack 额外要求"是最新的 AI 消息且不是首条"，
     * 否则 fallback 到上一轮 cid 误重生成。同时必须有 cid（避免 fallback 语义错误）。
     */
    canRestream() {
      if (!this.canBacktrack) return false
      return this.isLatestAiMessage && !this.isFirstAiMessage
    },
    metricsElapsedSec() {
      // 优先用后端权威 elapsedMs（毫秒）；fallback 到 responseTime（秒）
      if (this.message?.elapsedMs !== undefined && this.message.elapsedMs !== null) {
        return this.message.elapsedMs / 1000
      }
      if (this.message?.responseTime) return this.message.responseTime
      return 0
    },
    metricsTokenTotal() {
      return Number(this.message?.tokenUsage?.total || 0)
    },
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
          // v-html 注入前过 DOMPurify（挡 <script>、内联事件；iframe 强制 sandbox）
          return sanitizeHtml(html)
        } catch (error) {
          console.error('Markdown 渲染失败:', error, '原始内容:', this.message.content)
          // 降级处理，直接返回纯文本
          return this.escapeHtml(String(this.message.content))
        }
      }
      return this.escapeHtml(this.message.content)
    },
    // 拆分用户消息：把开头的 <quote>...</quote> 块单独抽出来
    parsedUserContent() {
      const content = this.message.content || ''
      if (this.message.role !== 'user') return { quote: null, text: content }
      const match = content.match(/^<quote>\n([\s\S]*?)\n<\/quote>\s*\n?([\s\S]*)$/)
      if (!match) return { quote: null, text: content }
      return { quote: match[1], text: match[2] }
    },
    // 引用块内容（按 markdown 渲染）
    renderedQuote() {
      const { quote } = this.parsedUserContent
      if (!quote) return ''
      try {
        let html = marked(this.preprocessContent(quote))
        html = this.renderLatex(html)
        // v-html 注入前过 DOMPurify（挡 <script>、内联事件）
        return sanitizeHtml(html)
      } catch (error) {
        console.error('引用块 Markdown 渲染失败:', error)
        return this.escapeHtml(quote)
      }
    },
    // 用户正文（去除 <quote> 后剩余的部分）
    renderedUserText() {
      const { text } = this.parsedUserContent
      if (!text) return ''
      // 保留原文以支持换行、空白；转义 HTML 防止注入
      return this.escapeHtml(text)
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
      // 用户消息超过5行则折叠（按"去掉引用块后的正文"算行数）
      if (this.message.role !== 'user') return false
      const text = this.parsedUserContent.text
      const lines = (text || '').split('\n').length
      return lines > 5
    },
    collapsedContent() {
      if (!this.isContentCollapsed) return this.message.content
      const lines = (this.message.content || '').split('\n')
      return lines.slice(0, 5).join('\n') + '\n...'
    },
    // 用户正文（去掉引用块）超过5行时折叠后的内容
    collapsedUserText() {
      if (!this.isContentCollapsed) return this.renderedUserText
      const text = this.parsedUserContent.text
      const lines = (text || '').split('\n')
      return this.escapeHtml(lines.slice(0, 5).join('\n') + '\n...')
    },
    componentUid() {
      return this._uid
    },
    // 工具调用超过 6 个时，强制折叠整个思考过程
    // 但用户主动展开后不再强制覆盖回折叠状态
    effectiveThinkingCollapsed() {
      // 等待审批的工具条目在这条消息里 → 强制展开（让用户看到内嵌审批按钮）
      // 覆盖用户手动折叠的状态，因为审批按钮就在 thinking-body 里
      if (this.pendingToolApproval && this.pendingToolApproval.messageIndex === this.messageIndex) {
        return false
      }
      const tcLen = this.message.toolCalls && this.message.toolCalls.length
      if (tcLen > 6 && !this.thinkingOverflowExpanded) return true
      return this.thinkingCollapsed
    },
    // 用户消息实际是否处于折叠态：
    // 内容超长（isContentCollapsed）且用户没主动展开过（isUserMessageCollapsed=false）→ 折叠
    // 折叠时显示前 5 行 + ...
    effectiveUserCollapsed() {
      return this.isContentCollapsed && !this.isUserMessageCollapsed
    }
  },
  watch: {
    'message.content': {
      handler() {
        this.$nextTick(() => {
          this.highlightCode()
          this.processMarkdownFiles()
          this.processMermaidFiles()
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
    /**
     * 耗时格式化：< 60s 显示 X.Xs，>= 60s 显示 Xm Ys
     * 与 Claude Code 风格一致，便于实时跟踪
     */
    formatElapsed(sec) {
      if (!sec || sec <= 0) return '0.0s'
      if (sec < 60) return `${sec.toFixed(1)}s`
      const m = Math.floor(sec / 60)
      const s = Math.floor(sec % 60)
      return `${m}m ${s}s`
    },
    /**
     * tokens 格式化：< 1k 直接显示，>= 1k 显示 X.Xk
     */
    formatTokenCount(n) {
      if (!n || n <= 0) return '0'
      if (n < 1000) return String(n)
      if (n < 10000) return `${(n / 1000).toFixed(2)}k`
      return `${Math.round(n / 1000)}k`
    },
    // 预处理原始文本 - 处理 [[ ]] 本地文件引用语法、MD 链接渲染和裸 URL
    preprocessContent(content) {
      if (typeof content !== 'string') return content

      // Step 1: 处理 [[ ]] 本地文件引用语法（先于裸 URL 处理）
      content = this._processDoubleBracketSyntax(content)

      // Step 2: 处理 markdown 链接中的 .md/.markdown 文件（转为可渲染的格式）
      content = this._processMarkdownLinks(content)

      // Step 3: 处理裸 URL（排除 markdown 图片和链接内的 URL）
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

          let start = i + match.index
          // 图片语法 ![...](...) 中，! 在 [ 前面一个位置，需要把 ! 也纳入 skip 范围
          if (content[start - 1] === '!') {
            start -= 1
          }
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

    // 处理 [[ ]] 本地文件引用语法
    _processDoubleBracketSyntax(content) {
      // 匹配 [[cached/...]] 或 [[http://...]] 格式
      const doubleBracketRegex = /\[\[([^\]]+)\]\]/g

      return content.replace(doubleBracketRegex, (match, path) => {
        // 清理路径
        const cleanPath = path.trim()

        // 容错：路径看起来不正常（有换行、空格、连续标点等）时原样输出，防止 AI 生成异常时输出乱码
        if (!cleanPath || /\s|[\n\r]/.test(cleanPath) || /[,，;；:：""''（）【】]/.test(cleanPath)) {
          return match
        }

        const ext = cleanPath.split('.').pop().toLowerCase()
        const filename = cleanPath.split('/').pop() || 'file'

        // 判断是否为 OSS URL
        const isOssUrl = cleanPath.startsWith('http')

        // 图片类型 - 转换为 markdown 图片语法，让渲染器直接处理
        if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'].includes(ext)) {
          const src = isOssUrl ? cleanPath : `/static/${cleanPath}`
          return `![${filename}](${src})`
        }

        // HTML 类型
        if (['html', 'htm'].includes(ext)) {
          const src = isOssUrl ? cleanPath : `/static/${cleanPath}`
          // iframe 内通常是 sandbox 生成的可视化（Plotly / Bokeh / ECharts），需要 JS + 下载弹窗；
          // 加上 allow-same-origin：Plotly 等库会调 parent.postMessage，需要知道父页 origin 才能正常传 target origin，
          //   否则只能用 null 当 target origin，spec 不允许 → Plotly 报错 → 图表渲染中断。
          // 内容来自后端生成的 trustworthy 脚本（LLM 产物 + CDN 库），不打开 allow-top-navigation 等敏感权限
          // referrerpolicy="no-referrer"：不向外发 Referer
          // 按钮用 data-action 而非 onclick：DOMPurify 默认剥 inline event handler，靠 Vue 事件代理分发
          return `<div class="file-render-block" data-path="${cleanPath}" data-oss-url="${isOssUrl ? cleanPath : ''}" data-type="html" data-name="${filename}">
            <iframe src="${src}" class="file-render-iframe" sandbox="allow-scripts allow-popups allow-same-origin" referrerpolicy="no-referrer"></iframe>
            <button class="fullscreen-btn" data-action="iframe-fullscreen" title="查看预览"></button>
            <button class="download-btn" data-action="file-download" title="下载"></button>
          </div>`
        }

        // Mermaid 语法类型（.mmd）- 流程图/ER图等
        if (ext === 'mmd') {
          return `<div class="file-render-block" data-path="${cleanPath}" data-oss-url="${isOssUrl ? cleanPath : ''}" data-type="mmd" data-name="${filename}" data-action="mermaid-preview" style="cursor:pointer;">
            <div class="mermaid-loading">加载中...</div>
          </div>`
        }

        // Markdown 类型 - 点击后通过 preview-file 事件预览
        if (['md', 'markdown'].includes(ext)) {
          return `<a class="md-file-link" data-path="${isOssUrl ? '' : cleanPath}" data-oss-url="${isOssUrl ? cleanPath : ''}" data-name="${filename}">${filename}</a>`
        }

        // 文本/代码文件（csv, json, txt, py, js ...）- 点击后预览纯文本
        if (TEXT_FILE_EXTS.has(ext)) {
          return `<a class="data-file-link" data-path="${isOssUrl ? '' : cleanPath}" data-oss-url="${isOssUrl ? cleanPath : ''}" data-name="${filename}">${filename}</a>`
        }

        // 其他类型，返回原文本
        return match
      })
    },

    // 处理 markdown 链接中的 .md 文件，将其转换为可渲染的格式
    _processMarkdownLinks(content) {
      // 匹配 markdown 链接 [text](url)，但排除图片链接 ![alt](url)
      // 使用括号计数找到正确的结束位置
      const result = []
      let i = 0

      while (i < content.length) {
        // 检查是否是图片链接开头
        if (content.slice(i).startsWith('![')) {
          // 图片链接，跳过
          const nextBracket = content.indexOf(']', i)
          if (nextBracket === -1) {
            result.push(content.slice(i))
            break
          }
          const nextParen = content.indexOf('(', nextBracket)
          if (nextParen === -1) {
            result.push(content.slice(i))
            break
          }
          // 找到匹配的 )
          let depth = 1
          let j = nextParen + 1
          while (j < content.length && depth > 0) {
            if (content[j] === '(') depth++
            else if (content[j] === ')') depth--
            j++
          }
          result.push(content.slice(i, j))
          i = j
          continue
        }

        // 检查是否是普通链接 [
        if (content[i] === '[') {
          const nextBracket = content.indexOf(']', i)
          if (nextBracket !== -1) {
            const nextParen = content.indexOf('(', nextBracket)
            if (nextParen !== -1 && nextParen === nextBracket + 1) {
              // 找到匹配的 )
              let depth = 1
              let j = nextParen + 1
              while (j < content.length && depth > 0) {
                if (content[j] === '(') depth++
                else if (content[j] === ')') depth--
                j++
              }
              const url = content.slice(nextParen + 1, j - 1)
              const ext = url.split('.').pop().toLowerCase()

              // 如果是 .md 或 .markdown 文件，转换为可渲染格式
              if (['md', 'markdown'].includes(ext)) {
                const filename = url.split('/').pop() || 'file.md'
                // 不push原始链接，只push可点击的文件名链接
                result.push(`<a class="md-file-link" data-oss-url="${url}" data-name="${filename}">${filename}</a>`)
                i = j
                continue
              }

              // 文本/代码文件（csv, json, txt, py, js ...）- 点击后预览纯文本
              if (TEXT_FILE_EXTS.has(ext)) {
                const filename = url.split('/').pop() || 'file'
                result.push(`<a class="data-file-link" data-oss-url="${url}" data-name="${filename}">${filename}</a>`)
                i = j
                continue
              }
            }
          }
        }
        result.push(content[i])
        i++
      }

      return result.join('')
    },

    // 处理 Markdown 文件的异步加载和渲染
    async processMarkdownFiles() {
      const mdBlocks = this.$el.querySelectorAll('.file-render-block[data-type="md"]')
      for (const block of mdBlocks) {
        const path = block.dataset.path
        const ossUrl = block.dataset.ossUrl
        const loadingEl = block.querySelector('.md-content-loading')
        const fileName = block.dataset.name || 'file'

        try {
          // 优先使用 OSS URL，否则使用本地路径
          const url = ossUrl || (path ? `/static/${path}` : null)
          if (!url) {
            if (loadingEl) loadingEl.textContent = '无效路径'
            continue
          }

          // 加上时间戳防止缓存
          const fetchUrl = url + (url.includes('?') ? '&' : '?') + '_t=' + Date.now()

          console.log(`[MD渲染] 开始加载: ${fileName}, URL: ${fetchUrl}`)
          const response = await fetch(fetchUrl)
          console.log(`[MD渲染] 响应状态: ${response.status} for ${url}`)

          if (response.ok) {
            const text = await response.text()
            console.log(`[MD渲染] 原始内容(${text.length}字符):`, text.substring(0, 300))
            const html = marked.parse(text)
            console.log(`[MD渲染] HTML长度: ${html.length}`)

            // 移除加载提示元素
            if (loadingEl) {
              loadingEl.remove()
            }

            // 创建类似代码块的渲染结构
            const preEl = document.createElement('pre')
            preEl.className = 'md-file-block collapsed'
            preEl.dataset.language = fileName
            preEl.innerHTML = `
              <div class="md-content">${html}</div>
              <button class="md-block-toggle" onclick="window.toggleMdBlock(this)">展开</button>
            `

            block.appendChild(preEl)
            console.log(`[MD渲染] 成功: ${fileName}, block子元素: ${block.children.length}`)
          } else {
            console.error(`[MD渲染] HTTP错误: ${response.status} for ${url}`)
            if (loadingEl) loadingEl.textContent = `加载失败(${response.status})`
          }
        } catch (e) {
          console.error(`[MD渲染] 异常:`, e, `URL: ${url || ossUrl || path}`)
          if (loadingEl) loadingEl.textContent = '加载异常'
        }
      }
    },

    // 处理 Mermaid 文件的异步加载和渲染
    async processMermaidFiles() {
      const mmdBlocks = this.$el.querySelectorAll('.file-render-block[data-type="mmd"]')
      for (const block of mmdBlocks) {
        const path = block.dataset.path
        const ossUrl = block.dataset.ossUrl
        const loadingEl = block.querySelector('.mermaid-loading')
        const fileName = block.dataset.name || 'file'

        try {
          const url = ossUrl || (path ? `/static/${path}` : null)
          if (!url) {
            if (loadingEl) loadingEl.textContent = '无效路径'
            continue
          }

          const fetchUrl = url + (url.includes('?') ? '&' : '?') + '_t=' + Date.now()
          const response = await fetch(fetchUrl)

          if (response.ok) {
            let mermaidCode = await response.text()
            // 去除代码块包裹符号（双重保障）
            mermaidCode = mermaidCode.trim().replace(/^```(?:mermaid)?\s*/i, '').replace(/\s*```$/, '')

            const id = 'mermaid-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8)
            const { svg } = await mermaid.render(id, mermaidCode)

            if (loadingEl) loadingEl.remove()
            const container = document.createElement('div')
            container.className = 'mermaid-rendered'
            container.innerHTML = svg
            block.insertBefore(container, block.firstChild)
            if (loadingEl) loadingEl.remove()

            // 渲染完成后注入 style 确保覆盖所有 CSS
            this.$nextTick(() => {
              const renderedSvg = block.querySelector('.mermaid-rendered svg')
              if (renderedSvg) {
                renderedSvg.removeAttribute('width')
                renderedSvg.removeAttribute('height')
                // 对话框内：宽度按容器自适应（不超过 900px），
                // 高度放开限制，让长流程图整体显示不滚动
                renderedSvg.style.width = '100%'
                renderedSvg.style.maxWidth = '900px'
                renderedSvg.style.height = 'auto'
                renderedSvg.style.maxHeight = 'none'
              }
              // 外层 block 不再限制高度，长流程图直接完整展开
              block.style.maxHeight = 'none'
              block.style.overflow = 'visible'
              const mermaidRendered = block.querySelector('.mermaid-rendered')
              if (mermaidRendered) {
                mermaidRendered.style.maxHeight = 'none'
                mermaidRendered.style.overflow = 'visible'
              }
            })
          } else {
            if (loadingEl) loadingEl.textContent = `加载失败(${response.status})`
          }
        } catch (e) {
          console.error(`[Mermaid渲染] 异常:`, e, `URL: ${url || ossUrl || path}`)
          if (loadingEl) loadingEl.textContent = '渲染异常'
        }
      }
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

    // 文件下载处理（供 window.handleFileDownload 调用）
    handleFileDownload(event, btn) {
      event.stopPropagation()
      event.preventDefault()

      const container = btn.closest('.file-render-block')
      if (!container) return

      const path = container.dataset.path
      const ossUrl = container.dataset.ossUrl
      const name = container.dataset.name || 'download'

      let url
      if (ossUrl) {
        // OSS 文件：直接使用 OSS URL
        url = ossUrl
      } else if (path) {
        // 本地文件：/static/{path}?download=true
        url = `/static/${path}?download=true`
      } else {
        return
      }

      const a = document.createElement('a')
      a.href = url
      a.download = name
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    },

    // 图片预览（使用 FilePreviewModal）
    handleImagePreview(img) {
      const src = img.src
      const alt = img.alt || 'image.png'
      const ext = (alt.split('.').pop() || 'png').toLowerCase()
      const mimeType = `image/${ext === 'svg' ? 'svg+xml' : ext}`

      this.previewFile = {
        name: alt,
        preview_url: src,
        iframe_url: src,
        file_type: 'IMAGE',
        type: mimeType,
        suffix: '.' + ext,
        preview_method: 'iframe'
      }
      this.previewVisible = true
    },

    // iframe 预览（HTML 文件走 FilePreviewPanel 展开，与工作树文件预览一致，不再弹浮窗）
    handleIframePreview(btn) {
      event.stopPropagation()
      const container = btn.closest('.file-render-block')
      if (!container) return

      const iframe = container.querySelector('iframe')
      if (!iframe) return

      const src = iframe.src
      const name = container.dataset.name || 'file.html'
      const ext = (name.split('.').pop() || 'html').toLowerCase()

      // 走与 mermaid 一致的 preview-file 事件 → App.vue 打开 FilePreviewPanel
      // 同时 fetch 一次源码作为 text_content，让 panel 的「原文」tab 有内容
      this.$emit('preview-file', {
        name: name,
        suffix: '.' + ext,
        type: 'text/html',
        file_type: 'HTML',
        url: src,
        preview_url: src,
        iframe_url: src,
        preview_method: 'iframe',
        text_content: '',
        content: ''
      })

      // 异步 fetch 源码，更新 text_content（panel 内的原文 tab 用）
      fetch(src).then(r => r.ok ? r.text() : Promise.reject(r.status)).then(text => {
        this.$emit('preview-file-text-update', { url: src, text_content: text, content: text })
      }).catch(() => { /* fetch 失败保持原文 tab 空，不影响渲染 tab */ })
    },

    // 兼容旧的方法名（避免被其他地方引用时崩溃）
    handleImageFullscreen(img) {
      this.handleImagePreview(img)
    },
    handleIframeFullscreen(btn) {
      this.handleIframePreview(btn)
    },

    // Mermaid 文件点击：发送 preview-file 事件，打开 FilePreviewPanel
    handleMermaidPreview(el) {
      event.stopPropagation()
      const container = el.closest('.file-render-block')
      if (!container) return

      const path = container.dataset.path
      const ossUrl = container.dataset.ossUrl
      const name = container.dataset.name || 'diagram.mmd'

      const url = ossUrl || (path ? `/static/${path}` : null)
      if (!url) return

      fetch(url + (url.includes('?') ? '&' : '?') + '_t=' + Date.now())
        .then(r => r.ok ? r.text() : Promise.reject(r.status))
        .then(content => {
          content = content.trim().replace(/^```(?:mermaid)?\s*/i, '').replace(/\s*```$/, '')
          this.$emit('preview-file', {
            name: name,
            text_content: content,
            url: url + '?download=true',
            suffix: '.mmd',
            type: 'text/vnd.mermaid'
          })
        })
        .catch(err => {
          this.$emit('preview-file', {
            name: name,
            text_content: '加载失败: ' + err,
            url: url + '?download=true'
          })
        })
    },

    handleMermaidFullscreen(btn) {
      this.handleMermaidPreview(btn)
    },

    // 关闭文件预览弹窗
    closePreview() {
      this.previewVisible = false
      this.previewFile = {}
    },

    // 全局 selectionchange 监听：选区变化时关闭引用按钮
    handleSelectionChange() {
      const selection = window.getSelection()
      if (!selection || selection.isCollapsed) {
        // 选区为空（仅为光标）→ 延迟关闭，给点击引用按钮留出时间
        setTimeout(() => {
          const s = window.getSelection()
          if (!s || s.isCollapsed) {
            this.quoteButtonVisible = false
          }
        }, 100)
      }
    },

    // 监听 mouseup：判断选区是否在同一块级元素内，是则显示引用按钮
    handleTextSelection(e) {
      // 仅 AI 消息支持引用
      if (this.message.role !== 'ai') return

      // 如果点击的就是引用按钮本身，不重新计算
      if (e && e.target && e.target.closest && e.target.closest('.quote-floating-btn')) {
        return
      }

      const selection = window.getSelection()
      if (!selection || selection.rangeCount === 0) {
        this.quoteButtonVisible = false
        return
      }

      const range = selection.getRangeAt(0)
      if (range.collapsed) {
        this.quoteButtonVisible = false
        return
      }

      const selectedText = selection.toString().trim()
      // 允许图片选区（图片本身没有文本内容）
      const hasImage = !!this._findImageInSelection(selection)
      // 只要有非空文本或包含图片，就显示按钮（不限制最小字符数）
      if (!selectedText && !hasImage) {
        this.quoteButtonVisible = false
        return
      }

      // 必须都在当前 MessageItem 的 .message-text 区域内
      const startInMessage = this.$el.contains(range.startContainer)
      const endInMessage = this.$el.contains(range.endContainer)
      if (!startInMessage || !endInMessage) {
        this.quoteButtonVisible = false
        return
      }

      // 必须在 .message-text 区域或 file-render-block 内
      const messageText = this.$el.querySelector('.message-text')
      const fileRenderBlock = this.$el.querySelector('.file-render-block')
      const inMessageText = messageText && (messageText.contains(range.startContainer) || messageText.contains(range.endContainer))
      const inFileBlock = fileRenderBlock && (fileRenderBlock.contains(range.startContainer) || fileRenderBlock.contains(range.endContainer))
      if (!inMessageText && !inFileBlock) {
        this.quoteButtonVisible = false
        return
      }

      // 计算按钮位置（选区上方居中）
      const rect = range.getBoundingClientRect()
      this.quoteButtonPos = {
        top: rect.top + window.scrollY - 38,
        left: rect.left + window.scrollX + rect.width / 2
      }
      this.quoteButtonVisible = true
    },

    // 点击引用按钮：智能提取引用内容并抛出
    handleQuoteClick() {
      const selection = window.getSelection()
      if (!selection || selection.rangeCount === 0) return

      const range = selection.getRangeAt(0)
      const selectedText = selection.toString().trim()
      if (!selectedText) return

      // 智能提取：把选中的 DOM 文本反推为原始 markdown
      const quoteContent = this._extractQuoteContent(selection, range)

      // 抛出引用事件
      this.$emit('quote', {
        content: quoteContent
      })

      this.quoteButtonVisible = false
      // 清除选区视觉
      selection.removeAllRanges()
    },

    // 向上查找最近的链接 <a> 祖先（支持普通链接、md/data 文件链接）
    _findLinkAncestor(node) {
      let cur = node.nodeType === 1 ? node : node.parentElement
      while (cur && cur !== document.body) {
        if (cur.tagName === 'A') {
          // 特殊链接：md-file-link、data-file-link（无 href，靠 class 识别）
          if (cur.classList && (cur.classList.contains('md-file-link') || cur.classList.contains('data-file-link'))) {
            return cur
          }
          // 普通链接（必须有 href）
          if (cur.href) {
            const text = (cur.textContent || '').trim()
            const href = cur.getAttribute('href') || ''
            // 排除裸 URL 链接（href 和 textContent 相同）
            if (text && href && text !== href) return cur
          }
        }
        cur = cur.parentElement
      }
      return null
    },

    // 向上查找最近的 [[ ]] 文件块祖先
    _findFileBlockAncestor(node) {
      let cur = node.nodeType === 1 ? node : node.parentElement
      while (cur && cur !== document.body) {
        if (cur.classList && cur.classList.contains('file-render-block')) return cur
        cur = cur.parentElement
      }
      return null
    },

    // 检测选区中是否包含 <img> 元素
    _findImageInSelection(selection) {
      if (!selection || selection.rangeCount === 0) return null
      const range = selection.getRangeAt(0)

      // 1. 选区起点本身是 <img>
      let cur = range.startContainer
      if (cur.nodeType === 1 && cur.tagName === 'IMG') return cur

      // 2. 向上查找 <img> 祖先
      while (cur && cur !== document.body) {
        if (cur.nodeType === 1 && cur.tagName === 'IMG') return cur
        cur = cur.parentElement
      }

      // 3. 选区内容中是否包含 <img.markdown-image>
      const ancestor = range.commonAncestorContainer
      if (ancestor.nodeType === 1 && ancestor.querySelectorAll) {
        const imgs = ancestor.querySelectorAll('img.markdown-image')
        for (const img of imgs) {
          if (range.intersectsNode(img)) return img
        }
      }

      return null
    },

    // 智能提取引用内容：把选区反推为原始 markdown
    // 智能提取引用内容：把选区反推为原始 markdown
    _extractQuoteContent(selection, range) {
      const content = this.message.content || ''

      // 0. 图片：选区包含 <img> → 返回 ![alt](src)
      const imgNode = this._findImageInSelection(selection)
      if (imgNode) {
        const src = imgNode.getAttribute('src') || ''
        const alt = imgNode.getAttribute('alt') || ''
        if (src) return `![${alt}](${src})`
      }

      // 1. 选区起点在链接 <a> 内 → 返回完整 [text](url)
      const linkNode = this._findLinkAncestor(range.startContainer)
      if (linkNode) {
        // 特殊链接：MD/data 文件（无 href，靠 data-oss-url 构造）
        if (linkNode.classList && (linkNode.classList.contains('md-file-link') || linkNode.classList.contains('data-file-link'))) {
          const ossUrl = linkNode.dataset.ossUrl || linkNode.getAttribute('href') || ''
          const name = linkNode.dataset.name || (linkNode.textContent || '').trim()
          if (ossUrl) return `[${name}](${ossUrl})`
        }
        // 普通链接
        const linkText = (linkNode.textContent || '').trim()
        const href = linkNode.getAttribute('href') || ''
        if (linkText && href) {
          // 尝试在原始 markdown 中找这个链接
          const escaped = linkText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
          const linkRegex = new RegExp(`\\[${escaped}\\]\\([^)]+\\)`)
          const match = content.match(linkRegex)
          if (match) return match[0]
          // 找不到就手动构造
          return `[${linkText}](${href})`
        }
      }

      // 2. 选区起点在 [[ ]] 文件块内 → 返回完整 [[...]]
      const fileNode = this._findFileBlockAncestor(range.startContainer)
      if (fileNode) {
        const ossUrl = fileNode.dataset.ossUrl
        const path = fileNode.dataset.path
        if (ossUrl) return `[[${ossUrl}]]`
        if (path) return `[[${path}]]`
      }

      // 3. 普通文字：walk DOM 反推为原始 markdown
      const selectedText = selection.toString().trim()
      if (selectedText) {
        return this._domToMarkdown(selection, range)
      }

      // 4. 选区为空
      return ''
    },

    // 把 DOM 选区反推为原始 markdown
    // 直接遍历真实 DOM（不依赖 cloneContents），用 range.intersectsNode() 判定包含
    // 避免部分包含 Element 在 cloneContents 下被丢弃属性的问题
    _domToMarkdown(selection, range) {
      // 先看选区是否完全在某个格式元素内（如 <strong>bold</strong>）
      const wrapper = this._detectFormattingWrapper(range)
      if (wrapper) {
        const text = selection.toString()
        if (text) {
          // 选区完全在格式元素（含 <a>）内 → 直接用包装器
          return wrapper.open + text + wrapper.close
        }
      }

      // 直接遍历选区公共祖先下的真实节点
      const root = range.commonAncestorContainer.nodeType === 1
        ? range.commonAncestorContainer
        : range.commonAncestorContainer.parentElement

      let result = ''
      for (const child of root.childNodes) {
        result += this._processRangeNode(child, range)
      }

      return result.replace(/^\s+|\s+$/g, '')
    },

    // 处理范围内的单个真实 DOM 节点
    _processRangeNode(node, range) {
      // 文本节点：取出落在 range 内的那一段
      if (node.nodeType === 3) {
        return this._getRangeText(node, range)
      }

      // 非元素节点忽略
      if (node.nodeType !== 1) return ''

      // 不在范围内的元素直接跳过
      if (!range.intersectsNode(node)) return ''

      const tag = node.tagName.toLowerCase()

      // 递归处理子节点
      let childrenMd = ''
      for (const child of node.childNodes) {
        childrenMd += this._processRangeNode(child, range)
      }

      // 用统一的规则包装 markdown
      return this._wrapMarkdownTag(tag, node, childrenMd, range)
    },

    // 取一个文本节点里落在 range 内的部分
    _getRangeText(textNode, range) {
      const text = textNode.textContent
      if (textNode === range.startContainer && textNode === range.endContainer) {
        return text.substring(range.startOffset, range.endOffset)
      }
      if (textNode === range.startContainer) {
        return text.substring(range.startOffset)
      }
      if (textNode === range.endContainer) {
        return text.substring(0, range.endOffset)
      }
      return text
    },

    // 把节点 + 子内容包成 markdown
    _wrapMarkdownTag(tag, node, content, range) {
      if (tag === 'p') return content + '\n\n'
      if (tag === 'br') return '\n'
      if (tag === 'h1') return '# ' + content + '\n\n'
      if (tag === 'h2') return '## ' + content + '\n\n'
      if (tag === 'h3') return '### ' + content + '\n\n'
      if (tag === 'h4') return '#### ' + content + '\n\n'
      if (tag === 'h5') return '##### ' + content + '\n\n'
      if (tag === 'h6') return '###### ' + content + '\n\n'

      if (tag === 'strong' || tag === 'b') return '**' + content + '**'
      if (tag === 'em' || tag === 'i') return '*' + content + '*'
      if (tag === 'del' || tag === 's' || tag === 'strike') return '~~' + content + '~~'

      if (tag === 'code') {
        if (node.parentElement && node.parentElement.tagName.toLowerCase() === 'pre') {
          return content
        }
        return '`' + content + '`'
      }
      if (tag === 'pre') {
        const codeEl = node.querySelector('code')
        const code = codeEl ? (codeEl.textContent || '') : content
        const langMatch = codeEl ? (codeEl.className.match(/language-(\S+)/) || [])[1] : ''
        const lang = langMatch || node.getAttribute('data-language') || ''
        return '```' + lang + '\n' + code.trim() + '\n```\n\n'
      }

      if (tag === 'a') {
        const href = node.getAttribute('href') || ''
        if (node.classList && (node.classList.contains('md-file-link') || node.classList.contains('data-file-link'))) {
          const ossUrl = node.dataset.ossUrl || href
          const name = node.dataset.name || content.trim()
          if (ossUrl) return `[${name}](${ossUrl})`
        }
        return '[' + content + '](' + href + ')'
      }

      if (tag === 'img') {
        const src = node.getAttribute('src') || ''
        const alt = node.getAttribute('alt') || ''
        return `![${alt}](${src})`
      }

      if (tag === 'blockquote') {
        return content.trim().split('\n').map(l => '> ' + l).join('\n') + '\n\n'
      }

      if (tag === 'ul') {
        const items = Array.from(node.children)
          .filter(c => c.tagName.toLowerCase() === 'li')
          .map(li => '- ' + this._processRangeNode(li, range).trim())
        return items.join('\n') + '\n\n'
      }
      if (tag === 'ol') {
        const items = Array.from(node.children)
          .filter(c => c.tagName.toLowerCase() === 'li')
          .map((li, i) => `${i + 1}. ` + this._processRangeNode(li, range).trim())
        return items.join('\n') + '\n\n'
      }
      if (tag === 'li') return content
      if (tag === 'hr') return '\n---\n\n'

      if (tag === 'div' && node.classList && node.classList.contains('file-render-block')) {
        const ossUrl = node.dataset.ossUrl
        const path = node.dataset.path
        if (ossUrl) return `[[${ossUrl}]]`
        if (path) return `[[${path}]]`
      }

      // 默认：直接返回子内容（无包装）
      return content
    },

    // 检测选区是否完全在某个格式元素内
    // 返回 { kind, open, close, node } 用于包装
    _detectFormattingWrapper(range) {
      // 起点和终点必须在同一个格式元素内（且不是同祖先的更外层元素）
      const startContainer = range.startContainer
      const endContainer = range.endContainer

      // 共同的最近格式祖先
      const findCommonFormatAncestor = (a, b) => {
        const ancestorsA = []
        let cur = a.nodeType === 1 ? a : a.parentElement
        while (cur && cur !== document.body) {
          ancestorsA.push(cur)
          cur = cur.parentElement
        }
        cur = b.nodeType === 1 ? b : b.parentElement
        while (cur && cur !== document.body) {
          if (ancestorsA.includes(cur)) {
            // 看 cur 是不是格式元素
            const tag = cur.tagName.toLowerCase()
            if (tag === 'strong' || tag === 'b') return { tag: 'strong', node: cur }
            if (tag === 'em' || tag === 'i') return { tag: 'em', node: cur }
            if (tag === 'code') return { tag: 'code', node: cur }
            if (tag === 'del' || tag === 's' || tag === 'strike') return { tag: 'del', node: cur }
            if (tag === 'a') return { tag: 'a', node: cur }
            // 找到共同祖先但不是格式元素，继续
            return null
          }
          cur = cur.parentElement
        }
        return null
      }

      const common = findCommonFormatAncestor(startContainer, endContainer)
      if (!common) return null

      // 检查选区是否完全在这个格式元素内
      // 即选区起点和终点都在这个元素内，且选区不超出这个元素
      const formatNode = common.node
      if (!formatNode.contains(startContainer) || !formatNode.contains(endContainer)) {
        return null
      }

      // 必须覆盖整个元素的内容（否则是部分选择，部分选择不应该包裹标记）
      // 简化：检查选区文本是否等于 formatNode 的 textContent
      // 但这样太严格了。改成：检查选区是否覆盖了 formatNode 的全部内容
      // 实际上对于 "bold" 选择，我们只检查 selection.toString() == formatNode.textContent
      // 但有空白差异，所以用 trim 比较
      const fullText = formatNode.textContent
      const selectedText = range.toString()
      if (selectedText.trim() !== fullText.trim()) {
        return null  // 部分选择，不包裹
      }

      const tag = common.tag
      if (tag === 'strong') return { kind: 'bold', open: '**', close: '**', node: formatNode }
      if (tag === 'em') return { kind: 'italic', open: '*', close: '*', node: formatNode }
      if (tag === 'code') {
        // 判断行内还是块级
        if (formatNode.parentElement && formatNode.parentElement.tagName.toLowerCase() === 'pre') {
          // 代码块：返回带语言标识的 ``` ``` 块
          const pre = formatNode.parentElement
          const langMatch = formatNode.className.match(/language-(\S+)/)
          const lang = langMatch ? langMatch[1] : ''
          return { kind: 'codeblock', open: '```' + lang + '\n', close: '\n```', node: pre }
        }
        return { kind: 'code', open: '`', close: '`', node: formatNode }
      }
      if (tag === 'del') return { kind: 'strike', open: '~~', close: '~~', node: formatNode }
      if (tag === 'a') {
        const href = formatNode.getAttribute('href') || ''
        // 特殊链接
        if (formatNode.classList && (formatNode.classList.contains('md-file-link') || formatNode.classList.contains('data-file-link'))) {
          const ossUrl = formatNode.dataset.ossUrl || href
          return { kind: 'link', open: `[${formatNode.dataset.name || formatNode.textContent}](`, close: ossUrl + ')', node: formatNode }
        }
        return { kind: 'link', open: '[' + formatNode.textContent + '](', close: href + ')', node: formatNode }
      }

      return null
    },

    previewMdFile(linkEl) {
      const path = linkEl.dataset.path
      const ossUrl = linkEl.dataset.ossUrl
      const name = linkEl.dataset.name || 'file.md'

      // 构建 fetch URL
      const url = ossUrl || (path ? `/static/${path}` : null)
      if (!url) {
        console.error('[预览MD] 无效路径:', { path, ossUrl })
        return
      }

      // 异步获取 MD 文件内容，然后发送到预览面板
      fetch(url + (url.includes('?') ? '&' : '?') + '_t=' + Date.now())
        .then(response => {
          if (!response.ok) throw new Error('加载失败')
          return response.text()
        })
        .then(content => {
          this.$emit('preview-file', {
            name: name,
            text_content: content,
            url: url + '?download=true'
          })
        })
        .catch(err => {
          console.error('[预览MD] 获取失败:', err)
          this.$emit('preview-file', {
            name: name,
            text_content: '加载失败: ' + err.message,
            url: url + '?download=true'
          })
        })
    },

    toggleMdReport(btn) {
      const reportBlock = btn.closest('.md-report-block')
      if (!reportBlock) return
      reportBlock.classList.toggle('collapsed')
      btn.textContent = reportBlock.classList.contains('collapsed') ? '展开' : '折叠'
    },

    toggleMdBlock(btn) {
      const preEl = btn.closest('pre.md-file-block')
      if (!preEl) return
      const isCollapsed = preEl.classList.contains('collapsed')
      preEl.classList.toggle('collapsed')
      preEl.classList.toggle('expanded')
      btn.textContent = isCollapsed ? '折叠' : '展开'
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

    /**
     * 导出到本轮为止的完整对话历史。
     * 调后端 /chat/{sid}/export/turn/{checkpoint_id} 拿 ZIP（openai.json + chatme.json）下载。
     */
    async exportTurn() {
      if (!this.canExportTurn || this.exporting) return
      const cid = this.message.checkpointId
      const sid = this.currentSessionId
      if (!cid || !sid) {
        console.warn('[exportTurn] missing checkpointId or sessionId')
        return
      }
      this.exporting = true
      try {
        const resp = await fetch(`/chat/${sid}/export/turn/${encodeURIComponent(cid)}`)
        if (!resp.ok) {
          const detail = await resp.text().catch(() => '')
          alert(`导出失败：${resp.status} ${detail || resp.statusText}`)
          return
        }
        const blob = await resp.blob()
        const filename = this._filenameFromResponse(resp) || `chatme_export_${sid.slice(0, 8)}.zip`
        this._downloadBlob(blob, filename)
      } catch (e) {
        console.error('[exportTurn] failed:', e)
        alert(`导出失败：${e?.message || e}`)
      } finally {
        this.exporting = false
      }
    },
    _downloadBlob(blob, filename) {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.style.display = 'none'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    },
    _filenameFromResponse(resp) {
      const cd = resp.headers.get('content-disposition') || ''
      const m = /filename="?([^";]+)"?/i.exec(cd)
      return m ? m[1] : ''
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

    // 撤回按钮：把整条消息交给父级（App.vue → handleWithdraw），
    // 父级负责「中断 + backtrack + reload conv + 填回输入框」。
    // MessageItem 这里只负责 emit（不直接调 API），跟「重新生成」emit restream 一致。
    withdrawUserMessage() {
      this.$emit('withdraw', this.message)
    },

    handleLinkClick(e) {
      const anchor = e.target.closest('a')
      if (!anchor) return

      // 检查是否是 MD 或数据文件链接
      if (anchor.classList.contains('md-file-link') || anchor.classList.contains('data-file-link')) {
        e.preventDefault()
        this.previewMdFile(anchor)
        return
      }

      const href = anchor.getAttribute('href')
      if (!href || !href.startsWith('http')) return
      e.preventDefault()
      this.$emit('open-link', href)
    },

    // 事件委托：捕获 .message-text 内 <img class="markdown-image"> 的点击
    // 替代原先 window.markdownImageClick 内联 onclick（刷新会话/复用组件时不可靠）
    handleMarkdownImageClick(e) {
      // 1. data-action 事件代理：v-html 中的 .file-render-block 按钮 / mmd 容器
      //    改用 data-action 属性（DOMPurify 默认剥 onclick，无法再 inline 触发）
      const actionEl = e.target.closest && e.target.closest('[data-action]')
      if (actionEl) {
        const action = actionEl.dataset.action
        if (action === 'iframe-fullscreen') {
          e.preventDefault()
          e.stopPropagation()
          this.handleIframePreview(actionEl)
          return
        }
        if (action === 'file-download') {
          this.handleFileDownload(e, actionEl)
          return
        }
        if (action === 'mermaid-preview') {
          e.stopPropagation()
          this.handleMermaidPreview(actionEl)
          return
        }
      }
      // 2. 原有：markdown image 预览
      const img = e.target.closest && e.target.closest('img.markdown-image, img[data-markdown-image="true"]')
      if (!img) return
      this.handleImagePreview(img)
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
      // 工具调用 > 6 时一旦用户主动展开过，就不再被强制覆盖回折叠
      const tcLen = this.message.toolCalls && this.message.toolCalls.length
      if (!this.thinkingCollapsed && tcLen > 6) {
        this.thinkingOverflowExpanded = true
      }
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
    /**
     * 判断指定 tool call 是否是当前待审批目标：
     * - pendingToolApproval 不为空
     * - messageIndex 匹配
     * - toolIndex 匹配
     */
    isToolAwaitingApproval(toolIndex) {
      if (!this.pendingToolApproval) return false
      return this.pendingToolApproval.messageIndex === this.messageIndex
        && this.pendingToolApproval.toolIndex === toolIndex
    },
    /**
     * 用户点击内嵌审批按钮，emit 给 App.vue 走 /decide + /resume 流程
     */
    emitToolDecision(decision) {
      this.$emit('tool-decide', decision)
    },
    /**
     * 「告诉 AI 怎么做」按钮：展开反馈 textarea
     */
    toggleFeedback(toolIndex) {
      this.feedbackExpanded = {
        ...this.feedbackExpanded,
        [toolIndex]: true,
      }
      // 第一次展开时预填空字符串（v-model 需要初始 key）
      if (!(toolIndex in this.feedbackText)) {
        this.feedbackText = { ...this.feedbackText, [toolIndex]: '' }
      }
    },
    /**
     * 反馈模式「取消」：回到 4 选项默认视图，清空已写文本
     */
    cancelFeedback(toolIndex) {
      this.feedbackExpanded = {
        ...this.feedbackExpanded,
        [toolIndex]: false,
      }
      this.feedbackText = { ...this.feedbackText, [toolIndex]: '' }
    },
    /**
     * 反馈模式「发送给 AI」：把文本拼成 `feedback:<text>` 作为 decision emit
     * 后端 permissions.py 看到这个前缀会返回 ("feedback", text)，由 _permission_wrap
     * 包成 ToolMessage 让 LLM 看到用户指引并重新尝试调用。
     */
    submitFeedback(toolIndex) {
      const text = (this.feedbackText[toolIndex] || '').trim()
      if (!text) return
      this.$emit('tool-decide', `feedback:${text}`)
    },
    hasArgs(args, toolName = '') {
      const filtered = this.filterInternalArgs(args, toolName)
      return Object.keys(filtered).length > 0
    },
    formatArgs(args, toolName = '') {
      const filtered = this.filterInternalArgs(args, toolName)
      try {
        return JSON.stringify(filtered, null, 2)
      } catch {
        return String(filtered)
      }
    },
    filterInternalArgs(args, toolName = '') {
      if (!args || typeof args !== 'object') return {}
      const filtered = { ...args }
      delete filtered.session_id
      // cmd / code 都支持 use_sandbox，统一剥掉这个内部参数
      if (toolName === 'code' || toolName === 'cmd') {
        // MCP 暴露给 LLM 时名字是 sandbox（去 use_ 前缀），兼容历史 use_sandbox
        delete filtered.sandbox
        delete filtered.use_sandbox
      }
      return filtered
    },
    formatArgs(args, toolName = '') {
      const filtered = this.filterInternalArgs(args, toolName)
      // cmd: 直接展示 shell 命令，去 JSON 包装
      if (toolName === 'cmd' && typeof filtered.command === 'string') {
        return filtered.command
      }
      // code: 语言非默认时打标签，再跟代码体
      if (toolName === 'code' && typeof filtered.code === 'string') {
        const lang = filtered.language || 'python'
        const isDefault = lang === 'python' || lang === 'py'
        return isDefault ? filtered.code : `[${lang}]\n${filtered.code}`
      }
      // 其他工具：JSON dump
      try {
        return JSON.stringify(filtered, null, 2)
      } catch {
        return String(filtered)
      }
    },
    getToolExecutionEnv(toolName, args) {
      // cmd 和 code 都走 use_sandbox；UI 标签统一显示执行环境
      // v0.1.3 反向命名：args.local === true → 本机执行（覆盖沙盒默认）
      if (toolName !== 'code' && toolName !== 'cmd') return null
      if (!args) return 'sandbox'
      if (args.local === true) return 'local'
      return 'sandbox'
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
            content: textContent,
            preview: file.preview,
            url: file.url
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
        // 优先使用 text_content（markdown 格式）进行渲染
        const textContent = file.text_content || file.content || ''
        if (typeof textContent === 'string' && textContent.trim().length > 0) {
          this.$emit('preview-file', {
            name: file.name,
            type: file.type,
            file_type: file.file_type,
            suffix: file.suffix,
            text_content: textContent,
            content: textContent,
            preview: file.preview,
            url: file.url
          })
        } else {
          const previewUrl = file.preview_url || file.iframe_url
          if (previewUrl) {
            this.$emit('preview-file', {
              preview_url: previewUrl,
              url: previewUrl,
              name: file.name,
              type: file.type,
              file_type: file.file_type,
              suffix: file.suffix,
              preview_method: file.preview_method,
              preview: file.preview
            })
          }
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

/* AI 错误消息框：与正常 markdown 渲染区分，避免报错堆栈被当成语法 */
.message-error-box {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  color: #b91c1c;
  max-width: 100%;
  margin: 4px 0;
}

.dark-theme .message-error-box {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.35);
  color: #fca5a5;
}

.message-error-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.message-error-content {
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.5;
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
.message-text :deep(h2) { font-size: 1.45em; font-weight: 900; color: #22c55e; }
.message-text :deep(h3) { font-size: 1.25em; font-weight: 900; color: #4ade80; }
.message-text :deep(h4) { font-size: 1.1em; font-weight: 700; color: #86efac; }
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

/* 耗时 + Tokens 指标：紧贴 thinking-header 右侧 chevron 左边，简洁小字（实时跳数字） */
.thinking-header-metrics {
  margin-left: auto;
  margin-right: 8px;
  font-size: 11px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.1px;
  cursor: default;
  white-space: nowrap;
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

/* 用户消息操作按钮组（复制 + 撤回）— 气泡左侧 */
.user-message-actions {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  padding-right: 6px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

/* 用户消息中含 <quote> 块时的样式 — 与 MessageInput 引用块保持一致 */
.user-message-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.user-quote-block {
  display: flex;
  align-items: stretch;
  gap: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
}

.user-quote-block .quote-block-bar {
  flex-shrink: 0;
  width: 3px;
  background: var(--button-bg);
}

.user-quote-block .quote-block-content {
  flex: 1;
  min-width: 0;
  padding: 8px 10px 8px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.user-quote-block .quote-block-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--button-bg);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.user-quote-block .quote-block-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  word-wrap: break-word;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
}

/* 引用块内 markdown 渲染的元素样式 — 与 .message-text 一致 */
.user-quote-block .quote-block-text :deep(p) {
  margin: 0 0 6px 0;
}
.user-quote-block .quote-block-text :deep(p:last-child) {
  margin-bottom: 0;
}
.user-quote-block .quote-block-text :deep(a) {
  color: var(--button-bg);
  text-decoration: none;
}
.user-quote-block .quote-block-text :deep(a:hover) {
  text-decoration: underline;
}
.user-quote-block .quote-block-text :deep(code) {
  background: var(--code-inline-bg);
  color: var(--code-inline-color);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.user-quote-block .quote-block-text :deep(strong) {
  font-weight: 600;
}
.user-quote-block .quote-block-text :deep(em) {
  font-style: italic;
}


.user-message-actions > * {
  pointer-events: auto;
}

.user-message:hover .user-message-actions,
.user-message-actions:hover {
  opacity: 1;
}

.user-action-button {
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

.user-action-button:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.user-action-button.copy-success,
.user-action-button.copy-success:hover {
  background: transparent;
  color: var(--text-secondary);
}

/* 撤回按钮：hover 时变红，提示「破坏性操作」 */
.user-withdraw-button:hover {
  background: #fef2f2;
  color: #ef4444;
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
  transition: opacity 0.2s, border-color 0.2s, box-shadow 0.2s;
}

.tool-call-item.tool-done {
  opacity: 1;
}

/* 待审批的 tool call：高亮黄色边框 + 阴影 + 顶部 badge */
.tool-call-item.awaiting-approval {
  opacity: 1;
  border-color: #f59e0b;
  box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.35), 0 2px 8px rgba(245, 158, 11, 0.12);
}

.tool-awaiting-badge {
  font-size: 10px;
  color: #b45309;
  background: rgba(245, 158, 11, 0.15);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  letter-spacing: 0.02em;
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

.tool-env-label {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 400;
}

.tool-env-label.env-local {
  /* local 工具名旁 ::local 标签保持灰色，不和 sandbox 标签色冲突 */
  color: var(--text-secondary);
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

/* 内嵌审批 UI：出现在 awaiting-approval 的 tool call 下方 */
.tool-inline-approval {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  background: rgba(245, 158, 11, 0.06);
  border-top: 1px solid rgba(245, 158, 11, 0.25);
}

.tool-inline-approval-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
}

.tool-inline-approval-icon {
  width: 14px;
  height: 14px;
  color: #f59e0b;
  flex-shrink: 0;
}

.tool-inline-approval-actions {
  display: flex;
  gap: 6px;
}

.tool-btn-deny,
.tool-btn-once,
.tool-btn-feedback,
.tool-btn-approve {
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  background: var(--bg-secondary);
  color: var(--text-primary);
  transition: all 0.15s ease;
}

.tool-btn-deny:disabled,
.tool-btn-once:disabled,
.tool-btn-feedback:disabled,
.tool-btn-approve:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.tool-btn-deny:hover:not(:disabled) {
  background: #fee2e2;
  color: #b91c1c;
  border-color: #fca5a5;
}

.tool-btn-once:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--text-secondary);
}

/* 「告诉 AI 怎么做」按钮：amber 主色调，呼应审批 UI 顶部的盾牌图标 */
.tool-btn-feedback {
  background: rgba(245, 158, 11, 0.08);
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.35);
}

.tool-btn-feedback:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.18);
  border-color: #f59e0b;
  color: #92400e;
}

/* 批准按钮：sandbox 默认绿色（v0.1.3 保持原样） */
.tool-btn-approve {
  background: #10b981;
  color: white;
  border-color: #10b981;
}

.tool-btn-approve:hover:not(:disabled) {
  background: #059669;
  border-color: #059669;
}

/* local 审核变体：淡红背景叠加（v0.1.3 区分 sandbox vs local） */
.tool-inline-approval--local {
  background: rgba(239, 68, 68, 0.06);  /* 淡红底，叠加在黄色边框上 */
}

/* local 警告符号 ⚠️ — 比盾牌更直观地传达「本机执行」风险 */
.tool-inline-approval-warn {
  font-size: 14px;
  line-height: 1;
  flex-shrink: 0;
}

/* local 工具的「批准」按钮改为浅红，提示这是本机执行（不是绿色放行） */
.tool-inline-approval--local .tool-btn-approve {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.45);
}

.tool-inline-approval--local .tool-btn-approve:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.22);
  border-color: #ef4444;
  color: #991b1b;
}

/* 反馈模式：textarea + 取消/发送两按钮 */
.tool-inline-feedback {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-feedback-textarea {
  width: 100%;
  min-height: 60px;
  resize: vertical;
  padding: 6px 8px;
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 5px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.5;
  box-sizing: border-box;
}

.tool-feedback-textarea:focus {
  outline: none;
  border-color: #f59e0b;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.15);
}

.tool-feedback-textarea:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.tool-inline-feedback-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
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

/* MD 和数据文件链接样式 */
.message-text :deep(.md-file-link),
.message-text :deep(.data-file-link) {
  color: var(--button-bg);
  text-decoration: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.15s;
}

.message-text :deep(.md-file-link:hover),
.message-text :deep(.data-file-link:hover) {
  background: var(--bg-hover);
  text-decoration: underline;
}

.file-render-block .markdown-image {
  max-height: 150px;
  width: auto;
  height: auto;
  object-fit: contain;
}

.file-render-iframe {
  width: 100%;
  height: 400px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.md-content-loading {
  color: var(--text-secondary);
  font-size: 13px;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.md-content {
  padding: 16px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: block;
  width: 100%;
  box-sizing: border-box;
}

.md-content p {
  margin: 0 0 12px 0;
}

/* MD 文件代码块样式 */
.message-text :deep(pre.md-file-block) {
  background: var(--code-block-bg);
  padding: 16px 20px;
  padding-bottom: 40px;
  border-radius: 12px;
  overflow: hidden;
  margin: 16px 0;
  border: 1px solid var(--code-block-border);
  position: relative;
  line-height: 1.6;
  box-shadow: var(--code-block-shadow);
  max-height: 200px;
  transition: max-height 0.3s ease;
}

.message-text :deep(pre.md-file-block.collapsed) {
  max-height: 200px;
}

.message-text :deep(pre.md-file-block.expanded) {
  max-height: none;
}

.message-text :deep(pre.md-file-block.collapsed::after) {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 60px;
  background: linear-gradient(transparent, var(--code-block-bg));
  pointer-events: none;
}

.message-text :deep(pre.md-file-block::before) {
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

.message-text :deep(.md-block-toggle) {
  position: absolute;
  bottom: 8px;
  right: 8px;
  padding: 4px 12px;
  font-size: 12px;
  background: var(--button-bg);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  z-index: 5;
}

.message-text :deep(.md-block-toggle:hover) {
  background: var(--button-hover);
}

.message-text :deep(pre.md-file-block) .md-content {
  background: transparent;
  border: none;
  padding: 0;
  color: var(--code-block-text);
  font-size: 13.5px;
  line-height: 1.65;
}

.message-text :deep(pre.md-file-block) .md-content p {
  margin: 8px 0;
}

.message-text :deep(pre.md-file-block) .md-content h1,
.message-text :deep(pre.md-file-block) .md-content h2,
.message-text :deep(pre.md-file-block) .md-content h3 {
  color: var(--code-block-text);
  margin: 12px 0 8px;
}

.message-text :deep(pre.md-file-block) .md-content table {
  color: var(--code-block-text);
}

/* 下载按钮 */
.file-render-block .download-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.5);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpolyline points='7 10 12 15 17 10'/%3E%3Cline x1='12' y1='15' x2='12' y2='3'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  background-size: 14px 14px;
  border: none;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  z-index: 10;
}

.file-render-block:hover .download-btn {
  opacity: 1;
}

.file-render-block .download-btn:hover {
  background: rgba(0, 0, 0, 0.7);
}

/* 全屏按钮 */
.file-render-block .fullscreen-btn {
  position: absolute;
  top: 8px;
  right: 44px;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.5);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 3H5a2 2 0 0 0-2 2v3'/%3E%3Cpath d='M21 8V5a2 2 0 0 0-2-2h-3'/%3E%3Cpath d='M3 16v3a2 2 0 0 0 2 2h3'/%3E%3Cpath d='M16 21h3a2 2 0 0 0 2-2v-3'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  background-size: 14px 14px;
  border: none;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  z-index: 10;
}

.file-render-block:hover .fullscreen-btn {
  opacity: 1;
}

.file-render-block .fullscreen-btn:hover {
  background: rgba(0, 0, 0, 0.7);
}

/* 浮动引用按钮 */
.quote-floating-btn {
  position: absolute;
  z-index: 1000;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  user-select: none;
  transition: background 0.15s, border-color 0.15s, color 0.15s, transform 0.1s;
}

.quote-floating-btn:hover {
  background: var(--bg-hover);
  border-color: var(--button-bg);
  color: var(--button-bg);
  transform: translateX(-50%) translateY(-1px);
}

.quote-floating-btn:active {
  transform: translateX(-50%) translateY(0);
}

.quote-floating-btn svg {
  flex-shrink: 0;
  opacity: 0.7;
}

.quote-floating-btn:hover svg {
  opacity: 1;
}

.file-render-block[data-type="mmd"] .download-btn {
  position: absolute;
  top: 8px;
  right: 8px;
}
</style>

<!-- v-html 动态生成的内容不在 scoped 管辖范围内，需要单独的非 scoped 样式 -->
<style>
.file-render-block[data-type="mmd"] {
  max-height: 900px !important;
  overflow: auto !important;
}

.file-render-block[data-type="mmd"] .mermaid-rendered {
  display: block !important;
  padding: 10px;
  overflow: visible !important;
  max-height: none !important;
  text-align: center;
}

.file-render-block[data-type="mmd"] .mermaid-rendered svg {
  max-width: 100%;
  height: auto;
  cursor: grab;
}

.file-render-block[data-type="mmd"] .mermaid-rendered svg:active {
  cursor: grabbing;
}

/* === v-html 注入的 .file-render-block + iframe + 按钮需要非 scoped ===
   （scoped 选择器要 data-v-xxx 才命中，v-html 出来的元素不带这个属性，
   所以这些规则要从 scoped 块搬到这里来） */
.file-render-block {
  position: relative;
  display: block;
  margin: 12px 0;
  /* 防止 iframe 内部绝对定位元素溢出到外层 markdown */
  overflow: hidden;
  isolation: isolate;
}
.file-render-iframe {
  display: block;
  width: 100%;
  height: 400px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  /* iframe 内容溢出时仅在 iframe 内部滚动，避免影响外层排版 */
  overflow: hidden;
}
.file-render-block .download-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.5);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpolyline points='7 10, 12 15, 17 10'/%3E%3Cline x1='12' y1='15' x2='12' y2='3'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  background-size: 14px 14px;
  border: none;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  z-index: 10;
}
.file-render-block:hover .download-btn { opacity: 1; }
.file-render-block .download-btn:hover { background: rgba(0, 0, 0, 0.7); }
.file-render-block .fullscreen-btn {
  position: absolute;
  top: 8px;
  right: 44px;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.5);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 3H5a2 2 0 0 0-2 2v3'/%3E%3Cpath d='M21 8V5a2 2 0 0 0-2-2h-3'/%3E%3Cpath d='M3 16v3a2 2 0 0 0 2 2h3'/%3E%3Cpath d='M16 21h3a2 2 0 0 0 2-2v-3'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  background-size: 14px 14px;
  border: none;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  z-index: 10;
}
.file-render-block:hover .fullscreen-btn { opacity: 1; }
.file-render-block .fullscreen-btn:hover { background: rgba(0, 0, 0, 0.7); }
</style>
