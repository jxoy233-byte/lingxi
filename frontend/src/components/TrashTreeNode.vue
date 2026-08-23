<template>
  <div class="ttn-wrapper">
    <!-- 目录节点：▶ 折叠 + 📁 图标 + 名字 + 计数 + × 永久删除整目录（行内二次确认） -->
    <div
      v-if="node.type === 'directory'"
      class="ttn-row ttn-dir"
      :style="{ paddingLeft: (depth * 14 + 8) + 'px' }"
      @click="toggle"
    >
      <span class="ttn-caret" :class="{ open: expanded }">▶</span>
      <span class="ttn-icon">📁</span>
      <span class="ttn-name">{{ node.name }}</span>
      <span v-if="node.children && node.children.length > 0" class="ttn-count">
        {{ node.children.length }}
      </span>
      <!-- 根节点（虚拟 __trash_root__）无 fullPath，不挂 × 按钮 -->
      <button
        v-if="node.fullPath"
        class="ttn-del ttn-del-dir"
        :class="{ confirming: confirmingDirDelete }"
        :disabled="busy"
        :title="confirmingDirDelete ? '再次点击永久删除该目录（含所有子项）' : '永久删除该目录'"
        :aria-label="confirmingDirDelete ? '再次点击永久删除该目录' : '永久删除目录'"
        @click.stop="onDirDeleteClick"
      >×</button>
    </div>

    <!-- 文件叶子节点：↩ 恢复 + × 永久删除（行内二次确认） -->
    <div
      v-else
      class="ttn-row ttn-file"
      :style="{ paddingLeft: (depth * 14 + 26) + 'px' }"
    >
      <span class="ttn-icon">{{ icon }}</span>
      <span class="ttn-name" :title="node.fullPath">{{ node.name }}</span>
      <span v-if="node.size != null" class="ttn-size">{{ formatSize(node.size) }}</span>
      <span v-if="node.timestamp" class="ttn-time" :title="node.fullTimestamp || node.timestamp">
        🕐 {{ formatTime(node.timestamp) }}
      </span>
      <button
        class="ttn-act ttn-restore"
        :disabled="busy"
        :title="busy ? '处理中…' : '恢复到原位置'"
        :aria-label="busy ? '处理中' : '恢复'"
        @click.stop="onRestoreClick"
      >↩</button>
      <button
        class="ttn-del"
        :class="{ confirming: confirmingDelete }"
        :disabled="busy"
        :title="confirmingDelete ? '再次点击永久删除' : '永久删除'"
        :aria-label="confirmingDelete ? '再次点击永久删除' : '永久删除'"
        @click.stop="onDeleteClick"
      >×</button>
    </div>

    <!-- 递归子节点 -->
    <div v-if="node.type === 'directory' && expanded && sortedChildren.length > 0">
      <TrashTreeNode
        v-for="child in sortedChildren"
        :key="child.type + ':' + (child.fullPath || child.name)"
        :node="child"
        :depth="depth + 1"
        :busy="busy"
        @trash-item-restore="$emit('trash-item-restore', $event)"
        @trash-item-delete="$emit('trash-item-delete', $event)"
        @trash-folder-delete="$emit('trash-folder-delete', $event)"
      />
    </div>
  </div>
</template>

<script>
/**
 * 回收站树节点 —— 跟 DataTreeNode.vue 同样套路（递归 + 目录/文件双形态），
 * 文件叶子挂「↩ 恢复」+「× 删除」两个行内操作按钮；目录节点（除虚拟根外）挂
 *「× 删除整目录」按钮，整目录删除由父级走 DELETE /trash/folder?path_prefix=...。
 *
 * 关键约定：
 * - 文件叶子同时挂 ↩ + ×，沿用偏好 21/22 的小红叉二次确认
 * - 目录节点挂 ×（根节点 __trash_root__ 不挂，因为它没 fullPath），同样行内二次确认
 * - parent 把 busy 通过 props 透传，busy=true 时整棵子树 × 按钮全部 disabled
 *   （防止并发删导致列表不一致）
 *
 * 节点结构（父级 buildTrashTree 生成）：
 * - 目录：{ type: 'directory', name, fullPath, children: [...] }
 *   fullPath = 拼出来的 original_path 前缀，给 × 整目录删除用
 * - 文件：{ type: 'file', name, size, timestamp, fullPath, item: { ...原始 trashItems 项 } }
 *   item 字段是为了「↩ 恢复」时把原始数据（含 trash_path）带回父级
 */
