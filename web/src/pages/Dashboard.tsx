import { Activity, Bot, Clock, Plus, TrendingUp } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchRuns, rememberedWorkdir } from '../lib/api';
import { mockRuns } from '../lib/mockData';
import type { RunListItem } from '../lib/types';
import { StatusBadge } from '../components/StatusBadge';

function openRun(run: RunListItem) {
  window.history.pushState({}, '', `/runs/${run.run_id}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function Dashboard({ onNewRun }: { onNewRun: () => void }) {
  const [runs, setRuns] = useState<RunListItem[]>(mockRuns);

  useEffect(() => {
    fetchRuns(rememberedWorkdir()).then((items) => {
      if (items.length > 0) setRuns(items);
    }).catch(() => undefined);
  }, []);

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>仪表盘</h1>
        <button className="button primary" onClick={onNewRun}>
          <Plus size={15} /> 新建运行
        </button>
      </header>
      <div className="statsGrid">
        <div className="statCard"><Activity size={16} /><span>今日运行</span><strong>7</strong><small>+3 vs 昨日</small></div>
        <div className="statCard success"><TrendingUp size={16} /><span>成功率</span><strong>85.7%</strong><small>+12% vs 上周</small></div>
        <div className="statCard"><Clock size={16} /><span>平均耗时</span><strong>23min</strong><small>-5min vs 上周</small></div>
        <div className="statCard blue"><Bot size={16} /><span>活跃 Agent</span><strong>3</strong><small>tech-lead, qa, reviewer</small></div>
      </div>
      <section className="panel">
        <div className="panelHeader">
          <h2>最近运行</h2>
          <button className="linkButton" onClick={() => openRun(mockRuns[0])}>查看运行详情</button>
        </div>
        <div className="tableWrap">
          <table>
            <thead><tr><th>Pipeline</th><th>Run</th><th>状态</th><th>需求</th><th>开始时间</th></tr></thead>
            <tbody>
              {runs.slice(0, 5).map((run) => (
                <tr key={run.run_id} onClick={() => openRun(run)}>
                  <td>{run.pipeline}</td>
                  <td className="mono">#{run.run_id}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td className="ellipsis">实现 Checkin 伴侣视图的签到历史展示功能</td>
                  <td>{run.started_at ? new Date(run.started_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
