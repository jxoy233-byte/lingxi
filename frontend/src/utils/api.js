/**
 * 后端 API 统一封装
 *
 * 主要为 SettingsDialog 服务：
 * - getConfig()        : GET  /admin/config  （读取可编辑配置，密钥脱敏）
 * - putConfig(update)  : PUT  /admin/config  （保存表单，白名单校验）
 * - restartBackend()   : POST /admin/restart （触发后端重启）
 * - healthCheck()      : GET  /admin/health  （健康检查，前端轮询等待重启）
 */

// 后端基础地址：开发期通过 Vite proxy 转发；Electron / 生产环境走同源
const API_BASE = ''

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`
  const resp = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const data = await resp.json()
      detail = data.detail || JSON.stringify(data)
    } catch (e) {
      // ignore
    }
    throw new Error(`HTTP ${resp.status}: ${detail}`)
  }
  // 202 Accepted（重启）不需要 body
  if (resp.status === 202) return { ok: true }
  return resp.json()
}

/**
 * 读取当前可编辑配置（密钥脱敏）
 * Returns: { ok, config: { llm_providers, skills } }
 */
export async function getConfig() {
  return request('/admin/config', { method: 'GET' })
}

/**
 * 保存配置（白名单校验）
 * @param {Object} update - { llm_providers?, skills? }
 *   api_key 空字符串表示「不修改该字段」
 * Returns: { ok, applied, restart_required, saved_keys }
 */
export async function putConfig(update) {
  return request('/admin/config', {
    method: 'PUT',
    body: JSON.stringify(update),
  })
}

/**
 * 触发后端重启（异步，调用后进程会被 os.execv 替换）
 * 前端拿 202 后开始轮询 healthCheck()，恢复后 window.location.reload()
 */
export async function restartBackend() {
  return request('/admin/restart', { method: 'POST' })
}

/**
 * 健康检查（轮询用）
 */
export async function healthCheck() {
  return request('/admin/health', { method: 'GET' })
}

// =========================================================================
// Scheduled Tasks（定时任务）
// =========================================================================
// 字段对齐 ChatMe/Scheduler/models.py:ScheduledTask.to_api_dict()

/**
 * 列出任务（按 session_id 过滤；空 = 全部）
 * Returns: { ok, tasks: [...] }
 */
export async function listScheduledTasks(sessionId = '') {
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  return request(`/admin/scheduled-tasks${q}`, { method: 'GET' })
}

/**
 * 任务详情
 * Returns: { ok, task, history? }
 */
export async function getScheduledTask(taskId, withHistory = false) {
  const q = withHistory ? '?with_history=true' : ''
  return request(`/admin/scheduled-tasks/${taskId}${q}`, { method: 'GET' })
}

/**
 * 创建任务
 * payload: { name, cron, prompt, session_id? }
 * Returns: { ok, task_id }
 */
export async function createScheduledTask(payload) {
  return request('/admin/scheduled-tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * 更新任务（部分字段；enabled / cron）
 */
export async function updateScheduledTask(taskId, patch) {
  return request(`/admin/scheduled-tasks/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

/**
 * 删除任务
 */
export async function deleteScheduledTask(taskId) {
  return request(`/admin/scheduled-tasks/${taskId}`, {
    method: 'DELETE',
  })
}

/**
 * 手动触发一次任务
 */
export async function runScheduledTask(taskId) {
  return request(`/admin/scheduled-tasks/${taskId}/run`, {
    method: 'POST',
  })
}
