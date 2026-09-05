/**
 * 跨平台路径 + 项目根定位
 *
 * 必须在主进程（main.js）的最顶部 import——其他模块依赖这里的常量。
 * 不要在这里 import electron 模块（preload 引用时会失败）；需要 app 的函数用参数传进来。
 */

import path from 'path'
import os from 'os'
import fs from 'fs'
import { exec, spawn } from 'child_process'
import { fileURLToPath } from 'url'

// ESM 里没有 __dirname，必须自己算（用 __dirname 会直接 ReferenceError）
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

export const IS_WIN = process.platform === 'win32'
export const IS_MAC = process.platform === 'darwin'
export const ARCH = process.arch  // 'arm64' | 'x64' | 'ia32'

// lingxi 项目 GitHub 仓库地址（autoClone 唯一来源；main 进程的 silent auto-clone
// 与 BootstrapView 用户确认卡片两条路径都引用这里，改地址只改这一行）
export const LINGXI_REPO_URL = 'https://github.com/jxoy233-byte/lingxi.git'

/**
 * 跨平台 venv Python 路径
 * - macOS / Linux:  .venv/bin/python
 * - Windows:        .venv/Scripts/python.exe
 */
export function venvPythonPath(projectRoot) {
  const venv = path.join(projectRoot, 'backend', '.venv')
  return IS_WIN
    ? path.join(venv, 'Scripts', 'python.exe')
    : path.join(venv, 'bin', 'python')
}

/**
 * 拿一个「能跑 main.py」的 Python 命令：优先 venv 里的，缺失时退化到系统 python3 / python。
 *
 * 返回数组形式 [exe, ...args]，方便直接传给 spawn：
 *   const [exe, ...args] = resolvePythonForBackend(projectRoot)
 *   spawn(exe, [...args, 'main.py'], { ... })
 *
 * 为什么要 fallback：
 *  - 用户可能在 .venv 损坏或没跑过 uv sync 时启动 app；直接报错太凶
 *  - 用系统 python 跑 main.py 时 import 会失败——但失败信息更明确（缺哪些包），
 *    用户再去跑 uv sync 也比"什么都看不到"好
 *  - 即使用 venv，也用「python -m」而非直跑 .venv/bin/python（PATH 解析更稳）
 */
export function resolvePythonForBackend(projectRoot) {
  const venvPy = venvPythonPath(projectRoot)
  try {
    if (fs.existsSync(venvPy)) {
      return IS_WIN ? [venvPy] : [venvPy]
    }
  } catch {}
  // 退化：系统 python（让 uv sync 自动补依赖 + 明确报错引导用户）
  const sysPy = IS_WIN ? 'python' : (IS_MAC || true) ? 'python3' : 'python'
  return [sysPy]
}

/**
 * 跨平台 shell 命令兼容：win 上没有 python3，统一用 python
 */
export function getShellCmd(cmd) {
  if (IS_WIN && cmd === 'python3') return 'python'
  return cmd
}

/**
 * 用用户在交互 shell 里跑命令 —— 拿到跟用户终端一致的环境。
 *
 * 为什么不用直接 exec('python3 --version')：
 * Electron 父进程是 GUI launchd（macOS）/ explorer.exe（Win），
 * 它继承的 PATH 不包含 `.zshrc` / `.bashrc` 里的 export，也不走 macOS path_helper
 * （`/etc/paths.d/*` 只在 login interactive shell 启动时被 `/etc/zprofile` 调用）。
 * 结果用户在终端能跑的 python3，Electron 子进程 ENOENT。
 *
 * 解法（按平台分流）：
 *   - macOS/Linux: `$SHELL -ilc '<cmd>'`
 *     -i  interactive：让 `eval "$(pyenv init -)"` 这类 interactive-only 初始化也走
 *     -l  login：让 /etc/zprofile → path_helper → /etc/paths.d/* 被注入
 *     -c  跑命令
 *   - Windows: `cmd.exe /d /s /c '<cmd>'`
 *     -ilc 是 bash/zsh 标志，cmd.exe 不认（会把它当文件名找）。所以 Windows 走 cmd.exe 自己的标志：
 *     /d 跳过 AutoRun 注册表项；/s 调整引号处理（docker compose 命令里常有
 *         `--format "{{.State.Status}}"` 这种含引号参数，没有 /s 时外层 /c 的字符串边界识别会断）；
 *     /c 执行命令后退出。
 *
 * ⚠️ 性能成本：每次 ~200ms（pyenv rehash + zsh 启动；cmd 启动也 ~50ms）。
 *   不适合做高频调用；这里只在 probe / 启动后端时用。
 *
 * 这是 best-effort：极少数用户的 .zshrc 用 `[[ $- != *i* ]] && return` 早期 return，
 * 会拿不到。CLI prompt（python3 / docker / uv）找不到时会在 UI 上显示具体报错。
 */
