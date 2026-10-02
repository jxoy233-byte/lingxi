/**
 * Word「原文」视图的纯文本抽取（从已解析好的 DOM 树拿）。
 *
 * 为什么要放 utils 而不是留在 ToolDocPreview.vue 里：这段 walk 逻辑是整个
 * 「原文编辑 → 保存回 docx」链路里最容易出错的一环（表格摊平、图片占位、
 * 容器递归），抽成不依赖组件的纯函数才能脱离浏览器单测。
 *
 * 契约：`root` 是塞了 mammoth HTML 的容器元素，返回按文档顺序排列的段落数组。
 * 段落之间的空行由调用方 join('\n\n')。
 *
 * 三条规则各有代价（UI 的 .raw-hint 里也写给用户看了）：
 *   - 表格按行 `\t` 拼成一段 —— 表结构丢失，但内容不丢
 *   - 列表项加 `• ` / `1. ` 前缀
 *   - 图片用 `[[图片 N]]` 占位，N = 文档顺序（1 起），后端按 N 搬回原位
 */

/** 图片占位符的构造/匹配必须与后端 `APIRouter/word_editor.py:_IMG_PLACEHOLDER` 一致。 */
export function imagePlaceholder(n) {
  return `[[图片 ${n}]]`
}

export function extractPlainTextBlocks(root) {
  const out = []

  // 先按 DOM 顺序给每张图编号 —— 与后端「body 里第 N 个含 drawing 的子元素」
  // 一一对应。递归 walk 可能从不同分支碰到同一张图，用 emitted 去重。
  const imgOrder = new Map()
  const allImgs = root.querySelectorAll('img')
  for (let i = 0; i < allImgs.length; i++) imgOrder.set(allImgs[i], i + 1)

  const emitted = new Set()
  const pushImages = (el) => {
    const imgs = el.querySelectorAll('img')
    for (let i = 0; i < imgs.length; i++) {
      const im = imgs[i]
      if (emitted.has(im)) continue
      emitted.add(im)
      out.push(imagePlaceholder(imgOrder.get(im)))
    }
  }

  const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim()
  // 先文字后图片：mammoth 的内联图是 <p>文字<img></p>，图在文字之后
  const pushText = (el) => {
    const t = clean(el.textContent)
    if (t) out.push(t)
  }

  const walkList = (listEl, ordered) => {
    const items = listEl.children
    for (let i = 0; i < items.length; i++) {
      const li = items[i]
      if (li.tagName !== 'LI') continue
      const t = clean(li.textContent)
      if (t) out.push((ordered ? `${i + 1}. ` : '• ') + t)
    }
  }

  const walkTable = (tbl) => {
    const rows = tbl.querySelectorAll('tr')
    for (let r = 0; r < rows.length; r++) {
      const cells = rows[r].querySelectorAll('th,td')
      const vals = []
      for (let c = 0; c < cells.length; c++) vals.push(clean(cells[c].textContent))
      if (vals.some((v) => v)) out.push(vals.join('\t'))
    }
  }

  const walk = (parent) => {
    const kids = parent.children
    for (let i = 0; i < kids.length; i++) {
      const el = kids[i]
      const tag = el.tagName
      if (tag === 'TABLE') {
        walkTable(el)
        pushImages(el)
      } else if (tag === 'UL' || tag === 'OL') {
        walkList(el, tag === 'OL')
        pushImages(el)
      } else if (tag === 'IMG') {
        pushImages(el)
      } else if (tag === 'DIV' || tag === 'SECTION') {
        walk(el)   // 容器递归：只下沉不产出，否则会把子块文字重复输出
      } else {
        // 其余（H1-H6 / P / 其它内联块）
        pushText(el)
        pushImages(el)
      }
    }
  }

  walk(root)
  return out
}
