<!--
  ExcelDocDrawer.vue —— 手动触发的 Excel 实时预览抽屉。

  与 WordDocDrawer 不同：
  - 默认不自动打开（_excelDrawer.visible 一直为 false，除非用户点 ChatHeader 📊 按钮）
  - AI 调 ExcelEditor 时只跟踪最新文件 + version++（同步 refresh），但不 visible
  - 用户点 ChatHeader 📊 按钮 → visible=true → 渲染当前 tracked 文件

  数据流：
  - App.vue 检测 tool_call_name 含 `from skills.ExcelEditor import` + ExcelDoc.create/open()
    → 抽 filePath，version++ → drawer component watch version → fetch + SheetJS 渲染
  - 每个 tool_call_result → version++ → reload（同 Word 的 200ms debounce）
  - 多 sheet 时给个 tab 选择（第一个 sheet 默认渲染）

  v1 只做只读预览，不做单元格编辑。
-->
<template>
  <transition name="slide">
    <aside
      v-if="visible"
      class="excel-doc-drawer"
      tabindex="-1"
      ref="drawerEl"
      :style="{ width: panelWidth + 'px' }"
      @keydown="handleKeydown"
    >
      <div class="resize-handle" @mousedown="startResize" />

      <header class="drawer-header">
        <span class="drawer-title">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
            <line x1="3" y1="9" x2="21" y2="9"/>
            <line x1="3" y1="15" x2="21" y2="15"/>
            <line x1="9" y1="3" x2="9" y2="21"/>
            <line x1="15" y1="3" x2="15" y2="21"/>
          </svg>
          表格预览
          <span v-if="sheets.length > 1" class="drawer-sheets-inline">({{ sheets.length }} sheets)</span>
        </span>
        <span v-if="isStreaming" class="drawer-streaming">
          <span class="streaming-dot" />
          AI 正在写入…
        </span>
        <span v-else class="drawer-idle">已就绪</span>

        <span class="drawer-spacer" />

        <button
          class="drawer-reload"
          :disabled="loading || !filePath"
          title="手动刷新"
          @click="reloadNow"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
        </button>
        <button class="drawer-close" title="关闭（Esc）" @click="$emit('close')">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </header>

      <!-- 多 sheet 时给个 tab 选择 -->
      <div v-if="sheets.length > 1" class="sheet-tabs" ref="tabStrip" tabindex="-1" @keydown="handleTabKeydown">
        <button
          v-for="(name, idx) in sheets"
          :key="name"
          type="button"
          class="sheet-tab"
          :class="{ active: name === activeSheet }"
          :title="name"
          @click="activeSheet = name"
        >
          {{ name }}
        </button>
      </div>

      <div class="drawer-content">
        <div v-if="loading && !sheetHtml" class="drawer-loading">
          <div class="loading-spinner" />
          加载中…
        </div>

        <div v-else-if="error" class="drawer-error">
          <div class="error-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
          </div>
          <div class="error-text">{{ error }}</div>
          <button class="error-retry" @click="reloadNow">重试</button>
        </div>

        <div v-else-if="!filePath" class="drawer-empty">
          <p>等待 AI 写入 Excel 文件…</p>
        </div>

        <div v-show="sheetHtml" class="sheet-wrap" v-html="sanitizedSheetHtml" />
      </div>
    </aside>
  </transition>
</template>

<script>
import DOMPurify from 'dompurify'

