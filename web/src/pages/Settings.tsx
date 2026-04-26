import { Bot, CheckCircle2, FolderGit2, Gauge, RadioTower, RotateCcw, Save, Settings2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fetchSettings, updateSettings } from '../lib/api';
import type { Settings as SettingsType } from '../lib/types';

const DEFAULT_SETTINGS: SettingsType = {
  provider: {
    default_provider: 'Auto',
    claude_params: '-p --output-format stream-json',
    codex_params: 'exec',
  },
  context_scanner: {
    enabled: true,
    max_file_size: 50000,
    exclude_dirs: 'node_modules, .git, build',
  },
  worktree: {
    isolation_mode: 'per-run',
    base_branch: 'main',
    merge_strategy: 'squash',
  },
  quality_gates: {
    build_gate: 'required',
    test_gate: 'required',
    coverage_gate: 'warning',
  },
  runner: {
    agent_timeout: '1800s',
    heartbeat: '60s',
    log_mode: 'interleaved',
  },
};

const PROVIDER_OPTIONS = ['Auto', 'Claude', 'Codex', 'OpenAI'];
const ISOLATION_OPTIONS = ['per-run', 'shared', 'none'];
const MERGE_OPTIONS = ['squash', 'merge', 'rebase'];
const GATE_OPTIONS = ['required', 'warning', 'optional'];
const LOG_MODE_OPTIONS = ['interleaved', 'sequential', 'agent-only'];

interface SettingRowProps {
  label: string;
  description: string;
  children: React.ReactNode;
}

function SettingRow({ label, description, children }: SettingRowProps) {
  return (
    <div className="settingRow">
      <div>
        <strong>{label}</strong>
        <small>{description}</small>
      </div>
      <div className="settingControl">{children}</div>
    </div>
  );
}

