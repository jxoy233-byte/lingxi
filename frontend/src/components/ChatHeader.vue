<template>
  <header class="chat-header">
    <div class="header-left">
      <button
        class="hamburger-btn"
        @click="$emit('toggle-sidebar')"
        title="打开菜单"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="3" y1="6" x2="21" y2="6"/>
          <line x1="3" y1="12" x2="21" y2="12"/>
          <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <h1>灵析</h1>
    </div>
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
  emits: ['toggle-theme', 'toggle-checkpoints', 'toggle-sidebar']
}
</script>

<style scoped>
.chat-header {
  height: var(--header-height, 60px);
  background-color: var(--header-bg);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hamburger-btn {
  display: none;
  width: 36px;
  height: 36px;
  border: none;
  background: var(--bg-hover);
  border-radius: 8px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  color: var(--text-primary);
  transition: background 0.2s;
}

.hamburger-btn:hover {
  background: var(--bg-hover);
  opacity: 0.8;
}

@media (max-width: 600px) {
  .hamburger-btn {
    display: flex;
  }
  .chat-header {
    padding: 0 12px;
  }
  .chat-header h1 {
    font-size: 17px;
  }
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
