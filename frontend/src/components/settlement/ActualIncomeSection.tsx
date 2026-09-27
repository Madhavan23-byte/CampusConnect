import React, { useState } from 'react'
import { apiClient } from '@/lib/apiClient'
import type {
  ActualIncome,
  IncomeSourceType,
  EvidenceUploadResponse,
} from '@/types'
import {
  TrendingUp,
  Plus,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Download,
} from 'lucide-react'

interface ActualIncomeSectionProps {
  eventId: string
  incomes: ActualIncome[]
  isSecretary: boolean
  isFinanceOfficer: boolean
  onRefresh: () => Promise<void>
  setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void
}

const INCOME_SOURCES: IncomeSourceType[] = [
  'REGISTRATION_FEE',
  'SPONSORSHIP',
  'STALL_RENTAL',
  'TICKET_SALES',
  'DONATION',
  'OTHER',
]

export const ActualIncomeSection: React.FC<ActualIncomeSectionProps> = ({
  eventId,
  incomes,
  isSecretary,
  isFinanceOfficer,
  onRefresh,
  setMessage,
}) => {
  // Modal states
  const [showRecordModal, setShowRecordModal] = useState(false)
  const [verifyTarget, setVerifyTarget] = useState<ActualIncome | null>(null)
  const [rejectTarget, setRejectTarget] = useState<ActualIncome | null>(null)

  // Record Form state
  const [sourceType, setSourceType] = useState<IncomeSourceType>('REGISTRATION_FEE')
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const [payerName, setPayerName] = useState('')
  const [receivedDate, setReceivedDate] = useState(new Date().toISOString().split('T')[0])
  const [referenceNumber, setReferenceNumber] = useState('')

  // Evidence upload state
  const [uploadedEvidence, setUploadedEvidence] = useState<EvidenceUploadResponse | null>(null)
  const [uploadingEvidence, setUploadingEvidence] = useState(false)

  // Finance modal states
  const [financeRemarks, setFinanceRemarks] = useState('')
  const [rejectionReason, setRejectionReason] = useState('')

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

  // Handle Evidence File Upload
  const handleUploadEvidence = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadingEvidence(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await apiClient.post<EvidenceUploadResponse>(
        `/events/${eventId}/incomes/upload-evidence`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      setUploadedEvidence(res.data)
      setMessage({ type: 'success', text: 'Income evidence uploaded successfully.' })
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to upload income evidence document.',
      })
    } finally {
      setUploadingEvidence(false)
    }
  }

  // Handle Record Income Form Submit
  const handleRecordIncome = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadedEvidence) {
      setMessage({ type: 'error', text: 'Supporting evidence document is required.' })
      return
    }
    const amt = parseFloat(amount)
    if (isNaN(amt) || amt <= 0) {
      setMessage({ type: 'error', text: 'Amount must be greater than zero.' })
      return
    }
    if (description.trim().length < 3) {
      setMessage({ type: 'error', text: 'Description must be at least 3 characters.' })
      return
    }
    if (payerName.trim().length < 2) {
      setMessage({ type: 'error', text: 'Payer name must be at least 2 characters.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/incomes`, {
        source_type: sourceType,
        amount: amount.trim(),
        description: description.trim(),
        payer_name: payerName.trim(),
        received_date: receivedDate,
        evidence_document_id: uploadedEvidence.document_id,
        reference_number: referenceNumber.trim() || undefined,
      })
      setMessage({ type: 'success', text: 'Actual income recorded successfully.' })
      setShowRecordModal(false)
      // reset form
      setAmount('')
      setDescription('')
      setPayerName('')
      setReferenceNumber('')
      setUploadedEvidence(null)
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to record actual income.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Verify Income
  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!verifyTarget) return

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/incomes/${verifyTarget.id}/verify`, {
        finance_remarks: financeRemarks.trim() || undefined,
      })
      setMessage({ type: 'success', text: 'Actual income verified.' })
      setVerifyTarget(null)
      setFinanceRemarks('')
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to verify income.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  // Handle Reject Income
  const handleReject = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!rejectTarget) return
    if (rejectionReason.trim().length < 5) {
      setMessage({ type: 'error', text: 'Rejection reason must be at least 5 characters.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/incomes/${rejectTarget.id}/reject`, {
        rejection_reason: rejectionReason.trim(),
        finance_remarks: financeRemarks.trim() || undefined,
      })
      setMessage({ type: 'success', text: 'Actual income rejected.' })
      setRejectTarget(null)
      setRejectionReason('')
      setFinanceRemarks('')
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to reject income.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'RECORDED':
        return (
          <span className="badge bg-blue-100 text-blue-800 border border-blue-300">
            <Clock className="w-3 h-3 text-blue-600" /> Recorded
          </span>
        )
      case 'VERIFIED':
        return (
          <span className="badge bg-emerald-100 text-emerald-800 border border-emerald-300">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" /> Verified
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

  const getSourceBadge = (source: string) => {
    return (
      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface-100 text-surface-700 border border-surface-200 uppercase">
        {source.replace(/_/g, ' ')}
      </span>
    )
  }

  return (
    <div className="card p-5 bg-white border border-surface-200 space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-200 pb-3">
        <div>
          <h4 className="text-sm font-bold text-surface-900 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-blue-600" />
            Actual Income Ledger (Self-Generated Revenue)
          </h4>
          <p className="text-xs text-surface-500">
            Participant fees, sponsorships, and stall rents. Only verified income credits against deficit.
          </p>
        </div>

        {isSecretary && (
          <button
            onClick={() => setShowRecordModal(true)}
            className="btn-primary text-xs px-3.5 py-2 inline-flex items-center gap-1.5 self-start sm:self-auto"
          >
            <Plus className="w-3.5 h-3.5" /> Record Income
          </button>
        )}
      </div>

      {incomes.length === 0 ? (
        <div className="text-center py-6 text-xs text-surface-400">
          No actual income entries recorded for this event.
        </div>
      ) : (
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Source &amp; Description</th>
                <th>Payer</th>
                <th>Amount</th>
                <th>Received Date</th>
                <th>Evidence</th>
                <th>Status</th>
                {isFinanceOfficer && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {incomes.map((inc) => (
                <tr key={inc.id}>
                  <td>
                    <div className="space-y-1">
                      {getSourceBadge(inc.source_type)}
                      <p className="font-semibold text-xs text-surface-900">{inc.description}</p>
                      {inc.reference_number && (
                        <span className="text-[10px] text-surface-400 block">
                          Ref: {inc.reference_number}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="text-xs font-medium text-surface-700">{inc.payer_name}</td>
                  <td>
                    <span className="text-xs font-bold text-surface-900">
                      {formatCurrency(inc.amount)}
                    </span>
                  </td>
                  <td className="text-xs text-surface-600">
                    {new Date(inc.received_date).toLocaleDateString()}
                  </td>
                  <td>
                    <a
                      href={`/api/v1/documents/${inc.evidence_document_id}/download`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[11px] text-primary-600 hover:text-primary-800 font-medium"
                    >
                      <Download className="w-3 h-3" /> View Doc
                    </a>
                  </td>
                  <td>
                    <div className="space-y-0.5">
                      {getStatusBadge(inc.status)}
                      {inc.finance_remarks && (
                        <p className="text-[10px] text-surface-500 italic max-w-xs truncate">
                          {inc.finance_remarks}
                        </p>
                      )}
                    </div>
                  </td>
                  {isFinanceOfficer && (
                    <td>
                      {inc.status === 'RECORDED' ? (
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => {
                              setVerifyTarget(inc)
                              setFinanceRemarks('')
                            }}
                            className="btn-primary text-[11px] px-2.5 py-1"
                          >
                            Verify
                          </button>
                          <button
                            onClick={() => {
                              setRejectTarget(inc)
                              setRejectionReason('')
                              setFinanceRemarks('')
                            }}
                            className="btn-danger text-[11px] px-2.5 py-1"
                          >
                            Reject
                          </button>
                        </div>
                      ) : (
                        <span className="text-[10px] text-surface-400">Audited</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal: Record Income (Secretary) */}
      {showRecordModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4 overflow-y-auto">
          <div className="card max-w-lg w-full p-6 space-y-4 bg-white animate-slide-up my-8 max-h-[90vh] overflow-y-auto">
            <h3 className="text-base font-bold text-surface-900">Record Actual Event Income</h3>
            <p className="text-xs text-surface-500">
              Every income item requires authentic supporting documentation (receipt, bank slip, or passbook entry).
            </p>

            <form onSubmit={handleRecordIncome} className="space-y-3">
              {/* Evidence Upload */}
              <div className="p-3 bg-surface-50 rounded-lg border border-surface-200 space-y-2">
                <label className="form-label text-xs">
                  Supporting Evidence Document (.pdf, .png, .jpg) *
                </label>
                <input
                  type="file"
                  required={!uploadedEvidence}
                  accept=".pdf,.png,.jpg,.jpeg"
                  onChange={(e) => {
                                        handleUploadEvidence(e)
                  }}
                  className="w-full text-xs text-surface-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-primary-50 file:text-primary-700"
                />

                {uploadingEvidence && (
                  <div className="flex items-center gap-1.5 text-xs text-primary-600">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Uploading document...
                  </div>
                )}

                {uploadedEvidence && (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-700 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Uploaded: {uploadedEvidence.filename} ({(uploadedEvidence.file_size / 1024).toFixed(1)} KB)
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="form-label text-xs">Source Category *</label>
                  <select
                    value={sourceType}
                    onChange={(e) => setSourceType(e.target.value as IncomeSourceType)}
                    className="form-input text-xs"
                  >
                    {INCOME_SOURCES.map((s) => (
                      <option key={s} value={s}>
                        {s.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="form-label text-xs">Amount Received (₹) *</label>
                  <input
                    type="number"
                    step="0.01"
                    min="1"
                    required
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="e.g. 1500.00"
                    className="form-input text-xs"
                  />
                </div>
              </div>

              <div>
                <label className="form-label text-xs">Payer / Sponsor Name *</label>
                <input
                  type="text"
                  required
                  value={payerName}
                  onChange={(e) => setPayerName(e.target.value)}
                  placeholder="e.g. Acme Tech Solutions Pvt Ltd"
                  className="form-input text-xs"
                />
              </div>

              <div>
                <label className="form-label text-xs">Description &amp; Purpose *</label>
                <input
                  type="text"
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="e.g. Title sponsorship fee for hackathon"
                  className="form-input text-xs"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="form-label text-xs">Received Date *</label>
                  <input
                    type="date"
                    required
                    value={receivedDate}
                    onChange={(e) => setReceivedDate(e.target.value)}
                    className="form-input text-xs"
                  />
                </div>

                <div>
                  <label className="form-label text-xs">Ref / Receipt # (Optional)</label>
                  <input
                    type="text"
                    value={referenceNumber}
                    onChange={(e) => setReferenceNumber(e.target.value)}
                    placeholder="e.g. REC-2026-101"
                    className="form-input text-xs"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-surface-200">
                <button
                  type="button"
                  onClick={() => setShowRecordModal(false)}
                  disabled={submitting}
                  className="btn-secondary text-xs px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || uploadingEvidence || !uploadedEvidence}
                  className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Save Income Entry
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Verify Income (Finance) */}
      {verifyTarget && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-surface-900">Verify Actual Income</h3>
            <p className="text-xs text-surface-500">
              Confirm bank receipt of {formatCurrency(verifyTarget.amount)} from {verifyTarget.payer_name}.
            </p>

            <form onSubmit={handleVerify} className="space-y-3">
              <div>
                <label className="form-label text-xs">Finance Remarks (Optional)</label>
                <textarea
                  rows={3}
                  value={financeRemarks}
                  onChange={(e) => setFinanceRemarks(e.target.value)}
                  placeholder="e.g. Verified against bank statement entry on [date]..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setVerifyTarget(null)}
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
                  Confirm Verification
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Reject Income (Finance) */}
      {rejectTarget && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4 bg-white animate-slide-up">
            <h3 className="text-base font-bold text-danger-900">Reject Actual Income</h3>
            <p className="text-xs text-surface-500">
              Provide justification for disallowing this income claim ({formatCurrency(rejectTarget.amount)}).
            </p>

            <form onSubmit={handleReject} className="space-y-3">
              <div>
                <label className="form-label text-xs">Rejection Reason *</label>
                <textarea
                  required
                  rows={3}
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  placeholder="State reason (min 5 chars)..."
                  className="form-input text-xs"
                />
              </div>

              <div>
                <label className="form-label text-xs">Additional Finance Notes (Optional)</label>
                <textarea
                  rows={2}
                  value={financeRemarks}
                  onChange={(e) => setFinanceRemarks(e.target.value)}
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setRejectTarget(null)}
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
    </div>
  )
}
