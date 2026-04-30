import { AlertTriangle, Bot, Cpu, FileText, GitBranch, Loader2, Play, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
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

type ConfigItemMeta = {
  key: string;
  label: string;
  description: string;
  group?: string;
};

const RUNNER_CONFIG_META: ConfigItemMeta[] = [
  {
    key: 'auto_split_requirements', label: '自动拆分需求', group: '需求拆分',
    description: '开启后，当需求上下文超过阈值时自动拆分为多个子任务，避免单次执行超出上下文窗口',
  },
  {
    key: 'context_threshold_chars', label: '上下文阈值', group: '需求拆分',
    description: '触发自动拆分的字符数阈值，也用于决定串行 / 并行执行策略',
  },
  {
    key: 'agent_timeout_seconds', label: 'Agent 超时', group: '运行控制',
    description: 'Agent 单次执行的最大时间，默认 1800 秒（30 分钟），超时后强制终止进程',
  },
  {
    key: 'heartbeat_seconds', label: '心跳间隔', group: '运行控制',
    description: '定时发射心跳事件的间隔（秒），用于前端展示 Agent 仍在运行中',
  },
  {
    key: 'stop_parallel_on_first_error', label: '遇错即停', group: '运行控制',
    description: '并行执行时，任意 Agent 失败则立即停止其他正在运行的 Agent，防止错误扩散',
  },
  {
    key: 'parallel_log_mode', label: '并行日志模式', group: '运行控制',
    description: '并行执行时日志输出方式：interleaved 交错输出便于实时查看各 Agent 进度',
  },
  {
    key: 'production_mode', label: '生产模式', group: '安全校验',
    description: '启用后会激活严格校验（强制 worktree、强制 verify 命令），确保生产环境代码安全',
  },
  {
    key: 'require_worktree', label: '强制 Worktree', group: '安全校验',
    description: '生产模式下强制要求启用 worktree 隔离，未启用则拒绝执行 pipeline',
  },
  {
    key: 'require_verify_cmd', label: '强制验证命令', group: '安全校验',
    description: '生产模式下强制要求配置 quality_gates 验证命令，确保交付代码质量',
  },
  {
    key: 'max_input_chars_per_file', label: '文件输入上限', group: '上下文控制',
    description: '单个输入文件传给 Agent 的最大字符数，防止过大文件导致 token 过度消耗',
  },
  {
    key: 'max_loopback_feedback_chars', label: '反馈长度上限', group: '上下文控制',
    description: 'QA / Reviewer 反馈给 Developer 的最大字符数，超出部分按 truncate 策略截断',
  },
  {
    key: 'loopback_truncate_strategy', label: '截断策略', group: '上下文控制',
    description: '反馈超长时的截断方式：smart 智能截取关键部分、head 保留头部、tail 保留尾部',
  },
];

const WORKTREE_CONFIG_META: ConfigItemMeta[] = [
  {
    key: 'enabled', label: '启用隔离',
    description: '每次 pipeline run 在 .ai/worktrees/<run-id>/ 创建独立 Git 工作目录和分支，确保多 Agent 并行时代码互不冲突',
  },
  {
    key: 'base_branch', label: '基准分支',
    description: '新建 worktree 基于此分支的最新提交作为起点，默认 main',
  },
  {
    key: 'merge_strategy', label: '合并策略',
    description: 'pipeline 全部通过后的合并方式：squash 将所有提交压缩为一个干净提交、merge-commit 保留完整历史',
  },
  {
    key: 'auto_cleanup', label: '自动清理',
    description: 'pipeline 完成后（无论成功或失败）自动删除 worktree 目录和对应的 Git 分支',
  },
  {
    key: 'merge_on_conflict', label: '冲突处理',
    description: '合并回主分支发生冲突时的策略：pause 暂停等待人工介入解决、abort 直接终止并标记失败',
  },
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
  const {
    available: _available,
    configured: _configured,
    default_model: legacyDefaultModel,
    fallback_models: _fallbackModels,
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

function formatConfigValue(key: string, value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span style={{ color: 'var(--text-muted)' }}>未设置</span>;
  if (typeof value === 'boolean') {
    return value
      ? <span className="configValueBadge configValueBadgeOn">启用</span>
      : <span className="configValueBadge configValueBadgeOff">关闭</span>;
  }
  if (typeof value === 'number') {
    const label = key.includes('seconds') ? `${value} 秒` : key.includes('chars') ? `${value.toLocaleString()} 字符` : String(value);
    return <span className="configValueNumber">{label}</span>;
  }
  const str = String(value);
  return <span className="configValueText">{str || <span style={{ color: 'var(--text-muted)' }}>—</span>}</span>;
}

function groupBy<T>(items: T[], fn: (item: T) => string): Record<string, T[]> {
  const groups: Record<string, T[]> = {};
  for (const item of items) {
    const key = fn(item);
    if (!groups[key]) groups[key] = [];
    groups[key].push(item);
  }
  return groups;
}

function renderConfigSection(
  title: string,
  subtitle: string,
  icon: React.ReactNode,
  config: Record<string, unknown>,
  meta: ConfigItemMeta[],
): React.ReactNode {
  const groups = groupBy(meta, (m) => m.group || '');
  const total = meta.length;

  return (
    <div className="settingGroup">
      <div className="configSectionHeader">
        <h2>{icon} {title}<span className="configItemCount">{total} 项配置</span></h2>
        <p className="configSectionSubtitle">{subtitle}</p>
      </div>
      {Object.entries(groups).map(([group, items]) => (
        <div key={group} className="configGroup">
          {group && <h3 className="configGroupTitle">{group}</h3>}
          <div className="configDescriptiveTable">
            {items.map((item) => {
              const value = config[item.key];
              return (
                <div key={item.key} className="configDescriptiveRow">
                  <div className="configDescriptiveTop">
                    <div className="configDescriptiveKey">
                      <code>{item.key}</code>
                      <span className="configDescriptiveLabel">{item.label}</span>
                    </div>
                    <div className="configDescriptiveValue">{formatConfigValue(item.key, value)}</div>
                  </div>
                  <p className="configDescriptiveDesc">{item.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
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
  const [activeAgentTab, setActiveAgentTab] = useState(0);

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
    const runtimeName = runtimes[id]?.name || id;
    const affectedAgents = agents.filter((agent) => agent.runtime_id === id);
    const msg = affectedAgents.length > 0
      ? `确定删除 Runtime「${runtimeName}」？\n${affectedAgents.length} 个 Agent 将被迁移到其他 Runtime。`
      : `确定删除 Runtime「${runtimeName}」？`;
    if (!window.confirm(msg)) return;
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
    const agentName = agents[index]?.name || `Agent ${index + 1}`;
    if (!window.confirm(`确定删除 Agent「${agentName}」？\n删除后需保存才会生效。`)) return;
    updateDraft({ agents: agents.filter((_, i) => i !== index) });
  }

  async function handleReset() {
    if (!window.confirm('确定重置为默认配置？\n当前所有自定义设置将被删除，此操作不可撤销。')) return;
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
              <div className="configSectionHeader">
                <h2><Cpu size={18} /> Runtimes<span className="configItemCount">{Object.keys(runtimes).length} 个 Runtime</span></h2>
                <p className="configSectionSubtitle">管理 AI Agent 的命令行运行时环境，配置 CLI 路径、模型覆盖及环境变量。</p>
              </div>
              <div className="settingsSectionHeader">
                <div></div>
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
                        <div className="settingsCardTitleGroup">
                          <strong className="settingsCardTitle">{runtime.name || displayRuntime.name || id}</strong>
                          {displayRuntime.version && <span className="settingsCardSubtitle">{displayRuntime.cli || runtime.cli} · v{displayRuntime.version}</span>}
                          {!displayRuntime.version && <span className="settingsCardSubtitle">{displayRuntime.cli || runtime.cli}</span>}
                        </div>
                        <div className="settingsCardActions">
                          <span className={`metaTag ${displayRuntime.available === false ? 'metaTagRed' : 'metaTagGreen'}`}>
                            {displayRuntime.available === false ? '不可用' : '可用'}
                          </span>
                          <button className="iconButton danger" onClick={() => removeRuntime(id)} aria-label="删除 Runtime">
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                      <div className="settingsFormGrid settingsFormGrid3Col">
                        <label>
                          Name
                          <input value={runtime.name || ''} onChange={(e) => updateRuntime(id, { ...runtime, name: e.target.value })} />
                        </label>
                        <label>
                          CLI
                          <div className="settingsReadOnlyField">
                            <span className="settingsReadOnlyLabel">自动检测</span>
                            <input value={displayRuntime.cli || runtime.cli || ''} readOnly className="settingsReadOnlyInput" />
                          </div>
                        </label>
                        <label>
                          Model Override
                          <input
                            value={runtime.model || runtime.default_model || ''}
                            placeholder={displayRuntime.model ? `CLI 当前配置: ${displayRuntime.model}` : '留空时使用 CLI 当前配置'}
                            onChange={(e) => updateRuntime(id, { ...runtime, model: e.target.value, default_model: undefined })}
                          />
                        </label>
                      </div>
                      {displayRuntime.model && (
                        <div className="settingsMetaLine settingsMetaInline" style={{ justifyContent: 'flex-start' }}>
                          <span className="metaTag">{displayRuntime.model}</span>
                        </div>
                      )}
                      {runtime.env && (
                        <div className="settingsEnvInfo">
                          <span className="settingsEnvCount">{Object.keys(runtime.env).length}</span> 个环境变量
                          <span className="settingsEnvHint">保存时跳过值为 *** 的字段</span>
                        </div>
                      )}
                    </div>
                  );
                })}
                {Object.keys(runtimes).length === 0 && <div className="emptyState">暂无 Runtime 配置</div>}
              </div>
            </div>
          )}

          {activeSection === 'agents' && (
            <div className="settingGroup">
              <div className="configSectionHeader">
                <h2><Bot size={18} /> Agents<span className="configItemCount">{agents.length} 个 Agent</span></h2>
                <p className="configSectionSubtitle">管理 AI 协作团队中的 Agent 成员，配置其职责角色、行为准则和能力边界。</p>
              </div>
              <div className="settingsSectionHeader">
                <div></div>
                <button className="button" onClick={() => { addAgent(); setActiveAgentTab(agents.length); }}><Plus size={14} /> 新增 Agent</button>
              </div>
              {agents.length > 0 && (
                <>
                  <div className="agentTabs">
                    {agents.map((agent, index) => {
                      const runtime = runtimes[agent.runtime_id];
                      return (
                        <button
                          key={`${agent.name}-${index}`}
                          type="button"
                          className={`agentTab ${activeAgentTab === index ? 'agentTabActive' : ''}`}
                          onClick={() => setActiveAgentTab(index)}
                        >
                          <span className="agentTabName">{agent.name || `Agent ${index + 1}`}</span>
                          {runtime && <span className="agentTabRuntime">{runtime.name}</span>}
                          <span
                            className="agentTabClose"
                            role="button"
                            tabIndex={0}
                            onClick={(e) => { e.stopPropagation(); removeAgent(index); setActiveAgentTab(Math.max(0, Math.min(activeAgentTab, agents.length - 2))); }}
                          >
                            &times;
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  {agents[activeAgentTab] && (() => {
                    const agent = agents[activeAgentTab];
                    const promptDraft = agentPrompts[agent.name];
                    const runtime = runtimes[agent.runtime_id];
                    return (
                      <div className="settingsEditCard" key={`${agent.name}-${activeAgentTab}`}>
                        <div className="settingsCardHeader">
                          <div className="settingsCardTitleGroup">
                            <strong className="settingsCardTitle">{agent.name}</strong>
                            {runtime && <span className="settingsCardSubtitle">{runtime.name}</span>}
                          </div>
                          <div className="settingsCardActions">
                            {agent.role && <span className="metaTag metaTagAccent">{agent.role}</span>}
                          </div>
                        </div>
                        <div className="settingsFormGrid">
                          <label>
                            Name
                            <input value={agent.name} onChange={(e) => updateAgentName(activeAgentTab, e.target.value)} />
                          </label>
                          <label>
                            Runtime
                            <select className="agentRuntimeSelect" value={agent.runtime_id} onChange={(e) => updateAgent(activeAgentTab, { runtime_id: e.target.value })}>
                              <option value="">选择 Runtime</option>
                              {runtimeIds.map((runtimeId) => (
                                <option key={runtimeId} value={runtimeId}>{runtimes[runtimeId]?.name || runtimeId}</option>
                              ))}
                            </select>
                          </label>
                          <label className="settingsWideField">
                            Role
                            <input
                              value={agent.role || ''}
                              onChange={(e) => updateAgent(activeAgentTab, { role: e.target.value })}
                              placeholder="如：summarizer、developer、reviewer 等"
                            />
                            <span className="settingsFieldHint">Agent 在协作流程中的职责定位，如 summarizer（总结者）、developer（开发者）</span>
                          </label>
                          <label className="settingsWideField">
                            Soul
                            <textarea
                              className="agentSoulTextarea"
                              value={promptDraft?.content || ''}
                              onChange={(e) => updatePromptDraft(agent.name, e.target.value)}
                              placeholder={promptDraft?.error || '定义 Agent 的行为准则、能力和人格...'}
                            />
                            <span className="settingsFieldHint">
                              {promptDraft?.content ? `${promptDraft.content.split('\n').length} 行 · ${promptDraft.content.length} 字符` : '定义 Agent 的行为准则、能力和人格'}
                            </span>
                          </label>
                        </div>
                        {promptDraft?.error && <div className="settingsMetaLine settingsMetaError">{promptDraft.error}</div>}
                      </div>
                    );
                  })()}
                </>
              )}
              {agents.length === 0 && (
                <div className="emptyState">
                  <Bot size={32} style={{ color: 'var(--text-muted)', marginBottom: 8 }} />
                  <p>暂无 Agent 配置</p>
                  <p className="settingsFieldHint">点击「新增 Agent」创建第一个 AI 团队成员</p>
                </div>
              )}
            </div>
          )}

          {activeSection === 'runner' && renderConfigSection(
            'Runner',
            '控制 AI Agent 的执行行为，包括超时、并发、上下文拆分及生产模式校验等运行时参数。',
            <Play size={18} />,
            (draftConfig.runner || {}) as Record<string, unknown>,
            RUNNER_CONFIG_META,
          )}

          {activeSection === 'worktree' && renderConfigSection(
            'Worktree',
            '基于 git worktree 为每次 pipeline run 创建代码隔离环境，确保并行安全且主分支不被污染。',
            <GitBranch size={18} />,
            (draftConfig.worktree || {}) as Record<string, unknown>,
            WORKTREE_CONFIG_META,
          )}
        </section>
      </div>
    </div>
  );
}
