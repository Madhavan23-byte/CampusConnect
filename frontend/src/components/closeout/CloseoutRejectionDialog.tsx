import React, { useState } from 'react'
import { XCircle, Loader2, X } from 'lucide-react'

interface CloseoutRejectionDialogProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (reason: string) => Promise<void>
  submitting: boolean
}

export const CloseoutRejectionDialog: React.FC<CloseoutRejectionDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  submitting,
}) => {
  const [reason, setReason] = useState('')

  if (!isOpen) return null

  const trimmed = reason.trim()
  const isValid = trimmed.length >= 5

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!isValid || submitting) return
    await onConfirm(trimmed)
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="reject-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-fade-in"
    >
      <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-surface-200 space-y-5">
        <div className="flex items-center justify-between border-b border-surface-100 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-danger-100 text-danger-700 rounded-lg">
              <XCircle className="w-5 h-5" />
            </div>
            <h3 id="reject-dialog-title" className="text-base font-bold text-surface-900">
              Reject Closeout Request
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="text-surface-400 hover:text-surface-700 p-1 rounded-lg"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <p className="text-xs text-surface-600 leading-relaxed">
          Rejecting the closeout petition returns the event to the{' '}
          <strong className="text-surface-900 font-semibold">COMPLETED</strong> state, allowing the club to resolve issues. An institutional justification is required.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="rejection-reason" className="block text-xs font-bold text-surface-700 mb-1">
              Rejection Justification <span className="text-danger-600">*</span>
            </label>
            <textarea
              id="rejection-reason"
              rows={4}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={submitting}
              placeholder="Specify the unresolved items or deficiencies that must be addressed (min. 5 characters)..."
              className="w-full text-xs p-3 border border-surface-300 rounded-xl focus:ring-2 focus:ring-danger-500/20 focus:border-danger-600 outline-none"
            />
            <div className="flex justify-between items-center text-[11px] mt-1">
              <span className={trimmed.length < 5 ? 'text-amber-600 font-medium' : 'text-surface-400'}>
                Minimum 5 characters required
              </span>
              <span className="text-surface-400">{trimmed.length}/1000</span>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-surface-100">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-xs font-semibold text-surface-600 hover:text-surface-900 rounded-xl border border-surface-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!isValid || submitting}
              className={`px-4 py-2 text-xs font-bold text-white rounded-xl shadow-sm flex items-center gap-2 ${
                isValid && !submitting
                  ? 'bg-danger-600 hover:bg-danger-700 cursor-pointer'
                  : 'bg-surface-300 cursor-not-allowed opacity-60'
              }`}
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Rejecting...</span>
                </>
              ) : (
                <>
                  <XCircle className="w-4 h-4" />
                  <span>Confirm Rejection</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
