import { Download, Maximize2, Minimize2, X, FileText, FileCode, FileJson, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { apiFetch, fetchRunArtifactText, projectQuery, rememberedWorkdir } from '../lib/api';
import { ReadableArtifact, isCodeFile, isJsonFile, isLogFile, isMarkdownFile } from './ReadableArtifact';

interface ArtifactViewerProps {
  runId: string;
  artifactName: string;
  projectId?: string;
  onClose: () => void;
}

function getFileIcon(filename: string) {
  if (isMarkdownFile(filename)) return <FileText size={16} />;
  if (isJsonFile(filename)) return <FileJson size={16} />;
  if (isCodeFile(filename) || isLogFile(filename)) return <FileCode size={16} />;
  return <FileText size={16} />;
}

export function ArtifactViewer({ runId, artifactName, projectId, onClose }: ArtifactViewerProps) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    setContent(null);

    const wd = projectId ? '' : rememberedWorkdir(runId);
    fetchRunArtifactText(runId, artifactName, { projectId, workdir: wd })
      .then((text) => {
        if (!disposed) setContent(text);
      })
      .catch((e: Error) => {
        if (!disposed) setError(e.message);
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });

    return () => { disposed = true; };
  }, [runId, artifactName, projectId]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const handleDownload = () => {
    const wd = rememberedWorkdir(runId);
    apiFetch(`/runs/${runId}/artifacts/${encodeURIComponent(artifactName)}${projectQuery({ projectId, workdir: projectId ? '' : wd })}`)
      .then((res) => res.blob())
      .then((blob) => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = artifactName;
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch(() => {});
  };

  const renderContent = () => {
    if (loading) {
      return (
        <div className="viewerLoading">
          <Loader2 size={24} className="spin" />
          <span>加载中...</span>
        </div>
      );
    }

    if (error) {
      return (
        <div className="viewerError">
          <p>加载失败：{error}</p>
        </div>
      );
    }

    if (!content) {
      return (
        <div className="viewerEmpty">
          <p>文件内容为空</p>
        </div>
      );
    }

    return <ReadableArtifact filename={artifactName} content={content} />;
  };

  return (
    <div className={`viewerOverlay ${fullscreen ? 'viewerFullscreen' : ''}`} onClick={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div className="viewerModal">
        <header className="viewerHeader">
          <div className="viewerTitle">
            {getFileIcon(artifactName)}
            <span className="viewerFileName">{artifactName}</span>
          </div>
          <div className="viewerActions">
            <button className="iconButton" title="下载" onClick={handleDownload}>
              <Download size={15} />
            </button>
            <button className="iconButton" title={fullscreen ? '退出全屏' : '全屏'} onClick={() => setFullscreen(!fullscreen)}>
              {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            <button className="iconButton" title="关闭 (ESC)" onClick={onClose}>
              <X size={15} />
            </button>
          </div>
        </header>
        <div className="viewerBody">
          {renderContent()}
        </div>
      </div>
    </div>
  );
}
