<template>
  <div v-if="exists" class="da-tree-wrapper">
    <button
      class="da-trigger"
      :class="{ active: showTree }"
      @click.stop="togglePanel"
      :title="`数据分析产物 (${fileCount} 个文件)`"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 3h18v4H3z"/>
        <path d="M3 11h18v4H3z"/>
        <path d="M3 19h18v2H3z"/>
      </svg>
      <span v-if="fileCount > 0" class="da-badge">{{ fileCount }}</span>
    </button>

    <transition name="da-fade">
      <div v-if="showTree" class="da-panel">
        <div class="da-panel-header">
          <span class="da-panel-title">📁 会话文件</span>
          <div class="da-panel-actions">
            <button class="da-icon-btn" @click="reload" title="刷新">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            </button>
            <button class="da-icon-btn" @click.stop="showTree = false" title="关闭">×</button>
          </div>
        </div>
        <div class="da-panel-body">
          <div v-if="loading" class="da-empty">加载中…</div>
          <div v-else-if="!rootNode || !rootNode.children || rootNode.children.length === 0" class="da-empty">
            暂无文件
          </div>
          <div v-else class="da-tree">
            <div
              v-for="child in sortedRootChildren"
              :key="child.name + '_' + child.type"
              class="da-node"
            >
              <DataTreeNode
                :node="child"
                :depth="0"
                @file-click="onFileClick"
              />
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script>
import DataTreeNode from './DataTreeNode.vue'

export default {
  name: 'DataAnalysisTree',
  components: { DataTreeNode },
  props: {
    sessionId: { type: String, default: '' }
  },
  emits: ['file-click'],
  data() {
    return {
      exists: false,
      rootPath: '',
      files: [],
      showTree: false,
      rootNode: null,
      loading: false
    }
  },
  computed: {
    fileCount() {
      return this.files.length
    },
    sortedRootChildren() {
      if (!this.rootNode || !this.rootNode.children) return []
      return [...this.rootNode.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    }
  },
  watch: {
    sessionId: {
      immediate: true,
      handler(newVal, oldVal) {
        // 切换会话时立刻清掉旧会话的显示状态（按钮、面板、文件列表），
        // 再异步去拿新会话的数据，避免短暂残留旧 UI
        if (newVal !== oldVal) {
          this.reset()
        }
        if (newVal) {
          this.check()
        }
      }
    }
  },
  methods: {
    togglePanel() {
      this.showTree = !this.showTree
    },
    onKeyDown(e) {
      if (e.key === 'Escape' && this.showTree) {
        this.showTree = false
      }
    },
    async check() {
      this.loading = true
      try {
        // 工作树：拉取当前 session_id 下全部文件（data_analysis 子目录 + 上传文件 + AI 中间产物等），
        // 比 /data-analysis/tree 范围广。旧接口保留供 FilePreviewPanel 内嵌文件列表用。
        const resp = await fetch(`/chat/${this.sessionId}/tree`)
        if (!resp.ok) {
          this.reset()
          return
        }
        const data = await resp.json()
        this.exists = !!data.exists
        this.rootPath = data.root_path || ''
        this.files = data.files || []
        if (this.exists) {
          this.buildTree()
        } else {
          this.rootNode = null
        }
      } catch (e) {
        console.error('[DataAnalysisTree] check failed:', e)
        this.reset()
      } finally {
        this.loading = false
      }
    },
    reset() {
      this.exists = false
      this.files = []
      this.rootNode = null
      this.showTree = false
      this.loading = false
    },
    buildTree() {
      // 根节点：用 sessionId 前 8 位做显示名（替代旧的 'data_analysis'，
      // 因为现在展示的是整个 session 下的文件，不再只是 data_analysis 子目录）
      const rootName = this.sessionId ? this.sessionId.slice(0, 8) : 'session'
      const root = { name: rootName, type: 'directory', children: [] }
      const basePrefix = this.rootPath.endsWith('/') ? this.rootPath : this.rootPath + '/'
      for (const file of this.files) {
        const rel = file.path.startsWith(basePrefix)
          ? file.path.slice(basePrefix.length)
          : file.path
        const parts = rel.split('/').filter(Boolean)
        if (parts.length === 0) continue
        let current = root
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i]
          const isFile = i === parts.length - 1
          if (isFile) {
            current.children.push({
              name: part,
              type: 'file',
              path: file.path,
              size: file.size,
              modified_at: file.modified_at
            })
          } else {
            let dir = current.children.find(c => c.name === part && c.type === 'directory')
            if (!dir) {
              dir = { name: part, type: 'directory', children: [] }
              current.children.push(dir)
            }
            current = dir
          }
        }
      }
      this.rootNode = root
    },
    reload() {
      this.check()
    },
    onFileClick(node) {
      // 点文件后不折叠树：保留树状态让用户继续浏览其他文件，
      // 树面板的关闭交给 click-outside 处理
      this.$emit('file-click', node)
    },
    onOutsideClick(e) {
      // 树没开就不处理
      if (!this.showTree) return
      // 点中树内部 → 不折叠（用户可能在点节点 toggle / 滚动等）
      if (this.$el && this.$el.contains(e.target)) return
      // 其他位置（包括文件预览栏 / overlay）→ 折叠
      this.showTree = false
    }
  },
  mounted() {
    document.addEventListener('keydown', this.onKeyDown)
    document.addEventListener('click', this.onOutsideClick)
  },
  beforeDestroy() {
    document.removeEventListener('keydown', this.onKeyDown)
    document.removeEventListener('click', this.onOutsideClick)
  }
}
</script>

<style scoped>
.da-tree-wrapper {
  position: relative;
  display: inline-block;
}

.da-trigger {
  position: relative;
  width: 40px;
  height: 40px;
  border: none;
  background: var(--bg-hover, #f3f4f6);
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-primary, #111);
  transition: all 0.2s;
}
.da-trigger:hover {
  background: var(--bg-hover, #e5e7eb);
  opacity: 0.85;
}
.da-trigger.active {
  background: var(--primary-color, #3b82f6);
  color: #fff;
}
.da-badge {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  font-size: 10px;
  background: var(--primary-color, #3b82f6);
  color: #fff;
  border-radius: 8px;
  line-height: 16px;
  text-align: center;
  font-weight: 500;
}
.da-trigger.active .da-badge {
  background: rgba(255, 255, 255, 0.35);
}

.da-panel {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 380px;
  max-height: 520px;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  /* 层级：FilePreviewPanel(100) < 本面板(150) < CheckpointPanel(200)
     - 文件预览打开时，文件树要"浮在上面"（高于 100）
     - 历史记录打开时，要让位（低于 200） */
  z-index: 150;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.da-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  background: var(--bg-secondary, #f9fafb);
}
.da-panel-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #111);
}
.da-panel-actions {
  display: flex;
  gap: 2px;
}
.da-icon-btn {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  color: var(--text-secondary, #6b7280);
  font-size: 16px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.da-icon-btn:hover {
  background: var(--bg-hover, #e5e7eb);
  color: var(--text-primary, #111);
}

.da-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 0;
}

.da-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary, #9ca3af);
  font-size: 13px;
}

.da-tree {
  font-size: 13px;
}

.da-fade-enter-active,
.da-fade-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.da-fade-enter-from,
.da-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