export default {
  name: 'ExcelDocDrawer',
  props: {
    visible: { type: Boolean, default: false },
    filePath: { type: String, default: '' },
    version: { type: Number, default: 0 },
    isStreaming: { type: Boolean, default: false }
  },
  emits: ['close'],
  data() {
    return {
      // SheetJS 解析后的 workbook（多 sheet 用）
      workbook: null,
      sheets: [],
      activeSheet: '',
      sheetHtml: '',          // 当前 active sheet 的 HTML
      error: null,
      loading: false,
      panelWidth: 540,
      isResizing: false,
      startX: 0,
      startWidth: 0,
      _reloadToken: 0,
      _reloadTimer: null,
      _lastRenderedVersion: -1,
      _XLSX: null
    }
  },
  computed: {
    sanitizedSheetHtml() {
      // SheetJS 输出的 sheet_to_html 含 inline style + table；DOMPurify 过一遍
      if (!this.sheetHtml) return ''
      return DOMPurify.sanitize(this.sheetHtml, {
        ALLOWED_TAGS: ['table','thead','tbody','tr','th','td','caption','colgroup','col'],
        ALLOWED_ATTR: ['colspan','rowspan','style'],
        ALLOW_DATA_ATTR: false
      })
    }
  },
  watch: {
    version() { this._scheduleReload() },
    activeSheet() {
      // 用户切换 sheet → 立即渲染（不 debounce）
      this._renderActiveSheet()
    },
    filePath() {
      // 文件变了 → 重置 workbook
      this.workbook = null
      this.sheets = []
      this.activeSheet = ''
      this.sheetHtml = ''
      this.error = null
      this._lastRenderedVersion = -1
      this._scheduleReload({ immediate: true })
    }
  },
  mounted() {
    this.$nextTick(() => {
      if (this.visible && this.$refs.drawerEl) {
        this.$refs.drawerEl.focus()
      }
    })
  },
  methods: {
    _scheduleReload(opts = {}) {
      if (this._reloadTimer) {
        clearTimeout(this._reloadTimer)
        this._reloadTimer = null
      }
      if (opts.immediate) {
        this.reloadNow()
        return
      }
      this._reloadTimer = setTimeout(() => {
        this._reloadTimer = null
        this.reloadNow()
      }, 200)
    },
    reloadNow() {
      this.reload()
    },
    async reload() {
      if (!this.filePath) return
      if (this.version === this._lastRenderedVersion) return
      const token = ++this._reloadToken
      this.loading = true
      this.error = null
      try {
        const resp = await fetch(this.filePath + '?t=' + Date.now())
        if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`)
        const buf = await resp.arrayBuffer()
        if (token !== this._reloadToken) return

        // 懒加载 SheetJS —— 首次打开才拉 chunk
        if (!this._XLSX) {
          const mod = await import('xlsx')
          this._XLSX = mod.read ? mod : mod.default
        }
        if (token !== this._reloadToken) return

        // 解析 workbook（不重新拉，buf 已在手上）
        const wb = this._XLSX.read(buf, { type: 'array' })
        if (token !== this._reloadToken) return
        this.workbook = wb
        this.sheets = wb.SheetNames || []
        this.activeSheet = this.sheets[0] || ''
        this._lastRenderedVersion = this.version
        // 渲染当前 sheet
        this._renderActiveSheet(token)
      } catch (e) {
        if (token !== this._reloadToken) return
        if (this.sheetHtml) {
          console.warn('[ExcelDocDrawer] reload 失败，保留旧预览:', e.message)
          this.error = null
        } else {
          this.error = `加载失败: ${e.message}`
        }
      } finally {
        if (token === this._reloadToken) this.loading = false
      }
    },
    /**
     * 渲染 active sheet → HTML。
     * 用 sheet_to_html（SheetJS 自带 HTML 输出），DOMPurify 兜底安全。
     * 不带 token 校验（内部调用，可被 reload 流程外的 sheet 切换触发）。
     */
    _renderActiveSheet(token) {
      if (!this.workbook || !this.activeSheet) return
      const sheet = this.workbook.Sheets[this.activeSheet]
      if (!sheet) {
        this.sheetHtml = '<p style="padding:20px;color:#999;">空 sheet</p>'
        return
      }
      // 用 sheet_to_html 保持 SheetJS 默认样式 + inline style
      let html = this._XLSX.utils.sheet_to_html(sheet, { editable: false })
      // SheetJS 默认输出 width/height 内联样式 + nowrap，容易太宽；保留但加 container 横向滚动
      this.sheetHtml = html
    },
    handleTabKeydown(e) {
      // tab strip 内 ←/→ 切 sheet
      if (!this.sheets.length) return
      const idx = this.sheets.indexOf(this.activeSheet)
      if (e.key === 'ArrowLeft' && idx > 0) {
        e.preventDefault()
        this.activeSheet = this.sheets[idx - 1]
      } else if (e.key === 'ArrowRight' && idx < this.sheets.length - 1) {
        e.preventDefault()
        this.activeSheet = this.sheets[idx + 1]
      }
    },
    handleKeydown(e) {
      // sheet-tabs 内部自己处理 ←/→，这里只兜底 Esc
      if (e.target.closest('.sheet-tabs')) return
      if (e.key === 'Escape' && !this.isResizing) {
        this.$emit('close')
      }
    },
    startResize(e) {
      this.isResizing = true
      this.startX = e.clientX
      this.startWidth = this.panelWidth
      document.addEventListener('mousemove', this.onResize)
      document.addEventListener('mouseup', this.stopResize)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    onResize(e) {
      if (!this.isResizing) return
      const delta = this.startX - e.clientX
      const next = Math.max(360, Math.min(window.innerWidth * 0.7, this.startWidth + delta))
      this.panelWidth = next
    },
    stopResize() {
      this.isResizing = false
      document.removeEventListener('mousemove', this.onResize)
      document.removeEventListener('mouseup', this.stopResize)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  },
  beforeUnmount() {
    this.stopResize()
    if (this._reloadTimer) {
      clearTimeout(this._reloadTimer)
      this._reloadTimer = null
    }
  }
}
</script>

<style scoped>
.excel-doc-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  background: var(--bg-primary, #ffffff);
  border-left: 1px solid var(--border-color, #e5e7eb);
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  z-index: 100;
  outline: none;
}

.resize-handle {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 1;
}
.resize-handle:hover {
  background: rgba(99, 102, 241, 0.15);
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px 12px 18px;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  background: var(--bg-secondary, #f9fafb);
  flex-shrink: 0;
  font-size: 13px;
  user-select: none;
}

.drawer-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--text-primary, #111827);
}
.drawer-title svg {
  color: var(--text-secondary, #6b7280);
}
.drawer-sheets-inline {
  font-weight: 400;
  color: var(--text-tertiary, #9ca3af);
  font-size: 11px;
}

.drawer-streaming {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #f59e0b;
  font-size: 12px;
  font-weight: 500;
}
.streaming-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f59e0b;
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

.drawer-idle {
  color: var(--text-tertiary, #9ca3af);
  font-size: 12px;
}

.drawer-spacer {
  flex: 1;
}

.drawer-reload,
.drawer-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s, color 0.15s;
}
.drawer-reload:hover:not(:disabled),
.drawer-close:hover {
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-primary, #111827);
}
.drawer-reload:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 多 sheet tab strip */
.sheet-tabs {
  display: flex;
  gap: 2px;
  padding: 6px 16px 0;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  background: var(--bg-secondary, #f9fafb);
  overflow-x: auto;
  flex-shrink: 0;
}
.sheet-tab {
  padding: 6px 12px;
  border: 1px solid transparent;
  border-bottom: none;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  font-size: 12px;
  cursor: pointer;
  border-radius: 4px 4px 0 0;
  white-space: nowrap;
  transition: background 0.15s, color 0.15s;
}
.sheet-tab:hover {
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-primary, #111827);
}
.sheet-tab.active {
  background: var(--bg-primary, #ffffff);
  border-color: var(--border-color, #e5e7eb);
  color: var(--text-primary, #111827);
  font-weight: 500;
  position: relative;
  top: 1px;
}

.drawer-content {
  flex: 1;
  overflow: auto;
  background: var(--bg-primary, #ffffff);
  position: relative;
}

.drawer-loading,
.drawer-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--text-tertiary, #9ca3af);
  font-size: 13px;
}
.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-color, #e5e7eb);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.drawer-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  padding: 32px;
  text-align: center;
}
.error-icon {
  color: var(--text-tertiary, #9ca3af);
}
.error-text {
  color: var(--text-secondary, #6b7280);
  font-size: 13px;
  line-height: 1.5;
  max-width: 320px;
}
.error-retry {
  padding: 6px 16px;
  border: 1px solid var(--border-color, #d1d5db);
  background: var(--bg-primary, #ffffff);
  border-radius: 5px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary, #111827);
}
.error-retry:hover {
  background: var(--bg-hover, #f3f4f6);
}

/* SheetJS sheet_to_html 输出：表格横向滚动 + 紧凑 padding */
.sheet-wrap {
  padding: 12px;
  overflow: auto;
}
.sheet-wrap :deep(table) {
  border-collapse: collapse;
  font-size: 12px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
}
.sheet-wrap :deep(th),
.sheet-wrap :deep(td) {
  border: 1px solid var(--border-color, #d1d5db);
  padding: 4px 8px;
  vertical-align: top;
  text-align: left;
  background: var(--bg-primary, #ffffff);
  white-space: nowrap;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sheet-wrap :deep(thead th) {
  background: var(--bg-secondary, #f9fafb);
  font-weight: 600;
}
/* SheetJS 会给数字右对齐单元格加 inline style，本地规则不动；颜色让它自然 */

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}
</style>