import React from 'react'
import type { EventClosureDetailResponse } from '@/types'
import {
  Lock,
  Archive,
  CheckCircle2,
  Clock,
  AlertCircle,
  FileCheck,
  RotateCcw,
} from 'lucide-react'

interface CloseoutStatusCardProps {
  details: EventClosureDetailResponse
}

export const CloseoutStatusCard: React.FC<CloseoutStatusCardProps> = ({ details }) => {
  const { event_status, is_archived, closure, latest_request, revisions, eligibility } = details

  // Determine conceptual state display
  let statusBadgeColor = 'bg-surface-100 text-surface-700 border-surface-300'
  let statusLabel: string = event_status
  let statusIcon = <Clock className="w-5 h-5 text-surface-600" />
  let statusHeadline = 'Event Lifecycle Status'
  let statusDescription = 'Event is in progress or pending operational completion.'

  if (is_archived || event_status === 'ARCHIVED') {
    statusBadgeColor = 'bg-purple-100 text-purple-900 border-purple-300'
    statusLabel = 'ARCHIVED'
    statusIcon = <Archive className="w-5 h-5 text-purple-700" />
    statusHeadline = 'Archived Historical Record'
    statusDescription = 'This event is retained as an immutable historical record. Operational modifications are disabled.'
  } else if (event_status === 'CLOSED') {
    statusBadgeColor = 'bg-emerald-100 text-emerald-900 border-emerald-300'
    statusLabel = 'CLOSED'
    statusIcon = <Lock className="w-5 h-5 text-emerald-700" />
    statusHeadline = 'Institutional Closeout Certified'
    statusDescription = 'Statutory closeout completed. Event financial balances, documents, and records are locked.'
  } else if (event_status === 'CLOSURE_REQUESTED') {
    statusBadgeColor = 'bg-primary-100 text-primary-900 border-primary-300'
    statusLabel = 'CLOSURE REQUESTED'
    statusIcon = <Clock className="w-5 h-5 text-primary-700" />
    statusHeadline = 'Closeout Certification Pending'
    statusDescription = 'The Club Secretary has submitted formal closeout petition. Awaiting statutory clearance by Dean, Principal, or Faculty Advisor.'
  } else if (revisions.length > 0 && event_status === 'COMPLETED') {
    statusBadgeColor = 'bg-blue-100 text-blue-900 border-blue-300'
    statusLabel = 'REOPENED'
    statusIcon = <RotateCcw className="w-5 h-5 text-blue-700" />
    statusHeadline = 'Event Reopened for Reconciliation'
    statusDescription = `Event was reopened by institutional authority (Revision #${revisions[revisions.length - 1].revision_number}).`
  } else if (eligibility.eligible) {
    statusBadgeColor = 'bg-emerald-100 text-emerald-900 border-emerald-300'
    statusLabel = 'READY FOR CLOSEOUT'
    statusIcon = <CheckCircle2 className="w-5 h-5 text-emerald-700" />
    statusHeadline = 'Ready for Statutory Closeout'
    statusDescription = 'All prerequisites are satisfied. Club Secretary may submit formal closeout request.'
  } else {
    statusBadgeColor = 'bg-amber-100 text-amber-900 border-amber-300'
    statusLabel = 'UNREADY'
    statusIcon = <AlertCircle className="w-5 h-5 text-amber-700" />
    statusHeadline = 'Prerequisites Incomplete'
    statusDescription = 'Closeout requirements are not yet satisfied. Resolve outstanding blockers before requesting closeout.'
  }

  return (
    <div className="card p-6 bg-white border border-surface-200 rounded-2xl shadow-sm space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <div className="p-3 rounded-xl bg-surface-50 border border-surface-200 shrink-0">
            {statusIcon}
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h2 className="text-base font-bold text-surface-900">{statusHeadline}</h2>
              <span
                data-testid="closeout-primary-status-badge"
                className={`px-3 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider border ${statusBadgeColor}`}
              >
                {statusLabel}
              </span>
            </div>
            <p className="text-xs text-surface-600 leading-relaxed max-w-2xl">
              {statusDescription}
            </p>
          </div>
        </div>

        {revisions.length > 0 && (
          <div className="self-start sm:self-auto text-right">
            <span className="text-[11px] font-semibold text-surface-500 uppercase tracking-wider block">
              Governance Revisions
            </span>
            <span className="text-xs font-bold text-primary-700 bg-primary-50 px-2 py-0.5 rounded border border-primary-200 inline-block mt-0.5">
              {revisions.length} {revisions.length === 1 ? 'Revision' : 'Revisions'}
            </span>
          </div>
        )}
      </div>

      {/* Dynamic Metadata Panels based on state */}
      {closure && (
        <div className="p-4 bg-emerald-50/60 border border-emerald-200 rounded-xl space-y-3">
          <div className="flex items-center justify-between border-b border-emerald-200/60 pb-2">
            <span className="text-xs font-bold text-emerald-950 flex items-center gap-1.5">
              <FileCheck className="w-4 h-4 text-emerald-600" />
              Statutory Certification Certificate
            </span>
            <span className="text-[11px] font-semibold text-emerald-800">
              {new Date(closure.certified_at).toLocaleString()}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 text-xs">
            <div>
              <span className="text-emerald-700 block text-[11px]">Certifying Authority</span>
              <span className="font-semibold text-emerald-950 font-mono text-[11px]">
                {closure.certified_by}
              </span>
            </div>
            <div>
              <span className="text-emerald-700 block text-[11px]">Venue Cleared Attestation</span>
              <span className="font-semibold text-emerald-950">
                {closure.venue_cleared ? 'Confirmed & Released' : 'Pending'}
              </span>
            </div>
            <div>
              <span className="text-emerald-700 block text-[11px]">Manifest Digest</span>
              <span
                className="font-mono text-[10px] text-emerald-950 truncate block"
                title={closure.certificate_manifest_hash}
              >
                {closure.certificate_manifest_hash}
              </span>
            </div>
          </div>

          {closure.closure_notes && (
            <div className="pt-2 border-t border-emerald-200/60 text-xs text-emerald-900">
              <span className="font-semibold block mb-0.5">Certification Notes:</span>
              <p className="bg-white/70 p-2.5 rounded-lg border border-emerald-200 text-xs italic">
                "{closure.closure_notes}"
              </p>
            </div>
          )}
        </div>
      )}

      {latest_request && event_status === 'CLOSURE_REQUESTED' && (
        <div className="p-4 bg-primary-50/60 border border-primary-200 rounded-xl space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="font-bold text-primary-950 flex items-center gap-1.5">
              <Clock className="w-4 h-4 text-primary-600" />
              Closeout Petition Submitted
            </span>
            {latest_request.requested_at && (
              <span className="text-[11px] text-primary-800">
                {new Date(latest_request.requested_at).toLocaleString()}
              </span>
            )}
          </div>
          {latest_request.requested_by && (
            <p className="text-primary-900">
              Submitted by Secretary: <span className="font-mono">{latest_request.requested_by}</span>
            </p>
          )}
          {latest_request.remarks && (
            <p className="text-primary-900 bg-white/70 p-2 rounded border border-primary-200">
              Remarks: "{latest_request.remarks}"
            </p>
          )}
        </div>
      )}
    </div>
  )
}
