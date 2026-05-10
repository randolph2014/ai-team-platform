import type {
  AgentPromptResponse,
  AppConfig,
  HarnessBundle,
  HarnessConflictPayload,
  HarnessFile,
  HarnessValidationResult,
  HumanDecision,
  Pipeline,
  PipelineTemplate,
  RunListItem,
  RunListResponse,
  RunReport,
  RuntimeCatalogResponse,
  SettingsResponse,
  TaskBoardEventRequest,
  TaskBoardResponse,
  Webhook,
} from './types';
import { normalizeHarnessFiles } from './harnessSchema';

const API_BASE = '/api';
const TOKEN_KEY = 'ai-team.token';
const RUN_WORKDIR_KEY = 'ai-team.runWorkdirs';
const LAST_WORKDIR_KEY = 'ai-team.lastWorkdir';

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

async function responseError(response: Response, fallback: string): Promise<ApiError> {
  const body = await response.json().catch(() => null);
  const detail = body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: unknown }).detail) : '';
  const message = detail || fallback;
  return new ApiError(message, response.status, body);
}

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
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
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

export type ProjectQueryOptions = {
  projectId?: string;
  workdir?: string;
};

export function projectQuery(options?: ProjectQueryOptions): string {
  const params = new URLSearchParams();
  if (options?.projectId) {
    params.set('project_id', options.projectId);
  } else if (options?.workdir) {
    params.set('workdir', options.workdir);
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

function normalizeRunQuery(input?: string | ProjectQueryOptions): ProjectQueryOptions {
  if (!input) return {};
  if (typeof input === 'string') return { workdir: input };
  return input;
}

// --- Runs ---

export async function fetchRuns(workdir?: string, params?: { page?: number; size?: number; status?: string }): Promise<RunListResponse> {
  const wd = workdir || rememberedWorkdir();
  const searchParams = new URLSearchParams();
  if (wd) searchParams.set('workdir', wd);
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.size) searchParams.set('size', String(params.size));
  if (params?.status) searchParams.set('status', params.status);
  const qs = searchParams.toString();
  const response = await apiFetch(`/runs${qs ? `?${qs}` : ''}`);
  if (!response.ok) throw new Error(`获取运行列表失败: ${response.status}`);
  const data = await response.json();
  if (Array.isArray(data)) {
    return { items: data, total: data.length, page: 1, size: data.length };
  }
  return data;
}

export async function fetchRun(runId: string, query?: string | ProjectQueryOptions): Promise<RunReport> {
  const normalized = normalizeRunQuery(query);
  const wd = normalized.projectId ? '' : (normalized.workdir || rememberedWorkdir(runId));
  const response = await apiFetch(`/runs/${runId}${projectQuery({ projectId: normalized.projectId, workdir: wd })}`);
  if (!response.ok) throw new Error(`获取运行详情失败: ${response.status}`);
  return response.json();
}

export async function fetchRunDiff(runId: string, query?: string | ProjectQueryOptions): Promise<{ run_id: string; diff: string; source: string }> {
  const normalized = normalizeRunQuery(query);
  const wd = normalized.projectId ? '' : (normalized.workdir || rememberedWorkdir(runId));
  const response = await apiFetch(`/runs/${runId}/diff${projectQuery({ projectId: normalized.projectId, workdir: wd })}`);
  if (!response.ok) throw new Error(`获取 diff 失败: ${response.status}`);
  return response.json();
}

export async function fetchRunArtifactText(runId: string, artifactName: string, query?: string | ProjectQueryOptions): Promise<string> {
  const normalized = normalizeRunQuery(query);
  const wd = normalized.projectId ? '' : (normalized.workdir || rememberedWorkdir(runId));
  const response = await apiFetch(`/runs/${runId}/artifacts/${encodeURIComponent(artifactName)}${projectQuery({ projectId: normalized.projectId, workdir: wd })}`);
  if (!response.ok) throw new Error(`加载产物失败: ${response.status}`);
  return response.text();
}

export function runWebSocketUrl(runId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = getToken();
  const base = `${protocol}//${window.location.host}/ws/runs/${runId}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export type CreateRunOptions = {
  config_path?: string;
  pipeline_id?: string;
  project_id?: string;
  execution_mode?: 'serial' | 'parallel' | 'auto' | string;
};

export async function createRun(
  workdir: string,
  requirement: string,
  options?: string | CreateRunOptions,
): Promise<{ run_id: string; status: string; project_root?: string; output_dir?: string }> {
  const extra: CreateRunOptions = typeof options === 'string' ? { config_path: options } : (options || {});
  const body: Record<string, unknown> = { requirement, yes: false, ...extra };
  if (extra.project_id) {
    body.project_id = extra.project_id;
  } else {
    body.workdir = workdir;
  }
  const response = await apiFetch('/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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

export async function submitHumanDecision(
  runId: string,
  workdir: string,
  decision: Pick<HumanDecision, 'stage_id' | 'decision' | 'reason' | 'required_changes' | 'target_stage'>,
): Promise<{ run_id: string; status: string; output_dir: string }> {
  const response = await apiFetch(`/runs/${runId}/human-decision${runQuery(workdir)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(decision),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '提交人工决策失败' }));
    throw new Error(error.detail || `提交人工决策失败: ${response.status}`);
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

