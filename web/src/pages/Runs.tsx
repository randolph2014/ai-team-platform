import { AlertTriangle, ArrowUpDown, ChevronLeft, ChevronRight, Loader2, Plus, Search, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchRuns, rememberedWorkdir } from '../lib/api';
import { StatusBadge } from '../components/StatusBadge';
import type { RunListItem } from '../lib/types';

type SortField = 'started_at' | 'duration_seconds' | 'status' | 'pipeline';
type SortDir = 'asc' | 'desc';

const SORT_FIELDS: { field: SortField; label: string }[] = [
  { field: 'started_at', label: '开始时间' },
  { field: 'duration_seconds', label: '耗时' },
  { field: 'status', label: '状态' },
  { field: 'pipeline', label: 'Pipeline' },
];
const PAGE_SIZE = 20;

function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return '—';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}min`;
  return `${Math.round(seconds / 3600)}h`;
}

function openRun(run: RunListItem) {
  window.history.pushState({}, '', `/runs/${run.run_id}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function Runs({ onNewRun }: { onNewRun: () => void }) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [sortField, setSortField] = useState<SortField>('started_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const loadRuns = useCallback(() => {
    setLoading(true);
    setError('');
    fetchRuns(rememberedWorkdir(), { page, size: PAGE_SIZE, status: undefined })
      .then((res) => {
        setRuns(res.items);
        setTotal(res.total);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [page]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const clearFilters = () => {
    setSearch('');
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const filteredSorted = useMemo(() => {
    let result = runs;

    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (r) =>
          r.run_id.toLowerCase().includes(q) ||
          (r.requirement || '').toLowerCase().includes(q) ||
          (r.pipeline || '').toLowerCase().includes(q),
      );
    }

    result = [...result].sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1;
      if (sortField === 'started_at') {
        return ((a.started_at || '') > (b.started_at || '') ? 1 : -1) * dir;
      }
      if (sortField === 'duration_seconds') {
        return ((a.duration_seconds || 0) - (b.duration_seconds || 0)) * dir;
      }
      if (sortField === 'status') {
        return (a.status || '').localeCompare(b.status || '') * dir;
      }
      return ((a.pipeline || '').localeCompare(b.pipeline || '')) * dir;
    });

    return result;
  }, [runs, search, sortField, sortDir]);

  const hasFilters = Boolean(search.trim());

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
          <button className="button primary" onClick={loadRuns}>重试</button>
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

      {!loading && runs.length > 0 && (
        <div className="runsToolbar">
          <div className="runsSearch">
            <Search size={14} />
            <input
              placeholder="搜索 Run ID、需求或 Pipeline..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button className="runsSearchClear" onClick={() => setSearch('')} aria-label="清除搜索">
                <X size={14} />
              </button>
            )}
          </div>

          <div className="runsSortGroup">
            <span className="runsSortLabel"><ArrowUpDown size={12} /> 排序</span>
            <select
              value={`${sortField}:${sortDir}`}
              onChange={(e) => {
                const [field, dir] = e.target.value.split(':') as [SortField, SortDir];
                setSortField(field);
                setSortDir(dir);
              }}
            >
              {SORT_FIELDS.flatMap(({ field, label }) => [
                <option key={`${field}:desc`} value={`${field}:desc`}>{label} ↓</option>,
                <option key={`${field}:asc`} value={`${field}:asc`}>{label} ↑</option>,
              ])}
            </select>
          </div>

          {hasFilters && (
            <div className="runsFilterHint">
              匹配 {filteredSorted.length}/{total} 条
              <button className="linkButton" onClick={clearFilters} style={{ fontSize: 12, padding: 0 }}>清除搜索</button>
            </div>
          )}
        </div>
      )}

      <section className="panel">
        {loading ? (
          <div className="tableSkeleton">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="tableSkeletonRow">
                <div className="skeletonLine w-80" />
                <div className="skeletonLine w-80" />
                <div className="skeletonLine w-140" />
                <div className="skeletonLine w-120" />
                <div className="skeletonLine w-120" />
                <div className="skeletonLine w-80" />
                <div className="skeletonLine w-140" />
              </div>
            ))}
          </div>
        ) : runs.length === 0 ? (
          <div className="emptyState">
            <Loader2 size={32} style={{ color: 'var(--text-muted)', marginBottom: 8 }} />
            <p>暂无执行记录</p>
            <small>点击「新建运行」启动第一个 AI 协作任务</small>
          </div>
        ) : filteredSorted.length === 0 ? (
          <div className="emptyState">
            <Search size={32} style={{ color: 'var(--text-muted)', marginBottom: 8 }} />
            <p>无匹配结果</p>
            <small>尝试调整搜索关键词或过滤条件</small>
          </div>
        ) : (
          <>
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>状态</th>
                  <th>需求</th>
                  <th>Pipeline</th>
                  <th>耗时</th>
                  <th className="sortableHeader" onClick={() => { setSortField('started_at'); setSortDir(sortField === 'started_at' && sortDir === 'desc' ? 'asc' : 'desc'); }}>
                    开始时间 {sortField === 'started_at' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredSorted.map((run) => (
                  <tr key={run.run_id} onClick={() => openRun(run)}>
                    <td className="mono">#{run.run_id}</td>
                    <td><StatusBadge status={run.status} /></td>
                    <td className="ellipsis">{run.requirement || '—'}</td>
                    <td>{run.pipeline || '默认'}</td>
                    <td>{formatDuration(run.duration_seconds)}</td>
                    <td>{run.started_at ? new Date(run.started_at).toLocaleString('zh-CN') : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft size={14} /> 上一页
              </button>
              <span className="paginationInfo">{page} / {totalPages}</span>
              <button
                className="button"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                下一页 <ChevronRight size={14} />
              </button>
            </div>
          )}
          </>
        )}
      </section>
    </div>
  );
}
