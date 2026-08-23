interface ToolCall {
  name: string
  arguments?: Record<string, unknown>
  result?: unknown
}

function summarize(t: ToolCall): string {
  const r = t.result as { ticket_id?: string; found?: boolean; message?: string; escalated?: boolean } | undefined
  if (t.name === 'create_it_ticket' && r?.ticket_id) return `已创建工单 ${r.ticket_id}`
  if (t.name === 'escalate_to_human') return '已转接人工客服'
  if (t.name === 'query_employee') return r?.found ? '已查询员工信息' : '未找到员工'
  if (t.name === 'query_it_assets') return r?.found ? '已查询 IT 资产' : '无登记资产'
  if (t.name === 'check_leave_balance') return r?.found ? '已查询假期余额' : '无假期记录'
  if (t.name === 'search_policy') return r?.found ? '已检索制度' : '未检索到相关制度'
  return `已调用 ${t.name}`
}

export function ToolCallBadge({ tool }: { tool: ToolCall }) {
  return (
    <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-3 py-1 text-xs text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300 dark:ring-emerald-800">
      <span>🔧</span>
      <span className="font-medium">{summarize(tool)}</span>
    </div>
  )
}
