import { MarkdownViewer } from './MarkdownViewer';

export function isMarkdownFile(filename: string): boolean {
  return /\.(md|markdown|mdx)$/i.test(filename);
}

export function isJsonFile(filename: string): boolean {
  return /\.json$/i.test(filename);
}

export function isCodeFile(filename: string): boolean {
  return /\.(py|js|ts|tsx|jsx|yaml|yml|sh|bash|toml|ini|cfg|conf|sql|html|css|xml|go|rs|java|rb|php|c|cpp|h|hpp)$/i.test(filename);
}

export function isLogFile(filename: string): boolean {
  return /\.(log|out|err)$/i.test(filename);
}

function isScalar(value: unknown): boolean {
  return value == null || ['string', 'number', 'boolean'].includes(typeof value);
}

function JsonValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="jsonEmpty">[]</span>;
    if (value.every(isScalar) && value.join(', ').length < 120) {
      return <span className="jsonInline">[{value.map((item) => String(item)).join(', ')}]</span>;
    }
    return (
      <div className="jsonArray">
        {value.map((item, index) => (
          <div className="jsonArrayItem" key={index}>
            <span className="jsonArrayIndex">{index + 1}</span>
            <JsonValue value={item} />
          </div>
        ))}
      </div>
    );
  }

  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="jsonEmpty">{'{}'}</span>;
    return (
      <div className="jsonObject">
        {entries.map(([key, item]) => (
          <div className="jsonField" key={key}>
            <div className="jsonKey">{key}</div>
            <div className="jsonValue"><JsonValue value={item} /></div>
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === 'string') {
    if (value.includes('\n') || value.length > 120) {
      return <pre className="jsonStringBlock">{value}</pre>;
    }
    return <span className="jsonString">{value}</span>;
  }

  if (value == null) return <span className="jsonNull">null</span>;
  return <span className="jsonPrimitive">{String(value)}</span>;
}

function StructuredJson({ content }: { content: string }) {
  try {
    const parsed = JSON.parse(content);
    return (
      <div className="artifactStructuredJson">
        <JsonValue value={parsed} />
      </div>
    );
  } catch {
    return (
      <pre className="viewerCodeBlock">
        <code className="language-json">{content}</code>
      </pre>
    );
  }
}

export function ReadableArtifact({ filename, content }: { filename: string; content: string }) {
  if (isMarkdownFile(filename)) {
    return <MarkdownViewer content={content} />;
  }

  if (isJsonFile(filename)) {
    return <StructuredJson content={content} />;
  }

  if (isCodeFile(filename) || isLogFile(filename)) {
    const lang = filename.split('.').pop() || '';
    return (
      <pre className="viewerCodeBlock">
        <code className={`language-${lang}`}>{content}</code>
      </pre>
    );
  }

  return <pre className="viewerPlainText">{content}</pre>;
}