export async function execInUserShell(command, opts = {}) {
  const shell = getUserShell()
  // spawn 直跑避免 /bin/sh 二次包裹；不走 exec() 默认行为
  // HISTFILE=/dev/null 屏蔽 zsh "Restored session" 噪音（不影响 PATH 解析，cmd.exe 忽略此变量）
  return new Promise((resolve, reject) => {
    const child = IS_WIN
      ? spawn(shell, ['/d', '/s', '/c', command], {
          timeout: opts.timeout ?? 10_000,
          cwd: opts.cwd,
          windowsHide: true,
          env: { ...process.env, HISTFILE: '/dev/null' },
        })
      : spawn(shell, ['-ilc', command], {
          timeout: opts.timeout ?? 10_000,
          cwd: opts.cwd,
          windowsHide: true,
          env: { ...process.env, HISTFILE: '/dev/null' },
        })
    let stdout = '', stderr = ''
    child.stdout?.on('data', d => stdout += d.toString())
    child.stderr?.on('data', d => stderr += d.toString())
    child.on('error', err => reject(err))
    child.on('close', code => {
      if (code === 0) resolve((stdout || stderr).trim())
      else reject(new Error(`exit ${code}: ${(stderr || stdout).trim().slice(0, 300)}`))
    })
  })
}

/**
 * 用户当前登录 shell：
 *  - macOS/Linux: $SHELL（Terminal.app / iTerm2 / GNOME Terminal 等都设这个）
 *  - Windows:     %ComSpec%（通常是 cmd.exe）
 */
export function getUserShell() {
  if (IS_WIN) return process.env.ComSpec || 'cmd.exe'
  return process.env.SHELL || '/bin/sh'
}

// ==================== 项目根定位 ====================
//
// 设计前提（重要）：app 里**不打包 backend/**。
// 用户从 GitHub 拉的项目（目录名 lingxi/ 或 ChatMe/）在本机任意路径，
// app 只负责「找到那个目录」，然后所有探测 / 修复 / 启动命令都在它下面跑。
// 这样 .venv、.chatme/config.json、cached/、docker-compose.yml 全部用本地那一份，
// 不存在「包内一份、本地一份」的分裂问题。

/** 拉下来的仓库可能叫这几个名字 */
const CANDIDATE_NAMES = ['lingxi', 'chatme']

/** BFS 扫描时跳过的目录（体积大 / 不可能放项目） */
const SKIP_DIRS = new Set([
  // 通用（构建 / 依赖产物）
  'Library', 'Applications', 'System', 'Music', 'Movies', 'Pictures',
  'node_modules', '.git', '.venv', 'venv', '__pycache__', 'dist',
  'Trash', '.Trash', 'AppData', 'Windows', 'Program Files',
  'Downloads', 'downloads', 'Desktop', 'desktop',
  // Linux 大目录（避免 maxVisits=4000 被吃掉扫不到项目）
  // .cargo / .rustup 是 registry cache / git refs，几乎不可能放项目源码
  '.cache', '.config', '.local', '.cargo', '.rustup',
  '.npm', '.nvm', '.yarn', '.next', '.claude',
  // 包管理器数据
  'snap', '.snap', 'flatpak', '.var',
])

/**
 * BFS 优先扫的 home 下子目录（绝大多数用户把项目放这几个地方）。
 * 不扫全 home——一是隐私（不该 readdir 用户所有目录），二是速度。
 * 找不到再降级到 home 全量 BFS。
 */
const COMMON_WORK_DIRS = [
  'Code', 'code', 'Projects', 'projects', 'work', 'workspace',
  'repos', 'src', 'dev', 'Developer', 'Documents',
]

/**
 * 判断一个目录是不是有效的项目根。
 * 判据取「app 真正要用到的两个东西」：
 *   - backend/pyproject.toml  → uv sync / python main.py 的落点
 *   - docker-compose.yml      → docker compose up redis / build sandbox 的落点
 * 只认目录名不靠谱（用户可能改名），只认其中一个也不够（可能是别的仓库）。
 */
export function isValidProjectRoot(dir) {
  if (!dir || typeof dir !== 'string') return false
  try {
    return fs.existsSync(path.join(dir, 'backend', 'pyproject.toml')) &&
           fs.existsSync(path.join(dir, 'docker-compose.yml'))
  } catch {
    return false
  }
}

