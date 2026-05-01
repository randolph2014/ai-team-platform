import { Eye, FileDiff, FileText, FolderGit2, GitBranchPlus, Wifi, WifiOff, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ArtifactViewer } from '../components/ArtifactViewer';
import { PipelineTimeline } from '../components/PipelineTimeline';
import { StatusBadge } from '../components/StatusBadge';
import { fetchRun, fetchRunDiff, rememberedWorkdir, rememberRunWorkdir, runQuery, runWebSocketUrl } from '../lib/api';
import type { RunEvent, RunReport } from '../lib/types';

function artifactColor(name: string): string {
  if (/\.(md|markdown)$/i.test(name)) return 'var(--blue)';
  if (/\.json$/i.test(name)) return 'var(--yellow)';
  if (/\.(py|js|ts|tsx|jsx)$/i.test(name)) return 'var(--green)';
  if (/\.(log|out|err)$/i.test(name)) return 'var(--text-muted)';
  if (/\.(yaml|yml)$/i.test(name)) return 'var(--purple)';
  return 'var(--accent)';
}

function fileIcon(file: string): string {
  if (/\.(py|js|ts|tsx|jsx|go|rs|java|kt|swift)$/i.test(file)) return 'var(--green)';
  if (/\.(yaml|yml|json|toml)$/i.test(file)) return 'var(--yellow)';
  if (/\.(md|markdown|rst|txt)$/i.test(file)) return 'var(--blue)';
  if (/\.(css|scss|less)$/i.test(file)) return 'var(--purple)';
  return 'var(--text-secondary)';
}

