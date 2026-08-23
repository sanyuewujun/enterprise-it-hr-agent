// 与后端 /api/chat 的 SSE 交互封装

export interface ChatEvent {
  type: string
  content?: string
  route?: string
  reason?: string
  items?: Array<{ source: string; heading: string; score: number }>
  name?: string
  arguments?: Record<string, unknown>
  result?: unknown
  message?: string
  note?: string
}

/**
 * 以流式方式调用对话接口，逐条产出后端事件。
 * @param signal 可用于取消请求（AbortController）
 */
export async function* streamChat(
  message: string,
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  })
  if (!resp.body) throw new Error('无响应体')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let sep: number
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        for (const line of block.split('\n')) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') return
          try {
            yield JSON.parse(data) as ChatEvent
          } catch {
            // 忽略无法解析的行
          }
        }
      }
    }
  } catch (e) {
    // 用户取消（AbortError）时静默结束；其他错误向上抛出
    if ((e as Error).name !== 'AbortError') throw e
  }
}

export interface SessionMeta {
  id: string
  title: string
  updated_at: number
}

export interface HistoryMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  route?: 'simple' | 'complex' | 'blocked'
  sources?: Array<{ source: string; heading: string; score: number }>
  tools?: Array<{ name: string; arguments?: Record<string, unknown>; result?: unknown }>
}

export async function listSessions(): Promise<SessionMeta[]> {
  const resp = await fetch('/api/sessions')
  if (!resp.ok) return []
  const data = await resp.json()
  return (data.sessions || []) as SessionMeta[]
}

export async function getSession(id: string): Promise<HistoryMessage[]> {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(id)}`)
  if (!resp.ok) return []
  const data = await resp.json()
  return (data.messages || []) as HistoryMessage[]
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
