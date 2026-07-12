<template>
  <transition name="modal">
    <div v-if="visible" class="settings-overlay" @click.self="close">
      <div class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <!-- 头部 -->
        <div class="settings-header">
          <h3 id="settings-title">Settings</h3>
          <button class="settings-close" @click="close" aria-label="关闭">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div class="settings-body">
          <!-- 左侧导航：纯文字标签 -->
          <nav class="settings-nav">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              :class="['nav-item', { active: activeTab === tab.key }]"
              @click="activeTab = tab.key"
            >
              {{ tab.label }}
            </button>
          </nav>

          <!-- 右侧内容 -->
          <div class="settings-content">
            <!-- 加载中 -->
            <div v-if="loading" class="state-msg">加载中...</div>

            <!-- 错误 -->
            <div v-else-if="loadError" class="state-msg">
              <span>{{ loadError }}</span>
              <button class="link-btn" @click="loadConfig">重试</button>
            </div>

            <!-- Appearance -->
            <section v-else-if="activeTab === 'appearance'" class="section">
              <div class="section-header">
                <h4>Theme</h4>
                <p class="section-desc">切换主题立即生效。</p>
              </div>
              <div class="theme-row">
                <label
                  v-for="opt in themeOptions"
                  :key="opt.value"
                  :class="['theme-pill', { active: theme === opt.value }]"
                >
                  <input type="radio" :value="opt.value" v-model="theme" />
                  <span class="pill-dot" :class="opt.value"></span>
                  <span>{{ opt.label }}</span>
                </label>
              </div>
            </section>

            <!-- Models -->
            <section v-else-if="activeTab === 'llm'" class="section">
              <div class="section-header">
                <h4>Models</h4>
                <p class="section-desc">LLM 提供方配置。修改后需重启后端。</p>
              </div>
              <div v-for="(prov, name) in formConfig.llm_providers" :key="name" class="group">
                <div class="group-title">
                  {{ providerLabel(name) }}
                  <span v-if="name === 'vl'" class="tag">vision</span>
                </div>
                <div class="field">
                  <label>Model</label>
                  <input v-model="prov.model_name" type="text" placeholder="如 gpt-4o" />
                </div>
                <div class="field">
                  <label>Base URL</label>
                  <input v-model="prov.base_url" type="text" placeholder="如 https://api.openai.com/v1" />
                </div>
                <div class="field">
                  <label>API Key</label>
                  <div class="password-wrap">
                    <input
                      v-model="prov.api_key"
                      :type="showKey[name] ? 'text' : 'password'"
                      placeholder="留空表示不修改"
                      autocomplete="off"
                    />
                    <button
                      type="button"
                      class="toggle-eye"
                      :title="showKey[name] ? '隐藏' : '显示'"
                      @click="showKey[name] = !showKey[name]"
                    >
                      {{ showKey[name] ? 'Hide' : 'Show' }}
                    </button>
                  </div>
                  <p class="field-hint">已脱敏。留空 = 保留原 key；填写 = 覆盖。</p>
                </div>
              </div>
            </section>

            <!-- MCP -->
            <section v-else-if="activeTab === 'mcp'" class="section">
              <div class="section-header">
                <h4>MCP Server</h4>
                <p class="section-desc">MCP 工具服务器。修改后需重启后端。</p>
              </div>
              <div class="group">
                <div class="field">
                  <label>URL</label>
                  <input v-model="formConfig.mcp_server.url" type="text" placeholder="http://127.0.0.1:18080/streamable" />
                </div>
                <div class="field">
                  <label>Transport</label>
                  <select v-model="formConfig.mcp_server.transport">
                    <option value="streamable_http">streamable_http</option>
                    <option value="sse">sse</option>
                  </select>
                </div>
              </div>
            </section>

            <!-- Skills -->
            <section v-else-if="activeTab === 'skills'" class="section">
              <div class="section-header">
                <h4>Skills API Keys</h4>
                <p class="section-desc">搜索技能所需。修改后需重启后端。</p>
              </div>
              <div class="group">
                <div class="field">
                  <label>Bocha</label>
                  <div class="password-wrap">
                    <input
                      v-model="formConfig.skills.bocha_api_key"
                      :type="showKey.bocha_api_key ? 'text' : 'password'"
                      placeholder="留空表示不修改"
                      autocomplete="off"
                    />
                    <button type="button" class="toggle-eye" @click="showKey.bocha_api_key = !showKey.bocha_api_key">
                      {{ showKey.bocha_api_key ? 'Hide' : 'Show' }}
                    </button>
                  </div>
                  <p class="field-hint">已脱敏。留空 = 保留原 key；填写 = 覆盖。</p>
                </div>
                <div class="field">
                  <label>Exa</label>
                  <div class="password-wrap">
                    <input
                      v-model="formConfig.skills.exa_api_key"
                      :type="showKey.exa_api_key ? 'text' : 'password'"
                      placeholder="留空表示不修改"
                      autocomplete="off"
                    />
                    <button type="button" class="toggle-eye" @click="showKey.exa_api_key = !showKey.exa_api_key">
                      {{ showKey.exa_api_key ? 'Hide' : 'Show' }}
                    </button>
                  </div>
                  <p class="field-hint">已脱敏。留空 = 保留原 key；填写 = 覆盖。</p>
                </div>
                <div class="field">
                  <label>Tavily</label>
                  <div class="password-wrap">
                    <input
                      v-model="formConfig.skills.tavily_api_key"
                      :type="showKey.tavily_api_key ? 'text' : 'password'"
                      placeholder="留空表示不修改"
                      autocomplete="off"
                    />
                    <button type="button" class="toggle-eye" @click="showKey.tavily_api_key = !showKey.tavily_api_key">
                      {{ showKey.tavily_api_key ? 'Hide' : 'Show' }}
                    </button>
                  </div>
                  <p class="field-hint">已脱敏。留空 = 保留原 key；填写 = 覆盖。</p>
                </div>
              </div>
            </section>
          </div>
        </div>

        <!-- 底部 -->
        <div class="settings-footer">
          <div class="footer-hint">
            <span v-if="activeTab === 'appearance'">主题实时生效</span>
            <span v-else>配置改动需重启后端</span>
          </div>
          <div class="footer-actions">
            <button class="btn-text" @click="close" :disabled="saving || restarting">Cancel</button>
            <button class="btn-text" @click="saveOnly" :disabled="saving || restarting || activeTab === 'appearance'">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
            <button class="btn-primary" @click="saveAndRestart" :disabled="saving || restarting || activeTab === 'appearance'">
              {{ restarting ? 'Restarting...' : 'Save & Restart' }}
            </button>
          </div>
        </div>

        <!-- 重启遮罩 -->
        <transition name="fade">
          <div v-if="restarting" class="restart-mask">
            <div class="restart-card">
              <div class="spinner"></div>
              <h4>Restarting backend</h4>
              <p>This will take a few seconds.</p>
              <p class="restart-progress">{{ restartElapsed }}s</p>
            </div>
          </div>
        </transition>
      </div>
    </div>
  </transition>
