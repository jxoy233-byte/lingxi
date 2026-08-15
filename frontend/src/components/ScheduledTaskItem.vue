<!--
  ScheduledTaskItem.vue

  单条定时任务行。展示：
  - 状态圆点 + 任务名
  - cron 表达式 · 上次运行时间 · 累计次数（单行 meta，保持行高紧凑）
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
          <span class="status-dot" :class="task.enabled ? 'on' : 'off'"></span>
          <span class="task-name">{{ task.name }}</span>
        </div>
        <div class="task-meta">
          <span class="cron">{{ task.cron }}</span>
          <span class="dot">·</span>
          <span v-if="lastRunLabel" :class="lastRunStatus">{{ lastRunLabel }}</span>
          <span v-else class="none">尚未运行</span>
          <span class="dot">·</span>
          <span>{{ task.run_count || 0 }} 次</span>
        </div>
      </div>

      <div class="task-actions">
        <button
          class="icon-btn"
          :title="task.enabled ? '暂停' : '启用'"
          :disabled="busy"
          @click.stop="onToggle"
        >
          <svg v-if="task.enabled" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <line x1="9" y1="5" x2="9" y2="19" />
            <line x1="15" y1="5" x2="15" y2="19" />
          </svg>
          <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="6 4 20 12 6 20 6 4" />
          </svg>
        </button>
        <button
          class="icon-btn"
          title="立即运行一次"
          :disabled="busy"
          @click.stop="$emit('run', task.task_id)"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 4 14 11 14 10 22 20 10 13 10 13 2" />
          </svg>
        </button>
        <button
          class="icon-btn delete"
          :class="{ confirming: confirmingDelete }"
          :title="confirmingDelete ? '再次点击确认删除' : '删除'"
          :disabled="busy"
          @click.stop="onDelete"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 21 6" />
            <path d="M8 6V4h8v2" />
            <path d="M6 6l1 14h10l1-14" />
          </svg>
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
  padding: 6px 12px;     /* 紧凑：左右 12 / 上下 6，单条 task 高度 ~36px（不含右侧按钮列时） */
  border-bottom: 1px solid var(--border-color);
  font-size: 13px;       /* 紧凑：略缩，配合侧栏窄宽度 */
  transition: background 0.15s ease;
}
.task-item:last-child {
  border-bottom: none;
}
.task-item:hover {
  background: var(--bg-hover);
}
.task-item.disabled {
  opacity: 0.6;
}
.task-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;   /* 让 name + meta 整体在 task-row 高度内垂直居中（与右侧按钮列对齐） */
}
.task-name-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.on {
  background: #22c55e;
}
.status-dot.off {
  background: var(--text-secondary);
  opacity: 0.5;
}
.task-name {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-secondary);
  margin-top: 2px;
  padding-left: 12px;
  overflow: hidden;
  white-space: nowrap;
}
.cron {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.dot {
  opacity: 0.4;
}
.ok { color: #22c55e; }
.none { opacity: 0.7; }

/* 操作按钮：紧凑竖排，作为 .task-row 的 flex 子项；
   默认 opacity: 0 隐藏，task-row / task-actions hover 时显出（保留常驻位置，仅淡入） */
.task-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.task-row:hover .task-actions,
.task-actions:hover,
.task-actions:focus-within {
  opacity: 1;
}
.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: 3px;
  padding: 2px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background 0.15s ease, color 0.15s ease;
}
.icon-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.icon-btn.delete:hover:not(:disabled) {
  color: #ef4444;
}
/* 行内二次确认：变红常显（见 CLAUDE.md 偏好 21） */
.icon-btn.delete.confirming {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.12);
  opacity: 1;
}

/* 触屏无 hover：操作按钮常显 */
@media (hover: none) {
  .task-actions { opacity: 1; }
}
</style>