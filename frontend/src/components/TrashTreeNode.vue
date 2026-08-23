<template>
  <div class="ttn-wrapper">
    <!-- 目录节点 -->
    <div
      v-if="node.type === 'directory'"
      class="ttn-row ttn-dir"
      :style="rowStyle"
      @click="toggle"
    >
      <span
        v-for="i in depth"
        :key="'indent-' + i"
        class="ttn-indent"
      ></span>

      <span class="ttn-caret" :class="{ open: expanded }">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 6 15 12 9 18"/>
        </svg>
      </span>

      <span class="ttn-icon ttn-icon--folder">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"
                :style="{ fill: 'rgba(239, 68, 68, 0.06)' }"/>
        </svg>
      </span>

      <span class="ttn-name" v-html="renderHighlighted(node.name)"></span>

      <span v-if="node.children && node.children.length > 0" class="ttn-count">
        {{ node.children.length }}
      </span>

      <!-- 根节点（虚拟 __trash_root__）无 fullPath，不挂 × 按钮 -->
      <button
        v-if="node.fullPath"
        class="ttn-del ttn-del-dir"
        :class="{ confirming: confirmingDirDelete }"
        :disabled="busy"
        :title="confirmingDirDelete ? '再次点击永久删除该目录' : '永久删除该目录'"
        @click.stop="onDirDeleteClick"
      >×</button>
    </div>

    <!-- 文件叶子节点 -->
    <div
      v-else
      class="ttn-row ttn-file"
      :style="rowStyle"
    >
      <span
        v-for="i in depth"
        :key="'indent-' + i"
        class="ttn-indent"
      ></span>
      <span class="ttn-caret ttn-caret--placeholder"></span>

      <span class="ttn-icon ttn-icon--file" :class="'ttn-icon-' + iconKind">
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
          <path v-else d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline v-if="iconKind !== 'image' && iconKind !== 'code'" points="14 2 14 8 20 8"/>
        </svg>
      </span>

      <span class="ttn-name" :title="node.fullPath" v-html="renderHighlighted(node.name)"></span>

      <span v-if="node.size != null" class="ttn-size">{{ formatSize(node.size) }}</span>
      <span v-if="node.timestamp" class="ttn-time" :title="node.fullTimestamp || node.timestamp">
        🕐 {{ formatTime(node.timestamp) }}
      </span>

      <button
        class="ttn-act ttn-restore"
        :disabled="busy"
        :title="busy ? '处理中…' : '恢复到原位置'"
        @click.stop="onRestoreClick"
      >↩</button>
      <button
        class="ttn-del"
        :class="{ confirming: confirmingDelete }"
        :disabled="busy"
        :title="confirmingDelete ? '再次点击永久删除' : '永久删除'"
        @click.stop="onDeleteClick"
      >×</button>
    </div>

    <!-- 递归子节点 -->
    <div v-if="node.type === 'directory' && expanded && sortedChildren.length > 0" class="ttn-children">
      <TrashTreeNode
        v-for="child in sortedChildren"
        :key="child.type + ':' + (child.fullPath || child.name)"
        :node="child"
        :depth="depth + 1"
        :busy="busy"
        :search="search"
        @trash-item-restore="$emit('trash-item-restore', $event)"
        @trash-item-delete="$emit('trash-item-delete', $event)"
        @trash-folder-delete="$emit('trash-folder-delete', $event)"
      />
    </div>
  </div>
</template>

<script>
/**
 * 回收站树节点 —— IDEA 风重制版（与 DataTreeNode.vue 同源）：
 * - 全 SVG 图标（chevron / 文件夹 / 文件类型）
 * - 缩进引导线 + 搜索匹配段高亮
 * - 行内 × 红叉二次确认沿用偏好 21/22 模式
 * - 整目录删除在目录行右侧也挂 ×（根节点不挂，因为它没 fullPath）
 * - parent 把 busy 通过 props 透传，busy=true 时整棵子树 × 按钮全部 disabled
 */
