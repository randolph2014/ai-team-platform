import { Download, FolderGit2, Wifi, WifiOff } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { PipelineTimeline } from '../components/PipelineTimeline';
import { StatusBadge } from '../components/StatusBadge';
import { fetchRun, rememberedWorkdir, rememberRunWorkdir, runQuery, runWebSocketUrl } from '../lib/api';
import type { RunEvent, RunReport } from '../lib/types';

export function RunDetail({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunReport | null>(null);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [workdir, setWorkdir] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
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
          if (!disposed) setRun(updated);
        }).catch(() => undefined);
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
        <button className="button"><Download size={15} /> 产物</button>
      </section>
      <section className="panel requirementPanel">
        <h2>需求描述</h2>
        <p>{run.requirement}</p>
        {loadError ? <p className="inlineError">无法加载真实运行记录：{loadError}</p> : null}
      </section>
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
