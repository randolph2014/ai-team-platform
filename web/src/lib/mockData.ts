import type { RunListItem, RunReport } from './types';

export const mockRuns: RunListItem[] = [
  {
    run_id: '42',
    status: 'running',
    pipeline: 'LifeRhythm 标准交付',
    output_dir: '.ai/team-output/42',
    started_at: new Date().toISOString(),
  },
  {
    run_id: '41',
    status: 'completed',
    pipeline: 'LifeRhythm 标准交付',
    output_dir: '.ai/team-output/41',
    started_at: new Date(Date.now() - 3600_000).toISOString(),
    completed_at: new Date(Date.now() - 1200_000).toISOString(),
  },
  {
    run_id: '40',
    status: 'failed',
    pipeline: 'LifeRhythm 标准交付',
    output_dir: '.ai/team-output/40',
    started_at: new Date(Date.now() - 86_400_000).toISOString(),
  },
];

export const mockRunDetail: RunReport = {
  run_id: '42',
  status: 'running',
  requirement: '实现 Checkin 伴侣视图的签到历史展示功能，并通过编译、测试和代码审查。',
  project_root: '/Users/wurui/IdeaProjects/LifeRhythm',
  output_dir: '.ai/team-output/42',
  config_source: 'project',
  started_at: new Date(Date.now() - 15 * 60_000).toISOString(),
  stages: [
    {
      stage_id: 'plan',
      stage_name: '方案讨论',
      status: 'completed',
      is_parallel: true,
      type: 'agent',
      duration_seconds: 121,
      agents: [
        { agent_name: 'brainstormer', provider: 'Claude', role: 'brainstormer', status: 'completed', duration_seconds: 116, output_file: 'brainstorm.md' },
        { agent_name: 'devils-advocate', provider: 'Claude', role: 'reviewer', status: 'completed', duration_seconds: 83, output_file: 'gap-analysis.md' },
      ],
      quality_gates: [],
    },
    {
      stage_id: 'architect',
      stage_name: '方案定稿',
      status: 'completed',
      is_parallel: false,
      type: 'agent',
      duration_seconds: 186,
      agents: [{ agent_name: 'solution-architect', provider: 'Claude', role: 'architect', status: 'completed', duration_seconds: 186, output_file: 'solution-draft.md' }],
      quality_gates: [],
    },
    {
      stage_id: 'develop',
      stage_name: '开发',
      status: 'running',
      is_parallel: false,
      type: 'agent',
      duration_seconds: 480,
      agents: [{ agent_name: 'tech-lead', provider: 'Claude', role: 'lead', status: 'running', duration_seconds: 480, output_file: 'tech-lead-output.md' }],
      quality_gates: [
        { name: 'Swift 编译', type: 'command', status: 'pending', command: 'swift build -c debug', required: true },
        { name: '单元测试', type: 'command', status: 'pending', command: 'swift test --parallel', required: true },
        { name: '代码覆盖率', type: 'threshold', status: 'pending', command: 'swift test --coverage', required: false },
      ],
    },
    {
      stage_id: 'verify',
      stage_name: '测试 + 审查',
      status: 'pending',
      is_parallel: true,
      type: 'agent',
      agents: [
        { agent_name: 'qa-automation', provider: 'Claude', role: 'tester', status: 'pending' },
        { agent_name: 'code-reviewer', provider: 'Claude', role: 'reviewer', status: 'pending' },
      ],
      quality_gates: [],
    },
    {
      stage_id: 'accept',
      stage_name: '人工验收',
      status: 'pending',
      is_parallel: false,
      type: 'human_review',
      agents: [],
      quality_gates: [],
    },
  ],
  artifacts: ['solution-draft.md', 'codebase-context.md', 'tech-lead-output.md', 'report.json'],
};

export const terminalLines = [
  'Reading Project.swift...',
  'Found CheckinView and CheckinHistoryStore.',
  'Updating CheckinHistoryViewModel.swift...',
  'Adding snapshot coverage for empty and populated states...',
  'Running swift build -c debug...',
];
