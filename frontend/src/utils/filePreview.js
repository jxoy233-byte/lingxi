export const MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'])
const HTML_EXTENSIONS = new Set(['.html', '.htm'])
const OFFICE_EXTENSIONS = new Set(['.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls', '.pdf'])

export function getFileSuffix(file = {}) {
  if (file.suffix) {
    const suffix = String(file.suffix).toLowerCase()
    return suffix.startsWith('.') ? suffix : `.${suffix}`
  }
  const name = String(file.name || '')
  const dotIndex = name.lastIndexOf('.')
  return dotIndex >= 0 ? name.slice(dotIndex).toLowerCase() : ''
}

export function isImagePreviewFile(file = {}) {
  const type = String(file.file_type || file.type || '').toLowerCase()
  return type === 'image' || type.startsWith('image/') || IMAGE_EXTENSIONS.has(getFileSuffix(file))
}

export function isHtmlPreviewFile(file = {}) {
  const type = String(file.file_type || file.type || '').toLowerCase()
  return type === 'html' || type === 'text/html' || HTML_EXTENSIONS.has(getFileSuffix(file))
}

export function isOfficePreviewFile(file = {}) {
  return OFFICE_EXTENSIONS.has(getFileSuffix(file))
}

function hashString(value) {
  let hash = 2166136261
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

export function buildFilePreviewSourceKey(file = {}, sessionId = '', resolvedUrl = '') {
  const explicitId = file.file_id || file.fileId || file.id || file.path
  if (explicitId) return `${sessionId || 'global'}:${explicitId}`

  const url = resolvedUrl || file.url || file.preview_url || file.iframe_url || file.preview || ''
  if (url && !String(url).startsWith('data:')) {
    return `${sessionId || 'global'}:${url}`
  }

  const name = file.name || 'preview'
  const size = file.size ?? file.file_size ?? ''
  const modifiedAt = file.modified_at || file.updated_at || ''
  const dataIdentity = url ? `${String(url).length}:${hashString(String(url))}` : 'no-url'
  return `${sessionId || 'global'}:${name}:${size}:${modifiedAt}:${dataIdentity}`
}

export function truncateTextToBytes(text, maxBytes = MAX_TEXT_PREVIEW_BYTES) {
  const value = String(text || '')
  const encoded = new TextEncoder().encode(value)
  if (encoded.byteLength <= maxBytes) {
    return { text: value, truncated: false, totalBytes: encoded.byteLength }
  }

  let end = maxBytes
  while (end > Math.max(0, maxBytes - 4)) {
    try {
      return {
        text: new TextDecoder('utf-8', { fatal: true }).decode(encoded.subarray(0, end)),
        truncated: true,
        totalBytes: encoded.byteLength
      }
    } catch (_) {
      end--
    }
  }

  return {
    text: new TextDecoder('utf-8').decode(encoded.subarray(0, end)),
    truncated: true,
    totalBytes: encoded.byteLength
  }
}

function parseContentRange(value) {
  const match = String(value || '').match(/^bytes\s+(\d+)-(\d+)\/(\d+|\*)$/i)
  if (!match) return null
  return {
    start: Number(match[1]),
    end: Number(match[2]),
    total: match[3] === '*' ? null : Number(match[3])
  }
}

export async function fetchTextPreview(
  url,
  { signal, sizeHint = 0, maxBytes = MAX_TEXT_PREVIEW_BYTES } = {}
) {
  // 已知 0 字节文件（新创建的空文件）不发 Range header —— 否则 FastAPI FileResponse 会回 416
  // （HTTP 416 = Requested Range Not Satisfiable，因为 0 字节文件没有 bytes=0-3999 这段）
  const useRange = sizeHint > 0
  const response = await fetch(url, {
    signal,
    headers: useRange ? { Range: `bytes=0-${maxBytes - 1}` } : undefined
  })
  // 416 兜底：万一 sizeHint 不准（比如缓存陈旧、文件刚被清空），也按「空文件」处理而不是抛错
  if (response.status === 416) {
    return { text: '', truncated: false, totalBytes: 0 }
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const contentRange = parseContentRange(response.headers.get('content-range'))
  const contentLength = Number(response.headers.get('content-length')) || 0
  const declaredTotal = contentRange?.total || Number(sizeHint) || (
    response.status === 200 ? contentLength : 0
  )

  if (!response.body || typeof response.body.getReader !== 'function') {
    const buffer = new Uint8Array(await response.arrayBuffer())
    const visible = buffer.subarray(0, maxBytes)
    return {
      text: new TextDecoder('utf-8').decode(visible),
      truncated: buffer.byteLength > maxBytes || declaredTotal > maxBytes,
      totalBytes: declaredTotal || buffer.byteLength
    }
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let text = ''
  let receivedBytes = 0
  let hasMoreData = false

  try {
    while (receivedBytes < maxBytes) {
      const { done, value } = await reader.read()
      if (done) break

      const remaining = maxBytes - receivedBytes
      const visibleChunk = value.byteLength > remaining ? value.subarray(0, remaining) : value
      text += decoder.decode(visibleChunk, { stream: true })
      receivedBytes += visibleChunk.byteLength

      if (value.byteLength > remaining) {
        hasMoreData = true
        break
      }
    }

    if (receivedBytes >= maxBytes && !declaredTotal && !contentRange) {
      const lookahead = await reader.read()
      hasMoreData = !lookahead.done
    }
  } finally {
    const completeBody = !hasMoreData && (
      receivedBytes < maxBytes || (declaredTotal > 0 && declaredTotal <= receivedBytes)
    )
    if (completeBody) text += decoder.decode()
    if (receivedBytes >= maxBytes || hasMoreData) {
      await reader.cancel().catch(() => {})
    }
  }

  const truncated = hasMoreData || declaredTotal > receivedBytes || (
    contentRange?.total != null && contentRange.end + 1 < contentRange.total
  )

  return {
    text,
    truncated,
    totalBytes: declaredTotal || receivedBytes
  }
}
