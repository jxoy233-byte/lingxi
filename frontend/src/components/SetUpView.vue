<template>
  <div class="setup-container">
    <div class="setup-card">
      <div class="setup-header">
        <h2>灵析 启动配置</h2>
        <p class="subtitle">首次启动需要检测并配置以下依赖项</p>
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
        <div v-else class="log-placeholder">点击"配置"按钮后，这里会显示实时日志</div>
      </div>

      <div class="actions">
        <button class="btn-secondary" @click="recheck" :disabled="checking || launching">
          {{ checking ? '检测中...' : '重新检测' }}
        </button>
        <button
          class="btn-primary"
          :disabled="!allOk || launching"
          @click="launch"
        >
          {{ launching ? '启动中...' : '启动应用' }}
        </button>
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
  data() {
    return {
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
          id: 'uv',
          label: 'uv（Python 包管理）',
          canAutoFix: true,
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
        {
          id: 'redis',
          label: 'Redis 容器',
          canAutoFix: true,
          ok: false,
          detail: '',
          fixing: false,
        },
        {
          id: 'sandbox',
          label: '代码沙盒镜像',
          canAutoFix: true,
          ok: false,
          detail: '',
          fixing: false,
        },
        {
          id: 'venv',
          label: 'Python 依赖（.venv）',
          canAutoFix: true,
          ok: false,
          detail: '',
          fixing: false,
        },
      ],
      logs: '',
      checking: false,
      launching: false,
      launchError: '',
    }
  },
  computed: {
    allOk() {
      return this.items.every(i => i.ok)
    },
  },
  async mounted() {
    await this.recheck()
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
  },
  methods: {
    async recheck() {
      this.checking = true
      try {
        const results = await window.electronAPI.probeAll()
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
    async fixOne(item) {
      item.fixing = true
      this.logs += `\n[${item.label}] 开始配置...\n`
      const result = await window.electronAPI.fixItem(item.id)
      item.fixing = false
      if (result.ok) {
        this.logs += `[${item.label}] ✅ 配置完成\n\n`
        await this.recheck()
      } else {
        this.logs += `[${item.label}] ❌ 配置失败：${result.error}\n\n`
      }
    },
    async launch() {
      this.launching = true
      this.launchError = ''
      this.logs += '\n[启动] 先启动 MCP 服务，再启动后端...\n'
      const result = await window.electronAPI.launch()
      if (!result.ok) {
        this.launchError = result.error
        this.logs += `[启动] ❌ 失败：${result.error}\n`
        this.launching = false
      }
      // 成功路径：main 进程会触发 startup:ready 事件，App.vue 切到主界面
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
  },
}
</script>

<style scoped>
.setup-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--bg-primary, #f5f5f7);
  padding: 24px;
}

.setup-card {
  width: 100%;
  max-width: 640px;
  background: var(--bg-secondary, #ffffff);
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  padding: 32px;
  display: flex;
  flex-direction: column;
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