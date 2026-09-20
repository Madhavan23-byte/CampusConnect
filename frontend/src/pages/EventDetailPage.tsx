import React, { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { apiClient } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'
import type {
  EventRequest,
  Hall,
  Document as EventDocument,
  ResourceRequest,
} from '@/types'
import {
  ArrowLeft,
  Calendar,
  Building,
  DollarSign,
  FileText,
  Layers,
  Send,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Upload,
  Trash2,
  Download,
  Loader2,
  AlertCircle,
  Plus,
} from 'lucide-react'

export const EventDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const { user } = useAuthStore()

  const [event, setEvent] = useState<EventRequest | null>(null)
  const [halls, setHalls] = useState<Hall[]>([])
  const [documents, setDocuments] = useState<EventDocument[]>([])
  const [resources, setResources] = useState<ResourceRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'overview' | 'venue' | 'budget' | 'documents' | 'resources'>('overview')

  const [submittingWorkflow, setSubmittingWorkflow] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Venue form state
  const [venueForm, setVenueForm] = useState({
    hall_id: '',
    requested_date: '',
    start_time: '10:00:00',
    end_time: '17:00:00',
    expected_audience: 100,
    requires_stage: false,
    requires_audio: false,
    requires_lcd: false,
    requires_ac: false,
    requires_projector: false,
    additional_requirements: '',
  })
  const [savingVenue, setSavingVenue] = useState(false)

  // Budget form state
  const [budgetForm, setBudgetForm] = useState({
    expected_income: 0,
    institute_contribution: 0,
    notes: '',
  })
  const [lineItemForm, setLineItemForm] = useState({
    description: '',
    category: 'LOGISTICS',
    estimated_amount: 1000,
    notes: '',
  })
  const [savingBudget, setSavingBudget] = useState(false)
  const [savingLineItem, setSavingLineItem] = useState(false)

  // Document upload state
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [docType, setDocType] = useState('EVENT_PLAN')
  const [uploadingDoc, setUploadingDoc] = useState(false)

  // Resource form state
  const [resourceForm, setResourceForm] = useState({
    resource_type: 'AUDIO_VISUAL',
    quantity: 1,
    notes: '',
  })
  const [savingResource, setSavingResource] = useState(false)

  const loadAll = useCallback(async () => {
    try {
      const [evRes, hallsRes, docsRes, resRes] = await Promise.all([
        apiClient.get<EventRequest>(`/events/${id}`),
        apiClient.get<Hall[]>('/halls').catch(() => ({ data: [] as Hall[] })),
        apiClient.get<EventDocument[]>(`/events/${id}/documents`).catch(() => ({ data: [] as EventDocument[] })),
        apiClient.get<ResourceRequest[]>(`/events/${id}/resources`).catch(() => ({ data: [] as ResourceRequest[] })),
      ])

      setEvent(evRes.data)
      setHalls(hallsRes.data || [])
      setDocuments(docsRes.data || [])
      setResources(resRes.data || [])

      if (evRes.data.venue_request) {
        setVenueForm({
          hall_id: evRes.data.venue_request.hall_id || '',
          requested_date: evRes.data.venue_request.requested_date || evRes.data.event_date || '',
          start_time: evRes.data.venue_request.start_time || '10:00:00',
          end_time: evRes.data.venue_request.end_time || '17:00:00',
          expected_audience: evRes.data.venue_request.expected_audience || evRes.data.expected_attendees || 100,
          requires_stage: evRes.data.venue_request.requires_stage || false,
          requires_audio: evRes.data.venue_request.requires_audio || false,
          requires_lcd: evRes.data.venue_request.requires_lcd || false,
          requires_ac: evRes.data.venue_request.requires_ac || false,
          requires_projector: evRes.data.venue_request.requires_projector || false,
          additional_requirements: evRes.data.venue_request.additional_requirements || '',
        })
      } else if (hallsRes.data?.length > 0) {
        setVenueForm((prev) => ({
          ...prev,
          hall_id: hallsRes.data[0].id,
          requested_date: evRes.data.event_date || '',
        }))
      }

      if (evRes.data.budget_proposal) {
        setBudgetForm({
          expected_income: evRes.data.budget_proposal.expected_income || 0,
          institute_contribution: evRes.data.budget_proposal.institute_contribution || 0,
          notes: evRes.data.budget_proposal.notes || '',
        })
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to load event details.' })
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const isEditable = event?.status === 'DRAFT' || event?.status === 'REVISION_REQUIRED'
  const isSecretary = user?.role === 'CLUB_SECRETARY' || user?.role === 'SYSTEM_ADMIN'

  // Submit to workflow
  const handleSubmitWorkflow = async () => {
    if (!window.confirm('Submit this proposal for statutory 6-stage institutional clearance?')) return
    setSubmittingWorkflow(true)
    setMessage(null)

    try {
      await apiClient.post(`/events/${id}/submit`)
      setMessage({ type: 'success', text: 'Proposal successfully submitted to institutional approval workflow!' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to submit proposal for clearance.',
      })
    } finally {
      setSubmittingWorkflow(false)
    }
  }

  // Save venue request
  const handleSaveVenue = async (e: React.FormEvent) => {
    e.preventDefault()
    setSavingVenue(true)
    setMessage(null)
    try {
      await apiClient.post(`/events/${id}/venue`, {
        ...venueForm,
        expected_audience: Number(venueForm.expected_audience),
      })
      setMessage({ type: 'success', text: 'Venue requirement saved.' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to save venue.' })
    } finally {
      setSavingVenue(false)
    }
  }

  // Save budget header
  const handleSaveBudget = async (e: React.FormEvent) => {
    e.preventDefault()
    setSavingBudget(true)
    setMessage(null)
    try {
      await apiClient.post(`/events/${id}/budget`, {
        expected_income: Number(budgetForm.expected_income),
        institute_contribution: Number(budgetForm.institute_contribution),
        notes: budgetForm.notes,
        line_items: [],
      })
      setMessage({ type: 'success', text: 'Budget parameters updated.' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to update budget.' })
    } finally {
      setSavingBudget(false)
    }
  }

  // Add line item
  const handleAddLineItem = async (e: React.FormEvent) => {
    e.preventDefault()
    setSavingLineItem(true)
    setMessage(null)
    try {
      await apiClient.post(`/events/${id}/budget/items`, {
        ...lineItemForm,
        estimated_amount: Number(lineItemForm.estimated_amount),
      })
      setMessage({ type: 'success', text: 'Budget line item added.' })
      setLineItemForm({ description: '', category: 'LOGISTICS', estimated_amount: 1000, notes: '' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to add line item.' })
    } finally {
      setSavingLineItem(false)
    }
  }

  // Delete line item
  const handleDeleteLineItem = async (itemId: string) => {
    if (!window.confirm('Delete this budget line item?')) return
    try {
      await apiClient.delete(`/events/${id}/budget/items/${itemId}`)
      setMessage({ type: 'success', text: 'Line item removed.' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to delete line item.' })
    }
  }

  // Upload document
  const handleUploadDocument = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadFile) return
    setUploadingDoc(true)
    setMessage(null)

    const formData = new FormData()
    formData.append('file', uploadFile)
    formData.append('document_type', docType)

    try {
      await apiClient.post(`/events/${id}/documents`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setMessage({ type: 'success', text: 'Document uploaded successfully.' })
      setUploadFile(null)
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to upload document.' })
    } finally {
      setUploadingDoc(false)
    }
  }

  // Delete document
  const handleDeleteDocument = async (docId: string) => {
    if (!window.confirm('Remove this document?')) return
    try {
      await apiClient.delete(`/events/${id}/documents/${docId}`)
      setMessage({ type: 'success', text: 'Document removed.' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to delete document.' })
    }
  }

  // Add resource
  const handleAddResource = async (e: React.FormEvent) => {
    e.preventDefault()
    setSavingResource(true)
    setMessage(null)
    try {
      await apiClient.post(`/events/${id}/resources`, {
        ...resourceForm,
        quantity: Number(resourceForm.quantity),
      })
      setMessage({ type: 'success', text: 'Resource declaration added.' })
      setResourceForm({ resource_type: 'AUDIO_VISUAL', quantity: 1, notes: '' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to add resource.' })
    } finally {
      setSavingResource(false)
    }
  }

  // Delete resource
  const handleDeleteResource = async (resId: string) => {
    if (!window.confirm('Remove this resource request?')) return
    try {
      await apiClient.delete(`/events/${id}/resources/${resId}`)
      setMessage({ type: 'success', text: 'Resource declaration removed.' })
      loadAll()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({ type: 'error', text: e.response?.data?.message || 'Failed to delete resource.' })
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-surface-500 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Loading event details...</span>
      </div>
    )
  }

  if (!event) {
    return <div className="p-8 text-center text-surface-500 text-sm">Event proposal not found.</div>
  }

  const steps = event.workflow_instance?.steps || []
  const currentStepOrder = event.workflow_instance?.current_step_order || 1

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Back link & Top Bar */}
      <div className="flex items-center justify-between">
        <Link
          to="/events"
          className="inline-flex items-center gap-1.5 text-xs text-surface-500 hover:text-surface-800 font-medium"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Proposals
        </Link>

        {isSecretary && isEditable && (
          <button
            onClick={handleSubmitWorkflow}
            disabled={submittingWorkflow}
            className="btn-primary text-xs px-4 py-2 rounded-lg flex items-center gap-2 shadow-sm"
          >
            {submittingWorkflow ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            Submit Proposal for Clearance
          </button>
        )}
      </div>

      {/* Alert banner if message */}
      {message && (
        <div
          className={`p-3.5 rounded-lg flex items-center gap-2.5 text-xs ${
            message.type === 'success'
              ? 'bg-success-50 border border-success-500 text-success-800'
              : 'bg-danger-50 border border-danger-500 text-danger-800'
          }`}
        >
          {message.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 text-success-600" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 text-danger-600" />
          )}
          <span>{message.text}</span>
        </div>
      )}

      {/* Revision notice if REVISION_REQUIRED */}
      {event.status === 'REVISION_REQUIRED' && (
        <div className="p-4 bg-amber-50 border border-amber-300 rounded-xl flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <h3 className="text-xs font-bold text-amber-900">Revision Required by Approver</h3>
            <p className="text-xs text-amber-800 mt-1">
              Please review the feedback in the statutory workflow below, make the necessary amendments to your venue, budget, or attached documents, and click <strong>Submit Proposal for Clearance</strong> to resubmit version {event.current_version + 1}.
            </p>
          </div>
        </div>
      )}

      {/* Main Header Card */}
      <div className="card p-6 bg-white">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface-100 text-surface-700">
                {event.event_type}
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-primary-50 text-primary-700 border border-primary-200">
                Version {event.current_version}
              </span>
              <span className="text-xs text-surface-400">Academic Year {event.academic_year}</span>
            </div>
            <h1 className="text-xl font-bold text-surface-900">{event.title}</h1>
            <p className="text-xs text-surface-500 mt-1">
              Organized by <span className="font-semibold text-surface-700">{event.club?.name || 'Club'}</span>
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${
                event.status === 'APPROVED'
                  ? 'bg-success-100 text-success-800'
                  : event.status === 'REJECTED'
                  ? 'bg-danger-100 text-danger-800'
                  : event.status === 'REVISION_REQUIRED'
                  ? 'bg-amber-100 text-amber-800'
                  : event.status === 'IN_REVIEW' || event.status === 'SUBMITTED'
                  ? 'bg-primary-100 text-primary-800'
                  : 'bg-surface-100 text-surface-800'
              }`}
            >
              {event.status}
            </span>
          </div>
        </div>

        {/* 6-Stage Workflow Stepper */}
        {steps.length > 0 && (
          <div className="mt-8 pt-6 border-t border-surface-200">
            <h2 className="text-xs font-semibold text-surface-500 uppercase tracking-wider mb-4">
              Statutory 6-Stage Governance Interlock
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
              {steps.map((st) => {
                const isCurrent = st.step_order === currentStepOrder && event.status === 'IN_REVIEW'
                const isDone = st.status === 'APPROVED'
                const isRejected = st.status === 'REJECTED'
                const isRevision = st.status === 'REVISION_REQUESTED'

                return (
                  <div
                    key={st.id}
                    className={`p-3 rounded-lg border text-left flex flex-col justify-between ${
                      isDone
                        ? 'bg-success-50/50 border-success-200'
                        : isRejected
                        ? 'bg-danger-50/50 border-danger-200'
                        : isRevision
                        ? 'bg-amber-50/50 border-amber-200'
                        : isCurrent
                        ? 'bg-primary-50/50 border-primary-300 ring-2 ring-primary-500/20'
                        : 'bg-surface-50 border-surface-200 opacity-60'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between gap-1 mb-1">
                        <span className="text-[10px] font-bold text-surface-500">Step {st.step_order}</span>
                        {isDone && <CheckCircle2 className="w-3.5 h-3.5 text-success-600" />}
                        {isRejected && <XCircle className="w-3.5 h-3.5 text-danger-600" />}
                        {isRevision && <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />}
                        {isCurrent && <Clock className="w-3.5 h-3.5 text-primary-600 animate-spin" />}
                      </div>
                      <p className="text-[11px] font-semibold text-surface-800 line-clamp-2">{st.step_name}</p>
                    </div>

                    <div className="mt-2 pt-2 border-t border-surface-200/50">
                      <span className="text-[10px] font-medium text-surface-600 block">{st.status}</span>
                      {st.comments && (
                        <p className="text-[9px] text-surface-500 italic mt-0.5 line-clamp-2">
                          "{st.comments}"
                        </p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-surface-200 gap-2 text-xs font-semibold">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-2.5 border-b-2 flex items-center gap-2 ${
            activeTab === 'overview'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-surface-500 hover:text-surface-800'
          }`}
        >
          <Calendar className="w-4 h-4" /> Overview &amp; Schedule
        </button>
        <button
          onClick={() => setActiveTab('venue')}
          className={`px-4 py-2.5 border-b-2 flex items-center gap-2 ${
            activeTab === 'venue'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-surface-500 hover:text-surface-800'
          }`}
        >
          <Building className="w-4 h-4" /> Venue Booking
        </button>
        <button
          onClick={() => setActiveTab('budget')}
          className={`px-4 py-2.5 border-b-2 flex items-center gap-2 ${
            activeTab === 'budget'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-surface-500 hover:text-surface-800'
          }`}
        >
          <DollarSign className="w-4 h-4" /> Budget Proposal
        </button>
        <button
          onClick={() => setActiveTab('documents')}
          className={`px-4 py-2.5 border-b-2 flex items-center gap-2 ${
            activeTab === 'documents'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-surface-500 hover:text-surface-800'
          }`}
        >
          <FileText className="w-4 h-4" /> Documents ({documents.length})
        </button>
        <button
          onClick={() => setActiveTab('resources')}
          className={`px-4 py-2.5 border-b-2 flex items-center gap-2 ${
            activeTab === 'resources'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-surface-500 hover:text-surface-800'
          }`}
        >
          <Layers className="w-4 h-4" /> Resources ({resources.length})
        </button>
      </div>

      {/* Tab 1: Overview */}
      {activeTab === 'overview' && (
        <div className="card p-6 space-y-4">
          <div>
            <h3 className="text-xs font-semibold text-surface-500 uppercase">Event Description</h3>
            <p className="text-xs text-surface-800 mt-1 leading-relaxed">
              {event.description || 'No detailed description specified.'}
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t border-surface-200">
            <div>
              <span className="text-xs font-semibold text-surface-500 uppercase block">Event Date</span>
              <span className="text-sm font-medium text-surface-800">
                {event.event_date ? new Date(event.event_date).toLocaleDateString() : 'TBD'}
              </span>
            </div>
            <div>
              <span className="text-xs font-semibold text-surface-500 uppercase block">Expected Attendees</span>
              <span className="text-sm font-medium text-surface-800">{event.expected_attendees || 0} pax</span>
            </div>
          </div>

          {(event.chief_guest_name || event.chief_guest_designation) && (
            <div className="pt-4 border-t border-surface-200">
              <h3 className="text-xs font-semibold text-surface-500 uppercase mb-2">Chief Guest Dignitary</h3>
              <p className="text-xs font-bold text-surface-900">{event.chief_guest_name}</p>
              <p className="text-xs text-surface-600">
                {event.chief_guest_designation} {event.chief_guest_institution && `— ${event.chief_guest_institution}`}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Venue */}
      {activeTab === 'venue' && (
        <div className="card p-6 space-y-6">
          <h2 className="text-sm font-bold text-surface-900">Hall Reservation &amp; AV Requirements</h2>

          {event.venue_request && (
            <div className="p-4 bg-surface-50 rounded-lg border border-surface-200 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-semibold text-surface-500">Selected Hall</span>
                  <p className="text-sm font-bold text-surface-900">
                    {halls.find((h) => h.id === event.venue_request?.hall_id)?.name || 'Auditorium'}
                  </p>
                </div>
                <span
                  className={`px-2.5 py-0.5 rounded text-[10px] font-bold ${
                    event.venue_request.status === 'APPROVED'
                      ? 'bg-success-100 text-success-800'
                      : 'bg-amber-100 text-amber-800'
                  }`}
                >
                  Venue: {event.venue_request.status}
                </span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                <div>
                  <span className="text-surface-400 block">Date:</span>
                  <span className="font-medium text-surface-800">{event.venue_request.requested_date}</span>
                </div>
                <div>
                  <span className="text-surface-400 block">Slot:</span>
                  <span className="font-medium text-surface-800">
                    {event.venue_request.start_time} – {event.venue_request.end_time}
                  </span>
                </div>
                <div>
                  <span className="text-surface-400 block">Audience:</span>
                  <span className="font-medium text-surface-800">{event.venue_request.expected_audience}</span>
                </div>
              </div>

              <div className="pt-2 border-t border-surface-200 flex flex-wrap gap-2">
                {event.venue_request.requires_stage && (
                  <span className="px-2 py-0.5 bg-white border border-surface-200 rounded text-[10px] text-surface-700">Stage</span>
                )}
                {event.venue_request.requires_audio && (
                  <span className="px-2 py-0.5 bg-white border border-surface-200 rounded text-[10px] text-surface-700">Audio Setup</span>
                )}
                {event.venue_request.requires_lcd && (
                  <span className="px-2 py-0.5 bg-white border border-surface-200 rounded text-[10px] text-surface-700">LCD Wall</span>
                )}
                {event.venue_request.requires_ac && (
                  <span className="px-2 py-0.5 bg-white border border-surface-200 rounded text-[10px] text-surface-700">Air Conditioning</span>
                )}
                {event.venue_request.requires_projector && (
                  <span className="px-2 py-0.5 bg-white border border-surface-200 rounded text-[10px] text-surface-700">Projector</span>
                )}
              </div>
            </div>
          )}

          {isEditable && isSecretary && (
            <form onSubmit={handleSaveVenue} className="pt-4 border-t border-surface-200 space-y-4">
              <h3 className="text-xs font-bold text-surface-800">
                {event.venue_request ? 'Update Venue Booking' : 'Reserve Venue'}
              </h3>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-surface-700 mb-1">Select Hall</label>
                  <select
                    required
                    value={venueForm.hall_id}
                    onChange={(e) => setVenueForm({ ...venueForm, hall_id: e.target.value })}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                  >
                    {halls.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.name} (Cap: {h.capacity})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-surface-700 mb-1">Requested Date</label>
                  <input
                    type="date"
                    required
                    value={venueForm.requested_date}
                    onChange={(e) => setVenueForm({ ...venueForm, requested_date: e.target.value })}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-surface-700 mb-1">Start Time</label>
                  <input
                    type="text"
                    required
                    placeholder="10:00:00"
                    value={venueForm.start_time}
                    onChange={(e) => setVenueForm({ ...venueForm, start_time: e.target.value })}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-surface-700 mb-1">End Time</label>
                  <input
                    type="text"
                    required
                    placeholder="17:00:00"
                    value={venueForm.end_time}
                    onChange={(e) => setVenueForm({ ...venueForm, end_time: e.target.value })}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-surface-700 mb-1">Expected Audience</label>
                  <input
                    type="number"
                    required
                    value={venueForm.expected_audience}
                    onChange={(e) => setVenueForm({ ...venueForm, expected_audience: Number(e.target.value) })}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-300 bg-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-surface-700 mb-1">Facility Requirements</label>
                <div className="flex flex-wrap gap-4 text-xs">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={venueForm.requires_stage}
                      onChange={(e) => setVenueForm({ ...venueForm, requires_stage: e.target.checked })}
                    />
                    Stage
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={venueForm.requires_audio}
                      onChange={(e) => setVenueForm({ ...venueForm, requires_audio: e.target.checked })}
                    />
                    Audio
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={venueForm.requires_lcd}
                      onChange={(e) => setVenueForm({ ...venueForm, requires_lcd: e.target.checked })}
                    />
                    LCD Wall
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={venueForm.requires_ac}
                      onChange={(e) => setVenueForm({ ...venueForm, requires_ac: e.target.checked })}
                    />
                    AC
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={venueForm.requires_projector}
                      onChange={(e) => setVenueForm({ ...venueForm, requires_projector: e.target.checked })}
                    />
                    Projector
                  </label>
                </div>
              </div>

              <button
                type="submit"
                disabled={savingVenue}
                className="btn-primary text-xs px-4 py-2 rounded-lg flex items-center gap-2"
              >
                {savingVenue && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save Venue Parameters
              </button>
            </form>
          )}
        </div>
      )}

      {/* Tab 3: Budget */}
      {activeTab === 'budget' && (
        <div className="card p-6 space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-surface-900">Fiscal Budget &amp; Sanction Breakdown</h2>
            {event.budget_proposal && (
              <span
                className={`px-2.5 py-0.5 rounded text-[10px] font-bold ${
                  event.budget_proposal.finance_status === 'VERIFIED'
                    ? 'bg-success-100 text-success-800'
                    : 'bg-amber-100 text-amber-800'
                }`}
              >
                Finance: {event.budget_proposal.finance_status}
              </span>
            )}
          </div>

          {/* Budget Header Card */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-4 bg-surface-50 rounded-lg border border-surface-200">
              <span className="text-[11px] font-semibold text-surface-500 block">Expected Club Income</span>
              <span className="text-xl font-bold text-surface-800">
                ₹{event.budget_proposal?.expected_income?.toLocaleString() || 0}
              </span>
            </div>
            <div className="p-4 bg-surface-50 rounded-lg border border-surface-200">
              <span className="text-[11px] font-semibold text-surface-500 block">Institute Contribution Requested</span>
              <span className="text-xl font-bold text-primary-700">
                ₹{event.budget_proposal?.institute_contribution?.toLocaleString() || 0}
              </span>
            </div>
            <div className="p-4 bg-surface-50 rounded-lg border border-surface-200">
              <span className="text-[11px] font-semibold text-surface-500 block">Total Expenditure</span>
              <span className="text-xl font-bold text-surface-900">
                ₹{event.budget_proposal?.total_expected_expenditure?.toLocaleString() || 0}
              </span>
            </div>
          </div>

          {/* Line items table */}
          <div>
            <h3 className="text-xs font-bold text-surface-800 mb-3">Itemized Expenditures</h3>
            {event.budget_proposal?.line_items?.length === 0 ? (
              <p className="text-xs text-surface-400 py-3">No line items recorded.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border border-surface-200 rounded-lg overflow-hidden">
                  <thead className="bg-surface-50 text-surface-600 border-b border-surface-200">
                    <tr>
                      <th className="py-2.5 px-3">Description</th>
                      <th className="py-2.5 px-3">Category</th>
                      <th className="py-2.5 px-3">Estimated Amount</th>
                      <th className="py-2.5 px-3">Notes</th>
                      {isEditable && isSecretary && <th className="py-2.5 px-3 text-right">Action</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-100">
                    {event.budget_proposal?.line_items?.map((item) => (
                      <tr key={item.id}>
                        <td className="py-2.5 px-3 font-medium text-surface-900">{item.description}</td>
                        <td className="py-2.5 px-3 text-surface-600">{item.category}</td>
                        <td className="py-2.5 px-3 font-semibold text-surface-900">
                          ₹{Number(item.estimated_amount).toLocaleString()}
                        </td>
                        <td className="py-2.5 px-3 text-surface-500">{item.notes || '—'}</td>
                        {isEditable && isSecretary && (
                          <td className="py-2.5 px-3 text-right">
                            <button
                              onClick={() => handleDeleteLineItem(item.id)}
                              className="text-danger-600 hover:text-danger-800 p-1"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Add Line Item & Budget Forms */}
          {isEditable && isSecretary && (
            <div className="pt-4 border-t border-surface-200 space-y-6">
              <form onSubmit={handleAddLineItem} className="p-4 bg-surface-50 rounded-lg space-y-3">
                <span className="text-xs font-bold text-surface-800 block">Add Line Item</span>
                <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                  <input
                    type="text"
                    required
                    placeholder="Description (e.g. Mementoes)"
                    value={lineItemForm.description}
                    onChange={(e) => setLineItemForm({ ...lineItemForm, description: e.target.value })}
                    className="px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                  />
                  <select
                    value={lineItemForm.category}
                    onChange={(e) => setLineItemForm({ ...lineItemForm, category: e.target.value })}
                    className="px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                  >
                    <option value="LOGISTICS">Logistics</option>
                    <option value="REFRESHMENTS">Refreshments</option>
                    <option value="PUBLICITY">Publicity</option>
                    <option value="HONORARIUM">Honorarium</option>
                    <option value="PRIZES">Prizes</option>
                    <option value="PRINTING">Printing</option>
                    <option value="EQUIPMENT">Equipment</option>
                    <option value="MISCELLANEOUS">Miscellaneous</option>
                  </select>
                  <input
                    type="number"
                    required
                    min="1"
                    placeholder="Amount (₹)"
                    value={lineItemForm.estimated_amount}
                    onChange={(e) => setLineItemForm({ ...lineItemForm, estimated_amount: Number(e.target.value) })}
                    className="px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                  />
                  <button
                    type="submit"
                    disabled={savingLineItem}
                    className="btn-primary text-xs px-3 py-1.5 rounded flex items-center justify-center gap-1"
                  >
                    {savingLineItem ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                    Add Item
                  </button>
                </div>
              </form>

              <form onSubmit={handleSaveBudget} className="p-4 bg-surface-50 rounded-lg space-y-3">
                <span className="text-xs font-bold text-surface-800 block">Update Income &amp; Sanction Parameters</span>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[11px] text-surface-600 mb-1">Expected Income (₹)</label>
                    <input
                      type="number"
                      required
                      value={budgetForm.expected_income}
                      onChange={(e) => setBudgetForm({ ...budgetForm, expected_income: Number(e.target.value) })}
                      className="w-full px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-surface-600 mb-1">Institute Contribution (₹)</label>
                    <input
                      type="number"
                      required
                      value={budgetForm.institute_contribution}
                      onChange={(e) => setBudgetForm({ ...budgetForm, institute_contribution: Number(e.target.value) })}
                      className="w-full px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      type="submit"
                      disabled={savingBudget}
                      className="w-full btn-secondary text-xs py-2 rounded flex items-center justify-center gap-1 border border-surface-300"
                    >
                      {savingBudget && <Loader2 className="w-3 h-3 animate-spin" />} Update Budget Totals
                    </button>
                  </div>
                </div>
              </form>
            </div>
          )}
        </div>
      )}

      {/* Tab 4: Documents */}
      {activeTab === 'documents' && (
        <div className="card p-6 space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-surface-900">Secure Document Repository</h2>
              <p className="text-xs text-surface-500 mt-0.5">
                Upload event brochures, approval letters, budget sheets, and guest clearances.
              </p>
            </div>
          </div>

          {documents.length === 0 ? (
            <p className="text-xs text-surface-400 py-4 text-center">No documents uploaded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border border-surface-200 rounded-lg overflow-hidden">
                <thead className="bg-surface-50 text-surface-600 border-b border-surface-200">
                  <tr>
                    <th className="py-2.5 px-3">Filename</th>
                    <th className="py-2.5 px-3">Type</th>
                    <th className="py-2.5 px-3">Size</th>
                    <th className="py-2.5 px-3">Uploaded</th>
                    <th className="py-2.5 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-100">
                  {documents.map((doc) => (
                    <tr key={doc.id}>
                      <td className="py-2.5 px-3 font-medium text-surface-900 flex items-center gap-2">
                        <FileText className="w-4 h-4 text-surface-400 shrink-0" />
                        <span className="truncate max-w-xs">{doc.original_filename}</span>
                      </td>
                      <td className="py-2.5 px-3 text-surface-600">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-surface-100 text-surface-700">
                          {doc.document_type}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-surface-500">
                        {(doc.file_size_bytes / 1024).toFixed(1)} KB
                      </td>
                      <td className="py-2.5 px-3 text-surface-500">
                        {new Date(doc.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-2.5 px-3 text-right space-x-2">
                        <a
                          href={`http://localhost:8000/api/v1/events/${id}/documents/${doc.id}/download`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center text-primary-600 hover:text-primary-800 p-1"
                          title="Download Document"
                        >
                          <Download className="w-3.5 h-3.5" />
                        </a>
                        {isEditable && isSecretary && (
                          <button
                            onClick={() => handleDeleteDocument(doc.id)}
                            className="text-danger-600 hover:text-danger-800 p-1"
                            title="Delete"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Upload Form */}
          {isEditable && isSecretary && (
            <form onSubmit={handleUploadDocument} className="pt-4 border-t border-surface-200 space-y-3">
              <span className="text-xs font-bold text-surface-800 block">Upload Supporting Document</span>
              <p className="text-[11px] text-surface-500">
                Allowed formats: PDF, PNG, JPG, DOCX (Max 10 MB). Verified with magic bytes.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className="px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                >
                  <option value="EVENT_PLAN">Event Plan</option>
                  <option value="BUDGET_DETAILS">Budget Details</option>
                  <option value="AUTHORITY_LETTER">Authority Letter</option>
                  <option value="CHIEF_GUEST_PROFILE">Chief Guest Profile</option>
                  <option value="VENUE_LAYOUT">Venue Layout</option>
                  <option value="SUPPORTING">Supporting Document</option>
                  <option value="OTHER">Other</option>
                </select>

                <input
                  type="file"
                  required
                  accept=".pdf,.png,.jpg,.jpeg,.docx"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  className="text-xs file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-primary-50 file:text-primary-700 hover:file:bg-primary-100"
                />

                <button
                  type="submit"
                  disabled={uploadingDoc || !uploadFile}
                  className="btn-primary text-xs px-3 py-1.5 rounded flex items-center justify-center gap-1"
                >
                  {uploadingDoc ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                  Upload File
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Tab 5: Resources */}
      {activeTab === 'resources' && (
        <div className="card p-6 space-y-6">
          <div>
            <h2 className="text-sm font-bold text-surface-900">Campus Infrastructure &amp; Logistics Declaration</h2>
            <p className="text-xs text-surface-500 mt-0.5">
              Declare required institutional equipment, furniture, electrical, security, and transport support.
            </p>
          </div>

          {resources.length === 0 ? (
            <p className="text-xs text-surface-400 py-4 text-center">No resource requirements declared.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border border-surface-200 rounded-lg overflow-hidden">
                <thead className="bg-surface-50 text-surface-600 border-b border-surface-200">
                  <tr>
                    <th className="py-2.5 px-3">Resource Type</th>
                    <th className="py-2.5 px-3">Quantity</th>
                    <th className="py-2.5 px-3">Notes</th>
                    <th className="py-2.5 px-3">Status</th>
                    {isEditable && isSecretary && <th className="py-2.5 px-3 text-right">Action</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-100">
                  {resources.map((r) => (
                    <tr key={r.id}>
                      <td className="py-2.5 px-3 font-semibold text-surface-800">{r.resource_type}</td>
                      <td className="py-2.5 px-3 font-bold text-surface-900">{r.quantity}</td>
                      <td className="py-2.5 px-3 text-surface-500">{r.notes || '—'}</td>
                      <td className="py-2.5 px-3">
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface-100 text-surface-700">
                          {r.status}
                        </span>
                      </td>
                      {isEditable && isSecretary && (
                        <td className="py-2.5 px-3 text-right">
                          <button
                            onClick={() => handleDeleteResource(r.id)}
                            className="text-danger-600 hover:text-danger-800 p-1"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Declare Resource Form */}
          {isEditable && isSecretary && (
            <form onSubmit={handleAddResource} className="pt-4 border-t border-surface-200 space-y-3">
              <span className="text-xs font-bold text-surface-800 block">Declare Additional Resource</span>
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                <select
                  value={resourceForm.resource_type}
                  onChange={(e) => setResourceForm({ ...resourceForm, resource_type: e.target.value })}
                  className="px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                >
                  <option value="AUDIO_VISUAL">Audio Visual</option>
                  <option value="FURNITURE">Furniture (Chairs/Podium)</option>
                  <option value="SECURITY">Campus Security</option>
                  <option value="ELECTRICAL">Electrical &amp; Generator</option>
                  <option value="TRANSPORT">Transport</option>
                  <option value="CATERING">Catering Support</option>
                  <option value="OTHER">Other</option>
                </select>

                <input
                  type="number"
                  min="1"
                  required
                  placeholder="Quantity"
                  value={resourceForm.quantity}
                  onChange={(e) => setResourceForm({ ...resourceForm, quantity: Number(e.target.value) })}
                  className="px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                />

                <input
                  type="text"
                  placeholder="Notes (e.g. 50 plastic chairs)"
                  value={resourceForm.notes}
                  onChange={(e) => setResourceForm({ ...resourceForm, notes: e.target.value })}
                  className="px-3 py-1.5 text-xs rounded border border-surface-300 bg-white"
                />

                <button
                  type="submit"
                  disabled={savingResource}
                  className="btn-primary text-xs px-3 py-1.5 rounded flex items-center justify-center gap-1"
                >
                  {savingResource ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  Add Resource
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  )
}
