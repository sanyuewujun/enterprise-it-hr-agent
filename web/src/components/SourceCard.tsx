interface Source {
  source: string
  heading: string
  score: number
}

export function SourceCard({ source }: { source: Source }) {
  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
      <span className="font-medium text-brand-600 dark:text-brand-100">
        📄 {source.source}
      </span>
      {source.heading && (
        <span className="ml-1">· {source.heading}</span>
      )}
      <span className="ml-1 text-slate-400">相关度 {source.score}</span>
    </div>
  )
}
