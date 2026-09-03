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
          <!-- 左侧导航：纯文字标签。
               ↑ / ↓（或 ← / →）切 tab，Enter 直接应用（与点击等价）。
               焦点挂在 nav 上，keydown 监听在 nav，不抢全局其他 keydown。 -->
          <nav
            class="settings-nav"
            tabindex="-1"
            ref="nav"
            @keydown="handleTabKeydown"
          >
            <button
              v-for="tab in tabs"
              :key="tab.key"
              :ref="'tab_' + tab.key"
              :class="['nav-item', { active: activeTab === tab.key }]"
              @click="selectTab(tab.key)"
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

                <!-- VL 专用：local 开关（决定是否走独立视觉模型 vs fallback 主用 LLM） -->
                <div v-if="name === 'vl'" class="field">
                  <label class="toggle-label">
                    <input
                      type="checkbox"
                      :checked="prov.local !== false"
                      @change="prov.local = $event.target.checked"
                    />
                    <span>使用独立视觉模型 (local)</span>
                  </label>
                  <p class="field-hint">
                    勾选：用下方专属 <code>Model / Base URL / API Key</code> 跑视觉任务（默认 Qwen3-VL-2B 本地模型）。<br>
                    <strong>不勾选（local=false）</strong>：忽略下方三个字段，<strong>fallback 到主用 LLM</strong>
                    （取 <code>llm_providers</code> 中第一个有效 provider，已自动 main→backup 切换），
                    适用于「不想额外配 VL、让主模型兼职看图」的场景。<br>
                    改动需重启后端生效 —— <code>local</code> 字段决定是否加载本地模型到内存。
                  </p>
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

            <!-- Skills -->
            <section v-else-if="activeTab === 'skills'" class="section">
              <div class="section-header">
                <h4>Skills API Keys</h4>
                <p class="section-desc">搜索技能所需。修改后需重启后端。</p>
              </div>
              <div class="group">
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

            <!-- Permissions -->
            <section v-else-if="activeTab === 'permissions'" class="section">
              <div class="section-header">
                <h4>Tool Permissions</h4>
                <p class="section-desc">
                  控制 LLM 跑 <code>cmd</code> / <code>code</code> 工具时是否询问。
                  改动需重启后端生效（Permissions 单例是启动时缓存的）。
                </p>
              </div>

              <div class="group">
                <div class="group-title">审批策略</div>
                <div class="policy-row">
                  <label
                    v-for="opt in policyOptions"
                    :key="opt.value"
                    :class="['policy-pill', { active: formConfig.permissions.approval_policy === opt.value }]"
                  >
                    <input type="radio" :value="opt.value" v-model="formConfig.permissions.approval_policy" />
                    <span class="policy-label">{{ opt.label }}</span>
                    <span class="policy-desc">{{ opt.desc }}</span>
                  </label>
                </div>
              </div>

              <div class="group">
                <div class="group-title">
                  已批准命令
                  <span class="tag">{{ formConfig.permissions.approved_commands.length }}</span>
                </div>
                <p class="field-hint" style="margin-bottom: 10px;">
                  同 pattern 命中后自动放行。点击 × 撤销授权。
                </p>
                <div v-if="formConfig.permissions.approved_commands.length === 0" class="empty-list">
                  还没有任何已批准命令
                </div>
                <div v-else class="cmd-list">
                  <div
                    v-for="(cmd, idx) in formConfig.permissions.approved_commands"
                    :key="cmd.pattern + idx"
                    class="cmd-row"
                  >
                    <div class="cmd-pattern">{{ cmd.pattern }}</div>
                    <div class="cmd-meta">
                      <span class="cmd-scope">{{ cmd.scope || 'global' }}</span>
                      <span class="cmd-time">{{ cmd.approved_at || '' }}</span>
                    </div>
                    <button class="cmd-delete" @click="removeApproved(idx)" aria-label="撤销">×</button>
                  </div>
                </div>
              </div>

              <div class="group">
                <div class="group-title">
                  已拒绝命令
                  <span class="tag">{{ formConfig.permissions.denied_commands.length }}</span>
                </div>
                <p class="field-hint" style="margin-bottom: 10px;">
                  同 pattern 命中后直接拦截。点击 × 撤销拒绝。
                </p>
                <div v-if="formConfig.permissions.denied_commands.length === 0" class="empty-list">
                  还没有任何已拒绝命令
                </div>
                <div v-else class="cmd-list">
                  <div
                    v-for="(cmd, idx) in formConfig.permissions.denied_commands"
                    :key="cmd.pattern + idx"
                    class="cmd-row"
                  >
                    <div class="cmd-pattern">{{ cmd.pattern }}</div>
                    <div class="cmd-meta">
                      <span class="cmd-time">{{ cmd.denied_at || '' }}</span>
                    </div>
                    <button class="cmd-delete" @click="removeDenied(idx)" aria-label="撤销">×</button>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>

        <!-- 底部 -->
        <div class="settings-footer">
          <div class="footer-hint">
            <span v-if="activeTab === 'appearance'">主题实时生效</span>
            <span v-else-if="activeTab === 'llm'">模型配置改动需重启后端</span>
            <span v-else-if="activeTab === 'skills'">API key 改动后下次调用立即生效（无需重启）</span>
            <span v-else-if="activeTab === 'permissions'">审批配置改动后下次执行立即生效（无需重启）</span>
            <span v-else>配置改动需重启后端</span>
          </div>
          <div class="footer-actions">
            <button class="btn-text" @click="close" :disabled="saving || restarting">Cancel</button>
            <button class="btn-text" @click="saveOnly" :disabled="saving || restarting || activeTab === 'appearance'">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
            <!-- Save & Restart 只在 llm tab 显示：模型连接字段（ChatOpenAI / Redis / VL weights
                 是启动期常驻对象，写 config 不影响已构造的 client，必须重启才生效。
                 permissions / skills / appearance 都是热加载，不需要重启按钮。 -->
            <button v-if="activeTab === 'llm'" class="btn-primary" @click="saveAndRestart" :disabled="saving || restarting">
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
        { key: 'skills', label: 'Skills' },
        { key: 'permissions', label: 'Permissions' }
      ],
      themeOptions: [
        { value: 'light', label: 'Light' },
        { value: 'dark', label: 'Dark' }
      ],
      theme: 'light',
      policyOptions: [
        { value: 'default', label: 'Default', desc: '敏感命令（写/code/网络）每次执行前询问' },
        { value: 'yolo', label: 'Yolo', desc: '全部放行（硬危险命令仍拦截）' }
      ],

      loading: false,
      loadError: '',
      formConfig: {
        llm_providers: {},
        skills: {},
        permissions: { approval_policy: 'default', approved_commands: [], denied_commands: [] }
      },
      // loadConfig 拉到的初始快照（脱敏前的版本，用于 buildPayload 计算 diff）
      // 用户编辑 formConfig 时不动这个；保存时只发有差异的段，避免"在 permissions tab
      // 改一字段却把 llm_providers 全部字段带上去"导致后端误判为 llm 段变更
      // （saved_segments=['llm_providers'] → restart_required=true 的根因）。
      originalConfig: null,

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
        // 把焦点抢到 nav 上，↑/↓ 立刻能切 tab
        this.$nextTick(() => {
          const nav = this.$refs.nav
          if (nav && nav.focus) nav.focus()
        })
      } else {
        this.cleanupTimer()
      }
    },
    theme(newVal) {
      this.$emit('theme-change', newVal === 'dark')
    }
  },
  mounted() {
    document.addEventListener('keydown', this.handleKeydown)
  },
  beforeDestroy() {
    document.removeEventListener('keydown', this.handleKeydown)
  },
  methods: {
    close() {
      this.cleanupTimer()
      this.$emit('close')
    },
    /**
     * 左侧 nav 键盘导航：
     *   - ↑ / ↓ (或 ← / →): 切 tab（夹紧边界）
     *   - Enter / Space: 显式应用当前 active tab（与点击等价 —— 通常 active 已是高亮，
     *                   但 Enter 让焦点明确表达"就是这个"）
     * 监听挂在 nav 容器上，open 时 .focus() 把键盘焦点拉过来。
     * Save 按钮 Enter 走原浏览器行为不被劫持（监听只在 nav 内部冒泡到这里时触发）。
     */
    handleTabKeydown(e) {
      const list = this.tabs
      if (!list || list.length === 0) return
      let idx = list.findIndex(t => t.key === this.activeTab)
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault()
        idx = Math.min(idx + 1, list.length - 1)
        this.selectTab(list[idx].key)
      } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault()
        idx = Math.max(idx - 1, 0)
        this.selectTab(list[idx].key)
      } else if (e.key === 'Home') {
        e.preventDefault()
        this.selectTab(list[0].key)
      } else if (e.key === 'End') {
        e.preventDefault()
        this.selectTab(list[list.length - 1].key)
      }
    },
    selectTab(key) {
      this.activeTab = key
      // 滚动 nav 让当前 tab 可见（nav 通常可滚动时才有意义）
      this.$nextTick(() => {
        const nav = this.$refs.nav
        const el = this.$refs['tab_' + key]
        if (!nav || !el || !el[0]) return
        const itemTop = el[0].offsetTop
        const itemBottom = itemTop + el[0].offsetHeight
        const viewTop = nav.scrollTop
        const viewBottom = viewTop + nav.clientHeight
        if (itemTop < viewTop) nav.scrollTop = itemTop - 4
        else if (itemBottom > viewBottom) nav.scrollTop = itemBottom - nav.clientHeight + 4
      })
    },
    /**
     * 弹窗可见时响应 Esc → 关闭。Save 按钮 Enter 提交让浏览器原生处理
     * （input focus 时 Enter 触发表单 submit / button click，不需要劫持）。
     * 这里只补 Esc，避免和 Save 按钮的原生 Enter 行为冲突。
     */
    handleKeydown(e) {
      if (!this.visible) return
      if (this.restarting || this.saving) return
      if (e.key === 'Escape') {
        e.preventDefault()
        this.close()
      }
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
        cfg.skills = cfg.skills || {}
        cfg.permissions = cfg.permissions || { approval_policy: 'default', approved_commands: [], denied_commands: [] }
        cfg.permissions.approved_commands = cfg.permissions.approved_commands || []
        cfg.permissions.denied_commands = cfg.permissions.denied_commands || []

        // 存一份脱敏前的快照给 buildPayload 做 diff：
        // originalConfig 里 api_key 是 masked 串（真值的 4*4 形式），
        // formConfig 里 api_key 是空字符串——diff 时两边都是"未修改"状态（用户输入新值
        // 后 formConfig 里的空字符串会被替换，diff 能识别）。
        this.originalConfig = JSON.parse(JSON.stringify(cfg))

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
    removeApproved(idx) {
      this.formConfig.permissions.approved_commands.splice(idx, 1)
    },
    removeDenied(idx) {
      this.formConfig.permissions.denied_commands.splice(idx, 1)
    },
    async saveOnly() {
      this.saving = true
      try {
        const payload = this.buildPayload()
        const result = await putConfig(payload)
        this.flashTip(this._tipForResult(result))
        // 保存成功即关闭 dialog（permissions / skills 等可热加载段无需重启），
        // 下次打开 dialog 时 watch.visible 钩子会自动 loadConfig() 拉最新脱敏状态。
        // ⚠️ 不要在这里 await loadConfig() 重拉：会覆盖用户当前正在编辑的 input
        // 里的真值为空字符串（脱敏不入 form），看起来像"点了没反应"。
        this.close()
      } catch (e) {
        alert('保存失败：' + (e.message || e))
      } finally {
        // 必须 finally 重置：dialog 是单例组件（v-if 控制可见），close 后 saving 仍
        // 是 true 会让下次打开 dialog 时所有按钮 disabled。原来的 finally 被去掉
        // 是个 bug，现在补回。
        this.saving = false
      }
    },
    _tipForResult(result) {
      // 后端可能未升级（缺 saved_segments 字段）→ 兼容 fallback 到 restart_required
      const segments = result.saved_segments || []
      const hasLlm = segments.includes('llm_providers')
      const hotSegments = segments.filter(s => s !== 'llm_providers')

      if (segments.length === 0) {
        return '已保存'
      }
      if (hasLlm && hotSegments.length > 0) {
        // 混合：permissions/skills 立即生效 + llm 重启生效
        const hotLabels = hotSegments.map(s =>
          s === 'permissions' ? '审批配置' : 'API key'
        ).join(' + ')
        return `已保存：${hotLabels} 立即生效，模型配置重启后端后生效`
      }
      if (hasLlm) {
        return '已保存，重启后端后生效'
      }
      // 纯 permissions / 纯 skills / 两者皆有 → 都热加载
      return '已保存，立即生效'
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
      // 只发跟 originalConfig 对比有修改的段（llm_providers / skills / permissions）。
      // 旧实现把整个 formConfig 都 PUT 出去，导致在 Permissions tab 改一个字段
      // 也会把 llm_providers 全部字段带上 → 后端 saved_segments=['llm_providers']
      // → restart_required=true（实际上 llm 段值没变，但后端无法区分）。
      const payload = {}
      const original = this.originalConfig || {}
      for (const topKey of ['llm_providers', 'skills', 'permissions']) {
        const cur = this.formConfig[topKey] || {}
        const orig = original[topKey] || {}
        const diff = this._deepDiff(cur, orig)
        if (diff !== null) {
          payload[topKey] = diff
        }
      }

      // 保留旧逻辑：脱敏后的空 api_key 不入 payload
      // （用户没填 key 时空字符串不能当真值发出去，会覆盖后端真值）
      if (payload.llm_providers) {
        for (const prov of Object.values(payload.llm_providers)) {
          if (prov && prov.api_key === '') delete prov.api_key
        }
      }
      if (payload.skills) {
        for (const k of Object.keys(payload.skills)) {
          if (k.endsWith('_api_key') && payload.skills[k] === '') {
            delete payload.skills[k]
          }
        }
      }

      // 段级别二次过滤：清空空 api_key 后某段可能完全无字段（如 skills 段只改了
      // 一个空 api_key）→ 不计入 saved_segments
      for (const topKey of ['llm_providers', 'skills', 'permissions']) {
        if (payload[topKey] && Object.keys(payload[topKey]).length === 0) {
          delete payload[topKey]
        }
      }

      // 递归清空空对象：_deepDiff 后可能产出像
      // `{llm_providers: {model1: {}, model2: {}, vl: {}}, permissions: {approval_policy: 'yolo'}}`
      // —— llm_providers 段还在但所有 provider 都是空对象（用户没改 llm 任何字段，只
      // 改了 api_key 被二次过滤删了）。递归剥掉空对象，让 payload 干净：
      // `{permissions: {approval_policy: 'yolo'}}`。
      // 空数组保留（approved_commands=[] 是有意义的状态）。
      return this._stripEmptyObjects(payload)
    },
    _stripEmptyObjects(obj) {
      // 递归清空空对象（仅剥"无子字段"的 {}；非空对象、标量、数组包括空数组都保留）
      // 必须递归：例如 payload.llm_providers = {model1: {}, model2: {}, vl: {}}
      // 顶层 llm_providers 非空（3 个 key），但内部每个 provider 都是空对象——需要
      // 一路剥到叶子，让 llm_providers 自身也变 {}，再被段级过滤删掉。
      if (Array.isArray(obj)) return obj
      if (typeof obj !== 'object' || obj === null) return obj

      const result = {}
      for (const [k, v] of Object.entries(obj)) {
        const processed = (typeof v === 'object' && v !== null && !Array.isArray(v))
          ? this._stripEmptyObjects(v)
          : v
        if (typeof processed === 'object' && processed !== null && !Array.isArray(processed) && Object.keys(processed).length === 0) {
          continue
        }
        result[k] = processed
      }
      return result
    },
    _deepDiff(current, original) {
      // 递归计算 current 相对 original 的差异：
      // - 完全一致 → 返回 null（调用方据此跳过该段）
      // - 有差异 → 返回 current 里不一致的部分（含子对象递归）
      // - 数组：用 JSON.stringify 整段对比（顺序敏感）
      // - 标量：直接 !==
      if (current === original) return null

      if (Array.isArray(current)) {
        return JSON.stringify(current) !== JSON.stringify(original || [])
          ? current
          : null
      }

      if (typeof current !== 'object' || current === null) {
        return current !== original ? current : null
      }

      // 对象：递归对比每个 key
      const result = {}
      let hasDiff = false
      const allKeys = new Set([
        ...Object.keys(current || {}),
        ...Object.keys(original || {}),
      ])
      for (const k of allKeys) {
        const curVal = current?.[k]
        const origVal = original?.[k]
        const subDiff = this._deepDiff(curVal, origVal)
        if (subDiff !== null) {
          result[k] = subDiff
          hasDiff = true
        }
      }
      return hasDiff ? result : null
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
  /* nav 自动 focus 接收 ↑↓/←→ 等键盘事件，不该显示浏览器默认黑 focus ring */
  outline: none;
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

/* checkbox 跟文字同行 —— 用于 vl.local 开关 */
.toggle-label {
  display: inline-flex !important;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px !important;
  font-weight: 500 !important;
  color: var(--text-primary) !important;
}
.toggle-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  margin: 0;
  cursor: pointer;
  accent-color: var(--text-primary);
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

/* ===== Permissions: policy picker ===== */
.policy-row {
  display: flex;
  gap: 8px;
}
.policy-pill {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  background: transparent;
  transition: border-color 0.12s, background 0.12s;
}
.policy-pill:hover { border-color: var(--text-secondary); }
.policy-pill.active {
  border-color: var(--text-primary);
  background: var(--bg-hover);
}
.policy-pill input { display: none; }
.policy-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.policy-desc {
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.4;
}

/* ===== Permissions: approved/denied lists ===== */
.empty-list {
  font-size: 12.5px;
  color: var(--text-secondary);
  font-style: italic;
  padding: 8px 0;
}
.cmd-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}
.cmd-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
}
.cmd-pattern {
  font-family: 'SF Mono', 'Menlo', monospace;
  font-size: 12px;
  color: var(--text-primary);
  word-break: break-all;
}
.cmd-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
  color: var(--text-secondary);
}
.cmd-scope {
  font-family: 'SF Mono', 'Menlo', monospace;
  background: var(--bg-hover);
  padding: 1px 6px;
  border-radius: 4px;
}
.cmd-time {
  font-family: 'SF Mono', 'Menlo', monospace;
}
.cmd-delete {
  width: 22px;
  height: 22px;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s;
}
.cmd-delete:hover {
  background: #fee2e2;
  color: #b91c1c;
  border-color: #fca5a5;
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
  /* 固定中灰背景（不跟主题翻黑/翻白）—— 用户偏好柔和的提示色调 */
  background: #6b7280;
  color: #ffffff;
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