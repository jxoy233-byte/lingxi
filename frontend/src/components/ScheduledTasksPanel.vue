<!--
  ScheduledTasksPanel.vue

  窗帘式下拉：当前会话的定时任务列表
  - 收起态（默认）：只显示 ⏰ N 个定时任务  ▼
  - 展开态：滑出任务列表 + 创建按钮
  - 空任务列表：整个面板隐藏（不显示"创建"提示）

  Props:
    tasks: Array<ScheduledTask>     当前会话的任务列表
    busy: Boolean                    整体 busy（disable 所有操作）
    session-id: String              当前 session_id（用于在创建任务时预填）

  Emits:
    toggle(task_id, new_enabled)
    run(task_id)
    delete(task_id)
    create(payload)                  父组件负责调 API
    refresh()                        手动刷新
-->
<template>
  <div v-if="tasks.length > 0" class="scheduled-panel">
    <button class="curtain-bar" @click="toggle">
      <span class="left">
        <span class="icon">⏰</span>
        <span class="label">{{ tasks.length }} 个定时任务</span>
      </span>
      <span class="right">
        <button
          class="refresh-btn"
          :class="{ spinning: refreshing }"
          :disabled="refreshing"
          title="刷新"
          @click.stop="onRefresh"
        >
          ↻
        </button>
        <span class="caret" :class="{ up: expanded }">▼</span>
      </span>
    </button>

    <Transition name="curtain">
      <div v-if="expanded" class="task-list-wrapper">
        <div class="task-list">
          <ScheduledTaskItem
            v-for="task in tasks"
            :key="task.task_id"
            :task="task"
            :busy="busy"
            @toggle="(...args) => $emit('toggle', ...args)"
            @run="(tid) => $emit('run', tid)"
            @delete="(tid) => $emit('delete', tid)"
          />
        </div>
      </div>
    </Transition>
  </div>
</template>

<script>
import ScheduledTaskItem from './ScheduledTaskItem.vue'

export default {
  name: 'ScheduledTasksPanel',
  components: { ScheduledTaskItem },
  props: {
    tasks: {
      type: Array,
      default: () => [],
    },
    busy: {
      type: Boolean,
      default: false,
    },
    refreshing: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      expanded: false,  // 默认收起
    }
  },
  methods: {
    toggle() {
      this.expanded = !this.expanded
    },
    onRefresh() {
      this.$emit('refresh')
    },
  },
}
</script>

<style scoped>
.scheduled-panel {
  /* 固定顶部、消息列表之上；高度随 expanded 自适应 */
  flex-shrink: 0;
  background: var(--panel-bg, #f9fafb);
  border-bottom: 1px solid var(--border-color, #e5e7eb);
}
.curtain-bar {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary, #6b7280);
  transition: background 0.15s ease;
  min-height: 40px;
}
.curtain-bar:hover {
  background: var(--hover-bg, rgba(0, 0, 0, 0.03));
}
.left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.right {
  display: flex;
  align-items: center;
  gap: 4px;
}
.icon { font-size: 14px; }
.label { font-weight: 500; }
.caret {
  display: inline-block;
  transition: transform 0.25s ease;
  font-size: 10px;
  padding: 0 6px;
}
.caret.up {
  transform: rotate(180deg);
}
.refresh-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-secondary, #6b7280);
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.15s ease;
}
.refresh-btn:hover:not(:disabled) {
  background: var(--hover-bg, rgba(0, 0, 0, 0.05));
  color: var(--text-primary, #1f2937);
}
.refresh-btn:disabled {
  cursor: default;
}
.refresh-btn.spinning {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 窗帘式展开：用 max-height + overflow:hidden 做平滑过渡 */
.task-list-wrapper {
  max-height: 320px;
  overflow: hidden;
  overflow-y: auto;
  border-top: 1px solid var(--border-color, #e5e7eb);
  background: var(--bg-primary, #ffffff);
}
.task-list {
  /* 全量入 DOM（不切片）；滚动交给 wrapper */
}
.curtain-enter-active,
.curtain-leave-active {
  transition: max-height 0.3s ease, opacity 0.25s ease;
  overflow: hidden;
}
.curtain-enter-from,
.curtain-leave-to {
  max-height: 0;
  opacity: 0;
}
.curtain-enter-to,
.curtain-leave-from {
  max-height: 320px;
  opacity: 1;
}
</style>