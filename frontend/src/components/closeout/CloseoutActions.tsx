import React from 'react'
import type { EventClosureDetailResponse, UserRole } from '@/types'
import {
  Send,
  Award,
  XCircle,
  RotateCcw,
  Archive,
  Loader2,
} from 'lucide-react'

interface CloseoutActionsProps {
  details: EventClosureDetailResponse
  userRole?: UserRole
  onOpenRequestDialog: () => void
  onOpenCertifyDialog: () => void
  onOpenRejectDialog: () => void
  onOpenReopenRequestDialog: () => void
  onOpenReopenApproveDialog: () => void
  onOpenArchiveDialog: () => void
  actionLoading: boolean
}

export const CloseoutActions: React.FC<CloseoutActionsProps> = ({
  details,
  userRole,
  onOpenRequestDialog,
  onOpenCertifyDialog,
  onOpenRejectDialog,
  onOpenReopenRequestDialog,
  onOpenReopenApproveDialog,
  onOpenArchiveDialog,
  actionLoading,
}) => {
  const { event_status, is_archived, eligibility } = details

  // Role booleans
  const isSecretary = userRole === 'CLUB_SECRETARY'
  const isAdvisor = userRole === 'FACULTY_ADVISOR'
  const isFinanceOfficer = userRole === 'FINANCE_OFFICER'
  const isDean = userRole === 'DEAN_STUDENT_AFFAIRS'
  const isPrincipal = userRole === 'PRINCIPAL'
  const isAdmin = userRole === 'SYSTEM_ADMIN'

  // Action capabilities based on backend contract
  const canRequestCloseout =
    isSecretary && event_status === 'COMPLETED' && eligibility.eligible && !is_archived

  const canCertify =
    (isDean || isPrincipal || isAdvisor) &&
    event_status === 'CLOSURE_REQUESTED' &&
    !is_archived

  const canReject =
    (isDean || isPrincipal || isAdvisor) &&
    event_status === 'CLOSURE_REQUESTED' &&
    !is_archived

  const canRequestReopen =
    (isSecretary || isAdvisor || isFinanceOfficer) &&
    event_status === 'CLOSED' &&
    !is_archived

  const canApproveReopen =
    (isDean || isPrincipal) &&
    event_status === 'CLOSED' &&
    !is_archived

  const canArchive =
    isAdmin &&
    event_status === 'CLOSED' &&
    !is_archived

  const hasAnyAction =
    canRequestCloseout ||
    canCertify ||
    canReject ||
    canRequestReopen ||
    canApproveReopen ||
    canArchive

  if (is_archived || event_status === 'ARCHIVED') {
    return (
      <div className="card p-5 bg-purple-50/50 border border-purple-200 rounded-2xl flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Archive className="w-5 h-5 text-purple-700" />
          <div>
            <h4 className="text-xs font-bold text-purple-950 uppercase tracking-wider">
              Immutable Historical Archive
            </h4>
            <p className="text-xs text-purple-800">
              This event is archived. No operational actions or modifications are permitted.
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (!hasAnyAction) {
    return null
  }

  return (
    <div className="card p-6 bg-white border border-surface-200 rounded-2xl shadow-sm space-y-4">
      <div className="flex items-center justify-between border-b border-surface-100 pb-3">
        <div>
          <h3 className="text-sm font-bold text-surface-900">Closeout Governance Actions</h3>
          <p className="text-xs text-surface-500">
            Available authoritative actions determined by your institutional role.
          </p>
        </div>
        {actionLoading && (
          <div className="flex items-center gap-2 text-xs text-primary-600 font-semibold">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Processing...</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 flex-wrap" data-testid="closeout-action-buttons">
        {/* Secretary: Request Closeout */}
        {canRequestCloseout && (
          <button
            type="button"
            data-testid="request-closeout-button"
            onClick={onOpenRequestDialog}
            disabled={actionLoading}
            className="btn-primary text-xs px-4 py-2.5 rounded-xl flex items-center gap-2 shadow-sm font-bold disabled:opacity-60 cursor-pointer"
          >
            <Send className="w-4 h-4" />
            Request Closeout
          </button>
        )}

        {/* Dean/Principal/Advisor: Certify Closeout */}
        {canCertify && (
          <button
            type="button"
            data-testid="certify-closeout-button"
            onClick={onOpenCertifyDialog}
            disabled={actionLoading}
            className="px-4 py-2.5 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl shadow-sm flex items-center gap-2 disabled:opacity-60 cursor-pointer"
          >
            <Award className="w-4 h-4" />
            Certify Closeout
          </button>
        )}

        {/* Dean/Principal/Advisor: Reject Closeout */}
        {canReject && (
          <button
            type="button"
            data-testid="reject-closeout-button"
            onClick={onOpenRejectDialog}
            disabled={actionLoading}
            className="px-4 py-2.5 text-xs font-bold text-white bg-danger-600 hover:bg-danger-700 rounded-xl shadow-sm flex items-center gap-2 disabled:opacity-60 cursor-pointer"
          >
            <XCircle className="w-4 h-4" />
            Reject Closeout
          </button>
        )}

        {/* Secretary/Advisor/Finance: Request Reopen */}
        {canRequestReopen && (
          <button
            type="button"
            data-testid="request-reopen-button"
            onClick={onOpenReopenRequestDialog}
            disabled={actionLoading}
            className="px-4 py-2.5 text-xs font-bold text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-xl shadow-sm flex items-center gap-2 disabled:opacity-60 cursor-pointer"
          >
            <RotateCcw className="w-4 h-4" />
            Petition Reopen
          </button>
        )}

        {/* Dean/Principal: Approve Reopen */}
        {canApproveReopen && (
          <button
            type="button"
            data-testid="approve-reopen-button"
            onClick={onOpenReopenApproveDialog}
            disabled={actionLoading}
            className="px-4 py-2.5 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-xl shadow-sm flex items-center gap-2 disabled:opacity-60 cursor-pointer"
          >
            <RotateCcw className="w-4 h-4" />
            Approve Reopening
          </button>
        )}

        {/* System Admin: Archive Event */}
        {canArchive && (
          <button
            type="button"
            data-testid="archive-event-button"
            onClick={onOpenArchiveDialog}
            disabled={actionLoading}
            className="px-4 py-2.5 text-xs font-bold text-white bg-purple-700 hover:bg-purple-800 rounded-xl shadow-sm flex items-center gap-2 disabled:opacity-60 cursor-pointer"
          >
            <Archive className="w-4 h-4" />
            Archive Event
          </button>
        )}
      </div>
    </div>
  )
}
