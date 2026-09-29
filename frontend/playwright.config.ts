import { defineConfig, devices } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const isWindows = process.platform === 'win32'
const pythonPath = isWindows
  ? path.resolve(__dirname, '../backend/.venv/Scripts/python.exe')
  : path.resolve(__dirname, '../backend/.venv/bin/python')

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    headless: true,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `"${pythonPath}" -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: path.resolve(__dirname, '../backend'),
      url: 'http://127.0.0.1:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 30_000,
      env: {
        RATE_LIMIT_LOGIN_PER_MINUTE: '100',
      },
    },
    {
      command: 'npx vite --port 5173 --host 127.0.0.1',
      cwd: __dirname,
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
})
