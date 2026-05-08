import DOMPurify from 'dompurify';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import rehypeRaw from 'rehype-raw';

interface MarkdownViewerProps {
  content: string;
  className?: string;
}

export function MarkdownViewer({ content, className }: MarkdownViewerProps) {
  const safe = DOMPurify.sanitize(content, {
    ADD_TAGS: ['details', 'summary'],
    ADD_ATTR: ['target', 'rel'],
  });

  return (
    <div className={`markdown-body ${className ?? ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight, rehypeRaw]}
        components={{
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
          table({ children, ...props }) {
            return (
              <div className="markdown-table-wrap">
                <table {...props}>{children}</table>
              </div>
            );
          },
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
