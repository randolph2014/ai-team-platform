import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Pipelines } from '../pages/Pipelines';
import { createPipeline, fetchPipelineTemplates, fetchPipelines, updatePipeline } from '../lib/api';

vi.mock('../lib/api', () => ({
  createPipeline: vi.fn(() => Promise.resolve({ id: 'project-delivery', name: '研发流水线' })),
  deletePipeline: vi.fn(),
  fetchPipelineTemplates: vi.fn(() => Promise.resolve([
    {
      id: 'project-delivery',
      name: '研发流水线',
      description: '完整研发闭环',
      stages: ['context_scan', 'develop'],
      stage_count: 2,
      human_gate_count: 0,
      estimated_effort: 'L',
      stage_summary: ['代码库扫描', '开发实施'],
      tags: ['feature', 'qa'],
      yaml_config: {
        name: '研发流水线',
        description: '完整研发闭环',
        version: '1.0',
        agents: [
          { name: 'coder', runtime_id: 'codex' },
        ],
        stages: [
          { id: 'context_scan', name: '代码库扫描', type: 'context_scan' },
          { id: 'develop', name: '开发实施', agents: ['coder'] },
        ],
      },
    },
  ])),
  fetchPipelines: vi.fn(() => Promise.resolve([])),
  updatePipeline: vi.fn(),
}));

const createPipelineMock = vi.mocked(createPipeline);
const updatePipelineMock = vi.mocked(updatePipeline);

describe('Pipeline builtin templates', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates a custom pipeline from a builtin template instead of updating the builtin id', async () => {
    render(<Pipelines />);

    fireEvent.click(await screen.findByRole('button', { name: /从模板创建/ }));
    expect(screen.getByDisplayValue('研发流水线')).toBeInTheDocument();
    expect(screen.getByText('代码库扫描（系统） → 开发实施（coder/codex）')).toBeInTheDocument();
    expect(screen.queryByText('feature')).not.toBeInTheDocument();
    expect(screen.queryByText('qa')).not.toBeInTheDocument();
    expect(screen.queryByText('L')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(createPipelineMock).toHaveBeenCalled();
    });
    expect(updatePipelineMock).not.toHaveBeenCalled();
  });
});