// --- Harness ---

export async function fetchHarness(projectId: string): Promise<HarnessBundle> {
  const response = await apiFetch(`/projects/${encodeURIComponent(projectId)}/harness`);
  if (!response.ok) {
    throw await responseError(response, `获取 Harness 失败: ${response.status}`);
  }
  const data = await response.json() as HarnessBundle;
  return { ...data, files: normalizeHarnessFiles(data.files || []) };
}

export async function validateHarness(projectId: string, files: HarnessFile[]): Promise<HarnessValidationResult> {
  const response = await apiFetch(`/projects/${encodeURIComponent(projectId)}/harness/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ files }),
  });
  if (!response.ok) {
    const error = await responseError(response, `Harness schema validation failed: ${response.status}`);
    return { valid: false, errors: [error.message] };
  }
  return response.json();
}

export async function saveHarness(projectId: string, files: HarnessFile[], manifestHash: string): Promise<HarnessBundle> {
  const response = await apiFetch(`/projects/${encodeURIComponent(projectId)}/harness`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ manifest_hash: manifestHash, files }),
  });
  if (response.status === 409) {
    const conflict = await response.json() as HarnessConflictPayload;
    throw new ApiError('manifest_conflict', 409, conflict);
  }
  if (!response.ok) {
    throw await responseError(response, `保存 Harness 失败: ${response.status}`);
  }
  const data = await response.json() as HarnessBundle;
  return { ...data, files: normalizeHarnessFiles(data.files || []) };
}

export async function runHarnessChecks(projectId: string): Promise<Record<string, unknown>> {
  const response = await apiFetch(`/projects/${encodeURIComponent(projectId)}/harness/checks/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: `harness-ui-${Date.now()}` }),
  });
  if (!response.ok) throw await responseError(response, `运行 Harness checks 失败: ${response.status}`);
  return response.json();
}

export async function fetchTaskBoard(projectId: string, query?: string): Promise<TaskBoardResponse> {
  const qs = query ? `?q=${encodeURIComponent(query)}` : '';
  const response = await apiFetch(`/projects/${encodeURIComponent(projectId)}/task-board${qs}`);
  if (!response.ok) throw await responseError(response, `获取 Task Board 失败: ${response.status}`);
  return response.json();
}

export async function appendTaskBoardEvent(projectId: string, event: TaskBoardEventRequest): Promise<{ project_id: string; task: Record<string, unknown> }> {
  const response = await apiFetch(`/projects/${encodeURIComponent(projectId)}/task-board/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
  });
  if (!response.ok) throw await responseError(response, `写入 Task Board 事件失败: ${response.status}`);
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
