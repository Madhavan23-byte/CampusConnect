import React from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { apiClient } from '@/lib/apiClient'
import { NotificationBell } from '@/components/NotificationBell'
import {
  LayoutDashboard,
  Calendar,
  PlusCircle,
  Clock,
  LogOut,
  GraduationCap,
} from 'lucide-react'

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, clearAuth } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = async () => {
    try {
      await apiClient.post('/auth/logout')
    } catch {
      // ignore
    }
    clearAuth()
    navigate('/login')
  }

  const isSecretary = user?.role === 'CLUB_SECRETARY' || user?.role === 'SYSTEM_ADMIN'
  const isReviewer = [
    'FACULTY_ADVISOR',
    'HALL_INCHARGE',
    'FINANCE_OFFICER',
    'ADVISOR_STUDENTS_UNION',
    'DEAN_STUDENT_AFFAIRS',
    'PRINCIPAL',
    'SYSTEM_ADMIN',
  ].includes(user?.role || '')

  const navItemClass = (path: string) =>
    `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
      location.pathname === path
        ? 'bg-primary-50 text-primary-700'
        : 'text-surface-600 hover:text-surface-900 hover:bg-surface-100'
    }`

  return (
    <div className="min-h-screen bg-surface-50 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-40 bg-white border-b border-surface-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <Link to="/dashboard" className="flex items-center gap-2.5">
              <div className="w-9 h-9 bg-primary-600 rounded-xl flex items-center justify-center shadow-sm">
                <GraduationCap className="w-5 h-5 text-white" />
              </div>
              <div>
                <span className="font-bold text-lg text-surface-900 leading-none block">CampusConnect</span>
                <span className="text-[10px] text-surface-400 font-medium">Governance Portal</span>
              </div>
            </Link>

            <nav className="hidden md:flex items-center gap-1">
              <Link to="/dashboard" className={navItemClass('/dashboard')}>
                <LayoutDashboard className="w-4 h-4" /> Dashboard
              </Link>
              <Link to="/events" className={navItemClass('/events')}>
                <Calendar className="w-4 h-4" /> Events
              </Link>
              {isSecretary && (
                <Link to="/events/new" className={navItemClass('/events/new')}>
                  <PlusCircle className="w-4 h-4" /> New Proposal
                </Link>
              )}
              {isReviewer && (
                <Link to="/workflow/pending" className={navItemClass('/workflow/pending')}>
                  <Clock className="w-4 h-4" /> Review Queue
                </Link>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <NotificationBell />

            <div className="h-6 w-px bg-surface-200 mx-1" />

            <div className="flex items-center gap-2.5">
              <div className="text-right hidden sm:block">
                <p className="text-xs font-semibold text-surface-800">{user?.full_name}</p>
                <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-primary-100 text-primary-800">
                  {user?.role?.replace(/_/g, ' ')}
                </span>
              </div>

              <button
                onClick={handleLogout}
                className="p-2 rounded-lg text-surface-500 hover:text-danger-600 hover:bg-danger-50 transition-colors"
                title="Sign Out"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  )
}
