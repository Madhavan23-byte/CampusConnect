import React, { useEffect, useState, useCallback } from 'react'
import type { EventClosureDetailResponse, UserRole } from '@/types'
import {
  getCloseoutDetails,
  requestCloseout,
  certifyCloseout,
  rejectCloseout,
  requestReopen,
  approveReopen,
  archiveEvent,
} from '@/services/closeoutService'
import { CloseoutStatusCard } from './CloseoutStatusCard'
import { CloseoutReadinessCard } from './CloseoutReadinessCard'
import { CloseoutActions } from './CloseoutActions'
import { CloseoutHistoryTimeline } from './CloseoutHistoryTimeline'
import { CloseoutRequestDialog } from './CloseoutRequestDialog'
import { CloseoutCertificationDialog } from './CloseoutCertificationDialog'
import { CloseoutRejectionDialog } from './CloseoutRejectionDialog'
import { CloseoutReopenRequestDialog } from './CloseoutReopenRequestDialog'
import { CloseoutReopenApprovalDialog } from './CloseoutReopenApprovalDialog'
import { ArchiveEventDialog } from './ArchiveEventDialog'
import {
  Loader2,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  Lock,
  Archive,
  ShieldAlert,
} from 'lucide-react'

export interface CloseoutTabProps {
  eventId: string
  eventStatus: string
  confirmedEventStatus?: string
  userRole?: UserRole
  onEventUpdated?: () => Promise<void> | void
}

