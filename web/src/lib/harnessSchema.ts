import type { HarnessFile, HarnessFileKind, HarnessReport } from './types';

const HARNESS_CONFIG_PATH = '.ai/harness.yaml';
const HARNESS_PREFIX = '.ai/harness/';

export function isEditableHarnessPath(path: string): boolean {
  return path === HARNESS_CONFIG_PATH || path.startsWith(HARNESS_PREFIX);
}

export function inferHarnessFileKind(path: string): HarnessFileKind {
  if (path === HARNESS_CONFIG_PATH) return 'config';
  if (path.startsWith(`${HARNESS_PREFIX}rules/`)) return 'rule';
  if (path.startsWith(`${HARNESS_PREFIX}skills/`)) return 'skill';
  if (path.startsWith(`${HARNESS_PREFIX}checks/`)) return 'check';
  if (path.startsWith(`${HARNESS_PREFIX}baselines/`)) return 'baseline';
  if (path.startsWith(`${HARNESS_PREFIX}tasks/`) || path.startsWith(`${HARNESS_PREFIX}task-events/`) || path === `${HARNESS_PREFIX}task-board.json`) return 'task';
  return 'unknown';
}

export function normalizeHarnessFiles(files: HarnessFile[]): HarnessFile[] {
  return files
    .filter((file) => isEditableHarnessPath(file.path))
    .map((file) => ({
      ...file,
      kind: file.kind ?? inferHarnessFileKind(file.path),
    }))
    .sort((a, b) => a.path.localeCompare(b.path));
}

export function filesForHarnessTab(files: HarnessFile[], tab: 'rules' | 'skills' | 'checks' | 'baselines'): HarnessFile[] {
  if (tab === 'rules') return files.filter((file) => file.kind === 'rule');
  if (tab === 'skills') return files.filter((file) => file.kind === 'skill');
  if (tab === 'baselines') return files.filter((file) => file.kind === 'baseline');
  return files.filter((file) => file.kind === 'config' || file.kind === 'check');
}

export function hasUnsafeHarnessPath(files: HarnessFile[]): boolean {
  return files.some((file) => !isEditableHarnessPath(file.path));
}

export function nextHarnessPath(files: HarnessFile[], tab: 'rules' | 'skills' | 'checks' | 'baselines'): string {
  const existing = new Set(files.map((file) => file.path));
  const base = {
    rules: '.ai/harness/rules/new-rule',
    skills: '.ai/harness/skills/new-skill',
    checks: '.ai/harness/checks/new-check',
    baselines: '.ai/harness/baselines/new-baseline',
  }[tab];
  const ext = tab === 'baselines' ? '.json' : tab === 'checks' ? '.yaml' : '.md';
  for (let index = 1; index < 1000; index += 1) {
    const suffix = index === 1 ? '' : `-${index}`;
    const path = `${base}${suffix}${ext}`;
    if (!existing.has(path)) return path;
  }
  return `${base}-${Date.now()}${ext}`;
}

export function defaultHarnessContent(tab: 'rules' | 'skills' | 'checks' | 'baselines'): string {
  if (tab === 'baselines') {
    return '{\n  "mode": "raise_only",\n  "metrics": {}\n}\n';
  }
  if (tab === 'checks') {
    return 'id: new-check\nseverity: warning\n';
  }
  if (tab === 'skills') {
    return '# New Skill\n\n## Boundary\n\nProject skill content.\n';
  }
  return '# New Rule\n\n## Policy\n\nProject rule content.\n';
}

export function parseHarnessReport(content: string): HarnessReport | null {
  try {
    const parsed = JSON.parse(content) as HarnessReport;
    if (!parsed || !Array.isArray(parsed.checks) || !parsed.summary) return null;
    return parsed;
  } catch {
    return null;
  }
}
