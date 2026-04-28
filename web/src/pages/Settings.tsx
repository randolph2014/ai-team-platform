import { AlertTriangle, FileText, Loader2, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchAgentPrompt,
  fetchRuntimeCatalog,
  fetchSettings,
  resetSettings,
  updateAgentPrompt,
  updateSettings,
} from '../lib/api';
import type {
  AgentConfig,
  AppConfig,
  RuntimeCandidate,
  RuntimeCatalogResponse,
  RuntimeConfig,
  SettingsResponse,
} from '../lib/types';

type SettingsSection = 'runtimes' | 'agents' | 'runner' | 'worktree';

const SETTINGS_SECTIONS: Array<{ key: SettingsSection; label: string }> = [
  { key: 'runtimes', label: 'Runtimes' },
  { key: 'agents', label: 'Agents' },
  { key: 'runner', label: 'Runner' },
  { key: 'worktree', label: 'Worktree' },
];

type PromptDraft = {
  path?: string;
  sourcePath?: string;
  content: string;
  originalContent: string;
  error?: string;
};

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
  const {
    available: _available,
    configured: _configured,
    default_model: legacyDefaultModel,
    launch_header: _launchHeader,
    path: _path,
    provider: _provider,
    source: _source,
    supported: _supported,
    unsupported_reason: _unsupportedReason,
    version: _version,
    ...rest
  } = runtime;
  const next: RuntimeConfig = {
    ...rest,
    cli: (runtime.cli || '').trim(),
  };
  if (!next.name?.trim()) delete next.name;
  else next.name = next.name.trim();
  if (!next.args || next.args.length === 0) delete next.args;
  else next.args = next.args.map((item) => item.trim()).filter(Boolean);
  if (!next.prompt_mode) delete next.prompt_mode;
  if (!next.model_arg_style?.trim()) delete next.model_arg_style;
  if (!next.model?.trim() && legacyDefaultModel?.trim()) next.model = legacyDefaultModel.trim();
  if (!next.model?.trim()) delete next.model;
  else next.model = next.model.trim();
  if (!next.fallback_models || next.fallback_models.length === 0) delete next.fallback_models;
  else {
    const fallbackModels = next.fallback_models.map((item) => item.trim()).filter(Boolean);
    if (fallbackModels.length > 0) next.fallback_models = fallbackModels;
    else delete next.fallback_models;
  }
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

async function readPromptDrafts(config: AppConfig): Promise<Record<string, PromptDraft>> {
  const agents = config.agents || [];
  const entries = await Promise.all(
    agents.map(async (agent) => {
      if (!agent.name) {
        return ['', { content: '', originalContent: '', error: 'Agent 名称为空' }] as const;
      }
      try {
        const prompt = await fetchAgentPrompt(agent.name);
        return [
          agent.name,
          {
            path: prompt.path,
            sourcePath: prompt.source_path,
            content: prompt.content,
            originalContent: prompt.content,
          },
        ] as const;
      } catch (err: unknown) {
        return [
          agent.name,
          {
            path: agent.prompt,
            content: '',
            originalContent: '',
            error: err instanceof Error ? err.message : 'Prompt 读取失败',
          },
        ] as const;
      }
    }),
  );
  return Object.fromEntries(entries.filter(([name]) => Boolean(name)));
}

function runtimeFromCandidate(candidate: RuntimeCandidate): RuntimeConfig {
  return {
    name: candidate.name,
    cli: candidate.cli,
    args: candidate.args,
    prompt_mode: candidate.prompt_mode,
    model_arg_style: candidate.model_arg_style,
  };
}

function candidateStatus(candidate: RuntimeCandidate): string {
  if (!candidate.available) return '未安装';
  if (!candidate.supported) return candidate.unsupported_reason || '暂未支持';
  return '可添加';
}

