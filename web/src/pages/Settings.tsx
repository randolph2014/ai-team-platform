import { AlertTriangle, FileText, Loader2, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchSettings, resetSettings, updateSettings } from '../lib/api';
import type { AgentConfig, AppConfig, RuntimeConfig, SettingsResponse } from '../lib/types';

type SettingsSection = 'runtimes' | 'agents' | 'runner' | 'worktree' | 'quality_gates' | 'raw';

const SETTINGS_SECTIONS: Array<{ key: SettingsSection; label: string }> = [
  { key: 'runtimes', label: 'Runtimes' },
  { key: 'agents', label: 'Agents' },
  { key: 'runner', label: 'Runner' },
  { key: 'worktree', label: 'Worktree' },
  { key: 'quality_gates', label: 'Quality Gates' },
  { key: 'raw', label: 'Raw' },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function renderValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span style={{ color: 'var(--text-muted)' }}>-</span>;
  if (typeof value === 'boolean') return <span style={{ color: value ? 'var(--green)' : 'var(--red)' }}>{value ? 'true' : 'false'}</span>;
  if (typeof value === 'number') return <span style={{ color: 'var(--blue)' }}>{value}</span>;
  if (typeof value === 'string') {
    if (value === '***') return <span style={{ color: 'var(--yellow)' }}>•••••••</span>;
    return value || <span style={{ color: 'var(--text-muted)' }}>-</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: 'var(--text-muted)' }}>[]</span>;
    return (
      <div className="configNestedList">
        {value.map((item, i) => (
          <div key={i} className="configNestedItem">
            {isRecord(item) ? renderObject(item) : renderValue(item)}
          </div>
        ))}
      </div>
    );
  }
  if (isRecord(value)) return renderObject(value);
  return String(value);
}

function renderObject(obj: Record<string, unknown>): React.ReactNode {
  return (
    <div className="configEntries">
      {Object.entries(obj).map(([key, val]) => (
        <div key={key} className="configEntry">
          <span className="configKey">{key}</span>
          <span className="configValue">{renderValue(val)}</span>
        </div>
      ))}
    </div>
  );
}

function splitList(value?: string[]): string {
  return (value || []).join(', ');
}

function parseList(value: string): string[] | undefined {
  const list = value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return list.length > 0 ? list : undefined;
}

function cleanRuntime(runtime: RuntimeConfig): RuntimeConfig {
  const next: RuntimeConfig = {
    ...runtime,
    cli: runtime.cli.trim(),
  };
  if (!next.name?.trim()) delete next.name;
  else next.name = next.name.trim();
  if (!next.args || next.args.length === 0) delete next.args;
  if (!next.prompt_mode) delete next.prompt_mode;
  if (!next.default_model?.trim()) delete next.default_model;
  else next.default_model = next.default_model.trim();
  if (next.env) {
    const env = Object.fromEntries(
      Object.entries(next.env).filter(([, value]) => value !== '***'),
    );
    if (Object.keys(env).length > 0) next.env = env;
    else delete next.env;
  }
  return next;
}

function sanitizeEnvPlaceholders(value: unknown, parentKey?: string): unknown {
  if (Array.isArray(value)) return value.map((item) => sanitizeEnvPlaceholders(item));
  if (!isRecord(value)) return value;
  const entries = Object.entries(value).flatMap(([key, child]) => {
    if (parentKey === 'env' && child === '***') return [];
    return [[key, sanitizeEnvPlaceholders(child, key)] as const];
  });
  return Object.fromEntries(entries);
}

function normalizeConfig(config: AppConfig): AppConfig {
  return {
    ...config,
    runtimes: config.runtimes || {},
    agents: config.agents || [],
  };
}

