import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { chromium } from 'playwright';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, '..');
const port = Number(process.env.PLAYWRIGHT_SMOKE_PORT || 5174);
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
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' });
  await page.getByText('AI Team Platform').waitFor();
  await page.getByRole('heading', { name: '登录' }).waitFor();
  await page.getByPlaceholder('sk-...').waitFor();
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
}