export function Settings() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [draftConfig, setDraftConfig] = useState<AppConfig | null>(null);
  const [runtimeCatalog, setRuntimeCatalog] = useState<RuntimeCatalogResponse | null>(null);
  const [agentPrompts, setAgentPrompts] = useState<Record<string, PromptDraft>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [activeSection, setActiveSection] = useState<SettingsSection>('runtimes');
  const [selectedCandidateId, setSelectedCandidateId] = useState('');

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [settingsResult, catalogResult] = await Promise.all([
        fetchSettings(),
        fetchRuntimeCatalog(),
      ]);
      const normalized = normalizeConfig(settingsResult.config);
      const prompts = await readPromptDrafts(normalized);
      setSettings(settingsResult);
      setRuntimeCatalog(catalogResult);
      setDraftConfig(normalized);
      setAgentPrompts(prompts);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
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
  const runtimeCandidates = runtimeCatalog?.candidates || [];
  const addableRuntimeCandidates = useMemo(
    () => runtimeCandidates.filter((candidate) => !runtimes[candidate.id]),
    [runtimeCandidates, runtimes],
  );

  useEffect(() => {
    if (addableRuntimeCandidates.length === 0) {
      setSelectedCandidateId('');
      return;
    }
    if (!selectedCandidateId || !addableRuntimeCandidates.some((candidate) => candidate.id === selectedCandidateId)) {
      setSelectedCandidateId(addableRuntimeCandidates[0].id);
    }
  }, [addableRuntimeCandidates, selectedCandidateId]);

  function updateDraft(section: Partial<AppConfig>) {
    setDraftConfig((current) => ({ ...(current || {}), ...section }));
    setSaveMessage('');
  }

  function updateRuntime(id: string, value: RuntimeConfig) {
    updateDraft({ runtimes: { ...runtimes, [id]: value } });
  }

  function addRuntimeFromCandidate() {
    const candidate = runtimeCandidates.find((item) => item.id === selectedCandidateId);
    if (!candidate) {
      setSaveMessage('请选择 Runtime');
      return;
    }
    if (!candidate.available || !candidate.supported) {
      setSaveMessage(`Runtime ${candidate.name} 当前不能添加：${candidateStatus(candidate)}`);
      return;
    }
    if (runtimes[candidate.id]) {
      setSaveMessage(`Runtime ${candidate.name} 已存在`);
      return;
    }
    updateDraft({
      runtimes: {
        ...runtimes,
        [candidate.id]: runtimeFromCandidate(candidate),
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

  function updateAgentName(index: number, name: string) {
    const previousName = agents[index]?.name;
    updateAgent(index, { name });
    setAgentPrompts((current) => {
      if (!previousName || !name.trim() || previousName === name || !current[previousName] || current[name]) return current;
      const next = { ...current, [name]: current[previousName] };
      delete next[previousName];
      return next;
    });
  }

  function updatePromptDraft(agentName: string, content: string) {
    if (!agentName.trim()) return;
    setAgentPrompts((current) => {
      const existing = current[agentName] || { content: '', originalContent: '' };
      return {
        ...current,
        [agentName]: {
          ...existing,
          content,
          error: undefined,
        },
      };
    });
    setSaveMessage('');
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
      const normalized = normalizeConfig(result.config);
      const [catalog, prompts] = await Promise.all([
        fetchRuntimeCatalog(),
        readPromptDrafts(normalized),
      ]);
      setSettings({ ...result, warnings: result.warnings || [] });
      setRuntimeCatalog(catalog);
      setDraftConfig(normalized);
      setAgentPrompts(prompts);
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
      const cleanedAgents = agents.map((agent) => {
        const next: AgentConfig = {
          name: agent.name.trim(),
          runtime_id: agent.runtime_id.trim(),
        };
        if (agent.role?.trim()) next.role = agent.role.trim();
        if (agent.prompt?.trim()) next.prompt = agent.prompt.trim();
        if (agent.timeout !== undefined) next.timeout = agent.timeout;
        return next;
      });
      const promptUpdates = cleanedAgents
        .map((agent) => ({ agent, prompt: agentPrompts[agent.name] }))
        .filter(({ prompt }) => prompt && prompt.content !== prompt.originalContent)
        .map(({ agent, prompt }) => ({ agentName: agent.name, content: prompt!.content }));
      const payload = sanitizeEnvPlaceholders({
        ...draftConfig,
        runtimes: cleanedRuntimes,
        agents: cleanedAgents,
      }) as AppConfig;
      const result = await updateSettings(payload);
      await Promise.all(promptUpdates.map((item) => updateAgentPrompt(item.agentName, item.content)));
      const normalized = normalizeConfig(result.config);
      const [catalog, prompts] = await Promise.all([
        fetchRuntimeCatalog(),
        readPromptDrafts(normalized),
      ]);
      setSettings(result);
      setRuntimeCatalog(catalog);
      setDraftConfig(normalized);
      setAgentPrompts(prompts);
      setSaveMessage(promptUpdates.length > 0 ? '设置和 Prompt 已保存' : '设置已保存');
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

  const selectedCandidate = runtimeCandidates.find((candidate) => candidate.id === selectedCandidateId);
  const canAddSelectedCandidate = Boolean(
    selectedCandidate && selectedCandidate.available && selectedCandidate.supported && !runtimes[selectedCandidate.id],
  );
  const warnings = settings.warnings || [];

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

      {saveMessage && <div className={`saveBanner ${saveMessage.includes('失败') || saveMessage.includes('不能') || saveMessage.includes('缺少') ? 'saveBannerError' : ''}`}>{saveMessage}</div>}
      {warnings.length > 0 && (
        <div className="saveBanner saveBannerError" style={{ marginBottom: 18 }}>
          {warnings.map((warning, i) => <p key={i}>{warning}</p>)}
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
                <div className="runtimeAddRow">
                  <select value={selectedCandidateId} onChange={(e) => setSelectedCandidateId(e.target.value)}>
                    {addableRuntimeCandidates.length === 0 && <option value="">没有可添加 Runtime</option>}
                    {addableRuntimeCandidates.map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.name} · {candidateStatus(candidate)}
                      </option>
                    ))}
                  </select>
                  <button className="button" onClick={addRuntimeFromCandidate} disabled={!canAddSelectedCandidate}>
                    <Plus size={14} /> 添加 Runtime
                  </button>
                </div>
              </div>
              {selectedCandidate && (!selectedCandidate.available || !selectedCandidate.supported) && (
                <div className="settingsMetaLine" style={{ marginBottom: 12 }}>
                  {selectedCandidate.name}: {candidateStatus(selectedCandidate)}
                </div>
              )}
              <div className="settingsCards">
                {Object.entries(runtimes).map(([id, runtime]) => {
                  const candidateRuntime = runtimeCandidates.find((candidate) => candidate.id === id);
                  const displayRuntime = { ...(candidateRuntime || {}), ...(runtimeCatalog?.runtimes?.[id] || {}), ...runtime };
                  return (
                    <div className="settingsEditCard" key={id}>
                      <div className="settingsCardHeader">
                        <div>
                          <strong>{runtime.name || displayRuntime.name || id}</strong>
                          <div className="settingsMetaLine settingsMetaInline">
                            id: {id} · cli: {displayRuntime.cli || runtime.cli}
                          </div>
                        </div>
                        <button className="iconButton danger" onClick={() => removeRuntime(id)} aria-label="删除 Runtime">
                          <Trash2 size={14} />
                        </button>
                      </div>
                      <div className="settingsFormGrid">
                        <label>
                          Name
                          <input value={runtime.name || ''} onChange={(e) => updateRuntime(id, { ...runtime, name: e.target.value })} />
                        </label>
                        <label>
                          CLI
                          <input value={runtime.cli || ''} readOnly className="settingsReadOnlyInput" />
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
                          Model Override
                          <input
                            value={runtime.model || runtime.default_model || ''}
                            placeholder={displayRuntime.model ? `CLI 当前配置: ${displayRuntime.model}` : '留空时使用 CLI 当前配置'}
                            onChange={(e) => updateRuntime(id, { ...runtime, model: e.target.value, default_model: undefined })}
                          />
                        </label>
                        <label>
                          Fallback Models
                          <input value={splitList(runtime.fallback_models)} onChange={(e) => updateRuntime(id, { ...runtime, fallback_models: parseList(e.target.value) })} />
                        </label>
                      </div>
                      <div className="runtimeMetaGrid">
                        <span>available: {displayRuntime.available === undefined ? '-' : displayRuntime.available ? 'true' : 'false'}</span>
                        <span>supported: {displayRuntime.supported === undefined ? '-' : displayRuntime.supported ? 'true' : 'false'}</span>
                        {displayRuntime.model && <span>detected model: {displayRuntime.model}</span>}
                        {displayRuntime.version && <span>version: {displayRuntime.version}</span>}
                        {displayRuntime.path && <span className="settingsWideMeta">path: {displayRuntime.path}</span>}
                        {displayRuntime.unsupported_reason && <span className="settingsWideMeta">reason: {displayRuntime.unsupported_reason}</span>}
                      </div>
                      {runtime.env && <div className="settingsMetaLine">env: {Object.keys(runtime.env).length} 个变量，保存时会跳过值为 *** 的字段</div>}
                    </div>
                  );
                })}
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
                {agents.map((agent, index) => {
                  const promptDraft = agentPrompts[agent.name];
                  return (
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
                          <input value={agent.name} onChange={(e) => updateAgentName(index, e.target.value)} />
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
                        <label className="settingsWideField">
                          Role
                          <input value={agent.role || ''} onChange={(e) => updateAgent(index, { role: e.target.value })} />
                        </label>
                        <label className="settingsWideField">
                          Prompt
                          <textarea
                            value={promptDraft?.content || ''}
                            onChange={(e) => updatePromptDraft(agent.name, e.target.value)}
                            placeholder={promptDraft?.error || 'Prompt 文档内容'}
                          />
                        </label>
                      </div>
                      <div className={`settingsMetaLine ${promptDraft?.error ? 'settingsMetaError' : ''}`}>
                        Prompt file: {promptDraft?.path || agent.prompt || '.ai/agents/<agent>.md'}
                        {promptDraft?.sourcePath && promptDraft.sourcePath !== promptDraft.path ? ` · source: ${promptDraft.sourcePath}` : ''}
                        {promptDraft?.error ? ` · ${promptDraft.error}` : ''}
                      </div>
                    </div>
                  );
                })}
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
        </section>
      </div>
    </div>
  );
}
