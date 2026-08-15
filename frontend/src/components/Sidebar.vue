<template>
  <aside :class="['sidebar', { 'collapsed': collapsed, 'mobile-open': mobileOpen }]">
    <div class="sidebar-header">
      <button @click="$emit('toggle')" class="toggle-btn">
        <span v-if="!collapsed">☰</span>
        <span v-else>→</span>
      </button>
      <button v-if="!collapsed" @click="$emit('new-chat')" class="new-chat-btn">
        + 新对话
      </button>
    </div>

    <div
      v-if="!collapsed"
      class="conversation-list"
      :class="{ 'has-overflow': hasOverflow }"
      ref="conversationListRef"
    >
      <ConversationItem
        v-for="(conv, index) in conversations"
        :key="conv.session_id"
        :conversation="conv"
        :is-active="conv.session_id === activeSessionId"
        :is-streaming="activeStreamingSessions.has(conv.session_id)"
        :is-completed-unread="completedSessions.has(conv.session_id)"
        :is-approval-pending="approvalPendingSessions.has(conv.session_id)"
        :is-errored="errorSessions.has(conv.session_id)"
        :scheduled-tasks="scheduledTasksMap.get(conv.session_id) || []"
        :scheduled-tasks-busy="scheduledTasksBusy"
        :is-scheduled-tasks-expanded="expandedScheduledTasks.has(conv.session_id)"
        @select="$emit('select-conversation', conv.session_id)"
        @delete="$emit('delete-conversation', conv.session_id)"
        @update-title="$emit('update-title', $event)"
        @refresh="$emit('refresh-conversation', conv.session_id)"
        @scheduled-task-toggle="(...args) => $emit('scheduled-task-toggle', ...args)"
        @scheduled-task-run="(tid) => $emit('scheduled-task-run', tid)"
        @scheduled-task-delete="(tid) => $emit('scheduled-task-delete', tid)"
        @toggle-scheduled-tasks="toggleScheduledTasksExpanded(conv.session_id)"
      />
      <div v-if="loadError" class="empty-state load-error">
        <div>加载对话列表失败</div>
        <div class="load-error-detail">{{ loadError }}</div>
        <div class="load-error-hint">请确认灵析后端服务已启动</div>
      </div>
      <div v-else-if="conversations.length === 0" class="empty-state">
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
    mobileOpen: {
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
    },
    activeStreamingSessions: {
      // 正在流式的 session_id Set；由 App.vue 整 Set 替换触发响应式
      type: Set,
      default: () => new Set()
    },
    completedSessions: {
      // 已完成（clean done）但用户还没点进去过的 session_id Set —— 侧栏绿点
      type: Set,
      default: () => new Set()
    },
    approvalPendingSessions: {
      // 等用户审批的 session_id Set —— 侧栏黄点
      type: Set,
      default: () => new Set()
    },
    errorSessions: {
      // 出错但用户还没点进去看的 session_id Set —— 侧栏红点（与 _sessionHadError 并行，独立清除）
      type: Set,
      default: () => new Set()
    },
    loadError: {
      // loadConversations 失败时的错误消息（App.vue 写入），空字符串 = 没有错误
      type: String,
      default: ''
    },
    scheduledTasksMap: {
      // session_id -> tasks[] 的 Map（由 App.vue 整 Map 替换触发响应式）
      type: Map,
      default: () => new Map()
    },
    scheduledTasksBusy: {
      // 是否有正在发起的 scheduled-tasks 请求（驱动各 ConversationItem 内 panel 的 busy 态）
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      hasOverflow: false,
      _resizeObserver: null,
      // 已展开的会话定时任务列表（session_id Set）—— 简单前端缓存：刷新页面后保留
      expandedScheduledTasks: new Set()
    }
  },
  mounted() {
    // 从 localStorage 恢复展开状态（per-user 配置，简单 key）
    try {
      const raw = localStorage.getItem('lingxi.scheduledTasksExpanded')
      if (raw) {
        const arr = JSON.parse(raw)
        if (Array.isArray(arr)) {
          this.expandedScheduledTasks = new Set(arr)
        }
      }
    } catch (e) {
      // localStorage 不可用（隐私模式 / SSR）静默降级，状态不持久即可
    }

    // 等 DOM 渲染后再测一次，避免第一次拿到的 clientHeight 还是 0
    this.$nextTick(() => this.checkOverflow())
    // 监听内容尺寸变化（conversations 增删 / 窗口大小变化），重新检测是否溢出
    if (typeof ResizeObserver !== 'undefined' && this.$refs.conversationListRef) {
      this._resizeObserver = new ResizeObserver(() => this.checkOverflow())
      this._resizeObserver.observe(this.$refs.conversationListRef)
    }
    window.addEventListener('resize', this.checkOverflow)
  },
  beforeUnmount() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect()
      this._resizeObserver = null
    }
    window.removeEventListener('resize', this.checkOverflow)
  },
  watch: {
    // conversations 变化时（新增 / 删除会话）重新检测
    conversations() {
      this.$nextTick(() => this.checkOverflow())
    },
    collapsed() {
      this.$nextTick(() => this.checkOverflow())
    },
    // expandedScheduledTasks 变化时同步到 localStorage（deep 监视 Set.add / Set.delete）
    expandedScheduledTasks: {
      handler(newSet) {
        try {
          localStorage.setItem(
            'lingxi.scheduledTasksExpanded',
            JSON.stringify(Array.from(newSet))
          )
        } catch (e) {
          // 写不进去（配额 / 隐私模式）静默
        }
      },
      deep: true
    }
  },
  methods: {
    /**
     * 检测会话列表是否溢出（scrollHeight > clientHeight）
     * 溢出时挂 .has-overflow class，让 webkit 滚动条样式生效
     * 不溢出时 width: 0 滚动条彻底消失，避免一直碍眼
     */
    checkOverflow() {
      const el = this.$refs.conversationListRef
      if (!el) return
      // +1 容差，避免 sub-pixel 抖动导致 hasOverflow 反复 toggle
      const overflow = el.scrollHeight > el.clientHeight + 1
      if (overflow !== this.hasOverflow) {
        this.hasOverflow = overflow
      }
    },
    /**
     * 切换指定会话的定时任务列表展开状态
     * —— Vue 2 Set 不响应式追踪 .add / .delete，必须整 Set 替换触发子组件重渲染
     */
    toggleScheduledTasksExpanded(sessionId) {
      if (!sessionId) return
      const next = new Set(this.expandedScheduledTasks)
      if (next.has(sessionId)) {
        next.delete(sessionId)
      } else {
        next.add(sessionId)
      }
      this.expandedScheduledTasks = next
    }
  },
  emits: ['toggle', 'new-chat', 'select-conversation', 'delete-conversation', 'update-title', 'refresh-conversation', 'scheduled-task-toggle', 'scheduled-task-run', 'scheduled-task-delete']
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
  /* 显式锁死高度为整个视口，不依赖父容器的 flex 计算；
     overflow: hidden 让 sidebar 内部自己处理滚动，避免外层被内容撑大 */
  height: 100vh;
  flex-shrink: 0;
  overflow: hidden;
}

