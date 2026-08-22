<template>
  <transition name="slash-fade">
    <div v-if="visible" ref="palette" class="slash-palette" @mousedown.prevent>
      <!-- 顶部「Slash 命令 / N 个可用」头去掉，直接进入分组列表 -->

      <!-- 按 kind 分组渲染：action 命令排前面，skill 排后面。
           同组内按 filtered 顺序保持稳定；过滤 query 时整组隐藏（避免跨组跳变）。
           顶层 <template v-for> 必须把 :key 放在 template 自身，子节点各自带 :key。 -->
      <template v-for="group in groupedFiltered" :key="group.kind">
        <div class="slash-palette-group-label">{{ group.label }}</div>
        <div
          v-for="cmd in group.items"
          :key="cmd.name"
          ref="items"
          class="slash-palette-item"
          :class="{
            active: cmd._globalIndex === selectedIndex,
            'slash-palette-item--action': cmd.kind === 'action'
          }"
          @mousedown.prevent="$emit('select', cmd)"
          @mouseenter="$emit('update:selectedIndex', cmd._globalIndex)"
        >
          <span class="slash-palette-name">
            <span class="slash-palette-prefix">/</span><span class="slash-palette-cmd">{{ cmd.name }}</span>
          </span>
          <span class="slash-palette-desc">{{ cmd.description }}</span>
          <span v-if="cmd._globalIndex === selectedIndex" class="slash-palette-keyhint">↵</span>
        </div>
      </template>

      <div v-if="filtered.length === 0" class="slash-palette-empty">
        没有匹配「{{ query }}」的命令
      </div>
    </div>
  </transition>
</template>

<script>
export default {
  name: 'SlashPalette',
  props: {
    visible: { type: Boolean, default: false },
    query: { type: String, default: '' },
    commands: { type: Array, default: () => [] },
    selectedIndex: { type: Number, default: 0 }
  },
  emits: ['select', 'update:selectedIndex', 'close'],
  computed: {
    filtered() {
      const q = (this.query || '').toLowerCase().trim()
      if (!q) return this.commands
      return this.commands.filter(cmd => {
        const name = (cmd.name || '').toLowerCase()
        const desc = (cmd.description || '').toLowerCase()
        const aliases = (cmd.aliases || []).map(a => String(a).toLowerCase())
        return name.includes(q) || desc.includes(q) || aliases.some(a => a.includes(q))
      })
    },
    /**
     * 按 kind 分组（命令 / 技能），每组内部维持 filtered 顺序。每条 cmd 携带 _globalIndex
     * 方便 selectedIndex 跨组定位（item ref / hover 高亮都用全局下标）。
     * 空组自动不渲染。
     */
    groupedFiltered() {
      const groups = []
      const buckets = {
        action: { kind: 'action', label: '命令', items: [] },
        skill: { kind: 'skill', label: '技能', items: [] }
      }
      let gIdx = 0
      for (const cmd of this.filtered) {
        const b = buckets[cmd.kind === 'action' ? 'action' : 'skill']
        if (!b) continue
        b.items.push({ ...cmd, _globalIndex: gIdx })
        gIdx++
      }
      for (const k of ['action', 'skill']) {
        if (buckets[k].items.length) groups.push(buckets[k])
      }
      return groups
    }
  },
  watch: {
    filtered() {
      // 过滤结果变化时，selectedIndex 不越界
      if (this.selectedIndex >= this.filtered.length) {
        this.$emit('update:selectedIndex', 0)
      }
      this.$nextTick(this.scrollActiveIntoView)
    },
    selectedIndex() {
      this.$nextTick(this.scrollActiveIntoView)
    },
    visible(val) {
      if (val) this.$nextTick(this.scrollActiveIntoView)
    }
  },
  methods: {
    // 键盘上下选择时让高亮项跟随滚动；只滚 palette 容器自身，不用
    // scrollIntoView（会连带把外层聊天区 / 页面一起滚）
    // grouped 渲染后，$refs.items 是二维数组（每组一项），需要扁平化定位全局下标。
    scrollActiveIntoView() {
      const container = this.$refs.palette
      const itemsRefs = this.$refs.items
      if (!container || !itemsRefs) return
      const flat = itemsRefs.flat()
      const el = flat[this.selectedIndex]
      if (!el) return

      const itemTop = el.offsetTop
      const itemBottom = itemTop + el.offsetHeight
      const viewTop = container.scrollTop
      const viewBottom = viewTop + container.clientHeight

      if (itemTop < viewTop) {
        container.scrollTop = itemTop - 4
      } else if (itemBottom > viewBottom) {
        container.scrollTop = itemBottom - container.clientHeight + 4
      }
    }
  }
}
</script>

<style scoped>
.slash-palette {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  right: 0;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.12), 0 0 0 1px rgba(0, 0, 0, 0.04);
  max-height: 320px;
  overflow: hidden auto;
  z-index: 100;
  padding: 4px;
}

.slash-palette-empty {
  padding: 24px 14px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}

.slash-palette-item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 12px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.1s ease;
  user-select: none;
}

.slash-palette-item.active,
.slash-palette-item:hover {
  background: rgba(186, 220, 248, 0.32);
}

@media (prefers-color-scheme: dark) {
  .slash-palette-item.active,
  .slash-palette-item:hover {
    background: rgba(56, 139, 253, 0.22);
  }
}

.slash-palette-name {
  display: inline-flex;
  align-items: baseline;
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.3;
  letter-spacing: 0.01em;
}

.slash-palette-prefix {
  color: var(--text-secondary);
  font-weight: 400;
  margin-right: 1px;
}

.slash-palette-cmd {
  color: var(--text-primary);
  font-weight: 600;
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
}

/* 前端动作命令（不发给 AI）：名字颜色淡一档 + 去掉加粗，与 skill 命令区分。
   不靠任何文字标签 / 图标，纯排版层级暗示。skill 是 primary + 600，action 是 secondary + 500。 */
.slash-palette-item--action .slash-palette-prefix {
  color: var(--text-secondary);
}
.slash-palette-item--action .slash-palette-cmd {
  color: var(--text-secondary);
  font-weight: 500;
}

.slash-palette-desc {
  flex: 1;
  min-width: 0;
  font-size: 11.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.4;
  text-align: right;
}

.slash-palette-item--action .slash-palette-desc {
  opacity: 0.85;
}

.slash-palette-keyhint {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  opacity: 0.6;
}

.slash-palette-group-label {
  padding: 8px 12px 4px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
  text-transform: uppercase;
  user-select: none;
}

/* Fade + slide 过渡 */
.slash-fade-enter-active,
.slash-fade-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.slash-fade-enter-from,
.slash-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

/* 深色主题微调 */
@media (prefers-color-scheme: dark) {
  .slash-palette {
    box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.4);
  }
}
</style>
