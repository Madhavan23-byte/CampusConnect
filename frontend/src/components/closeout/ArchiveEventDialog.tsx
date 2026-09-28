import React from 'react'
import { Archive, Loader2, X } from 'lucide-react'

interface ArchiveEventDialogProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => Promise<void>
  submitting: boolean
}

export const ArchiveEventDialog: React.FC<ArchiveEventDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  submitting,
}) => {
  if (!isOpen) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="archive-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-fade-in"
    >
      <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-surface-200 space-y-5">
        <div className="flex items-center justify-between border-b border-surface-100 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-purple-100 text-purple-800 rounded-lg">
              <Archive className="w-5 h-5" />
            </div>
            <h3 id="archive-dialog-title" className="text-base font-bold text-surface-900">
              Archive Event Record
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

        <div className="p-4 bg-purple-50/70 border border-purple-200 rounded-xl space-y-2">
          <p className="text-xs font-bold text-purple-950">
            Terminal Historical Transition
          </p>
          <p className="text-xs text-purple-900 leading-relaxed">
            This event will be moved to the <strong className="font-semibold">ARCHIVED</strong> state and removed from active operational workflows.
          </p>
          <p className="text-[11px] text-purple-800 leading-relaxed pt-1 border-t border-purple-200">
            <strong>Important:</strong> There is <em>NO physical deletion</em>. All financial settlements, execution records, invoices, photos, and governance audit entries remain permanently preserved as an immutable historical record.
          </p>
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
            type="button"
            onClick={onConfirm}
            disabled={submitting}
            className={`px-4 py-2 text-xs font-bold text-white rounded-xl shadow-sm flex items-center gap-2 ${
              !submitting
                ? 'bg-purple-700 hover:bg-purple-800 cursor-pointer'
                : 'bg-surface-300 cursor-not-allowed opacity-60'
            }`}
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Archiving...</span>
              </>
            ) : (
              <>
                <Archive className="w-4 h-4" />
                <span>Confirm &amp; Archive Event</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
