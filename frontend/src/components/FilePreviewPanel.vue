<template>
  <transition name="slide">
    <aside v-show="visible && tabs.length" class="file-preview-panel" :style="{ width: panelWidth + 'px' }">
      <div class="resize-handle" @mousedown="startResize"></div>

      <div class="preview-tabs" ref="tabStrip" tabindex="-1" @keydown="handleTabKeydown">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          class="preview-tab"
          :class="{ active: tab.id === activeTabId }"
          :title="tab.name"
          @click="selectTab(tab.id)"
        >
          <span v-if="tab.loading" class="tab-loading"></span>
          <span class="tab-name">{{ tab.name }}</span>
          <span
            class="tab-close"
            role="button"
            :aria-label="`关闭 ${tab.name}`"
            @click.stop="$emit('close-tab', tab.id)"
          >×</span>
        </button>
      </div>

      <div class="pane-stack">
        <transition name="tree-fade">
          <div v-if="showFileTree" ref="innerFileTree" class="inner-file-tree" @click.stop>
            <div class="inner-tree-header">
              <span class="inner-tree-title">文件列表</span>
              <button class="tree-close" @click="showFileTree = false" title="关闭">×</button>
            </div>
            <div class="inner-tree-body">
              <div v-if="treeLoading" class="inner-tree-empty">加载中…</div>
              <div v-else-if="!treeRootNode || !treeRootNode.children || treeRootNode.children.length === 0" class="inner-tree-empty">暂无文件</div>
              <div v-else class="inner-tree-list">
                <div v-for="child in treeRootChildren" :key="child.name + '_' + child.type">
                  <DataTreeNode :node="child" :depth="0" @file-click="onInnerFileClick" />
                </div>
              </div>
            </div>
          </div>
        </transition>

        <FilePreviewTabPane
          v-for="tab in tabs"
          v-show="tab.id === activeTabId"
          :key="tab.id"
          :tab="tab"
          :session-id="sessionId"
          :show-file-tree="showFileTree"
          @toggle-file-tree="toggleFileTree"
          @close-panel="$emit('close')"
          @reload="$emit('reload', $event)"
        />
      </div>
    </aside>
  </transition>
</template>

<script>
import DataTreeNode from './DataTreeNode.vue'
import FilePreviewTabPane from './FilePreviewTabPane.vue'

