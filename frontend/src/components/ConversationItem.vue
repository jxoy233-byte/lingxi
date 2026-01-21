<template>
  <div
    :class="['conversation-item', { 'active': isActive }]"
    @click="$emit('select')"
  >
    <div
      class="conv-title"
      @dblclick.stop="startEdit"
      v-if="!isEditing"
    >
      {{ conversation.title }}
    </div>
    <input
      v-else
      v-model="editTitle"
      class="conv-title-input"
      @blur="saveTitle"
      @keyup.enter="saveTitle"
      @keyup.esc="cancelEdit"
      @click.stop
      ref="titleInput"
    />
    <div class="conv-time">{{ formattedTime }}</div>
    <button @click.stop="$emit('delete')" class="delete-btn">×</button>
  </div>
</template>

<script>
export default {
  name: 'ConversationItem',
  props: {
    conversation: {
      type: Object,
      required: true
    },
    isActive: {
      type: Boolean,
      default: false
    }
  },
  emits: ['select', 'delete', 'update-title'],
  data() {
    return {
      isEditing: false,
      editTitle: '',
      currentTime: Date.now()
    }
  },
  computed: {
    formattedTime() {
      if (!this.conversation.updated_at) return ''

      const updatedAt = new Date(this.conversation.updated_at)
      const diffMs = this.currentTime - updatedAt.getTime()
      const diffMinutes = Math.floor(diffMs / 60000)
      const diffHours = Math.floor(diffMs / 3600000)
      const diffDays = Math.floor(diffMs / 86400000)

      if (diffMinutes < 1) return '刚刚'
      if (diffMinutes < 60) return `${diffMinutes}分钟前`
      if (diffHours < 24) return `${diffHours}小时前`
      if (diffDays < 30) return `${diffDays}天前`

      return updatedAt.toLocaleDateString('zh-CN')
    }
  },
  mounted() {
    // 每分钟更新一次时间显示
    this.timeInterval = setInterval(() => {
      this.currentTime = Date.now()
    }, 60000)
  },
  beforeUnmount() {
    if (this.timeInterval) {
      clearInterval(this.timeInterval)
    }
  },
  methods: {
    startEdit() {
      this.isEditing = true
      this.editTitle = this.conversation.title
      this.$nextTick(() => {
        this.$refs.titleInput?.focus()
        this.$refs.titleInput?.select()
      })
    },
    saveTitle() {
      if (!this.editTitle.trim()) {
        this.cancelEdit()
        return
      }

      this.$emit('update-title', {
        sessionId: this.conversation.session_id,
        title: this.editTitle.trim()
      })
      this.isEditing = false
    },
    cancelEdit() {
      this.isEditing = false
      this.editTitle = ''
    }
  }
}
</script>

<style scoped>
.conversation-item {
  padding: 12px;
  margin-bottom: 4px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  transition: background 0.2s;
}

.conversation-item:hover {
  background: var(--bg-hover);
}

.conversation-item.active {
  background: var(--bg-hover);
}

.conv-title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 24px;
  cursor: text;
}

.conv-title-input {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
  padding: 2px 4px;
  background-color: var(--bg-primary);
  border: 1px solid var(--button-bg);
  border-radius: 4px;
  color: var(--text-primary);
  outline: none;
  width: calc(100% - 32px);
}

.conv-time {
  font-size: 12px;
  color: var(--text-secondary);
}

.delete-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 4px;
  cursor: pointer;
  font-size: 20px;
  line-height: 1;
  opacity: 0;
  transition: all 0.2s;
}

.conversation-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
</style>
