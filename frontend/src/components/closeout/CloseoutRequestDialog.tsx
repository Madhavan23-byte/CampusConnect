import React, { useState } from 'react'
import { Send, Loader2, X } from 'lucide-react'

interface CloseoutRequestDialogProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (remarks?: string) => Promise<void>
  submitting: boolean
}

export const CloseoutRequestDialog: React.FC<CloseoutRequestDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  submitting,
}) => {
  const [remarks, setRemarks] = useState('')

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitting) return
    await onConfirm(remarks.trim() || undefined)
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="closeout-request-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-fade-in"
    >
      <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-surface-200 space-y-5">
        <div className="flex items-center justify-between border-b border-surface-100 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-primary-100 text-primary-700 rounded-lg">
              <Send className="w-5 h-5" />
            </div>
            <h3 id="closeout-request-dialog-title" className="text-base font-bold text-surface-900">
              Submit Closeout Petition
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
          You are petitioning the administration for statutory closeout of this event. Institutional authorities (Dean, Principal, or Advisor) will review the post-event report, financial settlement, and venue clearance before issuing the final closeout certificate.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="request-remarks" className="block text-xs font-bold text-surface-700 mb-1">
              Operational Summary / Remarks <span className="font-normal text-surface-400">(Optional)</span>
            </label>
            <textarea
              id="request-remarks"
              rows={3}
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              disabled={submitting}
              placeholder="e.g. All bills settled, venue cleared, photo evidence attached."
              className="w-full text-xs p-3 border border-surface-300 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-600 outline-none"
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
              disabled={submitting}
              className="px-4 py-2 text-xs font-bold text-white bg-primary-600 hover:bg-primary-700 rounded-xl shadow-sm flex items-center gap-2 cursor-pointer disabled:opacity-60"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Submitting Petition...</span>
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  <span>Submit Closeout Petition</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