export function Settings() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [draftConfig, setDraftConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [activeSection, setActiveSection] = useState<SettingsSection>('runtimes');

  const loadSettings = useCallback(() => {
    setLoading(true);
    setError('');
    fetchSettings()
      .then((result) => {
        setSettings(result);
        setDraftConfig(normalizeConfig(result.config));
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const runtimes = useMemo(
    () => draftConfig?.runtimes || {},
    [draftConfig],
  );
  const agents = useMemo(
    () => draftConfig?.agents || [],
    [draftConfig],
  );
  const runtimeIds = Object.keys(runtimes);

  function updateDraft(section: Partial<AppConfig>) {
    setDraftConfig((current) => ({ ...(current || {}), ...section }));
    setSaveMessage('');
  }

  function updateRuntime(id: string, value: RuntimeConfig) {
    updateDraft({ runtimes: { ...runtimes, [id]: value } });
  }

  function renameRuntime(oldId: string, newId: string) {
    const trimmed = newId.trim();
    if (!trimmed || runtimes[trimmed]) {
      setSaveMessage(`Runtime ID ${newId || '(empty)'} 无效或已存在`);
      return;
    }
    if (trimmed === oldId) return;
    const { [oldId]: runtime, ...rest } = runtimes;
    const renamed = { ...rest, [trimmed]: runtime };
    const renamedAgents = agents.map((agent) =>
      agent.runtime_id === oldId ? { ...agent, runtime_id: trimmed } : agent,
    );
    updateDraft({ runtimes: renamed, agents: renamedAgents });
  }

  function addRuntime() {
    let index = Object.keys(runtimes).length + 1;
    let id = `runtime-${index}`;
    while (runtimes[id]) {
      index += 1;
      id = `runtime-${index}`;
    }
    updateDraft({
      runtimes: {
        ...runtimes,
        [id]: { name: `Runtime ${index}`, cli: '', prompt_mode: 'arg' },
      },
    });
  }

  function removeRuntime(id: string) {
    const { [id]: _removed, ...nextRuntimes } = runtimes;
    updateDraft({
      runtimes: nextRuntimes,
      agents: agents.map((agent) =>
        agent.runtime_id === id ? { ...agent, runtime_id: Object.keys(nextRuntimes)[0] || '' } : agent,
      ),
    });
  }

  function updateAgent(index: number, patch: Partial<AgentConfig>) {
    updateDraft({
      agents: agents.map((agent, i) => (i === index ? { ...agent, ...patch } : agent)),
    });
  }

  function addAgent() {
    updateDraft({
      agents: [
        ...agents,
        {
          name: `agent-${agents.length + 1}`,
          runtime_id: runtimeIds[0] || '',
        },
      ],
    });
  }

  function removeAgent(index: number) {
    updateDraft({ agents: agents.filter((_, i) => i !== index) });
  }

  async function handleReset() {
    setSaving(true);
    setSaveMessage('');
    try {
      const result = await resetSettings();
      setSettings(result);
      setDraftConfig(normalizeConfig(result.config));
      setSaveMessage('设置已重置');
    } catch (e: unknown) {
      setSaveMessage(e instanceof Error ? e.message : '重置失败');
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    if (!draftConfig) return;
    setSaving(true);
    setSaveMessage('');
    try {
      const invalidRuntime = Object.entries(runtimes).find(([id, runtime]) => !id.trim() || !runtime.cli.trim());
      if (invalidRuntime) {
        throw new Error(`Runtime ${invalidRuntime[0] || '(empty)'} 缺少 ID 或 CLI`);
      }
      const invalidAgent = agents.find((agent) => !agent.name.trim() || !agent.runtime_id.trim() || !runtimes[agent.runtime_id]);
      if (invalidAgent) {
        throw new Error(`Agent ${invalidAgent?.name || '(empty)'} 缺少名称或有效 Runtime`);
      }
      const cleanedRuntimes = Object.fromEntries(
        Object.entries(runtimes)
          .map(([id, runtime]) => [id.trim(), cleanRuntime(runtime)]),
      );
      const cleanedAgents = agents
        .map((agent) => ({
          ...agent,
          name: agent.name.trim(),
          runtime_id: agent.runtime_id.trim(),
          role: agent.role?.trim() || undefined,
          prompt: agent.prompt?.trim() || undefined,
          model: agent.model?.trim() || undefined,
          fallback_models: agent.fallback_models?.filter(Boolean),
        }));
      const payload = sanitizeEnvPlaceholders({
        ...draftConfig,
        runtimes: cleanedRuntimes,
        agents: cleanedAgents,
      }) as AppConfig;
      const result = await updateSettings(payload);
      setSettings(result);
      setDraftConfig(normalizeConfig(result.config));
      setSaveMessage('设置已保存');
    } catch (e: unknown) {
      setSaveMessage(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>设置</h1></header>
        <div className="emptyState"><Loader2 size={24} className="spinner" /> 加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <header className="pageHeader"><h1>设置</h1></header>
        <div className="errorPanel">
          <h2><AlertTriangle size={20} /> 加载失败</h2>
          <p>{error}</p>
          <button className="button primary" onClick={loadSettings}>重试</button>
        </div>
      </div>
    );
  }

  if (!settings || !draftConfig) return null;

  return (
    <div className="page">
      <header className="pageHeader">
        <h1>设置</h1>
        <div className="pageActions">
          <span className="configSource">
            <FileText size={13} /> {settings.source}{settings.path ? ` · ${settings.path}` : ''}
          </span>
          <button className="button" onClick={handleReset} disabled={saving}><RotateCcw size={14} /> 重置为默认</button>
          <button className="button primary" onClick={handleSave} disabled={saving}><Save size={14} /> {saving ? '保存中...' : '保存'}</button>
        </div>
      </header>

      {saveMessage && <div className={`saveBanner ${saveMessage.includes('失败') ? 'saveBannerError' : ''}`}>{saveMessage}</div>}
      {settings.warnings.length > 0 && (
        <div className="saveBanner saveBannerError" style={{ marginBottom: 18 }}>
          {settings.warnings.map((warning, i) => <p key={i}>{warning}</p>)}
        </div>
      )}

      <div className="settingsGrid">
        <aside className="settingsNav">
          {SETTINGS_SECTIONS.map((section) => (
            <button
              key={section.key}
              type="button"
              className={activeSection === section.key ? 'settingsNavActive' : ''}
              onClick={() => setActiveSection(section.key)}
            >
              {section.label}
            </button>
          ))}
        </aside>

        <section className="panel">
          {activeSection === 'runtimes' && (
            <div className="settingGroup">
              <div className="settingsSectionHeader">
                <h2>Runtimes</h2>
                <button className="button" onClick={addRuntime}><Plus size={14} /> 新增 Runtime</button>
              </div>
              <div className="settingsCards">
                {Object.entries(runtimes).map(([id, runtime]) => (
                  <div className="settingsEditCard" key={id}>
                    <div className="settingsCardHeader">
                      <strong>{runtime.name || id}</strong>
                      <button className="iconButton danger" onClick={() => removeRuntime(id)} aria-label="删除 Runtime">
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <div className="settingsFormGrid">
                      <label>
                        ID
                        <input
                          defaultValue={id}
                          onBlur={(e) => {
                            renameRuntime(id, e.target.value);
                            if (!e.target.value.trim() || (e.target.value.trim() !== id && runtimes[e.target.value.trim()])) {
                              e.target.value = id;
                            }
                          }}
                        />
                      </label>
                      <label>
                        Name
                        <input value={runtime.name || ''} onChange={(e) => updateRuntime(id, { ...runtime, name: e.target.value })} />
                      </label>
                      <label>
                        CLI
                        <input value={runtime.cli || ''} onChange={(e) => updateRuntime(id, { ...runtime, cli: e.target.value })} />
                      </label>
                      <label>
                        Args
                        <input value={splitList(runtime.args)} onChange={(e) => updateRuntime(id, { ...runtime, args: parseList(e.target.value) })} />
                      </label>
                      <label>
                        Prompt Mode
                        <select value={runtime.prompt_mode || 'arg'} onChange={(e) => updateRuntime(id, { ...runtime, prompt_mode: e.target.value as RuntimeConfig['prompt_mode'] })}>
                          <option value="arg">arg</option>
                          <option value="stdin">stdin</option>
                        </select>
                      </label>
                      <label>
                        Default Model
                        <input value={runtime.default_model || ''} onChange={(e) => updateRuntime(id, { ...runtime, default_model: e.target.value })} />
                      </label>
                    </div>
                    {runtime.available !== undefined && (
                      <div className="settingsMetaLine">available: {runtime.available ? 'true' : 'false'}</div>
                    )}
                    {runtime.env && <div className="settingsMetaLine">env: {Object.keys(runtime.env).length} 个变量，保存时会跳过值为 *** 的字段</div>}
                  </div>
                ))}
                {Object.keys(runtimes).length === 0 && <div className="emptyState">暂无 Runtime 配置</div>}
              </div>
            </div>
          )}

          {activeSection === 'agents' && (
            <div className="settingGroup">
              <div className="settingsSectionHeader">
                <h2>Agents</h2>
                <button className="button" onClick={addAgent}><Plus size={14} /> 新增 Agent</button>
              </div>
              <div className="settingsCards">
                {agents.map((agent, index) => (
                  <div className="settingsEditCard" key={`${agent.name}-${index}`}>
                    <div className="settingsCardHeader">
                      <strong>{agent.name || `Agent ${index + 1}`}</strong>
                      <button className="iconButton danger" onClick={() => removeAgent(index)} aria-label="删除 Agent">
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <div className="settingsFormGrid">
                      <label>
                        Name
                        <input value={agent.name} onChange={(e) => updateAgent(index, { name: e.target.value })} />
                      </label>
                      <label>
                        Runtime
                        <select value={agent.runtime_id} onChange={(e) => updateAgent(index, { runtime_id: e.target.value })}>
                          <option value="">选择 Runtime</option>
                          {runtimeIds.map((runtimeId) => (
                            <option key={runtimeId} value={runtimeId}>{runtimes[runtimeId]?.name || runtimeId}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Role
                        <input value={agent.role || ''} onChange={(e) => updateAgent(index, { role: e.target.value })} />
                      </label>
                      <label>
                        Model
                        <input value={agent.model || ''} onChange={(e) => updateAgent(index, { model: e.target.value })} />
                      </label>
                      <label className="settingsWideField">
                        Fallback Models
                        <input value={splitList(agent.fallback_models)} onChange={(e) => updateAgent(index, { fallback_models: parseList(e.target.value) })} />
                      </label>
                      <label className="settingsWideField">
                        Prompt
                        <textarea value={agent.prompt || ''} onChange={(e) => updateAgent(index, { prompt: e.target.value })} />
                      </label>
                    </div>
                  </div>
                ))}
                {agents.length === 0 && <div className="emptyState">暂无 Agent 配置</div>}
              </div>
            </div>
          )}

          {activeSection === 'runner' && (
            <div className="settingGroup">
              <h2>Runner</h2>
              {renderValue(draftConfig.runner)}
            </div>
          )}

          {activeSection === 'worktree' && (
            <div className="settingGroup">
              <h2>Worktree</h2>
              {renderValue(draftConfig.worktree)}
            </div>
          )}

          {activeSection === 'quality_gates' && (
            <div className="settingGroup">
              <h2>Quality Gates</h2>
              {renderValue(draftConfig.quality_gates)}
            </div>
          )}

          {activeSection === 'raw' && (
            <div className="settingGroup">
              <h2>Raw</h2>
              {renderObject(draftConfig as Record<string, unknown>)}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
