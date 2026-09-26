<template>
  <header class="chat-header">
    <div class="header-left">
      <button
        class="hamburger-btn"
        @click="$emit('toggle-sidebar')"
        title="打开菜单"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="3" y1="6" x2="21" y2="6"/>
          <line x1="3" y1="12" x2="21" y2="12"/>
          <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <h1>灵析</h1>
    </div>
    <div class="header-actions">
      <slot name="extra-actions" />
      <button
        @click="$emit('refresh')"
        class="refresh-btn"
        title="刷新页面 (Ctrl/⌘+R)"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
      </button>
      <button
        v-if="hasSession"
        @click="$emit('toggle-checkpoints')"
        class="checkpoint-btn"
        title="查看历史版本"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
      </button>
      <!-- v0.5.x —— Word 写作抽屉切换：仅当 AI 写过 Word 文件时显示 -->
      <button
        v-if="hasSession && wordDrawerAvailable"
        @click="$emit('toggle-word-drawer')"
        class="drawer-toggle-btn"
        :class="{ active: wordDrawerOpen }"
        :title="wordDrawerOpen ? '关闭 Word 写作抽屉' : '打开 Word 写作抽屉'"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="9" y1="13" x2="15" y2="13"/>
          <line x1="9" y1="17" x2="15" y2="17"/>
        </svg>
      </button>
      <!-- v0.5.x —— Excel 写作抽屉切换：仅当 AI 写过 Excel 文件时显示。默认不自动打开 -->
      <button
        v-if="hasSession && excelDrawerAvailable"
        @click="$emit('toggle-excel-drawer')"
        class="drawer-toggle-btn"
        :class="{ active: excelDrawerOpen }"
        :title="excelDrawerOpen ? '关闭 Excel 表格预览' : '打开 Excel 表格预览（手动）'"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
          <line x1="3" y1="9" x2="21" y2="9"/>
          <line x1="3" y1="15" x2="21" y2="15"/>
          <line x1="9" y1="3" x2="9" y2="21"/>
          <line x1="15" y1="3" x2="15" y2="21"/>
        </svg>
      </button>
      <button
        @click="$emit('open-settings')"
        class="settings-btn"
        title="设置"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
      <button
        @click="$emit('open-setup')"
        class="setup-btn"
        title="安装 / 配置向导"
      >
        <!-- 摩法棒：与 ⚙ 视觉区隔，纯前端动作入口（点开 SetupView） -->
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M15 4V2"/>
          <path d="M15 16v-2"/>
          <path d="M8 9h2"/>
          <path d="M20 9h2"/>
          <path d="M17.8 11.8L19 13"/>
          <path d="M15 9h0"/>
          <path d="M17.8 6.2L19 5"/>
          <path d="m3 21 9-9"/>
          <path d="M12.2 6.2L11 5"/>
        </svg>
      </button>
    </div>
  </header>
</template>

<script>
export default {
  name: 'ChatHeader',
  props: {
    hasSession: {
      type: Boolean,
      default: false
    },
    // v0.5.x —— 写作抽屉可用性：AI 是否在本会话写过 Word/Excel 文件
    wordDrawerAvailable: {
      type: Boolean,
      default: false
    },
    excelDrawerAvailable: {
      type: Boolean,
      default: false
    },
    // v0.5.x —— 抽屉是否当前打开（按钮高亮态）
    wordDrawerOpen: {
      type: Boolean,
      default: false
    },
    excelDrawerOpen: {
      type: Boolean,
      default: false
    }
  },
  emits: [
    'open-settings', 'open-setup', 'toggle-checkpoints', 'toggle-sidebar',
    'refresh',
    // v0.5.x —— 抽屉切换
    'toggle-word-drawer', 'toggle-excel-drawer'
  ]
}
</script>

<style scoped>
.chat-header {
  height: var(--header-height, 60px);
  background-color: var(--header-bg);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hamburger-btn {
  display: none;
  width: 36px;
  height: 36px;
  border: none;
  background: var(--bg-hover);
  border-radius: 8px;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  color: var(--text-primary);
  transition: background 0.2s;
}

.hamburger-btn:hover {
  background: var(--bg-hover);
  opacity: 0.8;
}

@media (max-width: 600px) {
  .hamburger-btn {
    display: flex;
  }
  .chat-header {
    padding: 0 12px;
  }
  .chat-header h1 {
    font-size: 17px;
  }
}

.chat-header h1 {
  font-size: 20px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.checkpoint-btn,
.settings-btn,
.refresh-btn,
.setup-btn,
.drawer-toggle-btn {
  width: 40px;
  height: 40px;
  border: none;
  background: var(--bg-hover);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.checkpoint-btn,
.refresh-btn {
  color: var(--text-secondary);
}

.settings-btn {
  color: var(--text-secondary);
}

.checkpoint-btn:hover {
  background: var(--bg-hover);
  color: var(--button-bg);
  opacity: 0.8;
}

.refresh-btn:hover {
  background: var(--bg-hover);
  color: var(--button-bg);
  opacity: 0.8;
}

.refresh-btn:active svg {
  transform: rotate(360deg);
  transition: transform 0.6s ease;
}

.settings-btn:hover {
  background: var(--bg-hover);
  color: var(--button-bg);
  opacity: 0.8;
}

.setup-btn {
  color: var(--text-secondary);
}
.setup-btn:hover {
  background: var(--bg-hover);
  color: var(--button-bg);
  opacity: 0.8;
}

/* v0.5.x —— 抽屉切换按钮：active 态有蓝色高亮表示抽屉已开 */
.drawer-toggle-btn {
  color: var(--text-secondary);
}
.drawer-toggle-btn:hover {
  background: var(--bg-hover);
  color: var(--button-bg);
  opacity: 0.8;
}
.drawer-toggle-btn.active {
  background: var(--button-bg, #6366f1);
  color: #ffffff;
}
.drawer-toggle-btn.active:hover {
  opacity: 1;
}
</style>
