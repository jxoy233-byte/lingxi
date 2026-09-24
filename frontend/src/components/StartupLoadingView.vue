<!--
  StartupLoadingView.vue

  v0.3.x 启动期 waiting 全屏遮蔽。

  ⚠️ 与 BootstrapView 是**同一个启动状态的两个视图**（同一份 servicesReady 状态机 +
  同一份 App.vue `_startupLogs` 日志缓冲），任意时刻只显示一个：
  BootstrapView（✕）⇄ 本组件（⚙ 配置 / ✕），互相切换即换显示，不改变启动状态。
  启动完成后 onServicesReadyChange 收到 ready=true + autoEnter=true → appReady=true，
  两个视图一起消失、自动进主界面（无需用户点「进入应用」）。

  触发时机：
    - cold + autoEnter=true：App.vue _autoBootstrap() 启动 → 显示本浮层
    - warm + autoEnter=true：后端实际已在跑，但仍显示几秒 loading 反馈
    - classic BootstrapView 点 ✕（且已勾 autoEnter）：App.vue 切到本浮层
    - cold + autoEnter=false：BootstrapView classic 形态显示（不走本浮层）

  v0.3.x 改造（用户中途可介入）：
    - 「⚙ 启动配置」按钮 → emit('open-bootstrap')，App.vue 弹 BootstrapView deps 形态
    - 「▶ 查看日志（N 行）」→ 折叠 / 展开实时日志面板，日志由 App.vue 的 _startupLogs 下传
    - 「⏹ 停止启动」按钮 → emit('cancel')，App.vue 调 window.electronAPI.cancelBootstrap()
      （这是唯一「真正放弃自动启动」的入口，与 ✕ 的切视图语义不同）
    - 「✕」按钮（右上角）→ 语义同「⚙ 配置」emit('open-bootstrap')，
      与 ⚙ 配置按钮**完全一致**：切到 BootstrapView 让用户查看 / 调整启动配置，
      后台 bootstrap 继续跑，**保留 _autoEnterPreference=true**。
      区别仅入口位置（右上角 ✕ vs 卡片内 ⚙ 按钮）。

  视觉：v0.3.x 终态 — **完全去掉白底卡片容器**。
  之前 v0.3.0 + 第一次修复都是「dialog 弹窗」（带 bg-primary 卡片 + border + shadow + radius），
  本质上还是弹窗感，跟用户对「遮蔽背景」的诉求不符。
  现在改成 macOS launchpad / splash 风格：全屏半透明深色 backdrop + 居中堆叠内容（鹿 + 文案 +
  进度条 + 倒计时 + 按钮），所有元素直接画在 backdrop 上，**没有任何 dialog 容器**。
  z-index 2000 盖住所有 UI（含 NotFoundView 1800）。
