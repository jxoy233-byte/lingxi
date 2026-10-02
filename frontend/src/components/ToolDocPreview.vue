<!--
  ToolDocPreview.vue —— inline 渲染 Word/Excel 文档预览。

  v0.3.7 设计要点：
  - 渲染 / 原文 双 tab（继承 MD preview 的 tab 模式）：
    - 渲染 tab：mammoth (Word) / SheetJS (Excel) 转 HTML，AI 每写完一段就重 fetch 一次，
      内容自然一段段长出来（v0.3.8 起不做打字机揭示）
    - 原文 tab：textarea 持续可编辑（无需点"编辑"按钮）
    - 渲染 tab 双击文本 → 切到原文 tab 并 focus 段落位置
  - 持久 Save 按钮（仅 Word + 有 sessionId + 原文 tab 时显示）
  - 无任何「写入中 / 打字机 / 已完成」状态展示：面板内容本身就是唯一的进度信号
  - chrome prop：
    - 'panel'（默认）：bordered panel + header（"渲染 / 原文" tabs + save + reload），适合弹层 / 独立面板
    - 'minimal'：剥 border / background / padding，保留 tab 切换 + 内容，适合内嵌 tool_call_item / FilePreviewTabPane
  - 路径契约：normalizeDocPath 输出 /static/cached/{...}；提交保存时 _relPath() 剥 sid
-->
<template>
  <div
    class="tool-doc-preview"
    :class="`chrome-${chrome}`"
    tabindex="-1"
    ref="rootEl"
    @keydown="handleKeydown"
  >
    <!-- 工具条：与 MD 预览同款「原文 / 渲染效果」tab 行（共用 .preview-tabs / .preview-tab-btn 全局样式），
         右侧只挂保存 / 刷新 —— 状态一律不显示（见下方注释）。 -->
    <div class="preview-tabs tool-doc-toolbar">
      <button
        type="button"
        class="preview-tab-btn"
        :class="{ active: viewTab === 'raw' }"
        :disabled="!hasContent"
        @click="onSwitchToRaw"
      >原文</button>
      <button
        type="button"
        class="preview-tab-btn"
        :class="{ active: viewTab === 'rendered' }"
        :disabled="!hasContent"
        @click="viewTab = 'rendered'"
      >渲染效果</button>

      <span class="toolbar-spacer" />

      <!-- v0.3.8：AI 写入期间**不显示任何状态**。原来这里先后有过「AI 正在写入…」琥珀徽标、
           打字机进行中徽标、「✓ 已完成」提示三样，全删了 —— 面板靠内容自己一段段长出来
           表达「在写」，再叠一层状态只会让人以为卡住或重复。 -->

      <button
        v-if="canSave && viewTab === 'raw'"
        class="preview-action-btn save-btn"
        :disabled="saving || !hasSession"
        :title="saving ? '保存中…' : '保存（⌘S）'"
        @click="_saveEdits"
      >{{ saving ? '保存中…' : '保存' }}</button>

      <button
        v-if="canSave"
        class="preview-action-btn reload-btn"
        :disabled="loading || saving"
        title="手动刷新（⌘⇧R）"
        @click="reloadNow"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
      </button>
    </div>

    <div v-if="typeKind === 'excel' && sheets.length > 1 && viewTab === 'rendered'" class="sheet-tabs">
      <button
        v-for="(name, idx) in sheets"
        :key="name"
        type="button"
        class="sheet-tab"
        :class="{ active: name === activeSheet }"
        :title="name"
        @click="activeSheet = name"
      >{{ name }}</button>
    </div>

    <div class="preview-content">
      <div v-if="loading && !displayHtml" class="preview-loading">
        <div class="loading-spinner" />加载中…
      </div>

      <div v-else-if="error" class="preview-error">
        <div class="error-text">{{ error }}</div>
        <button class="error-retry" @click="reloadNow">重试</button>
      </div>

      <template v-else-if="viewTab === 'raw' && typeKind === 'word'">
        <div class="raw-edit-wrap">
          <textarea
            v-model="editDraft"
            class="docx-edit-textarea"
            spellcheck="false"
            placeholder="段落之间用空行分隔（⌘S 保存）"
            @keydown="_handleTextareaKeydown"
          />
          <div v-if="hasContent" class="raw-hint">
            <code>[[图片 N]]</code> 是图片占位符，保存时会把图片搬回它所在的位置——不要删。
            其余限制：表格按行文本重建（表结构不保留）、段落样式不保留。
          </div>
        </div>
      </template>

      <article
        v-else-if="displayHtml"
        class="doc-preview"
        :data-type="typeKind"
        v-html="displayHtml"
        @dblclick="_handleRenderedDblclick"
      />

      <div v-else class="preview-empty">
        等待 AI 写入{{ typeKind === 'word' ? '文档' : '表格' }}…
      </div>
    </div>
  </div>