export default {
  name: 'TrashTreeNode',
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 },
    busy: { type: Boolean, default: false }
  },
  emits: ['trash-item-restore', 'trash-item-delete', 'trash-folder-delete'],
  data() {
    return {
      expanded: this.depth < 1, // 默认展开前 1 层（根目录 / 第一层子目录）
      confirmingDelete: false, // 文件行 × 二次确认态
      confirmingDirDelete: false // 目录行 × 二次确认态
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
      const n = (this.node.name || '').toLowerCase()
      if (/\.(png|jpe?g|gif|webp|svg)$/.test(n)) return '🖼'
      if (/\.(csv|tsv)$/.test(n)) return '📊'
      if (/\.json$/.test(n)) return '📋'
      if (/\.xlsx?$/.test(n)) return '📈'
      if (/\.(md|markdown)$/.test(n)) return '📝'
      if (/\.mmd$/.test(n)) return '🕸'
      if (/\.py$/.test(n)) return '🐍'
      if (/\.(html?|css)$/.test(n)) return '🌐'
      if (/\.(txt|log)$/.test(n)) return '📄'
      return '📄'
    }
  },
  methods: {
    toggle() {
      this.expanded = !this.expanded
    },
    onRestoreClick() {
      // 文件叶子才有 item 字段，目录节点没这个按钮
      if (this.node.item) {
        this.$emit('trash-item-restore', this.node.item)
      }
    },
    onDeleteClick() {
      if (this.confirmingDelete) {
        // 第二次点红 × → 真删（先重置防止冒泡）
        this.confirmingDelete = false
        if (this.node.item) {
          this.$emit('trash-item-delete', this.node.item)
        }
      } else {
        // 第一次点 → 进确认态
        this.confirmingDelete = true
      }
    },
    onDirDeleteClick() {
      // 目录行 ×：第一次进红、第二次点红 × 整目录批量删除（emit 给父级）
      if (this.confirmingDirDelete) {
        this.confirmingDirDelete = false
        this.$emit('trash-folder-delete', this.node)
      } else {
        this.confirmingDirDelete = true
      }
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
        // 短格式 MM-DD HH:MM（树视图空间小，长格式 tooltip 里看完整）
        return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
      } catch (e) {
        return ''
      }
    }
  }
}
</script>

<style scoped>
.ttn-wrapper {
  user-select: none;
}
.ttn-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 0;
  line-height: 1.5;
  white-space: nowrap;
}
.ttn-row:hover {
  background: var(--bg-hover, #f9fafb);
}
.ttn-dir {
  cursor: pointer;
}
.ttn-caret {
  display: inline-block;
  width: 12px;
  font-size: 9px;
  transition: transform 0.15s;
  color: var(--text-secondary, #9ca3af);
  text-align: center;
}
.ttn-caret.open {
  transform: rotate(90deg);
}
.ttn-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.ttn-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary, #111);
  min-width: 0;
}
.ttn-count {
  font-size: 11px;
  color: var(--text-secondary, #9ca3af);
  flex-shrink: 0;
}
.ttn-size {
  font-size: 11px;
  color: var(--text-secondary, #9ca3af);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  flex-shrink: 0;
}
.ttn-time {
  font-size: 11px;
  color: var(--text-secondary, #9ca3af);
  opacity: 0.7;
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: nowrap;
}

/* ↩ 恢复：hover 变蓝（积极动作） */
.ttn-act {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary, #6b7280);
  transition: opacity 0.15s, background 0.15s, color 0.15s;
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

/* × 永久删除：默认隐藏，行 hover 时显出；第一次点 → 变红常显；第二次点红 × → 真删 */
.ttn-del {
  opacity: 0;
  font-size: 14px;
  font-weight: 500;
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
  /* busy 状态下置灰（parent.anyTrashBusy=true 时整树 × 全 disabled） */
  opacity: 0.3 !important;
  cursor: not-allowed;
  background: transparent !important;
  color: var(--text-secondary, #9ca3af) !important;
}
</style>
