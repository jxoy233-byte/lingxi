/**
 * 文件类型 → 图标 kind + 中文标签（文件树 / 回收站树共用一套）。
 *
 * 设计目标：让人在 16px 下「一眼看得出是什么文件」——
 *   颜色负责「大概是什么大类」（扫视用），字形负责「具体是什么」（确认用），两者互补。
 *
 * 为什么表驱动而不是一长串 if：
 *   1. 扩展新类型只加一行，不用碰模板；
 *   2. 文件树和回收站树必须表现一致，抽出来才不会各改各的、慢慢走样。
 *
 * 规则顺序敏感：先命中先算，所以更具体的类型（xlsx / docx）必须排在通用 doc 前面。
 */
export const FILE_KIND_RULES = [
  ['sheet', /\.(xlsx|xls|xlsm|numbers|ods)$/],
  ['table', /\.(csv|tsv|psv)$/],
  ['docx', /\.(docx|doc|odt|pages)$/],
  ['pdf', /\.pdf$/],
  ['markdown', /\.(md|markdown|mmd)$/],
  // svg 走「带标记的页面」比走「图片」更贴——它是可缩放的标记，不是位图
  ['html', /\.(html?|xhtml|vue|svg)$/],
  ['image', /\.(png|jpe?g|gif|webp|bmp|tiff?|ico|heic|avif)$/],
  ['video', /\.(mp4|mov|avi|mkv|webm|flv|wmv|m4v)$/],
  ['audio', /\.(mp3|wav|aac|flac|ogg|m4a|wma)$/],
  ['archive', /\.(zip|tar|gz|tgz|rar|7z|bz2|xz|zst|dmg|whl|jar)$/],
  ['font', /\.(ttf|otf|woff2?|eot)$/],
  ['json', /\.(json|jsonl|geojson)$/],
  [
    'code',
    /\.(py|js|mjs|cjs|ts|tsx|jsx|java|c|cc|cpp|h|hpp|cs|go|rs|rb|php|swift|kt|scala|sh|bash|zsh|fish|ps1|sql|r|jl|m|lua|pl|vim|ipynb)$/
  ],
  ['binary', /\.(exe|dll|so|dylib|bin|o|class|pyc|node|wasm|apk|ipa|app)$/],
  ['text', /\.(txt|log|rst|ini|cfg|conf|toml|yaml|yml|xml|properties|env)$/]
]

/**
 * 兜底 kind 单独定义，不作为一条规则混进 FILE_KIND_RULES。
 *
 * Why：混进去的话 `isKnownKind('doc')` 会恒为 true，于是「压根不认得」的文件
 * 也会去拿 doc 的短标，印出毫无信息量的 "FILE"——恰恰是这条路径要避免的东西。
 * 分开之后 FILE_KIND_RULES 里的每个 kind 都是「真的认出来了」，可以放心印短标。
 *
 * 认不出来的情况：没有扩展名（Makefile / LICENSE），或者后缀没注册（.foo / .qqq）。
 */
const FALLBACK_KIND = 'doc'

export const FILE_KIND_LABELS = {
  sheet: 'Excel 表格',
  table: 'CSV 数据表',
  docx: 'Word 文档',
  pdf: 'PDF 文档',
  markdown: 'Markdown 文档',
  html: '网页 / 矢量图',
  image: '图片',
  video: '视频',
  audio: '音频',
  archive: '压缩包',
  font: '字体文件',
  json: 'JSON 数据',
  code: '代码文件',
  binary: '可执行 / 编译产物',
  text: '文本文件',
  doc: '文件'
}

/**
 * kind → 徽章兜底短标。
 * 只在「扩展名太长塞不下」或「压根没扩展名」时才用到——正常情况一律显示真实扩展名。
 */