-->
<template>
  <!--
    根节点加 v-if="visible"：之前没有这个 gate，组件始终在 DOM 里渲染，
    .startup-loading-overlay 的 fixed + z-index 2000 + 半透明 backdrop 一直盖在主界面上，
    用户看到 StartupLoadingView 的 backdrop 但 click 不到主界面（被盖住）。
    v-if 让组件在 visible=false 时彻底卸载，DOM 完全无相关元素。
  -->
  <div
    v-if="visible"
    class="startup-loading-overlay"
    role="dialog"
    aria-modal="true"
    aria-labelledby="startup-loading-title"
  >
    <!-- 右上角关闭按钮：语义同「⚙ 配置」→ emit('open-bootstrap')，
         弹 deps 形态让用户能查看 / 调整启动配置；后台 bootstrap 继续跑，保留 autoEnter 偏好。
         这是和 ⚙ 配置**完全一致**的语义（仅入口不同：右上角 ✕ vs 卡片内 ⚙ 按钮）。
         ⚠️ 不是「退出等待」——本浮层与 BootstrapView 是同一个启动状态的两个视图，
            点 ✕ 只是切到 BootstrapView 那个视图，不取消后台启动。 -->
    <button
      type="button"
      class="exit-corner"
      @click="$emit('open-bootstrap')"
      title="打开启动配置面板（不取消后台启动）"
      aria-label="打开启动配置面板"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"/>
        <line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>

    <!-- 居中内容堆叠（无 card 容器） -->
    <div class="startup-loading-stack">
      <!-- 像素鹿舞台（与 NotFoundView 同款 16x18 SVG） -->
      <div class="pixel-deer-stage" aria-hidden="true">
        <div class="pixel-deer-shadow"></div>
        <div class="pixel-deer-wrap">
          <svg class="pixel-deer" viewBox="0 0 16 18" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
            <rect x="8" y="0" width="1" height="1" fill="#f5e6c8"/>
            <rect x="11" y="0" width="1" height="1" fill="#f5e6c8"/>
            <rect x="7" y="1" width="1" height="1" fill="#f5e6c8"/>
            <rect x="8" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="1" width="1" height="1" fill="#c9a875"/>
            <rect x="12" y="1" width="1" height="1" fill="#f5e6c8"/>
            <rect x="6" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="13" y="2" width="1" height="1" fill="#c9a875"/>
            <rect x="7" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="12" y="3" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="9" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="10" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="11" y="4" width="1" height="1" fill="#c9a875"/>
            <rect x="8" y="5" width="1" height="1" fill="#7a4f2c"/>
            <rect x="9" y="5" width="1" height="1" fill="#7a4f2c"/>
            <rect x="10" y="5" width="1" height="1" fill="#7a4f2c"/>
            <rect x="7" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="11" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="12" y="6" width="1" height="1" fill="#a87147"/>
            <rect x="7" y="7" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="7" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="7" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="7" width="1" height="1" fill="#1a1a1a"/>
            <rect x="11" y="7" width="1" height="1" fill="#1a1a1a"/>
            <rect x="12" y="7" width="1" height="1" fill="#3a2418"/>
            <rect x="7" y="8" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="9" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="11" y="8" width="1" height="1" fill="#f4d8a8"/>
            <rect x="12" y="8" width="1" height="1" fill="#3a2418"/>
            <rect x="8" y="9" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="9" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="9" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="10" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="10" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="10" width="1" height="1" fill="#a87147"/>
            <rect x="1" y="10" width="1" height="1" fill="#fff5e1"/>
            <rect x="1" y="11" width="1" height="1" fill="#fff5e1"/>
            <rect x="2" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="4" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="5" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="6" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="7" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="11" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="12" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="4" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="5" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="6" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="7" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="8" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="9" y="12" width="1" height="1" fill="#f4d8a8"/>
            <rect x="10" y="12" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="4" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="5" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="6" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="7" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="8" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="13" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="3" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="2" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="3" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="2" y="17" width="1" height="1" fill="#3a2418"/>
            <rect x="3" y="17" width="1" height="1" fill="#3a2418"/>
            <rect x="9" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="10" y="14" width="1" height="1" fill="#7a4f2c"/>
            <rect x="9" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="15" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="10" y="16" width="1" height="1" fill="#a87147"/>
            <rect x="9" y="17" width="1" height="1" fill="#3a2418"/>
            <rect x="10" y="17" width="1" height="1" fill="#3a2418"/>
          </svg>
        </div>
        <div class="pixel-particle pixel-particle--1"></div>
        <div class="pixel-particle pixel-particle--2"></div>
        <div class="pixel-particle pixel-particle--3"></div>
      </div>

      <!-- 文案：白色文字 + 阴影，半透明背景上可读 -->
      <div id="startup-loading-title" class="startup-loading-title">正在等待后端启动</div>
      <div class="startup-loading-subtitle">{{ subtitleText }}</div>

      <!-- 进度条：240px 居中、白色 -->
      <div class="startup-loading-progress-track">
        <div class="startup-loading-progress-bar" :style="{ width: progressPct + '%' }"></div>
      </div>
      <div class="startup-loading-hint">已等待 {{ elapsedLabel }} 秒</div>

      <!-- 操作按钮区：透明背景 + 白边框 -->
      <div class="startup-loading-actions">
        <button
          type="button"
          class="action-btn"
          @click="$emit('open-bootstrap')"
          title="查看 / 修改启动配置（项目根 / Python / Docker / Redis）"
        >
          ⚙ 启动配置
        </button>
        <button
          v-if="cancelable"
          type="button"
          class="action-btn danger"
          @click="confirmCancel"
          title="杀掉后端进程并停止启动流程"
        >
          ⏹ 停止启动
        </button>
      </div>

      <!-- 实时日志面板（底部抽屉式）。默认折叠；展开后深色半透明 -->
      <div v-if="startupLogs.length > 0 || logPanelOpen" class="startup-log-panel">
        <button type="button" class="log-toggle" @click="toggleLogPanel">
          <span class="log-toggle-icon">{{ logPanelOpen ? '▼' : '▶' }}</span>
          {{ logPanelOpen ? '收起日志' : `查看日志（${startupLogs.length} 行）` }}
        </button>
        <div v-if="logPanelOpen" ref="logContainer" class="log-content">
          <div v-if="startupLogs.length === 0" class="log-empty">等待主进程输出…</div>
          <div
            v-for="(line, idx) in startupLogs"
            :key="idx"
            :class="['log-line', `log-${line.item || 'startup'}`]"
          >
            <span class="log-prefix">[{{ line.item || 'startup' }}]</span>
            <span class="log-msg">{{ line.msg }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'StartupLoadingView',
  props: {
    visible: { type: Boolean, default: false },
    elapsed: { type: Number, default: 0 },
    // 实时日志：[{ item, msg }, ...]
    startupLogs: { type: Array, default: () => [] },
    // 是否显示「停止启动」按钮。autoEnter 路径 = true；warm path 但 autoEnter=false = false
    cancelable: { type: Boolean, default: false },
  },
  emits: [
    'open-bootstrap', // 「⚙ 配置」按钮 + 「✕ 退出等待」按钮 → App.vue 弹 deps BootstrapView
    'cancel',         // 「⏹ 停止启动」按钮 → App.vue 调 cancelBootstrap() 真正取消后台
  ],
  data() {
    return {
      TOTAL_WAIT_SECONDS: 120,
      logPanelOpen: false,
    }
  },
  watch: {
    startupLogs() {
      if (!this.logPanelOpen) return
      this.$nextTick(() => {
        const el = this.$refs.logContainer
        if (el) el.scrollTop = el.scrollHeight
      })
    },
    logPanelOpen(open) {
      if (open) {
        this.$nextTick(() => {
          const el = this.$refs.logContainer
          if (el) el.scrollTop = el.scrollHeight
        })
      }
    },
    visible(v) {
      if (!v) this.logPanelOpen = false
    },
  },
  computed: {
    progressPct() {
      return Math.max(0, Math.min(100, (this.elapsed / this.TOTAL_WAIT_SECONDS) * 100))
    },
    elapsedLabel() {
      return Math.max(0, Math.ceil(this.elapsed))
    },
    subtitleText() {
      if (this.elapsed < 5) return '后端服务启动中，请稍候…'
      if (this.elapsed < 30) return '首次启动需同步依赖，请稍候…'
      if (this.elapsed < 120) return '正在加载 AI 模型，请稍候…'
      return '启动耗时较长，请检查后端日志或网络'
    },
  },
  methods: {
    toggleLogPanel() {
      this.logPanelOpen = !this.logPanelOpen
    },
    confirmCancel() {
      const ok = window.confirm(
        '确定要停止启动吗？\n\n' +
        '• 已下载的依赖 / 已构建的镜像会保留\n' +
        '• 后端进程会被杀掉\n' +
        '• 之后可重新点击「启动应用」'
      )
      if (ok) this.$emit('cancel')
    },
  },
}
</script>

