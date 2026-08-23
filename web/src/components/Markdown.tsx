import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

/**
 * 助手消息的 Markdown 渲染组件。
 * - 使用 react-markdown + remark-gfm（支持表格 / 删除线 / 任务列表等 GFM 语法）；
 * - 通过 components 映射为 Tailwind 样式，并适配明暗主题；
 * - 流式输出时传入的是「半截」Markdown，react-markdown 能容错渲染，无需特殊处理。
 */
const components: Components = {
  h1: ({ node, ...props }) => (
    <h1 className="mb-2 mt-3 text-base font-bold text-slate-900 first:mt-0 dark:text-slate-100" {...props} />
  ),
  h2: ({ node, ...props }) => (
    <h2 className="mb-2 mt-3 text-[15px] font-bold text-slate-900 first:mt-0 dark:text-slate-100" {...props} />
  ),
  h3: ({ node, ...props }) => (
    <h3 className="mb-1.5 mt-2 text-sm font-semibold text-slate-900 first:mt-0 dark:text-slate-100" {...props} />
  ),
  p: ({ node, ...props }) => <p className="my-1.5 leading-relaxed" {...props} />,
  a: ({ node, ...props }) => (
    <a
      className="text-brand-600 underline decoration-brand-300 underline-offset-2 hover:text-brand-700 dark:text-brand-300"
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  ul: ({ node, ...props }) => <ul className="my-1.5 list-disc space-y-1 pl-5" {...props} />,
  ol: ({ node, ...props }) => <ol className="my-1.5 list-decimal space-y-1 pl-5" {...props} />,
  li: ({ node, ...props }) => <li className="leading-relaxed" {...props} />,
  blockquote: ({ node, ...props }) => (
    <blockquote
      className="my-2 border-l-4 border-slate-300 pl-3 text-slate-500 italic dark:border-slate-600 dark:text-slate-400"
      {...props}
    />
  ),
  hr: ({ node, ...props }) => <hr className="my-3 border-slate-200 dark:border-slate-700" {...props} />,
  strong: ({ node, ...props }) => <strong className="font-semibold text-slate-900 dark:text-slate-100" {...props} />,
  em: ({ node, ...props }) => <em className="italic" {...props} />,
  code: ({ node, className, children, ...props }) => {
    const isBlock = /language-/.test(className || '')
    if (isBlock) {
      return (
        <code
          className="block overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100 dark:bg-black/60"
          {...props}
        >
          {children}
        </code>
      )
    }
    return (
      <code
        className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em] text-rose-600 dark:bg-slate-700 dark:text-rose-300"
        {...props}
      >
        {children}
      </code>
    )
  },
  pre: ({ node, ...props }) => <pre className="my-2" {...props} />,
  table: ({ node, ...props }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs" {...props} />
    </div>
  ),
  thead: ({ node, ...props }) => <thead className="bg-slate-100 dark:bg-slate-700" {...props} />,
  th: ({ node, ...props }) => (
    <th className="border border-slate-200 px-2 py-1 text-left font-semibold dark:border-slate-600" {...props} />
  ),
  td: ({ node, ...props }) => (
    <td className="border border-slate-200 px-2 py-1 dark:border-slate-600" {...props} />
  ),
}

export function Markdown({ content }: { content: string }) {
  return (
    <div className="text-sm leading-relaxed text-slate-800 dark:text-slate-100">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
