import { CircleDollarSign, Coins, Hash, Loader2, Play } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchCostSummary, fetchRunCosts } from '../lib/api';

interface CostEntry {
  agent_name: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost: number;
  stage_id: string;
  timestamp: string;
}

interface CostSummary {
  total_cost: number;
  total_tokens: number;
  run_count: number;
  source?: string;
  token_basis?: string;
  pricing_basis?: string;
  is_estimate?: boolean;
}

export function Costs() {
  const [period, setPeriod] = useState('daily');
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState('');

  const [runId, setRunId] = useState('');
  const [runCosts, setRunCosts] = useState<CostEntry[] | null>(null);
  const [costLoading, setCostLoading] = useState(false);
  const [costError, setCostError] = useState('');

  function loadSummary(p: string) {
    setSummaryLoading(true);
    setSummaryError('');
    fetchCostSummary(p)
      .then((data) => setSummary(data))
      .catch((err: Error) => setSummaryError(err.message))
      .finally(() => setSummaryLoading(false));
  }

  useEffect(() => { loadSummary(period); }, [period]);

  function loadRunCosts() {
    if (!runId.trim()) return;
    setCostLoading(true);
    setCostError('');
    fetchRunCosts(runId.trim())
      .then((data) => setRunCosts(data.records))
      .catch((err: Error) => setCostError(err.message))
      .finally(() => setCostLoading(false));
  }

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>成本追踪</h1>
      </header>

      <section className="panel costDataNotice">
        <strong>真实执行记录，估算成本</strong>
        <span>
          数据来自后端 <code>cost_tracking</code> 表；Agent 完成后按 prompt/output 文本估算 Token，再按模型单价估算 USD。它可用于趋势和量级判断，但不是云厂商账单。
        </span>
      </section>

      <div className="costPeriodSelector">
        <button
          className={`button ${period === 'daily' ? 'primary' : ''}`}
          onClick={() => setPeriod('daily')}
        >
          日
        </button>
        <button
          className={`button ${period === 'weekly' ? 'primary' : ''}`}
          onClick={() => setPeriod('weekly')}
        >
          周
        </button>
        <button
          className={`button ${period === 'monthly' ? 'primary' : ''}`}
          onClick={() => setPeriod('monthly')}
        >
          月
        </button>
      </div>

      {summaryError && <div className="formError">{summaryError}</div>}

      <div className="statsGrid">
        <div className="statCard">
          <CircleDollarSign size={20} />
          <span>总成本</span>
          {summaryLoading ? (
            <strong className="skeletonText">—</strong>
          ) : (
            <strong>${summary?.total_cost.toFixed(4) ?? '0.0000'}</strong>
          )}
          <small>估算 USD</small>
        </div>
        <div className="statCard">
          <Hash size={20} />
          <span>总 Token</span>
          {summaryLoading ? (
            <strong className="skeletonText">—</strong>
          ) : (
            <strong>{(summary?.total_tokens ?? 0).toLocaleString()}</strong>
          )}
          <small>按文本估算</small>
        </div>
        <div className="statCard">
          <Play size={20} />
          <span>执行次数</span>
          {summaryLoading ? (
            <strong className="skeletonText">—</strong>
          ) : (
            <strong>{summary?.run_count ?? 0}</strong>
          )}
        </div>
        <div className="statCard">
          <Coins size={20} />
          <span>统计周期</span>
          <strong className="costPeriodLabel">
            {period === 'daily' ? '今日' : period === 'weekly' ? '本周' : '本月'}
          </strong>
        </div>
      </div>

      <section className="panel">
        <h2 style={{ marginBottom: 12 }}>按运行查询成本</h2>
        <div className="costRunQuery">
          <input
            type="text"
            placeholder="输入 Run ID"
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') loadRunCosts(); }}
          />
          <button
            className="button primary"
            onClick={loadRunCosts}
            disabled={costLoading || !runId.trim()}
          >
            {costLoading ? '查询中...' : '查询'}
          </button>
        </div>

        {costError && <div className="formError" style={{ marginTop: 12 }}>{costError}</div>}

        {runCosts && (
          <div className="tableWrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>模型</th>
                  <th>Token</th>
                  <th>成本 (USD)</th>
                </tr>
              </thead>
              <tbody>
                {runCosts.length === 0 ? (
                  <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>暂无成本数据</td></tr>
                ) : (
                  runCosts.map((entry, i) => (
                    <tr key={i}>
                      <td className="mono">{entry.agent_name}</td>
                      <td>{entry.model || '—'}</td>
                      <td>{(entry.prompt_tokens + entry.completion_tokens).toLocaleString()}</td>
                      <td className="mono">${entry.estimated_cost.toFixed(6)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
