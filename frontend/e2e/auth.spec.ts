import { test, expect } from '@playwright/test'
import { TEST_USERS, loginAs, logout, resetE2EData } from './helpers/auth'

test.describe('Authentication & Session Handling (E2E)', () => {
  test.beforeAll(() => {
    resetE2EData()
  })

  test('1. Application renders login page with expected inputs and branding', async ({ page }) => {
    await page.goto('/login')
    await expect(page).toHaveTitle(/CampusConnect/i)
    await expect(page.getByRole('heading', { name: 'CampusConnect' })).toBeVisible()
    await expect(page.getByPlaceholder('user@college.edu')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible()
  })

  test('2. Invalid credentials display error alert and prevent login', async ({ page }) => {
    await page.goto('/login')
    await page.fill('input[type="email"]', 'invalid.user@college.edu')
    await page.fill('input[type="password"]', 'WrongPassword123!')
    await page.click('button[type="submit"]')

    // Verify error message is shown
    const errorAlert = page.locator('div.text-danger-700')
    await expect(errorAlert).toBeVisible({ timeout: 10_000 })
    await expect(errorAlert).toContainText(/invalid email or password/i)
    await expect(page).toHaveURL(/.*\/login/)
  })

  test('3. Valid credentials authenticate user and redirect to dashboard', async ({ page }) => {
    await loginAs(page, TEST_USERS.secretary)
    await expect(page).toHaveURL(/.*\/dashboard/)
    await expect(page.getByText('E2E Club Secretary', { exact: true })).toBeVisible()
    await expect(page.getByText('CLUB SECRETARY', { exact: true })).toBeVisible()
  })

  test('4. Session persists across page reload', async ({ page }) => {
    await loginAs(page, TEST_USERS.secretary)
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/.*\/dashboard/)
    await expect(page.getByText('E2E Club Secretary', { exact: true })).toBeVisible()
  })

  test('5. Logout clears authentication state and redirects to login', async ({ page }) => {
    await loginAs(page, TEST_USERS.secretary)
    await logout(page)
    await expect(page).toHaveURL(/.*\/login/)

    // Attempting to navigate back to protected dashboard should redirect to login
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/.*\/login/)
  })

  test('6. Protected routes redirect unauthenticated visitors to login', async ({ page }) => {
    // Clear any existing cookies/storage
    await page.context().clearCookies()
    await page.goto('/events/new')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/.*\/login/)

    await page.goto('/workflow/pending')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/.*\/login/)
  })
})

