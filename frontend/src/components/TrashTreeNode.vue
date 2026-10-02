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
        <svg width="18" height="18" viewBox="0 0 24 24">
          <path class="ttn-folder-back"
                d="M2.5 6.5a2 2 0 0 1 2-2h4.2l1.8 2.2h9a2 2 0 0 1 2 2v9.8a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2z"/>
          <path class="ttn-folder-front"
                d="M2.5 9.5h19v9.5a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2z"/>
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

      <span class="ttn-icon ttn-icon--file" :class="'ttn-icon-' + iconKind" :title="iconHint">
        <svg width="18" height="18" viewBox="0 0 24 24">
          <rect class="ttn-badge" x="1.25" y="1.25" width="21.5" height="21.5" rx="5.5"/>
          <text
            v-if="badgeText"
            class="ttn-tag"
            x="12"
            y="12"
            text-anchor="middle"
            dominant-baseline="central"
            :font-size="badgeSize"
          >{{ badgeText }}</text>
          <!-- 无扩展名 / 后缀未注册（Makefile、LICENSE、.foo）→ 画文档页字形。
               这类文件没有可印的短标，印 "FILE" 既没信息量又跟文本徽章长得一样。 -->
          <g v-else>
            <path class="ttn-gl-doc"
                  d="M7.3 4.5h5.6l3.8 3.9v10.7a1.3 1.3 0 0 1-1.3 1.3H7.3A1.3 1.3 0 0 1 6 19.1V5.8a1.3 1.3 0 0 1 1.3-1.3z"/>
            <path class="ttn-gl-doc" d="M12.7 4.5v4.1h3.8"/>
            <path class="ttn-gl" d="M8.9 12.4h6.3M8.9 15.3h6.3M8.9 18.2h3.5"/>
          </g>
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
 * - 文件徽章与文件树（DataTreeNode）完全同源：kind 规则来自 `utils/fileKind.js`，
 *   颜色 token 共用 App.vue 的 `--ft-*`，两棵树不会各改各的走样
 */
import { resolveFileKind, fileKindHint, fileBadgeText, badgeFontSize } from '../utils/fileKind.js'

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
      return resolveFileKind(this.node.name)
    },
    iconHint() {
      return fileKindHint(this.node.name)
    },
    badgeText() {
      return fileBadgeText(this.node.name)
    },
    // 注意这是「值」不是「函数」——模板里直接 :font-size="badgeSize"，
    // 写成 badgeFontSize(badgeText) 会去调用这个数字，render 直接抛错、整棵子树消失
    badgeSize() {
      return badgeFontSize(this.badgeText)
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
  /* 18px 而不是 16px：徽章里印了 4 字符短标（DOCX / XLSX），16px 下缩到 ~5px 高根本读不出来。
     行高预算够：.dtn-row min-height 24 + 上下 padding 3 = 内容区 18px */
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

/* 回收站专属的红色文件夹（与文件树的蓝文件夹区分开，一眼知道在回收站里） */
.ttn-folder-back { fill: var(--ft-folder-back, #93c5fd); opacity: 0.5; }
.ttn-folder-front { fill: var(--accent-red, #ef4444); opacity: 0.82; }

/* 文件徽章：实心底色 + 扩展名小字，规则与文件树一致（--ft-* token 共用 App.vue） */
.ttn-badge { fill: var(--dtn-fg, #6b7280); }
.ttn-gl { fill: #fff; }
.ttn-gl-doc {
  fill: none;
  stroke: #fff;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.ttn-tag {
  fill: #fff;
  font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
  font-weight: 700;
  letter-spacing: -0.3px;
  font-variant-ligatures: none;
  text-rendering: geometricPrecision;
  user-select: none;
}
.ttn-icon-sheet   { --dtn-fg: var(--ft-sheet); }
.ttn-icon-table   { --dtn-fg: var(--ft-table); }
.ttn-icon-docx    { --dtn-fg: var(--ft-docx); }
.ttn-icon-pdf     { --dtn-fg: var(--ft-pdf); }
.ttn-icon-markdown { --dtn-fg: var(--ft-markdown); }
.ttn-icon-html    { --dtn-fg: var(--ft-html); }
.ttn-icon-image   { --dtn-fg: var(--ft-image); }
.ttn-icon-video   { --dtn-fg: var(--ft-video); }
.ttn-icon-audio   { --dtn-fg: var(--ft-audio); }
.ttn-icon-archive { --dtn-fg: var(--ft-archive); }
.ttn-icon-font    { --dtn-fg: var(--ft-font); }
.ttn-icon-json    { --dtn-fg: var(--ft-json); }
.ttn-icon-code    { --dtn-fg: var(--ft-code); }
.ttn-icon-binary  { --dtn-fg: var(--ft-binary); }
.ttn-icon-text    { --dtn-fg: var(--ft-text); }
.ttn-icon-doc,
.ttn-icon-other   { --dtn-fg: var(--ft-doc); }

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