.sidebar.collapsed {
  width: 60px;
}

.sidebar-header {
  /* 头部固定高度，不参与 flex 计算，让 conversation-list 能精确算出剩余高度 */
  flex-shrink: 0;
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
  /* 直接用 calc(100vh - 60px) 算出剩余高度（60px = 头部 12+36+12 高度），
     完全绕过 flex 子项的 min-height: auto 滚动失效问题 */
  height: calc(100vh - 60px);
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  box-sizing: border-box;
}

/* 滚动条：默认 width: 0 完全不可见；溢出时（.has-overflow）才显出 6px 细条
   不依赖 macOS 系统设置（有些用户系统设置是"始终显示滚动条"，
   加这条 local 覆盖让行为统一）。这也是为啥不能直接靠 webkit 默认行为 */
.conversation-list::-webkit-scrollbar {
  width: 0;
}

.conversation-list.has-overflow::-webkit-scrollbar {
  width: 6px;
}

.conversation-list.has-overflow::-webkit-scrollbar-track {
  background: transparent;
}

.conversation-list.has-overflow::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
  /* min-height 保证滑块最小可拖高度 */
  min-height: 30px;
}

.conversation-list.has-overflow::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

.empty-state {
  text-align: center;
  color: var(--text-secondary);
  padding: 20px;
  font-size: 14px;
}

/* 加载错误态：明确告诉用户「后端没起」而不是显示空白让人猜 */
.empty-state.load-error {
  text-align: left;
  padding: 14px 12px;
}
.load-error-detail {
  margin-top: 4px;
  font-size: 11px;
  color: var(--danger-color, #ff3b30);
  word-break: break-all;
  opacity: 0.85;
}
.load-error-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.7;
}

@media (max-width: 600px) {
  .sidebar {
    position: fixed;
    left: -260px;
    top: 0;
    height: 100vh;
    z-index: 100;
    width: 260px;
    transition: left 0.3s ease;
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.15);
  }
  .sidebar.mobile-open {
    left: 0;
  }
  .sidebar.collapsed {
    width: 260px;
  }
  .sidebar-header {
    padding: 16px 12px;
  }
}
</style>
