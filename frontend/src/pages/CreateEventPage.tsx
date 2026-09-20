import React, { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { apiClient } from '@/lib/apiClient'
import type { Club, EventType } from '@/types'
import { ArrowLeft, Loader2, AlertCircle } from 'lucide-react'

export const CreateEventPage: React.FC = () => {
  const navigate = useNavigate()
  const [clubs, setClubs] = useState<Club[]>([])
  const [loadingClubs, setLoadingClubs] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [formData, setFormData] = useState({
    club_id: '',
    title: '',
    description: '',
    event_type: 'TECHNICAL' as EventType,
    expected_attendees: 100,
    event_date: '',
    chief_guest_name: '',
    chief_guest_designation: '',
    chief_guest_institution: '',
    academic_year: '2025-2026',
  })

  useEffect(() => {
    const fetchClubs = async () => {
      try {
        const res = await apiClient.get<Club[]>('/clubs')
        setClubs(res.data || [])
        if (res.data?.length > 0) {
          setFormData((prev) => ({ ...prev, club_id: res.data[0].id }))
        }
      } catch {
        setError('Failed to load registered clubs.')
      } finally {
        setLoadingClubs(false)
      }
    }
    fetchClubs()
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const payload = {
        ...formData,
        expected_attendees: Number(formData.expected_attendees),
      }
      const res = await apiClient.post<{ id: string }>('/events', payload)
      navigate(`/events/${res.data.id}`)
    } catch (err: unknown) {
      const errorObj = err as { response?: { data?: { message?: string } } }
      setError(errorObj.response?.data?.message || 'Failed to create event proposal.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
      <Link
        to="/events"
        className="inline-flex items-center gap-1.5 text-xs text-surface-500 hover:text-surface-800 font-medium"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Proposals
      </Link>

      <div className="card p-6">
        <h1 className="text-lg font-bold text-surface-900 mb-1">Create Event Proposal</h1>
        <p className="text-xs text-surface-500 mb-6">
          Step 1: Define initial proposal details. You will attach venue, budget, documents, and resources on the next screen before statutory submission.
        </p>

        {error && (
          <div className="mb-5 p-3 bg-danger-50 border border-danger-500 rounded-lg flex items-center gap-2 text-danger-700 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {loadingClubs ? (
          <div className="flex items-center justify-center p-8 gap-2 text-surface-500 text-xs">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading clubs...
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-surface-700 mb-1">Organizing Club</label>
              <select
                required
                value={formData.club_id}
                onChange={(e) => setFormData({ ...formData, club_id: e.target.value })}
                className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
              >
                {clubs.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.academic_year})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-surface-700 mb-1">Event Title</label>
              <input
                type="text"
                required
                placeholder="e.g. Annual Autonomous Robotics Hackathon 2026"
                value={formData.title}
                onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-surface-700 mb-1">Event Category</label>
                <select
                  value={formData.event_type}
                  onChange={(e) => setFormData({ ...formData, event_type: e.target.value as EventType })}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
                >
                  <option value="TECHNICAL">Technical</option>
                  <option value="CULTURAL">Cultural</option>
                  <option value="SPORTS">Sports</option>
                  <option value="WORKSHOP">Workshop</option>
                  <option value="SEMINAR">Seminar</option>
                  <option value="GUEST_LECTURE">Guest Lecture</option>
                  <option value="COMPETITION">Competition</option>
                  <option value="OUTREACH">Outreach</option>
                  <option value="OTHER">Other</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-surface-700 mb-1">Proposed Event Date</label>
                <input
                  type="date"
                  required
                  value={formData.event_date}
                  onChange={(e) => setFormData({ ...formData, event_date: e.target.value })}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-surface-700 mb-1">Expected Attendees</label>
                <input
                  type="number"
                  min="1"
                  required
                  value={formData.expected_attendees}
                  onChange={(e) => setFormData({ ...formData, expected_attendees: Number(e.target.value) })}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-surface-700 mb-1">Academic Year</label>
                <input
                  type="text"
                  required
                  value={formData.academic_year}
                  onChange={(e) => setFormData({ ...formData, academic_year: e.target.value })}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-surface-700 mb-1">Brief Description</label>
              <textarea
                rows={3}
                placeholder="Objectives, scope, target audience, schedule overview..."
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
              />
            </div>

            {/* Chief Guest Section */}
            <div className="pt-3 border-t border-surface-200">
              <span className="text-xs font-semibold text-surface-800 block mb-2">Chief Guest Details (Optional)</span>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <input
                  type="text"
                  placeholder="Full Name"
                  value={formData.chief_guest_name}
                  onChange={(e) => setFormData({ ...formData, chief_guest_name: e.target.value })}
                  className="px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                />
                <input
                  type="text"
                  placeholder="Designation"
                  value={formData.chief_guest_designation}
                  onChange={(e) => setFormData({ ...formData, chief_guest_designation: e.target.value })}
                  className="px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                />
                <input
                  type="text"
                  placeholder="Institution / Org"
                  value={formData.chief_guest_institution}
                  onChange={(e) => setFormData({ ...formData, chief_guest_institution: e.target.value })}
                  className="px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                />
              </div>
            </div>

            <div className="pt-4 flex justify-end gap-3">
              <Link to="/events" className="btn text-xs px-4 py-2 border border-surface-300 text-surface-700 hover:bg-surface-50 rounded-lg">
                Cancel
              </Link>
              <button
                type="submit"
                disabled={submitting}
                className="btn-primary text-xs px-5 py-2 rounded-lg flex items-center gap-2"
              >
                {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
                Create Proposal &amp; Continue
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
