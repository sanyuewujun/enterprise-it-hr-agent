import { useEffect, useRef, useState } from 'react'
import { streamChat, listSessions, getSession, deleteSession, SessionMeta, HistoryMessage } from './api'
import { Message, MessageBubble } from './components/MessageBubble'
import { useTheme } from './components/ThemeToggle'

function genId() {
  return Math.random().toString(36).slice(2, 10)
}

function fmtTime(ts: number): string {
  if (!ts) return ''
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

export default function App() {
  const { dark, toggle } = useTheme()
  // 每个会话独立保存消息，切换会话不丢失
  const [convMessages, setConvMessages] = useState<Record<string, Message[]>>({})
  const [sessionId, setSessionId] = useState<string>(() => genId())
  const [sessions, setSessions] = useState<SessionMeta[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const safetyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 无新事件超过该时长则自动取消，作为兜底防止卡死
  const SAFETY_MS = 25000

  const messages = convMessages[sessionId] || []

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // 首次加载拉取历史会话列表
  useEffect(() => {
    listSessions().then(setSessions).catch(() => {})
  }, [])

  const refreshSessions = () => {
    listSessions().then(setSessions).catch(() => {})
  }

  const updateMsg = (id: string, patch: Partial<Message>) => {
    setConvMessages((prev) => {
      const list = prev[sessionId] || []
      return { ...prev, [sessionId]: list.map((m) => (m.id === id ? { ...m, ...patch } : m)) }
    })
  }

  const clearSafety = () => {
    if (safetyTimer.current) {
      clearTimeout(safetyTimer.current)
      safetyTimer.current = null
    }
  }

  const handleStop = () => {
    abortRef.current?.abort()
    clearSafety()
    fetch('/api/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '', session_id: sessionId }),
    }).catch(() => {})
    setSending(false)
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || sending) return
    const userMsg: Message = { id: genId(), role: 'user', content: text }
    const assistantId = genId()
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      streaming: true,
    }
    setConvMessages((prev) => ({
      ...prev,
      [sessionId]: [...(prev[sessionId] || []), userMsg, assistantMsg],
    }))
    setInput('')
    setSending(true)

    const ac = new AbortController()
    abortRef.current = ac
    let stopped = false
    const markStopped = () => {
      stopped = true
      updateMsg(assistantId, { streaming: false, stopped: true })
    }
    clearSafety()
    safetyTimer.current = setTimeout(() => {
      if (sending) handleStop()
    }, SAFETY_MS)

    const acc: Partial<Message> = { content: '', sources: [], tools: [] }
    try {
      for await (const ev of streamChat(text, sessionId, ac.signal)) {
        clearSafety()
        safetyTimer.current = setTimeout(() => {
          if (sending) handleStop()
        }, SAFETY_MS)
        if (ev.type === 'route') {
          acc.route = ev.route as 'simple' | 'complex' | 'blocked'
          updateMsg(assistantId, { ...acc })
        } else if (ev.type === 'source') {
          acc.sources = ev.items || []
          updateMsg(assistantId, { ...acc })
        } else if (ev.type === 'token') {
          acc.content = (acc.content || '') + (ev.content || '')
          updateMsg(assistantId, { ...acc })
        } else if (ev.type === 'tool') {
          acc.tools = [
            ...(acc.tools || []),
            { name: ev.name || '', arguments: ev.arguments, result: ev.result },
          ]
          updateMsg(assistantId, { ...acc })
        } else if (ev.type === 'error') {
          acc.content = (acc.content || '') + `\n[错误] ${ev.message}`
          updateMsg(assistantId, { ...acc })
        } else if (ev.type === 'done') {
          if (ev.note === '已取消') markStopped()
        }
      }
    } catch (e) {
      acc.content = (acc.content || '') + `\n[连接错误] ${(e as Error).message}`
      updateMsg(assistantId, { ...acc })
    } finally {
      clearSafety()
      if (stopped) markStopped()
      else
        updateMsg(assistantId, { streaming: false })
      setSending(false)
      refreshSessions() // 一轮结束后刷新侧栏（新会话/标题更新）
    }
  }

  const handleNewChat = () => {
    if (sending) handleStop()
    const id = genId()
    setSessionId(id)
    setConvMessages((prev) => ({ ...prev, [id]: [] }))
    setInput('')
  }

  const handleSelectSession = async (id: string) => {
    if (id === sessionId) return
    if (sending) handleStop()
    setSessionId(id)
    // 已加载过则直接切换；否则从后端拉取展示气泡
    if (!convMessages[id]) {
      try {
        const hist: HistoryMessage[] = await getSession(id)
        const msgs: Message[] = hist.map((h) => ({
          id: genId(),
          role: h.role,
          content: h.content,
          route: h.route,
          sources: h.sources,
          tools: h.tools,
        }))
        setConvMessages((prev) => ({ ...prev, [id]: msgs }))
      } catch {
        setConvMessages((prev) => ({ ...prev, [id]: [] }))
      }
    }
    setInput('')
  }

  const handleDeleteSession = async (id: string) => {
    await deleteSession(id).catch(() => {})
    refreshSessions()
    if (id === sessionId) handleNewChat()
  }

  const handleReset = async () => {
    try {
      await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: '', session_id: sessionId }),
      })
    } catch {
      /* ignore */
    }
    setConvMessages((prev) => ({ ...prev, [sessionId]: [] }))
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full bg-slate-100 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
      {/* 左侧会话侧栏 */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="flex items-center justify-between border-b border-slate-200 px-3 py-3 dark:border-slate-700">
          <span className="text-sm font-semibold">对话历史</span>
          <button
            onClick={handleNewChat}
            className="rounded-lg bg-brand-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-600"
          >
            ➕ 新对话
          </button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto p-2">
          {sessions.length === 0 && (
            <div className="px-2 py-4 text-center text-xs text-slate-400">
              暂无历史，发送消息后自动保存
            </div>
          )}
          {sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => handleSelectSession(s.id)}
              className={`group flex cursor-pointer items-center justify-between rounded-lg px-2.5 py-2 text-sm ${
                s.id === sessionId
                  ? 'bg-brand-50 text-brand-700 dark:bg-slate-700 dark:text-brand-300'
                  : 'hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate">{s.title || '(无标题)'}</div>
                <div className="text-[10px] text-slate-400">{fmtTime(s.updated_at)}</div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleDeleteSession(s.id)
                }}
                className="ml-1 hidden rounded px-1 text-slate-400 hover:text-rose-500 group-hover:block"
                title="删除会话"
              >
                🗑
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* 右侧主区域 */}
      <div className="flex flex-1 flex-col">
        {/* 顶部栏 */}
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
          <div className="flex items-center gap-2">
            <span className="text-lg">🤖</span>
            <div>
              <div className="text-sm font-semibold">企业智能 IT/HR 助手</div>
              <div className="text-[11px] text-slate-400">
                轻量速答 · 智能助手（RAG + 工具调用）
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="rounded-lg px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              清空当前
            </button>
            <button
              onClick={toggle}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-700"
            >
              {dark ? '☀️ 亮色' : '🌙 暗色'}
            </button>
          </div>
        </header>

        {/* 消息区 */}
        <main ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {messages.length === 0 && (
            <div className="mt-10 text-center text-sm text-slate-400">
              你好，我是企业智能助手小智。可以问我制度问题（如“年假怎么算”），
              或让我帮你查信息、建工单（如“查张伟的年假”“VPN 连不上帮我建工单”）。
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} msg={m} />
          ))}
        </main>

        {/* 输入区 */}
        <footer className="border-t border-slate-200 bg-white px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              className="max-h-32 flex-1 resize-none rounded-xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-600 dark:bg-slate-900"
            />
            <button
              onClick={sending ? handleStop : handleSend}
              disabled={!sending && !input.trim()}
              className={
                sending
                  ? 'rounded-xl bg-rose-500 px-4 py-2 text-sm font-medium text-white hover:bg-rose-600'
                  : 'rounded-xl bg-brand-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50'
              }
            >
              {sending ? '停止' : '发送'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
