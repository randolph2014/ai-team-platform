import type { RunListItem, RunReport } from './types';

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

export async function fetchRuns(workdir: string): Promise<RunListItem[]> {
  const response = await fetch(`/api/runs${runQuery(workdir)}`);
  if (!response.ok) throw new Error(`Failed to fetch runs: ${response.status}`);
  return response.json();
}

export async function fetchRun(runId: string, workdir: string): Promise<RunReport> {
  const response = await fetch(`/api/runs/${runId}${runQuery(workdir)}`);
  if (!response.ok) throw new Error(`Failed to fetch run: ${response.status}`);
  return response.json();
}

export function runWebSocketUrl(runId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/runs/${runId}`;
}
