<!--
  SetupView：安装 / 配置向导浮窗。
  入口：ChatHeader 🪄 按钮 / slash 命令 /setup（任意时刻手动打开）。
  设计：5 step + 完成页（6 个 pane）；浮窗形式（fixed + z-index 1000 + backdrop blur），
  与 BootstrapView 视觉一致，但**非阻塞** —— 用户主界面始终可点。
  复用：getConfig / putConfig / restartBackend / healthCheck（utils/api.js）。
  不复用 SettingsDialog scoped style —— 自带 scoped 副本，保持组件边界清晰。

  步骤：
    0  欢迎页            — 4 类配置简介 + 「开始 / 跳过」
    1  API Key           — llm_providers.model1/2 (model_name/base_url/api_key)
    2  搜索类 Key        — Exa / Tavily（checkbox 启用 + input）
    3  审批 Policy       — approval_policy default/yolo + approved list 折叠
    4  旧版文件解析      — LibreOffice 已装 / 未装（probe-libreoffice IPC）+ 下载链接
    5  完成页            — summary + 「完成 / 仍然跳过」

  进度条 + 顶部 step 导航均按 5 个核心 step 计数（欢迎/完成页不算 step）。
-->
<template>
  <transition name="setup-fade">
    <div v-if="visible" class="setup-overlay" @click.self="onSkipEntire">
      <div class="setup-backdrop"></div>
      <div class="setup-card" role="dialog" aria-modal="true" aria-labelledby="setup-title">
        <!-- ===== Header ===== -->
        <div class="setup-header">
          <div>
            <h3 id="setup-title">安装 / 配置向导</h3>
            <p class="subtitle">四步走完即可正常使用，全部可选，可随时跳过</p>
          </div>
          <button class="setup-close" @click="onSkipEntire" aria-label="关闭">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <!-- ===== Step nav (左侧) ===== -->
        <div class="setup-body">
          <nav class="setup-nav" tabindex="-1" ref="nav">
            <button
              v-for="(s, i) in stepsMeta"
              :key="s.key"
              :ref="'step_' + s.key"
              :class="['step-item', {
                active: currentStep === i,
                done: i < currentStep
              }]"
              @click="goToStep(i)"
              :disabled="loading || saving"
            >
              <span class="step-index">{{ i < currentStep ? '✓' : i + 1 }}</span>
              <span class="step-label">{{ s.label }}</span>
            </button>
          </nav>

          <!-- ===== 右侧内容 ===== -->
          <div class="setup-content">
            <!-- 加载态 -->
            <div v-if="loading" class="state-msg">加载配置中...</div>

            <!-- 错误态 -->
            <div v-else-if="loadError" class="state-msg">
              <span>{{ loadError }}</span>
              <button class="link-btn" @click="loadConfig">重试</button>
            </div>

            <!-- ====== Step 0：欢迎页 ====== -->
            <section v-else-if="currentStep === 0" class="section">
              <div class="section-header">
                <h4>欢迎</h4>
                <p class="section-desc">
                  灵析启动后可立即对话；如果还没配 API Key，部分功能（联网搜索、绘图）可能不可用。
                </p>
              </div>
              <ul class="welcome-list">
                <li><strong>① API Key</strong> — 至少填一个 LLM provider；支持主用 + 备用</li>
                <li><strong>② 搜索 Key</strong> — Exa / Tavily；让 AI 可以联网检索（可选）</li>
                <li><strong>③ 审批策略</strong> — 选择 default（敏感命令每次询问）或 yolo（放行）</li>
                <li><strong>④ Skills</strong> — 已启用 5 个默认预批准；高级里可微调</li>
              </ul>
              <p class="welcome-foot">所有项都可跳过，之后随时从右上角 🪄 按钮再次打开向导。</p>
            </section>

            <!-- ====== Step 1：API Key ====== -->
            <section v-else-if="currentStep === 1" class="section">
              <div class="section-header">
                <h4>API Key</h4>
                <p class="section-desc">主用 LLM 至少填一个 provider；备用用于主用不可用时降级。</p>
              </div>

              <div
                v-for="provName in editableProviderNames"
                :key="provName"
                class="group"
              >
                <div class="group-title">
                  {{ providerLabel(provName) }}
                  <span v-if="currentLlm?.active === provName" class="tag">主用</span>
                </div>

                <div class="field" v-if="provName === 'vl'">
                  <label class="toggle-label">
                    <input
                      type="checkbox"
                      :checked="formConfig.llm_providers.vl.local !== false"
                      @change="formConfig.llm_providers.vl.local = $event.target.checked"
                    />
                    <span>使用独立视觉模型 (local)</span>
                  </label>
                  <p class="field-hint">
                    不勾选（local=false）：忽略下方三字段，<strong>fallback 到主用 LLM</strong>，
                    由主模型兼职看图。<br>
                    <strong>改动需重启后端</strong>生效 —— VL 模型是否加载到内存由 local 字段决定。
                  </p>
                </div>

                <div class="field">
                  <label>Model</label>
                  <input v-model="formConfig.llm_providers[provName].model_name" type="text" placeholder="如 gpt-4o" />
                </div>
                <div class="field">
                  <label>Base URL</label>
                  <input v-model="formConfig.llm_providers[provName].base_url" type="text" placeholder="如 https://api.openai.com/v1" />
                </div>
                <div class="field">
                  <label>API Key</label>
                  <div class="password-wrap">
                    <input
                      v-model="formConfig.llm_providers[provName].api_key"
                      :type="showKey[provName] ? 'text' : 'password'"
                      placeholder="留空表示不修改"
                      autocomplete="off"
                    />
                    <button
                      type="button"
                      class="toggle-eye"
                      @click="showKey[provName] = !showKey[provName]"
                    >{{ showKey[provName] ? 'Hide' : 'Show' }}</button>
                  </div>
                  <p class="field-hint">已脱敏。留空 = 保留原 key；填写 = 覆盖。</p>
                </div>
              </div>
            </section>

            <!-- ====== Step 2：搜索 Key ====== -->
            <section v-else-if="currentStep === 2" class="section">
              <div class="section-header">
                <h4>搜索类 API Key</h4>
                <p class="section-desc">让 AI 能联网检索资料；不需要可跳过这一节。</p>
              </div>
              <div class="group">
                <div
                  v-for="skill in searchSkills"
                  :key="skill.key"
                  class="search-row"
                >
                  <label class="toggle-label">
                    <input
                      type="checkbox"
                      v-model="skillEnabled[skill.key]"
                    />
                    <span class="search-name">{{ skill.label }}</span>
                  </label>
                  <div class="password-wrap search-input-wrap" v-if="skillEnabled[skill.key]">
                    <input
                      :value="skillInputs[skill.key]"
                      @input="skillInputs[skill.key] = $event.target.value"
                      :type="showKey[skill.key] ? 'text' : 'password'"
                      :placeholder="skill.placeholder"
                      autocomplete="off"
                    />
                    <button
                      type="button"
                      class="toggle-eye"
                      @click="showKey[skill.key] = !showKey[skill.key]"
                    >{{ showKey[skill.key] ? 'Hide' : 'Show' }}</button>
                  </div>
                  <span v-else class="search-status">未启用</span>
                </div>
              </div>
            </section>

            <!-- ====== Step 3：审批 Policy ====== -->
            <section v-else-if="currentStep === 3" class="section">
              <div class="section-header">
                <h4>审批策略</h4>
                <p class="section-desc">控制 AI 跑 <code>cmd</code> / <code>code</code> 工具时是否每次询问。</p>
              </div>

              <div class="group">
                <div class="group-title">策略</div>
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
                <button class="advanced-toggle" @click="showAdvanced = !showAdvanced">
                  {{ showAdvanced ? '收起 高级' : '展开 高级（已批准命令）' }}
                </button>
                <div v-if="showAdvanced" class="advanced-block">
                  <div class="group-title">
                    已批准命令
                    <span class="tag">{{ formConfig.permissions.approved_commands.length }}</span>
                  </div>
                  <p class="field-hint" style="margin-bottom: 10px;">
                    向导已默认预批准 5 个核心 skill；高级可单独删某条。
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
                      </div>
                      <button class="cmd-delete" @click="removeApproved(idx)" aria-label="撤销">×</button>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <!-- ====== Step 4：旧版文件解析（LibreOffice） ====== -->
            <section v-else-if="currentStep === 4" class="section">
              <div class="section-header">
                <h4>旧版文件解析（可选）</h4>
                <p class="section-desc">
                  LibreOffice 用于把 <code>.doc</code> / <code>.ppt</code> / <code>.xls</code>
                  等老版本 Office 文件转成 PDF / 图片后让 AI 看。
                  <strong>不装也能用</strong>，只是这类文件不能直接上传解析。
                </p>
              </div>

              <!--
                探测态卡片：libreOfficeStatus 是 null（探测中）/ 'ok'（已装）/ 'missing'（未装）。
                ok → 绿底 + 版本号 + 路径；missing → 橙底 + 下载按钮；null → 灰底 + 「检测中…」
                走主进程 setup:probe-libreoffice IPC（which/where soffice + soffice --version）。
                visible watch 触发时自动探测；用户也可以重开 SetupView 重测（再次触发 visible=true）。
              -->
              <div :class="['lo-card', libreOfficeStatus || 'loading']">
                <div class="lo-info">
                  <span class="lo-icon">{{ libreOfficeIcon }}</span>
                  <div class="lo-text">
                    <div class="lo-label">{{ libreOfficeLabel }}</div>
                    <div class="lo-detail">{{ libreOfficeDetail }}</div>
                  </div>
                </div>
                <a
                  v-if="libreOfficeStatus === 'missing'"
                  class="lo-download"
                  href="https://www.libreoffice.org/download/"
                  @click.prevent="openLibreOfficeDownload"
                >下载 LibreOffice</a>
              </div>

              <p class="welcome-foot">
                下载安装后再次打开本向导即可看到 ✓ 已装状态；后端无需重启。
              </p>
            </section>

            <!-- ====== Step 5：完成页 ====== -->
            <section v-else-if="currentStep === 5" class="section">
              <div class="section-header">
                <h4>已完成</h4>
                <p class="section-desc">{{ summaryDesc }}</p>
              </div>
              <ul class="welcome-list" v-if="summaryItems.length">
                <li v-for="(item, i) in summaryItems" :key="i">{{ item }}</li>
              </ul>
              <p v-else class="welcome-foot">本轮没有改动任何配置项，跳过即可。</p>
              <p v-if="willRestart" class="restart-hint">
                ⚠️ 含 LLM 配置改动，保存后会重启后端（约 5-15s）后重新加载页面。
              </p>
            </section>
          </div>
        </div>

        <!-- ===== Footer ===== -->
        <div class="setup-footer">
          <div class="footer-hint">{{ footerHint }}</div>
          <div class="footer-actions">
            <button class="btn-text" @click="onPrev" :disabled="currentStep === 0 || saving || loading">
              ← 上一步
            </button>
            <button class="btn-text" @click="onSkipStep" :disabled="saving || loading">
              {{ currentStep === 0 ? '稍后再说' : '跳过本步' }}
            </button>
            <button v-if="currentStep < 5" class="btn-primary" @click="onNext" :disabled="saving || loading">
              下一步 →
            </button>
            <button v-else class="btn-primary" @click="onFinish" :disabled="saving || loading">
              {{ saving ? '保存中...' : '完成' }}
            </button>
          </div>
        </div>

        <!-- 重启 mask 移到 App.vue（全局共享），本组件 emit('restart-requested') 让父级
             接管 —— 与 banner「重新连接」/ Settings「Save & Restart」共用同一套 UI。 -->
      </div>
    </div>
  </transition>
