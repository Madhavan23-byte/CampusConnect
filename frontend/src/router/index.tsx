import React, { useEffect, useCallback } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { apiClient } from '@/lib/apiClient'
import { Layout } from '@/components/Layout'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { EventListPage } from '@/pages/EventListPage'
import { CreateEventPage } from '@/pages/CreateEventPage'
import { EventDetailPage } from '@/pages/EventDetailPage'
import { WorkflowPendingPage } from '@/pages/WorkflowPendingPage'
import { WorkflowStepPage } from '@/pages/WorkflowStepPage'
import { Loader2 } from 'lucide-react'

// Protected Route wrapper
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuthStore()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-50">
        <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <Layout>{children}</Layout>
}

export const AppRouter: React.FC = () => {
  const { setAuth, setLoading, isAuthenticated } = useAuthStore()

  const checkSession = useCallback(async () => {
    try {
      const res = await apiClient.get('/auth/me')
      const token = (apiClient.defaults.headers.common['Authorization'] as string)?.replace('Bearer ', '') || ''
      setAuth(res.data, token)
    } catch {
      setLoading(false)
    }
  }, [setAuth, setLoading])

  useEffect(() => {
    if (!isAuthenticated) {
      checkSession()
    } else {
      setLoading(false)
    }
  }, [isAuthenticated, checkSession, setLoading])

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LoginPage />}
      />

      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/events"
        element={
          <ProtectedRoute>
            <EventListPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/events/new"
        element={
          <ProtectedRoute>
            <CreateEventPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/events/:id"
        element={
          <ProtectedRoute>
            <EventDetailPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/workflow/pending"
        element={
          <ProtectedRoute>
            <WorkflowPendingPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/workflow/steps/:stepId"
        element={
          <ProtectedRoute>
            <WorkflowStepPage />
          </ProtectedRoute>
        }
      />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
