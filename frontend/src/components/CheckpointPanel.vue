<template>
  <transition name="slide">
    <aside v-if="visible" class="checkpoint-panel" tabindex="-1" ref="panel" @keydown="handleKeydown">
      <div class="panel-header">
        <h3>历史记录</h3>
        <button @click="$emit('close')" class="close-btn">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <div class="panel-content">
        <div v-if="checkpoints.length === 0" class="empty-state">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          <p>暂无历史记录</p>
        </div>

        <div v-else class="checkpoint-list">
          <div
            v-for="(checkpoint, index) in checkpoints"
            :key="checkpoint.checkpoint_id"
            class="checkpoint-item"
            :class="{ 'kb-active': selectedIndex === index }"
            @click="selectIndex(index)"
          >
            <div class="checkpoint-icon">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <polyline points="12 6 12 12 16 14"/>
              </svg>
            </div>
            <div class="checkpoint-info">
              <div class="checkpoint-title">对话 {{ checkpoints.length - index }}</div>
              <div class="checkpoint-preview">{{ checkpoint.content_preview }}...</div>
            </div>
            <button class="restore-btn" title="恢复到此版本（Enter 也可触发）" @click.stop="handleRestore(checkpoint)">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="1 4 1 10 7 10"/>
                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </aside>
  </transition>
</template>

<script>
export default {
  name: 'CheckpointPanel',
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    messages: {
      type: Array,
      default: () => []
    }
  },
  emits: ['close', 'restore'],
  data() {
    return {
      // 键盘高亮的 checkpoint 下标（最新一条默认高亮）
      selectedIndex: 0
    }
  },
  watch: {
    visible(val) {
      if (val) {
        // 重新打开时复位到第一条（最新）
        this.selectedIndex = 0
        this.$nextTick(() => {
          const p = this.$refs.panel
          if (p && p.focus) p.focus()
          this.scrollActiveIntoView()
        })
      }
    },
    selectedIndex() {
      this.$nextTick(this.scrollActiveIntoView)
    }
  },
  computed: {
    checkpoints() {
      // 从消息列表中提取所有带 checkpointId 的 AI 消息
      return this.messages
        .map((msg, index) => {
          if (msg.role === 'ai' && msg.checkpointId) {
            return {
              checkpoint_id: msg.checkpointId,
              message_index: index,
              content_preview: msg.content.substring(0, 50)
            }
          }
          return null
        })
        .filter(cp => cp !== null)
        .reverse() // 最新的在前面
    }
  },
  methods: {
    handleRestore(checkpoint) {
      this.$emit('restore', checkpoint.checkpoint_id)
    },
    /**
     * checkpoint 列表键盘导航：
     *   - ↑ / ↓: 切换高亮条目（夹紧到 [0, len-1]）
     *   - Enter: 恢复当前高亮条目
     *   - Esc: 关闭面板
     * 监听挂在 panel aside 上（tabindex=-1 + open 时自动 focus），保证键盘
     * 焦点在面板内就能生效。click 也更新 selectedIndex，让鼠标/键盘双轨同步。
     */
    handleKeydown(e) {
      const list = this.checkpoints
      if (list.length === 0) {
        if (e.key === 'Escape') {
          e.preventDefault()
          this.$emit('close')
        }
        return
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        this.selectedIndex = Math.min(this.selectedIndex + 1, list.length - 1)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        this.selectedIndex = Math.max(this.selectedIndex - 1, 0)
      } else if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault()
        const cp = list[this.selectedIndex]
        if (cp) this.handleRestore(cp)
      } else if (e.key === 'Escape') {
        e.preventDefault()
        this.$emit('close')
      }
    },
    selectIndex(i) {
      this.selectedIndex = i
    },
    /**
     * 高亮条目滚到视区内。只滚 .panel-content 自身，不连带外层页面跳动。
     * 参考 SlashPalette 的 scrollActiveIntoView 写法。
     */
    scrollActiveIntoView() {
      const panel = this.$refs.panel
      if (!panel) return
      const list = panel.querySelector('.checkpoint-list')
      if (!list) return
      const items = list.querySelectorAll('.checkpoint-item')
      const el = items[this.selectedIndex]
      if (!el) return
      const itemTop = el.offsetTop
      const itemBottom = itemTop + el.offsetHeight
      const viewTop = list.scrollTop
      const viewBottom = viewTop + list.clientHeight
      if (itemTop < viewTop) {
        list.scrollTop = itemTop - 4
      } else if (itemBottom > viewBottom) {
        list.scrollTop = itemBottom - list.clientHeight + 4
      }
    }
  }
}
</script>

<style scoped>
.checkpoint-panel {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: 320px;
  background: var(--bg-primary);
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  /* 必须 > DataAnalysisTree panel(150)，否则文件树会盖在历史记录之上 */
  z-index: 200;
  box-shadow: -4px 0 12px rgba(0, 0, 0, 0.08);
}

.panel-header {
  padding: 20px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-secondary);
  text-align: center;
}

.empty-state svg {
  color: var(--text-secondary);
  opacity: 0.5;
  margin-bottom: 12px;
}

.empty-state p {
  font-size: 14px;
  margin: 0;
}

.checkpoint-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.checkpoint-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.checkpoint-item:hover {
  background: var(--bg-hover);
  border-color: var(--button-bg);
  transform: translateX(-2px);
}

/* 键盘高亮条目：紫色 outline + 浅紫底。优先 hover（鼠标），
   没 hover 时键盘选中也能明显区分。 */
.checkpoint-item.kb-active {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.5);
  outline: 2px solid var(--button-bg);
  outline-offset: -2px;
}

/* 容器 focus 时给个微弱的 dashed outline 让键盘焦点可见。
   配合 aside 上 tabindex=-1 + open 时 .focus()。 */
.checkpoint-panel:focus {
  outline: none;
}
.checkpoint-panel:focus-visible {
  outline: 2px dashed rgba(99, 102, 241, 0.45);
  outline-offset: -2px;
}

.checkpoint-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--bg-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--button-bg);
  flex-shrink: 0;
}

.checkpoint-info {
  flex: 1;
  min-width: 0;
}

.checkpoint-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.checkpoint-preview {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.restore-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
}

.restore-btn:hover {
  background: var(--button-bg);
  color: white;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>
