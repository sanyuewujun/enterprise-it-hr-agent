import { SourceCard } from './SourceCard'
import { ToolCallBadge } from './ToolCallBadge'
import { Markdown } from './Markdown'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  route?: 'simple' | 'complex' | 'blocked'
  sources?: Array<{ source: string; heading: string; score: number }>
  tools?: Array<{ name: string; arguments?: Record<string, unknown>; result?: unknown }>
  streaming?: boolean
  stopped?: boolean
}

export function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
          isUser
            ? 'bg-brand-500 text-white'
            : 'bg-white text-slate-800 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700'
        }`}
      >
        {msg.route && (
          <div className="mb-1 text-[11px] font-medium text-slate-400">
            {msg.route === 'simple' ? '⚡ 轻量速答' : msg.route === 'blocked' ? '⚠️ 已拦截' : '🤖 智能助手'}
          </div>
        )}
        {isUser ? (
          <div className="whitespace-pre-wrap">{msg.content}</div>
        ) : (
          <>
            <div className="markdown-body">
              <Markdown content={msg.content} />
            </div>
            {/* 思考/工具调用阶段：左气泡不再空白，给出明确状态反馈 */}
            {!msg.content && msg.streaming && !msg.stopped && (
              <span className="inline-flex items-center gap-1 text-slate-400">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.2s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.1s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                <span className="ml-1">{msg.tools && msg.tools.length > 0 ? '正在调用工具…' : '模型思考中…'}</span>
              </span>
            )}
            {msg.streaming && msg.content && <span className="ml-0.5 animate-pulse">▍</span>}
            {msg.stopped && (
              <span className="ml-1 text-xs text-slate-400">（已停止）</span>
            )}
          </>
        )}
        {msg.sources && msg.sources.length > 0 && (
          <div className="mt-1">
            {msg.sources.map((s, i) => (
              <SourceCard key={i} source={s} />
            ))}
          </div>
        )}
        {msg.tools &&
          msg.tools.map((t, i) => <ToolCallBadge key={i} tool={t} />)}
      </div>
    </div>
  )
}
