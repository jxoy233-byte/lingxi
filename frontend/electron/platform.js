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
 * BFS 收窄版本：只从传入的 root 目录开始下钻，命中即返回。
 */
function bfsFrom(root, maxDepth, maxVisits) {
  const queue = [[root, 0]]
  let visits = 0

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
        return full
      }
      if (depth + 1 < maxDepth) queue.push([full, depth + 1])
    }
  }
  return null
}

/**
 * 找项目根：先扫 home 下的常见工作目录（绝大多数用户场景命中），
 * 找不到再降级到 home 全量 BFS。深度提到 5——之前 4 在
 * `~/work/org/repo/lingxi` 这种结构下会漏。
 */
function scanForProjectRoot(maxDepth = 5, maxVisits = 4000) {
  const home = os.homedir()

  // 先扫 home 直下的常见工作目录
  for (const d of COMMON_WORK_DIRS) {
    const full = path.join(home, d)
    if (!fs.existsSync(full)) continue
    const found = bfsFrom(full, maxDepth, maxVisits)
    if (found) return found
  }

  // 降级：home 全量
  return bfsFrom(home, maxDepth, maxVisits)
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
 *   2. 用户上次手动选择并保存到 userData 的路径
 *   3. dev 模式（未打包）：__dirname 上溯（frontend/electron → frontend → 根）
 *   4. home 下 BFS 扫 lingxi/ ChatMe/
 *
 * 第 4 步首次命中时会**自动持久化**：写 userData（让第 2 步下次直接命中）
 * + 写 shell rc / setx（让 CLI 启动也能用 env 变量）。后续启动零成本。
 * 全部没命中返回 null —— 由引导页让用户手动选目录（startup:pick-project-root）。
 *
 * ⚠️ app.isPackaged 要在 app.whenReady() 之后才准，所以不要在模块顶层调用本函数。
 */
export function discoverProjectRoot(app) {
  if (isValidProjectRoot(process.env.LINGXI_PROJECT_ROOT)) {
    return { root: process.env.LINGXI_PROJECT_ROOT, source: 'env' }
  }

  const saved = readSavedProjectRoot(app)
  if (saved) return { root: saved, source: 'saved' }

  if (!app.isPackaged) {
    const devRoot = path.resolve(__dirname, '..', '..')
    if (isValidProjectRoot(devRoot)) return { root: devRoot, source: 'dev' }
  }

  const scanned = scanForProjectRoot()
  if (scanned) {
    // 首次 BFS 命中 → 持久化，best-effort 不阻塞主流程
    try { saveProjectRoot(app, scanned) } catch (e) {
      console.error('[setup] userData 持久化失败:', e.message)
    }
    persistProjectRootToShell(scanned).catch(() => {})
    return { root: scanned, source: 'scan' }
  }

  return { root: null, source: 'none' }
}
