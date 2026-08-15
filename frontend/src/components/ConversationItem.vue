<template>
  <div
    :class="['conversation-item', {
      'active': isActive,
      'streaming': isStreaming
    }]"
    @click="$emit('select')"
    @contextmenu.prevent="$emit('refresh')"
  >
    <div class="conv-title-row">
      <span
        v-if="isStreaming || isCompletedUnread || isApprovalPending || isErrored"
        :class="['status-dot', {
          'streaming': isStreaming,
          'approval': !isStreaming && isApprovalPending,
          'errored': !isStreaming && !isApprovalPending && isErrored,
          'completed': !isStreaming && !isApprovalPending && !isErrored && isCompletedUnread
        }]"
        :title="dotTitle"
      ></span>
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
    <div class="conv-meta-row">
      <!-- 定时任务触发：放在底部时间行，点击 inline 展开该会话的任务列表 -->
      <button
        v-if="hasScheduledTasks"
        class="scheduled-trigger"
        :class="{ active: isScheduledTasksExpanded }"
        :title="isScheduledTasksExpanded ? '收起定时任务' : '展开定时任务'"
        @click.stop="$emit('toggle-scheduled-tasks')"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
        <svg
          class="caret"
          :class="{ up: isScheduledTasksExpanded }"
          width="9"
          height="9"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
        <span v-if="tasks.length > 1" class="badge">{{ tasks.length }}</span>
      </button>
      <span class="conv-time">{{ formattedTime }}</span>
    </div>

    <!-- 内嵌展开的任务列表（不在浮层里，直接渲染在 conv-item 下方） -->
    <transition name="scheduled-expand">
      <div v-if="isScheduledTasksExpanded" class="scheduled-inline" @click.stop>
        <ScheduledTaskItem
          v-for="task in scheduledTasks"
          :key="task.task_id"
          :task="task"
          :busy="scheduledTasksBusy"
          @toggle="(tid, en) => $emit('scheduled-task-toggle', tid, en)"
          @run="(tid) => $emit('scheduled-task-run', tid)"
          @delete="(tid) => $emit('scheduled-task-delete', tid)"
        />
      </div>
    </transition>

    <button
      @click.stop="handleDeleteClick"
      :class="['delete-btn', { 'confirming': isConfirmingDelete }]"
      :title="isConfirmingDelete ? '再次点击确认删除' : '删除'"
    >×</button>
  </div>
</template>

<script>
import ScheduledTaskItem from './ScheduledTaskItem.vue'

export default {
  name: 'ConversationItem',
  components: { ScheduledTaskItem },
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
    },
    isCompletedUnread: {
      // 流式 clean done 后用户还没点进去过——绿点
      type: Boolean,
      default: false
    },
    isApprovalPending: {
      // permission_request 触发，等用户审批——黄点
      type: Boolean,
      default: false
    },
    isErrored: {
      // SSE error 触发，用户还没点进去看过——红点
      type: Boolean,
      default: false
    },
    scheduledTasks: {
      // 该会话的定时任务列表；空数组 = 没有任务
      type: Array,
      default: () => []
    },
    scheduledTasksBusy: {
      // 是否正在请求（驱动 task 操作按钮的 busy 态）
      type: Boolean,
      default: false
    },
    isScheduledTasksExpanded: {
      // 该会话的定时任务列表是否展开（由 Sidebar 中央管理 + localStorage 缓存）
      type: Boolean,
      default: false
    }
  },
  emits: [
    'select', 'delete', 'update-title', 'refresh',
    'scheduled-task-toggle', 'scheduled-task-run', 'scheduled-task-delete',
    'toggle-scheduled-tasks'
  ],
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
    },
    // 状态点的 tooltip（优先级：streaming > approval > errored > completed）
    dotTitle() {
      if (this.isStreaming) return '正在流式响应…'
      if (this.isApprovalPending) return '等待命令审批'
      if (this.isErrored) return '会话出错（点击查看）'
      if (this.isCompletedUnread) return '已完成（点击查看）'
      return ''
    },
    hasScheduledTasks() {
      return this.scheduledTasks && this.scheduledTasks.length > 0
    },
    tasks() {
      return this.scheduledTasks
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

/* 侧栏状态点通用样式（绿/黄/红 + 蓝闪 streaming） */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.streaming {
  background: var(--button-bg);
  animation: blink 1.2s ease-in-out infinite;
}

.status-dot.completed {
  /* 绿：流式 clean done 后待用户回看（持久到点击） */
  background: #22c55e;
}

.status-dot.approval {
  /* 黄：permission_request 等用户决策（慢脉冲提示 actionable） */
  background: #eab308;
  animation: pulse-yellow 2s ease-in-out infinite;
}

.status-dot.errored {
  /* 红：SSE error 待用户查看 */
  background: #ef4444;
}

@keyframes blink {
  0%, 100% { opacity: 0.3; }
  50%      { opacity: 1; }
}

@keyframes pulse-yellow {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(234, 179, 8, 0.5); }
  50%      { opacity: 0.75; box-shadow: 0 0 0 4px rgba(234, 179, 8, 0); }
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

.conv-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.conv-time {
  font-size: 12px;
  color: var(--text-secondary);
}

/* ⏰ 触发按钮：紧凑、内嵌于 12px 时间行左侧 */
.scheduled-trigger {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  position: relative;
  height: 18px;
  padding: 0 5px;
  border: none;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 11px;
  transition: all 0.15s ease;
}
.scheduled-trigger:hover {
  background: var(--bg-hover);
  color: var(--button-bg);
}
.scheduled-trigger.active {
  background: var(--button-bg);
  color: #fff;
}
.scheduled-trigger .caret {
  opacity: 0.7;
  transition: transform 0.18s ease;
}
.scheduled-trigger .caret.up {
  transform: rotate(180deg);
}

.badge {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  margin-left: 2px;
  opacity: 0.85;
}
.scheduled-trigger.active .badge {
  opacity: 0.9;
}

/* 内嵌展开的定时任务列表 */
.scheduled-inline {
  margin-top: 6px;
  border-top: 1px solid var(--border-color);
  /* 与会话名字区域的横向分割线（上面 6px 间距 + 1px 实线） */
  /* 3 条 task 自然高度 = ~110px；超过 3 条就滚动，避免侧栏被撑得很长 */
  max-height: 110px;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 紧凑滚动条：默认不可见，hover 才显出（与侧栏主滚动条风格一致） */
.scheduled-inline::-webkit-scrollbar {
  width: 0;
}
.scheduled-inline:hover::-webkit-scrollbar {
  width: 4px;
}
.scheduled-inline::-webkit-scrollbar-track {
  background: transparent;
}
.scheduled-inline::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 2px;
  min-height: 20px;
}
.scheduled-inline::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

/* 展开 / 收起动画：高度 + 透明度（max-height 与 .scheduled-inline 保持一致） */
.scheduled-expand-enter-active,
.scheduled-expand-leave-active {
  transition: max-height 0.2s ease, opacity 0.18s ease;
  overflow: hidden;
}
.scheduled-expand-enter-from,
.scheduled-expand-leave-to {
  max-height: 0;
  opacity: 0;
}
.scheduled-expand-enter-to,
.scheduled-expand-leave-from {
  max-height: 110px;
  opacity: 1;
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
