<template>
  <transition name="help-fade">
    <div v-if="visible" class="help-overlay" @click.self="$emit('close')">
      <div class="help-dialog" role="dialog" aria-modal="true" aria-labelledby="help-dialog-title" tabindex="-1" ref="dialog">
        <header class="help-header">
          <h2 id="help-dialog-title" class="help-title">灵析 · 功能速览</h2>
          <button type="button" class="help-close" @click="$emit('close')" aria-label="关闭">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </header>

        <div class="help-body">
          <section class="help-section">
            <h3>灵析能做什么</h3>
            <p>多智能体数据分析系统：对话中自动拆步骤、调工具、跑代码，把产物落到你的本地工作空间。</p>
          </section>

          <section class="help-section">
            <h3>快捷键</h3>
            <ul>
              <li><kbd>//</kbd>（双击 <kbd>/</kbd>）：从任意位置聚焦输入框；输入框内按 <kbd>/</kbd> 正常输入不拦截</li>
              <li><kbd>↑</kbd> <kbd>↓</kbd> / <kbd>Enter</kbd> / <kbd>Esc</kbd>：slash 面板、审批、列表通用导航；配置向导内 <kbd>↑</kbd> <kbd>↓</kbd> 切左侧步骤</li>
              <li><kbd>1</kbd>–<kbd>4</kbd>：审批 4 档快速选（取消 / 仅本次 / 反馈 / 批准）</li>
              <li><kbd>Shift+Enter</kbd>：输入框换行</li>
              <li><kbd>Ctrl+W</kbd>：关闭文件预览当前 tab</li>
            </ul>
            <p class="help-hint">💡 提示：弹窗打开会自动抢焦点，回车 / 空格直接触发当前高亮按钮；多数场景键盘操作比鼠标点击更顺手 —— 输入框、slash 面板、审批、文件树、配置向导、文件预览 tab 全部支持完整键盘流。</p>
          </section>

          <section class="help-section">
            <h3>使用技巧</h3>

            <h4>审批</h4>
            <ul>
              <li><code>cmd</code> / <code>code</code> 执行前内嵌到对应工具行，4 档：仅本次 / 批准（永久放行）/ 反馈 / 拒绝</li>
            </ul>

            <h4>文件树</h4>
            <ul>
              <li>📁 看当前会话所有产物；行内 × 软删除到 <code>.trash/{sid}/</code>，面板头部 🗑 手工清空；树底 [+] 一键新建</li>
              <li><b>焦点</b>：点目录行 → 蓝竖线标记 → <kbd>{{ _modKey }}+V</kbd> 粘到这里；点文件 → 焦点跳到父目录（{{ _fileManager }} 习惯）</li>
              <li><b>复制 vs 剪切</b>：琥珀 ⎘ 角标 = 复制（原位保留）；半透灰划线 = 剪切（即将移走）；同位置粘贴自动生成 <code>foo(N).py</code></li>
              <li><b>框选 / 拖拽</b>：空白处长按进入框选；树内拖拽移动，按住 <kbd>Alt</kbd> 复制；从 {{ _fileManager }} 拖文件直接上传</li>
            </ul>

            <h4>引用 & 撤回</h4>
            <ul>
              <li>AI 消息行内 <code>“</code> → 引用进下次输入；用户消息 ↶ → 回溯到上一轮</li>
            </ul>

            <h4>配置向导</h4>
            <ul>
              <li>入口：顶栏 🪄 按钮 / <code>/setup</code> 命令 / Settings 入口；任意时刻手动打开</li>
              <li>打开即自动聚焦 — 回车直接触发当前高亮按钮，无需先点一下浮窗</li>
              <li><kbd>↑</kbd> <kbd>↓</kbd> 切左侧步骤（mac/win 通用）；到边停止不循环</li>
              <li><kbd>Tab</kbd> 在表单内切字段；<kbd>Esc</kbd> 关闭浮窗；输入框内 <kbd>↑</kbd> <kbd>↓</kbd> 走原生光标不动 step</li>
              <li>4 类配置全部可选，全部可跳过；空字段不写入，已填字段才走 PUT <code>/admin/config</code> diff</li>
            </ul>

            <h4>产物导出</h4>
            <ul>
              <li>顶栏 ⬇ ZIP / 👁 HTML 打包当前会话产物；AI 消息 ⬇ 导出该轮对话历史</li>
            </ul>
          </section>

          <div v-if="actionCommands.length" class="help-cmd-group">
            <div class="help-cmd-group-label">命令</div>
            <div class="help-cmd-list">
              <div
                v-for="cmd in actionCommands"
                :key="cmd.name"
                class="help-cmd help-cmd--action"
              >
                <span class="help-cmd-name">/{{ cmd.name }}</span>
                <span class="help-cmd-desc">{{ cmd.description }}</span>
              </div>
            </div>
          </div>

          <div v-if="skillCommands.length" class="help-cmd-group">
            <div class="help-cmd-group-label">技能</div>
            <div class="help-cmd-list">
              <div
                v-for="cmd in skillCommands"
                :key="cmd.name"
                class="help-cmd"
              >
                <span class="help-cmd-name">/{{ cmd.name }}</span>
                <span class="help-cmd-desc">{{ cmd.description }}</span>
              </div>
            </div>
            <p class="help-cmd-hint">软提示：AI 会优先用对应技能，但也会按需智能调用其他技能。</p>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<script>
