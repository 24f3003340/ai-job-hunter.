import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8011)
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 5174)
// Use a preinstalled Chromium if present (sandboxes can't download browsers); otherwise Playwright's own.
const candidates = [process.env.PW_CHROMIUM_PATH, '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'].filter(Boolean) as string[]
const executablePath = candidates.find((p) => existsSync(p))

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${FRONTEND_PORT}`, trace: 'retain-on-failure', ...devices['Desktop Chrome'], launchOptions: { executablePath } },
  webServer: [
    { command: './e2e/backend.sh', url: `http://127.0.0.1:${BACKEND_PORT}/health`, reuseExistingServer: false, timeout: 60_000, env: { E2E_BACKEND_PORT: String(BACKEND_PORT) } },
    { command: `npx vite --port ${FRONTEND_PORT} --strictPort --host 127.0.0.1`, url: `http://127.0.0.1:${FRONTEND_PORT}`, reuseExistingServer: false, timeout: 60_000,
      env: { VITE_DEV_PROXY_TARGET: `http://127.0.0.1:${BACKEND_PORT}` } },
  ],
})
