import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Settings } from '../pages/Settings';
import {
  fetchAgentPrompt,
  fetchRuntimeCatalog,
  fetchSettings,
  resetSettings,
  updateAgentPrompt,
  updateSettings,
} from '../lib/api';

vi.mock('../lib/api', () => ({
  fetchAgentPrompt: vi.fn(() => Promise.resolve({
    agent_name: 'planner',
    path: 'agents/planner.md',
    content: 'planner prompt',
  })),
  fetchRuntimeCatalog: vi.fn(() => Promise.resolve({
    runtimes: {
      auto: { name: 'Auto', cli: 'auto', available: true, configured: true },
    },
    candidates: [
      {
        id: 'claude',
        provider: 'claude',
        name: 'Claude Code',
        cli: 'claude',
        available: true,
        supported: true,
        args: ['-p', '--output-format', 'stream-json'],
        prompt_mode: 'arg',
        model_arg_style: 'long',
        version: '2.1.133 (Claude Code)',
        model: 'mimo-v2.5-pro',
      },
      {
        id: 'codex',
        provider: 'codex',
        name: 'Codex CLI',
        cli: 'codex',
        available: true,
        supported: true,
        args: ['exec'],
        prompt_mode: 'arg',
        model_arg_style: 'codex',
        version: 'codex-cli 0.128.0',
        model: 'gpt-5.5',
      },
      {
        id: 'opencode',
        provider: 'opencode',
        name: 'OpenCode',
        cli: 'opencode',
        available: true,
        supported: true,
        args: ['run'],
        prompt_mode: 'arg',
        model_arg_style: 'long',
        version: '1.14.41',
        model: 'glm-5',
      },
    ],
  })),
  fetchSettings: vi.fn(() => Promise.resolve({
    source: 'platform',
    path: '/repo/templates/team.yaml',
    warnings: [],
    config: {
      runtimes: {
        auto: { name: 'Auto', cli: 'auto' },
      },
      agents: [
        {
          name: 'planner',
          runtime_id: 'auto',
          role: 'planner',
          prompt: 'agents/planner.md',
        },
      ],
    },
  })),
  resetSettings: vi.fn(),
  updateAgentPrompt: vi.fn(),
  updateSettings: vi.fn(),
}));

const fetchAgentPromptMock = vi.mocked(fetchAgentPrompt);
const fetchRuntimeCatalogMock = vi.mocked(fetchRuntimeCatalog);
const fetchSettingsMock = vi.mocked(fetchSettings);
const resetSettingsMock = vi.mocked(resetSettings);
const updateAgentPromptMock = vi.mocked(updateAgentPrompt);
const updateSettingsMock = vi.mocked(updateSettings);

describe('Settings runtimes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('expands the default auto runtime into detected available CLIs', async () => {
    render(<Settings />);

    await waitFor(() => {
      expect(fetchSettingsMock).toHaveBeenCalled();
      expect(fetchRuntimeCatalogMock).toHaveBeenCalled();
      expect(fetchAgentPromptMock).toHaveBeenCalledWith('planner');
    });

    expect(await screen.findByText('Claude Code')).toBeInTheDocument();
    expect(screen.getByText('Codex CLI')).toBeInTheDocument();
    expect(screen.getByText('OpenCode')).toBeInTheDocument();
    expect(screen.queryByText('Auto')).not.toBeInTheDocument();

    expect(screen.getByText('2.1.133 (Claude Code)')).toBeInTheDocument();
    expect(screen.getByText('codex-cli 0.128.0')).toBeInTheDocument();
    expect(screen.getByText('1.14.41')).toBeInTheDocument();
    expect(screen.queryByText(/claude ·/)).not.toBeInTheDocument();

    expect(screen.getByText('mimo-v2.5-pro')).toBeInTheDocument();
    expect(screen.getByText('gpt-5.5')).toBeInTheDocument();
    expect(screen.getByText('glm-5')).toBeInTheDocument();
    expect(screen.queryByText('Name')).not.toBeInTheDocument();
    expect(screen.queryByText('CLI')).not.toBeInTheDocument();
    expect(screen.queryByText('Model Override')).not.toBeInTheDocument();
    expect(screen.queryByText(/CLI 当前配置/)).not.toBeInTheDocument();
    expect(screen.queryByText('自动检测')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '清除自定义设置' })).not.toBeInTheDocument();
  });

  it('moves agents off auto when the detected runtimes become the editable defaults', async () => {
    render(<Settings />);

    await screen.findByText('Claude Code');
    fireEvent.click(screen.getByRole('button', { name: 'Agents' }));

    const runtimeSelect = screen.getByLabelText('Runtime');
    expect(within(runtimeSelect).queryByRole('option', { name: 'Auto' })).not.toBeInTheDocument();
    expect(within(runtimeSelect).getByRole('option', { name: 'Claude Code' })).toHaveValue('claude');
    expect(runtimeSelect).toHaveValue('claude');
  });

  it('keeps saving available only on editable agent settings', async () => {
    updateSettingsMock.mockResolvedValueOnce({
      source: 'customized',
      path: 'db:default',
      warnings: [],
      config: {
        runtimes: {
          claude: { name: 'Claude Code', cli: 'claude' },
          codex: { name: 'Codex CLI', cli: 'codex' },
          opencode: { name: 'OpenCode', cli: 'opencode' },
        },
        agents: [
          {
            name: 'planner',
            runtime_id: 'claude',
            role: 'planner',
            prompt: 'agents/planner.md',
          },
        ],
      },
    });

    render(<Settings />);

    await screen.findByText('Claude Code');
    expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Agents' }));
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(updateSettingsMock).toHaveBeenCalledWith(expect.objectContaining({
        runtimes: expect.objectContaining({
          claude: expect.objectContaining({ name: 'Claude Code', cli: 'claude' }),
          codex: expect.objectContaining({ name: 'Codex CLI', cli: 'codex' }),
          opencode: expect.objectContaining({ name: 'OpenCode', cli: 'opencode' }),
        }),
        agents: [expect.objectContaining({ runtime_id: 'claude' })],
      }));
    });
    expect(updateAgentPromptMock).not.toHaveBeenCalled();
    expect(resetSettingsMock).not.toHaveBeenCalled();
  });
});
