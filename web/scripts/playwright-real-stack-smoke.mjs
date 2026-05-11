import { spawn, execFile } from 'node:child_process';
import { createServer } from 'node:net';
import { existsSync } from 'node:fs';
import { mkdtemp, mkdir, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, '..');
const repoRoot = resolve(webRoot, '..');
const runId = 'real-stack-smoke-run';
const postgresImage = process.env.PLAYWRIGHT_REAL_STACK_POSTGRES_IMAGE || 'postgres:17';
const redisImage = process.env.PLAYWRIGHT_REAL_STACK_REDIS_IMAGE || 'redis:7-alpine';

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

function getFreePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolvePort(address.port));
    });
  });
}

function preferredPython() {
  if (process.env.AI_TEAM_BACKEND_PYTHON) return process.env.AI_TEAM_BACKEND_PYTHON;
  const repoVenvPython = join(repoRoot, '.venv', 'bin', 'python');
  if (existsSync(repoVenvPython)) return repoVenvPython;
  return 'python3';
}

function execFileAsync(command, args, options = {}) {
  return new Promise((resolveExec, reject) => {
    execFile(command, args, { ...options, maxBuffer: 10 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolveExec({ stdout, stderr });
    });
  });
}

async function waitForCommand(label, command, args, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      return await execFileAsync(command, args);
    } catch (error) {
      lastError = error;
      await sleep(500);
    }
  }
  throw new Error(`${label} did not become ready: ${lastError?.stderr || lastError?.message || 'timeout'}`);
}

async function waitForServer(url, timeoutMs = 30000) {
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

async function apiJson(apiBaseUrl, path, options) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`${path} failed with ${response.status}: ${body}`);
  }
  return response.json();
}

