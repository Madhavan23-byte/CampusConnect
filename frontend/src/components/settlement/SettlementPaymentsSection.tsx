import React, { useState } from 'react'
import { apiClient } from '@/lib/apiClient'
import type {
  FinancialSettlement,
  SettlementPayment,
  SettlementPaymentType,
  PaymentMethod,
  EvidenceUploadResponse,
} from '@/types'
import {
  DollarSign,
  Plus,
  CheckCircle2,
  TrendingUp,
  TrendingDown,
  Download,
  Loader2,
} from 'lucide-react'

interface SettlementPaymentsSectionProps {
  eventId: string
  settlement: FinancialSettlement | null
  payments: SettlementPayment[]
  isFinanceOfficer: boolean
  onRefresh: () => Promise<void>
  setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void
}

const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'BANK_TRANSFER_NEFT', label: 'Bank Transfer (NEFT / RTGS)' },
  { value: 'CHEQUE', label: 'Institutional Cheque' },
  { value: 'CASH_VOUCHER', label: 'Treasury Cash Voucher' },
  { value: 'INSTITUTIONAL_TRANSFER', label: 'Internal Ledger Transfer' },
]

export const SettlementPaymentsSection: React.FC<SettlementPaymentsSectionProps> = ({
  eventId,
  settlement,
  payments,
  isFinanceOfficer,
  onRefresh,
  setMessage,
}) => {
  const [showPaymentModal, setShowPaymentModal] = useState(false)

  // Payment form states
  const [paymentType, setPaymentType] = useState<SettlementPaymentType>(
    settlement?.settlement_type === 'REFUND_DUE'
      ? 'ADVANCE_REFUND_RECEIPT'
      : 'REIMBURSEMENT_DISBURSEMENT'
  )
  const [amount, setAmount] = useState('')
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('BANK_TRANSFER_NEFT')
  const [transactionReference, setTransactionReference] = useState('')
  const [transactionDate, setTransactionDate] = useState(
    new Date().toISOString().split('T')[0]
  )
  const [notes, setNotes] = useState('')

  // Proof upload state
  const [uploadedProof, setUploadedProof] = useState<EvidenceUploadResponse | null>(null)
  const [uploadingProof, setUploadingProof] = useState(false)

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

  // Handle Proof Upload
  const handleUploadProof = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadingProof(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await apiClient.post<EvidenceUploadResponse>(
        `/events/${eventId}/settlement/upload-proof`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      setUploadedProof(res.data)
      setMessage({ type: 'success', text: 'Payment proof voucher uploaded.' })
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to upload payment proof document.',
      })
    } finally {
      setUploadingProof(false)
    }
  }

  // Open Payment Modal
  const handleOpenModal = () => {
    if (!settlement) return
    const isRefund = settlement.settlement_type === 'REFUND_DUE'
    setPaymentType(isRefund ? 'ADVANCE_REFUND_RECEIPT' : 'REIMBURSEMENT_DISBURSEMENT')
    setAmount(
      isRefund ? settlement.refund_due || '0.00' : settlement.reimbursement_due || '0.00'
    )
    setUploadedProof(null)
    setTransactionReference('')
    setNotes('')
    setShowPaymentModal(true)
  }

  // Handle Record Payment Submit
  const handleRecordPayment = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadedProof) {
      setMessage({ type: 'error', text: 'Supporting payment proof voucher is required.' })
      return
    }
    const amt = parseFloat(amount)
    if (isNaN(amt) || amt <= 0) {
      setMessage({ type: 'error', text: 'Payment amount must be greater than zero.' })
      return
    }
    if (!transactionReference.trim()) {
      setMessage({ type: 'error', text: 'Transaction reference is required.' })
      return
    }

    setSubmitting(true)
    try {
      await apiClient.post(`/events/${eventId}/settlement/payments`, {
        payment_type: paymentType,
        amount: amount.trim(),
        payment_method: paymentMethod,
        transaction_reference: transactionReference.trim(),
        transaction_date: new Date(transactionDate).toISOString(),
        proof_document_id: uploadedProof.document_id,
        notes: notes.trim() || undefined,
      })
      setMessage({ type: 'success', text: 'Settlement transaction recorded successfully.' })
      setShowPaymentModal(false)
      await onRefresh()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setMessage({
        type: 'error',
        text: e.response?.data?.message || 'Failed to record settlement payment.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  if (!settlement) return null

  const isPendingReimbursement = settlement.status === 'PENDING_REIMBURSEMENT'
  const isPendingRefund = settlement.status === 'PENDING_REFUND'
  const canRecordPayment = isFinanceOfficer && (isPendingReimbursement || isPendingRefund)

  return (
    <div className="card p-5 bg-white border border-surface-200 space-y-4">
      {/* Directional Settlement Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-200 pb-3">
        <div>
          <h4 className="text-sm font-bold text-surface-900 flex items-center gap-2">
            <DollarSign className="w-4 h-4 text-emerald-600" />
            Settlement Liquidation &amp; Payment Ledger
          </h4>
          <p className="text-xs text-surface-500">
            Institutional disbursements and refund receipts with audit-verified vouchers.
          </p>
        </div>

        {canRecordPayment && (
          <button
            onClick={handleOpenModal}
            className="btn-primary text-xs px-3.5 py-2 inline-flex items-center gap-1.5 self-start sm:self-auto"
          >
            <Plus className="w-3.5 h-3.5" />
            {isPendingRefund ? 'Record Refund Receipt' : 'Record Reimbursement Payment'}
          </button>
        )}
      </div>

      {/* Direction Status Callout */}
      <div
        className={`p-4 rounded-xl border flex items-start gap-3.5 ${
          settlement.settlement_type === 'REIMBURSEMENT_DUE'
            ? 'bg-purple-50/70 border-purple-200 text-purple-900'
            : settlement.settlement_type === 'REFUND_DUE'
            ? 'bg-amber-50/70 border-amber-200 text-amber-900'
            : 'bg-emerald-50/70 border-emerald-200 text-emerald-900'
        }`}
      >
        <div className="p-2 bg-white rounded-lg shadow-xs shrink-0">
          {settlement.settlement_type === 'REIMBURSEMENT_DUE' ? (
            <TrendingUp className="w-5 h-5 text-purple-600" />
          ) : settlement.settlement_type === 'REFUND_DUE' ? (
            <TrendingDown className="w-5 h-5 text-amber-600" />
          ) : (
            <CheckCircle2 className="w-5 h-5 text-emerald-600" />
          )}
        </div>

        <div className="space-y-0.5 flex-1">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-xs font-bold uppercase tracking-wider">
              {settlement.settlement_type === 'REIMBURSEMENT_DUE'
                ? 'Direction: Institution → Club (Reimbursement Payable)'
                : settlement.settlement_type === 'REFUND_DUE'
                ? 'Direction: Club → Institution (Unexpended Advance Refund)'
                : 'Account Position: Balanced (₹0.00 Outstanding)'}
            </span>
            <span className="text-sm font-extrabold">
              {settlement.settlement_type === 'REIMBURSEMENT_DUE'
                ? formatCurrency(settlement.reimbursement_due)
                : settlement.settlement_type === 'REFUND_DUE'
                ? formatCurrency(settlement.refund_due)
                : '₹0.00'}
            </span>
          </div>
          <p className="text-xs opacity-90">
            {settlement.settlement_type === 'REIMBURSEMENT_DUE'
              ? 'Institutional funds owed to student organizers for approved out-of-pocket event deficit.'
              : settlement.settlement_type === 'REFUND_DUE'
              ? 'Unspent cash advance funds required to be returned and credited back to the central institution treasury.'
              : 'All approved costs have been precisely offset by revenue and disbursed advance.'}
          </p>
        </div>
      </div>

      {/* Payment Transactions Table */}
      {payments.length === 0 ? (
        <div className="text-center py-6 text-xs text-surface-400">
          No settlement payments or refund vouchers recorded yet.
        </div>
      ) : (
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Payment Type</th>
                <th>Amount</th>
                <th>Method</th>
                <th>Reference / UTR</th>
                <th>Date</th>
                <th>Proof Voucher</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id}>
                  <td>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        p.payment_type === 'REIMBURSEMENT_DISBURSEMENT'
                          ? 'bg-purple-100 text-purple-800'
                          : 'bg-amber-100 text-amber-800'
                      }`}
                    >
                      {p.payment_type === 'REIMBURSEMENT_DISBURSEMENT'
                        ? 'Reimbursement'
                        : 'Advance Refund'}
                    </span>
                  </td>
                  <td>
                    <span className="text-xs font-bold text-surface-900">
                      {formatCurrency(p.amount)}
                    </span>
                  </td>
                  <td className="text-xs text-surface-700">
                    {p.payment_method.replace(/_/g, ' ')}
                  </td>
                  <td className="text-xs font-mono text-surface-800">
                    {p.transaction_reference}
                  </td>
                  <td className="text-xs text-surface-600">
                    {new Date(p.transaction_date).toLocaleDateString()}
                  </td>
                  <td>
                    <a
                      href={`/api/v1/documents/${p.proof_document_id}/download`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[11px] text-primary-600 hover:text-primary-800 font-medium"
                    >
                      <Download className="w-3 h-3" /> View Voucher
                    </a>
                  </td>
                  <td className="text-xs text-surface-500 italic max-w-xs truncate">
                    {p.notes || '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal: Record Settlement Payment (Finance Officer) */}
      {showPaymentModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4 overflow-y-auto">
          <div className="card max-w-lg w-full p-6 space-y-4 bg-white animate-slide-up my-8 max-h-[90vh] overflow-y-auto">
            <h3 className="text-base font-bold text-surface-900">
              Record Settlement Transaction
            </h3>
            <p className="text-xs text-surface-500">
              Liquidation transaction must strictly align with current settlement balance.
            </p>

            <form onSubmit={handleRecordPayment} className="space-y-3">
              {/* Proof Document Upload */}
              <div className="p-3 bg-surface-50 rounded-lg border border-surface-200 space-y-2">
                <label className="form-label text-xs">
                  Official Bank Proof Voucher / Receipt (.pdf, .png, .jpg) *
                </label>
                <input
                  type="file"
                  required={!uploadedProof}
                  accept=".pdf,.png,.jpg,.jpeg"
                  onChange={(e) => {
                                        handleUploadProof(e)
                  }}
                  className="w-full text-xs text-surface-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-primary-50 file:text-primary-700"
                />

                {uploadingProof && (
                  <div className="flex items-center gap-1.5 text-xs text-primary-600">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Uploading voucher...
                  </div>
                )}

                {uploadedProof && (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-700 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Uploaded: {uploadedProof.filename} ({(uploadedProof.file_size / 1024).toFixed(1)} KB)
                  </div>
                )}
              </div>

              {/* Payment Type (Strictly locked to settlement direction) */}
              <div>
                <label className="form-label text-xs">Transaction Direction *</label>
                <input
                  type="text"
                  disabled
                  value={
                    paymentType === 'REIMBURSEMENT_DISBURSEMENT'
                      ? 'Reimbursement Disbursement (Institution → Club)'
                      : 'Advance Refund Receipt (Club → Institution)'
                  }
                  className="form-input text-xs bg-surface-100 font-semibold cursor-not-allowed"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="form-label text-xs">Amount (₹) *</label>
                  <input
                    type="number"
                    step="0.01"
                    min="1"
                    required
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    className="form-input text-xs"
                  />
                </div>

                <div>
                  <label className="form-label text-xs">Payment Method *</label>
                  <select
                    value={paymentMethod}
                    onChange={(e) => setPaymentMethod(e.target.value as PaymentMethod)}
                    className="form-input text-xs"
                  >
                    {PAYMENT_METHODS.map((m) => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="form-label text-xs">UTR / Transaction Reference *</label>
                  <input
                    type="text"
                    required
                    value={transactionReference}
                    onChange={(e) => setTransactionReference(e.target.value)}
                    placeholder="e.g. UTR-2026-NEFT-991"
                    className="form-input text-xs"
                  />
                </div>

                <div>
                  <label className="form-label text-xs">Transaction Date *</label>
                  <input
                    type="date"
                    required
                    value={transactionDate}
                    onChange={(e) => setTransactionDate(e.target.value)}
                    className="form-input text-xs"
                  />
                </div>
              </div>

              <div>
                <label className="form-label text-xs">Notes (Optional)</label>
                <textarea
                  rows={2}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Treasury reference or liquidation remarks..."
                  className="form-input text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-surface-200">
                <button
                  type="button"
                  onClick={() => setShowPaymentModal(false)}
                  disabled={submitting}
                  className="btn-secondary text-xs px-3 py-1.5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || uploadingProof || !uploadedProof}
                  className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Confirm Transaction
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
