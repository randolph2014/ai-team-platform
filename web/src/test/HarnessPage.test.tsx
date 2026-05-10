import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Harness } from '../pages/Harness';
import {
  ApiError,
  fetchHarness,
  fetchTaskBoard,
  saveHarness,
  validateHarness,
} from '../lib/api';

vi.mock('../lib/api', () => {
  class MockApiError extends Error {
    status: number;
    body: unknown;
    constructor(message: string, status: number, body: unknown) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.body = body;
    }
  }
  return {
    ApiError: MockApiError,
    apiFetch: vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve([
        { id: 'proj-1', name: 'Repo', root_path: '/repo', created_at: '2026-05-10T00:00:00' },
      ]),
    })),
    fetchHarness: vi.fn(),
    fetchTaskBoard: vi.fn(() => Promise.resolve({ project_id: 'proj-1', summary: { total: 0, by_state: {} }, tasks: [] })),
    validateHarness: vi.fn(() => Promise.resolve({ valid: true, errors: [] })),
    saveHarness: vi.fn(),
    runHarnessChecks: vi.fn(() => Promise.resolve({ status: 'pass' })),
    appendTaskBoardEvent: vi.fn(() => Promise.resolve({ project_id: 'proj-1', task: {} })),
  };
});

const fetchHarnessMock = vi.mocked(fetchHarness);
const fetchTaskBoardMock = vi.mocked(fetchTaskBoard);
const validateHarnessMock = vi.mocked(validateHarness);
const saveHarnessMock = vi.mocked(saveHarness);

function harnessBundle(overrides: Record<string, unknown> = {}) {
  return {
    project_id: 'proj-1',
    manifest_hash: 'sha256:manifest-1',
    files: [
      { path: '.ai/harness.yaml', hash: 'sha256:config', content: "schema_version: '1.0'\n" },
      {
        path: '.ai/harness/rules/security.md',
        hash: 'sha256:rule',
        content: '# Security\n\n<script>window.__bad = true</script><img src=x onerror="window.__bad = true">',
      },
    ],
    summary: { rules_count: 1, skills_count: 0, checks_count: 0, baselines_count: 0 },
    validation: { valid: true, errors: [] },
    ...overrides,
  };
}

describe('Harness page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem('ai-team.lastProjectId', 'proj-1');
    fetchHarnessMock.mockResolvedValue(harnessBundle());
    saveHarnessMock.mockResolvedValue(harnessBundle({ manifest_hash: 'sha256:manifest-2' }));
  });

  it('loads Harness through project_id APIs and renders the five tabs', async () => {
    render(<Harness />);

    await waitFor(() => expect(fetchHarnessMock).toHaveBeenCalledWith('proj-1'));
    expect(fetchTaskBoardMock).toHaveBeenCalledWith('proj-1');
    for (const tab of ['Rules', 'Skills', 'Checks', 'Baselines', 'Task Board']) {
      expect(screen.getByRole('button', { name: tab })).toBeInTheDocument();
    }
  });

  it('validates before saving and sends manifest_hash with Harness files only', async () => {
    render(<Harness />);

    const textarea = await screen.findByDisplayValue(/# Security/);
    fireEvent.change(textarea, { target: { value: '# Security\n\nUpdated' } });
    fireEvent.click(screen.getByRole('button', { name: /保存/ }));

    await waitFor(() => {
      expect(validateHarnessMock).toHaveBeenCalledWith('proj-1', expect.arrayContaining([
        expect.objectContaining({ path: '.ai/harness/rules/security.md', content: '# Security\n\nUpdated' }),
      ]));
      expect(saveHarnessMock).toHaveBeenCalledWith('proj-1', expect.any(Array), 'sha256:manifest-1');
    });
    const savedFiles = saveHarnessMock.mock.calls[0][1];
    expect(savedFiles.every((file) => file.path === '.ai/harness.yaml' || file.path.startsWith('.ai/harness/'))).toBe(true);
  });

  it('shows stale manifest conflict and does not retry save', async () => {
    saveHarnessMock.mockRejectedValueOnce(new ApiError('manifest_conflict', 409, {
      error: 'manifest_conflict',
      current_manifest_hash: 'sha256:current',
      changed_files: ['.ai/harness/rules/security.md'],
    }));
    render(<Harness />);

    const textarea = await screen.findByDisplayValue(/# Security/);
    fireEvent.change(textarea, { target: { value: '# Security\n\nConflict' } });
    fireEvent.click(screen.getByRole('button', { name: /保存/ }));

    expect(await screen.findByText('Manifest 冲突')).toBeInTheDocument();
    expect(screen.getAllByText('.ai/harness/rules/security.md').length).toBeGreaterThan(0);
    expect(saveHarnessMock).toHaveBeenCalledTimes(1);
  });

  it('removes edit entry points when can_edit is false', async () => {
    fetchHarnessMock.mockResolvedValueOnce(harnessBundle({ permissions: { can_view: true, can_edit: false, can_run_checks: false } }));

    render(<Harness />);

    expect((await screen.findAllByText('.ai/harness/rules/security.md')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /保存/ })).not.toBeInTheDocument();
    expect(document.querySelector('textarea.harnessTextarea')).toBeNull();
    expect(screen.getByText(/# Security/)).toBeInTheDocument();
  });

  it('keeps editing available but hides Run Checks when can_run_checks is false', async () => {
    fetchHarnessMock.mockResolvedValueOnce(harnessBundle({ permissions: { can_view: true, can_edit: true, can_run_checks: false } }));

    render(<Harness />);

    expect(await screen.findByDisplayValue(/# Security/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /保存/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Run Checks/ })).not.toBeInTheDocument();
  });

  it('does not render Harness content when can_view is false', async () => {
    fetchHarnessMock.mockResolvedValueOnce(harnessBundle({ permissions: { can_view: false, can_edit: false, can_run_checks: false } }));

    render(<Harness />);

    expect(await screen.findByText('无访问权限')).toBeInTheDocument();
    expect(screen.getByText('没有权限访问该项目 Harness')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rules' })).not.toBeInTheDocument();
    expect(document.querySelector('textarea.harnessTextarea')).toBeNull();
  });

  it('renders sanitized Markdown preview', async () => {
    render(<Harness />);

    await screen.findByRole('heading', { name: 'Security' });
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('[onerror]')).toBeNull();
  });
});