</template>

<script>
import { getConfig, putConfig, restartBackend, healthCheck } from '@/utils/api.js'

export default {
  name: 'SettingsDialog',
  props: {
    visible: { type: Boolean, default: false },
    isDarkTheme: { type: Boolean, default: false }
  },
  emits: ['close', 'theme-change'],
  data() {
    return {
      activeTab: 'appearance',
      tabs: [
        { key: 'appearance', label: 'Appearance' },
        { key: 'llm', label: 'Models' },
        { key: 'mcp', label: 'MCP' },
        { key: 'skills', label: 'Skills' }
      ],
      themeOptions: [
        { value: 'light', label: 'Light' },
        { value: 'dark', label: 'Dark' }
      ],
      theme: 'light',

      loading: false,
      loadError: '',
      formConfig: {
        llm_providers: {},
        mcp_server: { url: '', transport: 'streamable_http' },
        skills: {}
      },

      showKey: {},

      saving: false,
      restarting: false,
      restartElapsed: 0,
      restartTimer: null
    }
  },
  watch: {
    visible(val) {
      if (val) {
        this.activeTab = 'appearance'
        this.theme = this.isDarkTheme ? 'dark' : 'light'
        this.loadConfig()
      } else {
        this.cleanupTimer()
      }
    },
    theme(newVal) {
      this.$emit('theme-change', newVal === 'dark')
    }
  },
  methods: {
    close() {
      this.cleanupTimer()
      this.$emit('close')
    },
    providerLabel(name) {
      const map = { model1: 'Primary model', model2: 'Backup model', vl: 'Vision model' }
      return map[name] || name
    },
    async loadConfig() {
      this.loading = true
      this.loadError = ''
      try {
        const resp = await getConfig()
        const cfg = JSON.parse(JSON.stringify(resp.config || {}))
        cfg.llm_providers = cfg.llm_providers || {}
        cfg.mcp_server = cfg.mcp_server || { url: '', transport: 'streamable_http' }
        cfg.skills = cfg.skills || {}

        // 脱敏的 api_key 不入 form（masked 串带回会被当新 key 覆盖真值，401）
        // 留空让 placeholder "留空表示不修改" 显示，buildPayload 会 delete 掉，后端 save_config 跳过
        for (const prov of Object.values(cfg.llm_providers)) {
          if (prov && 'api_key' in prov) prov.api_key = ''
        }
        for (const k of Object.keys(cfg.skills)) {
          if (k.endsWith('_api_key')) cfg.skills[k] = ''
        }

        this.formConfig = cfg
      } catch (e) {
        console.warn('[SettingsDialog] loadConfig failed:', e)
        this.loadError = '加载配置失败：' + (e.message || e)
      } finally {
        this.loading = false
      }
    },
    async saveOnly() {
      this.saving = true
      try {
        const payload = this.buildPayload()
        const result = await putConfig(payload)
        this.flashTip(result.restart_required ? '已保存，重启后端后生效' : '已保存')
      } catch (e) {
        alert('保存失败：' + (e.message || e))
      } finally {
        this.saving = false
      }
    },
    async saveAndRestart() {
      this.saving = true
      try {
        const payload = this.buildPayload()
        await putConfig(payload)
      } catch (e) {
        alert('保存失败：' + (e.message || e))
        this.saving = false
        return
      }
      this.saving = false

      this.restarting = true
      this.restartElapsed = 0
      this.restartTimer = setInterval(() => { this.restartElapsed++ }, 1000)

      try {
        await restartBackend()
      } catch (e) {
        console.warn('[SettingsDialog] restart request ended (expected):', e)
      }

      const ok = await this.pollHealth()
      this.cleanupTimer()

      if (ok) {
        window.location.reload()
      } else {
        this.restarting = false
        alert('重启超时，请检查后端日志并手动重启。')
      }
    },
    buildPayload() {
      const payload = JSON.parse(JSON.stringify(this.formConfig))
      if (payload.llm_providers) {
        for (const prov of Object.values(payload.llm_providers)) {
          if (prov.api_key === '') delete prov.api_key
        }
      }
      if (payload.skills) {
        for (const k of Object.keys(payload.skills)) {
          if (k.endsWith('_api_key') && payload.skills[k] === '') {
            delete payload.skills[k]
          }
        }
      }
      return payload
    },
    async pollHealth(maxWaitSec = 90) {
      // 每 2s 一次：本机启动 VL 模型冷启动可能耗 1 分钟，60s 不够
      for (let i = 0; i < maxWaitSec; i += 2) {
        try {
          await healthCheck()
          return true
        } catch (e) {
          await new Promise(r => setTimeout(r, 2000))
        }
      }
      return false
    },
    cleanupTimer() {
      if (this.restartTimer) {
        clearInterval(this.restartTimer)
        this.restartTimer = null
      }
    },
    flashTip(msg) {
      const tip = document.createElement('div')
      tip.className = 'flash-tip'
      tip.textContent = msg
      document.body.appendChild(tip)
      setTimeout(() => tip.remove(), 2500)
    }
  }
}
</script>

