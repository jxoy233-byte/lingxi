<template>
  <div class="dtn-wrapper">
    <!-- 目录节点 -->
    <div
      v-if="node.type === 'directory'"
      class="dtn-row dtn-dir"
      :style="{ paddingLeft: (depth * 14 + 8) + 'px' }"
      @click="toggle"
    >
      <span class="dtn-caret" :class="{ open: expanded }">▶</span>
      <span class="dtn-icon">📁</span>
      <span class="dtn-name">{{ node.name }}</span>
      <span v-if="node.children && node.children.length > 0" class="dtn-count">
        {{ node.children.length }}
      </span>
      <!-- 行内删除按钮：删除整棵子树到 .trash/{sid}/ -->
      <button
        class="dtn-del"
        :class="{ confirming: confirmingDelete }"
        :title="confirmingDelete ? '再次点击确认删除整个文件夹（含子树）' : '删除文件夹'"
        :aria-label="confirmingDelete ? '再次点击确认删除整个文件夹（含子树）' : '删除文件夹'"
        @click.stop="onDeleteClick"
      >{{ confirmingDelete ? '×' : '×' }}</button>
    </div>

    <!-- 文件节点 -->
    <div
      v-else
      class="dtn-row dtn-file"
      :style="{ paddingLeft: (depth * 14 + 26) + 'px' }"
      @click="onClick"
      :title="node.path"
    >
      <span class="dtn-icon">{{ icon }}</span>
      <span class="dtn-name">{{ node.name }}</span>
      <span v-if="node.size != null" class="dtn-size">{{ formatSize(node.size) }}</span>
      <!-- 行内删除按钮：参考偏好 21/22 模式（小红叉二次确认） -->
      <button
        class="dtn-del"
        :class="{ confirming: confirmingDelete }"
        :title="confirmingDelete ? '再次点击确认删除' : '删除'"
        :aria-label="confirmingDelete ? '再次点击确认删除' : '删除'"
        @click.stop="onDeleteClick"
      >{{ confirmingDelete ? '×' : '×' }}</button>
    </div>

    <!-- 递归子节点 -->
    <div v-if="node.type === 'directory' && expanded && sortedChildren.length > 0">
      <DataTreeNode
        v-for="child in sortedChildren"
        :key="child.type + ':' + (child.path || child.name)"
        :node="child"
        :depth="depth + 1"
        @file-click="$emit('file-click', $event)"
        @file-delete="$emit('file-delete', $event)"
      />
    </div>
  </div>
</template>

<script>
export default {
  name: 'DataTreeNode',
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 }
  },
  emits: ['file-click', 'file-delete'],
  data() {
    return {
      expanded: this.depth < 1, // 默认展开前 1 层（gen_xxx 一级）
      confirmingDelete: false
    }
  },
  computed: {
    sortedChildren() {
      if (!this.node.children) return []
      return [...this.node.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    },
    icon() {
      const name = (this.node.name || '').toLowerCase()
      if (/\.(png|jpe?g|gif|webp|svg)$/.test(name)) return '🖼'
      if (/\.(csv|tsv)$/.test(name)) return '📊'
      if (/\.json$/.test(name)) return '📋'
      if (/\.xlsx?$/.test(name)) return '📈'
      if (/\.(md|markdown)$/.test(name)) return '📝'
      if (/\.mmd$/.test(name)) return '🕸'
      if (/\.py$/.test(name)) return '🐍'
      if (/\.(html?|css)$/.test(name)) return '🌐'
      if (/\.(txt|log)$/.test(name)) return '📄'
      return '📄'
    }
  },
  methods: {
    toggle() {
      this.expanded = !this.expanded
    },
    onClick() {
      this.$emit('file-click', this.node)
    },
    onDeleteClick() {
      if (this.confirmingDelete) {
        // 第二次点 → 真删（先重置防止冒泡）
        this.confirmingDelete = false
        this.$emit('file-delete', this.node)
      } else {
        // 第一次点 → 进确认态
        this.confirmingDelete = true
      }
    },
    cancelDeleteConfirm() {
      this.confirmingDelete = false
    },
    onKeydown(e) {
      if (e.key === 'Escape' && this.confirmingDelete) {
        this.confirmingDelete = false
      }
    },
    onOutsideClick(e) {
      // 点中本节点的删除按钮 → 不重置（让按钮自己处理）
      if (this.$el && this.$el.contains(e.target)) return
      if (this.confirmingDelete) this.confirmingDelete = false
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
}
.dtn-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 0;
  cursor: pointer;
  line-height: 1.5;
  white-space: nowrap;
}
.dtn-row:hover {
  background: var(--bg-hover, #f3f4f6);
}
.dtn-caret {
  display: inline-block;
  width: 12px;
  font-size: 9px;
  transition: transform 0.15s;
  color: var(--text-secondary, #9ca3af);
  text-align: center;
}
.dtn-caret.open {
  transform: rotate(90deg);
}
.dtn-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.dtn-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary, #111);
}
.dtn-count,
.dtn-size {
  font-size: 11px;
  color: var(--text-secondary, #9ca3af);
  flex-shrink: 0;
}

/* —— 行内删除按钮 —— 参考偏好 21/22 模式 —— */
.dtn-del {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary, #9ca3af);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
}
.dtn-row:hover .dtn-del {
  opacity: 1;
}
.dtn-del:hover {
  background: var(--bg-hover, #e5e7eb);
  color: var(--text-primary, #111);
}
.dtn-del.confirming {
  /* 二次确认态：变红常显，不依赖 hover */
  opacity: 1 !important;
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
  font-weight: 600;
}
.dtn-del.confirming:hover {
  background: rgba(239, 68, 68, 0.22);
}
</style>
