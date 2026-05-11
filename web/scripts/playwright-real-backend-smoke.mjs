import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, '..');
const repoRoot = resolve(webRoot, '..');
const webPort = Number(process.env.PLAYWRIGHT_REAL_WEB_PORT || 5176);
const apiPort = Number(process.env.PLAYWRIGHT_REAL_API_PORT || 8001);
const baseUrl = `http://127.0.0.1:${webPort}`;
const apiBaseUrl = `http://127.0.0.1:${apiPort}`;
const runId = 'real-backend-smoke-run';

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function waitForServer(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Server is still starting.
    }
    await sleep(250);
  }
  throw new Error(`Server did not become ready at ${url}`);
}

function preferredPython() {
  if (process.env.AI_TEAM_BACKEND_PYTHON) return process.env.AI_TEAM_BACKEND_PYTHON;
  const repoVenvPython = join(repoRoot, '.venv', 'bin', 'python');
  if (existsSync(repoVenvPython)) return repoVenvPython;
  return 'python3';
}

async function writeJson(path, payload) {
  await writeFile(path, JSON.stringify(payload, null, 2), 'utf8');
}

async function createFixtureProject() {
  const fixtureRoot = await mkdtemp(join(tmpdir(), 'ai-team-real-smoke-'));
  const projectRoot = join(fixtureRoot, 'project');
  const outputDir = join(projectRoot, '.ai', 'team-output', runId);
  await mkdir(join(projectRoot, '.git'), { recursive: true });
  await mkdir(outputDir, { recursive: true });

  const harnessReport = {
    schema_version: '1.0',
    run_id: runId,
    project_id: 'filesystem-workdir',
    stage_id: 'harness_verify',
    harness_config_hash: 'sha256:real-backend-smoke',
    generated_at: '2026-05-12T00:00:00+08:00',
    status: 'fail',
    blocking: true,
    summary: { total: 2, passed: 1, warnings: 0, failed: 1, skipped: 0 },
    checks: [
      {
        id: 'block.real-backend',
        type: 'command',
        status: 'fail',
        severity: 'error',
        blocking: true,
        duration_ms: 12,
        exit_code: 1,
        matched_files: [],
        output_excerpt: 'real backend smoke block',
        evidence_refs: ['quality_gate:block.real-backend'],
      },
      {
        id: 'pass.report-present',
        type: 'pattern',
        status: 'pass',
        severity: 'warning',
        blocking: false,
        duration_ms: 4,
        exit_code: null,
        matched_files: ['README.md'],
        output_excerpt: 'report artifact available',
        evidence_refs: ['README.md:1'],
      },
    ],
    baseline_results: [],
    rule_violations: [],
    warnings: [],
    evidence: ['# Real Backend Evidence\n\nRendered through the actual FastAPI artifact endpoint.'],
    next_stage_contract: {},
  };

  const runReport = {
    run_id: runId,
    status: 'blocked',
    requirement: '真实端到端 smoke: 展示 Harness 阻断报告',
    project_root: projectRoot,
    output_dir: outputDir,
    config_source: 'platform',
    started_at: '2026-05-12T00:00:00+08:00',
    completed_at: '2026-05-12T00:00:12+08:00',
    duration_seconds: 12,
    changed_files: ['README.md'],
    diff_stat: 'README.md | 1 +',
    stages: [
      {
        stage_id: 'harness_verify',
        stage_name: 'Harness 验证',
        iteration: 1,
        status: 'failed',
        type: 'harness_verify',
      },
    ],
    artifacts: ['harness-report.json'],
    warnings: [],
    status_timeline: [
      { status: 'running', timestamp: '2026-05-12T00:00:00+08:00' },
      { status: 'blocked', timestamp: '2026-05-12T00:00:12+08:00', reason: 'Harness blocking check failed' },
    ],
  };

  await writeJson(join(outputDir, 'report.json'), runReport);
  await writeJson(join(outputDir, 'harness-report.json'), harnessReport);
  return { fixtureRoot, projectRoot };
}

async function stopProcess(child) {
  if (!child || child.exitCode !== null) return;
  child.kill('SIGTERM');
  await Promise.race([
    new Promise((resolveStop) => child.once('exit', resolveStop)),
    sleep(3000).then(() => {
      if (child.exitCode === null) child.kill('SIGKILL');
    }),
  ]);
}

const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCmd = preferredPython();
const { fixtureRoot, projectRoot } = await createFixtureProject();

const backend = spawn(
  pythonCmd,
  ['-m', 'uvicorn', 'api.app:create_app', '--factory', '--host', '127.0.0.1', '--port', String(apiPort)],
  {
    cwd: repoRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      AI_TEAM_API_KEYS: '',
      AI_TEAM_ALLOWED_ROOTS: projectRoot,
      AI_TEAM_CORS_ORIGINS: '*',
      AI_TEAM_DB_URL: '',
      AI_TEAM_PRODUCTION: '',
      DATABASE_URL: '',
    },
  },
);

const frontend = spawn(
  npmCmd,
  ['run', 'dev', '--', '--port', String(webPort), '--strictPort'],
  {
    cwd: webRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      BROWSER: 'none',
      VITE_API_PROXY_TARGET: apiBaseUrl,
      VITE_WS_PROXY_TARGET: `ws://127.0.0.1:${apiPort}`,
    },
  },
);

let browser;

try {
  backend.stdout.on('data', (chunk) => process.stdout.write(chunk));
  backend.stderr.on('data', (chunk) => process.stderr.write(chunk));
  frontend.stdout.on('data', (chunk) => process.stdout.write(chunk));
  frontend.stderr.on('data', (chunk) => process.stderr.write(chunk));

  await waitForServer(`${apiBaseUrl}/health`);
  await waitForServer(`${baseUrl}/runs`);

  browser = await chromium.launch();
  const page = await browser.newPage();
  await page.addInitScript(({ root, id }) => {
    window.localStorage.setItem('ai-team.lastWorkdir', root);
    window.localStorage.setItem('ai-team.runWorkdirs', JSON.stringify({ [id]: root }));
  }, { root: projectRoot, id: runId });

  await page.goto(`${baseUrl}/runs`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: '执行记录' }).waitFor();
  await page.getByText(`#${runId}`).waitFor();
  await page.getByText('真实端到端 smoke: 展示 Harness 阻断报告').waitFor();
  await page.getByText('blocked').first().waitFor();

  await page.getByText(`#${runId}`).click();
  await page.waitForURL(`**/runs/${runId}`);
  await page.getByRole('heading', { name: `Run #${runId}` }).waitFor();
  await page.getByText('Harness Report').waitFor();
  await page.getByText('block.real-backend: real backend smoke block').waitFor();
  await page.getByText('Rendered through the actual FastAPI artifact endpoint.').waitFor();
} finally {
  if (browser) await browser.close();
  await stopProcess(frontend);
  await stopProcess(backend);
  await rm(fixtureRoot, { recursive: true, force: true });
}
