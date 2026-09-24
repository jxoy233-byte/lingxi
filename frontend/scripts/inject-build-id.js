#!/usr/bin/env node
/**
 * 每次 build 前注入 buildId 到 .buildstamp.json。
 * electron-builder 的 extraResources 把 .buildstamp.json 复制到
 * process.resourcesPath/，main.js 启动时读这个文件拿当前 buildId。
 *
 * 与 readStartupPreferences 的 buildId 检测配合：
 *   - 重新 build → buildId 变 → prefs.autoEnterFrontend 重置为 false
 *   - 同一 build 多次启动 → buildId 一致 → 保留用户偏好
 *
 * 比 "用 main.js mtime" 更可靠：无论用户改哪个文件、跑 dev 还是 packaged，
 * 只要这个脚本跑了就 100% 准。.buildstamp.json 加到 .gitignore，不污染 git history。
 *
 * ESM 语法（package.json "type": "module"）。
 */
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const stampPath = join(__dirname, '..', '.buildstamp.json')
const buildId = String(Date.now())
writeFileSync(stampPath, JSON.stringify({ buildId }, null, 2) + '\n')
console.log(`[inject-build-id] buildId = ${buildId}`)