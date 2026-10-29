// Markdown 正文渲染（/docs 文档页）：react-markdown + remark-gfm（表格 / 删除线 / 任务列表）。
// 版式由 index.css 的 .doc-prose 承接；表格外包一层横向滚动容器，代码块横向滚动走 CSS。
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function Markdown({ content }: { content: string }) {
  return (
    <div className="doc-prose mt-8">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="doc-table-wrap">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

export default Markdown