// ==================== 版本指纹 ====================
//
// 目的：当用户换了新代码库（重新 git pull / 换目录 / 多副本共存）时，
// saved PROJECT_ROOT（userData/project-root.json 持久化）可能指向旧副本，
// 旧副本的 `app_config.get("port", N)` 兜底端口 / pyproject 版本号都还是老值，
// 启动时 main.js 的端口探测拿到的是老值 → 全部端口错乱。
//
// 解决：每次 discoverProjectRoot 都读 saved 路径 + BFS 候选的指纹，
// 谁的版本号更新用谁；端口字段变化了也能识别（不在 saved 段时仍以 saved 为准，
// BFS 里有更新版本才迁移）。
//
// 为什么不直接用 saved 路径永远赢：因为 Windows 重启 / 中途断电 / 换硬盘时
// 旧目录可能不可达或被新目录取代；纯 cached path 永远跟新代码脱节。

/**
 * 读 pyproject.toml 第一段 `version = "X.Y.Z"`。
 * 不引入 toml 解析（避免给主进程加重型依赖），用正则够用——pyproject 顶层
 * version 总是单行 `version = "..."` 格式（PEP 621）。
 */
function _readPyprojectVersion(projectRoot) {
  try {
    const text = fs.readFileSync(path.join(projectRoot, 'backend', 'pyproject.toml'), 'utf8')
    const m = text.match(/^\s*version\s*=\s*["']([^"']+)["']/m)
    return m ? m[1] : null
  } catch {
    return null
  }
}

/**
 * 读 backend/main.py 兜底端口 `app_config.get("port", NNNNN)`。
 * 这个数字一旦变了（比如 8211 → 38211），BFS 候选里的新值就是权威。
 * 只匹配主入口里的字面值，不深入（兜底端口通常写在一行；具体生效逻辑靠 ChatMeConfig）。
 */
