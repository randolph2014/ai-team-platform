import type {
  AgentPromptResponse,
  AppConfig,
  Pipeline,
  PipelineTemplate,
  RunListItem,
  RunReport,
  RuntimeCatalogResponse,
  SettingsResponse,
  Webhook,
} from './types';

const API_BASE = '/api';
const TOKEN_KEY = 'ai-team.token';
const RUN_WORKDIR_KEY = 'ai-team.runWorkdirs';
const LAST_WORKDIR_KEY = 'ai-team.lastWorkdir';

// --- Auth ---

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

export async function login(apiKey: string): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/login?api_key=${encodeURIComponent(apiKey)}`, {
    method: 'POST',
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '登录失败' }));
    throw new Error(body.detail || `登录失败: ${response.status}`);
  }
  const data: { access_token: string; token_type: string } = await response.json();
  setToken(data.access_token);
  return data.access_token;
}

export async function checkAuthStatus(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/auth/status`);
    if (!response.ok) return true;
    const data: { auth_enabled: boolean } = await response.json();
    return data.auth_enabled;
  } catch {
    return true;
  }
}

// --- Core fetch with auth ---

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (init?.headers) {
    if (init.headers instanceof Headers) {
      init.headers.forEach((v, k) => { headers[k] = v; });
    } else if (Array.isArray(init.headers)) {
      for (const [k, v] of init.headers) { headers[k] = v; }
    } else {
      Object.assign(headers, init.headers);
    }
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent('auth:expired'));
    throw new Error('认证已过期，请重新登录');
  }
  return response;
}

// --- Workdir helpers ---

function readJsonMap(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(RUN_WORKDIR_KEY) || '{}') as Record<string, string>;
  } catch {
    return {};
  }
}

export function rememberRunWorkdir(runId: string, workdir: string) {
  const map = readJsonMap();
  map[runId] = workdir;
  localStorage.setItem(RUN_WORKDIR_KEY, JSON.stringify(map));
  localStorage.setItem(LAST_WORKDIR_KEY, workdir);
}

export function rememberedWorkdir(runId?: string): string {
  if (runId) {
    const map = readJsonMap();
    if (map[runId]) return map[runId];
  }
  return localStorage.getItem(LAST_WORKDIR_KEY) || '';
}

export function runQuery(workdir: string): string {
  return workdir ? `?workdir=${encodeURIComponent(workdir)}` : '';
}

// --- Runs ---

export async function fetchRuns(workdir?: string): Promise<RunListItem[]> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/runs${runQuery(wd)}`);
  if (!response.ok) throw new Error(`获取运行列表失败: ${response.status}`);
  return response.json();
}

export async function fetchRun(runId: string, workdir?: string): Promise<RunReport> {
  const wd = workdir || rememberedWorkdir(runId);
  const response = await apiFetch(`/runs/${runId}${runQuery(wd)}`);
  if (!response.ok) throw new Error(`获取运行详情失败: ${response.status}`);
  return response.json();
}

export function runWebSocketUrl(runId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = getToken();
  const base = `${protocol}//${window.location.host}/ws/runs/${runId}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export async function createRun(workdir: string, requirement: string, configPath?: string): Promise<{ run_id: string; status: string }> {
  const response = await apiFetch('/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workdir, requirement, yes: false, config_path: configPath }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `创建运行失败: ${response.status}`);
  }
  return response.json();
}

export async function resumeRun(runId: string, workdir: string, yes: boolean, reject: boolean = false): Promise<{ run_id: string; status: string; output_dir: string }> {
  const params = new URLSearchParams({ workdir, yes: String(yes) });
  if (reject) params.set('reject', 'true');
  const response = await apiFetch(`/runs/${runId}/resume?${params.toString()}`, { method: 'POST' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to resume' }));
    throw new Error(error.detail || `恢复运行失败: ${response.status}`);
  }
  return response.json();
}

// --- Settings ---

export async function fetchSettings(workdir?: string): Promise<SettingsResponse> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/settings${runQuery(wd)}`);
  if (!response.ok) throw new Error(`获取设置失败: ${response.status}`);
  return response.json();
}

export async function updateSettings(config: AppConfig, workdir?: string): Promise<SettingsResponse> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/settings${runQuery(wd)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!response.ok) throw new Error(`保存设置失败: ${response.status}`);
  return response.json();
}

export async function resetSettings(workdir?: string): Promise<SettingsResponse> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/settings/reset${runQuery(wd)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new Error(`重置设置失败: ${response.status}`);
  return response.json();
}

export async function fetchRuntimeCatalog(workdir?: string): Promise<RuntimeCatalogResponse> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/config/runtimes${runQuery(wd)}`);
  if (!response.ok) throw new Error(`获取 Runtime 列表失败: ${response.status}`);
  return response.json();
}

