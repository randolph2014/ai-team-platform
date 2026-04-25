import { Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchRuns, rememberedWorkdir } from '../lib/api';
import { mockRuns } from '../lib/mockData';
import { StatusBadge } from '../components/StatusBadge';
import type { RunListItem } from '../lib/types';

export function Runs({ onNewRun }: { onNewRun: () => void }) {
  const [runs, setRuns] = useState<RunListItem[]>(mockRuns);

  useEffect(() => {
    fetchRuns(rememberedWorkdir()).then((items) => {
      if (items.length > 0) setRuns(items);
    }).catch(() => undefined);
  }, []);

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>执行记录</h1>
        <button className="button primary" onClick={onNewRun}><Plus size={15} /> 新建运行</button>
      </header>
      <section className="panel">
        <div className="tableWrap">
          <table>
            <thead><tr><th>Run</th><th>状态</th><th>Pipeline</th><th>输出目录</th><th>开始时间</th></tr></thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} onClick={() => {
                  window.history.pushState({}, '', `/runs/${run.run_id}`);
                  window.dispatchEvent(new PopStateEvent('popstate'));
                }}>
                  <td className="mono">#{run.run_id}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{run.pipeline}</td>
                  <td className="mono">{run.output_dir}</td>
                  <td>{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN') : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
