import { Download, FolderGit2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { PipelineTimeline } from '../components/PipelineTimeline';
import { StatusBadge } from '../components/StatusBadge';
import { fetchRun, rememberedWorkdir, rememberRunWorkdir, runQuery, runWebSocketUrl } from '../lib/api';
import { mockRunDetail } from '../lib/mockData';
import type { RunEvent, RunReport } from '../lib/types';

export function RunDetail({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunReport>(mockRunDetail);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [workdir, setWorkdir] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const queryWorkdir = new URLSearchParams(window.location.search).get('workdir') || '';
    const resolvedWorkdir = queryWorkdir || rememberedWorkdir(runId);
    setWorkdir(resolvedWorkdir);
    if (runId === '42' && !resolvedWorkdir) {
      setRun(mockRunDetail);
      return;
    }
    let ignore = false;
    setLoadError(null);
    fetchRun(runId, resolvedWorkdir)
      .then((payload) => {
        if (ignore) return;
        setRun(payload);
        rememberRunWorkdir(runId, payload.project_root);
      })
      .catch((error: Error) => {
        if (!ignore) setLoadError(error.message);
      });
    return () => { ignore = true; };
  }, [runId]);

  useEffect(() => {
    if (runId === '42' && !workdir) return;
    const socket = new WebSocket(runWebSocketUrl(runId));
    let disposed = false;
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent;
      if (event.type === 'agent:output' && typeof event.payload.text === 'string') {
        setLiveLines((lines) => [...lines.slice(-120), event.payload.text as string]);
      }
      if (event.type === 'run:completed') {
        fetchRun(runId, workdir).then(setRun).catch(() => undefined);
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
  }, [runId, workdir]);

  return (
    <div className="page">
      <section className="runHeader">
        <div>
          <div className="eyebrow">Pipeline: LifeRhythm 标准交付</div>
          <h1>Run #{run.run_id}</h1>
          <div className="runMeta">
            <StatusBadge status={run.status} />
            <span><FolderGit2 size={14} /> {run.project_root}</span>
            <span>{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN') : '-'}</span>
          </div>
        </div>
        <button className="button"><Download size={15} /> 产物</button>
      </section>
      <section className="panel requirementPanel">
        <h2>需求描述</h2>
        <p>{run.requirement}</p>
        {loadError ? <p className="inlineError">无法加载真实运行记录：{loadError}</p> : null}
      </section>
      <div className="detailGrid">
        <PipelineTimeline run={run} liveLines={liveLines} />
        <aside className="artifactPanel">
          <h2>产物文件</h2>
          {run.artifacts.map((artifact) => (
            <a key={artifact} href={`/api/runs/${run.run_id}/artifacts/${artifact}${runQuery(workdir || run.project_root)}`} className="artifactItem">
              {artifact}
            </a>
          ))}
        </aside>
      </div>
    </div>
  );
}
