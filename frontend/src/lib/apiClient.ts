/**
 * CampusConnect API Client
 * Axios instance with JWT interceptors and error handling.
 * Access token is kept in memory (Zustand store), never localStorage.
 */
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  withCredentials: true, // Required for HttpOnly refresh token cookie
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30_000,
})

// ---------------------------------------------------------------------------
// Request interceptor — attach access token from memory
// ---------------------------------------------------------------------------
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Access token is stored in memory, retrieved from auth store
    const accessToken = getAccessTokenFromStore()
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// ---------------------------------------------------------------------------
// Response interceptor — handle 401 with token refresh
// ---------------------------------------------------------------------------
let isRefreshing = false
let refreshQueue: Array<{
  resolve: (token: string) => void
  reject: (error: unknown) => void
}> = []

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Queue the request while refresh is in progress
        return new Promise((resolve, reject) => {
          refreshQueue.push({
            resolve: (token: string) => {
              originalRequest.headers.Authorization = `Bearer ${token}`
              resolve(apiClient(originalRequest))
            },
            reject,
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const { data } = await axios.post(
          `${BASE_URL}/api/v1/auth/refresh`,
          {},
          { withCredentials: true }
        )
        const newAccessToken: string = data.access_token

        // Update store with new token
        setAccessTokenInStore(newAccessToken)

        // Process queued requests
        refreshQueue.forEach(({ resolve }) => resolve(newAccessToken))
        refreshQueue = []

        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`
        return apiClient(originalRequest)
      } catch (refreshError) {
        // Refresh failed — clear auth state and redirect to login
        refreshQueue.forEach(({ reject }) => reject(refreshError))
        refreshQueue = []
        clearAuthStore()
        window.location.href = '/login'
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

// ---------------------------------------------------------------------------
// Store integration helpers
// These create a circular dependency if imported directly, so we use
// a late-binding approach. The auth store registers these on init.
// ---------------------------------------------------------------------------
let _getAccessToken: (() => string | null) = () => null
let _setAccessToken: ((token: string) => void) = () => {}
let _clearAuth: (() => void) = () => {}

export function registerAuthStoreHooks(
  getToken: () => string | null,
  setToken: (t: string) => void,
  clearAuth: () => void
) {
  _getAccessToken = getToken
  _setAccessToken = setToken
  _clearAuth = clearAuth
}

function getAccessTokenFromStore(): string | null {
  return _getAccessToken()
}

function setAccessTokenInStore(token: string): void {
  _setAccessToken(token)
}

function clearAuthStore(): void {
  _clearAuth()
}
