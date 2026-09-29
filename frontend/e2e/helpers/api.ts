/**
 * Lightweight programmatic API client for E2E test setup/teardown.
 * Used to create test fixtures via the backend API without going through the UI.
 */

const BASE_URL = 'http://127.0.0.1:8000/api/v1'

export const apiClient = {
  async login(email: string, password: string): Promise<string> {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) throw new Error(`Login failed: ${res.status} ${await res.text()}`)
    const data = await res.json()
    return data.access_token as string
  },

  async get<T>(path: string, token: string): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`)
    return res.json() as Promise<T>
  },

  async post<T>(path: string, body: unknown, token: string): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`POST ${path} failed: ${res.status} ${await res.text()}`)
    return res.json() as Promise<T>
  },
}
