<template>
  <!--
    浮窗形式：fixed 全屏 + 半透明 backdrop + 居中卡片。
    App.vue 的主界面始终在 DOM 里（appReady=false 时灰显禁用），
    用户点"启动应用" → 主进程广播 servicesReady=true → 浮窗消失，主界面启用。
  -->
  <div class="bootstrap-overlay">
    <div class="bootstrap-backdrop"></div>
    <div class="bootstrap-card">
      <div class="bootstrap-header">
        <h2>灵析 启动配置</h2>
        <p class="subtitle">首次启动需要检测并配置以下依赖项</p>
      </div>

      <!--
        项目目录行：未找到 lingxi/ 时给用户三条恢复路径任选其一
        - 克隆到默认父目录（os.homedir()，git 按仓库名建 ~/lingxi/）
        - 克隆到自定义父目录（picker → autoClone）
        - 指向已有 lingxi/ checkout（picker → setLastCloneTarget + saveProjectRoot，不 clone）
        三个按钮共享 picking* / cloning 互斥 disabled，防止连点 + 跨路径并发
        视觉上保持和 check-list 内其他项一致（同一个 .check-item 模板）
      -->
      <div :class="['check-item', getProjectRootClass()]" style="margin-bottom:8px">
        <span class="icon">{{ getProjectRootIcon() }}</span>
        <div class="info">
          <div class="label">
            {{ projectRoot.ok ? '项目目录（lingxi/）' : '未找到 lingxi 项目目录' }}
          </div>
          <div class="detail">{{ getProjectRootDetail() }}</div>
        </div>
        <div class="action">
          <!--
            项目目录缺失时三按钮栈：1) 默认父目录克隆 2) 自定义父目录克隆 3) 指向已有 lingxi/
            前两个走「克隆 lingxi」（warning 色，警示要写盘）；
            第三个走「指向现有 checkout」（accent 蓝，纯定位不写盘）—— 视觉上区分两类意图
          -->
          <div v-if="!projectRoot.ok" class="action-stack">
            <button
              class="btn-fix"
              :disabled="cloning || pickingCloneTarget || picking"
              @click="confirmAutoClone"
            >{{ cloning ? '克隆中...' : '克隆到默认目录' }}</button>
            <button
              class="btn-fix btn-fix-outline"
              :disabled="cloning || pickingCloneTarget || picking"
              @click="customizeClonePath"
            >{{ pickingCloneTarget ? '选择中...' : '克隆到其他目录...' }}</button>
            <button
              class="btn-fix btn-fix-existing"
              :disabled="cloning || pickingCloneTarget || picking"
              @click="pickProjectRoot"
            >{{ picking ? '选择中...' : '选择已有的 lingxi/ 目录' }}</button>
          </div>
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
            <!--
              Docker daemon 未启动（probeDocker 返 hint='start-daemon'）：
              显示「启动」按钮，点了走 IPC startup:start-docker + 轮询 recheck
              直到 daemon up 或 30s 超时。
            -->
            <button
              v-if="item.hint === 'start-daemon' && !item.starting"
              class="btn-fix"
              :disabled="item.starting"
              @click="startDockerDaemon(item)"
            >启动</button>
            <span
              v-else-if="item.hint === 'start-daemon' && item.starting"
              class="fixing-indicator"
            >启动中...</span>
            <button
              v-else-if="item.canAutoFix && !item.ok && !item.fixing"
              class="btn-fix"
              @click="fixOne(item)"
            >配置</button>
            <button
              v-else-if="!item.ok && !item.canAutoFix"
              class="btn-download"
              @click="openDownload(item.downloadUrl)"
            >下载</button>
            <span v-else-if="item.fixing" class="fixing-indicator">配置中...</span>
          </div>
        </div>
      </div>

      <div class="log-box" ref="logBox">
        <pre v-if="logs">{{ logs }}</pre>
        <div v-else class="log-placeholder">点击"启动应用"后，这里会显示自动配置进度</div>
      </div>

      <!--
        项目根自动迁移横幅（discoverProjectRoot 检测到 saved 路径版本落后于 BFS 时触发）：
        - 用户上次启动用的是旧 lingxi/ 副本（端口 8211 / 老 pyproject version）
        - 这次启动扫到更新副本（端口 38211 / 新 version），自动切过去
        - 不告诉用户会一脸懵「我的旧项目去哪了」——明确告知「我们帮你换了」
      -->
      <div v-if="swappedProjectRoot" class="swap-banner" role="status">
        <span class="swap-icon">🔄</span>
        <div class="swap-info">
          <div class="swap-title">已自动切换到更新的项目目录</div>
          <div class="swap-detail">
            旧：{{ shortenPath(swappedProjectRoot.from) }}
            <span v-if="swappedProjectRoot.fromFingerprint" class="swap-fp">
              (v{{ swappedProjectRoot.fromFingerprint.version || '?' }}:{{ swappedProjectRoot.fromFingerprint.port || '?' }})
            </span>
            <br />
            新：<strong>{{ shortenPath(currentProjectRoot) }}</strong>
          </div>
        </div>
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
  name: 'BootstrapView',
  // servicesReady 是父级 (App.vue) 持有的主进程 servicesReady 状态；
  // 通过 prop 下传避免 BootstrapView 重复 invoke getServicesReady（避免双源真相漂移）。
  props: {
    servicesReady: {
      type: Boolean,
      default: false
    },
    // discoverProjectRoot 自动迁移标记：saved PROJECT_ROOT 版本落后于 BFS 候选时
    // 主进程会带 swappedProjectRoot 字段推送 servicesReady=true，App.vue 把这个 prop 下传
    swappedProjectRoot: {
      type: Object,
      default: null
    },
    // 当前生效的 PROJECT_ROOT（同样由 App.vue 下传；用于横幅显示新路径）
    currentProjectRoot: {
      type: String,
      default: ''
    },
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
          // probeDocker 返回 hint='start-daemon' 时显示「启动」按钮；probePython 不返 hint
          hint: '',
        },
        {
          id: 'docker',
          label: 'Docker Desktop',
          canAutoFix: false,
          downloadUrl: 'https://www.docker.com/products/docker-desktop/',
          ok: false,
          detail: '',
          fixing: false,
          hint: '',
          // 启动 Docker Desktop 按钮 in-flight 标记（与 fixing 类似，避免重复点击）
          starting: false,
        },
      ],
      logs: '',
      checking: false,
      launching: false,
      launchError: '',
      autoEnterFrontend: false,
      // 三个互斥 in-flight 标记：UI 任意时刻只允许一种恢复路径在跑（克隆 / 选克隆目标 / 选现有目录）
      cloning: false,             // 实际 git clone 正在跑
      pickingCloneTarget: false,  // 「克隆到其他目录...」picker 打开中
      // picking 已在 data() 上面声明（指向已有 lingxi/ 目录 picker 打开中）
      // 默认克隆父目录展示用—— 是用户最终能控制的「父目录」，
      // 不是 ~/lingxi/（git 按仓库名自动建 lingxi/ 子目录，不在用户选择范围内）。
      // 在 mounted() 里通过 IPC startup:get-default-clone-target 拿到真实 OS 家目录，
      // 这里先用占位符 '~' 兜底（极短窗口，recheck 期间可见）。
      defaultCloneTarget: '~',
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
      if (ready) {
        this.logs += '[启动] ✅ 后端与 MCP 已就绪\n'
        // 「进入应用」按钮刚变为 enabled 时立即抢焦点，回车直接进 app
        this.$nextTick(this.focusPrimaryBtn)
      }
    },
    // 主进程 servicesReadyChange IPC 推送的 payload 不会作为 prop 进来（BootstrapView
    // 只接 servicesReady: Boolean），但 App.vue 触发 onServicesReadyChange 时我们可以
    // 直接通过 window.electronAPI 拿到 swappedProjectRoot 字段。挂一个全局 hook。
    // 实际上更简洁的做法：在 App.vue 里把 swappedProjectRoot 复制到 BootstrapView 的 prop。
    // 暂时保留简单方案：通过 _onGlobalSwapEvent 触发（mounted 里挂监听）。
    // 主进程服务 ready 推送 payload 里有 swappedProjectRoot 时记日志（App.vue 会通过
    // prop 下传显示横幅；这里只追加一行日志方便用户看 timeline）
    swappedProjectRoot(val) {
      if (val) {
        this.logs += `\n[启动] 🔄 已自动迁移到更新版本项目（旧：${val.from}）\n`
      }
    },
    // launching / autoEnterFrontend 切换也会改按钮状态（启动中→可启动 / 自动进）
    launching() { this.$nextTick(this.focusPrimaryBtn) },
    autoEnterFrontend() { this.$nextTick(this.focusPrimaryBtn) },
    items: {
      // 项目目录 / python / docker 检测结果回填后，按钮的 disabled 状态可能翻转
      deep: true,
      handler() { this.$nextTick(this.focusPrimaryBtn) }
    }
  },
  async mounted() {
    if (window.electronAPI?.getStartupPreferences) {
      const preferences = await window.electronAPI.getStartupPreferences()
      this.autoEnterFrontend = preferences?.autoEnterFrontend === true
    }
    // 拿到 OS 真实家目录作为默认 clone 父目录展示给用户看
    // （如 Mac 的 /Users/xxx/、Win 的 C:\Users\xxx\）
    if (window.electronAPI?.getDefaultCloneTarget) {
      try {
        const { targetDir } = await window.electronAPI.getDefaultCloneTarget()
        if (targetDir) this.defaultCloneTarget = targetDir
      } catch (e) {
        console.warn('getDefaultCloneTarget failed:', e)
        // 保留 '~' 占位符，主进程 autoCloneProject 也会 fallback 到 os.homedir()
      }
    }
    await this.recheck()
    // servicesReady 由 App.vue 持有 + 通过 prop 下传，避免双源真相；这里不再 invoke getServicesReady。
    if (this.servicesReady) {
      this.logs += '[启动] ✅ 后端与 MCP 已就绪\n'
    }
    // 项目根探测失败 → 三按钮栈自动显示（v-if="!projectRoot.ok"）。
    // 这是触发恢复的唯一入口（main 进程已删除 silent auto-clone，不会主动写盘）：
    //   1. 「克隆到默认目录」→ startup:auto-clone(targetDir=~)
    //   2. 「克隆到其他目录...」→ startup:pick-clone-target → startup:auto-clone
    //   3. 「选择已有的 lingxi/ 目录」→ startup:pick-project-root（已有 checkout 不需要 clone）
    if (!this.projectRoot.ok) {
      this.logs += '\n[启动] 未找到本地项目，请选择克隆 lingxi 仓库 / 指向已有目录\n'
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
    // 让 BootstrapView 卸载；这里只是发起 bootstrap 这一步。
    if (this.autoEnterFrontend && !this.servicesReady && this.allOk) {
      this.$nextTick(() => this.launch())
    }

    // 抢焦点到主按钮（启动应用 / 进入应用 / 启动中…），回车直接触发。
    // 主按钮 v-if 三态（启动中 disabled / 进入应用 / 启动应用），自动选第一个非 disabled 的
    this.$nextTick(this.focusPrimaryBtn)
  },
  methods: {
    /**
     * 把焦点抢到主按钮（启动应用 / 进入应用）；跳过 disabled 的「启动中…」按钮。
     * 不抢焦点到 overlay 容器（避免遮罩 click.self 行为异常）；
     * 主按钮本身就是焦点入口，回车 / 空格即可触发。
     */
    focusPrimaryBtn() {
      const btn = this.$el.querySelector('.btn-primary:not(:disabled)')
      if (btn && typeof btn.focus === 'function') btn.focus()
    },
    /**
     * 路径展示压缩：保留末 2 段目录 + 中间用 … 替代，避免横幅里塞满长路径
     * （Win 上 C:\Users\xxx\Documents\lingxi 这种显示出来很丑）。
     * 路径 < 50 字符原样返回。
     */
    shortenPath(p) {
      if (!p) return ''
      if (p.length < 50) return p
      const parts = p.split(/[/\\]/)
      if (parts.length <= 3) return p
      return `${parts[0]}/…/${parts.slice(-2).join('/')}`
    },
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
            // 主进程 probe-all 返回带 downloadUrl 时覆盖硬编码默认值
            // （平台感知：Mac/Win/Linux 不同下载页）
            if (results[item.id].downloadUrl) {
              item.downloadUrl = results[item.id].downloadUrl
            }
            // probeDocker daemon 未跑时返 hint='start-daemon'，驱动「启动」按钮显示
            item.hint = results[item.id].hint || ''
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
          // projectRoot.ok=true 后三按钮栈自动隐藏（v-if gate）
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
    /**
     * 「启动」按钮：手动启动 Docker Desktop（probeDocker 返回 hint='start-daemon' 时调用）。
     *
     * 流程：
     * 1. IPC startup:start-docker → main 端跨平台 spawn/open -a/systemctl
     * 2. 启动是异步的（Docker Desktop 一般 5-30s 完成），UI 端轮询 recheck 直到 docker.ok=true
     * 3. 30s 超时 → 留按钮让用户重试，不强行弹错误窗口
     *
     * @param {object} item — 当前 docker 项（Vue 响应式，starting 直接挂载；ok/hint 由 recheck 写入）
     */
    async startDockerDaemon(item) {
      if (!window.electronAPI?.startDocker) return
      if (item.starting) return  // 幂等：防止连点
      item.starting = true
      this.logs += '\n[docker] 启动 Docker Desktop...\n'
      try {
        const result = await window.electronAPI.startDocker()
        if (!result?.ok) {
          this.logs += `[docker] ⚠️ 启动失败：${result?.error || '未知错误'}\n`
          this.logs += '[docker] 请手动启动 Docker Desktop 后重新检测\n'
          return  // 启动失败 → 按钮保持可见，让用户重试
        }

        // 启动命令成功 → 轮询 recheck 直到 daemon up 或 30s 超时
        const POLL_INTERVAL_MS = 2_000
        const MAX_POLLS = 15  // 30s 上限
        for (let i = 0; i < MAX_POLLS; i++) {
          await new Promise(r => setTimeout(r, POLL_INTERVAL_MS))
          await this.recheck()
          const dockerItem = this.items.find(x => x.id === 'docker')
          if (dockerItem?.ok) {
            this.logs += '[docker] ✅ daemon 已就绪\n'
            return
          }
        }
        this.logs += '[docker] ⚠️ 30s 内未检测到 daemon，请确认 Docker Desktop 已运行后重新检测\n'
      } catch (e) {
        console.error('startDockerDaemon failed:', e)
        this.logs += `[docker] ❌ 异常：${e.message}\n`
      } finally {
        item.starting = false
      }
    },
    /**
     * 项目目录恢复路径 1：「克隆到默认目录」按钮触发。
     - 不传 targetDir → main 端 autoCloneProject fallback 到 os.homedir()
     - 不弹 dialog（skipDirPicker: true）——用户已在 UI 上点确认了
     */
    async confirmAutoClone() {
      this.cloning = true
      try {
        await this.runAutoClone({})
      } finally {
        this.cloning = false
      }
    },
    /**
     * 项目目录恢复路径 2：「克隆到其他目录...」按钮触发。
     - 先弹目录选择框（IPC startup:pick-clone-target，仅返回 targetDir 不 clone）
     - 用户选完后用 targetDir 调 autoClone，跳过 main 端内置 picker
     - 用户取消选择 → 三按钮栈保留，等用户点「克隆到默认目录」或「选择已有的 lingxi/ 目录」
     */
    async customizeClonePath() {
      this.pickingCloneTarget = true
      try {
        const pick = await window.electronAPI.pickCloneTarget()
        if (!pick?.ok) {
          // 用户取消 → 留在卡片上
          if (!pick?.canceled) {
            this.logs += `[clone] 自定义目录选择失败\n`
          }
          return
        }
        this.cloning = true
        try {
          await this.runAutoClone({ targetDir: pick.targetDir })
        } finally {
          this.cloning = false
        }
      } finally {
        this.pickingCloneTarget = false
      }
    },
    /**
     * 实际触发主进程 autoCloneProject 的统一入口（确认 / 自定义两条路径都走这里）。
     - opts.skipDirPicker 必须为 true —— 卡片已经走完了 picker 步骤
     - opts.targetDir 可选：有值时 main 按用户选的目录 clone，无值时 fallback 到 ~/
     - 完成后 recheck + 失败兜底（pickProjectRoot 主动唤起）
     */
    async runAutoClone(opts = {}) {
      if (!window.electronAPI?.autoClone) return
      this.logs += '\n[clone] git clone 开始...\n'
      const result = await window.electronAPI.autoClone({
        skipDirPicker: true,
        ...opts,
      })
      if (result?.ok) {
        this.logs += `[clone] ✅ 自动 clone 成功（${result.source}）→ ${result.projectRoot}\n`
        // projectRoot.ok=true 后三按钮栈自动隐藏（v-if gate）
        await this.recheck()  // 刷新 projectRoot / python / docker
        // clone 成功但 recheck 仍显示 projectRoot 不 ok（极端兜底场景）
        if (!this.projectRoot.ok) {
          this.logs += '[clone] ⚠️ clone 成功但项目检测失败，主动唤起手动选择对话框\n'
          await this.pickProjectRoot()
        }
      } else {
        this.logs += `[clone] ⚠️ 自动 clone 失败：${result?.error || '未知错误'}\n`
        this.logs += '[clone] 请检查 git 是否安装 / 网络通畅\n'
        // clone 失败 → 主动唤起手动选择对话框（用户可能已有 lingxi/ checkout 想直接用）
        this.logs += '[clone] 主动唤起手动选择目录对话框...\n'
        await this.pickProjectRoot()
      }
    },
    async saveAutoEnterPreference() {
      const result = await window.electronAPI.setAutoEnterFrontend(this.autoEnterFrontend)
      if (!result?.ok) {
        this.launchError = `保存启动偏好失败：${result?.error || '未知错误'}`
      }
    },
    /**
     * 在系统默认浏览器打开下载页。
     * 走已存在的 window.electron.openExternal bridge（preload.js:79 直接调 shell.openExternal），
     * 不重复造 IPC 通道。preload 已对协议做白名单校验（http/https only）。
     */
    openDownload(url) {
      if (!url) return
      // setTimeout 0 让点击事件先返回，避免部分浏览器引擎把 shell 调用当 popup 拦掉
      setTimeout(() => {
        try {
          window.electron.openExternal(url)
        } catch (e) {
          console.error('openExternal failed:', e)
        }
      }, 0)
    },
    /**
     * 触发一键 bootstrap（uv → redis → sandbox → venv → mcp → backend）。
     * 完成后由主进程 broadcast servicesReady=true，App.vue 翻 appReady=true，
     * BootstrapView 自动消失，主界面 mount + 加载会话。
     *
     * 按钮永远只走 bootstrap 这条路径；服务已就绪时按钮 disabled（mounted 期间由
     * App.vue 的 getServicesReady=true 触发 appReady=true 直接切走，BootstrapView 根本不会渲染）。
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
     * 项目目录行的状态：
     * - ok → 绿（已就绪，action 区为空）
     * - 其他 → 橙（fixing，三按钮栈可见）
     *
     * 旧版有 fail 红态——但新版不论失败还是提示克隆都展示同一组三按钮恢复路径，
     * 「失败」和「待克隆」在视觉上区分意义不大，统一用橙（fixing）即可。
     */
    getProjectRootClass() {
      return this.projectRoot.ok ? 'ok' : 'fixing'
    },
    getProjectRootIcon() {
      return this.projectRoot.ok ? '✓' : '⋯'
    },
    /**
     * detail 文本：
     * - ok → 显示当前 projectRoot 路径
     * - 其他 → 显示默认克隆父目录（用户看到的始终是父目录，
     *   不是 ~/lingxi/——git 会按仓库名自动创建 lingxi/ 子目录）。
     *   三按钮栈中前两个走 clone 用得上这个提示，第三个「选择已有目录」无关——后者是 picker 自己取路径。
     */
    getProjectRootDetail() {
      if (this.projectRoot.ok) return this.projectRoot.detail || ''
      return `默认克隆父目录：${this.defaultCloneTarget}`
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
 * bootstrap 完成 → BootstrapView 卸载 → 主界面从「灰显禁用」变可交互，零窗口创建/销毁竞态。
 */
.bootstrap-overlay {
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
  animation: bootstrap-fade-in 0.2s ease-out;
}

.bootstrap-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.bootstrap-card {
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
  animation: bootstrap-card-in 0.25s ease-out;
}

@keyframes bootstrap-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes bootstrap-card-in {
  from { opacity: 0; transform: translateY(-8px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0)    scale(1);    }
}

.bootstrap-header {
  margin-bottom: 24px;
}

/* ===== 项目目录行的恢复路径栈 ===== */
/* 当 projectRoot 不 ok 时，.check-item.fixing 行的 .action 区装三个栈按钮
   （克隆默认 / 克隆自定义 / 指向已有 lingxi/）。视觉上要和 check-list 内其他项
   保持一致 —— 不引入独立卡片。 */
.check-item .action-stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

/* 次级 outlined 按钮：border + text 都是 warning-color，与主按钮形成层级 */
.btn-fix-outline {
  border-color: var(--warning-color, #ff9500);
  color: var(--warning-color, #ff9500);
}

.btn-fix-outline:hover {
  background: var(--warning-color, #ff9500);
  color: white;
}

/* 「选择已有的 lingxi/ 目录」按钮：accent 蓝，与前两个橙色「克隆」按钮区分视觉类别
   —— 前两个会写盘（git clone），第三个只定位不写盘，冷暖色直接区分意图 */
.btn-fix-existing {
  border-color: var(--accent-color, #007aff);
  color: var(--accent-color, #007aff);
}

.btn-fix-existing:hover {
  background: var(--accent-color, #007aff);
  color: white;
}

.bootstrap-header h2 {
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

/* 项目根自动迁移横幅：amber 浅底 + 蓝字，告诉用户「我们换到新版本了」。
   视觉上跟 error-bar 区分（红 vs 琥珀），跟 info-banner 也分（蓝条 vs amber 块）。 */
.swap-banner {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 12px;
  padding: 10px 14px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 6px;
  font-size: 13px;
}
.swap-banner .swap-icon {
  font-size: 18px;
  line-height: 1;
}
.swap-banner .swap-title {
  font-weight: 600;
  color: #b45309;
  margin-bottom: 2px;
}
.swap-banner .swap-detail {
  color: var(--text-secondary, #555);
  line-height: 1.5;
  word-break: break-all;
}
.swap-banner .swap-fp {
  color: var(--text-tertiary, #888);
  font-size: 11px;
  font-family: var(--font-mono, monospace);
}
</style>