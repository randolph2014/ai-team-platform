import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { chromium } from 'playwright';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, '..');
const port = Number(process.env.PLAYWRIGHT_HARNESS_PORT || 5175);
const baseUrl = `http://127.0.0.1:${port}`;

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function waitForServer(url, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Vite is still starting.
    }
    await sleep(250);
  }
  throw new Error(`Vite dev server did not become ready at ${url}`);
}

const harnessFiles = [
  { path: '.ai/harness.yaml', hash: 'sha256:config', content: "schema_version: '1.0'\n" },
  { path: '.ai/harness/rules/security.md', hash: 'sha256:rule', content: '# Security\n\nInitial rule' },
  { path: '.ai/harness/skills/reviewer.md', hash: 'sha256:skill', content: '# Reviewer Skill\n' },
  { path: '.ai/harness/baselines/coverage.json', hash: 'sha256:baseline', content: '{\n  "mode": "raise_only",\n  "metrics": {"coverage": 90}\n}\n' },
];

const harnessReport = {
  schema_version: '1.0',
  run_id: 'run-harness-ui',
  project_id: 'proj-1',
  stage_id: 'harness_verify',
  harness_config_hash: 'sha256:manifest-2',
  generated_at: '2026-05-10T00:00:00Z',
  status: 'fail',
  blocking: true,
  summary: { total: 3, passed: 1, warnings: 1, failed: 1, skipped: 0 },
  checks: [
    { id: 'warn.docs', type: 'pattern', status: 'warning', severity: 'warning', blocking: false, duration_ms: 3, exit_code: null, matched_files: ['docs/spec.md'], output_excerpt: '1 pattern match', evidence_refs: ['docs/spec.md:4'] },
    { id: 'block.security', type: 'command', status: 'fail', severity: 'error', blocking: true, duration_ms: 8, exit_code: 1, matched_files: [], output_excerpt: 'security gate failed', evidence_refs: ['quality_gate:block.security'] },
  ],
  baseline_results: [{ check_id: 'baseline.coverage', changes: [{ metric: 'coverage', previous: 90, current: 88 }] }],
  rule_violations: [{ rule_id: 'no-messagebox', file: 'src/App.tsx', line: 12 }],
  warnings: ['non-blocking warning'],
  evidence: ['# Evidence Body\n\nSanitized report evidence'],
  next_stage_contract: {},
};

const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const server = spawn(
  npmCmd,
  ['run', 'dev', '--', '--port', String(port), '--strictPort'],
  {
    cwd: webRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, BROWSER: 'none' },
  },
);

let browser;

try {
  server.stdout.on('data', (chunk) => process.stdout.write(chunk));
  server.stderr.on('data', (chunk) => process.stderr.write(chunk));
  await waitForServer(`${baseUrl}/login`);

  browser = await chromium.launch();
  const page = await browser.newPage();
  await page.addInitScript(() => {
    window.localStorage.setItem('ai-team.lastProjectId', 'proj-1');
  });

  let manifestHash = 'sha256:manifest-1';
  let saveCount = 0;
  let readOnly = false;

  await page.route('**/api/auth/status', (route) => route.fulfill({ json: { auth_enabled: false } }));
  await page.route('**/api/projects', (route) => route.fulfill({
    json: [{ id: 'proj-1', name: 'Repo', root_path: '/repo', created_at: '2026-05-10T00:00:00' }],
  }));
  await page.route('**/api/projects/proj-1/harness', async (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        json: {
          project_id: 'proj-1',
          manifest_hash: manifestHash,
          files: harnessFiles,
          summary: { rules_count: 1, skills_count: 1, checks_count: 1, baselines_count: 1 },
          validation: { valid: true, errors: [] },
          permissions: readOnly ? { can_view: true, can_edit: false, can_run_checks: false } : { can_view: true, can_edit: true, can_run_checks: true },
        },
      });
    }
    const body = JSON.parse(route.request().postData() || '{}');
    if (body.workdir) throw new Error('Harness save used workdir');
    if (!body.manifest_hash) throw new Error('Harness save omitted manifest_hash');
    saveCount += 1;
    if (saveCount === 1) {
      manifestHash = 'sha256:manifest-2';
      return route.fulfill({
        json: {
          project_id: 'proj-1',
          manifest_hash: manifestHash,
          files: body.files,
          summary: { rules_count: 1, skills_count: 1, checks_count: 1, baselines_count: 1 },
          validation: { valid: true, errors: [] },
        },
      });
    }
    return route.fulfill({
      status: 409,
      json: {
        error: 'manifest_conflict',
        current_manifest_hash: 'sha256:current',
        changed_files: ['.ai/harness/rules/security.md'],
      },
    });
  });
  await page.route('**/api/projects/proj-1/harness/validate', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}');
    if (body.workdir) throw new Error('Harness validate used workdir');
    return route.fulfill({ json: { valid: true, errors: [], manifest_hash: 'sha256:candidate' } });
  });
  await page.route('**/api/projects/proj-1/harness/checks/run', (route) => route.fulfill({ json: harnessReport }));
  await page.route('**/api/projects/proj-1/task-board', (route) => route.fulfill({
    json: {
      project_id: 'proj-1',
      summary: { total: 1, by_state: { accepted: 1 } },
      tasks: [{ id: 'T-1', title: 'Accepted checkout', state: 'accepted', run_ids: ['run-1'], decision_ids: ['human:run-1:acceptance_confirm:1'], summary: 'Historical decision' }],
      related_tasks: [],
    },
  }));
  await page.route('**/api/runs/run-harness-ui?project_id=proj-1', (route) => route.fulfill({
    json: {
      run_id: 'run-harness-ui',
      status: 'blocked',
      requirement: 'Harness UI smoke',
      project_root: '/repo',
      output_dir: '/repo/.ai/team-output/run-harness-ui',
      config_source: 'platform',
      stages: [],
      artifacts: ['harness-report.json'],
      warnings: [],
    },
  }));
  await page.route('**/api/runs/run-harness-ui/artifacts/harness-report.json?project_id=proj-1', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(harnessReport),
  }));

  await page.goto(`${baseUrl}/harness`, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Rules', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Skills', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Checks', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Baselines', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Task Board', exact: true }).waitFor();

  await page.locator('textarea.harnessTextarea').fill('# Security\n\nUpdated');
  await page.getByRole('button', { name: /保存/ }).click();
  await page.getByText('Harness 已保存').waitFor();

  await page.locator('textarea.harnessTextarea').fill('# Security\n\nConflict');
  await page.getByRole('button', { name: /保存/ }).click();
  await page.getByText('Manifest 冲突').waitFor();
  if (saveCount !== 2) throw new Error(`expected 2 save attempts, got ${saveCount}`);

  readOnly = true;
  await page.goto(`${baseUrl}/harness`, { waitUntil: 'networkidle' });
  await page.getByText('.ai/harness/rules/security.md').first().waitFor();
  if (await page.locator('textarea.harnessTextarea').count()) {
    throw new Error('read-only Harness page rendered an editor');
  }

  await page.goto(`${baseUrl}/runs/run-harness-ui?project_id=proj-1`, { waitUntil: 'networkidle' });
  await page.getByText('Harness Report').waitFor();
  await page.getByText('block.security: security gate failed').waitFor();
  await page.getByText('Baseline Changes').waitFor();
  await page.getByText('Sanitized report evidence').waitFor();
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
}
