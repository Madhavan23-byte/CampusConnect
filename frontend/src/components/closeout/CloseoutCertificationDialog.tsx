import React, { useState } from 'react'
import { Award, Check, Loader2, X } from 'lucide-react'

interface CloseoutCertificationDialogProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (venueCleared: boolean, closureNotes?: string) => Promise<void>
  submitting: boolean
}

export const CloseoutCertificationDialog: React.FC<CloseoutCertificationDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  submitting,
}) => {
  const [venueCleared, setVenueCleared] = useState(false)
  const [closureNotes, setClosureNotes] = useState('')

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!venueCleared || submitting) return
    await onConfirm(venueCleared, closureNotes.trim() || undefined)
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="certify-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-fade-in"
    >
      <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-surface-200 space-y-5">
        <div className="flex items-center justify-between border-b border-surface-100 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-emerald-100 text-emerald-800 rounded-lg">
              <Award className="w-5 h-5" />
            </div>
            <h3 id="certify-dialog-title" className="text-base font-bold text-surface-900">
              Certify Statutory Event Closeout
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
          Certification is an authoritative institutional action. Upon certification, the event enters the{' '}
          <strong className="text-surface-900 font-semibold">CLOSED</strong> state and all operational modifications, financial settlements, and vouchers will be locked permanently.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Statutory Attestation Checkbox */}
          <div className="p-3.5 bg-emerald-50/70 border border-emerald-300 rounded-xl space-y-2">
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                id="venue-cleared-attestation"
                checked={venueCleared}
                onChange={(e) => setVenueCleared(e.target.checked)}
                disabled={submitting}
                className="mt-0.5 w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 border-surface-300"
              />
              <span className="text-xs font-semibold text-emerald-950 leading-snug">
                I confirm that the event venue has been cleared and released.
              </span>
            </label>
            <p className="text-[11px] text-emerald-800 pl-7">
              Statutory verification that premises have been inspected, restored, and handed back to the institution.
            </p>
          </div>

          {/* Optional notes */}
          <div>
            <label htmlFor="closure-notes" className="block text-xs font-bold text-surface-700 mb-1">
              Statutory Remarks / Closure Notes <span className="font-normal text-surface-400">(Optional)</span>
            </label>
            <textarea
              id="closure-notes"
              rows={3}
              value={closureNotes}
              onChange={(e) => setClosureNotes(e.target.value)}
              disabled={submitting}
              placeholder="e.g. All requirements completed satisfactorily, no pending liabilities."
              className="w-full text-xs p-3 border border-surface-300 rounded-xl focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-600 outline-none"
            />
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
              disabled={!venueCleared || submitting}
              className={`px-4 py-2 text-xs font-bold text-white rounded-xl shadow-sm flex items-center gap-2 ${
                venueCleared && !submitting
                  ? 'bg-emerald-600 hover:bg-emerald-700 cursor-pointer'
                  : 'bg-surface-300 cursor-not-allowed opacity-60'
              }`}
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Certifying...</span>
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  <span>Confirm &amp; Certify Closeout</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
