import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from '@/store/authStore'
import type { User } from '@/types'

const mockUser: User = {
  id: 'u1-1111',
  email: 'secretary@college.edu',
  full_name: 'Jane Secretary',
  role: 'CLUB_SECRETARY',
  is_active: true,
  email_verified: true,
  created_at: '2026-01-01T00:00:00Z',
}

describe('AuthStore (Zustand)', () => {
  beforeEach(() => {
    useAuthStore.getState().clearAuth()
  })

  it('starts unauthenticated with isLoading false after clearAuth', () => {
    const state = useAuthStore.getState()
    expect(state.user).toBeNull()
    expect(state.accessToken).toBeNull()
    expect(state.isAuthenticated).toBe(false)
  })

  it('sets authentication state correctly', () => {
    useAuthStore.getState().setAuth(mockUser, 'test-access-token')
    const state = useAuthStore.getState()
    expect(state.user).toEqual(mockUser)
    expect(state.accessToken).toBe('test-access-token')
    expect(state.isAuthenticated).toBe(true)
    expect(state.isLoading).toBe(false)
  })

  it('updates access token independently', () => {
    useAuthStore.getState().setAuth(mockUser, 'token-1')
    useAuthStore.getState().setAccessToken('token-2')
    expect(useAuthStore.getState().accessToken).toBe('token-2')
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
  })

  it('clears authentication state completely', () => {
    useAuthStore.getState().setAuth(mockUser, 'token-1')
    useAuthStore.getState().clearAuth()
    const state = useAuthStore.getState()
    expect(state.user).toBeNull()
    expect(state.accessToken).toBeNull()
    expect(state.isAuthenticated).toBe(false)
  })
})