export async function fetchAgentPrompt(agentName: string, workdir?: string): Promise<AgentPromptResponse> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/settings/agents/${encodeURIComponent(agentName)}/prompt${runQuery(wd)}`);
  if (!response.ok) throw new Error(`读取 Prompt 失败: ${response.status}`);
  return response.json();
}

export async function updateAgentPrompt(agentName: string, content: string, workdir?: string): Promise<AgentPromptResponse> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/settings/agents/${encodeURIComponent(agentName)}/prompt${runQuery(wd)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw new Error(`保存 Prompt 失败: ${response.status}`);
  return response.json();
}

// --- Pipelines ---

export async function fetchPipelines(workdir?: string): Promise<Pipeline[]> {
  const wd = workdir || rememberedWorkdir();
  const response = await apiFetch(`/pipelines${runQuery(wd)}`);
  if (!response.ok) throw new Error(`获取 Pipeline 列表失败: ${response.status}`);
  return response.json();
}

export async function fetchPipelineTemplates(): Promise<PipelineTemplate[]> {
  const response = await apiFetch('/pipelines/templates');
  if (!response.ok) throw new Error(`获取模板列表失败: ${response.status}`);
  return response.json();
}

export async function fetchPipeline(id: string): Promise<Pipeline> {
  const response = await apiFetch(`/pipelines/${id}`);
  if (!response.ok) throw new Error(`获取 Pipeline 失败: ${response.status}`);
  return response.json();
}

export async function createPipeline(pipeline: { id: string; name: string; description: string; yaml_config: Record<string, unknown> }): Promise<Pipeline> {
  const response = await apiFetch('/pipelines', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(pipeline),
  });
  if (!response.ok) throw new Error(`创建 Pipeline 失败: ${response.status}`);
  return response.json();
}

export async function updatePipeline(id: string, pipeline: Partial<Pipeline>): Promise<Pipeline> {
  const response = await apiFetch(`/pipelines/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(pipeline),
  });
  if (!response.ok) throw new Error(`更新 Pipeline 失败: ${response.status}`);
  return response.json();
}

export async function deletePipeline(id: string): Promise<void> {
  const response = await apiFetch(`/pipelines/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error(`删除 Pipeline 失败: ${response.status}`);
}

// --- Config ---

export async function validateConfig(workdir: string): Promise<{ valid: boolean; warnings: string[]; errors: string[] }> {
  const response = await apiFetch(`/config/validate${runQuery(workdir)}`);
  if (!response.ok) throw new Error(`验证配置失败: ${response.status}`);
  return response.json();
}

// --- Costs ---

export async function fetchRunCosts(runId: string): Promise<{ run_id: string; records: Array<{ agent_name: string; model: string; prompt_tokens: number; completion_tokens: number; estimated_cost: number; stage_id: string; timestamp: string }>; count: number; total_tokens: number; total_cost: number }> {
  const response = await apiFetch(`/costs?run_id=${runId}`);
  if (!response.ok) throw new Error(`获取成本数据失败: ${response.status}`);
  return response.json();
}

export async function fetchCostSummary(period: string = 'daily'): Promise<{ period: string; runs: string[]; run_count: number; total_calls: number; total_tokens: number; total_cost: number; by_model: Record<string, { prompt_tokens: number; completion_tokens: number; estimated_cost: number; calls: number }> }> {
  const response = await apiFetch(`/costs/summary?period=${period}`);
  if (!response.ok) throw new Error(`获取成本摘要失败: ${response.status}`);
  return response.json();
}

// --- Webhooks ---

export async function fetchWebhooks(): Promise<Webhook[]> {
  const response = await apiFetch('/webhooks');
  if (!response.ok) throw new Error(`获取 Webhook 列表失败: ${response.status}`);
  return response.json();
}

export async function fetchWebhook(id: string): Promise<Webhook> {
  const response = await apiFetch(`/webhooks/${id}`);
  if (!response.ok) throw new Error(`获取 Webhook 失败: ${response.status}`);
  return response.json();
}

export async function createWebhook(webhook: { url: string; secret: string; events: string[]; pipeline_id?: string }): Promise<Webhook> {
  const response = await apiFetch('/webhooks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(webhook),
  });
  if (!response.ok) throw new Error(`创建 Webhook 失败: ${response.status}`);
  return response.json();
}

export async function deleteWebhook(id: string): Promise<void> {
  const response = await apiFetch(`/webhooks/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error(`删除 Webhook 失败: ${response.status}`);
}
