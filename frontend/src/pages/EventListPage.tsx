import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiClient } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'
import type { EventRequest } from '@/types'
import { PlusCircle, Search, Calendar, Users, Loader2 } from 'lucide-react'

export const EventListPage: React.FC = () => {
  const { user } = useAuthStore()
  const [events, setEvents] = useState<EventRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')

  const fetchEvents = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<EventRequest[]>('/events')
      setEvents(res.data || [])
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchEvents()
  }, [])

  const filtered = events.filter((ev) => {
    const matchesSearch = ev.title.toLowerCase().includes(search.toLowerCase())
    const matchesStatus = statusFilter === 'ALL' || ev.status === statusFilter
    return matchesSearch && matchesStatus
  })

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'DRAFT':
        return 'bg-surface-100 text-surface-700 border-surface-200'
      case 'SUBMITTED':
      case 'IN_REVIEW':
        return 'bg-primary-50 text-primary-700 border-primary-200'
      case 'REVISION_REQUIRED':
        return 'bg-amber-50 text-amber-800 border-amber-300'
      case 'APPROVED':
        return 'bg-success-50 text-success-700 border-success-200'
      case 'REJECTED':
        return 'bg-danger-50 text-danger-700 border-danger-200'
      default:
        return 'bg-surface-100 text-surface-700 border-surface-200'
    }
  }

  const isSecretary = user?.role === 'CLUB_SECRETARY' || user?.role === 'SYSTEM_ADMIN'

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Top action header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-surface-900">Club Event Proposals</h1>
          <p className="text-xs text-surface-500 mt-1">
            Track, review, and manage event lifecycles and statutory clearances.
          </p>
        </div>

        {isSecretary && (
          <Link
            to="/events/new"
            className="btn-primary flex items-center gap-2 text-sm px-4 py-2 rounded-lg shrink-0"
          >
            <PlusCircle className="w-4 h-4" /> Propose New Event
          </Link>
        )}
      </div>

      {/* Filter and Search Bar */}
      <div className="card p-4 flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-surface-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search proposals..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-xs rounded-lg border border-surface-200 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <span className="text-xs text-surface-500 shrink-0">Filter Status:</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs px-2.5 py-1.5 rounded-lg border border-surface-200 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white w-full sm:w-auto"
          >
            <option value="ALL">All Statuses</option>
            <option value="DRAFT">Draft</option>
            <option value="SUBMITTED">Submitted</option>
            <option value="IN_REVIEW">In Review</option>
            <option value="REVISION_REQUIRED">Revision Required</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
          </select>
        </div>
      </div>

      {/* Event Cards Grid */}
      {loading ? (
        <div className="flex items-center justify-center p-12 text-surface-500 gap-2">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Loading proposals...</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-12 text-center text-surface-400">
          <Calendar className="w-12 h-12 mx-auto mb-3 stroke-1 text-surface-300" />
          <p className="text-sm font-medium">No event proposals found.</p>
          <p className="text-xs mt-1">Try adjusting your search or create a new proposal.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((ev) => (
            <div
              key={ev.id}
              className="card p-5 flex flex-col justify-between hover:shadow-md transition-shadow border border-surface-200"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-surface-100 text-surface-600">
                    {ev.event_type}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${getStatusBadge(
                      ev.status
                    )}`}
                  >
                    {ev.status}
                  </span>
                </div>

                <h2 className="text-sm font-bold text-surface-900 line-clamp-1 mb-1">{ev.title}</h2>
                <p className="text-xs text-surface-500 line-clamp-2 mb-4">
                  {ev.description || 'No description provided.'}
                </p>
              </div>

              <div className="pt-3 border-t border-surface-100 flex items-center justify-between text-[11px] text-surface-500">
                <div className="flex items-center gap-1.5">
                  <Calendar className="w-3.5 h-3.5 text-surface-400" />
                  <span>{ev.event_date ? new Date(ev.event_date).toLocaleDateString() : 'Date TBD'}</span>
                </div>

                {ev.expected_attendees && (
                  <div className="flex items-center gap-1">
                    <Users className="w-3.5 h-3.5 text-surface-400" />
                    <span>{ev.expected_attendees} pax</span>
                  </div>
                )}

                <Link
                  to={`/events/${ev.id}`}
                  className="font-semibold text-primary-600 hover:text-primary-700"
                >
                  Manage →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
