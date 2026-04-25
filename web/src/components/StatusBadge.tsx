import { CheckCircle2, Clock3, Loader2, XCircle } from 'lucide-react';
import type { RunStatus } from '../lib/types';

const labels: Record<string, string> = {
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  pending: '等待中',
  waiting: '待验收',
  skipped: '已跳过',
};

export function StatusBadge({ status }: { status: RunStatus | string }) {
  const Icon = status === 'completed' ? CheckCircle2 : status === 'failed' ? XCircle : status === 'running' ? Loader2 : Clock3;
  return (
    <span className={`badge badge-${status}`}>
      <Icon size={13} className={status === 'running' ? 'spin' : ''} />
      {labels[status] ?? status}
    </span>
  );
}
