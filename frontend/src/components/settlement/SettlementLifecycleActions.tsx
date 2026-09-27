import React, { useState } from 'react'
import { apiClient } from '@/lib/apiClient'
import type { FinancialSettlement } from '@/types'
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  RotateCcw,
  Send,
  Loader2,
  RefreshCw,
  Scale,
} from 'lucide-react'

interface SettlementLifecycleActionsProps {
  eventId: string
  settlement: FinancialSettlement | null
  isSecretary: boolean
  isFinanceOfficer: boolean
  isPrincipal: boolean
  isStale: boolean
  onRefresh: () => Promise<void>
  setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void
}

export const SettlementLifecycleActions: React.FC<SettlementLifecycleActionsProps> = ({
  eventId,
  settlement,
  isSecretary,
  isFinanceOfficer,
  isPrincipal,
  isStale,
  onRefresh,
  setMessage,
}) => {
  // Modal states
  const [showAuditModal, setShowAuditModal] = useState(false)
  const [auditAction, setAuditAction] = useState<'APPROVE' | 'QUERY'>('APPROVE')
  const [auditRemarks, setAuditRemarks] = useState('')
  const [queryReason, setQueryReason] = useState('')

  const [showReopenModal, setShowReopenModal] = useState(false)
  const [reopeningReason, setReopeningReason] = useState('')

  const [submitting, setSubmitting] = useState(false)

  // Handle Prepare / Recalculate
  const handlePrepare = async () => {
    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/settlement/prepare`)
      setMessage({
        type: 'success',
        text: 'Settlement calculated and source snapshot locked.',
      })
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to prepare settlement.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Submit to Finance
  const handleSubmit = async () => {
    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/settlement/submit`)
      setMessage({
        type: 'success',
        text: 'Financial settlement submitted to Finance for audit review.',
      })
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to submit settlement.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Finance Audit Submit (Approve or Query)
  const handleAudit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (auditAction === 'QUERY' && queryReason.trim().length < 5) {
      setMessage({ type: 'error', text: 'Query reason must be at least 5 characters.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/settlement/audit`, {
        action: auditAction,
        remarks: auditRemarks.trim() || undefined,
        query_reason: auditAction === 'QUERY' ? queryReason.trim() : undefined,
      })
      setMessage({
        type: 'success',
        text:
          auditAction === 'APPROVE'
            ? 'Financial settlement audited and approved.'
            : 'Audit query raised. Returned to Club Secretary for amendment.',
      })
      setShowAuditModal(false)
      setAuditRemarks('')
      setQueryReason('')
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to audit settlement.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Reopen
  const handleReopen = async (e: React.FormEvent) => {
    e.preventDefault()
    if (reopeningReason.trim().length < 5) {
      setMessage({ type: 'error', text: 'Reopening reason must be at least 5 characters.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/settlement/reopen`, {
        reopening_reason: reopeningReason.trim(),
      })
      setMessage({
        type: 'success',
        text: 'Settlement reopened for revisions. Immutable audit snapshot created.',
      })
      setShowReopenModal(false)
      setReopeningReason('')
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to reopen settlement.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-3">
      {/* 409 Stale Data Conflict Alert */}
      {isStale && (
        <div className="p-4 bg-amber-50 border border-amber-300 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <h4 className="text-xs font-bold text-amber-900">
                Financial Data Outdated (Conflict 409)
              </h4>
              <p className="text-xs text-amber-800 mt-0.5">
                Underlying verified expenses, incomes, or cash advance records changed while this settlement was under review.
                The settlement cryptographic fingerprint is stale. Recalculate before proceeding.
              </p>
            </div>
          </div>
          {isSecretary && (
            <button
              onClick={handlePrepare}
              disabled={submitting}
              className="btn-primary text-xs px-3.5 py-1.5 flex items-center gap-1.5 shrink-0"
            >
              {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Recalculate Settlement
            </button>
          )}
        </div>
      )}

      {/* Query Notice if Status is QUERIED */}
      {settlement && settlement.status === 'QUERIED' && (
        <div className="p-4 bg-red-50 border border-red-300 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="text-xs font-bold text-red-900">Finance Audit Query Raised</h4>
            <p className="text-xs text-red-800 italic">"{settlement.query_reason}"</p>
            <p className="text-[11px] text-red-700">
              Please review your actual expense invoices or income records, make necessary updates, then click Recalculate to generate an amended settlement draft.
            </p>
          </div>
        </div>
      )}

      {/* Unprepared Onboarding Card (404) */}
      {!settlement && (
        <div className="card p-6 bg-surface-50 border border-surface-200 text-center space-y-3">
          <Scale className="w-8 h-8 text-surface-400 mx-auto" />
          <div className="space-y-1">
            <h4 className="text-sm font-bold text-surface-800">Financial Settlement Not Prepared</h4>
            <p className="text-xs text-surface-500 max-w-md mx-auto">
              Once actual expenses are audited and event incomes are recorded, the Club Secretary prepares the institutional settlement.
            </p>
          </div>
          {isSecretary && (
            <button
              onClick={handlePrepare}
              disabled={submitting}
              className="btn-primary text-xs px-4 py-2 inline-flex items-center gap-2"
            >
              {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Prepare Draft Settlement
            </button>
          )}
        </div>
      )}

      {/* Action Bar for Prepared Settlement */}
      {settlement && (
        <div className="card p-4 bg-white border border-surface-200 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-surface-600">
            <span className="font-semibold text-surface-800">Current Phase:</span>{' '}
            <span className="capitalize">{settlement.status.toLowerCase().replace(/_/g, ' ')}</span>
            {settlement.submitted_at && (
              <span className="text-surface-400 ml-2">
                (Submitted: {new Date(settlement.submitted_at).toLocaleDateString()})
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Secretary Controls */}
            {isSecretary && (
              <>
                {(settlement.status === 'DRAFT' || settlement.status === 'QUERIED' || settlement.status === 'REOPENED') && (
                  <button
                    onClick={handlePrepare}
                    disabled={submitting}
                    className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
                    title="Recalculate figures against latest verified expenses and incomes"
                  >
                    {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                    Recalculate Draft
                  </button>
                )}

                {settlement.status === 'DRAFT' && (
                  <button
                    onClick={handleSubmit}
                    disabled={submitting || isStale}
                    className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5 shadow-sm"
                  >
                    {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                    Submit for Finance Audit
                  </button>
                )}
              </>
            )}

            {/* Finance Officer Audit Controls */}
            {isFinanceOfficer && settlement.status === 'UNDER_AUDIT' && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    setAuditAction('APPROVE')
                    setAuditRemarks('')
                    setQueryReason('')
                    setShowAuditModal(true)
                  }}
                  className="btn-primary text-xs px-3.5 py-1.5 flex items-center gap-1.5"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" /> Approve Settlement
                </button>
                <button
                  onClick={() => {
                    setAuditAction('QUERY')
                    setAuditRemarks('')
                    setQueryReason('')
                    setShowAuditModal(true)
                  }}
                  className="btn-danger text-xs px-3.5 py-1.5 flex items-center gap-1.5"
                >
                  <AlertCircle className="w-3.5 h-3.5" /> Raise Audit Query
                </button>
              </div>
            )}

            {/* Reopen Controls for Finance Officer or Principal on SETTLED */}
            {(isFinanceOfficer || isPrincipal) && settlement.status === 'SETTLED' && (
              <button
                onClick={() => {
                  setReopeningReason('')
                  setShowReopenModal(true)
                }}
                className="btn-secondary text-xs px-3.5 py-1.5 flex items-center gap-1.5 text-orange-700 hover:bg-orange-50 border-orange-300"
              >
                <RotateCcw className="w-3.5 h-3.5 text-orange-600" /> Reopen Account
              </button>
            )}
          </div>
        </div>
      )}

      {/* Modal: Finance Audit (Approve or Query) */}
      {showAuditModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-surface-900">
              {auditAction === 'APPROVE' ? 'Approve Financial Settlement' : 'Raise Audit Query'}
            </h3>
            <p className="text-xs text-surface-500">
              {auditAction === 'APPROVE'
                ? 'Confirm cumulative reconciliation. Account will proceed to reimbursement/refund liquidation or settlement.'
                : 'Return settlement to Club Secretary with specific instructions or discrepancies.'}
            </p>

            <form onSubmit={handleAudit} className="space-y-3">
              {auditAction === 'QUERY' && (
                <div>
                  <label className="form-label text-xs">Query Reason *</label>
                  <textarea
                    required
                    rows={3}
                    value={queryReason}
                    onChange={(e) => setQueryReason(e.target.value)}
                    placeholder="Specify the discrepancy or missing evidence (min 5 chars)..."
                    className="form-input text-xs"
                  />
                </div>
              )}

              <div>
                <label className="form-label text-xs">Finance Remarks (Optional)</label>
                <textarea
                  rows={2}
                  value={auditRemarks}
                  onChange={(e) => setAuditRemarks(e.target.value)}
                  placeholder="Audit observations or notes..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAuditModal(false)}
                  disabled={submitting}
                  className="btn-secondary text-xs px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className={
                    auditAction === 'APPROVE'
                      ? 'btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5'
                      : 'btn-danger text-xs px-4 py-1.5 flex items-center gap-1.5'
                  }
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {auditAction === 'APPROVE' ? 'Confirm Approval' : 'Send Audit Query'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Reopen Settlement */}
      {showReopenModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-orange-900 flex items-center gap-2">
              <RotateCcw className="w-4 h-4 text-orange-600" />
              Reopen Settled Settlement
            </h3>
            <div className="p-3 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800 space-y-1">
              <p className="font-semibold">Notice of Financial Revision:</p>
              <p>
                Reopening a settled financial account creates a new immutable revision and may change the outstanding reimbursement/refund position.
              </p>
            </div>

            <form onSubmit={handleReopen} className="space-y-3">
              <div>
                <label className="form-label text-xs">Reopening Justification *</label>
                <textarea
                  required
                  rows={3}
                  value={reopeningReason}
                  onChange={(e) => setReopeningReason(e.target.value)}
                  placeholder="State the audit justification (e.g., late invoice submission, clawback discovery) (min 5 chars)..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowReopenModal(false)}
                  disabled={submitting}
                  className="btn-secondary text-xs px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="btn-danger text-xs px-4 py-1.5 flex items-center gap-1.5"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Confirm Reopen
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
