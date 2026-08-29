<template>
  <!--
    浮窗形式：fixed 全屏 + 半透明 backdrop + 居中卡片。
    App.vue 的主界面始终在 DOM 里（appReady=false 时灰显禁用），
    用户点"启动应用" → 主进程广播 servicesReady=true → 浮窗消失，主界面启用。
  -->
  <div class="setup-overlay">
    <div class="setup-backdrop"></div>
    <div class="setup-card">
      <div class="setup-header">
        <h2>灵析 启动配置</h2>
        <p class="subtitle">首次启动需要检测并配置以下依赖项</p>
      </div>

      <!-- 项目目录行（独立于 items 列表，因为它有专属的「选择目录」按钮） -->
      <div :class="['check-item', projectRoot.ok ? 'ok' : 'fail']" style="margin-bottom:8px">
        <span class="icon">{{ projectRoot.ok ? '✓' : '✗' }}</span>
        <div class="info">
          <div class="label">项目目录（lingxi/）</div>
          <div class="detail">{{ projectRoot.detail || '检测中...' }}</div>
        </div>
        <div class="action">
          <button class="btn-fix" @click="pickProjectRoot" :disabled="picking">
            {{ picking ? '选择中...' : '选择目录' }}
          </button>
        </div>
      </div>

      <div class="check-list">
        <div
          v-for="item in items"
          :key="item.id"
          :class="['check-item', getStatusClass(item)]"
        >
          <span class="icon">{{ getStatusIcon(item) }}</span>
          <div class="info">
            <div class="label">{{ item.label }}</div>
            <div class="detail">{{ item.detail || '检测中...' }}</div>
          </div>
          <div class="action">
            <button
              v-if="item.canAutoFix && !item.ok && !item.fixing"
              class="btn-fix"
              @click="fixOne(item)"
            >配置</button>
            <a
              v-else-if="!item.ok && !item.canAutoFix"
              class="btn-download"
              :href="item.downloadUrl"
              target="_blank"
            >下载</a>
            <span v-else-if="item.fixing" class="fixing-indicator">配置中...</span>
          </div>
        </div>
      </div>

      <div class="log-box" ref="logBox">
        <pre v-if="logs">{{ logs }}</pre>
        <div v-else class="log-placeholder">点击"启动应用"后，这里会显示自动配置进度</div>
      </div>

      <label class="auto-enter-option">
        <input
          v-model="autoEnterFrontend"
          type="checkbox"
          :disabled="launching"
          @change="saveAutoEnterPreference"
        />
        <span>后端启动完成后自动进入前端</span>
      </label>

      <div class="actions">
        <button class="btn-secondary" @click="recheck" :disabled="checking || launching">
          {{ checking ? '检测中...' : '重新检测' }}
        </button>
        <!--
          主按钮三态：
          - launching=true：启动中，按钮 disabled 显示「启动中...」
          - servicesReady=true && !autoEnterFrontend：bootstrap 已完成但用户没勾自动进，
            显示「进入应用」让用户主动点；emit enter-app 让 App.vue 翻 appReady
          - 其他：未启动（cold 初始 / 后端挂掉重启），显示「启动应用」
        -->
        <button
          v-if="launching"
          class="btn-primary"
          disabled
        >启动中...</button>
        <button
          v-else-if="servicesReady && !autoEnterFrontend"
          class="btn-primary"
          @click="enterApp"
        >进入应用</button>
        <button
          v-else
          class="btn-primary"
          :disabled="!allOk"
          @click="launch"
        >启动应用</button>
      </div>

      <div v-if="launchError" class="error-bar">
        启动失败：{{ launchError }}
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'SetUpView',
  // servicesReady 是父级 (App.vue) 持有的主进程 servicesReady 状态；
  // 通过 prop 下传避免 SetUpView 重复 invoke getServicesReady（避免双源真相漂移）。
  props: {
    servicesReady: {
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      // 项目目录独立于 items：必须先确定 lingxi/ 根目录才能做后续
      projectRoot: { ok: false, detail: '' },
      picking: false,
      // UI 只展示 2 项：python 和 docker。
      // uv / redis / sandbox / venv 都是「docker + python 在」之后由 bootstrap 自动配置的，
      // 暴露成 4 个单独配置按钮只会徒增操作步骤（一键部署应该真的「一键」）。
      items: [
        {
          id: 'python',
          label: 'Python 3.12+',
          canAutoFix: false,
          downloadUrl: 'https://www.python.org/downloads/',
          ok: false,
          detail: '',
          fixing: false,
        },
        {
          id: 'docker',
          label: 'Docker Desktop',
          canAutoFix: false,
          downloadUrl: 'https://www.docker.com/products/docker-desktop/',
          ok: false,
          detail: '',
          fixing: false,
        },
      ],
      logs: '',
      checking: false,
      launching: false,
      launchError: '',
      autoEnterFrontend: false,
    }
  },
  computed: {
    allOk() {
      // 启动按钮可用 = 项目根 + 2 项基础检查都 ok
      return this.projectRoot.ok && this.items.every(i => i.ok)
    },
  },
  watch: {
    // servicesReady 由父级 (App.vue) 通过 prop 下传；这里只追加日志，不重复触发 launch。
    servicesReady(ready) {
      if (ready) this.logs += '[启动] ✅ 后端与 MCP 已就绪\n'
    }
  },
  async mounted() {
    if (window.electronAPI?.getStartupPreferences) {
      const preferences = await window.electronAPI.getStartupPreferences()
      this.autoEnterFrontend = preferences?.autoEnterFrontend === true
    }
    await this.recheck()
    // servicesReady 由 App.vue 持有 + 通过 prop 下传，避免双源真相；这里不再 invoke getServicesReady。
    if (this.servicesReady) {
      this.logs += '[启动] ✅ 后端与 MCP 已就绪\n'
    }
    // 订阅日志流
    if (window.electronAPI?.onStartupLog) {
      window.electronAPI.onStartupLog((data) => {
        this.logs += data.msg
        this.$nextTick(() => {
          if (this.$refs.logBox) {
            this.$refs.logBox.scrollTop = this.$refs.logBox.scrollHeight
          }
        })
      })
    }

    // 自动启动：用户勾选了"启动完成后自动进入前端" + 服务未就绪 + 探测都通过 → 自动触发 bootstrap。
    // 勾了 autoEnter 时主进程 bootstrap 完成后会带 autoEnterFrontend=true 广播，App.vue 翻 appReady
    // 让 SetUpView 卸载；这里只是发起 bootstrap 这一步。
    if (this.autoEnterFrontend && !this.servicesReady && this.allOk) {
      this.$nextTick(() => this.launch())
    }
  },
  methods: {
    async recheck() {
      this.checking = true
      try {
        const results = await window.electronAPI.probeAll()
        if (results.projectRoot) {
          this.projectRoot.ok = results.projectRoot.ok
          this.projectRoot.detail = results.projectRoot.detail || ''
        }
        this.items.forEach(item => {
          if (results[item.id]) {
            item.ok = results[item.id].ok
            item.detail = results[item.id].detail || ''
          }
        })
      } catch (e) {
        console.error('recheck failed:', e)
      } finally {
        this.checking = false
      }
    },
    async pickProjectRoot() {
      this.picking = true
      try {
        const result = await window.electronAPI.pickProjectRoot()
        if (result.ok) {
          this.projectRoot.ok = true
          this.projectRoot.detail = result.projectRoot
          this.logs += `\n[项目目录] 已选择：${result.projectRoot}\n`
          // 选了根目录后重新探测 python / docker
          await this.recheck()
        } else if (result.error && result.error !== '已取消') {
          this.logs += `[项目目录] ❌ ${result.error}\n`
        }
      } catch (e) {
        console.error('pickProjectRoot failed:', e)
        this.logs += `[项目目录] ❌ 选择失败：${e.message}\n`
      } finally {
        this.picking = false
      }
    },
    async saveAutoEnterPreference() {
      const result = await window.electronAPI.setAutoEnterFrontend(this.autoEnterFrontend)
      if (!result?.ok) {
        this.launchError = `保存启动偏好失败：${result?.error || '未知错误'}`
      }
    },
    /**
     * 触发一键 bootstrap（uv → redis → sandbox → venv → mcp → backend）。
     * 完成后由主进程 broadcast servicesReady=true，App.vue 翻 appReady=true，
     * SetUpView 自动消失，主界面 mount + 加载会话。
     *
     * 按钮永远只走 bootstrap 这条路径；服务已就绪时按钮 disabled（mounted 期间由
     * App.vue 的 getServicesReady=true 触发 appReady=true 直接切走，SetUpView 根本不会渲染）。
     */
    async launch() {
      this.launchError = ''

      if (!this.projectRoot.ok) {
        this.launchError = '请先选择项目目录'
        return
      }
      for (const item of this.items) {
        if (!item.ok) {
          this.launchError = `请先配置 ${item.label}`
          return
        }
      }

      this.launching = true
      this.logs += '\n[启动] 一键部署开始...\n'
      try {
        const result = await window.electronAPI.bootstrap({
          autoEnterFrontend: this.autoEnterFrontend,
        })
        if (!result?.ok) {
          this.launchError = result?.error || '启动失败'
          this.logs += `[启动] ❌ 失败：${this.launchError}\n`
        }
        // 成功路径：主进程会广播 services-ready-changed，App.vue 接管翻 appReady=true。
        // 防御性兜底：主进程 setServicesReady 有「servicesReady === ready 早返回」去重，
        // 若之前的 broadcast 被 renderer 错过，第二次 bootstrap 不会重发 broadcast，
        // 这里主动拉一次 servicesReady 同步状态 → 仍然 ready 且用户勾了自动进 → emit enter-app
        // 让 App.vue 的 onEnterApp 兜底翻 appReady=true（idempotent，不会与 broadcast 路径重复）。
        if (result?.ok && this.autoEnterFrontend && window.electronAPI?.getServicesReady) {
          const ready = await window.electronAPI.getServicesReady()
          if (ready) this.$emit('enter-app')
        }
      } catch (e) {
        this.launchError = e.message || '启动失败'
        this.logs += `[启动] ❌ 异常：${this.launchError}\n`
      } finally {
        this.launching = false
      }
    },
    getStatusClass(item) {
      if (item.fixing) return 'fixing'
      if (item.ok) return 'ok'
      return 'fail'
    },
    getStatusIcon(item) {
      if (item.fixing) return '⋯'
      if (item.ok) return '✓'
      return '✗'
    },
    /**
     * bootstrap 已完成 + 用户没勾自动进 → 用户手动点「进入应用」。
     * 通知父级 (App.vue) 翻 appReady=true + initConversationState。
     * 不要直接翻 this.$root.appReady 之类——App.vue 是真相源，统一走 emit。
     */
    enterApp() {
      this.$emit('enter-app')
    },
  },
}
</script>

