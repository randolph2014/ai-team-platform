import type { Pipeline, RunListItem, RunReport, Settings } from './types';

const RUN_WORKDIR_KEY = 'ai-team.runWorkdirs';
const LAST_WORKDIR_KEY = 'ai-team.lastWorkdir';

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

export async function fetchRuns(workdir?: string): Promise<RunListItem[]> {
  const wd = workdir || rememberedWorkdir();
  const response = await fetch(`/api/runs${runQuery(wd)}`);
  if (!response.ok) throw new Error(`Failed to fetch runs: ${response.status}`);
  return response.json();
}

export async function fetchRun(runId: string, workdir?: string): Promise<RunReport> {
  const wd = workdir || rememberedWorkdir(runId);
  const response = await fetch(`/api/runs/${runId}${runQuery(wd)}`);
  if (!response.ok) throw new Error(`Failed to fetch run: ${response.status}`);
  return response.json();
}

export function runWebSocketUrl(runId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/runs/${runId}`;
}

export async function createRun(workdir: string, requirement: string, configPath?: string): Promise<{ run_id: string; status: string }> {
  const response = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workdir, requirement, yes: false, config_path: configPath }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `Failed to create run: ${response.status}`);
  }
  return response.json();
}

export async function fetchSettings(workdir?: string): Promise<Settings> {
  const wd = workdir || rememberedWorkdir();
  const response = await fetch(`/api/settings${runQuery(wd)}`);
  if (!response.ok) throw new Error(`Failed to fetch settings: ${response.status}`);
  return response.json();
}

export async function updateSettings(settings: Partial<Settings>, workdir?: string): Promise<void> {
  const wd = workdir || rememberedWorkdir();
  const response = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workdir: wd, ...settings }),
  });
  if (!response.ok) throw new Error(`Failed to save settings: ${response.status}`);
}

export async function resetSettings(workdir?: string): Promise<void> {
  const wd = workdir || rememberedWorkdir();
  const response = await fetch('/api/settings/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workdir: wd }),
  });
  if (!response.ok) throw new Error(`Failed to reset settings: ${response.status}`);
}

export async function fetchPipelines(workdir?: string): Promise<Pipeline[]> {
  const wd = workdir || rememberedWorkdir();
  const response = await fetch(`/api/pipelines${runQuery(wd)}`);
  if (!response.ok) throw new Error(`Failed to fetch pipelines: ${response.status}`);
  return response.json();
}

export async function fetchPipeline(id: string): Promise<Pipeline> {
  const response = await fetch(`/api/pipelines/${id}`);
  if (!response.ok) throw new Error(`Failed to fetch pipeline: ${response.status}`);
  return response.json();
}

export async function createPipeline(pipeline: { name: string; description: string; yaml: string }): Promise<Pipeline> {
  const response = await fetch('/api/pipelines', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(pipeline),
  });
  if (!response.ok) throw new Error(`Failed to create pipeline: ${response.status}`);
  return response.json();
}

export async function updatePipeline(id: string, pipeline: Partial<Pipeline>): Promise<Pipeline> {
  const response = await fetch(`/api/pipelines/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(pipeline),
  });
  if (!response.ok) throw new Error(`Failed to update pipeline: ${response.status}`);
  return response.json();
}

export async function deletePipeline(id: string): Promise<void> {
  const response = await fetch(`/api/pipelines/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error(`Failed to delete pipeline: ${response.status}`);
}

export async function fetchProviders(): Promise<{ available: string[] }> {
  const response = await fetch('/api/config/providers');
  if (!response.ok) throw new Error(`Failed to fetch providers: ${response.status}`);
  return response.json();
}

export async function validateConfig(workdir: string): Promise<{ valid: boolean; warnings: string[]; errors: string[] }> {
  const response = await fetch(`/api/config/validate${runQuery(workdir)}`);
  if (!response.ok) throw new Error(`Failed to validate config: ${response.status}`);
  return response.json();
}

export async function fetchRunCosts(runId: string): Promise<{ run_id: string; entries: Array<{ agent_name: string; model: string; total_tokens: number; cost_usd: number }> }> {
  const response = await fetch(`/api/costs?run_id=${runId}`);
  if (!response.ok) throw new Error(`Failed to fetch costs: ${response.status}`);
  return response.json();
}

export async function fetchCostSummary(period: string = 'daily'): Promise<{ period: string; total_cost_usd: number; total_tokens: number; runs: number }> {
  const response = await fetch(`/api/costs/summary?period=${period}`);
  if (!response.ok) throw new Error(`Failed to fetch cost summary: ${response.status}`);
  return response.json();
}
