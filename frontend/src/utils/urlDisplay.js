/**
 * URL 显示规范化 —— 把用户可见的 URL 统一处理成「lingxi/...」格式：
 * - 本机 / 内网 host 全部显示成「lingxi」：避免泄露 localhost:18211 / 192.168.x.x:port 等网络细节
 * - 路径保留，query string 保留
 * - 非 URL 字符串（已经是相对路径）原样返回
 *
 * 用法：
 *   normalizeUrlForDisplay('http://localhost:18211/chat/abc/export/artifacts?format=html')
 *   // → 'lingxi/chat/abc/export/artifacts?format=html'
 *   normalizeUrlForDisplay('/static/cached/abc/data.png')
 *   // → '/static/cached/abc/data.png'  (相对路径原样)
 */
export function normalizeUrlForDisplay(url) {
  if (!url) return ''
  // 相对路径 / 非 URL 字符串原样返回
  if (!/^https?:\/\//i.test(url)) return url
  try {
    const u = new URL(url)
    const host = u.hostname
    const isLocal =
      host === 'localhost' ||
      host === '127.0.0.1' ||
      host === '0.0.0.0' ||
      host.endsWith('.local') ||
      /^192\.168\./.test(host) ||
      /^10\./.test(host) ||
      /^172\.(1[6-9]|2\d|3[01])\./.test(host)
    const hostname = isLocal ? 'lingxi' : host
    return hostname + (u.pathname !== '/' ? u.pathname : '') + (u.search || '')
  } catch {
    return url
  }
}