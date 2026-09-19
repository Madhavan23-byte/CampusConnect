/**
 * CampusConnect — Auth Store (Zustand)
 * Stores access token in memory only. Never persisted to localStorage.
 * Refresh token is stored in HttpOnly cookie (managed by browser).
 */
import { create } from 'zustand'
import { registerAuthStoreHooks } from '@/lib/apiClient'
import type { User } from '@/types'

interface AuthState {
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean

  // Actions
  setAuth: (user: User, accessToken: string) => void
  setAccessToken: (token: string) => void
  clearAuth: () => void
  setLoading: (loading: boolean) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isLoading: true, // True on init until we check session

  setAuth: (user, accessToken) =>
    set({ user, accessToken, isAuthenticated: true, isLoading: false }),

  setAccessToken: (token) =>
    set({ accessToken: token }),

  clearAuth: () =>
    set({ user: null, accessToken: null, isAuthenticated: false, isLoading: false }),

  setLoading: (loading) => set({ isLoading: loading }),
}))

// Register store hooks with the API client (avoids circular imports)
registerAuthStoreHooks(
  () => useAuthStore.getState().accessToken,
  (token: string) => useAuthStore.getState().setAccessToken(token),
  () => useAuthStore.getState().clearAuth()
)
