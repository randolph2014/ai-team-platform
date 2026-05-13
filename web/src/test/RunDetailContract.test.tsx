import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RunDetail } from '../pages/RunDetail';
import type { RunReport } from '../lib/types';
import { fetchRun } from '../lib/api';

vi.mock('../lib/api', () => ({
  apiFetch: vi.fn(),
  fetchRun: vi.fn(),
  fetchRunArtifactText: vi.fn(),
  fetchRunDiff: vi.fn(),
  projectQuery: vi.fn(() => ''),
  rememberedWorkdir: vi.fn(() => '/repo'),
  rememberRunWorkdir: vi.fn(),
  runWebSocketUrl: vi.fn(() => 'ws://localhost/ws/runs/run-contract'),
}));

class MockWebSocket {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor() {
    setTimeout(() => this.onopen?.(), 0);
  }

  close() {
    this.onclose?.();
  }
}

const fetchRunMock = vi.mocked(fetchRun);

function runReport(): RunReport {
  return {
    run_id: 'run-contract',
    status: 'completed',
    requirement: '实现 Task Contract 展示',
    project_root: '/repo',
    output_dir: '/repo/.ai/team-output/run-contract',
    config_source: 'project',
    stages: [
      {
        stage_id: 'develop',
        stage_name: '开发实施',
        status: 'completed',
        is_parallel: false,
        type: 'agent',
        agents: [],
        quality_gates: [],
        artifact_validations: [
          {
            artifact: 'implementation-report.json',
            validator: 'runtime-schema',
            status: 'passed',
            message: 'schema valid',
          },
        ],
      },
    ],
    artifacts: ['requirement-final.json', 'implementation-report.json'],
    current_contract_status: 'failed',
    current_contract_validations: [
      {
        artifact: 'implementation-report.json',
        validator: 'current-schema',
        status: 'failed',
        message: '$.traceability: required field missing',
      },
    ],
  };
}

describe('RunDetail current contract validation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, '', '/runs/run-contract');
    vi.stubGlobal('WebSocket', MockWebSocket);
    fetchRunMock.mockResolvedValue(runReport());
  });

  it('distinguishes runtime artifact validation from current schema revalidation', async () => {
    render(<RunDetail runId="run-contract" />);

    expect(await screen.findByText('当前契约再验证')).toBeInTheDocument();
    expect(screen.getByText('运行时校验')).toBeInTheDocument();
    expect(screen.getByText('当前 schema 再验证')).toBeInTheDocument();
    expect(screen.getAllByText('schema valid').length).toBeGreaterThan(0);
    expect(screen.getByText('$.traceability: required field missing')).toBeInTheDocument();
    expect(screen.getByText('Task Contract')).toBeInTheDocument();

    await waitFor(() => expect(fetchRunMock).toHaveBeenCalledWith('run-contract', '/repo'));
  });
});
