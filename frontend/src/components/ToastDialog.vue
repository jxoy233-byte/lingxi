<template>
  <transition name="toast-fade">
    <div v-if="visible" class="toast-overlay" @click.self="$emit('close')">
      <div class="toast-dialog" role="dialog" aria-modal="true" aria-labelledby="toast-dialog-title" tabindex="-1" ref="dialog">
        <div class="toast-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        </div>
        <div class="toast-body">
          <h2 id="toast-dialog-title" class="toast-title">{{ title }}</h2>
          <p v-if="message" class="toast-message">{{ message }}</p>
        </div>
        <button type="button" class="toast-close" @click="$emit('close')">知道了</button>
      </div>
    </div>
  </transition>
</template>

<script>
export default {
  name: 'ToastDialog',
  props: {
    visible: { type: Boolean, default: false },
    title: { type: String, default: '提示' },
    message: { type: String, default: '' }
  },
  emits: ['close'],
  watch: {
    visible(val) {
      if (val) {
        // dialog 自动 focus，确保 div 上的 tabindex 能接到键盘事件。
        // 同时也兜底 document 监听器，处理用户没在 dialog 内的情况。
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
     * 弹窗可见时响应 Esc / Enter。Enter 走「知道了」按钮等同路径（emit close），
     * Esc 同。div 上虽然加了 tabindex，但用户可能在 focus 别的元素，
     * document 监听确保任意 focus 状态都能生效。
     */
    handleKeydown(e) {
      if (!this.visible) return
      if (e.key === 'Escape') {
        e.preventDefault()
        this.$emit('close')
      } else if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault()
        this.$emit('close')
      }
    }
  }
}
</script>

<style scoped>
.toast-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.32);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2100;
  padding: 24px;
}

.toast-dialog {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  max-width: 420px;
  padding: 16px 18px;
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.16);
  /* dialog 自动 focus 接收键盘事件，不该显示浏览器默认黑 focus ring。
     关闭按钮 hover 高亮已足够表达「这里有关闭控件」。 */
  outline: none;
}

.toast-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.14);
  color: rgb(180, 83, 9);
}

.toast-body {
  flex: 1;
  min-width: 0;
}

.toast-title {
  margin: 0 0 2px;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.toast-message {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.toast-close {
  flex-shrink: 0;
  padding: 6px 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 7px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}

.toast-close:hover {
  background: var(--bg-hover);
  border-color: var(--button-bg);
}

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: opacity 0.15s ease;
}
.toast-fade-enter-active .toast-dialog,
.toast-fade-leave-active .toast-dialog {
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
}
.toast-fade-enter-from .toast-dialog,
.toast-fade-leave-to .toast-dialog {
  opacity: 0;
  transform: translateY(6px) scale(0.97);
}
</style>