<style scoped>
/*
 * 视觉风格：v0.3.x 终态 —— **完全去掉白底卡片容器**。
 * - 全屏 fixed 半透明深色 backdrop + blur(4px)
 * - 内容直接居中堆叠在 backdrop 上（鹿 + 文案 + 进度条 + 倒计时 + 按钮 + 日志）
 * - 文字 / 进度条 / 按钮全部用半透明白色 + 阴影 / 白边框，**任何主题下都清晰可读**
 * - 不再有 .startup-loading-card 容器，**彻底消除 dialog 弹窗感**
 *
 * z-index 2000：高于 NotFoundView 1800，**低于** BootstrapView 2100 与 .restart-mask 2400。
 * 完整层级链见 App.vue 里 .restart-mask 的 CSS 注释。
 */
.startup-loading-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 与 .restart-mask 同款 backdrop（light / dark） */
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: startup-loading-fade-in 0.3s ease-out;
  /* 兜底：light 主题下用更深一点的 backdrop 让白色文字 + 阴影仍可读 */
}

:global(.dark-theme) .startup-loading-overlay {
  background: rgba(0, 0, 0, 0.75);
}

/* ===== 居中内容堆叠（替代之前的卡片容器）===== */
.startup-loading-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  width: min(420px, 90vw);
  max-height: 88vh;
  overflow-y: auto;
  /* 文字颜色：白色 + 阴影，保证半透明背景上的可读性 */
  color: rgba(255, 255, 255, 0.95);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}

/* ===== 右上角退出按钮 ===== */
.exit-corner {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.75);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.exit-corner:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.3);
}

/* ===== 像素鹿舞台 ===== */
.pixel-deer-stage {
  position: relative;
  width: 96px;
  height: 120px;
  margin: 0 auto 0;
}

