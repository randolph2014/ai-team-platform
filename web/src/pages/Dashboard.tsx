import { Activity, AlertTriangle, Bot, Clock, Loader2, Plus, TrendingUp } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchRuns, rememberedWorkdir } from '../lib/api';
import type { RunListItem } from '../lib/types';
import { StatusBadge } from '../components/StatusBadge';

function openRun(run: RunListItem) {
  window.history.pushState({}, '', `/runs/${run.run_id}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function Dashboard({ onNewRun }: { onNewRun: () => void }) {
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

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayRuns = runs.filter((r) => r.started_at && new Date(r.started_at) >= today);
  const completedRuns = runs.filter((r) => r.status === 'completed' || r.status === 'failed');
  const successCount = runs.filter((r) => r.status === 'completed').length;
  const successRate = completedRuns.length > 0 ? Math.round((successCount / completedRuns.length) * 100) : 0;
  const avgDuration = completedRuns.reduce((sum, r) => sum + (r.duration_seconds || 0), 0) / Math.max(completedRuns.length, 1);
  const avgMin = avgDuration > 0 ? `${Math.round(avgDuration / 60)}min` : '—';

  if (error) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>仪表盘</h1></header>
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
        <h1>仪表盘</h1>
        <button className="button primary" onClick={onNewRun}>
          <Plus size={15} /> 新建运行
        </button>
      </header>
      <div className="statsGrid">
        <div className="statCard"><Activity size={16} /><span>今日运行</span><strong>{todayRuns.length}</strong><small>共 {runs.length} 条记录</small></div>
        <div className="statCard success"><TrendingUp size={16} /><span>成功率</span><strong>{successRate}%</strong><small>{successCount}/{completedRuns.length} 次</small></div>
        <div className="statCard"><Clock size={16} /><span>平均耗时</span><strong>{avgMin}</strong><small>{completedRuns.length} 次完成</small></div>
        <div className="statCard blue"><Bot size={16} /><span>运行记录</span><strong>{runs.length}</strong><small>历史总计</small></div>
      </div>
      <section className="panel">
        <div className="panelHeader">
          <h2>最近运行</h2>
        </div>
        {loading ? (
          <div className="emptyState"><Loader2 size={24} className="spinner" /> 加载中…</div>
        ) : runs.length === 0 ? (
          <div className="emptyState">暂无运行记录，点击「新建运行」开始</div>
        ) : (
          <div className="tableWrap">
            <table>
              <thead><tr><th>Pipeline</th><th>Run</th><th>状态</th><th>需求</th><th>开始时间</th></tr></thead>
              <tbody>
                {runs.slice(0, 20).map((run) => (
                  <tr key={run.run_id} onClick={() => openRun(run)}>
                    <td>{run.pipeline || '默认'}</td>
                    <td className="mono">#{run.run_id}</td>
                    <td><StatusBadge status={run.status} /></td>
                    <td className="ellipsis">{run.requirement || '—'}</td>
                    <td>{run.started_at ? new Date(run.started_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '-'}</td>
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
