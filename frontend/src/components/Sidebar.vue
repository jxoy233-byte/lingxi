<template>
  <aside :class="['sidebar', { 'collapsed': collapsed, 'mobile-open': mobileOpen }]">
    <!-- 头部：折叠按钮 + 视图 tab 切换 + 「+ 新对话」 -->
    <div class="sidebar-header">
      <button @click="$emit('toggle')" class="toggle-btn" title="折叠/展开侧栏">
        <span v-if="!collapsed">☰</span>
        <span v-else>→</span>
      </button>

      <!-- 视图 tab 切换器（会话聊天气泡 / 文件夹文件树） -->
      <div v-if="!collapsed" class="view-tabs" role="tablist">
        <button
          type="button"
          class="view-tab"
          :class="{ active: activeView === 'sessions' }"
          role="tab"
          :aria-selected="activeView === 'sessions'"
          @click="$emit('update:activeView', 'sessions')"
          title="会话列表"
        >
          <!-- 聊天气泡 + 3 个对话点（与文件夹在轮廓上有明显区分） -->
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            <circle cx="9" cy="11" r="0.9" fill="currentColor" stroke="none"/>
            <circle cx="12" cy="11" r="0.9" fill="currentColor" stroke="none"/>
            <circle cx="15" cy="11" r="0.9" fill="currentColor" stroke="none"/>
          </svg>
        </button>
        <button
          type="button"
          class="view-tab"
          :class="{ active: activeView === 'files' }"
          role="tab"
          :aria-selected="activeView === 'files'"
          @click="$emit('update:activeView', 'files')"
          title="文件树"
          :disabled="!activeSessionId"
        >
          <!-- 文件夹 + 内含文件线条（与聊天气泡形状差异：顶部有 tab 切角） -->
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-7l-2-2H5a2 2 0 0 0-2 2z"/>
            <line x1="8" y1="13" x2="16" y2="13"/>
            <line x1="8" y1="16" x2="13" y2="16"/>
          </svg>
          <span v-if="filesCount > 0" class="view-tab-badge">{{ filesCount }}</span>
        </button>
      </div>

      <!-- 仅在会话视图下显示「+ 新对话」（文件视图不需要这个按钮） -->
      <button
        v-if="!collapsed && activeView === 'sessions'"
        @click="$emit('new-chat')"
        class="new-chat-btn"
      >
        + 新对话
      </button>
    </div>

    <!-- 主体：按视图条件渲染 -->
    <div v-if="!collapsed" class="sidebar-body">
      <!-- ============================== 会话视图（原有逻辑） ============================== -->
      <div
        v-if="activeView === 'sessions'"
        class="conversation-list"
        :class="{ 'has-overflow': hasOverflow }"
        ref="conversationListRef"
      >
        <ConversationItem
          v-for="(conv, index) in conversations"
          :key="conv.session_id"
          :conversation="conv"
          :is-active="conv.session_id === activeSessionId"
          :is-streaming="activeStreamingSessions.has(conv.session_id)"
          :is-completed-unread="completedSessions.has(conv.session_id)"
          :is-approval-pending="approvalPendingSessions.has(conv.session_id)"
          :is-errored="errorSessions.has(conv.session_id)"
          :scheduled-tasks="scheduledTasksMap.get(conv.session_id) || []"
          :scheduled-tasks-busy="scheduledTasksBusy"
          :is-scheduled-tasks-expanded="expandedScheduledTasks.has(conv.session_id)"
          @select="$emit('select-conversation', conv.session_id)"
          @delete="$emit('delete-conversation', conv.session_id)"
          @update-title="$emit('update-title', $event)"
          @refresh="$emit('refresh-conversation', conv.session_id)"
          @scheduled-task-toggle="(...args) => $emit('scheduled-task-toggle', ...args)"
          @scheduled-task-run="(tid) => $emit('scheduled-task-run', tid)"
          @scheduled-task-delete="(tid) => $emit('scheduled-task-delete', tid)"
          @toggle-scheduled-tasks="toggleScheduledTasksExpanded(conv.session_id)"
        />
        <div v-if="loadError" class="empty-state load-error">
          <div>加载对话列表失败</div>
          <div class="load-error-detail">{{ loadError }}</div>
          <div class="load-error-hint">请确认灵析后端服务已启动</div>
        </div>
        <div v-else-if="conversations.length === 0" class="empty-state">
          暂无历史对话
        </div>
      </div>

      <!-- ============================== 文件视图（新增） ============================== -->
      <div v-else-if="activeView === 'files'" class="files-view">
        <!-- 文件 tab 切换 + 操作按钮 -->
        <div class="files-toolbar">
          <div class="files-tabs">
            <button
              type="button"
              class="files-tab"
              :class="{ active: filesActiveTab === 'files' }"
              @click="switchFilesTab('files')"
            >
              <span class="files-tab-label">📁 文件</span>
              <span v-if="filesCount > 0" class="files-tab-badge">{{ filesCount }}</span>
            </button>
            <button
              type="button"
              class="files-tab"
              :class="{ active: filesActiveTab === 'trash' }"
              @click="switchFilesTab('trash')"
            >
              <span class="files-tab-label">🗑 回收站</span>
              <span v-if="trashItems.length > 0" class="files-tab-badge files-tab-badge--trash">{{ trashItems.length }}</span>
            </button>
          </div>
          <div class="files-actions">
            <template v-if="filesActiveTab === 'files'">
              <button
                class="action-btn action-btn--danger"
                :disabled="!files.length || bulkSoftDeleting"
                @click="confirmBulkSoftDelete"
                title="一键全部软删除（移到回收站，可恢复）"
                aria-label="一键全部软删除"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1.5 14a2 2 0 0 1-2 1.83H8.5a2 2 0 0 1-2-1.83L5 6"/>
                  <path d="M10 11v6M14 11v6"/>
                  <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                </svg>
              </button>
              <button
                class="action-btn"
                :disabled="!files.length || exporting"
                @click="exportZip"
                title="导出 ZIP"
                aria-label="导出 ZIP"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              </button>
              <button
                class="action-btn"
                :disabled="!files.length || exporting"
                @click="previewHtml"
                title="HTML 预览"
                aria-label="HTML 预览"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
              </button>
            </template>
            <template v-else-if="filesActiveTab === 'trash'">
              <button
                class="action-btn action-btn--danger"
                :disabled="!trashItems.length || clearingTrash"
                @click="confirmClearTrash"
                title="清空回收站（物理删除）"
                aria-label="清空回收站"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1.5 14a2 2 0 0 1-2 1.83H8.5a2 2 0 0 1-2-1.83L5 6"/>
                  <path d="M10 11v6M14 11v6"/>
                  <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                </svg>
              </button>
            </template>
            <button class="action-btn" @click="reloadFiles" title="刷新" aria-label="刷新">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- 搜索过滤 -->
        <div class="files-search">
          <svg class="files-search-icon" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            v-model="filesSearch"
            type="text"
            :placeholder="filesActiveTab === 'files' ? '搜索文件名...' : '搜索回收站...'"
            class="files-search-input"
          />
          <button
            v-if="filesSearch"
            class="files-search-clear"
            @click="filesSearch = ''"
            title="清空搜索"
            aria-label="清空搜索"
          >×</button>
        </div>

        <!-- 文件树内容 -->
        <div
          class="files-tree"
          :class="{ 'has-overflow': filesHasOverflow }"
          ref="filesTreeRef"
          tabindex="-1"
          @mousedown="onFilesTreeFocus"
          @contextmenu.prevent="onTreeEmptyContextMenu"
        >
          <!-- 文件 tab -->
          <template v-if="filesActiveTab === 'files'">
            <div v-if="filesLoading" class="empty-state"
              @contextmenu.prevent="onTreeEmptyContextMenu">加载中…</div>
            <div v-else-if="!rootNode || !rootNode.children || rootNode.children.length === 0" class="empty-state"
              @contextmenu.prevent="onTreeEmptyContextMenu">
              暂无文件
              <div class="empty-state-hint">右键空白处可新建文件夹 / 文件</div>
            </div>
            <div v-else-if="filteredRootChildren.length === 0 && filesSearch" class="empty-state"
              @contextmenu.prevent="onTreeEmptyContextMenu">
              没有匹配「{{ filesSearch }}」的文件
            </div>
            <div v-else ref="treeListRef" class="tree-list"
              @contextmenu.prevent="onTreeEmptyContextMenu"
              @mousedown="onTreeMouseDown"
            >
              <!-- Finder/Explorer 风格 box-select 视觉矩形 -->
              <div
                v-if="boxSelect.active"
                class="box-select-rect"
                :style="boxSelectStyle"
              ></div>
              <DataTreeNode
                v-for="child in filteredRootChildren"
                :key="child.path || child.name"
                :node="child"
                :depth="0"
                :search="filesSearch"
                :selected-paths="selectedPaths"
                :last-clicked-path="lastClickedPath"
                :rename-target-path="renameTargetPath"
                :cut-path="cutClipboardPath"
                :copy-path="copyClipboardPath"
                :expanded-paths="expandedPaths"
                @node-select="onNodeSelect"
                @node-toggle-expand="onNodeToggleExpand"
                @file-click="onFileClick"
                @file-delete="onFileDelete"
                @node-context="onNodeContextMenu"
                @node-rename="onFileRename"
                @node-rename-done="onRenameDone"
              />
            </div>
          </template>

          <!-- 回收站 tab -->
          <template v-else-if="filesActiveTab === 'trash'">
            <div v-if="trashLoading" class="empty-state">加载中…</div>
            <div v-else-if="sortedTrashRootChildren.length === 0" class="empty-state">
              回收站为空
              <div class="empty-state-hint">软删除的文件会出现在这里</div>
            </div>
            <div v-else-if="filteredTrashRootChildren.length === 0 && filesSearch" class="empty-state">
              没有匹配「{{ filesSearch }}」的项
            </div>
            <div v-else class="tree-list">
              <TrashTreeNode
                v-for="child in filteredTrashRootChildren"
                :key="child.type + ':' + (child.fullPath || child.name)"
                :node="child"
                :depth="0"
                :busy="!!anyTrashBusy"
                :search="filesSearch"
                @trash-item-restore="onRestoreTrashItem"
                @trash-item-delete="onTrashItemDeleteClick"
                @trash-folder-delete="onTrashFolderDelete"
              />
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 拖拽调整宽度手柄 -->
    <div v-if="!collapsed && activeView === 'files'" class="resize-handle" @mousedown="startResize"></div>

    <!-- IDEA 风右键菜单 -->
    <div
      v-if="contextMenu.visible"
      class="ctx-menu"
      :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }"
      @click.stop
    >
      <button
        v-for="item in contextMenu.items"
        :key="item.key"
        class="ctx-menu-item"
        :class="{ 'ctx-menu-item--danger': item.danger, 'ctx-menu-item--disabled': item.disabled }"
        :disabled="item.disabled"
        @click="onContextMenuAction(item.key)"
      >
        <span class="ctx-menu-icon" v-if="item.icon" v-html="item.icon"></span>
        <span class="ctx-menu-label">{{ item.label }}</span>
        <span v-if="item.shortcut" class="ctx-menu-shortcut">{{ item.shortcut }}</span>
      </button>
    </div>

    <!-- 「新建文件夹/文件」弹窗 -->
    <div v-if="newItemDialog.visible" class="ctx-dialog-mask" @click.self="closeNewItemDialog">
      <div class="ctx-dialog">
        <div class="ctx-dialog-title">
          {{ newItemDialog.kind === 'folder' ? '新建文件夹' : '新建文件' }}
        </div>
        <div class="ctx-dialog-parent-hint">
          {{ newItemDialog.parent ? `在「${newItemDialog.parent}/」内创建` : '在会话根目录下创建' }}
        </div>
        <input
          ref="newItemInput"
          v-model="newItemDialog.name"
          class="ctx-dialog-input"
          :placeholder="newItemDialog.kind === 'folder' ? '文件夹名' : '文件名'"
          @keydown.enter.prevent="confirmNewItem"
          @keydown.esc.prevent="closeNewItemDialog"
          :disabled="newItemDialog.creating"
        />
        <div class="ctx-dialog-actions">
          <button class="ctx-dialog-btn ctx-dialog-btn--cancel" :disabled="newItemDialog.creating" @click="closeNewItemDialog">取消</button>
          <button class="ctx-dialog-btn ctx-dialog-btn--ok" :disabled="newItemDialog.creating" @click="confirmNewItem">
            {{ newItemDialog.creating ? '创建中…' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 确认弹窗 -->
    <ConfirmDialog
      :visible="showClearTrashDialog"
      title="清空回收站？"
      :message="`手动删除 .trash/${clearTrashSidShort}/ 下的软删除文件，无法恢复。`"
      confirm-text="清空"
      cancel-text="取消"
      @confirm="doClearTrash"
      @cancel="showClearTrashDialog = false"
    />

    <ConfirmDialog
      :visible="showBulkSoftDeleteDialog"
      :title="bulkDeleteTitle"
      :message="bulkDeleteMessage"
      confirm-text="移到回收站"
      cancel-text="取消"
      @confirm="confirmBulkDelete"
      @cancel="cancelBulkDelete"
    />

    <!-- 非阻塞 flash 消息（替换 file ops 里所有 alert()）—— 浮在侧栏底部，3 秒自动消失 -->
    <transition name="flash-fade">
      <div
        v-if="flashMessage"
        class="flash-message"
        :class="'flash-message--' + flashMessage.type"
      >{{ flashMessage.text }}</div>
    </transition>
  </aside>
</template>

<script>
import ConversationItem from './ConversationItem.vue'
import DataTreeNode from './DataTreeNode.vue'
import TrashTreeNode from './TrashTreeNode.vue'
import ConfirmDialog from './ConfirmDialog.vue'

export default {
  name: 'Sidebar',
  components: {
    ConversationItem,
    DataTreeNode,
    TrashTreeNode,
    ConfirmDialog
  },
  props: {
    collapsed: { type: Boolean, default: false },
    mobileOpen: { type: Boolean, default: false },
    conversations: { type: Array, default: () => [] },
    activeSessionId: { type: String, default: null },
    activeStreamingSessions: { type: Set, default: () => new Set() },
    completedSessions: { type: Set, default: () => new Set() },
    approvalPendingSessions: { type: Set, default: () => new Set() },
    errorSessions: { type: Set, default: () => new Set() },
    loadError: { type: String, default: '' },
    scheduledTasksMap: { type: Map, default: () => new Map() },
    scheduledTasksBusy: { type: Boolean, default: false },
    // 当前激活的视图：'sessions' | 'files' —— 由 App.vue 控制（持久化到 localStorage）
    activeView: {
      type: String,
      default: 'sessions',
      validator: (v) => ['sessions', 'files'].includes(v)
    }
  },
  emits: [
    'toggle',
    'new-chat',
    'select-conversation',
    'delete-conversation',
    'update-title',
    'refresh-conversation',
    'scheduled-task-toggle',
    'scheduled-task-run',
    'scheduled-task-delete',
    'update:activeView',
    // 文件视图事件 —— App.vue 接到后调对应后端接口（或触发文件预览）
    'file-click',
    'reload-files'
  ],
  data() {
    return {
      hasOverflow: false,
      filesHasOverflow: false,
      _resizeObserver: null,
      _filesResizeObserver: null,
      expandedScheduledTasks: new Set(),
      // 文件视图相关
      filesActiveTab: 'files', // 'files' | 'trash'
      filesSearch: '',
      // —— 文件树数据 ——
      files: [],
      rootPath: '',
      rootNode: null,
      filesLoading: false,
      // —— 回收站数据 ——
      trashItems: [],
      trashLoading: false,
      itemBusy: {},
      folderDeleting: {},
      // —— 操作状态 ——
      exporting: false,
      bulkSoftDeleting: false,
      clearingTrash: false,
      showBulkSoftDeleteDialog: false,
      // 多选批量删除 pending 状态（null 时表示「一键全删」场景）
      _pendingBulkDeletePaths: null,
      _pendingBulkDeleteMessage: '',
      showClearTrashDialog: false,
      // —— IDEA 风文件编辑状态 ——
      selectedPaths: [],          // 多选 path 数组（响应式：必须数组，Set 加减不触发重渲染）
      lastClickedPath: '',        // 最后点击的节点（Shift+click 范围选锚点）
      lastClickedNode: null,      // 最后点击的节点对象（F2/Delete 等快捷键的目标）
      // 展开状态：plain object { [path]: true }（Vue 3 对 plain object 字段追踪最可靠）
      expandedPaths: {},
      clipboard: null,            // { src: 相对路径, mode: 'copy' | 'cut' }
      renameTargetPath: '',       // 当前 inline 重命名中的节点 path
      _isMac: typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform),
      // —— 右键菜单 ——
      contextMenu: {
        visible: false,
        x: 0,
        y: 0,
        items: []     // [{ key, label, icon?, shortcut?, danger?, disabled? }]
      },
      // —— 新建文件夹/文件弹窗 ——
      newItemDialog: {
        visible: false,
        kind: 'folder',  // 'folder' | 'file'
        parent: '',      // 相对 cached/{sid}/ 的父目录
        name: '',
        creating: false  // 请求进行中：禁用按钮 + 输入框，给用户「实时」反馈
      },
      // 拖拽调宽度
      sidebarWidthPx: 260,
      isResizing: false,
      _resizeRafId: null,
      _resizeStartX: 0,
      _resizeStartWidth: 0,
      // —— 非阻塞 flash 消息（替换原 file ops 里所有 alert() 调用） ——
      flashMessage: null,        // { text, type: 'error'|'info'|'success', timestamp } | null
      _flashTimer: null,
      // —— Finder/Explorer 风格 box-select（拖拽框选） ——
      boxSelect: {
        active: false,           // 是否正在框选
        anchorX: 0, anchorY: 0,  // 鼠标按下的初始位置（相对 .tree-list 内容区）
        x: 0, y: 0,              // 矩形左上角（取 start/end 的较小值）
        width: 0, height: 0,     // 矩形尺寸
        additive: false          // true = 按住 Shift/Cmd/Ctrl 时累加而非替换选区
      }
    }
  },
  computed: {
    filesCount() {
      return this.files.length
    },
    selectedPath() {
      // 兼容旧 prop 透传：取最后一个被点击的节点 path
      return this.lastClickedPath || ''
    },
    selectedCount() {
      return this.selectedPaths.length
    },
    /**
     * 剪贴板是 cut 模式时，把 src 还原成完整 absolute path 传给 DataTreeNode
     * （DataTreeNode 用 node.path === cutPath 判定视觉状态）
     */
    cutClipboardPath() {
      if (!this.clipboard || this.clipboard.mode !== 'cut') return ''
      // clipboard.src 是相对 cached/{sid}/ 的路径，要拼回完整 path
      const basePrefix = this.rootPath.endsWith('/') ? this.rootPath : this.rootPath + '/'
      return this.clipboard.src ? basePrefix + this.clipboard.src : ''
    },
    copyClipboardPath() {
      if (!this.clipboard || this.clipboard.mode !== 'copy') return ''
      const basePrefix = this.rootPath.endsWith('/') ? this.rootPath : this.rootPath + '/'
      return this.clipboard.src ? basePrefix + this.clipboard.src : ''
    },
    /** 拍平当前选中的节点（用于批量操作：copy/cut/delete） */
    selectedNodes() {
      if (!this.rootNode || !this.selectedPaths.length) return []
      const result = []
      const findIn = (n) => {
        if (!n) return
        if (this.selectedPaths.includes(n.path)) result.push(n)
        if (n.type === 'directory' && n.children) n.children.forEach(findIn)
      }
      findIn(this.rootNode)
      return result
    },
    sortedRootChildren() {
      if (!this.rootNode || !this.rootNode.children) return []
      return [...this.rootNode.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    },
    sortedTrashRootChildren() {
      const root = this._buildTrashTree(this.trashItems)
      if (!root || !root.children) return []
      return [...root.children].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
    },
    // 按搜索词过滤的文件树根 children（递归过滤子节点，让搜索匹配的子项自动展开）
    filteredRootChildren() {
      if (!this.filesSearch) return this.sortedRootChildren
      return this.sortedRootChildren
        .map(child => this._filterTree(child, this.filesSearch.toLowerCase()))
        .filter(Boolean)
    },
    filteredTrashRootChildren() {
      if (!this.filesSearch) return this.sortedTrashRootChildren
      return this.sortedTrashRootChildren
        .map(child => this._filterTrashTree(child, this.filesSearch.toLowerCase()))
        .filter(Boolean)
    },
    anyTrashBusy() {
      return Object.values(this.itemBusy).some(Boolean) ||
        Object.values(this.folderDeleting).some(Boolean)
    },
    clearTrashSidShort() {
      return this.activeSessionId ? this.activeSessionId.slice(0, 8) : 'session'
    },
    bulkSoftDeleteSidShort() {
      return this.activeSessionId ? this.activeSessionId.slice(0, 8) : 'session'
    },
    bulkDeleteTitle() {
      // 多选批量删除 vs 一键全删共用一个 dialog，文案区分
      if (this._pendingBulkDeletePaths && this._pendingBulkDeletePaths.length) {
        return this._pendingBulkDeletePaths.length === 1
          ? '软删除此文件 / 目录？'
          : `软删除 ${this._pendingBulkDeletePaths.length} 项？`
      }
      return '一键全部软删除？'
    },
    bulkDeleteMessage() {
      if (this._pendingBulkDeleteMessage) return this._pendingBulkDeleteMessage
      return `将当前会话工作树下全部 ${this.files.length} 个文件 / 目录移到 .trash/${this.bulkSoftDeleteSidShort}/ 下，可从回收站恢复。`
    },
    /** box-select 矩形 CSS（absolute 定位到 .tree-list 内） */
    boxSelectStyle() {
      return {
        left: this.boxSelect.x + 'px',
        top: this.boxSelect.y + 'px',
        width: this.boxSelect.width + 'px',
        height: this.boxSelect.height + 'px'
      }
    }
  },
  watch: {
    activeSessionId: {
      immediate: true,
      handler(newVal, oldVal) {
        if (newVal !== oldVal) {
          this.resetFiles()
        }
        if (newVal) {
          this.checkFiles()
          if (this.activeView === 'files') {
            this.checkTrash()
          }
        }
      }
    },
    activeView(newVal) {
      // 切到 files 视图时拉一次回收站（badge 数据）
      if (newVal === 'files' && this.activeSessionId) {
        this.checkTrash()
      }
      // 切到 files 视图 → 把焦点放到文件树容器，让 Cmd+C/X/V/D/F2/箭头等快捷键
      // 能正常触发（_shortcutGuard 检查 e.target.tagName，不能是 textarea/input）。
      // 用户切回 sessions 视图时不主动抢焦点，让浏览器自然落到上次位置。
      if (newVal === 'files') {
        this.$nextTick(() => {
          const el = this.$refs.filesTreeRef
          if (el && typeof el.focus === 'function') el.focus({ preventScroll: true })
        })
      }
    }
  },
  methods: {
    // ========== 非阻塞 flash 消息（替换 file ops 里所有 alert()） ==========
    /**
     * 把焦点放到文件树容器 —— 用户在文件树上点击（任意位置）时调，
     * 让后续键盘快捷键（Cmd+C/X/V/D/F2/箭头）的 _shortcutGuard 通过（tagName=div）。
     * 切到 files 视图时也走这条把焦点抢过来（从 MessageInput 抢回）。
     *
     * 同时处理「点空白处清状态」：
     * - 点 .dtn-row（节点行）→ 不动，节点自己的 click handler 会处理
     * - 点 .tree-list 空白 → onTreeMouseDown 已经清了，跳过避免重复
     * - 点 .files-tree padding / .empty-state（加载中 / 暂无文件 / 搜索无结果）→ 清 lastClickedNode + 选区
     *   这样后续 Cmd+V / 右键新建文件夹 / F2 等操作默认到 sid/ 根，不会被上次点击的节点带偏。
     */
    onFilesTreeFocus(event) {
      const el = this.$refs.filesTreeRef
      if (el && typeof el.focus === 'function') {
        el.focus({ preventScroll: true })
      }
      if (!event || !event.target || !event.target.closest) return
      const t = event.target
      if (t.closest('.dtn-row')) return    // 节点行 → 留给节点 click handler
      if (t.closest('.tree-list')) return  // tree-list 空白 → onTreeMouseDown 已经清过
      // 现在命中的是 .files-tree padding 或 .empty-state 区域
      this.selectedPaths = []
      this.lastClickedPath = ''
      this.lastClickedNode = null
    },
    _flash(text, type = 'info') {
      this.flashMessage = { text, type, timestamp: Date.now() }
      if (this._flashTimer) clearTimeout(this._flashTimer)
      this._flashTimer = setTimeout(() => {
        // 用 timestamp 比对，避免新消息把旧的 timer 提前关掉（虽然现在 setInterval 写法不会，但留个保险）
        if (this.flashMessage && Date.now() - this.flashMessage.timestamp >= 2900) {
          this.flashMessage = null
        }
        this._flashTimer = null
      }, 3000)
    },
    // ========== 会话视图原有方法 ==========
    checkOverflow() {
      const el = this.$refs.conversationListRef
      if (!el) return
      const overflow = el.scrollHeight > el.clientHeight + 1
      if (overflow !== this.hasOverflow) {
        this.hasOverflow = overflow
      }
    },
    checkFilesOverflow() {
      const el = this.$refs.filesTreeRef
      if (!el) return
      const overflow = el.scrollHeight > el.clientHeight + 1
      if (overflow !== this.filesHasOverflow) {
        this.filesHasOverflow = overflow
      }
    },
    toggleScheduledTasksExpanded(sessionId) {
      if (!sessionId) return
      const next = new Set(this.expandedScheduledTasks)
      if (next.has(sessionId)) {
        next.delete(sessionId)
      } else {
        next.add(sessionId)
      }
      this.expandedScheduledTasks = next
    },
    // ========== 文件视图：数据加载 ==========
    async checkFiles() {
      if (!this.activeSessionId) return
      this.filesLoading = true
      try {
        const resp = await fetch(`/chat/${this.activeSessionId}/tree`)
        if (!resp.ok) {
          this.resetFiles()
          return
        }
        const data = await resp.json()
        this.rootPath = data.root_path || ''
        this.files = data.files || []
        if (data.exists) {
          this._buildFileTree()
        } else {
          this.rootNode = null
        }
      } catch (e) {
        console.error('[Sidebar] checkFiles failed:', e)
        this.resetFiles()
      } finally {
        this.filesLoading = false
      }
    },
    async checkTrash() {
      if (!this.activeSessionId) return
      this.trashLoading = true
      try {
        const resp = await fetch(`/chat/${encodeURIComponent(this.activeSessionId)}/trash/tree`)
        if (!resp.ok) {
          this.trashItems = []
          return
        }
        const data = await resp.json()
        this.trashItems = data.items || []
      } catch (e) {
        console.error('[Sidebar] checkTrash failed:', e)
        this.trashItems = []
      } finally {
        this.trashLoading = false
      }
    },
    resetFiles() {
      this.files = []
      this.rootNode = null
      this.filesLoading = false
      this.trashItems = []
      this.trashLoading = false
      this.itemBusy = {}
      this.folderDeleting = {}
      this.bulkSoftDeleting = false
      this.showBulkSoftDeleteDialog = false
      this._pendingBulkDeletePaths = null
      this._pendingBulkDeleteMessage = ''
      // IDEA 风文件编辑状态 —— 切会话时一并清
      this.selectedPaths = []
      this.lastClickedPath = ''
      this.lastClickedNode = null
      this.expandedPaths = {}
      this.clipboard = null
      this.renameTargetPath = ''
      this.contextMenu.visible = false
      this.newItemDialog.visible = false
    },
    _buildFileTree() {
      const rootName = this.activeSessionId ? this.activeSessionId.slice(0, 8) : 'session'
      const root = { name: rootName, type: 'directory', children: [] }
      const basePrefix = this.rootPath.endsWith('/') ? this.rootPath : this.rootPath + '/'
      // 优先用后端返回的 type 字段（兼容空目录）；老版本后端没 type 时 fallback 到「末段=file」
      for (const file of this.files) {
        const rel = file.path.startsWith(basePrefix)
          ? file.path.slice(basePrefix.length)
          : file.path
        const parts = rel.split('/').filter(Boolean)
        if (parts.length === 0) continue
        let current = root
        // 后端显式标注的 type 优先；没标注（老后端）则按末段/中间段推断
        const backendType = file.type  // 'file' | 'directory' | undefined
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i]
          const isLast = i === parts.length - 1
          // 末段的最终 type：优先用后端的，否则默认 'file'
          const nodeType = isLast
            ? (backendType || 'file')
            : 'directory'
          if (nodeType === 'file') {
            current.children.push({
              name: part,
              type: 'file',
              path: file.path,
              size: file.size,
              modified_at: file.modified_at
            })
          } else {
            const dirPath = basePrefix + parts.slice(0, i + 1).join('/')
            let dir = current.children.find(c => c.name === part && c.type === 'directory')
            if (!dir) {
              dir = { name: part, type: 'directory', path: dirPath, children: [] }
              current.children.push(dir)
            }
            current = dir
          }
        }
      }
      this.rootNode = root
      // 顶层目录默认展开（与 DataTreeNode 默认行为一致 —— DataTreeNode 自己也有默认展开，
      // 这里再加一个 shared state 供 Sidebar 范围选用）
      // 用 plain object：{ [path]: true } —— Vue 3 对字段追踪最可靠
      const nextExpanded = { ...this.expandedPaths }
      for (const child of root.children) {
        if (child.type === 'directory') nextExpanded[child.path] = true
      }
      this.expandedPaths = nextExpanded
    },
    _buildTrashTree(items) {
      const root = { name: '__trash_root__', type: 'directory', children: [] }
      for (const item of items || []) {
        const rel = item.original_path || item.name || ''
        const parts = rel.split('/').filter(Boolean)
        if (parts.length === 0) continue
        let current = root
        let currentPath = ''
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i]
          const isFile = i === parts.length - 1
          const partPath = currentPath ? currentPath + '/' + part : part
          if (isFile) {
            current.children.push({
              type: 'file',
              name: part,
              size: item.size,
              timestamp: item.timestamp,
              deleted_at: item.deleted_at,
              fullPath: rel,
              item: item
            })
          } else {
            let dir = current.children.find(c => c.type === 'directory' && c.name === part)
            if (!dir) {
              dir = { type: 'directory', name: part, fullPath: partPath, children: [] }
              current.children.push(dir)
            }
            current = dir
            currentPath = partPath
          }
        }
      }
      return root
    },
    /**
     * 树过滤：保留名字包含 search 的节点 + 其祖先链（让匹配项始终可见）。
     * 文件节点名字不匹配 → 剪掉；目录节点若子树全部被剪 → 也剪掉。
     */
    _filterTree(node, search) {
      if (!node) return null
      const nameLower = (node.name || '').toLowerCase()
      const selfMatch = nameLower.includes(search)
      if (node.type === 'file') {
        return selfMatch ? node : null
      }
      // directory
      const filteredChildren = (node.children || [])
        .map(c => this._filterTree(c, search))
        .filter(Boolean)
      if (selfMatch || filteredChildren.length > 0) {
        return { ...node, children: filteredChildren }
      }
      return null
    },
    _filterTrashTree(node, search) {
      if (!node) return null
      const nameLower = (node.name || '').toLowerCase()
      const selfMatch = nameLower.includes(search)
      if (node.type === 'file') {
        return selfMatch ? node : null
      }
      const filteredChildren = (node.children || [])
        .map(c => this._filterTrashTree(c, search))
        .filter(Boolean)
      if (selfMatch || filteredChildren.length > 0) {
        return { ...node, children: filteredChildren }
      }
      return null
    },
    // ========== 文件视图：用户操作 ==========
    switchFilesTab(tab) {
      if (this.filesActiveTab === tab) return
      this.filesActiveTab = tab
      if (tab === 'trash' && this.activeSessionId) {
        this.checkTrash()
      }
    },
    reloadFiles() {
      if (this.filesActiveTab === 'trash') {
        this.checkTrash()
      } else {
        this.checkFiles()
      }
      // 通知 App.vue 用于跨组件状态同步（其实 App.vue 调 sidebarRef.reloadFiles 即可，
      // 这里 emit 是兜底保险）
      this.$emit('reload-files')
    },
    onFileClick(node) {
      // 文件预览触发：保持 lastClickedNode 同步（onNodeSelect 已经更新过 selectedPaths / lastClickedPath）
      if (node && node.path && this.lastClickedPath !== node.path) {
        // 兜底：万一 file-click 触发但 node-select 没触发，补一次选中态
        this.selectedPaths = [node.path]
        this.lastClickedPath = node.path
        this.lastClickedNode = node
      }
      this.$emit('file-click', node)
    },
    /**
     * IDEA 风多选核心：
     * - 无 modifier（普通点击）→ 单选替换（[node.path]）；同时更新 lastClicked
     * - meta/ctrl → toggle（在多选集合里加 / 减）；保留 lastClicked = 本次点击
     * - shift → 范围选：在 lastClickedPath 与 node.path 之间（含）所有可见节点全选
     */
    onNodeSelect({ node, event, modifier }) {
      if (!node || !node.path) return
      // 目录 / 文件的统一处理：路径是唯一标识
      if (modifier.shift && this.lastClickedPath && this.rootNode) {
        // 范围选：从 lastClickedPath 到 node.path（按可见顺序）
        const allVisible = this._flattenVisibleNodes(this.rootNode)
        const lastIdx = allVisible.findIndex(n => n.path === this.lastClickedPath)
        const curIdx = allVisible.findIndex(n => n.path === node.path)
        if (lastIdx >= 0 && curIdx >= 0) {
          const lo = Math.min(lastIdx, curIdx)
          const hi = Math.max(lastIdx, curIdx)
          this.selectedPaths = allVisible.slice(lo, hi + 1).map(n => n.path)
        } else {
          // 找不到锚点 → 退化为单选
          this.selectedPaths = [node.path]
        }
        this.lastClickedNode = node
        // 注意：shift 范围选时不更新 lastClickedPath（保持原始锚点）
      } else if (modifier.meta) {
        // toggle
        const idx = this.selectedPaths.indexOf(node.path)
        if (idx >= 0) {
          this.selectedPaths = [
            ...this.selectedPaths.slice(0, idx),
            ...this.selectedPaths.slice(idx + 1)
          ]
        } else {
          this.selectedPaths = [...this.selectedPaths, node.path]
        }
        this.lastClickedPath = node.path
        this.lastClickedNode = node
      } else {
        // 普通点击 → 单选替换
        this.selectedPaths = [node.path]
        this.lastClickedPath = node.path
        this.lastClickedNode = node
      }
    },
    /**
     * 把整棵树按「visible order」拍平（depth-first，按 shared expandedPaths 决定是否递归）。
     * 用于 Shift+click 范围选：必须用「用户眼睛能看到的顺序」而不是任意排序。
     */
    _flattenVisibleNodes(root) {
      const out = []
      if (!root || !root.children) return out
      const walk = (n) => {
        if (!n) return
        if (n.path) out.push(n)  // 跳过虚拟根（path 为空）
        if (n.type === 'directory' && this.expandedPaths[n.path] && n.children) {
          for (const c of n.children) walk(c)
        }
      }
      for (const c of root.children) walk(c)
      return out
    },
    /**
     * Cmd/Ctrl+A 全选：选中所有可见节点（在当前 rootNode 拍平结果中）。
     */
    selectAll() {
      const all = this._flattenVisibleNodes(this.rootNode || { children: [] })
      this.selectedPaths = all.map(n => n.path)
      // lastClicked 保持不变（避免 Shift+click anchor 跳）
    },
    /**
     * 展开 / 折叠同步：DataTreeNode 触发 node-toggle-expand 后，Sidebar 更新共享 expandedPaths。
     * 用 plain object 替换保证响应式触发子组件重渲染。
     */
    onNodeToggleExpand({ node, expanded }) {
      if (!node || !node.path) return
      const next = { ...this.expandedPaths }
      if (expanded) next[node.path] = true
      else delete next[node.path]
      this.expandedPaths = next
    },
    /**
     * Finder/Explorer 风格 box-select —— 鼠标在 tree-list 空白处按下并拖动时画矩形，
     * 松开鼠标后所有「bbox 与矩形相交」的行被选中。
     *
     * 实现要点：
     * - 仅左键（button === 0）触发；右键 / 中键留给浏览器原生菜单
     * - 只在 target 是 tree-list 自己 / empty-state 容器（非节点行）时启动 —— 节点行的点击仍走原 onRowClick
     * - Shift/Cmd/Ctrl 按下时 additively 累加选区，否则替换选区
     * - 用 data-node-path 属性 + getBoundingClientRect 做命中检测（O(n) 遍历可见节点）
     * - mousemove / mouseup 挂在 window 上 —— 拖出 tree-list 也要能继续画 / 正常结束
     */
    onTreeMouseDown(event) {
      if (event.button !== 0) return
      const tree = this.$refs.treeListRef
      if (!tree) return
      // 只在「点的是空白处」时启动 —— 节点行点击 / 拖动不在此处理（节点行的 mousedown 会冒泡但不会到这里，因为它们的祖先也是 .tree-list 本身... 需要排除）
      // 这里用 closest()：如果 target 在 .dtn-row 内部，不启动 box-select
      if (event.target && event.target.closest && event.target.closest('.dtn-row')) {
        return
      }
      const rect = tree.getBoundingClientRect()
      const x = event.clientX - rect.left + tree.scrollLeft
      const y = event.clientY - rect.top + tree.scrollTop
      const additive = !!(event.shiftKey || event.metaKey || event.ctrlKey)
      this.boxSelect = {
        active: true,
        anchorX: x, anchorY: y,
        x, y, width: 0, height: 0,
        additive,
        // 非 additively 时记录起点选区，结束时基于这个做替换
        _prevSelection: additive ? this.selectedPaths.slice() : []
      }
      // additively 模式：不清空；纯 box-select：清空选区（替换语义）
      if (!additive) {
        this.selectedPaths = []
        this.lastClickedPath = ''
        this.lastClickedNode = null
      }
      // 阻止默认文字选中
      event.preventDefault()
      window.addEventListener('mousemove', this._onBoxSelectMouseMove)
      window.addEventListener('mouseup', this._onBoxSelectMouseUp)
    },
    _onBoxSelectMouseMove(event) {
      if (!this.boxSelect.active) return
      const tree = this.$refs.treeListRef
      if (!tree) return
      const rect = tree.getBoundingClientRect()
      const x = Math.max(0, Math.min(event.clientX - rect.left + tree.scrollLeft, tree.scrollWidth))
      const y = Math.max(0, Math.min(event.clientY - rect.top + tree.scrollTop, tree.scrollHeight))
      const x1 = Math.min(this.boxSelect.anchorX, x)
      const y1 = Math.min(this.boxSelect.anchorY, y)
      const x2 = Math.max(this.boxSelect.anchorX, x)
      const y2 = Math.max(this.boxSelect.anchorY, y)
      // 矩形太小（< 4px）时不更新，避免抖动
      if (x2 - x1 < 4 && y2 - y1 < 4) return
      this.boxSelect = {
        ...this.boxSelect,
        x: x1, y: y1, width: x2 - x1, height: y2 - y1
      }
      this._updateBoxSelection()
    },
    /**
     * 把当前 boxSelect 矩形应用到选区 —— 遍历 .tree-list 内所有 [data-node-path] 行，
     * bbox 与矩形相交的全部加入 / 替换选区。
     */
    _updateBoxSelection() {
      const tree = this.$refs.treeListRef
      if (!tree) return
      const sel = this.boxSelect
      const sx = sel.x, sy = sel.y, sx2 = sel.x + sel.width, sy2 = sel.y + sel.height
      const nodeEls = tree.querySelectorAll('[data-node-path]')
      const hitPaths = []
      for (const el of nodeEls) {
        const path = el.getAttribute('data-node-path')
        if (!path) continue
        const r = el.getBoundingClientRect()
        const elLeft = r.left - tree.getBoundingClientRect().left + tree.scrollLeft
        const elTop = r.top - tree.getBoundingClientRect().top + tree.scrollTop
        const elRight = elLeft + r.width
        const elBottom = elTop + r.height
        // 矩形相交判定
        if (elRight < sx || elLeft > sx2 || elBottom < sy || elTop > sy2) continue
        hitPaths.push(path)
      }
      if (sel.additive) {
        // 累加：合并 _prevSelection + 当前命中
        const set = new Set(sel._prevSelection)
        for (const p of hitPaths) set.add(p)
        this.selectedPaths = Array.from(set)
      } else {
        // 替换
        this.selectedPaths = hitPaths
      }
    },
    _onBoxSelectMouseUp() {
      window.removeEventListener('mousemove', this._onBoxSelectMouseMove)
      window.removeEventListener('mouseup', this._onBoxSelectMouseUp)
      // 矩形太小（< 4px）当作点击空白：清空选区
      if (this.boxSelect.width < 4 && this.boxSelect.height < 4) {
        if (!this.boxSelect.additive) {
          this.selectedPaths = []
          this.lastClickedPath = ''
          this.lastClickedNode = null
        }
      } else {
        // 设 lastClicked = 第一个命中节点（让快捷键的 paste 能找到合理 target）
        const firstPath = this.selectedPaths[0]
        if (firstPath) {
          this.lastClickedPath = firstPath
          this.lastClickedNode = this._findNodeInTree(firstPath)
        }
      }
      this.boxSelect = {
        active: false,
        anchorX: 0, anchorY: 0, x: 0, y: 0, width: 0, height: 0, additive: false
      }
    },
    /**
     * 右键菜单触发：上下文 = 节点 → 该节点的相关操作；上下文 = 空白 → 新建/粘贴
     */
    onNodeContextMenu({ node, event }) {
      event.preventDefault()
      // 如果右键的节点不在当前选中集合里，把它加入（IDEA 行为：右键 = 选中该节点）
      if (node && node.path && !this.selectedPaths.includes(node.path)) {
        this.selectedPaths = [node.path]
        this.lastClickedPath = node.path
        this.lastClickedNode = node
      }
      this._showContextMenu(event.clientX, event.clientY, this._nodeMenuItems())
    },
    onTreeEmptyContextMenu(event) {
      // 点在 tree-list 空白处 → 不清空选区（与 onNodeContextMenu 一致：右键不破坏当前选择）
      // 这样空白右键也能继续操作已选中的节点（IDEA 风格：菜单项始终可用）
      event.preventDefault()
      this._showContextMenu(event.clientX, event.clientY, this._emptyMenuItems())
    },
    // ===== IDEA 风文件编辑 =====

    _showContextMenu(x, y, items) {
      this.contextMenu = { visible: true, x, y, items }
      // 用 nextTick 等 DOM 渲染后做边界检测，避免菜单超出右 / 下边缘
      this.$nextTick(() => this._adjustContextMenuPosition())
    },
    _adjustContextMenuPosition() {
      const el = this.$el.querySelector('.ctx-menu')
      if (!el) return
      const rect = el.getBoundingClientRect()
      const winW = window.innerWidth
      const winH = window.innerHeight
      let { x, y } = this.contextMenu
      if (x + rect.width > winW) x = winW - rect.width - 4
      if (y + rect.height > winH) y = winH - rect.height - 4
      if (x < 4) x = 4
      if (y < 4) y = 4
      this.contextMenu.x = x
      this.contextMenu.y = y
    },
    _hideContextMenu() {
      this.contextMenu.visible = false
    },
    _onDocumentClickCloseMenu() {
      // 仅当菜单显示时关闭（点击菜单项自己 stop 了 propagation，不会到这里）
      if (this.contextMenu.visible) this._hideContextMenu()
    },
    /**
     * 节点右键菜单项 —— 按选中数量与是否有剪贴板内容生成操作列表
     * 多选时：复制 / 剪切 / 删除 文案加 N 项；重命名 禁用（只对单选生效）
     * 单选时：完整操作集（rename / copy / cut / paste-into-if-dir / delete）
     */
    _nodeMenuItems() {
      const mod = this._isMac ? '⌘' : 'Ctrl+'
      const nodes = this.selectedNodes
      const single = this.lastClickedNode
      const isMulti = nodes.length > 1

      const items = []
      // 重命名：始终显示（多选 / 无选区时禁用 —— 灰色但可见，IDEA 风格）
      items.push({
        key: 'rename',
        label: '重命名',
        shortcut: 'F2',
        disabled: isMulti || !single || !single.path
      })
      // 复制 / 剪切：始终显示（无选区时禁用）
      items.push({
        key: 'copy',
        label: isMulti ? `复制 ${nodes.length} 项` : '复制',
        shortcut: mod + 'C',
        disabled: nodes.length === 0
      })
      items.push({
        key: 'cut',
        label: isMulti ? `剪切 ${nodes.length} 项` : '剪切',
        shortcut: mod + 'X',
        disabled: nodes.length === 0
      })
      // 粘贴：有剪贴板时显示 —— 单选 + 目录 → 「粘贴到 dirname」；其他 → 普通「粘贴」
      if (this.clipboard) {
        if (!isMulti && single && single.type === 'directory') {
          items.push({
            key: 'paste-into',
            label: `粘贴到「${single.name}」`,
            shortcut: mod + 'V'
          })
        } else {
          items.push({
            key: 'paste-here',
            label: '粘贴',
            shortcut: mod + 'V'
          })
        }
      }
      items.push({ key: '__divider__', label: '' })
      // 新建文件夹 / 新建文件：始终显示（多选 / 无选区时禁用 —— 灰色但可见）
      items.push({
        key: 'new-folder',
        label: '新建文件夹',
        disabled: isMulti || !single || !single.path
      })
      items.push({
        key: 'new-file',
        label: '新建文件',
        disabled: isMulti || !single || !single.path
      })
      items.push({ key: '__divider__', label: '' })
      // 删除：始终显示（无选区时禁用 —— danger 红 + 灰）
      items.push({
        key: 'delete',
        label: isMulti ? `删除 ${nodes.length} 项` : '删除',
        shortcut: 'Del',
        danger: true,
        disabled: nodes.length === 0
      })
      return items
    },
    _emptyMenuItems() {
      const mod = this._isMac ? '⌘' : 'Ctrl+'
      const nodes = this.selectedNodes
      const single = this.lastClickedNode
      const isMulti = nodes.length > 1

      const items = []
      // 重命名：始终显示（多选 / 无选区时禁用 —— 灰色但可见）
      items.push({
        key: 'rename',
        label: '重命名',
        shortcut: 'F2',
        disabled: isMulti || !single || !single.path
      })
      // 复制 / 剪切：始终显示（无选区时禁用）
      items.push({
        key: 'copy',
        label: isMulti ? `复制 ${nodes.length} 项` : '复制',
        shortcut: mod + 'C',
        disabled: nodes.length === 0
      })
      items.push({
        key: 'cut',
        label: isMulti ? `剪切 ${nodes.length} 项` : '剪切',
        shortcut: mod + 'X',
        disabled: nodes.length === 0
      })
      // 粘贴：有剪贴板时显示（粘贴到根）
      if (this.clipboard) {
        items.push({
          key: 'paste-here',
          label: '粘贴',
          shortcut: mod + 'V'
        })
      }
      items.push({ key: '__divider__', label: '' })
      // 新建文件夹 / 新建文件：始终启用（空白右键 → 根目录）
      items.push({ key: 'new-folder', label: '新建文件夹' })
      items.push({ key: 'new-file', label: '新建文件' })
      items.push({ key: '__divider__', label: '' })
      // 删除：始终显示（无选区时禁用 —— danger 红 + 灰）
      items.push({
        key: 'delete',
        label: isMulti ? `删除 ${nodes.length} 项` : '删除',
        shortcut: 'Del',
        danger: true,
        disabled: nodes.length === 0
      })
      items.push({ key: '__divider__', label: '' })
      // 刷新（始终启用）
      items.push({
        key: 'refresh',
        label: '刷新',
        shortcut: 'F5'
      })
      return items
    },
    async onContextMenuAction(key) {
      this._hideContextMenu()
      if (key === '__divider__') return
      const nodes = this.selectedNodes
      const single = this.lastClickedNode
      switch (key) {
        case 'copy':
          if (nodes.length) this.copySelected(nodes)
          break
        case 'cut':
          if (nodes.length) this.cutSelected(nodes)
          break
        case 'paste-into':
        case 'paste-here':
          this.pasteInto(single)
          break
        case 'rename':
          if (single && single.path) this.renameTargetPath = single.path
          break
        case 'delete':
          // 批量删除走 _batchDeleteSelected（弹一次确认 → 调后端批量端点）
          if (nodes.length) this._batchDeleteSelected(nodes)
          break
        case 'new-folder':
        case 'new-file':
          this.openNewItemDialog(key === 'new-folder' ? 'folder' : 'file', single)
          break
        case 'refresh':
          this.checkFiles()
          break
      }
    },
    /** 把选中节点复制到剪贴板（支持多选：clipboard 存 srcs 数组） */
    copySelected(nodes) {
      const list = Array.isArray(nodes) ? nodes : [nodes]
      const items = list
        .filter(n => n && n && n.path)
        .map(n => ({
          src: this._extractRelativePath(n.path),
          name: n.name
        }))
      if (!items.length) return
      this.clipboard = {
        items,
        mode: 'copy',
        // 兼容单条 src（单选时）—— 取第一项，方便 pasteInto 单条路径场景
        src: items[0].src,
        name: items[0].name,
        // 跨会话防御：切到别的会话再粘贴时，_shortcutPaste 会检测 sessionId 不一致并清空剪贴板
        sessionId: this.activeSessionId
        // 默认粘贴位置永远是 sid/ 根目录（不再记录 srcDir）—— 用户偏好：
        // 复制 foo.txt 后直接 Cmd+V / 空白右键粘贴，副本应回到 sid/ 根目录
      }
    },
    /** 剪切（支持多选） */
    cutSelected(nodes) {
      const list = Array.isArray(nodes) ? nodes : [nodes]
      const items = list
        .filter(n => n && n.path)
        .map(n => ({
          src: this._extractRelativePath(n.path),
          name: n.name
        }))
      if (!items.length) return
      this.clipboard = {
        items,
        mode: 'cut',
        src: items[0].src,
        name: items[0].name,
        sessionId: this.activeSessionId
      }
    },
    /**
     * 粘贴（Cmd+V / 右键粘贴）：target 是目录时粘到 target 内部，否则默认到 sid/ 根目录。
     * 真正的批量 / 单条 / self-paste / flash 反馈全部委托给 _batchCopyToDir。
     * cut 模式成功后清空剪贴板 + 选区。
     */
    async pasteInto(targetNode) {
      if (!this.clipboard || !this.activeSessionId) return
      const items = this.clipboard.items || [{ src: this.clipboard.src, name: this.clipboard.name }]
      const srcs = items.map(i => i.src).filter(Boolean)
      if (!srcs.length) return
      let dstDir = (targetNode && targetNode.type === 'directory')
        ? this._extractRelativePath(targetNode.path) : ''
      // Self-paste 静默回退：任何一个 src 是目录且 dstDir 是其自身/子目录时，
      // 把整批重定向到根目录 —— 不再弹「不能把 X 复制到自身内部」红色警告。
      // 用户真要粘到子目录：换到那个目录右键 → 「粘贴到 <dirname>」即可。
      if (dstDir && srcs.some(src => this._isSelfPaste(src, dstDir))) {
        dstDir = ''
      }
      const wasCut = this.clipboard.mode === 'cut'
      const result = await this._batchCopyToDir(srcs, dstDir, { mode: this.clipboard.mode })
      if (!result.ok) return
      if (wasCut) {
        // cut 成功 → 源已被移走，清剪贴板 + 选区，避免再次粘贴误删
        this.clipboard = null
        this.selectedPaths = []
        this.lastClickedPath = ''
        this.lastClickedNode = null
      }
    },
    /**
     * 批量复制 / 移动到指定目录 —— Cmd+V 粘贴 + Cmd+D 复制副本共用底座（drag-drop 未来也能用）。
     * - mode: 'copy' | 'cut'（'cut' = move）
     * - 单条 vs 批量：srcs.length === 1 → `/file/{op}`；否则 `/files/{op}`
     * - auto_rename=true：目标已存在时后端自动追加 (1)/(2)... 而不是 409
     * - 客户端预校验 self-paste（src 是目录 AND dstDir 是 src 自身 / 子目录）→ 静默 return
     *   （`pasteInto` 已经提前重定向到根目录，这里只是防御兜底 —— 给未来 drag-drop 等
     *    入口一个安全网，避免递归复制打到后端）
     * - 返回 { ok, renamedCount } —— ok=false 表示未发送请求或请求失败，调用方不应再做事
     */
    async _batchCopyToDir(srcs, dstDir, { mode = 'copy' } = {}) {
      if (!this.activeSessionId || !srcs.length) return { ok: false }
      // self-paste 预校验（防御兜底，静默拦截，不弹红色警告）
      for (const src of srcs) {
        if (this._isSelfPaste(src, dstDir)) return { ok: false }
      }
      const isBatch = srcs.length > 1
      const op = mode === 'cut' ? 'move' : 'copy'
      const url = isBatch
        ? `/chat/${encodeURIComponent(this.activeSessionId)}/files/${op}`
        : `/chat/${encodeURIComponent(this.activeSessionId)}/file/${op}`
      const body = isBatch
        ? { srcs, dst_dir: dstDir, auto_rename: true }
        : { src: srcs[0], dst_dir: dstDir, auto_rename: true }
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        })
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}))
          this._flash(`${op === 'copy' ? '复制' : '移动'}失败：${detail.detail || resp.statusText}`, 'error')
          return { ok: false }
        }
        const result = await resp.json().catch(() => ({}))
        // 批量部分失败：failures 非空 + removed > 0 → 提示具体哪些失败
        if (isBatch && result.failures && result.failures.length && (result.removed || 0) > 0) {
          const first = result.failures[0]
          this._flash(
            `${op === 'copy' ? '复制' : '移动'}部分失败：${result.removed} 成功，${result.skipped} 跳过（${this._basename(first.src)}：${first.reason}）`,
            'error'
          )
        } else if (isBatch && result.failures && result.failures.length) {
          const first = result.failures[0]
          this._flash(`${op === 'copy' ? '复制' : '移动'}失败：${this._basename(first.src)}：${first.reason}`, 'error')
          return { ok: false }
        }
        // 成功统计
        let renamedCount = 0
        if (isBatch) {
          renamedCount = (result.successes || []).filter(s => s && s.renamed).length
        } else if (result.renamed) {
          renamedCount = 1
        }
        const verb = op === 'copy' ? '复制' : '移动'
        const msg = isBatch
          ? `已${verb} ${srcs.length} 项${renamedCount > 0 ? `（${renamedCount} 项自动改名）` : ''}`
          : (renamedCount > 0 ? `已${verb}为「${this._basename(result.dst)}」` : `已${verb}`)
        await this.checkFiles()
        this._flash(msg, 'success')
        return { ok: true, renamedCount }
      } catch (e) {
        console.error(`[Sidebar] ${op} failed:`, e)
        this._flash(`${op === 'copy' ? '复制' : '移动'}失败：${e.message || e}`, 'error')
        return { ok: false }
      }
    },
    async _execFileOp(op, body) {
      // 单条文件操作 fallback（用于 rename / 单条 copy/move 罕见场景）
      const url = `/chat/${encodeURIComponent(this.activeSessionId)}/file/${op}`
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        })
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}))
          this._flash(`${op} 失败：${detail.detail || resp.statusText}`, 'error')
          return
        }
        await this.checkFiles()
      } catch (e) {
        console.error(`[Sidebar] ${op} failed:`, e)
        this._flash(`${op} 失败：${e.message || e}`, 'error')
      }
    },
    /**
     * 批量软删除多选节点（右键 / Delete 键 → ConfirmDialog → POST /files/soft-delete）。
     * 单条路径走原生 DELETE /file，多条走 batch endpoint。
     */
    _batchDeleteSelected(nodes) {
      if (!nodes || !nodes.length) return
      const rels = nodes
        .map(n => this._extractRelativePath(n.path))
        .filter(Boolean)
      if (!rels.length) return
      const message = rels.length === 1
        ? `确认将「${nodes[0].name}」软删除到回收站？\n（每天 11:30 自动清理，可恢复）`
        : `确认将选中的 ${rels.length} 个文件 / 目录软删除到回收站？\n（每天 11:30 自动清理，可恢复）`
      this._pendingBulkDeletePaths = rels
      this._pendingBulkDeleteMessage = message
      this.showBulkSoftDeleteDialog = true
    },
    async _doBatchDelete(paths) {
      if (!paths || !paths.length || !this.activeSessionId) return
      try {
        const resp = await fetch(`/chat/${encodeURIComponent(this.activeSessionId)}/files/soft-delete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_paths: paths })
        })
        const result = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this._flash(`批量删除失败：${result.detail || resp.statusText}`, 'error')
          return
        }
        if ((result.skipped || 0) > 0 && result.failures && result.failures.length) {
          console.warn('[Sidebar] batch delete skipped:', result.failures)
          const first = result.failures[0]
          this._flash(`部分跳过：${result.removed} 成功，${result.skipped} 跳过（${this._basename(first.path)}：${first.reason}）`, 'error')
          return  // 有失败就不算完全成功，不闪 success
        }
        // 清空选区（已删的节点不再存在）
        this.selectedPaths = []
        this.lastClickedPath = ''
        this.lastClickedNode = null
        await this.checkFiles()
        if (this.filesActiveTab === 'trash') {
          await this.checkTrash()
        }
        this._flash(`已软删除 ${paths.length} 项`, 'success')
      } catch (e) {
        console.error('[Sidebar] batch delete failed:', e)
        this._flash(`批量删除失败：${e.message || e}`, 'error')
      }
    },
    /** 重命名提交：POST /file/rename */
    async onFileRename({ node, newName }) {
      if (!this.activeSessionId || !node || !node.path) return
      const src = this._extractRelativePath(node.path)
      try {
        const resp = await fetch(`/chat/${encodeURIComponent(this.activeSessionId)}/file/rename`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ src, new_name: newName })
        })
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}))
          this._flash(`重命名失败：${detail.detail || resp.statusText}`, 'error')
          return
        }
        await this.checkFiles()
        this._flash(`已重命名为「${newName}」`, 'success')
      } catch (e) {
        console.error('[Sidebar] rename failed:', e)
        this._flash(`重命名失败：${e.message || e}`, 'error')
      }
    },
    onRenameDone() {
      this.renameTargetPath = ''
    },
    /** 打开新建文件夹/文件弹窗 */
    openNewItemDialog(kind, targetNode) {
      let parent = ''
      if (targetNode && targetNode.type === 'directory') {
        // 目录节点 → 创建在内部
        parent = this._extractRelativePath(targetNode.path)
      } else if (targetNode && targetNode.type === 'file') {
        // 文件节点 → 创建在父目录（同级）
        const parentDir = this._findParentInTree(targetNode)
        parent = parentDir ? this._extractRelativePath(parentDir.path) : ''
      }
      // 无 target / 父目录解析失败 → 根
      this.newItemDialog = { visible: true, kind, parent, name: '' }
      this.$nextTick(() => {
        const input = this.$refs.newItemInput
        if (input) input.focus()
      })
    },
    closeNewItemDialog() {
      this.newItemDialog.visible = false
      this.newItemDialog.creating = false
      this.newItemDialog.name = ''
    },
    async confirmNewItem() {
      if (this.newItemDialog.creating) return  // 防双击
      const { kind, parent, name } = this.newItemDialog
      const trimmed = (name || '').trim()
      if (!trimmed) return
      // —— 前端预校验：parent 必须在树里实际存在 —— 避免把 stale 路径（如 (1) (1) (1) 后缀的旧名）
      // 发到后端才被拦，且错误信息里直接回显 path 给用户造成「文件名错乱」困惑。
      // parent === '' 表示根目录，永远合法。
      let safeParent = parent
      if (safeParent && !this._nodePathExists(safeParent)) {
        // 自动回退到根目录 + flash 提示用户「原位置已失效」
        this._flash(`目标「${safeParent}」已不存在，自动改在根目录创建`, 'info')
        safeParent = ''
        this.newItemDialog.parent = ''  // 同步弹窗里的提示
      }
      this.newItemDialog.creating = true
      const url = kind === 'folder'
        ? `/chat/${encodeURIComponent(this.activeSessionId)}/folder`
        : `/chat/${encodeURIComponent(this.activeSessionId)}/file`
      const body = kind === 'folder'
        ? { parent: safeParent, name: trimmed }
        : { parent: safeParent, name: trimmed, content: '' }
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        })
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}))
          this._flash(`创建失败：${this._humanizeCreateError(detail.detail) || resp.statusText}`, 'error')
          return
        }
        this.closeNewItemDialog()
        await this.checkFiles()
        this._flash(`已创建「${trimmed}」`, 'success')
      } catch (e) {
        console.error('[Sidebar] create failed:', e)
        this._flash(`创建失败：${e.message || e}`, 'error')
      } finally {
        this.newItemDialog.creating = false
      }
    },
    /**
     * 把后端 detail（如「父目录不存在或不是目录: ecommerce_customers (1) (1) (1).csv_254b」）
     * 翻译成用户友好的中文，剥离原始路径避免回显陈旧/奇怪的文件名。
     */
    _humanizeCreateError(detail) {
      if (!detail) return ''
      const s = String(detail)
      if (s.includes('父目录不存在') || s.includes('不是目录')) return '目标位置已不存在或不是目录'
      if (s.includes('目标已存在') || s.includes('已存在同名')) return '已存在同名文件/文件夹'
      if (s.includes('name 必须')) return '名称不能为空或含路径分隔符'
      if (s.includes('路径必须为相对路径') || s.includes('路径含非法') || s.includes('路径越界')) return '目标路径不合法'
      if (s.includes('非法 sid')) return '会话 ID 非法'
      // 兜底：剥离冒号后面的具体路径，只保留前缀（避免回显奇怪的 (1) (1) (1) 后缀名）
      const colonIdx = s.indexOf(':')
      if (colonIdx > 0 && colonIdx < 20) return s.slice(0, colonIdx).trim()
      return s
    },
    /**
     * 检查某个相对路径（如 `data/sub` 或空字符串=根）在当前树里实际存在
     */
    _nodePathExists(relPath) {
      if (!relPath) return true  // 空 = 根
      if (!this.rootNode) return false
      const parts = relPath.split('/').filter(Boolean)
      let current = this.rootNode
      for (const part of parts) {
        if (!current.children) return false
        const next = current.children.find(c => c.name === part && c.type === 'directory')
        if (!next) return false
        current = next
      }
      return true
    },
    /**
     * 全局键盘快捷键 —— Finder / Explorer 风格 + 平台差异适配。
     *
     * 完整快捷键表：
     * | 操作           | Mac              | Win                  | 反馈约定                              |
     * | 新建文件夹     | Cmd+Shift+N      | Ctrl+Shift+N         | 总是开弹窗                            |
     * | 新建文件       | Cmd+Shift+Alt+N  | Ctrl+Shift+Alt+N     | 总是开弹窗                            |
     * | 全选           | Cmd+A            | Ctrl+A               | 总是生效 + flash 成功提示             |
     * | 复制           | Cmd+C            | Ctrl+C               | 无选区 → flash 提示「请先选中」       |
     * | 剪切           | Cmd+X            | Ctrl+X               | 无选区 → flash 提示                   |
     * | 粘贴           | Cmd+V            | Ctrl+V               | 剪贴板空 → flash 提示                 |
     * | 复制副本       | Cmd+D            | Ctrl+D               | 跨父目录选 → flash 提示               |
     * | 删除（软）     | Cmd+Backspace / Cmd+Delete | Delete / Shift+Delete  | 无选区 → flash 提示            |
     * | 重命名         | F2               | F2                   | 无选区 → flash 提示                   |
     * | 打开/折叠      | Enter            | Enter                | 无选区 → flash 提示                   |
     * | 快速预览       | Space            | —                    | 目录/无选区 静默                      |
     * | 刷新           | F5               | F5                   | 总是生效                              |
     * | 清选/取消      | Esc              | Esc                  | 清 selectedPaths + 关菜单/对话框       |
     * | 箭头导航       | ↑↓←→             | 同                   | 总是生效（Shift 范围选）              |
     *
     * 输入框 / textarea / contentEditable focus 时不抢键（用户在重命名/搜索时按方向键不应触发导航）。
     */
    onGlobalKeydown(e) {
      if (!this._shortcutGuard(e)) return
      const mod = this._isMac ? e.metaKey : e.ctrlKey

      // —— 全局 always-on ——
      if (mod && e.shiftKey && e.altKey && /^n$/i.test(e.key)) {
        e.preventDefault(); return this._shortcutNewFile()
      }
      if (mod && e.shiftKey && !e.altKey && /^n$/i.test(e.key)) {
        e.preventDefault(); return this._shortcutNewFolder()
      }
      if (!mod && e.key === 'Escape') {
        e.preventDefault(); return this._shortcutEscape()
      }
      if (!mod && e.key === 'F5') {
        e.preventDefault(); return this.reloadFiles()
      }
      if (mod && /^a$/i.test(e.key) && !e.shiftKey && !e.altKey) {
        e.preventDefault()
        this.selectAll()
        return this._flash(`已全选 ${this.selectedPaths.length} 项`, 'info')
      }

      // —— 同步 lastClickedNode / 拿到当前选区 ——
      const { nodes, single } = this._effectiveSelection()

      // —— 剪贴板操作（Cmd/Ctrl + 单字母，不带 Shift/Alt）——
      if (mod && !e.shiftKey && !e.altKey) {
        if (/^c$/i.test(e.key)) { e.preventDefault(); return this._shortcutCopy(nodes) }
        if (/^x$/i.test(e.key)) { e.preventDefault(); return this._shortcutCut(nodes) }
        if (/^v$/i.test(e.key)) { e.preventDefault(); return this._shortcutPaste() }
        if (/^d$/i.test(e.key)) { e.preventDefault(); return this._shortcutDuplicate(nodes) }
      }

      // —— 编辑 / 删除（无 modifier）——
      if (this._isDeleteKey(e, mod)) {
        e.preventDefault(); return this._shortcutDelete(nodes)
      }
      if (!mod && e.key === 'F2') {
        e.preventDefault(); return this._shortcutRename(single)
      }
      if (!mod && e.key === 'Enter') {
        e.preventDefault(); return this._shortcutEnter(single)
      }
      if (this._isMac && !mod && e.key === ' ') {
        e.preventDefault(); return this._shortcutQuickLook(single)
      }

      // —— 箭头键 → 节点导航（Shift + 箭头 → 范围选）——
      if (!mod && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        e.preventDefault(); return this._navigateWithArrow(e.key, e.shiftKey)
      }
    },
    /**
     * 守卫：仅在文件视图 + 当前会话 + 「files」tab（不是 trash）下响应快捷键，
     * 且 focus 不在输入框 / textarea / contentEditable 里。
     */
    _shortcutGuard(e) {
      if (this.activeView !== 'files' || !this.activeSessionId) return false
      if (this.filesActiveTab !== 'files') return false
      const tag = (e.target && e.target.tagName) || ''
      if (tag === 'INPUT' || tag === 'TEXTAREA') return false
      if (e.target && e.target.isContentEditable) return false
      return true
    },
    /**
     * 拿当前生效的选区节点数组 + 单节点（用于 Enter / F2 / Duplicate 等单选依赖）。
     * 同步 lastClickedNode —— Shift+click 范围选后状态可能分裂；
     * 如果 lastClickedNode 为 null 但 selectedPaths 非空，回填第一个节点。
     */
    _effectiveSelection() {
      let single = this.lastClickedNode
      if (!single && this.selectedPaths.length) {
        single = this.selectedNodes[0] || null
        if (single) this.lastClickedNode = single
      }
      return { nodes: this.selectedNodes, single }
    },
    /**
     * 平台差异集中在一处 —— Mac Finder vs Win Explorer 的删除键。
     * - Mac：Cmd+Backspace / Cmd+Delete 都算删除（Finder 习惯，forward-delete 也接受）
     * - Mac：单独 Backspace（无 Cmd）→ 不响应（让浏览器处理 —— 否则会误删页面）
     * - Win：Delete 主键（Explorer 习惯），Shift+Delete 作为别名（Explorer 原意是永久删除
     *        绕过回收站，但本项目只有软删 .trash/ 概念，所以 Shift+Delete 也走软删路径）
     * - Win：Backspace **不算**删除键（Explorer 里是「返回上一级目录」语义，不是删除）
     */
    _isDeleteKey(e, mod) {
      if (e.key === 'Delete') {
        // Mac: 无 mod 也接受 forward-delete；Win: 必须无 mod（Cmd/Ctrl+Delete 不响应）
        return !mod || this._isMac
      }
      if (e.key === 'Backspace' && mod && this._isMac) return true   // Mac Cmd+Backspace
      if (!this._isMac && e.key === 'Delete' && e.shiftKey) return true  // Win Shift+Delete 别名
      return false
    },
    _shortcutCopy(nodes) {
      if (!nodes.length) return this._flash('请先选中要复制的文件或文件夹', 'info')
      this.copySelected(nodes)
      this._flash(`已复制 ${nodes.length} 项到剪贴板`, 'info')
    },
    _shortcutCut(nodes) {
      if (!nodes.length) return this._flash('请先选中要剪切的文件或文件夹', 'info')
      this.cutSelected(nodes)
      this._flash(`已剪切 ${nodes.length} 项（粘贴后源会被移除）`, 'info')
    },
    /**
     * Cmd+V：跨会话防御 + **永远默认到 sid/ 根目录**
     *
     * 不管 lastClickedNode 是文件 / 目录 / 空，都走根 —— 用户复制了「和 lastClickedNode
     * 同名的目录」时若粘进 lastClickedNode 会触发 `_isSelfPaste` 报错（例如复制 `data/`
     * 后点击 `data/` 节点，再 Cmd+V → 不能把 `data` 复制到自身内部），违背快捷键预期。
     * 真要粘到子目录必须显式右键目录 → 「粘贴到 <dirname>」。
     */
    _shortcutPaste() {
      if (!this.clipboard) return this._flash('剪贴板为空，先按 Cmd+C 复制文件', 'info')
      if (this.clipboard.sessionId && this.clipboard.sessionId !== this.activeSessionId) {
        this.clipboard = null
        return this._flash('剪贴板属于其他会话，已清空', 'info')
      }
      this.pasteInto(null)
    },
    /**
     * Cmd+D (Duplicate) —— 在同一父目录下复制副本（auto_rename 自动追加 (1)/(2)）。
     * 跨父目录多选 → 拒绝 + flash 提示，避免「不同目录的 (1) 副本」语义不清。
     */
    _shortcutDuplicate(nodes) {
      if (!nodes.length) return this._flash('请先选中要复制副本的文件或文件夹', 'info')
      const parentDirs = new Set(nodes.map(n => {
        const rel = this._extractRelativePath(n.path)
        return rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : ''
      }))
      if (parentDirs.size > 1) {
        return this._flash('复制副本要求所有选中项在同一目录下', 'error')
      }
      const dstDir = [...parentDirs][0]
      const srcs = nodes.map(n => this._extractRelativePath(n.path)).filter(Boolean)
      this._batchCopyToDir(srcs, dstDir, { mode: 'copy' })
    },
    _shortcutDelete(nodes) {
      if (!nodes.length) return this._flash('请先选中要删除的文件或文件夹', 'info')
      if (nodes.length === 1) this._directDelete(nodes[0])
      else this._batchDeleteSelected(nodes)
    },
    _shortcutRename(single) {
      if (!single || !single.path) return this._flash('请先选中要重命名的文件或文件夹', 'info')
      this.renameTargetPath = single.path
    },
    /** Enter 快捷键（Finder / Explorer 通用）：目录切换展开；文件触发预览 */
    _shortcutEnter(single) {
      if (!single || !single.path) return this._flash('请先选中文件或文件夹', 'info')
      if (single.type === 'directory') {
        const isExpanded = !!this.expandedPaths[single.path]
        this.onNodeToggleExpand({ node: single, expanded: !isExpanded })
      } else {
        this.onFileClick(single)
      }
    },
    /** Mac Finder 习惯：Space = 快速预览（仅文件；目录/无选区静默不打扰用户） */
    _shortcutQuickLook(single) {
      if (!single || single.type !== 'file' || !single.path) return
      this.onFileClick(single)
    },
    _shortcutNewFolder() { this.openNewItemDialog('folder', this.lastClickedNode) },
    _shortcutNewFile()   { this.openNewItemDialog('file',   this.lastClickedNode) },
    /** Esc 状态机：右键菜单 → 关菜单 → 新建对话框 → 关对话框 → 重命名 → 退出重命名 → 选区清空 */
    _shortcutEscape() {
      if (this.contextMenu && this.contextMenu.visible) return this._hideContextMenu()
      if (this.newItemDialog && this.newItemDialog.visible) return this.closeNewItemDialog()
      if (this.renameTargetPath) { this.renameTargetPath = ''; return }
      if (this.selectedPaths.length) {
        this.selectedPaths = []
        this.lastClickedPath = ''
        this.lastClickedNode = null
      }
    },
    /**
     * 箭头键导航（Finder / Explorer 通用）：
     * - ArrowDown / ArrowUp：移动到下一个 / 上一个可见节点
     * - ArrowRight：目录未展开 → 展开；已展开 → 跳到首子；文件 → 跳下一个
     * - ArrowLeft：目录已展开 → 折叠；未展开 / 文件 → 跳到父目录
     * - Shift + 箭头：以 lastClickedPath 为锚点做范围选
     * - 滚动到可见区域（scrollIntoView block: nearest）
     */
    _navigateWithArrow(key, shiftKey) {
      const visible = this._flattenVisibleNodes(this.rootNode || { children: [] })
      if (!visible.length) return
      const single = this.lastClickedNode
      const curIdx = single ? visible.findIndex(n => n.path === single.path) : -1

      let nextIdx = curIdx
      let handled = false

      if (key === 'ArrowDown') {
        nextIdx = curIdx < 0 ? 0 : Math.min(curIdx + 1, visible.length - 1)
      } else if (key === 'ArrowUp') {
        nextIdx = curIdx < 0 ? 0 : Math.max(curIdx - 1, 0)
      } else if (key === 'ArrowRight') {
        if (single && single.type === 'directory' && !this.expandedPaths[single.path]) {
          // 目录未展开 → 展开
          this.onNodeToggleExpand({ node: single, expanded: true })
          handled = true
        } else if (single && single.type === 'directory' && this.expandedPaths[single.path]) {
          // 已展开 → 跳到首子（_flattenVisibleNodes 把展开的子节点排在父后）
          nextIdx = curIdx + 1
        } else {
          // 文件 → 下一个
          nextIdx = curIdx < 0 ? 0 : Math.min(curIdx + 1, visible.length - 1)
        }
      } else if (key === 'ArrowLeft') {
        if (single && single.type === 'directory' && this.expandedPaths[single.path]) {
          // 已展开 → 折叠
          this.onNodeToggleExpand({ node: single, expanded: false })
          handled = true
        } else if (single) {
          // 跳到父目录
          const parent = this._findParentInTree(single)
          if (parent) {
            const parentIdx = visible.findIndex(n => n.path === parent.path)
            if (parentIdx >= 0) nextIdx = parentIdx
          }
        }
      }

      if (handled) return

      if (nextIdx < 0 || nextIdx >= visible.length) return
      const next = visible[nextIdx]
      if (shiftKey && this.lastClickedPath) {
        // Shift + 箭头 → 范围选（以 lastClickedPath 为锚点）
        const anchorIdx = visible.findIndex(n => n.path === this.lastClickedPath)
        if (anchorIdx >= 0) {
          const lo = Math.min(anchorIdx, nextIdx)
          const hi = Math.max(anchorIdx, nextIdx)
          this.selectedPaths = visible.slice(lo, hi + 1).map(n => n.path)
        } else {
          this.selectedPaths = [next.path]
          this.lastClickedPath = next.path
          this.lastClickedNode = next
        }
        // Shift 范围选时不滚动（保持原始锚点可见即可）
        this._scrollNodeIntoView(next.path, /* smooth */ false)
      } else {
        // 普通箭头 → 单选替换
        this.selectedPaths = [next.path]
        this.lastClickedPath = next.path
        this.lastClickedNode = next
        this._scrollNodeIntoView(next.path, /* smooth */ true)
      }
    },
    /** 滚动指定 path 的节点到可见区域（block: nearest 不破坏当前滚动位置） */
    _scrollNodeIntoView(path, smooth = true) {
      if (!path) return
      const tree = this.$refs.treeListRef
      if (!tree) return
      // CSS.escape 处理 path 里可能含的特殊字符（虽然 hex sid + 路径应该没有，但保险起见）
      let el
      try {
        el = tree.querySelector(`[data-node-path="${CSS.escape(path)}"]`)
      } catch (e) {
        el = null
      }
      if (el && el.scrollIntoView) {
        el.scrollIntoView({ block: 'nearest', behavior: smooth ? 'smooth' : 'auto' })
      }
    },
    /** 跳过 DataTreeNode × 二次确认态，直接通过 API 删除（键盘 Delete 单条触发） */
    async _directDelete(node) {
      if (!this.activeSessionId || !node || !node.path) return
      const relPath = this._extractRelativePath(node.path)
      if (!relPath) return
      try {
        const resp = await fetch(`/chat/${encodeURIComponent(this.activeSessionId)}/file?file_path=${encodeURIComponent(relPath)}`, { method: 'DELETE' })
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}))
          this._flash(`删除失败：${detail.detail || resp.statusText}`, 'error')
          return
        }
        this.selectedPaths = []
        this.lastClickedPath = ''
        this.lastClickedNode = null
        this.checkFiles()
        this._flash(`已删除「${this._basename(relPath)}」`, 'success')
      } catch (e) {
        console.error('[Sidebar] delete failed:', e)
        this._flash(`删除失败：${e.message || e}`, 'error')
      }
    },
    /** 在文件树中按完整绝对路径找节点（DFS）—— 用于预校验 self-paste / conflict */
    _findNodeInTree(absolutePath) {
      if (!this.rootNode || !absolutePath) return null
      const findIn = (n) => {
        if (!n) return null
        if (n.path === absolutePath) return n
        if (n.children) {
          for (const c of n.children) {
            const r = findIn(c)
            if (r) return r
          }
        }
        return null
      }
      return findIn(this.rootNode)
    },
    /**
     * 自粘贴预校验：src 是目录 AND dstDir 是 src 自身或其后代目录
     * → 后端 copy_file / move_file 会返回 400「不能把目录复制到自身子目录」
     * 客户端拦截避免发无效请求 + 用户看到 alert
     */
    _isSelfPaste(srcRelPath, dstDir) {
      if (!srcRelPath || !dstDir) return false
      // 源必须是目录（文件 self-paste 无意义）
      const basePrefix = this.rootPath.endsWith('/') ? this.rootPath : this.rootPath + '/'
      const srcNode = this._findNodeInTree(basePrefix + srcRelPath)
      if (!srcNode || srcNode.type !== 'directory') return false
      // 顶层目录（无 /）粘贴到根 → 不算 self-paste（视为合法的「移回根」操作）
      if (!srcRelPath.includes('/') && !dstDir) return false
      const srcAsDir = srcRelPath.endsWith('/') ? srcRelPath : srcRelPath + '/'
      return dstDir === srcRelPath || dstDir.startsWith(srcAsDir)
    },
    // _parentDirRelative 已删除 —— 默认粘贴永远是 sid/ 根目录，不再需要记录源父目录
    /** 命名冲突预校验：完整相对路径是否已存在于树中（避免 409 错误） */
    _pathExistsInTree(relPath) {
      if (!this.rootNode || !relPath) return false
      const fullPath = this.rootPath + (this.rootPath.endsWith('/') ? '' : '/') + relPath
      return !!this._findNodeInTree(fullPath)
    },
    /** 在文件树中找节点的父目录节点（用于粘贴到同级目录） */
    _findParentInTree(node) {
      if (!node || !node.path || !this.rootNode || !this.rootNode.children) return null
      // 文件 path = "cached/{sid}/parent_dir/file"，剥去末段就是父 path
      const parts = node.path.split('/')
      parts.pop()
      const parentPath = parts.join('/')
      const findIn = (n) => {
        if (!n || !n.children) return null
        for (const c of n.children) {
          if (c.path === parentPath) return c
          if (c.type === 'directory') {
            const found = findIn(c)
            if (found) return found
          }
        }
        return null
      }
      return findIn(this.rootNode)
    },
    async onFileDelete(node) {
      if (!this.activeSessionId || !node || !node.path) return
      const relPath = this._extractRelativePath(node.path)
      if (!relPath) {
        console.error('[Sidebar] file delete failed: relPath parse error for', node.path)
        return
      }
      try {
        const url = `/chat/${encodeURIComponent(this.activeSessionId)}/file?file_path=${encodeURIComponent(relPath)}`
        const resp = await fetch(url, { method: 'DELETE' })
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}))
          this._flash(`删除失败：${detail.detail || resp.statusText}`, 'error')
          return
        }
        this.checkFiles()
        this._flash(`已删除「${this._basename(relPath)}」`, 'success')
      } catch (e) {
        console.error('[Sidebar] file delete failed:', e)
        this._flash(`删除失败：${e.message || e}`, 'error')
      }
    },
    _extractRelativePath(absolutePath) {
      const basePrefix = this.rootPath.endsWith('/') ? this.rootPath : this.rootPath + '/'
      if (absolutePath.startsWith(basePrefix)) {
        return absolutePath.slice(basePrefix.length)
      }
      return absolutePath.split('/').pop()
    },
    /** 取路径最后一段（basename），用于 flash 文案 */
    _basename(p) {
      if (!p) return ''
      const s = String(p)
      const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'))
      return i >= 0 ? s.slice(i + 1) : s
    },
    onTrashItemDeleteClick(item) {
      if (!item || !item.trash_path) return
      this.deleteTrashItem(item)
    },
    async deleteTrashItem(item) {
      if (!this.activeSessionId || !item || !item.trash_path) return
      const path = item.trash_path
      this.itemBusy[path] = true
      try {
        const url = `/chat/${encodeURIComponent(this.activeSessionId)}/trash/item?trash_path=${encodeURIComponent(path)}`
        const resp = await fetch(url, { method: 'DELETE' })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this._flash(`永久删除失败：${data.detail || resp.statusText}`, 'error')
          return
        }
        await this.checkTrash()
        this._flash('已永久删除', 'success')
      } catch (e) {
        console.error('[Sidebar] deleteTrashItem failed:', e)
        this._flash(`永久删除失败：${e.message || e}`, 'error')
      } finally {
        this.itemBusy[path] = false
      }
    },
    async onRestoreTrashItem(item) {
      if (!this.activeSessionId || !item || !item.trash_path) return
      const path = item.trash_path
      this.itemBusy[path] = true
      try {
        const resp = await fetch(`/chat/${encodeURIComponent(this.activeSessionId)}/trash/restore`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ trash_path: path })
        })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          if (resp.status === 409) {
            // 409 在 UI 上一行已经够明显 —— 简短提示，详情进 console
            this._flash('恢复失败：目标位置已有同名文件', 'error')
            console.warn('[Sidebar] restore 409:', data.detail)
          } else {
            this._flash(`恢复失败：${data.detail || resp.statusText}`, 'error')
          }
          return
        }
        await this.checkTrash()
        this.checkFiles()
        this._flash('已恢复', 'success')
      } catch (e) {
        console.error('[Sidebar] onRestoreTrashItem failed:', e)
        this._flash(`恢复失败：${e.message || e}`, 'error')
      } finally {
        this.itemBusy[path] = false
      }
    },
    async onTrashFolderDelete(node) {
      if (!node || !node.fullPath) return
      await this.deleteTrashFolder(node.fullPath)
    },
    async deleteTrashFolder(pathPrefix) {
      if (!this.activeSessionId || !pathPrefix) return
      this.folderDeleting[pathPrefix] = true
      try {
        const url = `/chat/${encodeURIComponent(this.activeSessionId)}/trash/folder?path_prefix=${encodeURIComponent(pathPrefix)}`
        const resp = await fetch(url, { method: 'DELETE' })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this._flash(`批量删除失败：${data.detail || resp.statusText}`, 'error')
          return
        }
        await this.checkTrash()
        this._flash('已批量删除', 'success')
      } catch (e) {
        console.error('[Sidebar] deleteTrashFolder failed:', e)
        this._flash(`批量删除失败：${e.message || e}`, 'error')
      } finally {
        this.folderDeleting[pathPrefix] = false
      }
    },
    confirmClearTrash() {
      if (!this.activeSessionId || this.clearingTrash) return
      this.showClearTrashDialog = true
    },
    async doClearTrash() {
      this.showClearTrashDialog = false
      if (!this.activeSessionId || this.clearingTrash) return
      this.clearingTrash = true
      try {
        const resp = await fetch(`/chat/${encodeURIComponent(this.activeSessionId)}/trash`, { method: 'DELETE' })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this._flash(`清空失败：${data.detail || resp.statusText}`, 'error')
          return
        }
        await this.checkTrash()
        this._flash('回收站已清空', 'success')
      } catch (e) {
        console.error('[Sidebar] clear trash failed:', e)
        this._flash(`清空失败：${e.message || e}`, 'error')
      } finally {
        this.clearingTrash = false
      }
    },
    confirmBulkSoftDelete() {
      // 一键全删（toolbar 按钮）—— 不带 _pendingBulkDeletePaths
      if (!this.activeSessionId || !this.files.length || this.bulkSoftDeleting) return
      this._pendingBulkDeletePaths = null  // null 表示「一键全删」场景
      this._pendingBulkDeleteMessage = ''
      this.showBulkSoftDeleteDialog = true
    },
    /**
     * ConfirmDialog 确认回调 —— 按 _pendingBulkDeletePaths 是否有值分发到不同流程：
     * - 有 paths → 多选批量删除（POST /files/soft-delete）
     * - null → 一键全删（DELETE /files）
     */
    async confirmBulkDelete() {
      this.showBulkSoftDeleteDialog = false
      const pendingPaths = this._pendingBulkDeletePaths
      this._pendingBulkDeletePaths = null
      this._pendingBulkDeleteMessage = ''
      if (!this.activeSessionId) return
      // 多选批量
      if (pendingPaths && pendingPaths.length) {
        await this._doBatchDelete(pendingPaths)
        return
      }
      // 一键全删
      if (this.bulkSoftDeleting) return
      this.bulkSoftDeleting = true
      try {
        const resp = await fetch(`/chat/${encodeURIComponent(this.activeSessionId)}/files`, { method: 'DELETE' })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this._flash(`一键软删除失败：${data.detail || resp.statusText}`, 'error')
          return
        }
        await this.checkFiles()
        if (this.filesActiveTab === 'trash') {
          await this.checkTrash()
        }
        this._flash('已全部软删除', 'success')
      } catch (e) {
        console.error('[Sidebar] bulk soft delete failed:', e)
        this._flash(`一键软删除失败：${e.message || e}`, 'error')
      } finally {
        this.bulkSoftDeleting = false
      }
    },
    cancelBulkDelete() {
      this.showBulkSoftDeleteDialog = false
      this._pendingBulkDeletePaths = null
      this._pendingBulkDeleteMessage = ''
    },
    async exportZip() {
      if (!this.activeSessionId || this.exporting) return
      this.exporting = true
      try {
        const resp = await fetch(`/chat/${this.activeSessionId}/export/artifacts?format=zip`)
        if (!resp.ok) {
          const detail = await resp.text().catch(() => '')
          this._flash(`导出失败：${detail || resp.statusText}`, 'error')
          return
        }
        const blob = await resp.blob()
        this._downloadBlob(blob, this._filenameFromResponse(resp) || `data_analysis_${this.activeSessionId.slice(0, 8)}.zip`)
      } catch (e) {
        console.error('[Sidebar] export zip failed:', e)
        this._flash(`导出失败：${e.message || e}`, 'error')
      } finally {
        this.exporting = false
      }
    },
    async previewHtml() {
      if (!this.activeSessionId || this.exporting) return
      this.exporting = true
      try {
        const resp = await fetch(`/chat/${this.activeSessionId}/export/artifacts?format=html`)
        if (!resp.ok) {
          const detail = await resp.text().catch(() => '')
          this._flash(`导出失败：${detail || resp.statusText}`, 'error')
          return
        }
        const blob = await resp.blob()
        const filename = this._filenameFromResponse(resp) || `data_analysis_${this.activeSessionId.slice(0, 8)}.html`
        this._downloadBlob(blob, filename)
      } catch (e) {
        console.error('[Sidebar] preview html failed:', e)
        this._flash(`导出失败：${e.message || e}`, 'error')
      } finally {
        this.exporting = false
      }
    },
    _downloadBlob(blob, filename) {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.style.display = 'none'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    },
    _filenameFromResponse(resp) {
      const cd = resp.headers.get('content-disposition') || ''
      const m = /filename="?([^";]+)"?/i.exec(cd)
      return m ? m[1] : ''
    },
    // ========== 拖拽调宽度 ==========
    startResize(e) {
      e.preventDefault()
      this.isResizing = true
      this._resizeStartX = e.clientX
      this._resizeStartWidth = this.sidebarWidthPx
      window.addEventListener('mousemove', this.handleResize)
      window.addEventListener('mouseup', this.stopResize)
      document.body.style.cursor = 'ew-resize'
      document.body.style.userSelect = 'none'
    },
    handleResize(e) {
      if (!this.isResizing) return
      if (this._resizeRafId) return
      this._resizeRafId = requestAnimationFrame(() => {
        const delta = e.clientX - this._resizeStartX
        const newWidth = this._resizeStartWidth + delta
        this.sidebarWidthPx = Math.max(220, Math.min(newWidth, 520))
        this._resizeRafId = null
      })
    },
    stopResize() {
      if (!this.isResizing) return
      this.isResizing = false
      if (this._resizeRafId) {
        cancelAnimationFrame(this._resizeRafId)
        this._resizeRafId = null
      }
      window.removeEventListener('mousemove', this.handleResize)
      window.removeEventListener('mouseup', this.stopResize)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  },
  mounted() {
    // localStorage 恢复
    try {
      const raw = localStorage.getItem('lingxi.scheduledTasksExpanded')
      if (raw) {
        const arr = JSON.parse(raw)
        if (Array.isArray(arr)) {
          this.expandedScheduledTasks = new Set(arr)
        }
      }
    } catch (e) { /* 静默 */ }

    this.$nextTick(() => {
      this.checkOverflow()
      this.checkFilesOverflow()
    })

    if (typeof ResizeObserver !== 'undefined') {
      if (this.$refs.conversationListRef) {
        this._resizeObserver = new ResizeObserver(() => this.checkOverflow())
        this._resizeObserver.observe(this.$refs.conversationListRef)
      }
      if (this.$refs.filesTreeRef) {
        this._filesResizeObserver = new ResizeObserver(() => this.checkFilesOverflow())
        this._filesResizeObserver.observe(this.$refs.filesTreeRef)
      }
    }
    window.addEventListener('resize', this.checkOverflow)
    // 全局键盘快捷键（文件编辑）—— 监听到文件视图的 root 元素 / document
    document.addEventListener('keydown', this.onGlobalKeydown)
    // 点别处关右键菜单
    document.addEventListener('click', this._onDocumentClickCloseMenu)
  },
  beforeUnmount() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect()
      this._resizeObserver = null
    }
    if (this._filesResizeObserver) {
      this._filesResizeObserver.disconnect()
      this._filesResizeObserver = null
    }
    window.removeEventListener('resize', this.checkOverflow)
    document.removeEventListener('keydown', this.onGlobalKeydown)
    document.removeEventListener('click', this._onDocumentClickCloseMenu)
    // box-select 兜底清理（防止组件在拖动中被卸载 → window 监听泄漏）
    window.removeEventListener('mousemove', this._onBoxSelectMouseMove)
    window.removeEventListener('mouseup', this._onBoxSelectMouseUp)
    if (this.isResizing) {
      this.stopResize()
    }
    if (this._flashTimer) {
      clearTimeout(this._flashTimer)
      this._flashTimer = null
    }
  }
}
</script>

<style scoped>
.sidebar {
  width: 260px;
  background-color: var(--sidebar-bg);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  height: 100vh;
  flex-shrink: 0;
  overflow: hidden;
  position: relative;
}

.sidebar.collapsed {
  width: 60px;
}

.sidebar-header {
  flex-shrink: 0;
  padding: 12px;
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border-color);
  align-items: center;
}

.toggle-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: var(--bg-hover);
  border-radius: 6px;
  cursor: pointer;
  font-size: 18px;
  color: var(--text-primary);
  transition: background 0.2s;
  flex-shrink: 0;
}

.toggle-btn:hover {
  background: var(--bg-hover);
  opacity: 0.8;
}

/* —— 视图 tab 切换器（📋 会话 / 📁 文件） —— */
.view-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  background: var(--bg-hover, #f3f4f6);
  border-radius: 8px;
  padding: 2px;
  flex-shrink: 0;
}

.view-tab {
  position: relative;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  cursor: pointer;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.view-tab:hover:not(:disabled) {
  color: var(--text-primary, #111);
}

.view-tab.active {
  background: var(--bg-primary, #fff);
  color: var(--primary-color, #3b82f6);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.view-tab:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.view-tab-badge {
  position: absolute;
  top: 1px;
  right: 1px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  font-size: 9px;
  background: var(--primary-color, #3b82f6);
  color: #fff;
  border-radius: 7px;
  line-height: 14px;
  text-align: center;
  font-weight: 600;
}

.view-tab.active .view-tab-badge {
  background: var(--primary-color, #3b82f6);
  color: #fff;
}

.new-chat-btn {
  flex: 1;
  height: 36px;
  border: none;
  background: var(--button-bg);
  color: white;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.2s;
  min-width: 0;
}

.new-chat-btn:hover {
  background: var(--button-hover);
}

/* —— 主体：两视图共享 — = */
.sidebar-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* —— 会话列表视图（原有） —— */
.conversation-list {
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  box-sizing: border-box;
}

.conversation-list::-webkit-scrollbar {
  width: 0;
}
.conversation-list.has-overflow::-webkit-scrollbar {
  width: 6px;
}
.conversation-list.has-overflow::-webkit-scrollbar-track {
  background: transparent;
}
.conversation-list.has-overflow::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
  min-height: 30px;
}
.conversation-list.has-overflow::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

/* —— 文件视图 —— */
.files-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.files-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-color);
  gap: 4px;
  min-height: 32px;
}

.files-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.files-tab {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 6px;
  height: 22px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  font-size: 11.5px;
  font-weight: 500;
  border-radius: 4px;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s, color 0.15s;
}

.files-tab:hover {
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-primary, #111);
}

.files-tab.active {
  background: var(--primary-color, #3b82f6);
  color: #fff;
}

.files-tab-label {
  font-size: 12px;
}

.files-tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  font-size: 10px;
  font-weight: 600;
  border-radius: 8px;
  background: var(--bg-hover, #e5e7eb);
  color: var(--text-secondary, #6b7280);
  line-height: 1;
}

.files-tab.active .files-tab-badge {
  background: rgba(255, 255, 255, 0.3);
  color: #fff;
}

.files-tab-badge--trash {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.files-tab.active .files-tab-badge--trash {
  background: rgba(255, 255, 255, 0.3);
  color: #fff;
}

.files-actions {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  flex-shrink: 0;
  background: var(--bg-hover, #f3f4f6);
  border-radius: 5px;
  padding: 1px;
}

.action-btn {
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 3px;
  color: var(--text-secondary, #6b7280);
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.action-btn:hover:not(:disabled) {
  background: var(--bg-hover, #e5e7eb);
  color: var(--text-primary, #111);
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.action-btn--danger {
  color: #ef4444;
}

.action-btn--danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
}

/* —— 搜索框 —— */
.files-search {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-color);
  position: relative;
}

.files-search-icon {
  position: absolute;
  left: 18px;
  color: var(--text-secondary, #9ca3af);
  pointer-events: none;
}

.files-search-input {
  flex: 1;
  height: 28px;
  padding: 0 26px 0 28px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary, #fff);
  color: var(--text-primary, #111);
  font-size: 12.5px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.files-search-input::placeholder {
  color: var(--text-secondary, #9ca3af);
}

.files-search-input:focus {
  border-color: var(--primary-color, #3b82f6);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.files-search-clear {
  position: absolute;
  right: 14px;
  width: 18px;
  height: 18px;
  border: none;
  background: transparent;
  color: var(--text-secondary, #9ca3af);
  cursor: pointer;
  font-size: 14px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.files-search-clear:hover {
  background: var(--bg-hover, #e5e7eb);
  color: var(--text-primary, #111);
}

/* —— 文件树容器 —— */
.files-tree {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 4px 0;
  outline: none;   /* tabindex=-1 让容器可获焦以配合快捷键；不要画可见的 focus ring */
}

.files-tree::-webkit-scrollbar {
  width: 0;
}
.files-tree.has-overflow::-webkit-scrollbar {
  width: 6px;
}
.files-tree.has-overflow::-webkit-scrollbar-track {
  background: transparent;
}
.files-tree.has-overflow::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
  min-height: 30px;
}
.files-tree.has-overflow::-webkit-scrollbar-thumb:hover {
  background: var(--text-secondary);
}

.tree-list {
  font-size: 13px;
  position: relative;     /* box-select 矩形 absolute 定位的参考 */
  user-select: none;      /* 拖框选时禁止文字选择 */
  cursor: default;
}

/* —— Finder/Explorer 风格 box-select 视觉矩形 —— */
.box-select-rect {
  position: absolute;
  pointer-events: none;   /* 不挡鼠标事件 —— 让窗口级 mousemove 持续触发 */
  background: rgba(59, 130, 246, 0.12);   /* 蓝底半透 —— 与多选选中色一致 */
  border: 1px solid rgba(59, 130, 246, 0.5);
  border-radius: 2px;
  z-index: 50;
  /* 禁用过渡 —— 让矩形跟随鼠标实时移动 */
  transition: none;
}

.empty-state {
  text-align: center;
  color: var(--text-secondary, #9ca3af);
  padding: 24px;
  font-size: 13px;
}

.empty-state-hint {
  margin-top: 4px;
  font-size: 11.5px;
  opacity: 0.7;
}

.empty-state.load-error {
  text-align: left;
  padding: 14px 12px;
}

.load-error-detail {
  margin-top: 4px;
  font-size: 11.5px;
  opacity: 0.8;
  word-break: break-all;
}

.load-error-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.7;
}

/* —— 拖拽调宽度手柄 —— */
.resize-handle {
  position: absolute;
  top: 0;
  right: -3px;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
  z-index: 10;
  user-select: none;
}

.resize-handle:hover {
  background: var(--primary-color, #3b82f6);
  opacity: 0.15;
}

/* —— IDEA 风右键菜单 —— */
.ctx-menu {
  position: fixed;
  z-index: 1000;
  min-width: 180px;
  padding: 4px;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.06);
  font-size: 12.5px;
  user-select: none;
}

.ctx-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 5px 10px;
  border: none;
  background: transparent;
  color: var(--text-primary, #111);
  cursor: pointer;
  border-radius: 4px;
  text-align: left;
  font: inherit;
  transition: background 0.1s;
}
.ctx-menu-item:hover:not(:disabled) {
  background: var(--bg-hover, #f3f4f6);
}
.ctx-menu-item--danger {
  color: #ef4444;
}
.ctx-menu-item--danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.08);
}
.ctx-menu-item--disabled,
.ctx-menu-item:disabled {
  color: var(--text-secondary, #9ca3af);
  cursor: not-allowed;
  opacity: 0.6;
}
.ctx-menu-item + .ctx-menu-item[disabled] {
  /* 分隔线条目 */
  pointer-events: none;
}
.ctx-menu-icon {
  width: 14px;
  flex-shrink: 0;
  color: var(--text-secondary, #6b7280);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.ctx-menu-label {
  flex: 1;
  min-width: 0;
}
.ctx-menu-shortcut {
  font-size: 11px;
  color: var(--text-secondary, #9ca3af);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  flex-shrink: 0;
}

/* —— 新建文件夹/文件弹窗 —— */
.ctx-dialog-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.32);
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(2px);
}

.ctx-dialog {
  background: var(--bg-primary, #fff);
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.16);
  padding: 18px;
  min-width: 320px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ctx-dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #111);
}

.ctx-dialog-parent-hint {
  font-size: 11.5px;
  color: var(--text-secondary, #6b7280);
  margin: -4px 0 6px 2px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all;
}
.ctx-dialog-input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 5px;
  background: var(--bg-primary, #fff);
  color: var(--text-primary, #111);
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.ctx-dialog-input:focus {
  border-color: var(--primary-color, #3b82f6);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.ctx-dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.ctx-dialog-btn {
  height: 30px;
  padding: 0 14px;
  border-radius: 5px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
}
.ctx-dialog-btn--cancel {
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-primary, #111);
  border-color: var(--border-color, #e5e7eb);
}
.ctx-dialog-btn--cancel:hover {
  background: var(--bg-primary, #fff);
  opacity: 0.85;
}
.ctx-dialog-btn--ok {
  background: var(--button-bg, #3b82f6);
  color: #fff;
}
.ctx-dialog-btn--ok:hover {
  background: var(--button-hover, #2563eb);
}

/* —— 非阻塞 flash 消息（替换 file ops 里所有 alert()） —— */
.flash-message {
  position: absolute;
  bottom: 14px;
  left: 50%;
  transform: translateX(-50%);
  padding: 7px 14px;
  border-radius: 5px;
  font-size: 12.5px;
  line-height: 1.4;
  z-index: 1200;
  max-width: calc(100% - 24px);
  text-align: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
  animation: flash-in 0.2s ease-out;
  pointer-events: none;
}
.flash-message--error {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fca5a5;
}
.flash-message--info {
  background: #eff6ff;
  color: #1e40af;
  border: 1px solid #93c5fd;
}
.flash-message--success {
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #86efac;
}
@keyframes flash-in {
  from { opacity: 0; transform: translate(-50%, 6px); }
  to { opacity: 1; transform: translate(-50%, 0); }
}
.flash-fade-leave-active { transition: opacity 0.18s ease-in; }
.flash-fade-leave-to { opacity: 0; }
</style>