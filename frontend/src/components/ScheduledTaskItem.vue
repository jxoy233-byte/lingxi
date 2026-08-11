<!--
  ScheduledTaskItem.vue

  单条定时任务行。展示：
  - 任务名 + enabled 状态徽章
  - cron 表达式 + 下次运行时间（如果有）
  - 上次运行状态（success / error / interrupted）+ 时长
  - 操作按钮：暂停/启用 / 立即运行 / 删除（带行内二次确认小红叉）

  Props:
    task: { task_id, name, cron, prompt_preview, session_id, enabled, run_count, last_run }
    busy: 当前正在处理这个 task（disable 所有按钮）

  Emits:
    toggle(task_id, new_enabled)
    run(task_id)
    delete(task_id)
-->
<template>
  <div class="task-item" :class="{ disabled: !task.enabled }">
    <div class="task-row">
      <div class="task-main">
        <div class="task-name-line">
          <span class="task-name">{{ task.name }}</span>
          <span class="task-badge" :class="task.enabled ? 'on' : 'off'">
            {{ task.enabled ? '启用' : '暂停' }}
          </span>
        </div>
        <div class="task-meta">
          <span class="cron">⏰ {{ task.cron }}</span>
          <span class="dot">·</span>
          <span class="session">session: {{ task.session_id || '<auto>' }}</span>
        </div>
        <div class="task-stats">
          <span v-if="lastRunLabel" class="last-run" :class="lastRunStatus">
            {{ lastRunLabel }}
          </span>
          <span v-else class="last-run none">尚未运行</span>
          <span class="dot">·</span>
          <span class="run-count">累计 {{ task.run_count || 0 }} 次</span>
        </div>
      </div>

      <div class="task-actions">
        <button
          class="icon-btn"
          :title="task.enabled ? '暂停' : '启用'"
          :disabled="busy"
          @click.stop="onToggle"
        >
          <span v-if="task.enabled">⏸</span>
          <span v-else>▶</span>
        </button>
        <button
          class="icon-btn"
          title="立即运行一次"
          :disabled="busy"
          @click.stop="$emit('run', task.task_id)"
        >
          ⚡
        </button>
        <button
          class="icon-btn delete"
          :class="{ confirming: confirmingDelete }"
          :title="confirmingDelete ? '再次点击确认删除' : '删除'"
          :disabled="busy"
          @click.stop="onDelete"
        >
          🗑
        </button>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ScheduledTaskItem',
  props: {
    task: {
      type: Object,
      required: true,
    },
    busy: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      confirmingDelete: false,  // 行内二次确认小红叉状态机（小红叉见 CLAUDE.md 偏好 21）
    }
  },
  computed: {
    lastRunLabel() {
      if (!this.task.last_run) return null
      // last_run 是 time.time() 时间戳（秒）；前端显示「MM-DD HH:MM」
      const d = new Date(this.task.last_run * 1000)
      const pad = (n) => String(n).padStart(2, '0')
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    },
    lastRunStatus() {
      // history 第一条 = 最近一次执行；从 task 上没有 history 字段，
      // 所以这里只能根据 run_count 是否为 0 来判定「无历史」
      // status 判定留给未来 SSE 事件推动，本组件先按 enabled 切色
      return this.task.enabled ? 'ok' : 'paused'
    },
  },
  mounted() {
    // 行内小红叉状态机：点别处 / Esc 取消
    document.addEventListener('click', this.cancelDeleteConfirm)
    document.addEventListener('keydown', this.onKeydown)
  },
  beforeUnmount() {
    document.removeEventListener('click', this.cancelDeleteConfirm)
    document.removeEventListener('keydown', this.onKeydown)
  },
  methods: {
    onToggle() {
      this.$emit('toggle', this.task.task_id, !this.task.enabled)
    },
    onDelete() {
      if (this.confirmingDelete) {
        // 第二次点红叉：立刻重置再 emit（防止 document click 冒泡再触发 cancel）
        this.confirmingDelete = false
        this.$emit('delete', this.task.task_id)
      } else {
        this.confirmingDelete = true
      }
    },
    cancelDeleteConfirm(e) {
      if (this.confirmingDelete && !this.$el.contains(e.target)) {
        this.confirmingDelete = false
      }
    },
    onKeydown(e) {
      if (e.key === 'Escape' && this.confirmingDelete) {
        this.confirmingDelete = false
      }
    },
  },
}
</script>

<style scoped>
.task-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  font-size: 13px;
  transition: background 0.15s ease;
}
.task-item:hover {
  background: var(--hover-bg, rgba(0, 0, 0, 0.03));
}
.task-item.disabled {
  opacity: 0.7;
}
.task-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.task-main {
  flex: 1;
  min-width: 0;
}
.task-name-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.task-name {
  font-weight: 500;
  color: var(--text-primary, #1f2937);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-badge {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  flex-shrink: 0;
}
.task-badge.on {
  background: rgba(34, 197, 94, 0.12);
  color: rgb(34, 197, 94);
}
.task-badge.off {
  background: rgba(156, 163, 175, 0.15);
  color: rgb(107, 114, 128);
}
.task-meta,
.task-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
  margin-top: 2px;
}
.dot {
  opacity: 0.5;
}
.last-run.ok { color: rgb(34, 197, 94); }
.last-run.paused { color: var(--text-secondary, #6b7280); }
.last-run.none { color: var(--text-tertiary, #9ca3af); }
.task-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.icon-btn {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  padding: 4px 6px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  color: var(--text-secondary, #6b7280);
  transition: all 0.15s ease;
}
.icon-btn:hover:not(:disabled) {
  background: var(--hover-bg, rgba(0, 0, 0, 0.05));
  color: var(--text-primary, #1f2937);
}
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.icon-btn.delete.confirming {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.12);
  opacity: 1;
}
</style>