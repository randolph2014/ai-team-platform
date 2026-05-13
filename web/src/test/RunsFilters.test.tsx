import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Runs } from '../pages/Runs';
import { fetchRuns, rememberedWorkdir } from '../lib/api';

vi.mock('../lib/api', () => ({
  fetchRuns: vi.fn(() => Promise.resolve({
    items: [
      {
        run_id: 'run-1',
        status: 'completed',
        requirement: '生成清单',
        pipeline: '研发流水线',
        started_at: '2026-01-01T00:00:00',
      },
    ],
    total: 1,
    page: 1,
    size: 20,
  })),
  rememberedWorkdir: vi.fn(() => '/repo'),
}));

const fetchRunsMock = vi.mocked(fetchRuns);
const rememberedWorkdirMock = vi.mocked(rememberedWorkdir);

describe('Runs filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps search and sorting but removes unfinished status shortcut filters', async () => {
    render(<Runs onNewRun={vi.fn()} />);

    await waitFor(() => {
      expect(fetchRunsMock).toHaveBeenCalledWith('/repo', { page: 1, size: 20, status: undefined });
    });
    expect(rememberedWorkdirMock).toHaveBeenCalled();
    expect(screen.getByPlaceholderText('搜索 Run ID、需求或 Pipeline...')).toBeInTheDocument();
    expect(screen.getByText('排序')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'queued' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'completed' })).not.toBeInTheDocument();
  });
});