.pixel-deer-wrap {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.pixel-deer {
  width: 100%;
  height: 100%;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  transform-origin: 50% 100%;
  animation: deer-hop 1.4s ease-in-out infinite;
  will-change: transform;
}

.pixel-deer-shadow {
  position: absolute;
  bottom: 2px;
  left: 50%;
  width: 54px;
  height: 6px;
  background: rgba(0, 0, 0, 0.32);
  border-radius: 50%;
  transform: translateX(-50%);
  animation: deer-shadow-pulse 1.4s ease-in-out infinite;
}

.pixel-particle {
  position: absolute;
  width: 3px;
  height: 3px;
  border-radius: 0;
  background: rgba(255, 255, 255, 0.7);
  pointer-events: none;
  opacity: 0;
}
.pixel-particle--1 { left: 10px; bottom: 14px; animation: pixel-float 2.6s ease-in-out infinite; animation-delay: 0s; }
.pixel-particle--2 { left: 76px; bottom: 24px; animation: pixel-float 3.2s ease-in-out infinite; animation-delay: 0.8s; }
.pixel-particle--3 { left: 84px; bottom: 8px; animation: pixel-float 2.8s ease-in-out infinite; animation-delay: 1.4s; }

/* ===== 文案（白色 + 阴影）===== */
.startup-loading-title {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  text-align: center;
  margin-top: 4px;
}

.startup-loading-subtitle {
  font-size: 12.5px;
  color: rgba(255, 255, 255, 0.7);
  text-align: center;
  line-height: 1.4;
}

/* ===== 进度条 ===== */
.startup-loading-progress-track {
  width: 240px;
  height: 2px;
  background: rgba(255, 255, 255, 0.18);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 6px;
}

.startup-loading-progress-bar {
  height: 100%;
  background: rgba(255, 255, 255, 0.85);
  transition: width 0.1s linear;
  border-radius: 2px;
}

.startup-loading-hint {
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.6);
  text-align: center;
}

/* ===== 操作按钮区（透明背景 + 白边框 + hover 浅白底）===== */
.startup-loading-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  justify-content: center;
  flex-wrap: wrap;
}

.action-btn {
  padding: 7px 16px;
  font-size: 12.5px;
  font-family: inherit;
  color: rgba(255, 255, 255, 0.95);
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.25);
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  text-shadow: none;
}
.action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(255, 255, 255, 0.5);
}
.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-btn.danger {
  color: #fca5a5;
  border-color: rgba(252, 165, 165, 0.4);
}
.action-btn.danger:hover:not(:disabled) {
  background: rgba(220, 38, 38, 0.2);
  border-color: rgba(252, 165, 165, 0.7);
  color: #fff;
}

/* ===== 实时日志面板（深色半透明）===== */
.startup-log-panel {
  width: 100%;
  margin-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.15);
  padding-top: 8px;
}

.log-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  background: none;
  border: none;
  padding: 4px 0;
  cursor: pointer;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  font-family: inherit;
  text-shadow: none;
}
.log-toggle:hover { color: rgba(255, 255, 255, 0.95); }
.log-toggle-icon { font-size: 10px; }

.log-content {
  max-height: 180px;
  overflow-y: auto;
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.4;
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  padding: 6px 8px;
  margin-top: 4px;
  scroll-behavior: smooth;
  color: rgba(255, 255, 255, 0.85);
  text-shadow: none;
}

.log-line {
  display: flex;
  gap: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}

.log-prefix {
  flex-shrink: 0;
  font-weight: 600;
  opacity: 0.85;
  min-width: 60px;
}

.log-msg {
  flex: 1;
  white-space: pre-wrap;
}

/* 按 item 上色（半透明白/黄/绿等 — backdrop 上清晰） */
.log-uv .log-prefix { color: rgba(255, 255, 255, 0.6); }
.log-redis .log-prefix { color: #fca5a5; }
.log-sandbox .log-prefix { color: #fdba74; }
.log-venv .log-prefix { color: #93c5fd; }
.log-backend .log-prefix { color: #c4b5fd; }
.log-startup { font-weight: 600; }
.log-startup .log-prefix { color: #86efac; }

.log-empty {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
  font-style: italic;
  text-align: center;
  padding: 4px 0;
}

/* ===== 动画 keyframes ===== */
@keyframes deer-hop {
  0%   { transform: translateY(0)     scaleY(0.9)  scaleX(1.06); }
  18%  { transform: translateY(-3px)  scaleY(1)    scaleX(1); }
  50%  { transform: translateY(-14px) scaleY(1.07) scaleX(0.95); }
  82%  { transform: translateY(-3px)  scaleY(1)    scaleX(1); }
  100% { transform: translateY(0)     scaleY(0.9)  scaleX(1.06); }
}

@keyframes deer-shadow-pulse {
  0%, 100% { transform: translateX(-50%) scaleX(1);   opacity: 0.32; }
  50%      { transform: translateX(-50%) scaleX(0.55); opacity: 0.16; }
}

@keyframes pixel-float {
  0%   { opacity: 0;    transform: translateY(0); }
  15%  { opacity: 0.7; }
  100% { opacity: 0;    transform: translateY(-26px); }
}

@keyframes startup-loading-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .pixel-deer,
  .pixel-deer-shadow,
  .pixel-particle { animation: none; }
}
</style>