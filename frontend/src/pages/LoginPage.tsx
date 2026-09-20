import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GraduationCap, AlertCircle, Loader2 } from 'lucide-react'
import { apiClient } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      const res = await apiClient.post('/auth/login', { email, password })
      const { user, access_token } = res.data
      setAuth(user, access_token)
      navigate('/dashboard')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setError(e.response?.data?.message || 'Invalid email or password.')
    } finally {
      setLoading(false)
    }
  }

  const quickLogin = (presetEmail: string) => {
    setEmail(presetEmail)
    setPassword('Pass123!Secure')
  }

  return (
    <div className="min-h-screen bg-surface-50 flex items-center justify-center p-4">
      <div className="card p-8 max-w-md w-full shadow-modal">
        <div className="text-center mb-6">
          <div className="w-14 h-14 bg-primary-600 rounded-2xl flex items-center justify-center mx-auto mb-3 shadow-md">
            <GraduationCap className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-surface-900">CampusConnect</h1>
          <p className="text-surface-500 text-xs mt-1">Collegiate Club &amp; Event Governance Platform</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-danger-50 border border-danger-500 rounded-lg flex items-center gap-2 text-danger-700 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-surface-700 mb-1">Email Address</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@college.edu"
              className="w-full px-3 py-2 text-sm rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-surface-700 mb-1">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              className="w-full px-3 py-2 text-sm rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full btn-primary py-2.5 text-sm font-semibold rounded-lg flex items-center justify-center"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Sign In'}
          </button>
        </form>

        <div className="mt-6 pt-4 border-t border-surface-200">
          <p className="text-[11px] font-medium text-surface-500 mb-2 text-center">Quick Role Pre-fills (Testing):</p>
          <div className="flex flex-wrap gap-1.5 justify-center">
            <button
              type="button"
              onClick={() => quickLogin('admin@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Admin
            </button>
            <button
              type="button"
              onClick={() => quickLogin('secretary@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Secretary
            </button>
            <button
              type="button"
              onClick={() => quickLogin('advisor@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Advisor
            </button>
            <button
              type="button"
              onClick={() => quickLogin('hall@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Hall
            </button>
            <button
              type="button"
              onClick={() => quickLogin('finance@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Finance
            </button>
            <button
              type="button"
              onClick={() => quickLogin('union@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Union
            </button>
            <button
              type="button"
              onClick={() => quickLogin('dean@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Dean
            </button>
            <button
              type="button"
              onClick={() => quickLogin('principal@college.edu')}
              className="px-2 py-1 bg-surface-100 hover:bg-surface-200 text-surface-700 rounded text-[10px] font-medium"
            >
              Principal
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
