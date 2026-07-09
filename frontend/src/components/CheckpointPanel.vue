<template>
  <transition name="slide">
    <aside v-if="visible" class="checkpoint-panel">
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
            <button class="restore-btn" title="恢复到此版本" @click.stop="handleRestore(checkpoint)">
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
