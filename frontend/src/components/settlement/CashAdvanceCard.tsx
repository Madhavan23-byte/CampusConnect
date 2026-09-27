import React, { useState } from 'react'
import { apiClient } from '@/lib/apiClient'
import type { CashAdvance } from '@/types'
import {
  CreditCard,
  Plus,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Calendar,
  Tag,
} from 'lucide-react'

interface CashAdvanceCardProps {
  eventId: string
  advance: CashAdvance | null
  isSecretary: boolean
  isFinanceOfficer: boolean
  onRefresh: () => Promise<void>
  setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void
}

export const CashAdvanceCard: React.FC<CashAdvanceCardProps> = ({
  eventId,
  advance,
  isSecretary,
  isFinanceOfficer,
  onRefresh,
  setMessage,
}) => {
  // Modal states
  const [showRequestModal, setShowRequestModal] = useState(false)
  const [showApproveModal, setShowApproveModal] = useState(false)
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [showDisburseModal, setShowDisburseModal] = useState(false)

  // Form states
  const [amountRequested, setAmountRequested] = useState('')
  const [requestReason, setRequestReason] = useState('')

  const [amountApproved, setAmountApproved] = useState('')
  const [approveRemarks, setApproveRemarks] = useState('')

  const [rejectionReason, setRejectionReason] = useState('')

  const [amountDisbursed, setAmountDisbursed] = useState('')
  const [paymentReference, setPaymentReference] = useState('')
  const [disbursementDate, setDisbursementDate] = useState(
    new Date().toISOString().split('T')[0]
  )
  const [disburseNotes, setDisburseNotes] = useState('')

  const [submitting, setSubmitting] = useState(false)

  const formatCurrency = (val?: string | number | null) => {
    if (val === undefined || val === null || val === '') return '₹0.00'
    const num = typeof val === 'number' ? val : parseFloat(val)
    if (isNaN(num)) return '₹0.00'
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2,
    }).format(num)
  }

  // Handle Request Advance
  const handleRequest = async (e: React.FormEvent) => {
    e.preventDefault()
    const amt = parseFloat(amountRequested)
    if (isNaN(amt) || amt <= 0) {
      setMessage({ type: 'error', text: 'Requested amount must be greater than zero.' })
      return
    }
    if (requestReason.trim().length < 5) {
      setMessage({ type: 'error', text: 'Reason must be at least 5 characters.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/advances`, {
        amount_requested: amountRequested.trim(),
        reason: requestReason.trim(),
      })
      setMessage({ type: 'success', text: 'Cash advance requested successfully.' })
      setShowRequestModal(false)
      setAmountRequested('')
      setRequestReason('')
      await onRefresh()
    } catch (err: unknown) {
      const resp = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response
      const errData = resp?.data
      const detail = errData?.detail
      let text = 'Failed to request cash advance.'
      if (typeof detail === 'string') {
        text = detail
      } else if (Array.isArray(detail)) {
        text = detail
          .map((d: { msg?: string; message?: string }) => d.msg || d.message || '')
          .filter(Boolean)
          .join(', ')
      } else if (typeof errData?.message === 'string') {
        text = errData.message
      }
      setMessage({
        type: 'error',
        text,
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Approve Advance
  const handleApprove = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!advance) return
    const amt = parseFloat(amountApproved)
    if (isNaN(amt) || amt <= 0) {
      setMessage({ type: 'error', text: 'Approved amount must be greater than zero.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/advances/${advance.id}/approve`, {
        amount_approved: amountApproved.trim(),
        remarks: approveRemarks.trim() || undefined,
      })
      setMessage({ type: 'success', text: 'Cash advance approved successfully.' })
      setShowApproveModal(false)
      setAmountApproved('')
      setApproveRemarks('')
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to approve cash advance.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Reject Advance
  const handleReject = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!advance) return
    if (rejectionReason.trim().length < 5) {
      setMessage({ type: 'error', text: 'Rejection reason must be at least 5 characters.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/advances/${advance.id}/reject`, {
        rejection_reason: rejectionReason.trim(),
      })
      setMessage({ type: 'success', text: 'Cash advance rejected.' })
      setShowRejectModal(false)
      setRejectionReason('')
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to reject cash advance.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Disburse Advance
  const handleDisburse = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!advance) return
    const amt = parseFloat(amountDisbursed)
    if (isNaN(amt) || amt <= 0) {
      setMessage({ type: 'error', text: 'Disbursed amount must be greater than zero.' })
      return
    }
    if (!paymentReference.trim()) {
      setMessage({ type: 'error', text: 'Payment reference / transaction ID is mandatory.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/advances/${advance.id}/disburse`, {
        amount_disbursed: amountDisbursed.trim(),
        payment_reference: paymentReference.trim(),
        disbursement_date: new Date(disbursementDate).toISOString(),
        notes: disburseNotes.trim() || undefined,
      })
      setMessage({ type: 'success', text: 'Cash advance disbursed successfully.' })
      setShowDisburseModal(false)
      setAmountDisbursed('')
      setPaymentReference('')
      setDisburseNotes('')
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to disburse cash advance.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'REQUESTED':
        return (
          <span className="badge bg-amber-100 text-amber-800 border border-amber-300">
            <Clock className="w-3 h-3 text-amber-600" /> Requested
          </span>
        )
      case 'APPROVED':
        return (
          <span className="badge bg-blue-100 text-blue-800 border border-blue-300">
            <CheckCircle2 className="w-3 h-3 text-blue-600" /> Approved
          </span>
        )
      case 'DISBURSED':
        return (
          <span className="badge bg-emerald-100 text-emerald-800 border border-emerald-300">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" /> Disbursed
          </span>
        )
      case 'REJECTED':
        return (
          <span className="badge bg-red-100 text-red-800 border border-red-300">
            <XCircle className="w-3 h-3 text-red-600" /> Rejected
          </span>
        )
      default:
        return <span className="badge bg-surface-100">{status}</span>
    }
  }

  return (
    <div className="card p-5 bg-white border border-surface-200 space-y-4">
      <div className="flex items-center justify-between border-b border-surface-200 pb-3">
        <div>
          <h4 className="text-sm font-bold text-surface-900 flex items-center gap-2">
            <CreditCard className="w-4 h-4 text-orange-600" />
            Institutional Cash Advance
          </h4>
          <p className="text-xs text-surface-500">
            Pre-event liquidity requisition (Single advance per event policy).
          </p>
        </div>

        {advance && getStatusBadge(advance.status)}
      </div>

      {!advance ? (
        <div className="text-center py-6 space-y-3">
          <p className="text-xs text-surface-500">
            No cash advance requested for this event.
          </p>
          {isSecretary && (
            <button
              onClick={() => setShowRequestModal(true)}
              className="btn-primary text-xs px-3.5 py-2 inline-flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" /> Request Cash Advance
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-4 text-xs">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 p-3 bg-surface-50 rounded-lg border border-surface-200">
            <div>
              <span className="text-[10px] text-surface-400 block font-medium">Requested</span>
              <span className="font-bold text-surface-800">
                {formatCurrency(advance.amount_requested)}
              </span>
            </div>
            <div>
              <span className="text-[10px] text-surface-400 block font-medium">Approved</span>
              <span className="font-bold text-blue-700">
                {advance.amount_approved ? formatCurrency(advance.amount_approved) : 'Pending'}
              </span>
            </div>
            <div>
              <span className="text-[10px] text-surface-400 block font-medium">Disbursed</span>
              <span className="font-bold text-emerald-700">
                {formatCurrency(advance.amount_disbursed)}
              </span>
            </div>
          </div>

          {advance.notes && (
            <div className="text-surface-700 bg-surface-50 p-2.5 rounded border border-surface-200">
              <span className="font-bold block text-[11px] mb-0.5 text-surface-800">
                Justification:
              </span>
              <p className="italic text-[11px] text-surface-600">{advance.notes}</p>
            </div>
          )}

          {advance.payment_reference && (
            <div className="flex items-center gap-4 text-[11px] text-surface-600">
              <span className="flex items-center gap-1">
                <Tag className="w-3 h-3 text-surface-400" /> Ref: {advance.payment_reference}
              </span>
              {advance.disbursement_date && (
                <span className="flex items-center gap-1">
                  <Calendar className="w-3 h-3 text-surface-400" /> Date:{' '}
                  {new Date(advance.disbursement_date).toLocaleDateString()}
                </span>
              )}
            </div>
          )}

          {advance.rejection_reason && (
            <div className="p-2.5 bg-red-50 border border-red-200 rounded text-red-800 text-[11px]">
              <span className="font-bold block mb-0.5">Rejection Reason:</span>
              <p>{advance.rejection_reason}</p>
            </div>
          )}

          {/* Action Buttons for Finance Officer */}
          {isFinanceOfficer && (
            <div className="flex flex-wrap gap-2 pt-2 border-t border-surface-100">
              {advance.status === 'REQUESTED' && (
                <>
                  <button
                    onClick={() => {
                      setAmountApproved(advance.amount_requested)
                      setShowApproveModal(true)
                    }}
                    className="btn-primary text-xs px-3 py-1.5"
                  >
                    Approve Advance
                  </button>
                  <button
                    onClick={() => setShowRejectModal(true)}
                    className="btn-danger text-xs px-3 py-1.5"
                  >
                    Reject Advance
                  </button>
                </>
              )}

              {advance.status === 'APPROVED' && (
                <button
                  onClick={() => {
                    setAmountDisbursed(advance.amount_approved || advance.amount_requested)
                    setShowDisburseModal(true)
                  }}
                  className="btn-primary text-xs px-3 py-1.5"
                >
                  Disburse Funds
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Modal: Request Advance (Secretary) */}
      {showRequestModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-surface-900">Request Cash Advance</h3>
            <p className="text-xs text-surface-500">
              Advance is limited to policy guidelines and sanctioned event grant.
            </p>

            <form onSubmit={handleRequest} className="space-y-3">
              <div>
                <label className="form-label text-xs">Amount Requested (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  min="1"
                  value={amountRequested}
                  onChange={(e) => setAmountRequested(e.target.value)}
                  placeholder="e.g. 5000"
                  className="form-input text-xs"
                />
              </div>

              <div>
                <label className="form-label text-xs">Reason & Justification</label>
                <textarea
                  required
                  rows={3}
                  value={requestReason}
                  onChange={(e) => setRequestReason(e.target.value)}
                  placeholder="Explain why pre-event advance is required (min 5 chars)..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowRequestModal(false)}
                  disabled={submitting}
                  className="btn-secondary text-xs px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Submit Request
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Approve Advance (Finance) */}
      {showApproveModal && advance && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-surface-900">Approve Cash Advance</h3>
            <p className="text-xs text-surface-500">
              Sanction amount requested ({formatCurrency(advance.amount_requested)}).
            </p>

            <form onSubmit={handleApprove} className="space-y-3">
              <div>
                <label className="form-label text-xs">Amount Approved (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  min="1"
                  value={amountApproved}
                  onChange={(e) => setAmountApproved(e.target.value)}
                  className="form-input text-xs"
                />
              </div>

              <div>
                <label className="form-label text-xs">Remarks (Optional)</label>
                <textarea
                  rows={2}
                  value={approveRemarks}
                  onChange={(e) => setApproveRemarks(e.target.value)}
                  placeholder="Notes for club records..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowApproveModal(false)}
                  disabled={submitting}
                  className="btn-secondary text-xs px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Confirm Approval
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Reject Advance (Finance) */}
      {showRejectModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-danger-900">Reject Cash Advance</h3>
            <p className="text-xs text-surface-500">
              State the regulatory or financial reason for rejecting this advance.
            </p>

            <form onSubmit={handleReject} className="space-y-3">
              <div>
                <label className="form-label text-xs">Rejection Reason</label>
                <textarea
                  required
                  rows={3}
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  placeholder="Provide audit reason (min 5 chars)..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowRejectModal(false)}
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
                  Confirm Rejection
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Disburse Advance (Finance) */}
      {showDisburseModal && advance && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-surface-900">Disburse Cash Advance</h3>
            <p className="text-xs text-surface-500">
              Record bank transaction or voucher disbursement details.
            </p>

            <form onSubmit={handleDisburse} className="space-y-3">
              <div>
                <label className="form-label text-xs">Amount Disbursed (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  min="1"
                  value={amountDisbursed}
                  onChange={(e) => setAmountDisbursed(e.target.value)}
                  className="form-input text-xs"
                />
              </div>

              <div>
                <label className="form-label text-xs">Payment Reference / UTR Number</label>
                <input
                  type="text"
                  required
                  value={paymentReference}
                  onChange={(e) => setPaymentReference(e.target.value)}
                  placeholder="e.g. UTR-2026-BANK-001"
                  className="form-input text-xs"
                />
              </div>

              <div>
                <label className="form-label text-xs">Disbursement Date</label>
                <input
                  type="date"
                  required
                  value={disbursementDate}
                  onChange={(e) => setDisbursementDate(e.target.value)}
                  className="form-input text-xs"
                />
              </div>

              <div>
                <label className="form-label text-xs">Notes (Optional)</label>
                <textarea
                  rows={2}
                  value={disburseNotes}
                  onChange={(e) => setDisburseNotes(e.target.value)}
                  placeholder="Disbursement remarks..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowDisburseModal(false)}
                  disabled={submitting}
                  className="btn-secondary text-xs px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Confirm Disbursement
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
