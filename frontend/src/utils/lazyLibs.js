/**
 * mammoth / xlsx 模块级 Promise 缓存。
 *
 * 旧实现（v0.3.6 drawer 时代）用组件实例字段（_mammoth / _xlsx）缓存，
 * 多个 inline preview 各自一份会重复 import。模块级 Promise 缓存保证整个
 * 会话内只 import 一次，第二个 await 直接拿到已 resolved 的 promise。
 *
 * 懒加载 chunk 实测（v0.3.8，mammoth 1.12.3）：mammoth 381KB / xlsx 418KB
 * —— 全局只拉一次对首屏体验很重要。
 *
 * ⚠️ mammoth 用包主入口 `mammoth`，**不要**改成 `mammoth/mammoth.browser.js`。
 * 后者是伸手进别人包里的 browserify 预构建产物：路径随时可能消失，且失败
 * 只在「那台机器的 node_modules 没装全」时出现，本地永远复现不了
 * （v0.3.8 Windows 打包就是这么断的：Rollup failed to resolve import）。
 * Vite 客户端构建会应用 mammoth package.json 的 browser 字段，把
 * lib/unzip.js 换成 browser/unzip.js（真 ArrayBuffer 实现，不是 stub）、
 * lib/docx/files.js 换成浏览器版，所以主入口在浏览器里同样吃 { arrayBuffer }，
 * 调用方（ToolDocPreview.vue）无需改动。
 * 换过去反而更小：预构建 bundle 494KB → 主入口 381KB。
 */

let _mammothPromise = null
export function loadMammoth() {
  if (!_mammothPromise) {
    _mammothPromise = import('mammoth').then(m => m.default || m)
  }
  return _mammothPromise
}

let _xlsxPromise = null
export function loadXLSX() {
  if (!_xlsxPromise) {
    _xlsxPromise = import('xlsx').then(m => (m.read ? m : m.default))
  }
  return _xlsxPromise
}