export const CloseoutTab: React.FC<CloseoutTabProps> = ({
  eventId,
  eventStatus,
  confirmedEventStatus,
  userRole,
  onEventUpdated,
}) => {
  void eventStatus
  void confirmedEventStatus
  const [details, setDetails] = useState<EventClosureDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)

  // Status alerts & error handling
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [conflictWarning, setConflictWarning] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [forbiddenError, setForbiddenError] = useState(false)
  const [notFoundError, setNotFoundError] = useState(false)

  // Dialog toggles
  const [isRequestOpen, setIsRequestOpen] = useState(false)
  const [isCertifyOpen, setIsCertifyOpen] = useState(false)
  const [isRejectOpen, setIsRejectOpen] = useState(false)
  const [isReopenRequestOpen, setIsReopenRequestOpen] = useState(false)
  const [isReopenApproveOpen, setIsReopenApproveOpen] = useState(false)
  const [isArchiveOpen, setIsArchiveOpen] = useState(false)

  const loadDetails = useCallback(
    async (isManualRefresh = false, preserveConflict = false) => {
      if (isManualRefresh) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      setErrorMessage(null)
      if (!preserveConflict) {
        setConflictWarning(null)
      }
      setForbiddenError(false)
      setNotFoundError(false)

      try {
        const data = await getCloseoutDetails(eventId)
        setDetails(data)
      } catch (err: unknown) {
        const e = err as { response?: { status?: number; data?: { message?: string; detail?: string } } }
        const status = e.response?.status
        const msg = e.response?.data?.message || e.response?.data?.detail || 'Failed to load event closeout details.'

        if (status === 403) {
          setForbiddenError(true)
        } else if (status === 404) {
          setNotFoundError(true)
        } else if (status === 409) {
          setConflictWarning('Event state conflict detected. Resynchronizing with institutional server state...')
        } else {
          setErrorMessage(msg)
        }
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [eventId]
  )

  useEffect(() => {
    loadDetails()
  }, [loadDetails])

  // Shared error extractor
  const handleMutationError = async (err: unknown, fallbackMessage: string) => {
    const e = err as { response?: { status?: number; data?: { message?: string; detail?: string } } }
    const status = e.response?.status
    const msg = e.response?.data?.message || e.response?.data?.detail || fallbackMessage

    if (status === 409) {
      setConflictWarning('A concurrent lifecycle update occurred. The view has been refreshed to the authoritative server state.')
      await loadDetails(true, true)
      if (onEventUpdated) {
        await onEventUpdated()
      }
    } else {
      setErrorMessage(msg)
    }
  }

  // Action 1: Secretary requests closeout
  const handleRequestCloseout = async (remarks?: string) => {
    if (actionLoading) return
    setActionLoading(true)
    setErrorMessage(null)
    setConflictWarning(null)
    setSuccessMessage(null)

    try {
      const res = await requestCloseout(eventId, { remarks })
      setSuccessMessage(res.message || 'Closeout petition submitted successfully.')
      setIsRequestOpen(false)
      await loadDetails(true)
      if (onEventUpdated) await onEventUpdated()
    } catch (err) {
      await handleMutationError(err, 'Failed to submit closeout petition.')
    } finally {
      setActionLoading(false)
    }
  }

  // Action 2: Certify closeout
  const handleCertifyCloseout = async (venueCleared: boolean, closureNotes?: string) => {
    if (actionLoading) return
    setActionLoading(true)
    setErrorMessage(null)
    setConflictWarning(null)
    setSuccessMessage(null)

    try {
      const res = await certifyCloseout(eventId, {
        venue_cleared: venueCleared,
        closure_notes: closureNotes,
      })
      setSuccessMessage(res.message || 'Event closeout certified successfully. All records locked.')
      setIsCertifyOpen(false)
      await loadDetails(true)
      if (onEventUpdated) await onEventUpdated()
    } catch (err) {
      await handleMutationError(err, 'Failed to certify closeout.')
    } finally {
      setActionLoading(false)
    }
  }

  // Action 3: Reject closeout
  const handleRejectCloseout = async (reason: string) => {
    if (actionLoading) return
    setActionLoading(true)
    setErrorMessage(null)
    setConflictWarning(null)
    setSuccessMessage(null)

    try {
      const res = await rejectCloseout(eventId, { reason })
      setSuccessMessage(res.message || 'Closeout request rejected. Event returned to operational state.')
      setIsRejectOpen(false)
      await loadDetails(true)
      if (onEventUpdated) await onEventUpdated()
    } catch (err) {
      await handleMutationError(err, 'Failed to reject closeout.')
    } finally {
      setActionLoading(false)
    }
  }

  // Action 4: Request reopening
  const handleRequestReopen = async (reason: string) => {
    if (actionLoading) return
    setActionLoading(true)
    setErrorMessage(null)
    setConflictWarning(null)
    setSuccessMessage(null)

    try {
      const res = await requestReopen(eventId, { reason })
      setSuccessMessage(res.message || 'Reopening petition submitted for executive review.')
      setIsReopenRequestOpen(false)
      await loadDetails(true)
      if (onEventUpdated) await onEventUpdated()
    } catch (err) {
      await handleMutationError(err, 'Failed to submit reopening petition.')
    } finally {
      setActionLoading(false)
    }
  }

  // Action 5: Approve reopening
  const handleApproveReopen = async (reason: string) => {
    if (actionLoading) return
    setActionLoading(true)
    setErrorMessage(null)
    setConflictWarning(null)
    setSuccessMessage(null)

    try {
      const res = await approveReopen(eventId, { reason })
      setSuccessMessage(res.message || 'Event successfully reopened for statutory amendments.')
      setIsReopenApproveOpen(false)
      await loadDetails(true)
      if (onEventUpdated) await onEventUpdated()
    } catch (err) {
      await handleMutationError(err, 'Failed to approve reopening.')
    } finally {
      setActionLoading(false)
    }
  }

  // Action 6: Archive event
  const handleArchiveEvent = async () => {
    if (actionLoading) return
    setActionLoading(true)
    setErrorMessage(null)
    setConflictWarning(null)
    setSuccessMessage(null)

    try {
      const res = await archiveEvent(eventId)
      setSuccessMessage(res.message || 'Event moved to permanent historical archive.')
      setIsArchiveOpen(false)
      await loadDetails(true)
      if (onEventUpdated) await onEventUpdated()
    } catch (err) {
      await handleMutationError(err, 'Failed to archive event.')
    } finally {
      setActionLoading(false)
    }
  }

  // Loading State
  if (loading) {
    return (
      <div
        data-testid="closeout-loading-state"
        className="card p-12 bg-white border border-surface-200 rounded-2xl flex flex-col items-center justify-center space-y-3"
      >
        <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
        <p className="text-xs font-semibold text-surface-600">
          Loading institutional event closeout governance state...
        </p>
      </div>
    )
  }

  // 403 Forbidden State
  if (forbiddenError) {
    return (
      <div
        data-testid="closeout-forbidden-state"
        className="card p-8 bg-white border border-danger-200 rounded-2xl space-y-3"
      >
        <div className="flex items-center gap-3 text-danger-700">
          <ShieldAlert className="w-6 h-6" />
          <h3 className="text-sm font-bold">Closeout Access Restricted (403)</h3>
        </div>
        <p className="text-xs text-surface-600 leading-relaxed">
          You do not have institutional authorization to inspect or execute closeout procedures for this event. Authorized roles include Club Secretary, assigned Faculty Advisor, Finance Officer, Dean of Student Affairs, Principal, and System Administrator.
        </p>
      </div>
    )
  }

  // 404 Not Found State
  if (notFoundError || !details) {
    return (
      <div
        data-testid="closeout-not-found-state"
        className="card p-8 bg-white border border-surface-200 rounded-2xl space-y-3 text-center"
      >
        <AlertCircle className="w-8 h-8 text-surface-400 mx-auto" />
        <h3 className="text-sm font-bold text-surface-800">Closeout Record Not Found</h3>
        <p className="text-xs text-surface-500 max-w-md mx-auto">
          No confirmed event closeout record could be retrieved for ID <span className="font-mono">{eventId}</span>. Ensure the event proposal has been approved and confirmed.
        </p>
        <div className="pt-2">
          <button
            type="button"
            onClick={() => loadDetails(true)}
            className="btn-outline text-xs px-4 py-2 rounded-xl inline-flex items-center gap-2"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </button>
        </div>
      </div>
    )
  }

  const isClosed = details.event_status === 'CLOSED'
  const isArchived = details.is_archived || details.event_status === 'ARCHIVED'
  const isClosedOrArchived = isClosed || isArchived

  return (
    <div className="space-y-6" data-testid="closeout-tab-container">
      {/* Top Controls & Refresh */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-surface-900">Event Closeout &amp; Governance</h2>
          <p className="text-xs text-surface-500">
            Statutory event completion, financial reconciliation lock, and archival record.
          </p>
        </div>
        <button
          type="button"
          data-testid="closeout-refresh-button"
          onClick={() => loadDetails(true)}
          disabled={refreshing || actionLoading}
          className="btn-outline text-xs px-3.5 py-1.5 rounded-xl flex items-center gap-1.5 text-surface-600 hover:text-surface-900 cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          <span>{refreshing ? 'Refreshing...' : 'Refresh State'}</span>
        </button>
      </div>

      {/* Global Read-Only Notice Banner */}
      {isClosed && !isArchived && (
        <div
          data-testid="closeout-closed-banner"
          className="p-4 bg-slate-900 text-white rounded-2xl flex items-center justify-between shadow-sm"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 bg-slate-800 text-emerald-400 rounded-xl">
              <Lock className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold tracking-wider uppercase text-emerald-400">
                  Event Closed &amp; Locked
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  Statutory Clearance Completed
                </span>
              </div>
              <p className="text-xs text-slate-300 mt-0.5">
                Event data is locked after institutional closeout. All operational modifications are disabled.
              </p>
            </div>
          </div>
        </div>
      )}

      {isArchived && (
        <div
          data-testid="closeout-archived-banner"
          className="p-4 bg-purple-950 text-white rounded-2xl flex items-center justify-between shadow-sm"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-900 text-purple-300 rounded-xl">
              <Archive className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold tracking-wider uppercase text-purple-300">
                  Event Archived
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                  Permanent Historical Record
                </span>
              </div>
              <p className="text-xs text-purple-200 mt-0.5">
                This event is retained as an immutable historical record. Operational modifications and reopenings are disabled.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 409 Conflict Warning Banner */}
      {conflictWarning && (
        <div
          data-testid="closeout-conflict-warning"
          className="p-4 bg-amber-50 border border-amber-300 rounded-xl flex items-start gap-3"
        >
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-0.5 text-xs text-amber-900">
            <p className="font-bold">Lifecycle State Conflict (HTTP 409)</p>
            <p>{conflictWarning}</p>
          </div>
        </div>
      )}

      {/* Success Banner */}
      {successMessage && (
        <div
          data-testid="closeout-success-message"
          className="p-4 bg-emerald-50 border border-emerald-300 rounded-xl flex items-start gap-3"
        >
          <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
          <div className="space-y-0.5 text-xs text-emerald-900">
            <p className="font-bold">Action Completed</p>
            <p>{successMessage}</p>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {errorMessage && (
        <div
          data-testid="closeout-error-message"
          className="p-4 bg-danger-50 border border-danger-300 rounded-xl flex items-start gap-3"
        >
          <AlertCircle className="w-5 h-5 text-danger-600 shrink-0 mt-0.5" />
          <div className="space-y-0.5 text-xs text-danger-900">
            <p className="font-bold">Closeout Operation Failed</p>
            <p>{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Primary Lifecycle Status Card */}
      <CloseoutStatusCard details={details} />

      {/* Statutory Eligibility & Blockers Card */}
      <CloseoutReadinessCard
        eligibility={details.eligibility}
        isClosedOrArchived={isClosedOrArchived}
      />

      {/* Role-based Action Buttons */}
      <CloseoutActions
        details={details}
        userRole={userRole}
        onOpenRequestDialog={() => setIsRequestOpen(true)}
        onOpenCertifyDialog={() => setIsCertifyOpen(true)}
        onOpenRejectDialog={() => setIsRejectOpen(true)}
        onOpenReopenRequestDialog={() => setIsReopenRequestOpen(true)}
        onOpenReopenApproveDialog={() => setIsReopenApproveOpen(true)}
        onOpenArchiveDialog={() => setIsArchiveOpen(true)}
        actionLoading={actionLoading}
      />

      {/* Audit History & Revisions Timeline */}
      <CloseoutHistoryTimeline details={details} />

      {/* Modal Dialogs */}
      <CloseoutRequestDialog
        isOpen={isRequestOpen}
        onClose={() => setIsRequestOpen(false)}
        onConfirm={handleRequestCloseout}
        submitting={actionLoading}
      />

      <CloseoutCertificationDialog
        isOpen={isCertifyOpen}
        onClose={() => setIsCertifyOpen(false)}
        onConfirm={handleCertifyCloseout}
        submitting={actionLoading}
      />

      <CloseoutRejectionDialog
        isOpen={isRejectOpen}
        onClose={() => setIsRejectOpen(false)}
        onConfirm={handleRejectCloseout}
        submitting={actionLoading}
      />

      <CloseoutReopenRequestDialog
        isOpen={isReopenRequestOpen}
        onClose={() => setIsReopenRequestOpen(false)}
        onConfirm={handleRequestReopen}
        submitting={actionLoading}
      />

      <CloseoutReopenApprovalDialog
        isOpen={isReopenApproveOpen}
        onClose={() => setIsReopenApproveOpen(false)}
        onConfirm={handleApproveReopen}
        submitting={actionLoading}
        petitionReason={details.latest_request?.remarks}
      />

      <ArchiveEventDialog
        isOpen={isArchiveOpen}
        onClose={() => setIsArchiveOpen(false)}
        onConfirm={handleArchiveEvent}
        submitting={actionLoading}
      />
    </div>
  )
}