</template>

<script>
import DOMPurify from 'dompurify'
import { loadMammoth, loadXLSX } from '@/utils/lazyLibs.js'
import { extractPlainTextBlocks } from '@/utils/wordExtract.js'

// AI 改写 docx/xlsx 是「先写临时文件再替换」，面板 re-fetch 有可能撞上中间态
// （404 或半截 zip）。撞上了就退避重试，否则这份文档的追加内容永远不显示
// （本轮没有下一次 docVersion 递增来救它）。
const RELOAD_DEBOUNCE_MS = 200 // 同一次写入里 tool_call_name / result 之间的合并窗口
const RELOAD_RETRY_MAX = 3
const RELOAD_RETRY_MS = 400
// 距底 ≤ 该像素视为「贴着底」，新内容追加后继续跟到底
const FOLLOW_BOTTOM_THRESHOLD = 48

export default {
  name: 'ToolDocPreview',
  props: {
    toolName: { type: String, required: true }, // 'WordEditor' | 'ExcelEditor'
    args: { type: Object, default: () => ({}) },
    version: { type: Number, default: 0 },
    isStreaming: { type: Boolean, default: false },
    sessionId: { type: String, default: '' },
    path: { type: String, default: '' },
    // 'panel' = bordered panel + header（独立面板用）
    // 'minimal' = 剥 border / background，保留 tab + 内容（内嵌 tool_call_item / TabPane 用）
    chrome: { type: String, default: 'panel' }
  },
  emits: ['edit-saved'],
  data() {
    return {
      // 当前视图 tab
      viewTab: 'rendered',  // 'rendered' | 'raw'

      // Word: mammoth 输出原文（抽段落用）
      rawHtml: null,
      // Excel: SheetJS sheet_to_html 输出
      sheetHtml: null,
      workbook: null,
      _xlsx: null,
      sheets: [],
      activeSheet: '',
      loading: false,
      error: null,
      _reloadToken: 0,
      _reloadTimer: null,
      _lastRenderedVersion: -1,
      // [v0.3.8] re-fetch 失败（文件正被改写 → 半截 zip / 短暂 404）时的重试预算。
      // 每次 version 递增重置；用完就认栽，保留旧内容 + 显示加载失败。
      _reloadRetryLeft: RELOAD_RETRY_MAX,

      // 原文编辑状态（v0.3.7 简化：原文 tab 直接可编辑，无需"进入编辑模式"）
      editDraft: '',
      // 是否需要 reload 后回填 editDraft（保留用户编辑）
      _editDirty: false,
      // 程序化赋值 editDraft 时抑制 dirty 标记（reload 同步 / 切 tab 初始化）
      _suppressDirty: false,
      saving: false,
      _saveToken: 0,
      // v0.3.8 —— 自动跟底 + 用户接管
      //   _userTookOver：用户在这个滚动区里动过（滚轮 / 触摸 / 拖滚动条）且没停在底部
      //                  → 停止自动跟底，用户优先；滚回底部自动解除
      //   _programmaticScroll：_scrollToBottom 自己触发的 scroll 事件，不算用户操作
      //   _scrollerEl：当前绑 scroll 监听的元素（两种 chrome 的滚动容器位置不同，见 _scrollParent）
      _userTookOver: false,
      _programmaticScroll: false,
      _scrollerEl: null
    }
  },
  computed: {
    typeKind() {
      return this.toolName === 'WordEditor' ? 'word' : 'excel'
    },
    canSave() {
      // 仅 Word + 有 sessionId + 有内容时支持保存
      return this.typeKind === 'word' && !!this.sessionId
    },
    hasContent() {
      if (this.typeKind === 'word') return !!this.rawHtml
      return !!this.sheetHtml
    },
    hasSession() {
      return !!this.sessionId
    },
    sanitizedHtml() {
      const raw = this.typeKind === 'word' ? this.rawHtml : this.sheetHtml
      if (!raw) return ''
      if (this.typeKind === 'word') {
        return DOMPurify.sanitize(raw, {
          ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','strong','em','u','s','sub','sup',
                         'ul','ol','li','a','table','thead','tbody','tr','th','td','br','img','span'],
          ALLOWED_ATTR: ['href','src','style','colspan','rowspan'],
          ALLOW_DATA_ATTR: false
        })
      }
      return DOMPurify.sanitize(raw, {
        ALLOWED_TAGS: ['table','thead','tbody','tr','th','td','caption','colgroup','col'],
        ALLOWED_ATTR: ['colspan','rowspan','style'],
        ALLOW_DATA_ATTR: false
      })
    },
    displayHtml() {
      if (this.viewTab === 'raw') return ''  // 让 textarea 接管
      return this.sanitizedHtml
    }
  },
  watch: {
    // [v0.3.8] docVersion +1 = 这次 WordEditor/ExcelEditor 调用返回了，文档有新内容 →
    // 重新 fetch 一次，面板内容就这么一段段长出来。
    //
    // 这是面板唯一的刷新触发源。**不要**改回 isStreaming 的 true→false 翻转：`cmd`/`code`
    // 要走审批，审批挂起时 App.vue 会 _endStreamingSession(sid) 把 isStreaming 清掉，那个
    // 翻转根本不会出现。docVersion 只在 tool_call_result 时 +1，是精确的「有新内容了」信号。
    version() {
      this._reloadRetryLeft = RELOAD_RETRY_MAX
      this._scheduleReload()
    },
    path() {
      this.rawHtml = null
      this.sheetHtml = null
      this.error = null
      this._lastRenderedVersion = -1
      this._editDirty = false
      this._scheduleReload({ immediate: true })
    },
    viewTab(v) {
      // 原文 tab 里编辑挡住了若干次 reload（见 _scheduleReload）→ 切回来补上。
      if (v === 'rendered' && this.version !== this._lastRenderedVersion) {
        this._scheduleReload({ immediate: true })
      }
    },
    activeSheet() {
      this._renderActiveSheet()
    },
    isStreaming(newV) {
      // 「这份文档的写入结束」= 兜底信号。后端 on_tool_end 在工具 stdout 为空时
      // **不发** tool_call_result（core.py:1185 `if output_content:`），那条路径上
      // docVersion 永远不会 bump，reload 一次都不会发生 → 面板永久停在旧内容。
      // 这里在流式态结束且内容确实落后时强制补一次 fetch。
      // 多一次 fetch 的代价可以忽略（reload 的 token 守卫会掐掉重复的那次）。
      if (!newV && this.path && this.version !== this._lastRenderedVersion) {
        this._reloadRetryLeft = RELOAD_RETRY_MAX
        this._scheduleReload({ immediate: true })
      }
    },
    // 用户手动改 textarea → 标记 dirty，下次 reload 不覆盖（保留用户输入）
    editDraft() {
      if (this._suppressDirty) return
      this._editDirty = true
    }
  },
  mounted() {
    this._scheduleReload({ immediate: true })
  },
  beforeUnmount() {
    if (this._reloadTimer) clearTimeout(this._reloadTimer)
    this._scrollerEl?.removeEventListener('scroll', this._onScrollerScroll)
    this._scrollerEl = null
  },
  methods: {
    // ─── fetch + mammoth/xlsx ───
    _scheduleReload(opts = {}) {
      // 原文 tab + 用户已编辑 → 不 reload（避免覆盖用户输入）。
      // ⚠️ 这里**不能**顺手把 _lastRenderedVersion 推到最新：那等于把这次 version
      // 标记成「已处理」，但内容其实一次都没重取 —— 用户切回「渲染效果」时
      // version 守卫会认为无需 reload，渲染视图就永远停在旧内容上。
      // 不消费的结果是：每次 version 递增都会走到这里被挡住（很便宜），
      // 切回渲染 tab 时由 viewTab watcher 补一次 reload。
      if (this.viewTab === 'raw' && this._editDirty) return
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
        this.reload({ force: !!opts.force })
      }, opts.delay ?? RELOAD_DEBOUNCE_MS)
    },
    reloadNow() { return this.reload({ force: true }) },
    async reload({ force = false } = {}) {
      if (!this.path) return
      // [v0.3.7] 手动触发（toolbar ↻ / 「重试」按钮）→ force 跳过 version 守卫，
      // 否则上次保存失败挂的 error 文案永远清不掉，用户卡住。自动触发（watcher / SSE）走 version 守卫避免重复 fetch。
      if (!force && this.version === this._lastRenderedVersion) return
      // ⚠️ 必须把这次 fetch 对应的 version 钉住，完成时用它而不是 this.version。
      // fetch 期间 docVersion 可能又 +1（AI 连写两段，第二段的 tool_call_result 到了）：
      // 那时 this.version 已经是新值，可这次取回来的文件**还是旧的**。写新值等于
      // 宣称「新版已渲染」，随后为新版排的那次 reload 会被版本守卫挡掉 ——
      // 追加的内容就永远停在旧版本，面板看着像不更新。
      const renderVersion = this.version
      const token = ++this._reloadToken
      this.loading = true
      this.error = null
      try {
        const resp = await fetch(this.path + '?t=' + Date.now())
        if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`)
        const buf = await resp.arrayBuffer()
        if (token !== this._reloadToken) return

        // 改内容前先记下「这次要不要自动跟到底」——追加的新段落长在文档末尾，
        // 不跟的话新内容会静默地长在视口外，看着像没更新。
        // 首次加载（还没有旧内容）不跟：那会把刚写完的长文档直接甩到最后一屏，
        // 用户看到的是报告结尾而不是开头。
        // 用户接管过（在这个滚动区里往上滚过）→ 不跟，用户优先（见 _onScrollerScroll）。
        const followBottom = this.hasContent && !this._userTookOver

        if (this.typeKind === 'word') {
          const mammoth = await loadMammoth()
          if (token !== this._reloadToken) return
          const result = await mammoth.convertToHtml({ arrayBuffer: buf })
          if (token !== this._reloadToken) return
          this.rawHtml = result.value
          this._lastRenderedVersion = renderVersion
          // 用户尚未手动改过 → 自动同步 editDraft；已改过 → 保留用户输入
          if (!this._editDirty) {
            this._setEditDraft(this._extractParagraphsFromHtml().join('\n\n'))
          }
        } else {
          const XLSX = await loadXLSX()
          if (token !== this._reloadToken) return
          const wb = XLSX.read(buf, { type: 'array' })
          if (token !== this._reloadToken) return
          this._xlsx = XLSX
          this.workbook = wb
          this.sheets = wb.SheetNames || []
          if (!this.sheets.includes(this.activeSheet)) this.activeSheet = this.sheets[0] || ''
          this._lastRenderedVersion = renderVersion
          this._renderActiveSheet()
        }
        this._reloadRetryLeft = RELOAD_RETRY_MAX
        if (followBottom) this._scrollToBottom()
      } catch (e) {
        if (token !== this._reloadToken) return
        if (this.displayHtml) {
          // 已有内容 + 这次没取到 = 撞上了改写中间态（临时 404 / 半截 zip）。
          // 直接保留旧内容就够了？不够 —— 本轮不会再有下一次 docVersion 递增来救它，
          // 追加的段落就永远停在旧版本。退避重试几次再认栽。
          console.warn('[ToolDocPreview] reload 失败，保留旧预览:', e.message)
          this.error = null
          if (this._reloadRetryLeft > 0) {
            this._reloadRetryLeft -= 1
            this._scheduleReload({ delay: RELOAD_RETRY_MS, force: true })
          }
        } else if (this.isStreaming) {
          // AI 还在写：tool_call_name 到达时文件根本还不存在，404 是预期内的。
          // 报「加载失败」是假警报，压掉它让空状态继续显示「等待 AI 写入…」；
          // tool_call_result 到达 → version bump → 重新 fetch。
          this.error = null
        } else {
          this.error = `加载失败: ${e.message}`
        }
      } finally {
        if (token === this._reloadToken) this.loading = false
      }
    },
    /** 是不是一个真的在滚、且内容超得过的容器。 */
    _isScroller(el) {
      if (!el || el.nodeType !== 1) return false
      const overflowY = getComputedStyle(el).overflowY
      return (overflowY === 'auto' || overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 1
    },
    /**
     * 找真正在滚动的容器。两种 chrome 的滚动区位置完全不同：
     * - chrome='panel'（FilePreviewModal）：滚的是**本组件内部**的 .preview-content
     *   （它是 $el 的子节点，不在祖先链上 —— 只往上找会漏掉它，追加就永远不跟底）；
     * - chrome='minimal'（FilePreviewTabPane）：.preview-content 是 max-height:none 不滚，
     *   滚的是外层 .content-container。
     * 所以先看自己的 .preview-content，再沿祖先链往上找第一个真在滚的。
     */
    _scrollParent() {
      const own = this.$el?.querySelector?.('.preview-content')
      let el = null
      if (this._isScroller(own)) {
        el = own
      } else {
        let cur = this.$el
        while (cur && cur !== document.body) {
          if (this._isScroller(cur)) { el = cur; break }
          cur = cur.parentElement
        }
      }
      // 滚动容器会变（chrome 切换 / 首次渲染时内容还不够长还不算 scroller），
      // 换容器就把 scroll 监听搬过去。scroll 是唯一能同时覆盖滚轮 / 触摸 /
      // 拖滚动条 / 键盘 PageDown 的事件，所以在容器上监听而不是在输入事件上猜。
      if (el !== this._scrollerEl) {
        this._scrollerEl?.removeEventListener('scroll', this._onScrollerScroll)
        this._scrollerEl = el
        if (el) el.addEventListener('scroll', this._onScrollerScroll)
      }
      return el
    },
    /**
     * 用户在预览区里滚了 → 记为「接管」。
     * 停在底部 = 他想继续跟着 AI 走（解除接管）；往上滚 = 他要自己看，停止自动跟底。
     */
    _onScrollerScroll() {
      if (this._programmaticScroll) return
      this._userTookOver = !this._isScrolledToBottom()
    },
    _isScrolledToBottom() {
      const el = this._scrollParent()
      if (!el) return true
      return el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_BOTTOM_THRESHOLD
    },
    _scrollToBottom() {
      this.$nextTick(() => {
        const el = this._scrollParent()
        if (!el) return
        // 程序化滚动会派发 scroll 事件，必须挡住，否则会被当成「用户接管」
        // 自己把自己关掉。scroll 事件在下一帧的「update the rendering」阶段派发，
        // 早于 rAF 回调，所以这里用 rAF 复位是安全的。
        this._programmaticScroll = true
        el.scrollTop = el.scrollHeight
        requestAnimationFrame(() => { this._programmaticScroll = false })
      })
    },
    _renderActiveSheet() {
      if (!this.workbook || !this.activeSheet || !this._xlsx) return
      const sheet = this.workbook.Sheets[this.activeSheet]
      if (!sheet) {
        this.sheetHtml = '<p style="padding:20px;color:#999;">空 sheet</p>'
        return
      }
      this.sheetHtml = this._xlsx.utils.sheet_to_html(sheet, { editable: false })
    },

    // ─── view tab 切换 ───
    onSwitchToRaw() {
      // 切到原文 tab：填充 editDraft（如尚未填），聚焦 textarea
      if (this.typeKind !== 'word') {
        this.viewTab = 'raw'
        return
      }
      if (!this.editDraft && this.rawHtml) {
        // 初始化不算用户编辑 → 抑制 dirty
        this._setEditDraft(this._extractParagraphsFromHtml().join('\n\n'))
      }
      this.viewTab = 'raw'
      // ⚠️ 不要在这里清 _editDirty。首次填充走 _setEditDraft，它自己 suppress 了 dirty
      // 标记，不需要额外清；而用户改过字再切 tab 时，这一行会把「有未保存修改」
      // 悄悄抹掉 —— 下一次 docVersion bump 就会用新内容覆盖他正在编辑的文本。
      this.$nextTick(() => {
        this.$el.querySelector('.docx-edit-textarea')?.focus()
      })
    },
    /** 程序化写 editDraft（抑制 dirty watcher）。 */
    _setEditDraft(text) {
      this._suppressDirty = true
      this.editDraft = text
      this.$nextTick(() => { this._suppressDirty = false })
    },
    _handleRenderedDblclick(e) {
      // 渲染 tab 双击文本 → 切到原文 tab 并 focus
      if (this.viewTab !== 'rendered') return
      if (this.typeKind !== 'word') return  // Excel 暂不支持编辑
      // 找到双击点附近的段落文字，定位到对应行
      const target = e.target
      const paraText = (target.textContent || '').trim()
      this.onSwitchToRaw()
      this.$nextTick(() => {
        const ta = this.$el.querySelector('.docx-edit-textarea')
        if (!ta || !paraText) return
        const idx = this.editDraft.indexOf(paraText.slice(0, 30))
        if (idx < 0) return
        ta.setSelectionRange(idx, idx + paraText.length)
        ta.focus()
      })
    },
    _handleTextareaKeydown(e) {
      // textarea 内 Cmd/Ctrl+S → 保存
      const mod = e.metaKey || e.ctrlKey
      if (mod && !e.shiftKey && !e.altKey && (e.key || '').toLowerCase() === 's') {
        e.preventDefault()
        this._saveEdits()
      }
    },

    /**
     * 从 mammoth HTML 抽出「原文」纯文本块（按文档顺序）→ 填 editDraft。
     *
     * 遍历规则（表格摊平 / 列表前缀 / 图片占位）全在 utils/wordExtract.js，
     * 那里有单测；这里只负责「解析 HTML → 调纯函数 → join」。
     */
    _extractParagraphsFromHtml() {
      if (!this.rawHtml) return []
      const tmp = document.createElement('div')
      tmp.innerHTML = this.rawHtml
      return extractPlainTextBlocks(tmp)
    },
    async _saveEdits() {
      if (this.saving) return
      if (!this.sessionId || !this.path) return
      // 未改动 → 无需保存
      if (!this._editDirty) return
      const token = ++this._saveToken
      this.saving = true
      this.error = null
      try {
        const paragraphs = this.editDraft
          .split(/\n{2,}/)
          .map(s => s.trim())
          .filter(Boolean)
        const resp = await fetch('/api/word_editor/replace', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: this.sessionId,
            file_path: this._relPath(),
            paragraphs
          })
        })
        if (token !== this._saveToken) return
        if (!resp.ok) {
          const txt = await resp.text().catch(() => '')
          throw new Error(`HTTP ${resp.status} ${txt}`)
        }
        // 保存成功：清 _editDirty（下次 reload 用新版）+ force reload 显示新内容
        this._editDirty = false
        this._lastRenderedVersion = -1
        this.reloadNow()
        this.$emit('edit-saved')
      } catch (e) {
        if (token !== this._saveToken) return
        console.error('[ToolDocPreview] save failed:', e)
        this.error = `保存失败: ${e.message}`
      } finally {
        if (token === this._saveToken) this.saving = false
      }
    },
    _relPath() {
      // URL 形态：/static/cached/[...] —— [...] 可能是：
      //   "X.docx"（flat 路径，AI 没拼 sid）
      //   "{sid}/X.docx" 或 "{sid}/sub/X.docx"（sid-scoped 路径，可编辑）
      // 后端 _resolve_safe(sid, relPath) = CACHED_DIR / sid / relPath
      // 所以提交时 relPath 必须**不**含 sid —— 自己剥掉：
      const url = this.path || ''
      const idx = url.indexOf('/cached/')
      if (idx < 0) return url
      const after = url.slice(idx + '/cached/'.length)
      const m = after.match(/^([0-9a-f]{12}|[0-9a-f]{32})\/(.+)$/)
      return m ? m[2] : after
    },

    // ─── 键盘 ───
    handleKeydown(e) {
      const mod = e.metaKey || e.ctrlKey
      const k = (e.key || '').toLowerCase()
      if (mod && e.shiftKey && !e.altKey && k === 'r') {
        e.preventDefault()
        this.reloadNow()
        return
      }
      // 渲染 tab → 双击触发的 viewTab='raw' 同步键盘切换也允许
      if (mod && e.shiftKey && !e.altKey && k === 'e') {
        e.preventDefault()
        this.onSwitchToRaw()
        return
      }
      // textarea 内 Cmd/Ctrl+S 已在 _handleTextareaKeydown 处理；root 这层不需要
      if (e.key === 'Escape' && this.viewTab === 'raw' && !this._editDirty) {
        // 原文 tab 且未改动 → 切回渲染 tab
        e.preventDefault()
        this.viewTab = 'rendered'
      }
    }
  }
}
</script>

<style scoped>
.tool-doc-preview {
  display: flex;
  flex-direction: column;
  font-size: 13px;
  outline: none;
}
/* panel：独立面板 */
.tool-doc-preview.chrome-panel {
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 6px;
  margin-top: 6px;
  background: var(--bg-primary, #ffffff);
  overflow: hidden;
  transition: border-color 0.15s;
}
/* minimal：嵌入用，无 border / padding */
.tool-doc-preview.chrome-minimal {
  border: none;
  background: transparent;
  margin: 0;
}

/* 工具条 = MD 预览同款 .preview-tabs 行（全局样式）+ 右侧状态/按钮 */
.tool-doc-toolbar {
  align-items: center;
  gap: 6px;
}
.tool-doc-toolbar .toolbar-spacer { flex: 1; }

.preview-action-btn {
  border: none;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  cursor: pointer;
  border-radius: 4px;
  font-size: 12px;
  height: 24px;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.save-btn { padding: 0 10px; }
.reload-btn { width: 24px; padding: 0; }
.preview-action-btn:hover:not(:disabled) {
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-primary, #111827);
}
.preview-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.save-btn:not(:disabled) {
  background: #6366f1;
  color: #fff;
}
.save-btn:not(:disabled):hover {
  background: #4f46e5;
  color: #fff;
}

/* 多 sheet 选择：小号 pill 行（跟上面的 tab 行区分开，不贴边） */
.sheet-tabs {
  display: flex; gap: 4px;
  margin-bottom: 8px;
  overflow-x: auto;
  flex-shrink: 0;
}
.sheet-tab {
  padding: 3px 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  border-radius: 4px;
  white-space: nowrap;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.sheet-tab:hover { background: var(--bg-hover); }
.sheet-tab.active {
  background: var(--button-bg);
  border-color: var(--button-bg);
  color: #ffffff;
  font-weight: 500;
}

.preview-content {
  flex: 1;
  overflow: auto;
  max-height: 520px;
  position: relative;
  cursor: text;
  background: var(--bg-primary, #ffffff);
}
.tool-doc-preview.chrome-minimal .preview-content {
  max-height: none;
  background: transparent;
}

.preview-loading,
.preview-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 120px; gap: 12px; color: var(--text-tertiary, #9ca3af); font-size: 13px;
}
.loading-spinner {
  width: 22px; height: 22px;
  border: 2px solid var(--border-color, #e5e7eb);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.preview-error {
  padding: 16px;
  text-align: center;
  color: var(--text-secondary, #6b7280);
  font-size: 13px;
}
.error-text { margin-bottom: 8px; }
.error-retry {
  padding: 4px 12px;
  border: 1px solid var(--border-color, #d1d5db);
  background: var(--bg-primary, #ffffff);
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-primary, #111827);
}

.doc-preview {
  padding: 20px 28px;
  max-width: 760px;
  margin: 0 auto;
  line-height: 1.7;
  color: var(--text-primary, #111827);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  font-size: 14px;
  user-select: text;
}
.doc-preview[data-type="word"] :deep(h1) { font-size: 22px; font-weight: bold; margin: 1.2em 0 0.5em; }
.doc-preview[data-type="word"] :deep(h2) { font-size: 18px; font-weight: bold; margin: 1em 0 0.4em; }
.doc-preview[data-type="word"] :deep(h3) { font-size: 16px; font-weight: bold; margin: 0.8em 0 0.4em; }
.doc-preview[data-type="word"] :deep(h4) { font-size: 15px; font-weight: bold; margin: 0.6em 0 0.3em; }
.doc-preview[data-type="word"] :deep(p) { margin: 0.6em 0; }
.doc-preview[data-type="word"] :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
  font-size: 13px;
}
.doc-preview[data-type="word"] :deep(th),
.doc-preview[data-type="word"] :deep(td) {
  border: 1px solid var(--border-color, #d1d5db);
  padding: 6px 10px;
  text-align: left;
  vertical-align: top;
}
.doc-preview[data-type="word"] :deep(th) { background: var(--bg-secondary, #f9fafb); font-weight: 600; }
.doc-preview[data-type="word"] :deep(ul),
.doc-preview[data-type="word"] :deep(ol) { margin: 0.6em 0; padding-left: 2em; }
.doc-preview[data-type="word"] :deep(li) { margin: 0.2em 0; }
.doc-preview[data-type="word"] :deep(a) { color: #6366f1; text-decoration: underline; }
.doc-preview[data-type="word"] :deep(img) { max-width: 100%; height: auto; display: block; margin: 1em auto; }

.doc-preview[data-type="excel"] :deep(table) {
  border-collapse: collapse;
  font-size: 12px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
}
.doc-preview[data-type="excel"] :deep(th),
.doc-preview[data-type="excel"] :deep(td) {
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
.doc-preview[data-type="excel"] :deep(thead th) {
  background: var(--bg-secondary, #f9fafb);
  font-weight: 600;
}

.raw-edit-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.raw-hint {
  flex-shrink: 0;
  padding: 6px 20px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-tertiary, #9ca3af);
  border-top: 1px dashed var(--border-color, #e5e7eb);
}

.docx-edit-textarea {
  display: block;
  width: 100%;
  flex: 1;
  min-height: 280px;
  box-sizing: border-box;
  padding: 20px 28px;
  border: none;
  outline: none;
  resize: vertical;
  background: var(--bg-primary, #ffffff);
  color: var(--text-primary, #111827);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}
/* minimal chrome：textarea 也走透明 */
.tool-doc-preview.chrome-minimal .docx-edit-textarea {
  background: var(--bg-primary, #ffffff);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 6px;
}


</style>