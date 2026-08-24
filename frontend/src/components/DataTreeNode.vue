<template>
  <div class="dtn-wrapper">
    <!-- 目录节点 -->
    <div
      v-if="node.type === 'directory'"
      class="dtn-row dtn-dir"
      :class="{ selected: isSelected, 'dtn-cut': isCutSource, 'dtn-copy': isCopySource, 'drop-target': isDropTarget, 'focus-target': isFocusTarget }"
      :style="rowStyle"
      :data-node-path="node.path || ''"
      :draggable="!renaming"
      @click="onRowClick"
      @contextmenu.prevent.stop="onContextMenu"
      @dragstart.stop="onRowDragStart"
      @dragend.stop="onRowDragEnd"
    >
      <span
        v-for="i in depth"
        :key="'indent-' + i"
        class="dtn-indent"
      ></span>

      <span class="dtn-caret" :class="{ open: isExpanded }" @click.stop="toggle">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 6 15 12 9 18"/>
        </svg>
      </span>

      <span class="dtn-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path v-if="isExpanded" d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>
          <path v-else d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"
                :style="{ fill: 'rgba(59, 130, 246, 0.08)' }"/>
        </svg>
      </span>

      <!-- inline 重命名态 -->
      <input
        v-if="renaming"
        ref="renameInput"
        v-model="renameText"
        class="dtn-rename-input"
        @blur="commitRename"
        @keydown.enter.prevent="commitRename"
        @keydown.esc.prevent="cancelRename"
        @click.stop
        @contextmenu.stop
      />
      <span v-else class="dtn-name" v-html="renderHighlighted(node.name)"></span>

      <span v-if="node.children && node.children.length > 0" class="dtn-count">
        {{ node.children.length }}
      </span>

      <button
        class="dtn-del"
        :class="{ confirming: confirmingDelete }"
        :title="confirmingDelete ? '再次点击确认删除整个文件夹' : '删除文件夹'"
        @click.stop="onDeleteClick"
      >×</button>
    </div>

    <!-- 文件节点 -->
    <div
      v-else
      class="dtn-row dtn-file"
      :class="{ selected: isSelected, 'dtn-cut': isCutSource, 'dtn-copy': isCopySource, 'drop-target': isDropTarget }"
      :style="rowStyle"
      :data-node-path="node.path || ''"
      :draggable="!renaming"
      @click="onClick"
      @contextmenu.prevent.stop="onContextMenu"
      @dragstart.stop="onRowDragStart"
      @dragend.stop="onRowDragEnd"
      :title="node.path"
    >
      <span
        v-for="i in depth"
        :key="'indent-' + i"
        class="dtn-indent"
      ></span>
      <span class="dtn-caret dtn-caret--placeholder"></span>

      <span class="dtn-icon dtn-icon--file" :class="'dtn-icon-' + iconKind">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path v-if="iconKind === 'image'" d="M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5z"/>
          <circle v-if="iconKind === 'image'" cx="9" cy="9" r="1.5" fill="currentColor"/>
          <path v-if="iconKind === 'image'" d="M21 15l-5-5L5 21"/>
          <path v-else-if="iconKind === 'data'"
                d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <path v-else-if="iconKind === 'data'" d="M9 13h6M9 17h6M9 9h2"/>
          <path v-else-if="iconKind === 'code'"
                d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>
          <path v-else-if="iconKind === 'markdown'"
                d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <path v-else-if="iconKind === 'markdown'" d="M8 13v4M12 13v4M16 13l-2 4M8 13l4 4M8 17l4-4"/>
          <path v-else d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline v-if="iconKind !== 'image' && iconKind !== 'code' && iconKind !== 'markdown'"
                    points="14 2 14 8 20 8"/>
          <line v-if="iconKind === 'code'" x1="2" y1="12" x2="6" y2="12"/>
        </svg>
      </span>

      <input
        v-if="renaming"
        ref="renameInput"
        v-model="renameText"
        class="dtn-rename-input"
        @blur="commitRename"
        @keydown.enter.prevent="commitRename"
        @keydown.esc.prevent="cancelRename"
        @click.stop
        @contextmenu.stop
      />
      <span v-else class="dtn-name" v-html="renderHighlighted(node.name)"></span>

      <span v-if="node.size != null" class="dtn-size">{{ formatSize(node.size) }}</span>

      <button
        class="dtn-del"
        :class="{ confirming: confirmingDelete }"
        :title="confirmingDelete ? '再次点击确认删除' : '删除'"
        @click.stop="onDeleteClick"
      >×</button>
    </div>

    <!-- 递归子节点（带树线） -->
    <div v-if="node.type === 'directory' && isExpanded && sortedChildren.length > 0" class="dtn-children">
      <DataTreeNode
        v-for="child in sortedChildren"
        :key="child.type + ':' + (child.path || child.name)"
        :node="child"
        :depth="depth + 1"
        :search="search"
        :selected-paths="selectedPaths"
        :last-clicked-path="lastClickedPath"
        :rename-target-path="renameTargetPath"
        :cut-path="cutPath"
        :copy-path="copyPath"
        :expanded-paths="expandedPaths"
        :drop-target-path="dropTargetPath"
        :focus-dir="focusDir"
        :focus-dir-prop="focusDirProp"
        @node-select="$emit('node-select', $event)"
        @node-toggle-expand="$emit('node-toggle-expand', $event)"
        @file-click="$emit('file-click', $event)"
        @file-delete="(n) => $emit('file-delete', n)"
        @node-context="$emit('node-context', $event)"
        @node-rename="$emit('node-rename', $event)"
        @node-rename-done="$emit('node-rename-done', $event)"
      />
    </div>
  </div>
