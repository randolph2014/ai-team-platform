import { ChevronDown, ChevronRight, Loader2, Maximize2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { apiFetch, rememberedWorkdir, runQuery } from '../lib/api';
import { ArtifactViewer } from './ArtifactViewer';
import { MarkdownViewer } from './MarkdownViewer';

interface ArtifactContentProps {
  runId: string;
  artifactName: string;
  label?: string;
}

function isMarkdownFile(filename: string): boolean {
  return /\.(md|markdown|mdx)$/i.test(filename);
}

export function ArtifactContent({ runId, artifactName, label }: ArtifactContentProps) {
  const [expanded, setExpanded] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showViewer, setShowViewer] = useState(false);

  useEffect(() => {
    if (!expanded || content !== null) return;
    setLoading(true);
    setError(null);
    const wd = rememberedWorkdir(runId);
    apiFetch(`/runs/${runId}/artifacts/${encodeURIComponent(artifactName)}${runQuery(wd)}`)
      .then((res) => {
        if (!res.ok) throw new Error(`加载失败: ${res.status}`);
        return res.text();
      })
      .then((text) => {
        setContent(text);
      })
      .catch((e: Error) => {
        setError(e.message);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [expanded, content, runId, artifactName]);

  const renderInlineContent = () => {
    if (!content) return null;

    if (isMarkdownFile(artifactName)) {
      return (
        <div className="artifactContentMarkdown">
          <MarkdownViewer content={content} />
        </div>
      );
    }

    return <pre className="artifactContentPre">{content}</pre>;
  };

  return (
    <div className="artifactContentWrapper">
      <div className="artifactContentHeader">
        <button
          className="artifactContentToggle"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>{label || artifactName}</span>
        </button>
        <button
          className="artifactContentExpand"
          title="全屏查看"
          onClick={() => setShowViewer(true)}
        >
          <Maximize2 size={12} />
        </button>
      </div>
      {expanded && (
        <div className="artifactContentBody">
          {loading && (
            <div className="artifactContentLoading">
              <Loader2 size={14} className="spin" /> 加载中...
            </div>
          )}
          {error && <div className="artifactContentError">{error}</div>}
          {content && !loading && renderInlineContent()}
        </div>
      )}
      {showViewer && (
        <ArtifactViewer
          runId={runId}
          artifactName={artifactName}
          onClose={() => setShowViewer(false)}
        />
      )}
    </div>
  );
}