</template>

<script>
import { getConfig, putConfig } from '@/utils/api.js'

export default {
  name: 'SetupView',
  props: {
    visible: { type: Boolean, default: false }
  },
  emits: ['close', 'restart-requested'],
  data() {
    return {
      currentStep: 0,
      // 0 欢迎 / 1 apikey / 2 search / 3 policy / 4 libreoffice / 5 完成 — 共 6 个 pane 但 nav 展示 1-4 四个核心 step
      // （0/5 是入口和出口，不是 step）
      stepsMeta: [
        { key: 'welcome',     label: '欢迎' },
        { key: 'apikey',      label: 'API Key' },
        { key: 'search',      label: '搜索 Key' },
        { key: 'policy',      label: '审批策略' },
        { key: 'libreoffice', label: '旧版文件解析' },
        { key: 'done',        label: '完成' }
      ],

      // ====== Step 4 LibreOffice 探测态 ======
      // null（探测中）→ ok（已装 + version/path）→ missing（未装）→ error（探测异常）。
      // 状态机只在本组件内自维护：visible=true 触发 loadConfig 之后异步调 probe，
      // 不依赖后端 /admin/config，单独走 setup:probe-libreoffice IPC。
      libreOfficeStatus: null,
      libreOfficeVersion: '',
      libreOfficePath: '',
      libreOfficeError: '',

      loading: false,
      loadError: '',
      // 装载 /admin/config 拉到的脱敏 form（api_key 为空串由前端处理）
      formConfig: {
        llm_providers: {},
        skills: {},
        permissions: { approval_policy: 'default', approved_commands: [], denied_commands: [] }
      },
      // 脱敏前的快照，用于 buildPayload diff
      originalConfig: null,

      // ====== Step 2 搜索类 key 的两段式状态 ======
      // skillEnabled：勾选 = 想改；不勾 = 保持现状不动（不发 payload 字段）
      // skillInputs：用户输入的真值（即便勾了也允许空串 = 不修改）
      // 为什么不直接绑到 formConfig.skills.*_api_key：
      //   ① 用户没勾某项时就不应当发空串出去覆盖原值
      //   ② 用户勾 + 输入空字符串 = 等价于「不修改」，与勾选的语义保持一致
      skillEnabled: { exa: false, tavily: false },
      skillInputs:  { exa: '',    tavily: ''    },

      // provider 显隐 key（password / text）
      showKey: {},
      // 高级折叠（policy 已批准命令）
      showAdvanced: false,

      saving: false,
      // 重启遮罩 / 计时器 / IPC 都搬到 App.vue（_backendRestarting / _restartElapsed / _restartTimer），
      // SetupView 通过 emit('restart-requested') 让 App.vue 跑统一重启流程。
      // banner「重新连接」/ Settings「Save & Restart」/ SetupView apikey 改动共用同一份实现。

      policyOptions: [
        { value: 'default', label: 'Default', desc: '敏感命令（写 / code / 网络）每次执行前询问' },
        { value: 'yolo',    label: 'Yolo',    desc: '全部放行（硬危险命令仍会拦截）' }
      ],

      searchSkills: [
        { key: 'exa',    label: 'Exa',    placeholder: '留空表示不修改' },
        { key: 'tavily', label: 'Tavily', placeholder: '留空表示不修改' }
      ]
    }
  },
  computed: {
    /** 当前 form 里主用 provider 的 name（来自 GET /admin/config 之前的快照，可能为 null） */
    currentLlm() {
      // 后端 GET /admin/config 不返回 active；用 formConfig 第一个有 api_key 的 provider 当 active
      const providers = this.formConfig.llm_providers || {}
      const valid = Object.entries(providers).find(([n, p]) =>
        n !== 'vl' && p && p.api_key && p.api_key.trim()
      )
      return { active: valid ? valid[0] : null }
    },
    /** 步骤 1 在表单里展示哪些 provider key —— 保持 whitelist，禁止新增/删除 */
    editableProviderNames() {
      return Object.keys(this.formConfig.llm_providers || {})
    },
    /**
     * 完成页 summary：扫描 formConfig / skillEnabled / skillInputs，
     * 列出本轮相对 originalConfig 实际有改动的项。每条一句话告诉用户「改了 X」。
     */
    summaryItems() {
      const items = []
      const cur = this.formConfig
      const orig = this.originalConfig || {}

      // LLM providers：diff model_name / base_url / api_key 任一非空字段
      if (cur.llm_providers && orig.llm_providers) {
        for (const name of new Set([...Object.keys(cur.llm_providers), ...Object.keys(orig.llm_providers)])) {
          const c = cur.llm_providers[name] || {}
          const o = orig.llm_providers[name] || {}
          const fields = []
          if (c.model_name && c.model_name !== o.model_name) fields.push('model_name')
          if (c.base_url   && c.base_url   !== o.base_url)   fields.push('base_url')
          if (c.api_key    && c.api_key    !== o.api_key)    fields.push('api_key')
          if (name === 'vl' && 'local' in c && c.local !== (o.local ?? true)) fields.push('local')
          if (fields.length) items.push(`${name}：更新 ${fields.join(' / ')}`)
        }
      }

      // Skills
      for (const skill of this.searchSkills) {
        if (this.skillEnabled[skill.key]) {
          const input = (this.skillInputs[skill.key] || '').trim()
          if (input) items.push(`${skill.label}：填了新 key`)
        }
      }

      // Policy
      if (cur.permissions?.approval_policy !== orig.permissions?.approval_policy) {
        items.push(`审批策略：${orig.permissions?.approval_policy || 'default'} → ${cur.permissions.approval_policy}`)
      }
      const curAppr = cur.permissions?.approved_commands || []
      const origAppr = orig.permissions?.approved_commands || []
      if (curAppr.length < origAppr.length) {
        items.push(`已移除 ${origAppr.length - curAppr.length} 条预批准命令`)
      }

      return items
    },
    summaryDesc() {
      return this.summaryItems.length
        ? '本轮改动如下；点「完成」保存。'
        : '本轮没改任何配置，点「完成」或「仍然跳过」直接关闭。'
    },
    /**
     * 检测「完成」是否要走 backend 重启分支：
     * 用户在 step 1 改了 LLM 字段（含 api_key / model_name / base_url / vl.local）
     * → saved_segments 会含 'llm_providers' → 必须 restartBackend。
     */
    willRestart() {
      const cur = this.formConfig
      const orig = this.originalConfig || {}
      if (cur.llm_providers && orig.llm_providers) {
        for (const name of Object.keys(cur.llm_providers)) {
          const c = cur.llm_providers[name] || {}
          const o = orig.llm_providers[name] || {}
          if ((c.model_name || '') !== (o.model_name || '')) return true
          if ((c.base_url   || '') !== (o.base_url   || '')) return true
          if ((c.api_key    || '').trim()) return true   // 任意 provider 填了新 key
          if (name === 'vl' && 'local' in c && c.local !== (o.local ?? true)) return true
        }
      }
      return false
    },
    footerHint() {
      if (this.currentStep === 0) return '随时跳过，向导不会保存任何空字段'
      if (this.currentStep === 4) {
        return 'LibreOffice 仅本机探测，不改动任何配置项'
      }
      if (this.currentStep === 5) {
        return this.willRestart
          ? '⚠️ 含 LLM 配置改动，保存后将重启后端'
          : '任何项都可保留原状不动，向导只发「实际改了」的字段'
      }
      return '任何字段都可留空（保留原值），填了字段才算改动'
    },
    /**
     * LibreOffice 卡片展示用 computed。集中到一处便于在多模板点引用一致。
     */
    libreOfficeIcon() {
      switch (this.libreOfficeStatus) {
        case 'ok':     return '✓'
        case 'missing':return '✗'
        case 'error':  return '!'
        default:       return '⋯'
      }
    },
    libreOfficeLabel() {
      switch (this.libreOfficeStatus) {
        case 'ok':     return this.libreOfficeVersion
          ? `LibreOffice ${this.libreOfficeVersion} 已安装`
          : 'LibreOffice 已安装'
        case 'missing':return 'LibreOffice 未安装'
        case 'error':  return 'LibreOffice 检测失败'
        default:       return '检测中...'
      }
    },
    libreOfficeDetail() {
      if (this.libreOfficeStatus === 'ok') return this.libreOfficePath || 'soffice 在 PATH 中'
      if (this.libreOfficeStatus === 'missing') {
        return '点击下方「下载」到 libreoffice.org/download 安装；安装后重新打开本向导自动探测'
      }
      if (this.libreOfficeStatus === 'error') {
        return this.libreOfficeError || '请稍后重试或检查 PATH'
      }
      return '正在扫描本地 soffice 命令...'
    },
  },
  watch: {
    visible(val) {
      if (val) {
        // 复位状态机（防止上次开着 setup 时改外部状态再开回来不一致）
        this.currentStep = 0
        this.showAdvanced = false
        // 重启遮罩 / timer 都搬到 App.vue,这里不需要清理
        // 拉最新配置 + 异步探测 LibreOffice 并行（不互相依赖）
        this.loadConfig().finally(() => {
          this.focusCurrentStep()
        })
        this.probeLibreOffice()
      }
    },
    skillEnabled: {
      deep: true,
      handler() {
        // 跟随 enable 状态自动重置 input placeholder —— 不强制清空，
        // 用户切回已勾选项时能看见上次输入
      }
    }
  },
  mounted() {
    // Esc 关闭（与 SettingsDialog 一致）
    document.addEventListener('keydown', this.handleKeydown)
  },
  beforeDestroy() {
    document.removeEventListener('keydown', this.handleKeydown)
    this.cleanupTimer()
  },
  methods: {
    close() { this.$emit('close') },
    onSkipEntire() { this.close() },
    onSkipStep() {
      // 跳过当前 step：欢迎页视为彻底跳过 → 关闭；其他 step 视为「本步不改」→ 推进
      if (this.currentStep === 0) {
        this.close()
      } else if (this.currentStep === 5) {
        // 完成页的「仍然跳过」等价关弹窗
        this.close()
      } else {
        this.goToStep(Math.min(this.currentStep + 1, 5))
      }
    },
    onPrev() {
      if (this.currentStep > 0) this.goToStep(this.currentStep - 1)
    },
    onNext() {
      if (this.currentStep < 5) this.goToStep(this.currentStep + 1)
    },
    goToStep(i) {
      if (i < 0 || i > 5 || this.saving || this.loading) return
      this.currentStep = i
      // 键盘 ↑↓ 切换时把焦点跟着移到新 step 按钮上 — 视觉焦点跟得上，
      // 屏幕阅读器也能听到正确的 step 标签
      this.$nextTick(() => {
        const ref = this.$refs[`step_${this.stepsMeta[i].key}`]
        if (ref && ref[0] && typeof ref[0].focus === 'function') {
          ref[0].focus()
        }
      })
    },
    focusCurrentStep() {
      this.$nextTick(() => {
        const ref = this.$refs[`step_${this.stepsMeta[this.currentStep].key}`]
        if (ref && ref[0] && typeof ref[0].focus === 'function') {
          ref[0].focus()
        }
      })
    },
    providerLabel(name) {
      const map = {
        model1: '主用模型',
        model2: '备用模型',
        vl:     '视觉模型'
      }
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

        // 存脱敏前的快照给 buildPayload 做 diff（与 SettingsDialog 同样的策略）
        this.originalConfig = JSON.parse(JSON.stringify(cfg))

        // 脱敏的 api_key 不入 form —— 留空让 placeholder 提示「留空表示不修改」
        for (const prov of Object.values(cfg.llm_providers)) {
          if (prov && 'api_key' in prov) prov.api_key = ''
        }
        for (const k of Object.keys(cfg.skills)) {
          if (k.endsWith('_api_key')) cfg.skills[k] = ''
        }

        // vl.local 不传时后端默认 True；前端 form 默认也 True
        if (cfg.llm_providers.vl && typeof cfg.llm_providers.vl.local !== 'boolean') {
          cfg.llm_providers.vl.local = true
        }

        this.formConfig = cfg

        // 初始化搜索类 key 状态 —— 已有 key 的勾选并回填，提示用户「已配」状态
        for (const skill of this.searchSkills) {
          const origVal = (this.originalConfig.skills[skill.key + '_api_key'] || '').trim()
          this.skillEnabled[skill.key] = false
          this.skillInputs[skill.key]  = ''
          // 原始 api_key 是脱敏 4*4 形态，仍视作「已配置」（不主动回填真值）
          if (origVal) {
            this.skillEnabled[skill.key] = true
            this.skillInputs[skill.key]  = ''
          }
        }
      } catch (e) {
        console.warn('[SetupView] loadConfig failed:', e)
        this.loadError = '加载配置失败：' + (e.message || e)
      } finally {
        this.loading = false
      }
    },
    /**
     * 探测本地 LibreOffice：调 setup:probe-libreoffice IPC。
     * - installed=true → libreOfficeStatus='ok' + version/path 展示
     * - installed=false → libreOfficeStatus='missing'（显示下载按钮）
     * - IPC 异常 → libreOfficeStatus='error'（仍可重试，无破坏性）
     *
     * 异步探测独立于 loadConfig —— 即便 loadConfig 拖累 1-2s，lo 卡片也能快速亮起。
     * 不发任何 payload，不影响 buildPayload / willRestart。
     */
    async probeLibreOffice() {
      if (!window.electronAPI?.probeLibreOffice) {
        // 主进程没暴露（dev / 旧版本）→ 当作未装处理，不阻断向导
        this.libreOfficeStatus = 'missing'
        this.libreOfficeVersion = ''
        this.libreOfficePath = ''
        return
      }
      try {
        const result = await window.electronAPI.probeLibreOffice()
        if (result?.installed) {
          this.libreOfficeStatus = 'ok'
          this.libreOfficeVersion = result.version || ''
          this.libreOfficePath    = result.path || ''
          this.libreOfficeError   = ''
        } else {
          this.libreOfficeStatus = 'missing'
          this.libreOfficeVersion = ''
          this.libreOfficePath    = ''
          this.libreOfficeError   = ''
        }
      } catch (e) {
        console.warn('[SetupView] probeLibreOffice failed:', e)
        this.libreOfficeStatus = 'error'
        this.libreOfficeError  = e?.message || String(e)
      }
    },
    /**
     * 在系统默认浏览器打开 LibreOffice 通用下载页。
     * 走 window.electron.openExternal bridge（preload.js 直接调 shell.openExternal），
     * 不重复造 IPC 通道 —— 与 BootstrapView 的 downloadUrl 路径同源。
     */
    openLibreOfficeDownload() {
      const url = 'https://www.libreoffice.org/download/'
      // setTimeout 0 让 click 事件先返回，避免部分浏览器引擎把 shell 调用当 popup 拦掉
      setTimeout(() => {
        try {
          window.electron?.openExternal?.(url)
        } catch (e) {
          console.error('[SetupView] openLibreOfficeDownload failed:', e)
        }
      }, 0)
    },
    removeApproved(idx) {
      this.formConfig.permissions.approved_commands.splice(idx, 1)
    },
    /**
     * 计算要发的 payload：
     *   - 段级 diff（仅在 formConfig 与 originalConfig 对比有差异时发）
     *   - 空 api_key 不发（与 SettingsDialog 同样的约定，save_config 内部也跳过）
     *   - search 类 key 走 skillEnabled 才发
     * 复用 SettingsDialog 的 _stripEmptyObjects 思想 —— 但 setup 简化：
     *   只在 llm_providers / skills 段内部剥空 provider / 空字符串；
     *   permissions 段保留全部（policy 修改总应该发）。
     */
    buildPayload() {
      const payload = {}
      const orig = this.originalConfig || {}

      // llm_providers
      if (this.formConfig.llm_providers && orig.llm_providers) {
        const llmDiff = {}
        for (const name of new Set([...Object.keys(this.formConfig.llm_providers), ...Object.keys(orig.llm_providers)])) {
          const c = this.formConfig.llm_providers[name] || {}
          const o = orig.llm_providers[name] || {}
          const provDiff = {}
          if ((c.model_name || '') !== (o.model_name || '')) provDiff.model_name = c.model_name
          if ((c.base_url   || '') !== (o.base_url   || '')) provDiff.base_url   = c.base_url
          if ((c.api_key    || '').trim()) provDiff.api_key = c.api_key
          if (name === 'vl' && typeof c.local === 'boolean' && c.local !== (o.local ?? true)) provDiff.local = c.local
          if (Object.keys(provDiff).length) llmDiff[name] = provDiff
        }
        if (Object.keys(llmDiff).length) payload.llm_providers = llmDiff
      }

      // skills：仅发送用户**显式启用**且**确实填了新值**的项
      if (this.formConfig.skills || orig.skills) {
        const skillsDiff = {}
        for (const skill of this.searchSkills) {
          if (!this.skillEnabled[skill.key]) continue
          const input = (this.skillInputs[skill.key] || '').trim()
          if (!input) continue
          skillsDiff[skill.key + '_api_key'] = input
        }
        if (Object.keys(skillsDiff).length) payload.skills = skillsDiff
      }

      // permissions：policy 字段 + approved_commands 列表（数组顺序 / 长度变化）
      if (this.formConfig.permissions && orig.permissions) {
        const cur = this.formConfig.permissions
        const o = orig.permissions
        const permsDiff = {}
        if (cur.approval_policy !== o.approval_policy) permsDiff.approval_policy = cur.approval_policy
        if (JSON.stringify(cur.approved_commands) !== JSON.stringify(o.approved_commands || [])) {
          permsDiff.approved_commands = cur.approved_commands
        }
        if (Object.keys(permsDiff).length) payload.permissions = permsDiff
      }

      return payload
    },
    /** 完成 → 持久化 + 按需重启 */
    async onFinish() {
      const payload = this.buildPayload()
      if (Object.keys(payload).length === 0) {
        // 没改动 → 关弹窗即结束（不调后端，避免空 PUT 触发差异判断）
        this.close()
        return
      }
      this.saving = true
      try {
        const result = await putConfig(payload)
        const segments = result.saved_segments || []
        const needsRestart = segments.includes('llm_providers')

        if (needsRestart) {
          this.restartAndReload()
        } else {
          this.flashTip('已保存，立即生效')
          this.close()
        }
      } catch (e) {
        alert('保存失败：' + (e.message || e))
      } finally {
        this.saving = false
      }
    },
    restartAndReload() {
      // 重启逻辑全部交给 App.vue：emit('restart-requested') 让 App.vue 跑
      //   handleRestartBackend：开全局 spinner 遮罩 → IPC restartBackend（主进程
      //   会等 /health 通,最长 120s）→ this.refreshPage()（webContents.reload）。
      // 不在 SetupView 内自渲染遮罩 / 自 poll health / 自重启,避免和 banner / Settings
      // 出现三套不一致实现（之前就是这样导致 timer 显示 0s / 遮罩不消失等）。
      this.$emit('restart-requested')
      // 关闭 SetupView：用户已看到全局遮罩反馈,继续留着会在 reload 那一帧抖动。
      this.close()
    },
    handleKeydown(e) {
      if (!this.visible) return
      if (this.saving || this.loading) return
      // 输入框 / textarea / select / contenteditable 内不接管 ↑↓ —
      // 让原生光标 / 选项切换行为正常（用户在 step 表单里编辑时优先本地编辑体验）
      const ae = document.activeElement
      const inEditable = ae && (
        ae.tagName === 'INPUT' ||
        ae.tagName === 'TEXTAREA' ||
        ae.tagName === 'SELECT' ||
        ae.isContentEditable
      )
      if (inEditable) return

      if (e.key === 'Escape') {
        e.preventDefault()
        this.close()
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        // ↑↓ 切换左侧 step 模块（mac/win 共用 ArrowUp/ArrowDown key 名）
        // 到边停止，不循环 — 避免误触一直找不到当前位置
        e.preventDefault()
        const dir = e.key === 'ArrowDown' ? 1 : -1
        const next = Math.max(0, Math.min(this.stepsMeta.length - 1, this.currentStep + dir))
        this.goToStep(next)
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
/* ===== 浮窗架构：与 BootstrapView 同形 ===== */
.setup-overlay {
  position: fixed;
  inset: 0;
  z-index: 1500;             /* 比 BootstrapView(1000) 高，避免被盖 */
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: transparent;
  pointer-events: auto;
}
.setup-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}
.setup-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 720px;
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  overflow: hidden;
  animation: setup-card-in 0.22s ease-out;
}
@keyframes setup-card-in {
  from { opacity: 0; transform: translateY(-8px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0)    scale(1);    }
}

/* ===== Header ===== */
.setup-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 22px 12px;
  border-bottom: 1px solid var(--border-color);
}
.setup-header h3 {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}
.setup-header .subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.setup-close {
  width: 28px;
  height: 28px;
  padding: 0;
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
.setup-close:hover { background: var(--bg-hover); color: var(--text-primary); }

/* ===== Body: nav + content ===== */
.setup-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.setup-nav {
  width: 180px;
  flex-shrink: 0;
  border-right: 1px solid var(--border-color);
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  outline: none;
}
.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  text-align: left;
  transition: background 0.1s, color 0.1s;
  font-family: inherit;
}
.step-item:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-primary); }
.step-item.active { background: var(--bg-hover); color: var(--text-primary); font-weight: 500; }
.step-item:disabled { opacity: 0.6; cursor: not-allowed; }
/* 键盘 ↑↓ 切换 step 时的焦点提示（不干扰鼠标点击的 hover 视觉） */
.step-item:focus-visible {
  outline: 2px solid var(--button-bg, #3b82f6);
  outline-offset: 1px;
}
.step-item.done .step-index { color: var(--success-color, #34c759); }
.step-index {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-color);
  border-radius: 50%;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}
.step-item.active .step-index {
  border-color: var(--accent-color, #007aff);
  color: var(--accent-color, #007aff);
}
.step-item.done .step-index {
  border-color: var(--success-color, #34c759);
  background: rgba(52, 199, 89, 0.08);
}

/* ===== Content ===== */
.setup-content {
  flex: 1;
  overflow-y: auto;
  padding: 18px 26px 4px;
  min-height: 280px;
}
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

.section-header { margin-bottom: 16px; }
.section-header h4 {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.section-desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.welcome-list {
  list-style: none;
  padding: 0;
  margin: 12px 0;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.8;
}
.welcome-list li {
  padding: 4px 0;
}
.welcome-foot {
  margin: 12px 0 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.restart-hint {
  margin: 14px 0 0;
  padding: 10px 12px;
  border: 1px solid var(--warning-color, #ff9500);
  background: rgba(255, 149, 0, 0.08);
  color: var(--warning-color, #ff9500);
  border-radius: 6px;
  font-size: 12.5px;
  line-height: 1.5;
}

/* ===== Form groups (与 SettingsDialog 视觉一致) ===== */
.group {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.group:last-child { margin-bottom: 0; }
.group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
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
  margin-bottom: 10px;
}
.field:last-child { margin-bottom: 0; }
.field label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}
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
}
.field input:focus { outline: none; border-color: var(--text-primary); }
.field input::placeholder { color: var(--text-secondary); opacity: 0.7; }
.field-hint {
  margin: 4px 0 0;
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.4;
}
.password-wrap { position: relative; display: flex; }
.password-wrap input { padding-right: 56px; }
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
.toggle-eye:hover { background: var(--bg-hover); color: var(--text-primary); }

/* ===== Step 2 search row ===== */
.search-row {
  display: grid;
  grid-template-columns: 140px 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-color);
}
.search-row:last-child { border-bottom: none; }
.search-name {
  font-size: 13px;
  font-weight: 500;
}
.search-input-wrap { width: 100%; }
.search-status {
  font-size: 12px;
  color: var(--text-secondary);
  font-style: italic;
}

/* ===== Step 3 policy pill ===== */
.policy-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.policy-pill {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
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
.policy-label { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.policy-desc  { font-size: 11.5px; color: var(--text-secondary); line-height: 1.4; }

/* ===== Advanced toggle（policy 已批准命令） ===== */
.advanced-toggle {
  width: 100%;
  padding: 8px 14px;
  border: 1px dashed var(--border-color);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12.5px;
  font-family: inherit;
  transition: background 0.15s;
}
.advanced-toggle:hover { background: var(--bg-hover); color: var(--text-primary); }
.advanced-block { margin-top: 12px; }

/* ===== Step 4 LibreOffice 卡 ===== */
/* 视觉沿用 BootstrapView 的 .check-item ok/fail/fixing 三态，但 step 内更紧凑 */
.lo-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  transition: border-color 0.15s, background 0.15s;
}
.lo-card.loading { border-color: var(--border-color); background: var(--bg-secondary); }
.lo-card.ok      { border-color: var(--success-color, #34c759); background: rgba(52, 199, 89, 0.06); }
.lo-card.missing { border-color: var(--warning-color, #ff9500); background: rgba(255, 149, 0, 0.06); }
.lo-card.error   { border-color: var(--danger-color,  #ff3b30); background: rgba(255, 59, 48, 0.06); }

.lo-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}
.lo-icon {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-secondary);
}
.lo-card.ok      .lo-icon { color: var(--success-color, #34c759); }
.lo-card.missing .lo-icon { color: var(--warning-color, #ff9500); }
.lo-card.error   .lo-icon { color: var(--danger-color,  #ff3b30); }

.lo-text { min-width: 0; flex: 1; }
.lo-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  word-break: break-all;
}
.lo-detail {
  font-size: 11.5px;
  color: var(--text-secondary);
  margin-top: 2px;
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* 下载按钮 — 走 BootstrapView 的 .btn-download 视觉（border + accent 蓝）保持品牌一致 */
.lo-download {
  flex-shrink: 0;
  padding: 6px 14px;
  font-size: 12px;
  border: 1px solid var(--accent-color, #007aff);
  background: transparent;
  color: var(--accent-color, #007aff);
  border-radius: 6px;
  cursor: pointer;
  text-decoration: none;
  font-family: inherit;
  transition: background 0.15s, color 0.15s;
}
.lo-download:hover { background: var(--accent-color, #007aff); color: white; }

/* ===== cmd list（policy approved/denied）===== */
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
  max-height: 180px;
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
}
.cmd-delete:hover {
  background: #fee2e2;
  color: #b91c1c;
  border-color: #fca5a5;
}

/* ===== Footer ===== */
.setup-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 22px;
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
.btn-text:hover:not(:disabled) { background: var(--bg-hover); }
.btn-primary {
  background: var(--text-primary);
  color: var(--bg-primary);
  border-color: var(--text-primary);
}
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-text:disabled,
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

/* ===== Transitions ===== */
.setup-fade-enter-active,
.setup-fade-leave-active { transition: opacity 0.18s ease; }
.setup-fade-enter-from,
.setup-fade-leave-to { opacity: 0; }

.fade-enter-active,
.fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from,
.fade-leave-to { opacity: 0; }
</style>

<style>
/* flash-tip 走全局样式（与 SettingsDialog 保持一致的视觉提示） */
.flash-tip {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
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
  to   { opacity: 1; transform: translate(-50%, 0); }
}
</style>
