/**
 * v-html 注入前的净化工具
 *
 * 提供两类入口，按来源可信度区分：
 *
 * 1. sanitizeHtml(html) —— 用于「不可信 HTML」（marked 输出 / LLM 文本）
 *    - 剥 <script>、内联事件、javascript: URL
 *    - 保留 data-*、class、id、target / rel、referrerpolicy
 *    - 允许 <iframe>，但强制要求 sandbox（无 sandbox 一律剥 src 再加 sandbox=""）
 *
 * 2. passthroughTrustedSvg(svg) —— 用于「trusted 库输出」（mermaid / echarts SVG）
 *    - 完全 passthrough，不进 DOMPurify
 *    - 仅当 SVG 上游是受信任的 library（mermaid.render / echarts.setOption 等）
 *      才允许使用，理由：
 *      - DOMPurify 默认会剥 <foreignObject> 内容，破坏 mermaid 的 HTML 标签
 *      - library 在 parse 阶段就拒绝 <script> 等恶意标签进入 SVG 输出
 *    - 调用方必须自行保证：来源 = 沙盒 / 系统生成的 SVG，不可直接喂用户原文
 */

import DOMPurify from 'dompurify'

const CONFIG = {
  // markdown 链接：target="_blank" rel="noopener noreferrer"
  ADD_ATTR: ['target', 'rel', 'referrerpolicy'],
  // markdown 中嵌入的文件预览 iframe（带 sandbox 引入时保留）
  ADD_TAGS: ['iframe'],
}

// 进入 DOMPurify 的 iframe 强制要求 sandbox（无 sandbox 可能执行第三方脚本）
DOMPurify.addHook('uponSanitizeElement', (node, data) => {
  if (data.tagName === 'iframe') {
    if (!node.hasAttribute('sandbox')) {
      node.removeAttribute('src')
      node.setAttribute('sandbox', '')
    }
  }
})

export function sanitizeHtml(html) {
  if (!html) return ''
  return DOMPurify.sanitize(html, CONFIG)
}

/**
 * trusted 库输出（mermaid / echarts SVG）直接 passthrough。
 * 必须确认 SVG 来源是 trusted library，禁止喂用户原文。
 */
export function passthroughTrustedSvg(svg) {
  return svg || ''
}