export function Settings() {
  const [settings, setSettings] = useState<SettingsType>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [activeSection, setActiveSection] = useState(0);

  useEffect(() => {
    fetchSettings()
      .then(setSettings)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  function update<K extends keyof SettingsType>(section: K, key: keyof SettingsType[K], value: unknown) {
    setSettings((prev) => ({
      ...prev,
      [section]: { ...prev[section], [key]: value },
    }));
  }

  async function handleSave() {
    setSaving(true);
    setSaveMessage('');
    try {
      await updateSettings(settings);
      setSaveMessage('设置已保存');
    } catch (e: unknown) {
      setSaveMessage(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  function handleReset() {
    setSettings(DEFAULT_SETTINGS);
    setSaveMessage('已恢复默认值（未保存）');
  }

  const sections: Array<{ name: string; icon: typeof Settings2 }> = [
    { name: 'Provider', icon: Bot },
    { name: '上下文扫描', icon: RadioTower },
    { name: 'Worktree', icon: FolderGit2 },
    { name: '质量门禁', icon: CheckCircle2 },
    { name: 'Runner', icon: Gauge },
  ];

  if (loading) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>设置</h1></header>
        <div className="emptyState">加载中...</div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>设置</h1>
        <div className="pageActions">
          <button className="button" onClick={handleReset}><RotateCcw size={14} /> 恢复默认</button>
          <button className="button primary" onClick={handleSave} disabled={saving}><Save size={14} /> {saving ? '保存中...' : '保存'}</button>
        </div>
      </header>
      {saveMessage && <div className={`saveBanner ${saveMessage.includes('失败') ? 'saveBannerError' : ''}`}>{saveMessage}</div>}
      <div className="settingsGrid">
        <aside className="settingsNav">
          {sections.map((section, index) => {
            const Icon = section.icon;
            return (
              <a
                key={section.name}
                className={activeSection === index ? 'settingsNavActive' : ''}
                onClick={() => setActiveSection(index)}
              >
                <Icon size={14} /> {section.name}
              </a>
            );
          })}
        </aside>
        <section className="panel">
          {activeSection === 0 && (
            <div className="settingGroup">
              <h2><Bot size={16} /> Provider</h2>
              <SettingRow label="默认 Provider" description="默认使用的 AI Provider，可通过命令参数覆盖">
                <select value={settings.provider.default_provider} onChange={(e) => update('provider', 'default_provider', e.target.value)}>
                  {PROVIDER_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              </SettingRow>
              <SettingRow label="Claude 参数" description="传递给 Claude CLI 的额外参数">
                <input value={settings.provider.claude_params} onChange={(e) => update('provider', 'claude_params', e.target.value)} />
              </SettingRow>
              <SettingRow label="Codex 参数" description="传递给 Codex CLI 的额外参数">
                <input value={settings.provider.codex_params} onChange={(e) => update('provider', 'codex_params', e.target.value)} />
              </SettingRow>
            </div>
          )}

          {activeSection === 1 && (
            <div className="settingGroup">
              <h2><RadioTower size={16} /> 上下文扫描</h2>
              <SettingRow label="启用扫描" description="在运行前自动扫描项目上下文">
                <label className="switch">
                  <input type="checkbox" checked={settings.context_scanner.enabled} onChange={(e) => update('context_scanner', 'enabled', e.target.checked)} />
                  <span className="switchSlider" />
                </label>
              </SettingRow>
              <SettingRow label="最大文件大小" description="扫描时忽略超过此字节数的文件">
                <input type="number" value={settings.context_scanner.max_file_size} onChange={(e) => update('context_scanner', 'max_file_size', Number(e.target.value))} />
              </SettingRow>
              <SettingRow label="排除目录" description="逗号分隔的目录列表，扫描时跳过">
                <input value={settings.context_scanner.exclude_dirs} onChange={(e) => update('context_scanner', 'exclude_dirs', e.target.value)} />
              </SettingRow>
            </div>
          )}

          {activeSection === 2 && (
            <div className="settingGroup">
              <h2><FolderGit2 size={16} /> Worktree</h2>
              <SettingRow label="隔离模式" description="如何为每个运行创建隔离的工作区">
                <select value={settings.worktree.isolation_mode} onChange={(e) => update('worktree', 'isolation_mode', e.target.value)}>
                  {ISOLATION_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              </SettingRow>
              <SettingRow label="基础分支" description="创建 worktree 时基于的分支">
                <input value={settings.worktree.base_branch} onChange={(e) => update('worktree', 'base_branch', e.target.value)} />
              </SettingRow>
              <SettingRow label="合并策略" description="代码合并时使用的策略">
                <select value={settings.worktree.merge_strategy} onChange={(e) => update('worktree', 'merge_strategy', e.target.value)}>
                  {MERGE_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              </SettingRow>
            </div>
          )}

          {activeSection === 3 && (
            <div className="settingGroup">
              <h2><CheckCircle2 size={16} /> 质量门禁</h2>
              <SettingRow label="编译门禁" description="编译检查的要求级别">
                <select value={settings.quality_gates.build_gate} onChange={(e) => update('quality_gates', 'build_gate', e.target.value)}>
                  {GATE_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              </SettingRow>
              <SettingRow label="测试门禁" description="测试通过的要求级别">
                <select value={settings.quality_gates.test_gate} onChange={(e) => update('quality_gates', 'test_gate', e.target.value)}>
                  {GATE_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              </SettingRow>
              <SettingRow label="覆盖率门禁" description="代码覆盖率的要求级别">
                <select value={settings.quality_gates.coverage_gate} onChange={(e) => update('quality_gates', 'coverage_gate', e.target.value)}>
                  {GATE_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              </SettingRow>
            </div>
          )}

          {activeSection === 4 && (
            <div className="settingGroup">
              <h2><Gauge size={16} /> Runner</h2>
              <SettingRow label="Agent 超时" description="单个 Agent 的最大运行时间">
                <input value={settings.runner.agent_timeout} onChange={(e) => update('runner', 'agent_timeout', e.target.value)} />
              </SettingRow>
              <SettingRow label="Heartbeat" description="Agent 心跳间隔">
                <input value={settings.runner.heartbeat} onChange={(e) => update('runner', 'heartbeat', e.target.value)} />
              </SettingRow>
              <SettingRow label="并行日志" description="多 Agent 并发时日志输出模式">
                <select value={settings.runner.log_mode} onChange={(e) => update('runner', 'log_mode', e.target.value)}>
                  {LOG_MODE_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              </SettingRow>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
