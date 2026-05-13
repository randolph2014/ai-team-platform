import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NewRunModal } from '../components/NewRunModal';
import {
  apiFetch,
  createRun,
  fetchPipelineTemplates,
  fetchPipelines,
  rememberRunWorkdir,
} from '../lib/api';

vi.mock('../lib/api', () => ({
  apiFetch: vi.fn(),
  createRun: vi.fn(() => Promise.resolve({ run_id: 'api-run-1', status: 'running', project_root: '/repo' })),
  fetchPipelineTemplates: vi.fn(() => Promise.resolve([
    {
      id: 'project-delivery',
      name: '研发流水线',
      description: '完整研发闭环',
      stages: ['context_scan', 'develop'],
      yaml_config: {},
    },
    {
      id: 'bugfix',
      name: '修复 bug 流水线',
      description: '定位、修复、回归',
      stages: ['context_scan', 'develop', 'qa'],
      yaml_config: {},
    },
  ])),
  fetchPipelines: vi.fn(() => Promise.resolve([
    {
      id: 'custom-pipe',
      name: '自定义交付',
      description: '项目自定义流程',
      yaml_config: {},
    },
  ])),
  rememberRunWorkdir: vi.fn(),
  runQuery: vi.fn(() => '?workdir=%2Frepo'),
}));

function jsonResponse(data: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(data),
  } as Response);
}

const apiFetchMock = vi.mocked(apiFetch);
const createRunMock = vi.mocked(createRun);
const fetchPipelineTemplatesMock = vi.mocked(fetchPipelineTemplates);
const fetchPipelinesMock = vi.mocked(fetchPipelines);
const rememberRunWorkdirMock = vi.mocked(rememberRunWorkdir);

describe('NewRunModal pipeline selection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiFetchMock.mockImplementation((path, init) => {
      if (path === '/projects' && !init) {
        return jsonResponse([
          { id: 'proj-1', name: 'Repo', root_path: '/repo', created_at: '2026-01-01T00:00:00' },
        ]);
      }
      if (path.startsWith('/projects/browse')) {
        return jsonResponse({ path: null, parent: null, entries: [{ name: 'repo', path: '/repo' }] });
      }
      if (path === '/projects/import') {
        return jsonResponse({ id: 'proj-1', name: 'Repo', root_path: '/repo', created_at: '2026-01-01T00:00:00' });
      }
      return jsonResponse({});
    });
    window.history.replaceState({}, '', '/dashboard');
  });

  it('loads builtin templates and custom pipelines as executable run choices', async () => {
    render(<NewRunModal open onClose={vi.fn()} onRefreshNeeded={vi.fn()} />);

    await waitFor(() => {
      expect(fetchPipelineTemplatesMock).toHaveBeenCalled();
      expect(fetchPipelinesMock).toHaveBeenCalled();
    });

    expect(screen.getByRole('option', { name: '研发流水线' })).toHaveValue('template:project-delivery');
    expect(screen.getByRole('option', { name: '修复 bug 流水线' })).toHaveValue('template:bugfix');
    expect(screen.getByRole('option', { name: '自定义交付' })).toHaveValue('pipeline:custom-pipe');
  });

  it('submits the selected pipeline id when creating a run', async () => {
    render(<NewRunModal open onClose={vi.fn()} onRefreshNeeded={vi.fn()} />);

    await screen.findByRole('option', { name: '修复 bug 流水线' });
    await screen.findByRole('option', { name: 'Repo (/repo)' });
    fireEvent.change(screen.getByLabelText('Pipeline 模板'), {
      target: { value: 'template:bugfix' },
    });
    fireEvent.change(screen.getByLabelText('项目路径'), {
      target: { value: 'proj-1' },
    });
    fireEvent.change(screen.getByLabelText('需求描述'), {
      target: { value: '修复登录失败' },
    });
    fireEvent.click(screen.getByRole('button', { name: '开始运行' }));

    await waitFor(() => {
      expect(createRunMock).toHaveBeenCalledWith('', '修复登录失败', { pipeline_id: 'template:bugfix', project_id: 'proj-1' });
    });
    expect(rememberRunWorkdirMock).toHaveBeenCalledWith('api-run-1', '/repo');
  });

  it('imports a directory through the project path picker instead of exposing manual path input', async () => {
    apiFetchMock.mockImplementation((path, init) => {
      if (path === '/projects' && !init) {
        return jsonResponse([]);
      }
      if (path === '/projects/browse') {
        return jsonResponse({ path: null, parent: null, entries: [{ name: 'repo', path: '/repo' }] });
      }
      if (path.startsWith('/projects/browse?path=')) {
        return jsonResponse({ path: '/repo', parent: null, entries: [] });
      }
      if (path === '/projects/import') {
        return jsonResponse({ id: 'proj-1', name: 'Repo', root_path: '/repo', created_at: '2026-01-01T00:00:00' });
      }
      return jsonResponse({});
    });

    render(<NewRunModal open onClose={vi.fn()} onRefreshNeeded={vi.fn()} />);

    expect(screen.queryByText(/\/api\/projects/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/手动输入/)).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: '选择项目路径' }));
    fireEvent.click(await screen.findByRole('button', { name: 'repo' }));
    await screen.findByText('/repo');
    fireEvent.click(screen.getByRole('button', { name: '引入并选择' }));

    await screen.findByRole('option', { name: 'Repo (/repo)' });
    expect(apiFetchMock).toHaveBeenCalledWith('/projects/import', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ root_path: '/repo' }),
    }));
  });

  it('uses a larger textarea for requirement input', async () => {
    render(<NewRunModal open onClose={vi.fn()} onRefreshNeeded={vi.fn()} />);

    expect(await screen.findByLabelText('需求描述')).toHaveClass('requirementTextarea');
  });
});