</template>

<script>
/**
 * 数据树节点 —— IDEA 风重制 + 文件编辑交互：
 * - 全 SVG 图标 + 缩进引导线 + 搜索匹配段 mark 高亮
 * - 单击选中（向上 emit 给 Sidebar 维护 selectedNode）
 * - 右键弹出菜单（位置信息 emit 给 Sidebar，由 Sidebar 渲染全局 context menu）
 * - 重命名态：renameTargetPath 命中本节点 → 本节点进入 inline 重命名输入
 * - 行内 × 红叉二次确认沿用偏好 21/22 模式
 *
 * 节点结构（父级 buildFileTree 生成）：
 * - 目录：{ type: 'directory', name, path, children: [...] }
 * - 文件：{ type: 'file', name, path, size, modified_at }
 */
export default {
  name: 'DataTreeNode',
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 },
    search: { type: String, default: '' },
    // 多选集合（来自 Sidebar.selectedPaths）—— 数组形式以触发响应式
    selectedPaths: { type: Array, default: () => [] },
    // 最后点击的节点 path（Shift+click 范围选的锚点）
    lastClickedPath: { type: String, default: '' },
    // 当前正在重命名的 path（命中本节点 → 进入 inline rename）
    renameTargetPath: { type: String, default: '' },
    // 剪贴板里的「cut 源」完整 path（绝对 path 与本节点 path 一致 → 半透灰显）
    cutPath: { type: String, default: '' },
    // 剪贴板里的「copy 源」完整 path（命中本节点 → 加底色 + 角标提示）
    copyPath: { type: String, default: '' },
    // 共享展开状态（plain object { path: true }，由父级 Sidebar 维护，用于 Shift+click 范围选）
    expandedPaths: { type: Object, default: () => ({}) },
    // 当前 hover 的内部拖拽目标绝对路径（'' = 无）—— 由 Sidebar.dropTargetPath 决定
    // 每个 DataTreeNode 自己判断 `node.path === dropTargetPath` 来决定高亮
    dropTargetPath: { type: String, default: '' },
    // 当前焦点目录的相对路径（'' = 无焦点，即根）。Cmd+V 粘贴的目标目录。
    // 视觉上：左侧一条纤细的强调色竖线（inset box-shadow），与 copy/cut 视觉区分清晰但保持简约。
    focusDir: { type: String, default: '' },
    // 当前焦点目录的**绝对路径**（与 node.path 同格式），用于直接 === 比较点亮视觉
    focusDirProp: { type: String, default: '' }
  },
  emits: [
    'file-click',          // 兼容旧逻辑：选中 + 触发预览（按 modifier 转发）
    'node-select',         // 用户主动点击节点 → { node, event: MouseEvent, modifier: { meta, shift, alt, ctrl } }
    'file-delete',
    'node-context',        // 右键菜单触发 → { node, event: MouseEvent }
    'node-rename',         // 提交重命名 → { node, newName }
    'node-rename-done',    // 重命名完成（成功或取消）→ { node }
    'node-toggle-expand'   // 展开状态切换 → { node, expanded }
  ],
  data() {
    return {
      confirmingDelete: false,
      renaming: false,
      renameText: ''
    }
  },
  computed: {
    rowStyle() {
      return { paddingLeft: (this.depth * 18) + 'px' }
    },
    isSelected() {
      // 虚拟根节点（path 为空）不参与选中
      return this.node.path && this.selectedPaths.includes(this.node.path)
    },
    isExpanded() {
      // 单一权威：shared expandedPaths（plain object { path: true }）
      // 没有 depth 兜底 —— 否则顶层 dir 被折叠后会立即被 depth < 1 重新展开，
      // 用户感受是「点了没反应」。_buildFileTree 已经把顶层 dir 默认展开写进 state。
      const ep = this.expandedPaths
      if (!ep || typeof ep !== 'object') return this.depth < 1
      return this.node.path ? !!ep[this.node.path] : false
    },
    isCutSource() {
      // 剪贴板 mode=cut 时的源节点 → 半透灰显示，明确告诉用户「这行即将被移走」
      return this.node.path && this.cutPath && this.node.path === this.cutPath
    },
    isDropTarget() {
      // 内部拖拽时此节点是 drop 目标（高亮目录行）—— 路径与 Sidebar 传下来的 dropTargetPath 一致
      return !!(this.node.path && this.dropTargetPath && this.node.path === this.dropTargetPath)
    },
    isCopySource() {
      // 剪贴板 mode=copy 时的源节点 → 浅蓝底 + 「复制」语义角标（不破坏原选中色）
      return this.node.path && this.copyPath && this.node.path === this.copyPath
    },
    isFocusTarget() {
      // 当前目录是 Cmd+V 的目标目录 → 左侧纤细强调色竖线
      // 直接用绝对路径比较（focusDirProp 是 Sidebar 拼好的绝对路径，与 node.path 同格式）
      return !!(this.node.path && this.focusDirProp && this.node.path === this.focusDirProp)
    },
    sortedChildren() {
      if (!this.node.children) return []
      return [...this.node.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    },
    iconKind() {
      const name = (this.node.name || '').toLowerCase()
      if (/\.(png|jpe?g|gif|webp|svg)$/.test(name)) return 'image'
      if (/\.(csv|tsv|xlsx?)$/.test(name)) return 'data'
      if (/\.(json)$/.test(name)) return 'data'
      if (/\.(py|js|ts|jsx|tsx|vue|rs|go|java|c|cpp|h|hpp|rb|sh|bash)$/.test(name)) return 'code'
      if (/\.(md|markdown)$/.test(name)) return 'markdown'
      if (/\.mmd$/.test(name)) return 'markdown'
      return 'text'
    }
  },
  watch: {
    renameTargetPath(newVal) {
      if (newVal && newVal === this.node.path) {
        this.startRename()
      } else if (this.renaming && newVal !== this.node.path) {
        // 别的节点进入重命名，本节点退出
        this.cancelRename()
      }
    }
  },
  methods: {
    toggle() {
      const next = !this.isExpanded
      this.$emit('node-toggle-expand', { node: this.node, expanded: next })
    },
    /**
     * 点击 row —— 区分目录与文件：
     * - 目录：plain click 同时切换展开 + 选中；meta/cmd click 只切换选中不展开
     * - 文件：plain click = 选中 + 预览；meta/cmd click = 切换选中不预览
     */
    onRowClick(e) {
      const modifier = this._modifierOf(e)
      // 目录：plain click / shift 点击都展开；meta/cmd 点击不展开（toggle 只切选中）
      if (!modifier.meta) {
        this.toggle()
      }
      this._emitSelect(e, /* previewFile */ false)
    },
    onClick(e) {
      // 文件节点：始终触发预览（modifier 区分预览时机）
      this._emitSelect(e, /* previewFile */ true)
    },
    onChildClick(node, event) {
      // 递归子节点转发
      this.$emit('node-select', { node, event, modifier: this._modifierOf(event) })
    },
    _emitSelect(e, previewFile) {
      const modifier = this._modifierOf(e)
      this.$emit('node-select', { node: this.node, event: e, modifier })
      // 预览文件：plain click 时；meta/shift click 不预览避免误开
      if (previewFile && !modifier.meta && !modifier.shift) {
        this.$emit('file-click', this.node)
      }
    },
    _modifierOf(e) {
      return {
        meta: !!(e && (e.metaKey || e.ctrlKey)),
        shift: !!(e && e.shiftKey),
        alt: !!(e && e.altKey)
      }
    },
    onContextMenu(e) {
      this.$emit('node-context', { node: this.node, event: e })
    },
    /**
     * 拖拽开始（HTML5 drag API）：
     * - 多选整组拖拽：如果本节点在 selectedPaths 内且 selectedPaths.length > 1 → 拖整组
     * - 单选：只拖本节点
     * - setData('application/x-lingxi-paths', JSON) 给 Sidebar drop handler 解析
     * - effectAllowed = 'copyMove' 让浏览器根据 Alt/Option 切换 copy/move 光标
     */
    onRowDragStart(e) {
      if (!this.node.path || this.renaming) {
        if (e && e.preventDefault) e.preventDefault()
        return
      }
      const inSelection = this.selectedPaths.includes(this.node.path)
      const draggingPaths = (inSelection && this.selectedPaths.length > 1)
        ? [...this.selectedPaths]
        : [this.node.path]
      try {
        e.dataTransfer.effectAllowed = 'copyMove'
        e.dataTransfer.setData('application/x-lingxi-paths', JSON.stringify(draggingPaths))
      } catch (_) {}
      // 多选拖拽时给浏览器一个自定义拖拽图像（提示整组）
      if (draggingPaths.length > 1) {
        try {
          const ghost = document.createElement('div')
          ghost.textContent = `${draggingPaths.length} 项`
          ghost.style.cssText = 'position:absolute;top:-9999px;left:-9999px;background:#3b82f6;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:600;'
          document.body.appendChild(ghost)
          e.dataTransfer.setDragImage(ghost, 0, 0)
          // 拖完后清理
          setTimeout(() => { try { document.body.removeChild(ghost) } catch (_) {} }, 0)
        } catch (_) {}
      }
    },
    onRowDragEnd() {
      // dragend 不需做事 —— Sidebar 的 _systemDragDepth / dropTargetPath 由 onFilesTreeDragLeave 清
    },
    onDeleteClick() {
      if (this.confirmingDelete) {
        this.confirmingDelete = false
        this.$emit('file-delete', this.node)
      } else {
        this.confirmingDelete = true
      }
    },
    cancelDeleteConfirm() {
      this.confirmingDelete = false
    },
    onKeydown(e) {
      if (e.key === 'Escape') {
        if (this.confirmingDelete) this.confirmingDelete = false
        if (this.renaming) this.cancelRename()
      }
    },
    onOutsideClick(e) {
      if (this.$el && this.$el.contains(e.target)) return
      if (this.confirmingDelete) this.confirmingDelete = false
    },
    startRename() {
      this.renaming = true
      this.renameText = this.node.name
      this.$nextTick(() => {
        const input = this.$refs.renameInput
        if (input) {
          input.focus()
          input.select()
        }
      })
    },
    commitRename() {
      if (!this.renaming) return
      const newName = (this.renameText || '').trim()
      const oldName = this.node.name
      this.renaming = false
      if (!newName || newName === oldName) {
        this.$emit('node-rename-done', { node: this.node, success: false })
        return
      }
      this.$emit('node-rename', { node: this.node, newName })
    },
    cancelRename() {
      this.renaming = false
      this.renameText = ''
      this.$emit('node-rename-done', { node: this.node, success: false })
    },
    renderHighlighted(name) {
      if (!this.search || !name) return this._escape(name || '')
      const searchLower = this.search.toLowerCase()
      const nameLower = name.toLowerCase()
      const idx = nameLower.indexOf(searchLower)
      if (idx < 0) return this._escape(name)
      const before = name.slice(0, idx)
      const match = name.slice(idx, idx + this.search.length)
      const after = name.slice(idx + this.search.length)
      return this._escape(before) +
        '<mark class="dtn-hl">' + this._escape(match) + '</mark>' +
        this._escape(after)
    },
    _escape(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
    },
    formatSize(bytes) {
      if (bytes == null) return ''
      if (bytes < 1024) return bytes + 'B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'K'
      return (bytes / 1024 / 1024).toFixed(1) + 'M'
    }
  },
  mounted() {
    document.addEventListener('click', this.onOutsideClick)
    document.addEventListener('keydown', this.onKeydown)
  },
  beforeDestroy() {
    document.removeEventListener('click', this.onOutsideClick)
    document.removeEventListener('keydown', this.onKeydown)
  }
}
</script>

