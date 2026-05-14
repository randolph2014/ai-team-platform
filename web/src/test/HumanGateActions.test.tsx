import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PipelineTimeline } from '../components/PipelineTimeline';
import type { RunReport, StageRun } from '../lib/types';
import { resumeRun, submitHumanDecision } from '../lib/api';

vi.mock('../lib/api', () => ({
  rememberedWorkdir: vi.fn(() => '/repo'),
  resumeRun: vi.fn(),
  submitHumanDecision: vi.fn(() => Promise.resolve({ run_id: 'r1', status: 'resuming' })),
}));

const submitHumanDecisionMock = vi.mocked(submitHumanDecision);
const resumeRunMock = vi.mocked(resumeRun);

function stage(overrides: Partial<StageRun> = {}): StageRun {
  return {
    stage_id: 'task_plan_confirm',
    stage_name: '任务计划确认',
    status: 'waiting',
    is_parallel: false,
    type: 'human_review',
    agents: [],
    quality_gates: [],
    ...overrides,
  };
}

function runReport(stages: StageRun[]): RunReport {
  return {
    run_id: 'r1',
    status: 'paused',
    requirement: '实现人工确认',
    project_root: '/repo',
    output_dir: '/repo/.ai/runs/r1',
    config_source: 'test',
    stages,
    artifacts: [],
  };
}

function renderTimeline(stages: StageRun[] = [stage()], onStageAction = vi.fn()) {
  render(<PipelineTimeline run={runReport(stages)} onStageAction={onStageAction} />);
  return onStageAction;
}

describe('Human gate actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('requires a rejection reason before submitting a rejected human decision', async () => {
    renderTimeline();

    const reason = screen.getByLabelText('拒绝理由');
    const rejectButton = screen.getByRole('button', { name: /拒绝/ });

    expect(reason).toBeInTheDocument();
    expect(rejectButton).toBeDisabled();

    fireEvent.change(reason, { target: { value: '任务缺少回滚方案' } });
    expect(rejectButton).toBeEnabled();

    fireEvent.click(rejectButton);

    await waitFor(() => {
      expect(submitHumanDecisionMock).toHaveBeenCalledWith('r1', '/repo', {
        stage_id: 'task_plan_confirm',
        decision: 'rejected',
        reason: '任务缺少回滚方案',
        required_changes: [],
      });
    });
    expect(resumeRunMock).not.toHaveBeenCalled();
  });

  it('splits required changes by line and removes blank items', async () => {
    renderTimeline();

    fireEvent.change(screen.getByLabelText('拒绝理由'), {
      target: { value: '计划不可验收' },
    });
    fireEvent.change(screen.getByLabelText('必须修改项'), {
      target: { value: '  补充回滚方案  \n\n更新自动化验证\n  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: /拒绝/ }));

    await waitFor(() => {
      expect(submitHumanDecisionMock).toHaveBeenCalledWith('r1', '/repo', {
        stage_id: 'task_plan_confirm',
        decision: 'rejected',
        reason: '计划不可验收',
        required_changes: ['补充回滚方案', '更新自动化验证'],
      });
    });
  });

  it('submits an approved human decision without reason or required changes', async () => {
    renderTimeline();

    fireEvent.click(screen.getByRole('button', { name: /通过/ }));

    await waitFor(() => {
      expect(submitHumanDecisionMock).toHaveBeenCalledWith('r1', '/repo', {
        stage_id: 'task_plan_confirm',
        decision: 'approved',
        reason: '',
        required_changes: [],
      });
    });
    expect(resumeRunMock).not.toHaveBeenCalled();
  });

  it('refreshes the run after a human decision is submitted', async () => {
    const onStageAction = renderTimeline();

    fireEvent.click(screen.getByRole('button', { name: /通过/ }));

    await waitFor(() => {
      expect(onStageAction).toHaveBeenCalledTimes(1);
    });
  });

  it('shows artifact validation failures, human decisions, and loopback target on a stage card', () => {
    renderTimeline([
      stage({
        status: 'failed',
        artifact_validations: [
          {
            artifact: 'plans/task-plan.md',
            validator: 'plan-contract',
            status: 'failed',
            message: '缺少回滚方案',
          },
        ],
        human_decision: {
          stage_id: 'task_plan_confirm',
          decision: 'rejected',
          reason: '任务缺少回滚方案',
          required_changes: ['补充回滚方案'],
        },
        loopback_to: 'task_plan',
      }),
    ]);

    expect(screen.getByText('产物校验')).toBeInTheDocument();
    expect(screen.getByText('plans/task-plan.md')).toBeInTheDocument();
    expect(screen.getByText('plan-contract')).toBeInTheDocument();
    expect(screen.getByText('缺少回滚方案')).toBeInTheDocument();
    expect(screen.getByText('人工决策')).toBeInTheDocument();
    expect(screen.getByText('已拒绝')).toBeInTheDocument();
    expect(screen.getByText('任务缺少回滚方案')).toBeInTheDocument();
    expect(screen.getByText('补充回滚方案')).toBeInTheDocument();
    expect(screen.getByText(/回退到 task_plan/)).toBeInTheDocument();
  });
});
