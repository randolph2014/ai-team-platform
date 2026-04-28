import { AlertTriangle, Loader2, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchRuns, rememberedWorkdir } from '../lib/api';
import { StatusBadge } from '../components/StatusBadge';
import type { RunListItem } from '../lib/types';

export function Runs({ onNewRun }: { onNewRun: () => void }) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    fetchRuns(rememberedWorkdir())
      .then(setRuns)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) {
    return (
      <div className="page">
        <header className="pageHeader">
          <h1>执行记录</h1>
          <button className="button primary" onClick={onNewRun}><Plus size={15} /> 新建运行</button>
        </header>
        <div className="errorPanel">
          <h2><AlertTriangle size={20} /> 加载失败</h2>
          <p>{error}</p>
          <button className="button primary" onClick={() => {
            setError('');
            setLoading(true);
            fetchRuns(rememberedWorkdir())
              .then(setRuns)
              .catch((err: Error) => setError(err.message))
              .finally(() => setLoading(false));
          }}>重试</button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>执行记录</h1>
        <button className="button primary" onClick={onNewRun}><Plus size={15} /> 新建运行</button>
      </header>
      <section className="panel">
        {loading ? (
          <div className="emptyState"><Loader2 size={24} className="spinner" /> 加载中…</div>
        ) : runs.length === 0 ? (
          <div className="emptyState">暂无执行记录</div>
        ) : (
          <div className="tableWrap">
            <table>
              <thead><tr><th>Run</th><th>状态</th><th>需求</th><th>Pipeline</th><th>输出目录</th><th>开始时间</th></tr></thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id} onClick={() => {
                    window.history.pushState({}, '', `/runs/${run.run_id}`);
                    window.dispatchEvent(new PopStateEvent('popstate'));
                  }}>
                    <td className="mono">#{run.run_id}</td>
                    <td><StatusBadge status={run.status} /></td>
                    <td className="ellipsis">{run.requirement || '—'}</td>
                    <td>{run.pipeline || '默认'}</td>
                    <td className="mono">{run.output_dir}</td>
                    <td>{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN') : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
