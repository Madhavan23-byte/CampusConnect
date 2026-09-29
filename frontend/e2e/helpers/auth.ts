import { Page, expect } from '@playwright/test'
import { execSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

export const TEST_USERS = {
  admin: { email: 'e2e.admin@college.edu', password: 'Password123!', name: 'E2E Administrator', role: 'SYSTEM_ADMIN' },
  secretary: { email: 'e2e.sec@college.edu', password: 'Password123!', name: 'E2E Club Secretary', role: 'CLUB_SECRETARY' },
  advisor: { email: 'e2e.advisor@college.edu', password: 'Password123!', name: 'E2E Faculty Advisor', role: 'FACULTY_ADVISOR' },
  hall: { email: 'e2e.hall@college.edu', password: 'Password123!', name: 'E2E Hall Incharge', role: 'HALL_INCHARGE' },
  finance: { email: 'e2e.finance@college.edu', password: 'Password123!', name: 'E2E Finance Officer', role: 'FINANCE_OFFICER' },
  union: { email: 'e2e.union@college.edu', password: 'Password123!', name: 'E2E Union Advisor', role: 'ADVISOR_STUDENTS_UNION' },
  dean: { email: 'e2e.dean@college.edu', password: 'Password123!', name: 'E2E Dean Student Affairs', role: 'DEAN_STUDENT_AFFAIRS' },
  principal: { email: 'e2e.principal@college.edu', password: 'Password123!', name: 'E2E Principal', role: 'PRINCIPAL' },
  otherSecretary: { email: 'e2e.other_sec@college.edu', password: 'Password123!', name: 'Other Club Secretary', role: 'CLUB_SECRETARY' },
}

export function resetE2EData(): void {
  const isWindows = process.platform === 'win32'
  const pythonPath = isWindows
    ? path.resolve(__dirname, '../../../backend/.venv/Scripts/python.exe')
    : path.resolve(__dirname, '../../../backend/.venv/bin/python')
  const scriptPath = path.resolve(__dirname, '../../../backend/scripts/seed_e2e_data.py')
  const cwd = path.resolve(__dirname, '../../../backend')

  execSync(`"${pythonPath}" "${scriptPath}" --reset`, {
    cwd,
    stdio: 'pipe',
  })
}

export async function loginAs(page: Page, user: { email: string; password: string }): Promise<void> {
  await page.goto('/login')
  await page.waitForLoadState('networkidle')

  // Fill credentials
  await page.fill('input[type="email"]', user.email)
  await page.fill('input[type="password"]', user.password)
  await page.click('button[type="submit"]')

  // Verify dashboard navigation
  await expect(page).toHaveURL(/.*\/dashboard/, { timeout: 15_000 })
}

export async function logout(page: Page): Promise<void> {
  const logoutBtn = page.getByRole('button', { name: /sign out|logout/i })
  if (await logoutBtn.isVisible()) {
    await logoutBtn.click()
  } else {
    // Navigate directly to login and clear storage
    await page.goto('/login')
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })
    await page.context().clearCookies()
    await page.goto('/login')
  }
  await expect(page).toHaveURL(/.*\/login/, { timeout: 10_000 })
}
