<template>
  <aside :class="['sidebar', { 'collapsed': collapsed }]">
    <div class="sidebar-header">
      <button @click="$emit('toggle')" class="toggle-btn">
        <span v-if="!collapsed">☰</span>
        <span v-else>→</span>
      </button>
      <button v-if="!collapsed" @click="$emit('new-chat')" class="new-chat-btn">
        + 新对话
      </button>
    </div>

    <div v-if="!collapsed" class="conversation-list">
      <ConversationItem
        v-for="conv in conversations"
        :key="conv.session_id"
        :conversation="conv"
        :is-active="conv.session_id === activeSessionId"
        @select="$emit('select-conversation', conv.session_id)"
        @delete="$emit('delete-conversation', conv.session_id)"
        @update-title="$emit('update-title', $event)"
      />
      <div v-if="conversations.length === 0" class="empty-state">
        暂无历史对话
      </div>
    </div>
  </aside>
</template>

<script>
import ConversationItem from './ConversationItem.vue'

export default {
  name: 'Sidebar',
  components: {
    ConversationItem
  },
  props: {
    collapsed: {
      type: Boolean,
      default: false
    },
    conversations: {
      type: Array,
      default: () => []
    },
    activeSessionId: {
      type: String,
      default: null
    }
  },
  emits: ['toggle', 'new-chat', 'select-conversation', 'delete-conversation', 'update-title']
}
</script>

<style scoped>
.sidebar {
  width: 260px;
  background-color: var(--sidebar-bg);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  transition: width 0.3s ease;
}

.sidebar.collapsed {
  width: 60px;
}

.sidebar-header {
  padding: 12px;
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border-color);
}

.toggle-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: var(--bg-hover);
  border-radius: 6px;
  cursor: pointer;
  font-size: 18px;
  color: var(--text-primary);
  transition: background 0.2s;
}

.toggle-btn:hover {
  background: var(--bg-hover);
  opacity: 0.8;
}

.new-chat-btn {
  flex: 1;
  height: 36px;
  border: none;
  background: var(--button-bg);
  color: white;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.2s;
}

.new-chat-btn:hover {
  background: var(--button-hover);
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.empty-state {
  text-align: center;
  color: var(--text-secondary);
  padding: 20px;
  font-size: 14px;
}
</style>