async function pollRun(apiBaseUrl, projectId, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let lastRun = null;
  while (Date.now() < deadline) {
    lastRun = await apiJson(apiBaseUrl, `/api/runs/${runId}?project_id=${encodeURIComponent(projectId)}`);
    if (lastRun.status === 'completed') return lastRun;
    if (['failed', 'blocked', 'cancelled'].includes(lastRun.status)) {
      throw new Error(`Run finished with ${lastRun.status}: ${lastRun.error_message || ''}`);
    }
    await sleep(750);
  }
  throw new Error(`Run did not complete in time. Last status: ${lastRun?.status || 'unknown'}`);
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

async function stopContainer(name) {
  if (!name) return;
  await execFileAsync('docker', ['stop', name]).catch(() => undefined);
}

function pipeOutput(name, child) {
  child.stdout.on('data', (chunk) => process.stdout.write(`[${name}] ${chunk}`));
  child.stderr.on('data', (chunk) => process.stderr.write(`[${name}] ${chunk}`));
}

async function writeFixtureConfig(projectRoot) {
  await mkdir(join(projectRoot, '.git'), { recursive: true });
  await mkdir(join(projectRoot, '.ai', 'agents'), { recursive: true });
  await mkdir(join(projectRoot, '.ai', 'pipeline-configs'), { recursive: true });
  await writeFile(join(projectRoot, '.ai', 'agents', 'dev.md'), 'You are a smoke-test developer.\n', 'utf8');
  const configPath = join(projectRoot, '.ai', 'pipeline-configs', 'real-stack-smoke.yaml');
  await writeFile(
    configPath,
    `metadata:
  name: real-stack-smoke
runtimes:
  mock:
    name: Mock Runtime
    cli: mock
    response: |
      Real stack smoke implementation completed.
agents:
  - name: dev
    runtime_id: mock
    role: developer
    prompt: agents/dev.md
pipeline:
  execution_mode: serial
  stages:
    - id: develop
      name: Real Stack Develop
      agents: [dev]
      input: requirement
      output:
        dev: implementation-report.md
quality_gates: []
worktree:
  enabled: false
runner:
  auto_split_requirements: false
`,
    'utf8',
  );
  return configPath;
}

const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const pythonCmd = preferredPython();
const suffix = `${process.pid}-${Date.now()}`;
const pgContainer = `ai-team-smoke-pg-${suffix}`;
const redisContainer = `ai-team-smoke-redis-${suffix}`;
const fixtureRoot = await mkdtemp(join(tmpdir(), 'ai-team-real-stack-smoke-'));
const projectRoot = join(fixtureRoot, 'project');
const webPort = Number(process.env.PLAYWRIGHT_REAL_STACK_WEB_PORT || await getFreePort());
const apiPort = Number(process.env.PLAYWRIGHT_REAL_STACK_API_PORT || await getFreePort());
const postgresPort = Number(process.env.PLAYWRIGHT_REAL_STACK_POSTGRES_PORT || await getFreePort());
const redisPort = Number(process.env.PLAYWRIGHT_REAL_STACK_REDIS_PORT || await getFreePort());
const baseUrl = `http://127.0.0.1:${webPort}`;
const apiBaseUrl = `http://127.0.0.1:${apiPort}`;
const databaseUrl = `postgresql://ai_team:ai_team@127.0.0.1:${postgresPort}/ai_team`;
const redisUrl = `redis://127.0.0.1:${redisPort}/0`;

let backend;
let frontend;
let worker;
let browser;

try {
  await execFileAsync('docker', [
    'run',
    '-d',
    '--rm',
    '--name',
    pgContainer,
    '-e',
    'POSTGRES_USER=ai_team',
    '-e',
    'POSTGRES_PASSWORD=ai_team',
    '-e',
    'POSTGRES_DB=ai_team',
    '-p',
    `127.0.0.1:${postgresPort}:5432`,
    postgresImage,
  ]);
  await execFileAsync('docker', [
    'run',
    '-d',
    '--rm',
    '--name',
    redisContainer,
    '-p',
    `127.0.0.1:${redisPort}:6379`,
    redisImage,
  ]);

  await waitForCommand(
    'Postgres',
    'docker',
    ['exec', pgContainer, 'pg_isready', '-U', 'ai_team', '-d', 'ai_team'],
  );
  await waitForCommand(
    'Redis',
    'docker',
    ['exec', redisContainer, 'redis-cli', 'ping'],
  );

  const configPath = await writeFixtureConfig(projectRoot);
  const env = {
    ...process.env,
    AI_TEAM_API_KEYS: '',
    AI_TEAM_ALLOWED_ROOTS: projectRoot,
    AI_TEAM_CORS_ORIGINS: '*',
    AI_TEAM_DB_URL: databaseUrl,
    AI_TEAM_REDIS_URL: redisUrl,
    AI_TEAM_PRODUCTION: '',
    DATABASE_URL: databaseUrl,
  };

  backend = spawn(
    pythonCmd,
    ['-m', 'uvicorn', 'api.app:create_app', '--factory', '--host', '127.0.0.1', '--port', String(apiPort)],
    { cwd: repoRoot, stdio: ['ignore', 'pipe', 'pipe'], env },
  );
  pipeOutput('api', backend);
  await waitForServer(`${apiBaseUrl}/health`, 45000);

  worker = spawn(pythonCmd, ['-m', 'engine.tasks'], {
    cwd: repoRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env,
  });
  pipeOutput('worker', worker);

  frontend = spawn(npmCmd, ['run', 'dev', '--', '--port', String(webPort), '--strictPort'], {
    cwd: webRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      BROWSER: 'none',
      VITE_API_PROXY_TARGET: apiBaseUrl,
      VITE_WS_PROXY_TARGET: `ws://127.0.0.1:${apiPort}`,
    },
  });
  pipeOutput('web', frontend);
  await waitForServer(`${baseUrl}/runs`, 30000);

  const project = await apiJson(apiBaseUrl, '/api/projects', {
    method: 'POST',
    body: JSON.stringify({ name: 'Real Stack Smoke Project', root_path: projectRoot }),
  });
  const expectedProjectRoot = await realpath(projectRoot).catch(() => projectRoot);
  if (!project.id || project.root_path !== expectedProjectRoot) {
    throw new Error(`Project API returned unexpected payload: ${JSON.stringify(project)}`);
  }

  const created = await apiJson(apiBaseUrl, '/api/runs', {
    method: 'POST',
    body: JSON.stringify({
      project_id: project.id,
      run_id: runId,
      requirement: '真实全栈 smoke: 经由 DB、Redis/RQ、worker 后在前端展示',
      yes: true,
      config_path: configPath,
      execution_mode: 'serial',
    }),
  });
  if (created.run_id !== runId || created.status !== 'queued') {
    throw new Error(`Run create API returned unexpected payload: ${JSON.stringify(created)}`);
  }

  const redisJob = await waitForCommand(
    'RQ job key',
    'docker',
    ['exec', redisContainer, 'redis-cli', 'GET', `ai-team:run_job:${runId}`],
    10000,
  );
  if (!redisJob.stdout.trim()) {
    throw new Error(`Redis did not store ai-team:run_job:${runId}`);
  }

  const completed = await pollRun(apiBaseUrl, project.id);
  if (!completed.artifacts.includes('implementation-report.md')) {
    throw new Error(`Completed run is missing implementation-report.md: ${JSON.stringify(completed.artifacts)}`);
  }

  const list = await apiJson(apiBaseUrl, `/api/runs?project_id=${encodeURIComponent(project.id)}`);
  if (!Array.isArray(list.items) || !list.items.some((item) => item.run_id === runId && item.status === 'completed')) {
    throw new Error(`DB-backed run list did not include completed run: ${JSON.stringify(list)}`);
  }

  browser = await chromium.launch();
  const page = await browser.newPage();
  await page.addInitScript(({ root, id }) => {
    window.localStorage.setItem('ai-team.lastWorkdir', root);
    window.localStorage.setItem('ai-team.runWorkdirs', JSON.stringify({ [id]: root }));
  }, { root: project.root_path, id: runId });

  await page.goto(`${baseUrl}/runs`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: '执行记录' }).waitFor();
  await page.getByText(`#${runId}`).waitFor();
  await page.getByText('真实全栈 smoke: 经由 DB、Redis/RQ、worker 后在前端展示').waitFor();
  await page.getByText('completed').first().waitFor();

  await page.goto(`${baseUrl}/runs/${runId}?project_id=${encodeURIComponent(project.id)}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: `Run #${runId}` }).waitFor();
  await page.getByText('Pipeline: project').waitFor();
  await page.getByText('Real Stack Develop').waitFor();
  const implementationArtifact = page.getByTitle('点击查看 implementation-report.md');
  await implementationArtifact.waitFor();
  await implementationArtifact.click();
  await page.getByText('Real stack smoke implementation completed.').waitFor();
} finally {
  if (browser) await browser.close();
  await stopProcess(frontend);
  await stopProcess(worker);
  await stopProcess(backend);
  await stopContainer(redisContainer);
  await stopContainer(pgContainer);
  await rm(fixtureRoot, { recursive: true, force: true });
}
