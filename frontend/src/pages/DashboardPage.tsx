import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiClient } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'
import {
  ArrowUpRight,
  PlusCircle,
  Loader2,
} from 'lucide-react'

interface SecretaryMetrics {
  draft_count: number
  submitted_count: number
  in_review_count: number
  revision_required_count: number
  approved_count: number
  rejected_count: number
  recent_events: Array<{
    id: string
    title: string
    club_name?: string
    status: string
  }>
}

interface ReviewerMetrics {
  pending_actions: number
  completed_approvals: number
  recent_workflow_activity: Array<{
    action: string
    entity_id?: string
    created_at?: string
  }>
}

interface AdminMetrics {
  active_users: number
  pending_proposals: number
  system_counts?: {
    total_clubs?: number
    total_events?: number
  }
}

interface DashboardData {
  secretary?: SecretaryMetrics
  reviewer?: ReviewerMetrics
  admin?: AdminMetrics
}

export const DashboardPage: React.FC = () => {
  const { user } = useAuthStore()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadDashboard = async () => {
      try {
        const res = await apiClient.get<DashboardData>('/dashboard')
        setData(res.data)
      } catch {
        // ignore
      } finally {
        setLoading(false)
      }
    }
    loadDashboard()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-surface-500 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Loading dashboard metrics...</span>
      </div>
    )
  }

  const role = user?.role || ''

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Welcome Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-xl border border-surface-200 shadow-sm">
        <div>
          <h1 className="text-xl font-bold text-surface-900">Welcome, {user?.full_name}</h1>
          <p className="text-xs text-surface-500 mt-1">
            Institutional Role:{' '}
            <span className="font-semibold text-primary-700">{role.replace(/_/g, ' ')}</span>
          </p>
        </div>

        {(role === 'CLUB_SECRETARY' || role === 'SYSTEM_ADMIN') && (
          <Link
            to="/events/new"
            className="btn-primary flex items-center gap-2 text-sm px-4 py-2 rounded-lg"
          >
            <PlusCircle className="w-4 h-4" /> Propose New Event
          </Link>
        )}
      </div>

      {/* Secretary View */}
      {data?.secretary && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <div className="card p-4">
              <span className="text-[11px] font-medium text-surface-500 block">Drafts</span>
              <span className="text-2xl font-bold text-surface-800">{data.secretary.draft_count}</span>
            </div>
            <div className="card p-4">
              <span className="text-[11px] font-medium text-surface-500 block">Submitted</span>
              <span className="text-2xl font-bold text-primary-600">{data.secretary.submitted_count}</span>
            </div>
            <div className="card p-4">
              <span className="text-[11px] font-medium text-surface-500 block">In Review</span>
              <span className="text-2xl font-bold text-warning-600">{data.secretary.in_review_count}</span>
            </div>
            <div className="card p-4">
              <span className="text-[11px] font-medium text-surface-500 block">Revision Req.</span>
              <span className="text-2xl font-bold text-amber-600">{data.secretary.revision_required_count}</span>
            </div>
            <div className="card p-4">
              <span className="text-[11px] font-medium text-surface-500 block">Approved</span>
              <span className="text-2xl font-bold text-success-700">{data.secretary.approved_count}</span>
            </div>
            <div className="card p-4">
              <span className="text-[11px] font-medium text-surface-500 block">Rejected</span>
              <span className="text-2xl font-bold text-danger-700">{data.secretary.rejected_count}</span>
            </div>
          </div>

          <div className="card p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-surface-800">Recent Club Proposals</h2>
              <Link to="/events" className="text-xs text-primary-600 hover:text-primary-700 font-medium">
                View all →
              </Link>
            </div>

            {data.secretary.recent_events?.length === 0 ? (
              <p className="text-xs text-surface-400 py-4 text-center">No proposals created yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-surface-50 text-surface-600 border-b border-surface-200">
                    <tr>
                      <th className="py-2.5 px-3">Title</th>
                      <th className="py-2.5 px-3">Club</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-100">
                    {data.secretary.recent_events.map((ev) => (
                      <tr key={ev.id} className="hover:bg-surface-50">
                        <td className="py-2.5 px-3 font-medium text-surface-900">{ev.title}</td>
                        <td className="py-2.5 px-3 text-surface-600">{ev.club_name || 'Club'}</td>
                        <td className="py-2.5 px-3">
                          <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-surface-100 text-surface-700">
                            {ev.status}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-right">
                          <Link to={`/events/${ev.id}`} className="text-primary-600 hover:text-primary-800 font-medium">
                            Details
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reviewer View */}
      {data?.reviewer && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="card p-6 bg-gradient-to-br from-primary-50 to-white border-primary-200">
              <span className="text-xs font-semibold text-primary-800 uppercase tracking-wider">Awaiting Your Action</span>
              <div className="flex items-center justify-between mt-3">
                <span className="text-4xl font-extrabold text-primary-700">{data.reviewer.pending_actions}</span>
                <Link
                  to="/workflow/pending"
                  className="btn-primary text-xs px-3 py-1.5 rounded-lg flex items-center gap-1"
                >
                  Review Queue <ArrowUpRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </div>

            <div className="card p-6">
              <span className="text-xs font-semibold text-surface-500 uppercase tracking-wider">Sanctioned &amp; Approved</span>
              <div className="mt-3">
                <span className="text-4xl font-extrabold text-surface-800">{data.reviewer.completed_approvals}</span>
              </div>
            </div>
          </div>

          <div className="card p-6">
            <h2 className="text-sm font-semibold text-surface-800 mb-4">Recent Review Activity</h2>
            {data.reviewer.recent_workflow_activity?.length === 0 ? (
              <p className="text-xs text-surface-400 py-4 text-center">No recent review actions.</p>
            ) : (
              <div className="space-y-2">
                {data.reviewer.recent_workflow_activity.map((act, idx) => (
                  <div key={idx} className="p-3 bg-surface-50 rounded-lg text-xs flex items-center justify-between">
                    <div>
                      <span className="font-semibold text-surface-800">{act.action}</span>
                      <span className="text-surface-500 ml-2">ID: {act.entity_id?.slice(0, 8)}...</span>
                    </div>
                    <span className="text-[10px] text-surface-400">{act.created_at ? new Date(act.created_at).toLocaleDateString() : ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Admin View */}
      {data?.admin && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="card p-5">
              <span className="text-xs font-medium text-surface-500">Active Users</span>
              <span className="text-2xl font-bold text-surface-900 block mt-1">{data.admin.active_users}</span>
            </div>
            <div className="card p-5">
              <span className="text-xs font-medium text-surface-500">Total Clubs</span>
              <span className="text-2xl font-bold text-surface-900 block mt-1">{data.admin.system_counts?.total_clubs}</span>
            </div>
            <div className="card p-5">
              <span className="text-xs font-medium text-surface-500">Pending Reviews</span>
              <span className="text-2xl font-bold text-primary-600 block mt-1">{data.admin.pending_proposals}</span>
            </div>
            <div className="card p-5">
              <span className="text-xs font-medium text-surface-500">Total Proposals</span>
              <span className="text-2xl font-bold text-surface-900 block mt-1">{data.admin.system_counts?.total_events}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
