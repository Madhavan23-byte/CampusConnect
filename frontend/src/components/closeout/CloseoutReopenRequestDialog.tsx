import React, { useState } from 'react'
import { RotateCcw, Loader2, X } from 'lucide-react'

interface CloseoutReopenRequestDialogProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (reason: string) => Promise<void>
  submitting: boolean
}

export const CloseoutReopenRequestDialog: React.FC<CloseoutReopenRequestDialogProps> = ({
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
      aria-labelledby="reopen-request-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-fade-in"
    >
      <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-surface-200 space-y-5">
        <div className="flex items-center justify-between border-b border-surface-100 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-blue-100 text-blue-700 rounded-lg">
              <RotateCcw className="w-5 h-5" />
            </div>
            <h3 id="reopen-request-dialog-title" className="text-base font-bold text-surface-900">
              Petition for Event Reopening
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

        <div className="p-3.5 bg-blue-50/70 border border-blue-200 rounded-xl space-y-1">
          <p className="text-xs font-semibold text-blue-950">
            Institutional Approval Required
          </p>
          <p className="text-xs text-blue-800 leading-relaxed">
            This event is currently closed. Requesting reopening creates an institutional petition requiring approval by the Dean of Student Affairs or Principal.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="reopen-reason" className="block text-xs font-bold text-surface-700 mb-1">
              Reopening Justification <span className="text-danger-600">*</span>
            </label>
            <textarea
              id="reopen-reason"
              rows={4}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={submitting}
              placeholder="State the financial, administrative, or compliance justification for reopening this closed event (min. 5 characters)..."
              className="w-full text-xs p-3 border border-surface-300 rounded-xl focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none"
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
                  ? 'bg-blue-600 hover:bg-blue-700 cursor-pointer'
                  : 'bg-surface-300 cursor-not-allowed opacity-60'
              }`}
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Submitting...</span>
                </>
              ) : (
                <>
                  <RotateCcw className="w-4 h-4" />
                  <span>Submit Reopen Petition</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
