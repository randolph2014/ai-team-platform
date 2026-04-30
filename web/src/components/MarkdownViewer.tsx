import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import rehypeRaw from 'rehype-raw';

interface MarkdownViewerProps {
  content: string;
  className?: string;
}

/**
 * Markdown 渲染组件
 * 支持 GFM（表格、任务列表、删除线等）、代码高亮、HTML 原生标签
 */
export function MarkdownViewer({ content, className }: MarkdownViewerProps) {
  return (
    <div className={`markdown-body ${className ?? ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight, rehypeRaw]}
        components={{
          // 自定义链接：外部链接在新标签页打开
          a({ href, children, ...props }) {
            const isExternal = href && (href.startsWith('http://') || href.startsWith('https://'));
            return (
              <a
                href={href}
                target={isExternal ? '_blank' : undefined}
                rel={isExternal ? 'noopener noreferrer' : undefined}
                {...props}
              >
                {children}
              </a>
            );
          },
          // 自定义表格 wrapper，支持横向滚动
          table({ children, ...props }) {
            return (
              <div className="markdown-table-wrap">
                <table {...props}>{children}</table>
              </div>
            );
          },
          // 自定义代码块添加复制按钮
          pre({ children, ...props }) {
            return (
              <div className="markdown-code-block">
                <pre {...props}>{children}</pre>
              </div>
            );
          },
        }}
      />
    </div>
  );
}