export default {
  name: 'FilePreviewPanel',
  components: { DataTreeNode, FilePreviewTabPane },
  props: {
    visible: { type: Boolean, default: false },
    tabs: { type: Array, default: () => [] },
    activeTabId: { type: String, default: null },
    sessionId: { type: String, default: '' }
  },
  emits: ['close', 'activate-tab', 'close-tab', 'reload', 'file-select'],
  data() {
    return {
      panelWidth: 480,
      isResizing: false,
      startX: 0,
      startWidth: 0,
      showFileTree: false,
      treeFiles: [],
      treeRootPath: '',
      treeRootNode: null,
      treeLoading: false
    }
  },
  computed: {
    treeRootChildren() {
      if (!this.treeRootNode || !this.treeRootNode.children) return []
      return [...this.treeRootNode.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    }
  },
  watch: {
    activeTabId() {
      this.scrollActiveTabIntoView()
    },
    sessionId(newVal, oldVal) {
      if (newVal !== oldVal) {
        this.showFileTree = false
        this.treeFiles = []
        this.treeRootNode = null
      }
    },
    visible(value) {
      if (value) {
        this.scrollActiveTabIntoView()
        // 把焦点抢到 tab 条上，← / → 立刻能切 tab
        this.$nextTick(() => {
          const strip = this.$refs.tabStrip
          if (strip && strip.focus) strip.focus()
        })
      } else {
        this.showFileTree = false
      }
    }
  },
  methods: {
    scrollActiveTabIntoView() {
      this.$nextTick(() => {
        const activeTab = this.$refs.tabStrip?.querySelector('.preview-tab.active')
        activeTab?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
      })
    },
    /**
     * 顶部 tab 键盘导航：
     *   - ← / →: 切 tab（水平 tab 条，左右键符合视觉方向）
     *   - Enter / Space: 显式 apply 当前高亮 tab（与点击等价）
     *   - Home / End: 跳到第一个 / 最后一个 tab
     *   - Ctrl+W: 关闭当前 tab（与 IDE 一致；不挡用户的 Ctrl+W 系统快捷键，
     *             但在 tabStrip 内被认为是关闭意图）
     * 监听挂在 .preview-tabs 上（tabindex=-1），open 时 .focus() 把键盘焦点拉过来。
     */
    handleTabKeydown(e) {
      const list = this.tabs
      if (!list || list.length === 0) return
      let idx = list.findIndex(t => t.id === this.activeTabId)
      if (idx < 0) idx = 0
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        idx = Math.min(idx + 1, list.length - 1)
        this.selectTab(list[idx].id)
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        idx = Math.max(idx - 1, 0)
        this.selectTab(list[idx].id)
      } else if (e.key === 'Home') {
        e.preventDefault()
        this.selectTab(list[0].id)
      } else if (e.key === 'End') {
        e.preventDefault()
        this.selectTab(list[list.length - 1].id)
      } else if ((e.key === 'w' || e.key === 'W') && (e.ctrlKey || e.metaKey)) {
        // Ctrl/Cmd+W: 关闭当前 tab
        e.preventDefault()
        if (list[idx]) this.$emit('close-tab', list[idx].id)
      }
    },
    selectTab(id) {
      this.$emit('activate-tab', id)
      this.$nextTick(this.scrollActiveTabIntoView)
    },
    async toggleFileTree() {
      this.showFileTree = !this.showFileTree
      if (this.showFileTree && (!this.treeRootNode || this.treeFiles.length === 0)) {
        await this.loadFileTree()
      }
    },
    async loadFileTree() {
      if (!this.sessionId) return
      this.treeLoading = true
      try {
        const resp = await fetch(`/chat/${this.sessionId}/data-analysis/tree`)
        if (!resp.ok) {
          this.treeFiles = []
          this.treeRootNode = null
          return
        }
        const data = await resp.json()
        this.treeRootPath = data.root_path || ''
        this.treeFiles = data.files || []
        this.buildTreeNode()
      } catch (e) {
        console.error('[FilePreviewPanel] loadFileTree failed:', e)
        this.treeFiles = []
        this.treeRootNode = null
      } finally {
        this.treeLoading = false
      }
    },
    buildTreeNode() {
      const root = { name: 'data_analysis', type: 'directory', children: [] }
      const basePrefix = this.treeRootPath.endsWith('/') ? this.treeRootPath : this.treeRootPath + '/'
      for (const file of this.treeFiles) {
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
      this.treeRootNode = root
    },
    onInnerFileClick(node) {
      this.$emit('file-select', node)
    },
    onInnerTreeOutsideClick(e) {
      if (!this.showFileTree) return
      const tree = this.$refs.innerFileTree
      if (tree && tree.contains(e.target)) return
      this.showFileTree = false
    },
    startResize(e) {
      e.preventDefault()
      e.stopPropagation()
      this.isResizing = true
      this.startX = e.clientX
      this.startWidth = this.panelWidth
      window.addEventListener('mousemove', this.handleResize, { passive: true })
      window.addEventListener('mouseup', this.stopResize, { passive: false })
      document.body.style.cursor = 'ew-resize'
      document.body.style.userSelect = 'none'
      document.body.style.pointerEvents = 'none'
    },
    handleResize(e) {
      if (!this.isResizing) return
      const deltaX = this.startX - e.clientX
      const maxWidth = Math.min(800, window.innerWidth * 0.6)
      this.panelWidth = Math.max(320, Math.min(this.startWidth + deltaX, maxWidth))
    },
    stopResize(e) {
      if (!this.isResizing) return
      e?.preventDefault()
      this.isResizing = false
      window.removeEventListener('mousemove', this.handleResize)
      window.removeEventListener('mouseup', this.stopResize)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.body.style.pointerEvents = ''
    }
  },
  mounted() {
    document.addEventListener('click', this.onInnerTreeOutsideClick)
  },
  beforeUnmount() {
    document.removeEventListener('click', this.onInnerTreeOutsideClick)
    window.removeEventListener('mousemove', this.handleResize)
    window.removeEventListener('mouseup', this.stopResize)
    if (this.isResizing) {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.body.style.pointerEvents = ''
    }
  }
}
</script>

<style scoped>
.file-preview-panel {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  height: 100vh;
  background: var(--bg-primary);
  border-left: 1px solid var(--border-color);
  z-index: 100;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.1);
  min-width: 320px;
  max-width: 800px;
  will-change: width;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.resize-handle { position: absolute; left: -15px; top: 0; bottom: 0; width: 20px; cursor: ew-resize; z-index: 30; user-select: none; }
.resize-handle::before { content: ''; position: absolute; left: 15px; top: 0; bottom: 0; width: 2px; background: transparent; transition: background 0.15s; pointer-events: none; }
.resize-handle:hover::before { background: var(--button-bg); opacity: 0.4; }
.preview-tabs {
  display: flex;
  align-items: flex-end;
  min-height: 42px;
  padding: 6px 8px 0;
  gap: 3px;
  overflow-x: auto;
  overflow-y: hidden;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
  scrollbar-width: thin;
  /* tab 条自动 focus 接收 ←/→/Home/End 等键盘事件，
     不该显示浏览器默认黑 focus ring（active tab 已有高亮）。 */
  outline: none;
}
.preview-tabs::-webkit-scrollbar { height: 4px; }
.preview-tabs::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 2px; }
.preview-tab {
  min-width: 110px;
  max-width: 190px;
  height: 34px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 8px 0 10px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 7px 7px 0 0;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  flex: 0 0 auto;
}
.preview-tab:hover { background: var(--bg-hover); color: var(--text-primary); }
.preview-tab.active { background: var(--bg-primary); color: var(--text-primary); border-color: var(--border-color); }
.tab-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12.5px; flex: 1; text-align: left; }
.tab-close { width: 18px; height: 18px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 15px; line-height: 1; }
.tab-close:hover { color: #ef4444; background: rgba(239, 68, 68, 0.12); }
.tab-loading { width: 9px; height: 9px; border: 1.5px solid var(--border-color); border-top-color: var(--button-bg); border-radius: 50%; animation: tab-spin 0.8s linear infinite; flex-shrink: 0; }
@keyframes tab-spin { to { transform: rotate(360deg); } }
.pane-stack { position: relative; flex: 1; min-height: 0; overflow: hidden; }
.pane-stack > :deep(.preview-tab-pane) { height: 100%; }
.inner-file-tree {
  position: absolute;
  top: 54px;
  left: 12px;
  width: 320px;
  max-width: calc(100% - 24px);
  max-height: 60vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  z-index: 20;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.inner-tree-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-bottom: 1px solid var(--border-color); background: var(--bg-secondary); flex-shrink: 0; }
.inner-tree-title { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.tree-close { width: 22px; height: 22px; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; border-radius: 4px; font-size: 15px; }
.tree-close:hover { background: var(--bg-hover); color: var(--text-primary); }
.inner-tree-body { flex: 1; overflow-y: auto; padding: 4px 0; }
.inner-tree-empty { padding: 20px; text-align: center; color: var(--text-secondary); font-size: 12px; }
.inner-tree-list { font-size: 12.5px; }
.tree-fade-enter-active, .tree-fade-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.tree-fade-enter-from, .tree-fade-leave-to { opacity: 0; transform: translateY(-4px); }
.slide-enter-active, .slide-leave-active { transition: transform 0.25s ease; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }
</style>
