import axios from 'axios'

/**
 * axios 实例
 * - baseURL 为 /api：开发模式由 Vite 代理到 :8000，生产模式由 FastAPI 同源托管
 * - timeout 35s：略大于后端 30s 超时，确保后端先返回友好的 504，而非前端生硬掐断
 */
const http = axios.create({
  baseURL: '/api',
  timeout: 65000  // 略大于后端 60s 上限，避免后端仍在处理时前端先报错
})

/**
 * 智慧问诊
 * @param {string} query 用户问题
 * @param {string} sessionId 会话 ID
 * @returns {Promise} 后端 ConsultationResponse：
 *   { answer, intent, symptoms, departments, medications,
 *     disclaimers, warnings, duration_ms, timestamp }
 */
export function consult(query, sessionId) {
  return http.post('/consult', { query, session_id: sessionId })
}

/**
 * 健康检查
 * @returns {Promise} { status, neo4j_connected, vector_index_loaded, agent_system_ready, ... }
 */
export function health() {
  return http.get('/health')
}

/**
 * 对话历史列表（按 updated_at 倒序，后端读 MySQL）
 * @returns {Promise} { conversations: [{id, title, created_at, updated_at}] }
 */
export function listConversations() {
  return http.get('/conversations')
}

/**
 * 恢复单个对话（全部消息，时间正序）
 * @param {string} id 对话 ID（= session_id）
 * @returns {Promise} { conversation_id, messages: [{role, content, intent, created_at}] }
 */
export function getConversation(id) {
  return http.get(`/conversations/${id}`)
}

/**
 * 删除对话（MySQL 两表 + Redis key 同步清空）
 * @param {string} id 对话 ID
 */
export function deleteConversation(id) {
  return http.delete(`/conversations/${id}`)
}

/**
 * 流式问诊（SSE）
 * EventSource 不支持 POST，故用 fetch + ReadableStream 手工解析 SSE 帧。
 * 事件协议（对应后端 POST /api/consult/stream）：
 *   event: progress — { node, label, facts }      每个 Agent 节点完成的进度
 *   event: answer   — ConsultationResponse JSON   完整终答（字段与 /consult 一致）
 *   event: error    — { message }                 错误信息
 *   event: done     — [DONE]                      结束标记
 *
 * @param {string} query 用户问题
 * @param {string} sessionId 会话 ID
 * @param {object} callbacks { onProgress, onAnswer, onError, onDone }
 * @returns {Promise<void>} 连接层失败时 reject（调用方据此降级回 consult()）
 */
export async function consultStream(query, sessionId, callbacks = {}) {
  const resp = await fetch('/api/consult/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, session_id: sessionId })
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`SSE 连接失败：HTTP ${resp.status}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatch = (frame) => {
    // 一帧形如："event: progress\ndata: {...}"（data 可能多行）
    let event = 'message'
    const dataLines = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    const data = dataLines.join('\n')
    try {
      if (event === 'progress') callbacks.onProgress?.(JSON.parse(data))
      else if (event === 'answer') callbacks.onAnswer?.(JSON.parse(data))
      else if (event === 'error') callbacks.onError?.(JSON.parse(data))
      else if (event === 'done') callbacks.onDone?.()
    } catch (e) {
      console.warn('SSE 帧解析失败:', event, data, e)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE 帧以空行（\n\n）分隔
    let sepIndex
    while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sepIndex)
      buffer = buffer.slice(sepIndex + 2)
      if (frame.trim()) dispatch(frame)
    }
  }
}

export default http
