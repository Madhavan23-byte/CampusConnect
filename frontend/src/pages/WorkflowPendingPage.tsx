import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiClient } from '@/lib/apiClient'
import { Clock, ArrowUpRight, Loader2, CheckCircle2 } from 'lucide-react'

interface PendingItem {
  step_id: string
  instance_id: string
  event_request_id: string
  event_title: string
  club_name: string
  step_order: number
  step_name: string
  version_number: number
  submitted_at: string
  assigned_to: string
}

export const WorkflowPendingPage: React.FC = () => {
  const [items, setItems] = useState<PendingItem[]>([])
  const [loading, setLoading] = useState(true)

  const fetchPending = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<PendingItem[]>('/workflows/pending')
      setItems(res.data || [])
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPending()
  }, [])

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-surface-900">Institutional Review Queue</h1>
          <p className="text-xs text-surface-500 mt-1">
            Proposals awaiting your statutory evaluation and clearance.
          </p>
        </div>

        <span className="px-3 py-1 rounded-full text-xs font-bold bg-primary-50 text-primary-700 border border-primary-200 shrink-0 self-start sm:self-auto">
          {items.length} Awaiting Action
        </span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-12 text-surface-500 gap-2">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Loading review items...</span>
        </div>
      ) : items.length === 0 ? (
        <div className="card p-12 text-center text-surface-400">
          <CheckCircle2 className="w-12 h-12 mx-auto mb-3 stroke-1 text-success-500" />
          <p className="text-sm font-semibold text-surface-800">Your queue is clear!</p>
          <p className="text-xs mt-1">No proposals are currently awaiting your authorization.</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-surface-50 text-surface-600 border-b border-surface-200">
                <tr>
                  <th className="py-3 px-4 font-semibold">Event Proposal</th>
                  <th className="py-3 px-4 font-semibold">Club</th>
                  <th className="py-3 px-4 font-semibold">Statutory Clearance Stage</th>
                  <th className="py-3 px-4 font-semibold">Version</th>
                  <th className="py-3 px-4 font-semibold">Submitted</th>
                  <th className="py-3 px-4 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-100">
                {items.map((item) => (
                  <tr key={item.step_id} className="hover:bg-surface-50 transition-colors">
                    <td className="py-3 px-4 font-bold text-surface-900">
                      {item.event_title}
                    </td>
                    <td className="py-3 px-4 text-surface-600">{item.club_name}</td>
                    <td className="py-3 px-4">
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold bg-primary-50 text-primary-700 border border-primary-200">
                        <Clock className="w-3 h-3 text-primary-600" />
                        Step {item.step_order}: {item.step_name}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-surface-500">v{item.version_number}</td>
                    <td className="py-3 px-4 text-surface-500">
                      {item.submitted_at ? new Date(item.submitted_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <Link
                        to={`/workflow/steps/${item.step_id}?event_id=${item.event_request_id}`}
                        className="btn-primary text-xs px-3 py-1.5 rounded-lg inline-flex items-center gap-1 font-semibold"
                      >
                        Review Step <ArrowUpRight className="w-3.5 h-3.5" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
