/**
 * mammoth / xlsx 模块级 Promise 缓存。
 *
 * 旧实现（v0.3.6 drawer 时代）用组件实例字段（_mammoth / _xlsx）缓存，
 * 多个 inline preview 各自一份会重复 import。模块级 Promise 缓存保证整个
 * 会话内只 import 一次，第二个 await 直接拿到已 resolved 的 promise。
 *
 * mammoth chunk ~150KB，xlsx ~700KB —— 全局只拉一次对首屏体验很重要。
 */

let _mammothPromise = null
export function loadMammoth() {
  if (!_mammothPromise) {
    _mammothPromise = import('mammoth/mammoth.browser.js').then(m => m.default || m)
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