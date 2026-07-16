<template>
  <div
    :class="['conversation-item', { 'active': isActive, 'streaming': isStreaming }]"
    @click="$emit('select')"
    @contextmenu.prevent="$emit('refresh')"
  >
    <div class="conv-title-row">
      <span v-if="isStreaming" class="streaming-dot" title="正在流式响应…"></span>
      <div
        class="conv-title"
        @dblclick.stop="startEdit"
        v-if="!isEditing"
        :title="conversation.title"
      >
        {{ truncatedTitle }}
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
    </div>
    <div class="conv-time">{{ formattedTime }}</div>
    <button
      @click.stop="handleDeleteClick"
      :class="['delete-btn', { 'confirming': isConfirmingDelete }]"
      :title="isConfirmingDelete ? '再次点击确认删除' : '删除'"
    >×</button>
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
    },
    isStreaming: {
      type: Boolean,
      default: false
    }
  },
  emits: ['select', 'delete', 'update-title', 'refresh'],
  data() {
    return {
      isEditing: false,
      editTitle: '',
      currentTime: Date.now(),
      // 行内二次确认：第一次点 × 进入 confirming 态（按钮变红），
      // 第二次点同一按钮才真正 emit delete；点别处 / Esc 取消。
      isConfirmingDelete: false
    }
  },
  computed: {
    truncatedTitle() {
      const title = this.conversation.title || ''
      return title.length > 10 ? title.substring(0, 10) + '...' : title
    },
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
    // 行内二次确认取消：点别处 / Esc 都重置 confirming 态
    document.addEventListener('click', this.cancelDeleteConfirm)
    document.addEventListener('keydown', this.onKeydown)
  },
  beforeUnmount() {
    if (this.timeInterval) {
      clearInterval(this.timeInterval)
    }
    document.removeEventListener('click', this.cancelDeleteConfirm)
    document.removeEventListener('keydown', this.onKeydown)
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
    },
    handleDeleteClick() {
      if (this.isConfirmingDelete) {
        // 第二次点：立刻重置 confirming（防止 document click 收到事件后再 cancel 一次），
        // 然后 emit delete，让 App.vue 真正调 DELETE 接口。
        // 删除成功 → ConversationItem unmount → 监听自动清理。
        // 删除失败 → isConfirmingDelete 已是 false，用户可重新点一次。
        this.isConfirmingDelete = false
        this.$emit('delete')
      } else {
        // 第一次点：进入确认态，按钮变红一直显
        this.isConfirmingDelete = true
      }
    },
    cancelDeleteConfirm(e) {
      // 仅在 confirming 态取消；按钮自身的 click 在 handleDeleteClick 里处理，
      // 但 document click 仍会冒泡到这里——此时 isConfirmingDelete 已是 false（被 handleDeleteClick 重置），
      // 所以这个分支只针对"点别处"的情况生效。
      // 同时检查事件源是否在本组件内（防御性，避免 button click 被二次处理）
      if (this.isConfirmingDelete && this.$el && !this.$el.contains(e?.target)) {
        this.isConfirmingDelete = false
      }
    },
    onKeydown(e) {
      if (e.key === 'Escape' && this.isConfirmingDelete) {
        this.isConfirmingDelete = false
      }
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

.conv-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.streaming-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--button-bg);
  flex-shrink: 0;
  animation: blink 1.2s ease-in-out infinite;
}

@keyframes blink {
  0%, 100% { opacity: 0.3; }
  50%      { opacity: 1; }
}

.conv-title {
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
  cursor: text;
}

.conv-title-input {
  font-size: 14px;
  font-weight: 500;
  padding: 2px 4px;
  background-color: var(--bg-primary);
  border: 1px solid var(--button-bg);
  border-radius: 4px;
  color: var(--text-primary);
  outline: none;
  flex: 1;
  min-width: 0;
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

/* 行内二次确认：confirming 态按钮变红且一直显（不再依赖 hover） */
.delete-btn.confirming {
  opacity: 1;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.12);
}

.delete-btn.confirming:hover {
  color: #dc2626;
  background: rgba(239, 68, 68, 0.22);
}
</style>
