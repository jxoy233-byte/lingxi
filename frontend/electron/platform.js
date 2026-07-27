/**
 * 跨平台路径 + 命令工具
 *
 * 必须在主进程（main.js）的最顶部 import——其他模块依赖这里的常量。
 * 不要在这里 import electron 模块，会导致 preload.js 引用时失败。
 */

import path from 'path'
import os from 'os'

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
 * 跨平台 shell 命令兼容：win 上没有 python3，统一用 python
 */
export function getShellCmd(cmd) {
  if (IS_WIN && cmd === 'python3') return 'python'
  return cmd
}

/**
 * 项目根目录
 * - dev 模式（electron .）：__dirname 上溯到 ChatMe/
 * - packaged（dmg/nsis）：process.resourcesPath 就是根目录
 *     （package.json 的 extraResources 把 docker-compose.yml / sandbox/ / backend/
 *     全部直接复制到 Resources/ 下，所以 resourcesPath 本身就是这些资源的根）
 *
 * ⚠️ 注意：app.isPackaged 必须在 app.whenReady() 之后才能拿到，
 * 所以这个函数**不在模块顶层调用**，由 main.js 在 app.whenReady() 时调用。
 */
export function getProjectRoot(app) {
  if (app.isPackaged) {
    // process.resourcesPath = .../灵析.app/Contents/Resources/（mac）或 .../resources/（win）
    // docker-compose.yml / sandbox/ / backend/ 都在它下面
    return process.resourcesPath
  }
  // dev: frontend/electron/platform.js → frontend/ → ChatMe/
  return path.resolve(__dirname, '..', '..')
}

/**
 * MCP ready 文件路径（Electron 用来判断 MCP 服务完全就绪）
 * - macOS / Linux:  /tmp/chatme-mcp.ready
 * - Windows:        %TEMP%/chatme-mcp.ready
 */
export function mcpReadyFilePath() {
  return path.join(os.tmpdir(), 'chatme-mcp.ready')
}