export default {
  name: 'TrashTreeNode',
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 },
    busy: { type: Boolean, default: false },
    search: { type: String, default: '' }
  },
  emits: ['trash-item-restore', 'trash-item-delete', 'trash-folder-delete'],
  data() {
    return {
      expanded: this.depth < 1,
      confirmingDelete: false,
      confirmingDirDelete: false
    }
  },
  computed: {
    rowStyle() {
      return { paddingLeft: (this.depth * 18) + 'px' }
    },
    sortedChildren() {
      if (!this.node.children) return []
      return [...this.node.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    },
    iconKind() {
      const n = (this.node.name || '').toLowerCase()
      if (/\.(png|jpe?g|gif|webp|svg)$/.test(n)) return 'image'
      if (/\.(csv|tsv|xlsx?)$/.test(n)) return 'data'
      if (/\.json$/.test(n)) return 'data'
      if (/\.(py|js|ts|jsx|tsx|vue|rs|go|java|c|cpp|h|hpp|rb|sh|bash)$/.test(n)) return 'code'
      if (/\.(md|markdown|mmd)$/.test(n)) return 'markdown'
      return 'text'
    }
  },
  methods: {
    toggle() {
      this.expanded = !this.expanded
    },
    onRestoreClick() {
      if (this.node.item) {
        this.$emit('trash-item-restore', this.node.item)
      }
    },
    onDeleteClick() {
      if (this.confirmingDelete) {
        this.confirmingDelete = false
        if (this.node.item) {
          this.$emit('trash-item-delete', this.node.item)
        }
      } else {
        this.confirmingDelete = true
      }
    },
    onDirDeleteClick() {
      if (this.confirmingDirDelete) {
        this.confirmingDirDelete = false
        this.$emit('trash-folder-delete', this.node)
      } else {
        this.confirmingDirDelete = true
      }
    },
    cancelConfirm() {
      this.confirmingDelete = false
      this.confirmingDirDelete = false
    },
    onKeydown(e) {
      if (e.key === 'Escape') {
        if (this.confirmingDelete || this.confirmingDirDelete) {
          this.confirmingDelete = false
          this.confirmingDirDelete = false
        }
      }
    },
    onOutsideClick(e) {
      if (this.$el && this.$el.contains(e.target)) return
      if (this.confirmingDelete || this.confirmingDirDelete) {
        this.confirmingDelete = false
        this.confirmingDirDelete = false
      }
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
        '<mark class="ttn-hl">' + this._escape(match) + '</mark>' +
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
    },
    formatTime(iso) {
      if (!iso) return ''
      try {
        const d = new Date(iso)
        if (isNaN(d.getTime())) return ''
        const pad = (n) => String(n).padStart(2, '0')
        return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
      } catch (e) {
        return ''
      }
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
.ttn-wrapper {
  user-select: none;
  font-size: 12.5px;
}
.ttn-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px 3px 0;
  line-height: 1.4;
  white-space: nowrap;
  min-height: 24px;
  position: relative;
  border-radius: 3px;
  margin: 0 4px 1px 4px;
  cursor: pointer;
}
.ttn-row:hover {
  background: var(--bg-hover, #f3f4f6);
}

/* —— 缩进引导线 —— */
.ttn-indent {
  display: inline-block;
  width: 18px;
  height: 100%;
  position: relative;
  flex-shrink: 0;
}
.ttn-indent::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-color, #e5e7eb);
  opacity: 0.7;
}

.ttn-caret {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 10px;
  height: 14px;
  flex-shrink: 0;
  color: var(--text-secondary, #9ca3af);
  transition: transform 0.15s;
}
.ttn-caret.open {
  transform: rotate(90deg);
}
.ttn-caret--placeholder {
  /* 文件节点无 chevron，留空占位 */
}

.ttn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}
.ttn-icon--folder {
  color: #ef4444;
}
.ttn-icon--file {
  color: var(--text-secondary, #6b7280);
}
.ttn-icon-image { color: #8b5cf6; }
.ttn-icon-data { color: #10b981; }
.ttn-icon-code { color: #f59e0b; }
.ttn-icon-markdown { color: #6366f1; }

.ttn-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary, #111);
  min-width: 0;
}
.ttn-name :deep(.ttn-hl) {
  background: rgba(250, 204, 21, 0.4);
  color: var(--primary-color, #3b82f6);
  font-weight: 600;
  border-radius: 2px;
  padding: 0 1px;
}

.ttn-count {
  font-size: 10.5px;
  color: var(--text-secondary, #9ca3af);
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.ttn-size {
  font-size: 10.5px;
  color: var(--text-secondary, #9ca3af);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  flex-shrink: 0;
  padding: 0 2px;
}
.ttn-time {
  font-size: 10.5px;
  color: var(--text-secondary, #9ca3af);
  opacity: 0.7;
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: nowrap;
}

/* —— ↩ 恢复：hover 变蓝（积极动作） —— */
.ttn-act {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
  font-size: 11px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary, #6b7280);
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
  margin-left: 2px;
}
.ttn-row:hover .ttn-act {
  opacity: 1;
}
.ttn-act.ttn-restore:hover {
  background: var(--bg-hover, #e5e7eb);
  color: var(--primary-color, #3b82f6);
}
.ttn-act:disabled {
  opacity: 0.4 !important;
  cursor: not-allowed;
}

/* —— × 永久删除 —— */
.ttn-del {
  opacity: 0;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  font-size: 13px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary, #9ca3af);
  cursor: pointer;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
}
.ttn-row:hover .ttn-del {
  opacity: 1;
}
.ttn-del:hover {
  background: var(--bg-hover, #e5e7eb);
  color: #ef4444;
}
.ttn-del.confirming {
  opacity: 1 !important;
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
  font-weight: 600;
}
.ttn-del.confirming:hover {
  background: rgba(239, 68, 68, 0.22);
}
.ttn-del:disabled {
  opacity: 0.3 !important;
  cursor: not-allowed;
  background: transparent !important;
  color: var(--text-secondary, #9ca3af) !important;
}

/* —— 子节点容器 —— */
.ttn-children {
  position: relative;
}
</style>