export function RunDetail({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunReport | null>(null);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [workdir, setWorkdir] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
  const [viewingArtifact, setViewingArtifact] = useState<string | null>(null);
  const [changedFiles, setChangedFiles] = useState<string[]>([]);
  const [diffStat, setDiffStat] = useState('');
  const [viewingDiff, setViewingDiff] = useState(false);
  const [diffContent, setDiffContent] = useState('');
  const [diffLoading, setDiffLoading] = useState(false);
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const queryWorkdir = new URLSearchParams(window.location.search).get('workdir') || '';
    const resolvedWorkdir = queryWorkdir || rememberedWorkdir(runId);
    setWorkdir(resolvedWorkdir);
    let ignore = false;
    setLoadError(null);
    setLoading(true);
    setRun(null);
    fetchRun(runId, resolvedWorkdir)
      .then((payload) => {
        if (ignore) return;
        setRun(payload);
        rememberRunWorkdir(runId, payload.project_root);
        if (payload.changed_files?.length) setChangedFiles(payload.changed_files);
        if (payload.diff_stat) setDiffStat(payload.diff_stat);
      })
      .catch((error: Error) => {
        if (!ignore) setLoadError(error.message);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => { ignore = true; };
  }, [runId]);

  useEffect(() => {
    if (!run || !workdir) return;
    const socket = new WebSocket(runWebSocketUrl(runId));
    let disposed = false;
    socket.onopen = () => {
      if (!disposed) setWsConnected(true);
    };
    socket.onclose = () => {
      if (!disposed) setWsConnected(false);
    };
    socket.onerror = () => {
      if (!disposed) setWsConnected(false);
    };
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent;
      if (event.type === 'agent:output' && typeof event.payload.text === 'string') {
        setLiveLines((lines) => [...lines.slice(-120), event.payload.text as string]);
      }
      if (event.type === 'run:completed') {
        fetchRun(runId, workdir).then((updated) => {
          if (!disposed) {
            setRun(updated);
            if (updated.changed_files?.length) setChangedFiles(updated.changed_files);
            if (updated.diff_stat) setDiffStat(updated.diff_stat);
          }
        }).catch(() => undefined);
      }
      if (event.type === 'files:changed') {
        const files = (event.payload.changed_files as string[]) || [];
        if (files.length) setChangedFiles(files);
        if (typeof event.payload.diff_stat === 'string') setDiffStat(event.payload.diff_stat);
      }
    };
    return () => {
      disposed = true;
      if (socket.readyState === WebSocket.OPEN) {
        socket.close();
      } else if (socket.readyState === WebSocket.CONNECTING) {
        socket.onopen = () => {
          if (disposed) socket.close();
        };
      }
    };
  }, [run ? run.run_id : '', workdir]);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [liveLines]);

  async function handleViewDiff() {
    setDiffLoading(true);
    setViewingDiff(true);
    try {
      const result = await fetchRunDiff(runId, workdir);
      setDiffContent(result.diff);
    } catch {
      setDiffContent(diffStat || '暂无 diff 数据');
    } finally {
      setDiffLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <section className="runHeader skeleton">
          <div>
            <div className="eyebrow skeletonLine w-120" />
            <div className="skeletonLine w-180" style={{ height: 24 }} />
            <div className="runMeta" style={{ marginTop: 10 }}>
              <div className="skeletonLine w-80" />
              <div className="skeletonLine w-200" />
              <div className="skeletonLine w-140" />
            </div>
          </div>
        </section>
        <section className="panel requirementPanel">
          <div className="skeletonLine w-80" style={{ marginBottom: 8 }} />
          <div className="skeletonLine w-full" />
        </section>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="page">
        <div className="errorPanel">
          <h2>加载失败</h2>
          <p>{loadError}</p>
          <button className="button primary" onClick={() => {
            setLoadError(null);
            setLoading(true);
            fetchRun(runId, workdir)
              .then(setRun)
              .catch((error: Error) => setLoadError(error.message))
              .finally(() => setLoading(false));
          }}>重试</button>
        </div>
      </div>
    );
  }

  if (!run) return null;

  return (
    <div className="page">
      <section className="runHeader">
        <div>
          <div className="eyebrow">Pipeline: {run.config_source || 'Standard'}</div>
          <h1>Run #{run.run_id}</h1>
          <div className="runMeta">
            <StatusBadge status={run.status} />
            <span><FolderGit2 size={14} /> {run.project_root}</span>
            <span>{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN') : '-'}</span>
            <span className={wsConnected ? 'wsIndicator wsConnected' : 'wsIndicator wsDisconnected'}>
              {wsConnected ? <Wifi size={13} /> : <WifiOff size={13} />}
              {wsConnected ? '实时连接' : '已断开'}
            </span>
          </div>
        </div>
      </section>

      <section className="panel requirementPanel">
        <h2>需求描述</h2>
        <p>{run.requirement}</p>
        {loadError ? <p className="inlineError">无法加载真实运行记录：{loadError}</p> : null}
      </section>

      {changedFiles.length > 0 && (
        <section className="panel fileChangesPanel">
          <div className="panelHeader">
            <h2><GitBranchPlus size={16} /> 文件变更<span className="artifactCount">{changedFiles.length}</span></h2>
            <button className="button" onClick={handleViewDiff}>
              <FileDiff size={14} /> 查看 Diff
            </button>
          </div>
          <div className="fileChangesList">
            {changedFiles.map((file) => (
              <div key={file} className="fileChangeItem">
                <span className="fileChangeDot" style={{ background: fileIcon(file) }} />
                <span className="fileChangeName mono">{file}</span>
              </div>
            ))}
          </div>
          {diffStat && (
            <div className="fileChangesStat">
              <FileText size={12} />
              <span>{diffStat.split('\n').slice(0, 2).join(' | ')}</span>
            </div>
          )}
        </section>
      )}

      <div className="detailGrid">
        <PipelineTimeline
          run={run}
          liveLines={liveLines}
          onStageAction={() => {
            fetchRun(runId, workdir || run.project_root)
              .then(setRun)
              .catch(() => undefined);
          }}
        />
        <aside className="artifactPanel">
          <h2>产物文件 <span className="artifactCount">{run.artifacts.length}</span></h2>
          {run.artifacts.length === 0 ? (
            <div className="artifactEmpty">暂无产物文件</div>
          ) : (
            <div className="artifactList">
              {run.artifacts.map((artifact) => (
                <button
                  key={artifact}
                  className="artifactItem"
                  onClick={() => setViewingArtifact(artifact)}
                  title={`点击查看 ${artifact}`}
                >
                  <span className="artifactDot" style={{ background: artifactColor(artifact) }} />
                  <span className="artifactName">{artifact}</span>
                  <Eye size={12} className="artifactViewIcon" />
                </button>
              ))}
            </div>
          )}
        </aside>
      </div>

      {viewingArtifact && (
        <ArtifactViewer
          runId={run.run_id}
          artifactName={viewingArtifact}
          onClose={() => setViewingArtifact(null)}
        />
      )}

      {viewingDiff && (
        <div className="modalOverlay" onClick={() => setViewingDiff(false)}>
          <div className="modal modalWide" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <h2><FileDiff size={18} /> Git Diff</h2>
              <button className="iconButton" onClick={() => setViewingDiff(false)} aria-label="关闭">
                <X size={16} />
              </button>
            </div>
            <div className="diffContent">
              {diffLoading ? (
                <div className="emptyState" style={{ padding: 32 }}>
                  <span className="spinner" style={{ display: 'inline-block', width: 24, height: 24, border: '2px solid var(--border)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                  <span style={{ marginTop: 12 }}>加载 diff...</span>
                </div>
              ) : (
                <pre className="diffPre">{diffContent || '暂无 diff 数据'}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
