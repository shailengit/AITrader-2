import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the TradeCraft frontend E2E tests.
 *
 * Only the Vite dev server is booted here (webServer). The workflow_loop spec
 * also depends on the FastAPI backend (:8000) and Postgres (:5431) being up —
 * the backend is NOT started by this config and must be run separately, e.g.:
 *   cd backend && ./venv/bin/python -m app.main
 *
 * Install before first run:
 *   cd frontend && npm i -D @playwright/test && npx playwright install chromium
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
