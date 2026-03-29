<template>
  <header class="chat-header">
    <h1>ChatMe</h1>
    <div class="header-actions">
      <button
        v-if="hasSession"
        @click="$emit('toggle-checkpoints')"
        class="checkpoint-btn"
        title="查看历史版本"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
      </button>
      <button
        @click="$emit('toggle-theme')"
        class="theme-toggle-btn"
        :title="isDarkTheme ? '切换到浅色模式' : '切换到深色模式'"
      >
        <span v-if="isDarkTheme">☀️</span>
        <span v-else>🌙</span>
      </button>
    </div>
  </header>
</template>

<script>
export default {
  name: 'ChatHeader',
  props: {
    isDarkTheme: {
      type: Boolean,
      default: false
    },
    hasSession: {
      type: Boolean,
      default: false
    }
  },
  emits: ['toggle-theme', 'toggle-checkpoints']
}
</script>

<style scoped>
.chat-header {
  height: 60px;
  background-color: var(--header-bg);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.chat-header h1 {
  font-size: 20px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.checkpoint-btn,
.theme-toggle-btn {
  width: 40px;
  height: 40px;
  border: none;
  background: var(--bg-hover);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.checkpoint-btn {
  color: var(--text-secondary);
}

.checkpoint-btn:hover {
  background: var(--bg-hover);
  color: var(--button-bg);
  opacity: 0.8;
}

.theme-toggle-btn {
  font-size: 20px;
}

.theme-toggle-btn:hover {
  background: var(--bg-hover);
  opacity: 0.8;
}
</style>