<style scoped>
/* ===== Modal shell ===== */
.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1500;
}

.settings-modal {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  width: 720px;
  max-width: 92vw;
  height: 580px;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ===== Header ===== */
.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-color);
}

.settings-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.settings-close {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}
.settings-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* ===== Body layout ===== */
.settings-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.settings-nav {
  width: 160px;
  flex-shrink: 0;
  border-right: 1px solid var(--border-color);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.nav-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13.5px;
  font-weight: 400;
  transition: background 0.12s, color 0.12s;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.nav-item.active {
  background: var(--bg-hover);
  color: var(--text-primary);
  font-weight: 500;
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
}

/* ===== States ===== */
.state-msg {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 60px 20px;
  color: var(--text-secondary);
  font-size: 13px;
}
.link-btn {
  background: none;
  border: none;
  color: var(--text-primary);
  cursor: pointer;
  text-decoration: underline;
  font-size: 13px;
  padding: 0;
}

/* ===== Section ===== */
.section-header {
  margin-bottom: 20px;
}
.section-header h4 {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}
.section-desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* ===== Theme picker ===== */
.theme-row {
  display: flex;
  gap: 8px;
}
.theme-pill {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary);
  background: transparent;
  transition: border-color 0.12s, background 0.12s;
}
.theme-pill:hover {
  border-color: var(--text-secondary);
}
.theme-pill.active {
  border-color: var(--text-primary);
  background: var(--bg-hover);
}
.theme-pill input { display: none; }
.pill-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  flex-shrink: 0;
}
.pill-dot.light { background: #ffffff; }
.pill-dot.dark { background: #1f2937; }

/* ===== Form groups ===== */
.group {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.group:last-child { margin-bottom: 0; }

.group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.tag {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.04em;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}
.field:last-child { margin-bottom: 0; }
.field label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}
.field input,
.field select {
  width: 100%;
  padding: 8px 10px;
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  transition: border-color 0.12s;
}
.field input:focus,
.field select:focus {
  outline: none;
  border-color: var(--text-primary);
}
.field input::placeholder {
  color: var(--text-secondary);
  opacity: 0.7;
}

.field-hint {
  margin: 4px 0 0;
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.password-wrap {
  position: relative;
  display: flex;
}
.password-wrap input {
  padding-right: 56px;
}
.toggle-eye {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  height: 24px;
  padding: 0 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  border-radius: 4px;
  font-weight: 500;
}
.toggle-eye:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* ===== Footer ===== */
.settings-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-primary);
}
.footer-hint {
  font-size: 12px;
  color: var(--text-secondary);
}
.footer-actions {
  display: flex;
  gap: 6px;
}

.btn-text,
.btn-primary {
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
  font-family: inherit;
}

.btn-text {
  background: transparent;
  color: var(--text-primary);
  border-color: var(--border-color);
}
.btn-text:hover:not(:disabled) {
  background: var(--bg-hover);
}

.btn-primary {
  background: var(--text-primary);
  color: var(--bg-primary);
  border-color: var(--text-primary);
}
.btn-primary:hover:not(:disabled) {
  opacity: 0.88;
}

.btn-text:disabled,
.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== Restart overlay ===== */
.restart-mask {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
  border-radius: 12px;
}
.dark-theme .restart-mask {
  background: rgba(33, 33, 33, 0.85);
}

.restart-card {
  text-align: center;
  padding: 24px;
}
.restart-card h4 {
  margin: 14px 0 4px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.restart-card p {
  margin: 4px 0;
  font-size: 13px;
  color: var(--text-secondary);
}
.restart-progress {
  margin-top: 8px !important;
  font-size: 12px !important;
  color: var(--text-primary) !important;
  font-weight: 500;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 2px solid var(--border-color);
  border-top-color: var(--text-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ===== Transitions ===== */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.18s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

<style>
/* flash-tip 走全局样式（用 document.body 直接 append 的元素走不到 scoped） */
.flash-tip {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--text-primary);
  color: var(--bg-primary);
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  z-index: 2000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  animation: flash-in 0.2s ease-out;
}
@keyframes flash-in {
  from { opacity: 0; transform: translate(-50%, 6px); }
  to { opacity: 1; transform: translate(-50%, 0); }
}
</style>