<style scoped>
.dtn-wrapper {
  user-select: none;
  font-size: 12.5px;
}
.dtn-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px 3px 0;
  cursor: pointer;
  line-height: 1.4;
  white-space: nowrap;
  min-height: 24px;
  position: relative;
  border-radius: 3px;
  margin: 0 4px 1px 4px;
}
.dtn-row:hover {
  background: var(--bg-hover, #f3f4f6);
}
/* 内部拖拽 drop target 高亮 —— 仅目录行生效，文件行会落到父目录所以不高亮 */
.dtn-row.dtn-dir.drop-target {
  background: rgba(59, 130, 246, 0.18);
  outline: 2px dashed rgba(59, 130, 246, 0.7);
  outline-offset: -2px;
}
.dtn-row.selected {
  background: rgba(59, 130, 246, 0.12);
}
.dtn-row.selected:hover {
  background: rgba(59, 130, 246, 0.16);
}

/* —— 剪贴板视觉区分 —— */
/* cut 源：剪下后即将被移走 → 半透灰 + 斜体划线感（避免误以为是 ghost） */
.dtn-row.dtn-cut {
  opacity: 0.45;
  font-style: italic;
}
.dtn-row.dtn-cut .dtn-name {
  text-decoration: line-through;
  text-decoration-color: rgba(107, 114, 128, 0.5);
  text-decoration-thickness: 1px;
}
.dtn-row.dtn-cut:hover {
  opacity: 0.7;
}
/* copy 源：复制后仍保留原位 → 琥珀色（暖色系，与蓝色 focus 视觉分离）+ 角标 ⎘
 * 与 focus 蓝色实心左边框 + selected 蓝色背景形成三态清晰区分：
 *   - selected（多选/单选）: 蓝色浅底，无边框
 *   - focus（Cmd+V 目标）:   蓝色浅底 + 蓝色实心左边框
 *   - copy（剪贴板复制源）:  琥珀色浅底 + ⎘ 角标（无左边框）
 *   - cut（剪贴板剪切源）:   灰色 + 斜体 + 划线
 * 选蓝色 vs 琥珀色：copy 是「源（会保留）」，focus 是「目的（会粘到这里）」，
 * 冷暖对比 + 角标 + 边框三层信号，扫一眼就能区分。
 */
.dtn-row.dtn-copy {
  position: relative;
  background: rgba(245, 158, 11, 0.10);          /* amber 500，10% 不透明 */
}
.dtn-row.dtn-copy:hover {
  background: rgba(245, 158, 11, 0.15);
}
.dtn-row.dtn-copy .dtn-name::after {
  content: '⎘';
  margin-left: 5px;
  font-size: 11px;
  color: #d97706;                                  /* amber 600 —— 比底色深一档 */
  font-weight: 700;
  vertical-align: middle;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.dtn-indent {
  display: inline-block;
  width: 18px;
  height: 100%;
  position: relative;
  flex-shrink: 0;
}
.dtn-indent::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-color, #e5e7eb);
  opacity: 0.7;
}

.dtn-caret {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 10px;
  height: 14px;
  flex-shrink: 0;
  color: var(--text-secondary, #9ca3af);
  transition: transform 0.15s;
  cursor: pointer;
}
.dtn-caret.open {
  transform: rotate(90deg);
}
.dtn-caret--placeholder {
  visibility: hidden;
}

.dtn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--primary-color, #3b82f6);
}
.dtn-icon--file { color: var(--text-secondary, #6b7280); }
.dtn-icon-image { color: #8b5cf6; }
.dtn-icon-data { color: #10b981; }
.dtn-icon-code { color: #f59e0b; }
.dtn-icon-markdown { color: #6366f1; }
.dtn-icon-text { color: #6b7280; }

.dtn-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary, #111);
  min-width: 0;
}
.dtn-name :deep(.dtn-hl) {
  background: rgba(250, 204, 21, 0.4);
  color: var(--primary-color, #3b82f6);
  font-weight: 600;
  border-radius: 2px;
  padding: 0 1px;
}

/* —— inline 重命名输入 —— */
.dtn-rename-input {
  flex: 1;
  height: 22px;
  padding: 0 4px;
  border: 1px solid var(--primary-color, #3b82f6);
  border-radius: 3px;
  background: var(--bg-primary, #fff);
  color: var(--text-primary, #111);
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
  min-width: 0;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.18);
}

.dtn-count,
.dtn-size {
  font-size: 10.5px;
  color: var(--text-secondary, #9ca3af);
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  padding: 0 2px;
}

.dtn-del {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary, #9ca3af);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
  margin-left: 2px;
}
.dtn-row:hover .dtn-del {
  opacity: 1;
}
.dtn-del:hover {
  background: var(--bg-hover, #e5e7eb);
  color: var(--text-primary, #111);
}
.dtn-del.confirming {
  opacity: 1 !important;
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
  font-weight: 600;
}
.dtn-del.confirming:hover {
  background: rgba(239, 68, 68, 0.22);
}

.dtn-children {
  position: relative;
}

/* —— 当前焦点目录（Cmd+V 目标） ——
 * 视觉：左侧 2px 强调色竖线（inset box-shadow）+ 浅蓝背景叠加。
 * 与「选中态 selected」「复制/剪切源」三者互斥视觉：
 *   - selected：纯浅蓝背景（0.12 opacity）
 *   - copy：浅蓝背景 + 浅蓝虚线左边框（0.5 opacity，2px）
 *   - cut：半透灰 + 斜体
 *   - focus：浅蓝背景 + 实心左边框（0.85 opacity，2px）—— 比 copy 略实，强调「这里是目的地」
 * 多态共存时按 CSS 顺序：focus 写在最后，hover / cut 状态会覆盖背景但保留左侧竖线语义。
 */
.dtn-row.dtn-dir.focus-target {
  background: rgba(59, 130, 246, 0.1);
  box-shadow: inset 2px 0 0 rgba(59, 130, 246, 0.85);
}
.dtn-row.dtn-dir.focus-target:hover {
  background: rgba(59, 130, 246, 0.16);
}
.dtn-row.dtn-dir.focus-target.selected {
  background: rgba(59, 130, 246, 0.18);
}
.dtn-row.dtn-dir.focus-target.selected:hover {
  background: rgba(59, 130, 246, 0.22);
}
/* 焦点 + 复制源共存：focus 蓝色实心左边框 + copy 琥珀色 ⎘ 角标同时显示 —— 两个信号独立不打架 */
.dtn-row.dtn-dir.focus-target.dtn-copy {
  background: rgba(245, 158, 11, 0.12);          /* 偏 amber，保留 copy 暖色基调 */
  box-shadow: inset 2px 0 0 rgba(59, 130, 246, 0.85);  /* focus 蓝色左竖线保留 */
}
.dtn-row.dtn-dir.focus-target.dtn-copy:hover {
  background: rgba(245, 158, 11, 0.18);
}
</style>