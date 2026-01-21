<template>
  <header class="chat-header">
    <h1>ChatMe</h1>
    <div class="header-actions">
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
    }
  },
  emits: ['toggle-theme']
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

.theme-toggle-btn {
  width: 40px;
  height: 40px;
  border: none;
  background: var(--bg-hover);
  border-radius: 8px;
  cursor: pointer;
  font-size: 20px;
  transition: background 0.2s;
}

.theme-toggle-btn:hover {
  background: var(--bg-hover);
  opacity: 0.8;
}
</style>
