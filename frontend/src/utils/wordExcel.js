/**
 * Word / Excel skill 检测 + 路径规范化工具。
 *
 * 为什么抽到 utils：检测 WordEditor / ExcelEditor 调用的正则和 sandbox 路径规范化
 * 逻辑需要在 App.vue (SSE handler) 和 ToolDocPreview.vue (inline 渲染) 两处共用。
 * 复刻必然 drift（WordEditor 加新方法时漏同步）；抽成纯函数 → 单点真理。
 *
 * 与后端 `APIRouter/word_editor.py` 的 `_resolve_safe(sid, relPath)` 对齐：
 *   - normalizeDocPath 输出 URL 形如 `/static/cached/{sid}/X.docx`（前端 fetch 用）
 *   - ToolDocPreview 的 _relPath() 剥 sid 得相对路径（save POST body 里也用）
 *   - 后端 _resolve_safe 自己拼 sid → CACHED_DIR / sid / relPath
 */

export function isWordEditorCall(tool) {
  if (!tool || tool.name !== 'code') return false
  const code = String(tool?.args?.code || '')
  return /from\s+skills\.WordEditor\s+import\b/i.test(code)
      && /\bWordDoc\.(?:create|open)\s*\(/i.test(code)
}

export function isExcelEditorCall(tool) {
  if (!tool || tool.name !== 'code') return false
  const code = String(tool?.args?.code || '')
  return /from\s+skills\.ExcelEditor\s+import\b/i.test(code)
      && /\bExcelDoc\.(?:create|open|from_csv)\s*\(/i.test(code)
}

/**
 * sid 占位符：SKILL.md 示例写的是 "/cached/{sid}/report.docx"，AI 照着写成
 * f-string 后花括号里就是这个（或同义的 session_id / sessionId）。
 */
const _SID_TOKEN = /\{(?:session_id|sessionId|sid)\}/gi
/**
 * `.format(sid)` 惯用法的位置占位符。多个同时出现时猜不出哪个是 sid，
 * 所以只在**恰好一个**时才替换。
 */
const _FMT_TOKEN = /\{\}|\{[01]\}/g

/** 把路径字面量里的 sid 占位符换成真实 session_id；换不了返回 null。 */
function _substituteSid(p, sessionId) {
  if (!sessionId) return p
  const out = p.replace(_SID_TOKEN, sessionId)
  const fmt = out.match(_FMT_TOKEN) || []
  if (fmt.length === 1) return out.replace(_FMT_TOKEN, sessionId)
  if (fmt.length > 1) return null   // 多个位置占位符 → 映射猜不准，弃用这个候选
  return out
}

/**
 * 只拿末段文件名 + 当前 session 目录兜底。
 *
 * 两类候选走这条路：
 *   ① 裸文件名（`os.path.join("/cached", sid, "报告.docx")` 只捞得到 `"报告.docx"`）
 *   ② 前缀解不出来的路径（`f"{OUT_DIR}/报告.docx"` → `{OUT_DIR}/报告.docx`，
 *      OUT_DIR 是个局部变量，前端无从得知）
 * 宁可猜一个大概率对的 session 目录，也不要整条丢弃 —— 丢弃 = 面板永远不弹。
 */
function _bareNameFallback(p, sessionId) {
  const tail = String(p || '').split('/').pop() || ''
  if (!tail || /[{}]/.test(tail) || !/\.(docx|xlsx)$/i.test(tail)) return null
  if (!sessionId) return null
  return `/cached/${sessionId}/${tail}`
}

/**
 * 解析单个候选字面量 → 真实路径。
 *
 * 替换 sid 占位符 → 解不出来的前缀退化成「末段文件名 + 当前 session 目录」。
 * 返回 null 表示「这个候选不能用」，调用方继续试下一个。
 *
 * 注：f/r/b 这类字符串前缀在正则里已经被前缀组吃掉，不会进到这里。
 */
function _resolveLiteral(lit, sessionId) {
  if (!lit) return null
  let p = _substituteSid(String(lit).trim(), sessionId)
  if (p === null) return null
  if (/[{}]/.test(p)) return _bareNameFallback(p, sessionId)  // 前缀解不出 → 猜 session 目录
  if (!/\.(docx|xlsx)$/i.test(p)) return null
  if (!p.includes('/') && sessionId) p = `/cached/${sessionId}/${p}`
  return p
}

/**
 * 从 code 里解析文档路径（Word / Excel 共用）。
 *
 * 为什么不能只认「紧跟 open/create 的字符串字面量」：AI 实际写出来的形态很多，
 * f-string、先赋值给变量再传进去、.format()、+ 拼接全都合法。原来那条正则只吃
 * 字面量紧跟括号的情况，其余一律返回 null —— 表现就是思考面板里出现了
 * 「Word 文档」指示器，但右侧面板永远不自动弹、点了也没反应（三处调用全被这一个
 * null 静默 return 掐断）。
 *
 * 改成「候选队列 + 逐个降级」：
 *   ① create() 调用点的字面量 —— 优先，因为我们要预览的是**正在写**的那份，
 *      不是 open() 进来的那份（"open 输入 → create 输出" 的续写场景会 open 在前）
 *   ② open() / from_csv() 调用点的字面量
 *   ③ 全代码里所有以 .docx / .xlsx 结尾的字面量（覆盖变量 / 拼接 / format）
 * 每个候选过一遍 _resolveLiteral，先解析成功的胜出。
 */
function _extractDocPath(tool, ext, sessionId) {
  const code = String(tool?.args?.code || '')
  if (!code) return null

  const candidates = []
  // 前缀组吃掉 f/r/b 等；group1 = 引号，group2 = 引号内的路径
  const atCall = (method) => {
    const re = new RegExp(
      `\\b(?:WordDoc|ExcelDoc)\\.${method}\\s*\\(\\s*(?:[fFrRbBuU]{1,2})?(["'\`])([^"'\`\\n]*)\\1`
    )
    const m = re.exec(code)
    return m ? m[2] : null
  }
  for (const method of ['create', 'open', 'from_csv']) {
    const p = atCall(method)
    if (p) candidates.push(p)
  }

  const litRe = new RegExp(`(["'\`])([^"'\`\\n]*?\\.${ext})\\1`, 'gi')
  let g
  while ((g = litRe.exec(code)) !== null) candidates.push(g[2])

  for (const c of candidates) {
    const p = _resolveLiteral(c, sessionId)
    if (p) return p
  }
  return null
}

/**
 * 抽 WordDoc.create / WordDoc.open 写的文档路径。
 * 传 sessionId 才能解 f-string 里的 {session_id} 占位符。
 */
export function extractWordPath(tool, sessionId = '') {
  return _extractDocPath(tool, 'docx', sessionId)
}

/** 抽 ExcelDoc.create / open / from_csv 写的文档路径。 */
export function extractExcelPath(tool, sessionId = '') {
  return _extractDocPath(tool, 'xlsx', sessionId)
}

/**
 * 从工具 stdout 里捞出**实际写到磁盘**的文档路径（权威兜底）。
 *
 * 为什么需要：从 code 文本猜路径本质是猜——AI 完全可以写成
 * `f"{OUT}/报告.docx"` / `os.path.join(...)` / 变量拼接，猜错就静默不开面板。
 * 而 stdout 是工具自己 print 的真实路径（WordEditor 惯例 `OK -> /cached/{sid}/X.docx`），
 * tool_call_result 阶段拿它当真理来源，code 解析只负责「更早弹面板」。
 *
 * 扫所有匹配项并取第一个带 sid 的候选；没有 sid 目录的就取第一个。
 */
export function extractDocPathFromOutput(stdout, sessionId = '') {
  const text = String(stdout || '')
  if (!text) return null
  const re = /((?:\/)?(?:static\/)?cached\/[^\s'"<>,;)\]]+?\.(?:docx|xlsx))/gi
  const hits = []
  let m
  while ((m = re.exec(text)) !== null) {
    const p = m[1].replace(/\/+$/, '')
    if (hits.includes(p)) continue
    hits.push(p)
    if (sessionId && p.includes(`/${sessionId}/`)) return p
  }
  return hits[0] || null
}

/**
 * 把 sandbox 路径规范成 fetch URL。
 *
 * 输入形如："/cached/report.docx" / "cached/report.docx" / "/work/sub/X.docx"
 *          或 AI 自己拼 sid 的 "/cached/{sid}/X.docx"
 * 输出形如："/static/cached/..."（去掉 /cached/ 前缀，信任 AI 给的路径前缀原样转发）
 *
 * 为什么不再加 sid：
 *   - 旧版强行加 sid 会让 URL 变成 /static/cached/{sid}/X.docx，但 AI 实际写到 backend/cached/X.docx
 *     （沙盒 /cached 挂载到 host backend/cached/，没有 sid 嵌套），404
 *   - static_file._has_session_id 检测到 sid 时不走 fallback
 *   - 改成「信任 AI 路径」：剥 /cached/ 前缀后直接转 /static/cached/，URL 与实际文件位置对齐
 *   - 副作用：跨 session 同名文件会冲突——但这是 sandbox flat mount 的固有特性，跟前端 URL 无关
 *
 * 不存在路径 → null（调用方应跳过）
 */
export function normalizeDocPath(raw) {
  let p = String(raw || '').replace(/^\/?(?:cached|work)\//, '').replace(/^cached\//, '')
  if (!p) return null
  return `/static/cached/${p}`
}