function _readMainPyPort(projectRoot) {
  try {
    const text = fs.readFileSync(path.join(projectRoot, 'backend', 'main.py'), 'utf8')
    const m = text.match(/app_config\.get\(\s*["']port["']\s*,\s*(\d{4,6})\s*\)/)
    return m ? parseInt(m[1], 10) : null
  } catch {
    return null
  }
}

/**
 * 取一个项目根的「版本指纹」。
 * 返回 { version: string|null, port: number|null }；任一字段缺失为 null（不抛）。
 *
 * 后续 _compareFingerprints 用这两个字段决定哪个更新：version 不同以 version 为主，
 * version 相同才看 port（port 不一致说明用户改了端口但没 bump version，照样走更新）。
 */
export function _readProjectFingerprint(projectRoot) {
  return {
    version: _readPyprojectVersion(projectRoot),
    port: _readMainPyPort(projectRoot),
  }
}

/**
 * 简单 semver 比较（major.minor.patch，忽略 prerelease / build）。
 * 任一为 null → 返回 0（视为相等，由调用方决定 fallback）。
 * 返回：a > b → 正数；a < b → 负数；相等 → 0。
 */
function _compareSemver(a, b) {
  if (!a || !b) return 0
  const pa = a.split('.').map(n => parseInt(n, 10) || 0)
  const pb = b.split('.').map(n => parseInt(n, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0, y = pb[i] || 0
    if (x !== y) return x - y
  }
  return 0
}

/**
 * 比较两个指纹谁更新。
 * 规则：
 *   1) version 双方都有 → 以 semver 判定（-1/0/+1）
 *   2) version 有一方缺失 → 用 port 是否变化判定（任一方缺失视为「不知道」，返 0）
 *   3) 全部相同 → 0
 *
 * 调用方通常用 > 0 表示「b 比 a 新」；相同版本但 port 不同也算 b 更新（罕见，但兜底）。
 */
function _compareFingerprints(a, b) {
  if (a.version && b.version) {
    const v = _compareSemver(a.version, b.version)
    if (v !== 0) return v
  }
  // version 相同或缺失 → 看 port 是否变了
  if (a.port && b.port && a.port !== b.port) {
    // port 不一致：按「端口数字更大」为更新约定不靠谱（迁移可能升也可能降）；
    // 用 saved vs candidate 的相对位置来判：candidate 端口是未来端口 → candidate 更新。
    // 实际上发现 port 变化且 version 没变通常是开发期手工改的，candidate 优先即可。
    return 1
  }
  return 0
}

const STARTUP_PREFERENCES_FILE = 'startup-preferences.json'

function startupPreferencesPath(app) {
  return path.join(app.getPath('userData'), STARTUP_PREFERENCES_FILE)
}

export function readStartupPreferences(app) {
  try {
    const raw = fs.readFileSync(startupPreferencesPath(app), 'utf8')
    const parsed = JSON.parse(raw)
    return { autoEnterFrontend: parsed.autoEnterFrontend === true }
  } catch {
    return { autoEnterFrontend: false }
  }
}

export function saveStartupPreferences(app, preferences) {
  const p = startupPreferencesPath(app)
  fs.mkdirSync(path.dirname(p), { recursive: true })
  fs.writeFileSync(
    p,
    JSON.stringify({ autoEnterFrontend: preferences.autoEnterFrontend === true }, null, 2),
    'utf8'
  )
}

/** 用户手动选过的项目根，存到 userData（跨启动持久化） */
function savedConfigPath(app) {
  return path.join(app.getPath('userData'), 'project-root.json')
}

export function readSavedProjectRoot(app) {
  try {
    const raw = fs.readFileSync(savedConfigPath(app), 'utf8')
    const dir = JSON.parse(raw).projectRoot
    return isValidProjectRoot(dir) ? dir : null
  } catch {
    return null
  }
}

export function saveProjectRoot(app, dir) {
  const p = savedConfigPath(app)
  fs.mkdirSync(path.dirname(p), { recursive: true })
  fs.writeFileSync(p, JSON.stringify({ projectRoot: dir }, null, 2), 'utf8')
}

/**
 * BFS 收窄版本：从传入的 root 目录开始下钻，命中即返回第一个 valid 根。
 * 旧路径，给保留为单元用——discoverProjectRoot 现在改用 _bfsCollectAll 拿全候选。
 */
function bfsFrom(root, maxDepth, maxVisits) {
  const found = _bfsCollectAll(root, maxDepth, maxVisits)
  return found.length > 0 ? found[0] : null
}

/**
 * BFS 全量收：返回所有命中的 valid 项目根（[{path, fingerprint}, ...]）。
 * 不再「命中即返回」——升级判断要拿全候选对比 fingerprint。
 */
function _bfsCollectAll(root, maxDepth, maxVisits) {
  const queue = [[root, 0]]
  let visits = 0
  const results = []

  while (queue.length && visits < maxVisits) {
    const [dir, depth] = queue.shift()
    visits++

    let entries
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
      continue
    }

    for (const e of entries) {
      if (!e.isDirectory()) continue
      if (e.name.startsWith('.') || SKIP_DIRS.has(e.name)) continue

      const full = path.join(dir, e.name)
      if (CANDIDATE_NAMES.includes(e.name.toLowerCase()) && isValidProjectRoot(full)) {
        results.push({ path: full, fingerprint: _readProjectFingerprint(full) })
        // 不 return，继续下钻（深度可能更深还有同名 lingxi/）
      }
      if (depth + 1 < maxDepth) queue.push([full, depth + 1])
    }
  }
  return results
}

// ==================== 最近 clone 路径临时变量 ====================
//
// 模块级临时变量：记录最近一次 autoCloneProject 的成功路径。
// 作用：clone 后 discoverProjectRoot 重检测时优先用这个值（避免 BFS 扫盘，
//       也兜底 saveProjectRoot 写盘失败导致 saved 路径不命中的场景）。
// 进程重启后自动重置为 null——跨启动靠 readSavedProjectRoot 命中。
let lastCloneTarget = null

/** 暴露给 caller 主动覆盖（pickProjectRoot 选了不同目录时调） */
export function setLastCloneTarget(dir) {
  lastCloneTarget = dir && isValidProjectRoot(dir) ? dir : null
}

export function getLastCloneTarget() {
  return lastCloneTarget
}

/**
 * 找项目根：先扫 home 下的常见工作目录（绝大多数用户场景命中），
 * 找不到再降级到 home 全量 BFS。深度提到 5——之前 4 在
 * `~/work/org/repo/lingxi` 这种结构下会漏。
 *
 * 返回 [{path, fingerprint}, ...]（不去重）；discoverProjectRoot 自己挑 best。
 * 兼容旧行为：调用方拿首个就当作旧 scanForProjectRoot 的返回值。
 */
function _scanAllProjectRoots(maxDepth = 5, maxVisits = 4000) {
  const home = os.homedir()
  const collected = []
  const seen = new Set()

  const pushUnique = (cands) => {
    for (const c of cands) {
      if (!seen.has(c.path)) {
        seen.add(c.path)
        collected.push(c)
      }
    }
  }

  // 先扫 home 直下的常见工作目录
  for (const d of COMMON_WORK_DIRS) {
    const full = path.join(home, d)
    if (!fs.existsSync(full)) continue
    pushUnique(_bfsCollectAll(full, maxDepth, maxVisits))
  }

  // 降级：home 全量
  pushUnique(_bfsCollectAll(home, maxDepth, maxVisits))

  return collected
}

/**
 * 旧 API 兼容：从全量扫描里取第一个有效根。
 * 新代码应直接用 _scanAllProjectRoots + discoverProjectRoot 的版本比较逻辑。
 */
function scanForProjectRoot(maxDepth = 5, maxVisits = 4000) {
  const all = _scanAllProjectRoots(maxDepth, maxVisits)
  return all.length > 0 ? all[0].path : null
}

/**
 * 把项目根写到 shell 环境变量（best-effort，失败不抛）。
 *
 * 设计目的：用户从 GitHub 拉项目 → app 自动找到 lingxi/ → 写 env
 * → 后续 CLI（chatme_mcp / chatme_main）启动时不用再传路径或 cd。
 *
 * - macOS/Linux: 追加到 $SHELL 对应的 rc 文件（zsh→.zshrc, bash→.bashrc, fish→config.fish）
 *   只在 login shell 的 bash 才写 .bash_profile
 * - Windows: `setx LINGXI_PROJECT_ROOT <path>`（写用户环境变量，永久）
 *
 * 已存在 `LINGXI_PROJECT_ROOT=` 的赋值就跳过，避免重复追加污染 rc 文件。
 */
export function persistProjectRootToShell(dir) {
  return new Promise((resolve) => {
    try {
      if (IS_WIN) {
        exec(`setx LINGXI_PROJECT_ROOT "${dir}"`, (err, _stdout, stderr) => {
          if (err) resolve({ ok: false, error: (stderr || err.message || '').trim() })
          else resolve({ ok: true })
        })
        return
      }

      const home = os.homedir()
      const shell = process.env.SHELL || ''
      let rcFile, line

      if (shell.includes('zsh')) {
        rcFile = path.join(home, '.zshrc')
        line = `export LINGXI_PROJECT_ROOT="${dir}"`
      } else if (shell.includes('fish')) {
        rcFile = path.join(home, '.config', 'fish', 'config.fish')
        line = `set -gx LINGXI_PROJECT_ROOT "${dir}"`
      } else if (shell.includes('bash')) {
        // macOS bash login 读 .bash_profile，Linux 一般读 .bashrc
        rcFile = (IS_MAC && !fs.existsSync(path.join(home, '.bashrc')))
          ? path.join(home, '.bash_profile')
          : path.join(home, '.bashrc')
        line = `export LINGXI_PROJECT_ROOT="${dir}"`
      } else {
        // 兜底：哪个 rc 存在写哪个
        const zshrc = path.join(home, '.zshrc')
        rcFile = fs.existsSync(zshrc) ? zshrc : path.join(home, '.bashrc')
        line = `export LINGXI_PROJECT_ROOT="${dir}"`
      }

      // 写之前先确保目录在（fish config.fish 需要）
      fs.mkdirSync(path.dirname(rcFile), { recursive: true })

      let existing = ''
      try { existing = fs.readFileSync(rcFile, 'utf8') } catch {}
      if (existing.includes('LINGXI_PROJECT_ROOT=')) {
        // 已有赋值，**不**自动改值（用户可能手动改成别的）；只标 skipped
        return resolve({ ok: true, skipped: true, rcFile })
      }

      const block = `\n# ChatMe project root (auto-added by 灵析 app, do not edit)\n${line}\n`
      fs.appendFileSync(rcFile, block)
      resolve({ ok: true, rcFile })
    } catch (e) {
      resolve({ ok: false, error: e.message })
    }
  })
}

/**
 * 项目根定位，按优先级：
 *   1. LINGXI_PROJECT_ROOT 环境变量（CLI / 调试 / 特殊部署）
 *   2. 用户上次手动选择并保存到 userData 的路径 —— **带版本指纹校验**：
 *      如果 BFS 能扫到比 saved 更新（version 大 / port 变化）的 lingxi/，自动迁移
 *      到新路径并返回 `swappedFrom` 字段供 UI 提示用户。
 *   3. dev 模式（未打包）：__dirname 上溯（frontend/electron → frontend → 根）
 *   4. home 下 BFS 扫 lingxi/ ChatMe/
 *
 * 第 4 步首次命中时会**自动持久化**：写 userData（让第 2 步下次直接命中）
 * + 写 shell rc / setx（让 CLI 启动也能用 env 变量）。后续启动零成本。
 * 全部没命中返回 null —— 由引导页让用户手动选目录（startup:pick-project-root）。
 *
 * ⚠️ app.isPackaged 要在 app.whenReady() 之后才准，所以不要在模块顶层调用本函数。
 *
 * 返回 { root, source, swappedFrom? }：
 *   - root: 最终使用的项目根路径
 *   - source: 'env' | 'clone' | 'saved' | 'dev' | 'scan' | 'swap' | 'none'
 *     - 'swap': saved 路径被自动迁移到更新版本（root 是新值）
 *     - 其他值与旧语义一致
 *   - swappedFrom: 仅当发生自动迁移时存在，{ path, fingerprint } 指向旧 saved
 */
export function discoverProjectRoot(app) {
  if (isValidProjectRoot(process.env.LINGXI_PROJECT_ROOT)) {
    return { root: process.env.LINGXI_PROJECT_ROOT, source: 'env' }
  }

  // 优先检查刚刚 clone 出来的路径（clone 后用户还没做任何事，肯定想用这个）。
  // 兜底场景：saveProjectRoot 写 userData 失败 / saved 路径被别处 lingxi/ 覆盖，
  // 这时 lastCloneTarget 是「本进程最权威」的当前路径。
  // env 优先级最高：用户主动设置 LINGXI_PROJECT_ROOT 时不被临时变量抢占。
  if (lastCloneTarget && isValidProjectRoot(lastCloneTarget)) {
    return { root: lastCloneTarget, source: 'clone' }
  }

  const saved = readSavedProjectRoot(app)
  if (saved) {
    // saved 命中 → 但还是要跑一次 BFS 收集候选，比 fingerprint 看是否有过期副本。
    // 为什么不直接信任 saved：Windows 启动失败场景里 saved 路径可能指向旧 lingxi/ 副本，
    // 副本里 backend/main.py 还写着兜底端口 8211，新 lingxi/ 已经迁移到 38211。
    // 不比对的话 saved 永远赢 → 后端永远起不来。
    const savedFp = _readProjectFingerprint(saved)
    const candidates = _scanAllProjectRoots().filter(c => c.path !== saved)

    let bestCandidate = null
    for (const c of candidates) {
      if (_compareFingerprints(savedFp, c.fingerprint) < 0) {
        // c 比 saved 更新 → 候选赢；多个候选时挑 version 最大的（port 仅作 tie-break）
        if (!bestCandidate || _compareFingerprints(bestCandidate.fingerprint, c.fingerprint) < 0) {
          bestCandidate = c
        }
      }
    }

    if (bestCandidate) {
      // 自动迁移：持久化新路径 + log warn（main.js console 能看到，调试用）
      console.warn(
        `[setup] ⚠️ saved PROJECT_ROOT 落后于 BFS 候选，自动迁移: ` +
        `${saved} (v${savedFp.version || '?'}:${savedFp.port || '?'}) → ` +
        `${bestCandidate.path} (v${bestCandidate.fingerprint.version || '?'}:${bestCandidate.fingerprint.port || '?'})`
      )
      try { saveProjectRoot(app, bestCandidate.path) } catch (e) {
        console.error('[setup] 迁移时 userData 持久化失败:', e.message)
      }
      persistProjectRootToShell(bestCandidate.path).catch(() => {})
      return {
        root: bestCandidate.path,
        source: 'swap',
        swappedFrom: { path: saved, fingerprint: savedFp },
      }
    }

    return { root: saved, source: 'saved' }
  }

  if (!app.isPackaged) {
    const devRoot = path.resolve(__dirname, '..', '..')
    if (isValidProjectRoot(devRoot)) return { root: devRoot, source: 'dev' }
  }

  const candidates = _scanAllProjectRoots()
  if (candidates.length > 0) {
    // 首次 BFS 命中 → 持久化第一个，best-effort 不阻塞主流程
    const first = candidates[0]
    try { saveProjectRoot(app, first.path) } catch (e) {
      console.error('[setup] userData 持久化失败:', e.message)
    }
    persistProjectRootToShell(first.path).catch(() => {})
    return { root: first.path, source: 'scan' }
  }

  return { root: null, source: 'none' }
}

// ==================== Git 自动 clone ====================

/**
 * 检测 git 是否安装。返回 { ok, detail }。
 * 用 execInUserShell 拿与用户终端一致的 PATH（pyenv / Homebrew / Git for Windows）。
 */
export async function detectGitInstalled() {
  try {
    const out = await execInUserShell('git --version', { timeout: 5000 })
    return { ok: true, detail: out.trim() }
  } catch {
    return { ok: false, detail: 'git 未安装（请安装 Git for Windows / Xcode Command Line Tools）' }
  }
}

/**
 * 启动 Docker Desktop（daemon 未跑时用）。
 * 跨平台策略：
 *   - macOS: `open -a Docker`（靠 LaunchServices 找 /Applications/Docker.app）
 *   - Windows: 常见安装路径探测 Docker Desktop.exe 并 spawn；找不到时回退 Start Menu
 *     的 `docker`（PATH 里走通时打开 Docker Desktop 入口）
 *   - Linux: `systemctl start docker`（service 兜底）——多数发行版通用
 * 返回 { ok, error? }。不验证 daemon 是否真的起来（启动慢，UI 端轮询 recheck）。
 */
export async function startDockerDesktop() {
  try {
    if (IS_MAC) {
      await new Promise((resolve, reject) => {
        exec('open -a Docker', { timeout: 5_000 }, (err, _stdout, stderr) => {
          if (err) reject(new Error(stderr?.trim() || err.message))
          else resolve()
        })
      })
      return { ok: true }
    }

    if (IS_WIN) {
      // 常见安装路径，按 Newer→Older 顺序探测（Docker 4.x 改 LOCALAPPDATA）
      const candidates = [
        path.join(process.env.LOCALAPPDATA || '', 'Docker', 'Docker', 'Docker Desktop.exe'),
        path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'Docker', 'Docker', 'Docker Desktop.exe'),
        path.join(process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)', 'Docker', 'Docker', 'Docker Desktop.exe'),
      ].filter(Boolean)

      let exe = null
      for (const c of candidates) {
        if (c && fs.existsSync(c)) { exe = c; break }
      }
      if (!exe) {
        return { ok: false, error: '未找到 Docker Desktop.exe，请确认 Docker Desktop 已安装' }
      }
      // 用 spawn 解耦，detached 让 Docker Desktop 独立进程脱离父进程生命周期
      const child = spawn(exe, [], { detached: true, stdio: 'ignore', windowsHide: true })
      child.unref()
      return { ok: true }
    }

    // Linux: 优先 systemctl，失败回退 service
    await new Promise((resolve, reject) => {
      exec('systemctl start docker', { timeout: 10_000 }, (err, _stdout, stderr) => {
        if (err) {
          exec('service docker start', { timeout: 10_000 }, (err2, _stdout2, stderr2) => {
            if (err2) reject(new Error(stderr2?.trim() || stderr?.trim() || err.message))
            else resolve()
          })
        } else resolve()
      })
    })
    return { ok: true }
  } catch (err) {
    return { ok: false, error: err.message || String(err) }
  }
}

/**
 * 自动 git clone 项目到 targetDir/lingxi/。已存在且合法 → 复用；已存在但不合法 → 拒绝。
 *
 * 注意 targetDir 是「父目录」（git 会按仓库名自动建 lingxi/ 子目录），
 * caller 必须传父目录，不能传 ~/lingxi/ 本身——否则 git 会在 ~/lingxi/lingxi/ 嵌套。
 * 仓库名从 opts.repoUrl 末段提取（去掉 .git 后缀）。
 *
 * @param {Electron.App} app — 用于 saveProjectRoot 持久化
 * @param {object} opts
 * @param {string} [opts.targetDir] — 默认 ~/(git 会建 ~/lingxi/)
 * @param {string} [opts.repoUrl]  — 默认 LINGXI_REPO_URL（platform.js 顶部常量）
 * @param {(msg: string) => void} [opts.onLog] — 实时日志回调（main 进程 silent 时传 () => {}）
 * @returns {Promise<{ok: boolean, projectRoot?: string, source?: 'existing'|'cloned', error?: string}>}
 */
export async function autoCloneProject(app, opts = {}) {
  const targetDir = opts.targetDir || os.homedir()
  const repoUrl = opts.repoUrl || LINGXI_REPO_URL
  const onLog = opts.onLog || (() => {})

  // 从 URL 末段提取仓库名作为 git clone 自动创建的子目录名
  // 例：https://github.com/jxoy233-byte/lingxi.git → 'lingxi'
  const repoName = (repoUrl.split('/').pop() || 'lingxi').replace(/\.git$/, '') || 'lingxi'
  const projectRoot = path.join(targetDir, repoName)

  // 1) 已存在且合法 → 复用
  if (fs.existsSync(projectRoot) && isValidProjectRoot(projectRoot)) {
    onLog(`[clone] 复用已存在的项目根：${projectRoot}\n`)
    setLastCloneTarget(projectRoot)  // 进程内优先用这个（即便 saved 没命中也能找到）
    try { saveProjectRoot(app, projectRoot) } catch (e) {
      console.error('[clone] userData 持久化失败：', e.message)
    }
    return { ok: true, projectRoot, source: 'existing' }
  }

  // 2) 已存在但不是 lingxi → 拒绝（防覆盖）
  if (fs.existsSync(projectRoot)) {
    return {
      ok: false,
      error: `${projectRoot} 已存在但不是有效的 lingxi 项目根（缺 backend/pyproject.toml 或 docker-compose.yml）。请手动选择其他目录。`,
    }
  }

  // 3) clone
  // ⚠️ Win 上 `git clone "<url>" "<path>"` 走 cmd.exe /c 字符串拼装经常翻车：
  //   - 中文用户名 / 路径含空格 → cmd.exe 引号转义把路径搞坏
  //   - git for Windows 2.40+ 在某些 home 子目录路径上报
  //     `fatal: could not create leading directories ...: Invalid argument`（git bug）
  // 修法：直接 spawn('git', ['clone', url, path]) 用数组参数，完全绕开 cmd.exe 字符串解析。
  // PATH 用用户 shell 真实 PATH（mac/linux: printenv PATH；Win: echo %PATH%），
  // 保证能命中 git 命令（git 在 `C:\Program Files\Git\cmd\git.exe`，不在 Electron 父进程 PATH 里）。
  //
  // cwd 选 os.tmpdir() 而不是 targetDir / homedir：
  //   - cwd = targetDir 时 git 在自己下面建 repoName/（某些 git 版本会触发上面那个 bug）
  //   - cwd = homedir 时若 targetDir = ~/(用户选了 home)，cwd == targetDir，危险
  //   - tmpdir 永远不是用户项目父目录，绝对不会撞上 cwd == targetDir 的边界场景
  onLog(`[clone] git clone ${repoUrl} ${projectRoot}\n`)
  try {
    const { spawn: childSpawn } = await import('child_process')
    // 拿用户 shell 真实 PATH
    let shellPath = ''
    try {
      const cmd = IS_WIN ? 'echo %PATH%' : 'printenv PATH'
      const out = await execInUserShell(cmd, { timeout: 3000 })
      // 过滤掉非路径行（zsh 偶尔的 "Restored session" 噪音）
      const validLine = out.split('\n')
        .map(l => l.trim())
        .find(l => IS_WIN
          ? /^[A-Za-z]:[\\/]/.test(l) || l.includes(':\\')
          : l.startsWith('/'))
      shellPath = validLine || process.env.PATH || ''
    } catch {
      shellPath = process.env.PATH || ''
    }
    const sep = IS_WIN ? ';' : ':'
    const merged = [...new Set([
      ...(shellPath ? shellPath.split(sep) : []),
      ...((process.env.PATH || '').split(sep)),
    ])].join(sep)
    const env = { ...process.env, PATH: merged }

    const child = childSpawn('git', ['clone', repoUrl, projectRoot], {
      env,
      cwd: os.tmpdir(),  // 避免 cwd == targetDir 触发 git Win bug
      timeout: 300_000,  // 5 分钟
      windowsHide: true,
    })
    let stdout = '', stderr = ''
    child.stdout?.on('data', d => { stdout += d.toString(); onLog(d.toString()) })
    child.stderr?.on('data', d => { stderr += d.toString(); onLog(d.toString()) })

    await new Promise((resolve, reject) => {
      child.on('error', reject)
      child.on('close', code => {
        if (code === 0) resolve()
        else reject(new Error(`exit ${code}: ${(stderr || stdout).trim().slice(0, 500)}`))
      })
    })
  } catch (err) {
    return { ok: false, error: `git clone 失败：${err.message}` }
  }

  // 4) clone 完校验（防御网络中间人或 repo 错误）
  if (!isValidProjectRoot(projectRoot)) {
    return { ok: false, error: `clone 完成但目录结构校验失败：${projectRoot}` }
  }

  // 5) 持久化（让下次启动 discoverProjectRoot 第 2 级 saved 直接命中）
  setLastCloneTarget(projectRoot)  // 进程内优先用这个（discoverProjectRoot 第 1.5 级）
  try { saveProjectRoot(app, projectRoot) } catch (e) {
    console.error('[clone] userData 持久化失败：', e.message)
  }
  persistProjectRootToShell(projectRoot).catch(() => {})  // best-effort

  return { ok: true, projectRoot, source: 'cloned' }
}