export default {
  name: 'HelpDialog',
  props: {
    visible: { type: Boolean, default: false },
    commands: { type: Array, default: () => [] }
  },
  emits: ['close'],
  watch: {
    visible(val) {
      if (val) {
        this.$nextTick(() => {
          const dlg = this.$refs.dialog
          if (dlg) dlg.focus()
        })
      }
    }
  },
  mounted() {
    document.addEventListener('keydown', this.handleKeydown)
  },
  beforeDestroy() {
    document.removeEventListener('keydown', this.handleKeydown)
  },
  methods: {
    /**
     * 弹窗可见时响应 Esc → 关闭。div 上加 tabindex 让它能接 keyboard 事件，
     * 但仍然监听 document 兜底（用户可能在 textarea focus 等其他场景）。
     */
    handleKeydown(e) {
      if (!this.visible) return
      if (e.key === 'Escape') {
        e.preventDefault()
        this.$emit('close')
      }
    }
  },
  computed: {
    actionCommands() {
      return this.commands.filter(c => c.kind === 'action')
    },
    skillCommands() {
      return this.commands.filter(c => c.kind !== 'action')
    },
    /** Mac vs Win/Linux：决定帮助文本里的修饰键与文件管理器名 */
    _isMac() {
      if (typeof navigator === 'undefined') return false
      return /Mac|iPhone|iPad/.test(navigator.platform)
    },
    _modKey() { return this._isMac ? 'Cmd' : 'Ctrl' },
    _modKeyKbd() { return this._isMac ? '⌘' : 'Ctrl' },
    _fileManager() { return this._isMac ? 'Finder' : 'Explorer' }
  }
}
</script>

<style scoped>
.help-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.42);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 24px;
}

.help-dialog {
  width: 100%;
  max-width: 620px;
  max-height: calc(100vh - 48px);
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* dialog 自动 focus 接收键盘事件，不该显示浏览器默认黑 focus ring */
  outline: none;
}

.help-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.help-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.help-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}

.help-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.help-body {
  padding: 18px 20px 22px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.1) transparent;
}

.help-body::-webkit-scrollbar { width: 6px; }
.help-body::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.12); border-radius: 3px; }

.help-section {
  margin-bottom: 18px;
}

.help-section:last-child {
  margin-bottom: 0;
}

.help-section h3 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.02em;
}

/* —— 使用技巧里的子标题（h4） —— 比 h3 小，与正文视觉分层 */
.help-section h4 {
  margin: 12px 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.01em;
}
.help-section h4:first-of-type {
  margin-top: 0;
}

.help-section ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
}

.help-section p {
  margin: 0 0 10px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.help-hint {
  background: var(--bg-secondary);
  padding: 8px 10px;
  border-radius: 6px;
  border-left: 2px solid var(--button-bg);
}

.help-section code {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  padding: 1px 5px;
  background: var(--bg-secondary);
  border-radius: 4px;
  border: 1px solid var(--border-color);
}

/* 键盘按键视觉：白底浅灰边 + 阴影，模拟物理键帽。比 <code> 更"可按" */
.help-section kbd {
  display: inline-block;
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1;
  padding: 3px 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-bottom-width: 2px;
  border-radius: 4px;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.04);
  vertical-align: baseline;
  white-space: nowrap;
}

.help-cmd-group {
  margin-bottom: 12px;
}

.help-cmd-group:last-child {
  margin-bottom: 0;
}

.help-cmd-group-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
  text-transform: uppercase;
  padding: 0 2px 4px;
  user-select: none;
}

.help-cmd-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.help-cmd {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--bg-secondary);
  transition: background 0.12s;
}

.help-cmd:hover {
  background: var(--bg-hover);
}

.help-cmd-name {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}

.help-cmd-desc {
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
  line-height: 1.4;
}

/* 前端动作命令：名字 + 描述变淡一档，与技能命令区分。 */
.help-cmd--action .help-cmd-name {
  color: var(--text-secondary);
  font-weight: 500;
}
.help-cmd--action .help-cmd-desc {
  opacity: 0.85;
}

/* 技能命令组的尾部小提示：解释「软要求」语义 */
.help-cmd-hint {
  margin: 6px 2px 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-secondary);
  opacity: 0.85;
}

.slash-chip-slash {
  opacity: 0.6;
  font-weight: 400;
}

.slash-chip-preview {
  display: inline-block;
  padding: 1px 8px;
  background: rgba(59, 130, 246, 0.14);
  color: rgb(59, 130, 246);
  border-radius: 8px;
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 0.9em;
}

.help-fade-enter-active,
.help-fade-leave-active {
  transition: opacity 0.18s ease;
}
.help-fade-enter-active .help-dialog,
.help-fade-leave-active .help-dialog {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.help-fade-enter-from,
.help-fade-leave-to {
  opacity: 0;
}
.help-fade-enter-from .help-dialog,
.help-fade-leave-to .help-dialog {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
</style>