export const FILE_KIND_BADGE = {
  sheet: 'XLS',
  table: 'CSV',
  docx: 'DOC',
  pdf: 'PDF',
  markdown: 'MD',
  html: 'HTML',
  image: 'IMG',
  video: 'VID',
  audio: 'AUD',
  archive: 'ZIP',
  font: 'FONT',
  json: 'JSON',
  code: 'CODE',
  binary: 'BIN',
  text: 'TXT',
  doc: 'FILE'
}

/** 徽章最多塞 4 个字符（再长就糊成一坨），这个上限同时决定字号档位 */
const MAX_BADGE_CHARS = 4

/**
 * kind 是否命中了某条具体规则（而不是落到兜底的 'doc'）。
 * 决定「扩展名太长时能不能退回一个有共识的短标」：
 * .woff2 命中 font 规则 → FONT 说得通；.zzz 落兜底 → 说什么都说不通，直接画字形。
 */
function isKnownKind(kind) {
  return FILE_KIND_RULES.some(([k]) => k === kind)
}

/**
 * 文件名 → 徽章上的短标，**没有就返回 null**（null = 交给「文档页」字形）。
 *
 * 为什么不画图形字形：18px 下「文档轮廓 / 网格 / 地球」这些抽象符号全都会糊成同一坨，
 * 十几种类型摆在一起根本分不出。直接印真实扩展名（PDF / DOCX / PY / ZIP）才有区分度，
 * 跟 Windows / Adobe 的文件类型图标一致。用户扫一眼就知道是什么，不用点开 title 猜。
 *
 * 三档决策：
 * 1. 扩展名 ≤ 4 字符 → 印真实扩展名（.pdf→PDF / .py→PY / .tsx→TSX）
 * 2. 扩展名太长但 kind 认得 → 印该类型的共识短标（.woff2→FONT / .jsonl→JSON）
 * 3. 压根不认得（Makefile / LICENSE / .后缀未注册）→ **返回 null，画文档页字形**
 *    这种情况印 "FILE" 是最糟的：既没有信息量，又跟其它文本徽章长得一样。
 */
export function fileBadgeText(name) {
  const ext = (name || '').match(/\.([A-Za-z0-9]{1,12})$/)
  if (ext && ext[1].length <= MAX_BADGE_CHARS) return ext[1].toUpperCase()
  const kind = resolveFileKind(name)
  return isKnownKind(kind) ? FILE_KIND_BADGE[kind] : null
}

/**
 * 徽章字号档位：字符越多越小。
 * 24 单位 viewBox 里粗体大写宽度 ≈ 0.62 × fontSize × 字符数，徽章内可用宽约 19 单位
 * → 每档都取「刚好塞满」的最大字号，不留无谓的保守余量（4 字符档是唯一被宽度卡住的档）。
 */
export function badgeFontSize(text) {
  const n = (text || '').length
  if (n <= 1) return 13
  if (n === 2) return 11
  if (n === 3) return 9.6
  return 7.5
}

/** 未知类型走字形而不是短标——模板用它决定画 text 还是画文档页 */
export function hasKnownBadge(name) {
  return fileBadgeText(name) !== null
}

/** 文件名 → kind（未知一律 doc，不返回 null——模板直接当 class 用，null 会渲染出 'dtn-icon-null'） */
export function resolveFileKind(name) {
  const lower = (name || '').toLowerCase()
  for (const [kind, re] of FILE_KIND_RULES) {
    if (re.test(lower)) return kind
  }
  return FALLBACK_KIND
}

/**
 * 文件名 → 悬停提示。徽章已经印了短标，title 负责补完整的
 * 「中文品类 + 真实扩展名」——短标只有 4 个字符，`MD` 到底是 markdown 还是别的要看 title。
 */
export function fileKindHint(name) {
  const label = FILE_KIND_LABELS[resolveFileKind(name)] || FILE_KIND_LABELS.doc
  const ext = (name || '').match(/\.([A-Za-z0-9]{1,12})$/)
  return ext ? `${label}（.${ext[1].toLowerCase()}）` : label
}