<style scoped>
/*
 * 浮窗形式：fixed 全屏 overlay + 半透明 backdrop + 居中卡片。
 * 渲染层永远叠加在主界面之上（App.vue 控制 v-if），主界面始终在 DOM 里 mount 着，
 * bootstrap 完成 → SetUpView 卸载 → 主界面从「灰显禁用」变可交互，零窗口创建/销毁竞态。
 */
.setup-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  /* 浮窗本身不需要背景色——backdrop 单独做半透明 + 模糊 */
  background: transparent;
  pointer-events: auto;
  animation: setup-fade-in 0.2s ease-out;
}

.setup-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.setup-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 640px;
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  background: var(--bg-secondary, #ffffff);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  padding: 32px;
  display: flex;
  flex-direction: column;
  animation: setup-card-in 0.25s ease-out;
}

@keyframes setup-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes setup-card-in {
  from { opacity: 0; transform: translateY(-8px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0)    scale(1);    }
}

.setup-header {
  margin-bottom: 24px;
}

.setup-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary, #1d1d1f);
}

.subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary, #6e6e73);
}

.check-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.check-item {
  display: flex;
  align-items: center;
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-tertiary, #f5f5f7);
  border: 1px solid transparent;
  transition: all 0.2s;
}

.check-item.ok {
  border-color: var(--success-color, #34c759);
  background: var(--success-bg, rgba(52, 199, 89, 0.08));
}

.check-item.fail {
  border-color: var(--danger-color, #ff3b30);
  background: var(--danger-bg, rgba(255, 59, 48, 0.05));
}

.check-item.fixing {
  border-color: var(--warning-color, #ff9500);
  background: var(--warning-bg, rgba(255, 149, 0, 0.05));
}

.check-item .icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 16px;
  margin-right: 12px;
}

.check-item.ok .icon { color: var(--success-color, #34c759); }
.check-item.fail .icon { color: var(--danger-color, #ff3b30); }
.check-item.fixing .icon { color: var(--warning-color, #ff9500); }

.check-item .info {
  flex: 1;
  min-width: 0;
}

.check-item .label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary, #1d1d1f);
}

.check-item .detail {
  font-size: 12px;
  color: var(--text-secondary, #6e6e73);
  margin-top: 2px;
  word-break: break-all;
}

.check-item .action {
  margin-left: 12px;
}

.btn-fix, .btn-download {
  padding: 4px 12px;
  font-size: 12px;
  border: 1px solid var(--accent-color, #007aff);
  background: transparent;
  color: var(--accent-color, #007aff);
  border-radius: 6px;
  cursor: pointer;
  text-decoration: none;
  display: inline-block;
}

.btn-fix:hover, .btn-download:hover {
  background: var(--accent-color, #007aff);
  color: white;
}

.fixing-indicator {
  font-size: 12px;
  color: var(--warning-color, #ff9500);
}

.log-box {
  background: #1d1d1f;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  max-height: 160px;
  min-height: 80px;
  overflow-y: auto;
}

.log-box pre {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-placeholder {
  font-size: 12px;
  color: #6e6e73;
  font-style: italic;
}

.auto-enter-option {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  font-size: 13px;
  color: var(--text-primary, #1d1d1f);
  cursor: pointer;
}

.auto-enter-option input {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: var(--accent-color, #007aff);
}

.auto-enter-option:has(input:disabled) {
  opacity: 0.55;
  cursor: not-allowed;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn-secondary, .btn-primary {
  padding: 8px 20px;
  font-size: 14px;
  border-radius: 6px;
  cursor: pointer;
  border: none;
  transition: opacity 0.2s;
}

.btn-secondary {
  background: var(--bg-tertiary, #f5f5f7);
  color: var(--text-primary, #1d1d1f);
}

.btn-primary {
  background: var(--accent-color, #007aff);
  color: white;
}

.btn-secondary:disabled, .btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-bar {
  margin-top: 12px;
  padding: 10px 14px;
  background: var(--danger-bg, rgba(255, 59, 48, 0.1));
  color: var(--danger-color, #ff3b30);
  border-radius: 6px;
  font-size: 13px;
}
</style>