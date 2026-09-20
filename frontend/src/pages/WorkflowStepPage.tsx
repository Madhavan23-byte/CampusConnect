import React, { useEffect, useState } from 'react'
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom'
import { apiClient } from '@/lib/apiClient'
import type { EventRequest, WorkflowInstanceStep } from '@/types'
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  AlertCircle,
  Building,
  DollarSign,
  FileText,
} from 'lucide-react'

export const WorkflowStepPage: React.FC = () => {
  const { stepId } = useParams<{ stepId: string }>()
  const [searchParams] = useSearchParams()
  const eventId = searchParams.get('event_id')
  const navigate = useNavigate()

  const [event, setEvent] = useState<EventRequest | null>(null)
  const [currentStep, setCurrentStep] = useState<WorkflowInstanceStep | null>(null)
  const [loading, setLoading] = useState(true)

  const [comments, setComments] = useState('')
  const [submittingAction, setSubmittingAction] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  useEffect(() => {
    const loadEventAndStep = async () => {
      try {
        if (eventId) {
          const evRes = await apiClient.get<EventRequest>(`/events/${eventId}`)
          setEvent(evRes.data)
          const steps = evRes.data.workflow_instance?.steps || []
          const found = steps.find((s) => s.id === stepId)
          if (found) setCurrentStep(found)
        }
      } catch {
        setError('Failed to load proposal details.')
      } finally {
        setLoading(false)
      }
    }
    loadEventAndStep()
  }, [stepId, eventId])

  const handleApprove = async () => {
    if (!window.confirm('Confirm APPROVAL for this statutory step?')) return
    setError(null)
    setSubmittingAction(true)

    try {
      await apiClient.post(`/workflows/steps/${stepId}/approve`, {
        comments: comments.trim() ? comments.trim() : null,
      })
      setSuccess('Step approved successfully!')
      setTimeout(() => navigate('/workflow/pending'), 1200)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setError(e.response?.data?.message || 'Failed to approve step.')
      setSubmittingAction(false)
    }
  }

  const handleRequestRevision = async () => {
    if (comments.trim().length < 5) {
      setError('Comments are mandatory for requesting revision (minimum 5 characters).')
      return
    }
    if (!window.confirm('Request REVISION from the club secretary?')) return
    setError(null)
    setSubmittingAction(true)

    try {
      await apiClient.post(`/workflows/steps/${stepId}/request-revision`, {
        comments: comments.trim(),
      })
      setSuccess('Revision requested successfully. Proposal returned to club.')
      setTimeout(() => navigate('/workflow/pending'), 1200)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setError(e.response?.data?.message || 'Failed to request revision.')
      setSubmittingAction(false)
    }
  }

  const handleReject = async () => {
    if (comments.trim().length < 5) {
      setError('Comments are mandatory for rejecting proposal (minimum 5 characters).')
      return
    }
    if (!window.confirm('REJECT this proposal? This terminates the clearance workflow.')) return
    setError(null)
    setSubmittingAction(true)

    try {
      await apiClient.post(`/workflows/steps/${stepId}/reject`, {
        comments: comments.trim(),
      })
      setSuccess('Proposal rejected. Workflow terminated.')
      setTimeout(() => navigate('/workflow/pending'), 1200)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setError(e.response?.data?.message || 'Failed to reject proposal.')
      setSubmittingAction(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-surface-500 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Loading step assessment...</span>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      <Link
        to="/workflow/pending"
        className="inline-flex items-center gap-1.5 text-xs text-surface-500 hover:text-surface-800 font-medium"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Review Queue
      </Link>

      {error && (
        <div className="p-3.5 bg-danger-50 border border-danger-500 rounded-lg flex items-center gap-2.5 text-danger-800 text-xs">
          <AlertCircle className="w-4 h-4 shrink-0 text-danger-600" />
          <span>{error}</span>
        </div>
      )}

      {success && (
        <div className="p-3.5 bg-success-50 border border-success-500 rounded-lg flex items-center gap-2.5 text-success-800 text-xs">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-success-600" />
          <span>{success}</span>
        </div>
      )}

      {/* Decision Card */}
      <div className="card p-6 border-2 border-primary-200 bg-white">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4 pb-4 border-b border-surface-200">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-primary-700 bg-primary-50 px-2 py-0.5 rounded">
              Statutory Evaluation
            </span>
            <h1 className="text-base font-bold text-surface-900 mt-1">
              Step {currentStep?.step_order || ''}: {currentStep?.step_name || 'Approval Step'}
            </h1>
          </div>
          <span className="text-xs text-surface-500">
            Assigned: <strong className="text-surface-800">{currentStep?.assigned_to || 'Reviewer'}</strong>
          </span>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-surface-700 mb-1">
              Evaluation Remarks / Justification
            </label>
            <textarea
              rows={3}
              placeholder="Enter approval remarks or mandatory reason for revision / rejection (min 5 chars)..."
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
            />
            <p className="text-[10px] text-surface-400 mt-1">
              Remarks are mandatory when Requesting Revision or Rejecting.
            </p>
          </div>

          <div className="flex flex-wrap gap-3 pt-2">
            <button
              onClick={handleApprove}
              disabled={submittingAction}
              className="btn bg-success-600 hover:bg-success-700 text-white text-xs px-4 py-2 rounded-lg flex items-center gap-1.5 font-semibold"
            >
              {submittingAction ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              Approve Step
            </button>

            <button
              onClick={handleRequestRevision}
              disabled={submittingAction}
              className="btn bg-amber-500 hover:bg-amber-600 text-white text-xs px-4 py-2 rounded-lg flex items-center gap-1.5 font-semibold"
            >
              {submittingAction ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <AlertTriangle className="w-3.5 h-3.5" />}
              Request Revision
            </button>

            <button
              onClick={handleReject}
              disabled={submittingAction}
              className="btn bg-danger-600 hover:bg-danger-700 text-white text-xs px-4 py-2 rounded-lg flex items-center gap-1.5 font-semibold"
            >
              {submittingAction ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
              Reject Proposal
            </button>
          </div>
        </div>
      </div>

      {/* Proposal Summary Preview */}
      {event && (
        <div className="card p-6 space-y-6">
          <div className="border-b border-surface-200 pb-4">
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface-100 text-surface-700">
                {event.event_type}
              </span>
              <span className="text-xs text-surface-400">Version {event.current_version}</span>
            </div>
            <h2 className="text-lg font-bold text-surface-900">{event.title}</h2>
            <p className="text-xs text-surface-500">
              Club: <span className="font-semibold text-surface-700">{event.club?.name || 'Club'}</span> • Proposed Date:{' '}
              <span className="font-semibold text-surface-700">
                {event.event_date ? new Date(event.event_date).toLocaleDateString() : 'TBD'}
              </span>
            </p>
          </div>

          <div>
            <h3 className="text-xs font-semibold text-surface-500 uppercase mb-1">Description</h3>
            <p className="text-xs text-surface-800 leading-relaxed">{event.description || 'No description provided.'}</p>
          </div>

          {/* Venue details */}
          {event.venue_request && (
            <div className="p-4 bg-surface-50 rounded-lg border border-surface-200">
              <h3 className="text-xs font-bold text-surface-800 flex items-center gap-1.5 mb-2">
                <Building className="w-3.5 h-3.5 text-primary-600" /> Venue Requirement
              </h3>
              <p className="text-xs text-surface-700">
                Date: <strong>{event.venue_request.requested_date}</strong> ({event.venue_request.start_time} –{' '}
                {event.venue_request.end_time}), Audience: <strong>{event.venue_request.expected_audience}</strong>
              </p>
            </div>
          )}

          {/* Budget details */}
          {event.budget_proposal && (
            <div className="p-4 bg-surface-50 rounded-lg border border-surface-200">
              <h3 className="text-xs font-bold text-surface-800 flex items-center gap-1.5 mb-2">
                <DollarSign className="w-3.5 h-3.5 text-primary-600" /> Budget Breakdown
              </h3>
              <p className="text-xs text-surface-700">
                Total Expenditure: <strong>₹{event.budget_proposal.total_expected_expenditure?.toLocaleString()}</strong> • Institute Grant Requested:{' '}
                <strong>₹{event.budget_proposal.institute_contribution?.toLocaleString()}</strong>
              </p>
            </div>
          )}

          {/* Attached docs count */}
          <div className="flex items-center justify-between pt-2 text-xs text-surface-500">
            <span className="flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5 text-surface-400" />
              {event.documents?.length || 0} Attached Document(s)
            </span>
            <Link
              to={`/events/${event.id}`}
              target="_blank"
              className="text-primary-600 hover:text-primary-800 font-medium"
            >
              Open Complete Proposal in New Tab →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
