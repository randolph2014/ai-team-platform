import { Activity, AlertTriangle, BarChart3, Bot, Clock, Loader2, PieChart, Plus, TrendingUp, Zap } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, Cell, PieChart as RePieChart, Pie, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchRuns, rememberedWorkdir } from '../lib/api';
import type { RunListItem } from '../lib/types';
import { StatusBadge } from '../components/StatusBadge';

const CHART_COLORS = {
  completed: '#22c55e',
  failed: '#ef4444',
  running: '#3b82f6',
  queued: '#eab308',
  paused: '#a855f7',
  resuming: '#06b6d4',
  blocked: '#f97316',
  cancelled: '#9898b0',
};

function openRun(run: RunListItem) {
  window.history.pushState({}, '', `/runs/${run.run_id}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return '—';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}min`;
  return `${Math.round(seconds / 3600)}h`;
}

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  detail: string;
  accent?: 'success' | 'blue' | 'purple';
}

function StatCard({ icon, label, value, detail, accent }: StatCardProps) {
  return (
    <div className={`statCard ${accent || ''}`}>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="statCard skeleton">
      <div className="skeletonLine w-180" />
      <div className="skeletonLine w-120" />
      <div className="skeletonLine w-140" />
      <div className="skeletonLine w-80" />
    </div>
  );
}

export function Dashboard({ onNewRun }: { onNewRun: () => void }) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    fetchRuns(rememberedWorkdir())
      .then((res) => setRuns(res.items))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => {
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const todayRuns = runs.filter((r) => r.started_at && new Date(r.started_at) >= todayStart);
    const completedRuns = runs.filter((r) => r.status === 'completed' || r.status === 'failed');
    const successCount = runs.filter((r) => r.status === 'completed').length;
    const successRate = completedRuns.length > 0 ? Math.round((successCount / completedRuns.length) * 100) : 0;
    const avgDuration = completedRuns.length > 0
      ? completedRuns.reduce((sum, r) => sum + (r.duration_seconds || 0), 0) / completedRuns.length
      : 0;

    const statusDistribution = (['completed', 'failed', 'running', 'queued', 'paused', 'resuming', 'blocked', 'cancelled'] as const)
      .map((s) => ({ name: s, value: runs.filter((r) => r.status === s).length }))
      .filter((d) => d.value > 0);

    const dailyRuns = new Map<string, number>();
    runs.forEach((r) => {
      if (r.started_at) {
        const d = new Date(r.started_at).toISOString().slice(0, 10);
        dailyRuns.set(d, (dailyRuns.get(d) || 0) + 1);
      }
    });
    const trendData = Array.from(dailyRuns.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-14)
      .map(([date, count]) => ({ date: date.slice(5), count }));

    return { todayRuns: todayRuns.length, completedRuns: completedRuns.length, successCount, successRate, avgDuration, statusDistribution, trendData };
  }, [runs]);

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
              .then((res) => setRuns(res.items))
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

      {loading ? (
        <div className="statsGrid">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : (
        <div className="statsGrid">
          <StatCard icon={<Activity size={16} />} label="今日运行" value={stats.todayRuns} detail={`共 ${runs.length} 条记录`} />
          <StatCard icon={<TrendingUp size={16} />} label="成功率" value={`${stats.successRate}%`} detail={`${stats.successCount}/${stats.completedRuns} 次`} accent="success" />
          <StatCard icon={<Clock size={16} />} label="平均耗时" value={formatDuration(stats.avgDuration)} detail={`${stats.completedRuns} 次完成`} />
          <StatCard icon={<Bot size={16} />} label="运行记录" value={runs.length} detail="历史总计" accent="blue" />
        </div>
      )}

      {!loading && runs.length > 0 && (
        <div className="dashboardCharts">
          <section className="panel">
            <div className="panelHeader">
              <h2><BarChart3 size={16} /> 运行趋势（近两周）</h2>
            </div>
            {stats.trendData.length > 0 ? (
              <div className="chartWrapper">
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={stats.trendData}>
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} />
                    <Tooltip
                      contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12 }}
                      labelStyle={{ color: 'var(--text-primary)' }}
                    />
                    <Bar dataKey="count" fill="var(--accent)" radius={[4, 4, 0, 0]} name="运行次数" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="emptyState" style={{ padding: 24 }}>暂无趋势数据</div>
            )}
          </section>

          <section className="panel">
            <div className="panelHeader">
              <h2><PieChart size={16} /> 状态分布</h2>
            </div>
            {stats.statusDistribution.length > 0 ? (
              <div className="chartRow">
                <div className="chartWrapper" style={{ flex: '0 0 180px' }}>
                  <ResponsiveContainer width="100%" height={180}>
                    <RePieChart>
                      <Pie
                        data={stats.statusDistribution}
                        cx="50%"
                        cy="50%"
                        innerRadius={40}
                        outerRadius={75}
                        dataKey="value"
                        nameKey="name"
                        stroke="none"
                      >
                        {stats.statusDistribution.map((entry) => (
                          <Cell key={entry.name} fill={CHART_COLORS[entry.name as keyof typeof CHART_COLORS] || 'var(--text-muted)'} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12 }}
                      />
                    </RePieChart>
                  </ResponsiveContainer>
                </div>
                <div className="chartLegend">
                  {stats.statusDistribution.map((entry) => (
                    <div key={entry.name} className="chartLegendItem">
                      <span className="chartLegendDot" style={{ background: CHART_COLORS[entry.name as keyof typeof CHART_COLORS] || 'var(--text-muted)' }} />
                      <span className="chartLegendLabel">{entry.name}</span>
                      <span className="chartLegendValue">{entry.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="emptyState" style={{ padding: 24 }}>暂无状态数据</div>
            )}
          </section>
        </div>
      )}

      <section className="panel">
        <div className="panelHeader">
          <h2>最近运行</h2>
          {runs.length > 20 && (
            <a href="/runs" className="viewAllLink" onClick={(e) => {
              e.preventDefault();
              window.history.pushState({}, '', '/runs');
              window.dispatchEvent(new PopStateEvent('popstate'));
            }}>
              查看全部 ({runs.length})
            </a>
          )}
        </div>
        {loading ? (
          <div className="tableSkeleton">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="tableSkeletonRow">
                <div className="skeletonLine w-120" />
                <div className="skeletonLine w-80" />
                <div className="skeletonLine w-80" />
                <div className="skeletonLine w-200" />
                <div className="skeletonLine w-140" />
              </div>
            ))}
          </div>
        ) : runs.length === 0 ? (
          <div className="emptyState">
            <Zap size={32} style={{ color: 'var(--text-muted)', marginBottom: 8 }} />
            <p>暂无运行记录</p>
            <small>点击「新建运行」启动第一个 AI 协作任务</small>
          </div>
        ) : (
          <div className="tableWrap">
            <table>
              <thead><tr><th>Pipeline</th><th>Run</th><th>状态</th><th>需求</th><th>耗时</th><th>开始时间</th></tr></thead>
              <tbody>
                {runs.slice(0, 20).map((run) => (
                  <tr key={run.run_id} onClick={() => openRun(run)}>
                    <td>{run.pipeline || '默认'}</td>
                    <td className="mono">#{run.run_id}</td>
                    <td><StatusBadge status={run.status} /></td>
                    <td className="ellipsis">{run.requirement || '—'}</td>
                    <td>{formatDuration(run.duration_seconds)}</td>
                    <td>{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'}</td>
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
