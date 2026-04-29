import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { rememberedWorkdir, runQuery } from '../lib/api';

interface ArtifactContentProps {
  runId: string;
  artifactName: string;
  label?: string;
}

export function ArtifactContent({ runId, artifactName, label }: ArtifactContentProps) {
  const [expanded, setExpanded] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!expanded || content !== null) return;
    setLoading(true);
    setError(null);
    const wd = rememberedWorkdir(runId);
    const token = localStorage.getItem('ai-team.token') || '';
    fetch(`/api/runs/${runId}/artifacts/${artifactName}${runQuery(wd)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(async (res) => {
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

  return (
    <div className="artifactContentWrapper">
      <button
        className="artifactContentToggle"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>{label || artifactName}</span>
      </button>
      {expanded && (
        <div className="artifactContentBody">
          {loading && (
            <div className="artifactContentLoading">
              <Loader2 size={14} className="spin" /> 加载中...
            </div>
          )}
          {error && <div className="artifactContentError">{error}</div>}
          {content && !loading && (
            <pre className="artifactContentPre">{content}</pre>
          )}
        </div>
      )}
    </div>
  );
}
