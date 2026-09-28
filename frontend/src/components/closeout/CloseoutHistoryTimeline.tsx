import React from 'react'
import type { EventClosureDetailResponse } from '@/types'
import {
  Send,
  Award,
  RotateCcw,
  Archive,
} from 'lucide-react'

interface CloseoutHistoryTimelineProps {
  details: EventClosureDetailResponse
}

export const CloseoutHistoryTimeline: React.FC<CloseoutHistoryTimelineProps> = ({ details }) => {
  const { closure, latest_request, revisions, is_archived, event_status } = details

  const hasHistory = !!latest_request || !!closure || revisions.length > 0 || is_archived

  if (!hasHistory) {
    return (
      <div className="card p-6 bg-white border border-surface-200 rounded-2xl shadow-sm text-center text-xs text-surface-400 py-8">
        No closeout governance events recorded yet.
      </div>
    )
  }

  return (
    <div className="card p-6 bg-white border border-surface-200 rounded-2xl shadow-sm space-y-6">
      <div className="border-b border-surface-100 pb-3">
        <h3 className="text-sm font-bold text-surface-900">Closeout Audit &amp; Revision History</h3>
        <p className="text-xs text-surface-500">
          Chronological record of statutory petitions, certifications, rejections, and revisions.
        </p>
      </div>

      <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-surface-200">
        {/* 1. Latest Request (if recorded) */}
        {latest_request && (
          <div className="relative flex items-start gap-4">
            <span className="absolute -left-6 mt-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary-100 text-primary-600 ring-4 ring-white">
              <Send className="w-3 h-3" />
            </span>
            <div className="space-y-1 bg-surface-50/80 p-3.5 rounded-xl border border-surface-200 w-full text-xs">
              <div className="flex items-center justify-between">
                <span className="font-bold text-surface-900">Closeout Petition Submitted</span>
                {latest_request.requested_at && (
                  <span className="text-[11px] text-surface-500">
                    {new Date(latest_request.requested_at).toLocaleString()}
                  </span>
                )}
              </div>
              {latest_request.requested_by && (
                <p className="text-surface-600">
                  Petitioner: <span className="font-mono text-surface-800">{latest_request.requested_by}</span>
                </p>
              )}
              {latest_request.remarks && (
                <p className="text-surface-700 italic bg-white p-2 rounded border border-surface-200">
                  "{latest_request.remarks}"
                </p>
              )}
            </div>
          </div>
        )}

        {/* 2. Statutory Certification (if present) */}
        {closure && (
          <div className="relative flex items-start gap-4">
            <span className="absolute -left-6 mt-1 flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 ring-4 ring-white">
              <Award className="w-3 h-3" />
            </span>
            <div className="space-y-1.5 bg-emerald-50/50 p-3.5 rounded-xl border border-emerald-200 w-full text-xs">
              <div className="flex items-center justify-between">
                <span className="font-bold text-emerald-950">Statutory Closeout Certified</span>
                <span className="text-[11px] text-emerald-800">
                  {new Date(closure.certified_at).toLocaleString()}
                </span>
              </div>
              <p className="text-emerald-900">
                Certified By: <span className="font-mono font-semibold">{closure.certified_by}</span>
              </p>
              <div className="flex items-center gap-2 text-[11px] text-emerald-800">
                <span className="font-semibold">Venue Clearance:</span>
                <span>{closure.venue_cleared ? 'Confirmed' : 'Unconfirmed'}</span>
              </div>
              {closure.closure_notes && (
                <p className="text-emerald-900 italic bg-white/80 p-2 rounded border border-emerald-200">
                  "{closure.closure_notes}"
                </p>
              )}
              <div className="text-[10px] text-emerald-700 font-mono pt-1 truncate">
                Hash: {closure.certificate_manifest_hash}
              </div>
            </div>
          </div>
        )}

        {/* 3. Revisions (if any) */}
        {revisions.map((rev) => (
          <div key={rev.id} className="relative flex items-start gap-4">
            <span className="absolute -left-6 mt-1 flex h-5 w-5 items-center justify-center rounded-full bg-blue-100 text-blue-600 ring-4 ring-white">
              <RotateCcw className="w-3 h-3" />
            </span>
            <div className="space-y-1.5 bg-blue-50/50 p-3.5 rounded-xl border border-blue-200 w-full text-xs">
              <div className="flex items-center justify-between">
                <span className="font-bold text-blue-950">
                  Revision #{rev.revision_number} Archived &amp; Reopened
                </span>
                <span className="text-[11px] text-blue-800">
                  {new Date(rev.reopened_at || rev.created_at).toLocaleString()}
                </span>
              </div>
              <p className="text-blue-900">
                Reopened By Authority: <span className="font-mono font-semibold">{rev.reopened_by}</span>
              </p>
              <div className="bg-white/80 p-2 rounded border border-blue-200 text-blue-950">
                <span className="font-semibold block mb-0.5">Reopening Justification:</span>
                <p className="italic">"{rev.reopening_reason}"</p>
              </div>
            </div>
          </div>
        ))}

        {/* 4. Archival (if archived) */}
        {(is_archived || event_status === 'ARCHIVED') && (
          <div className="relative flex items-start gap-4">
            <span className="absolute -left-6 mt-1 flex h-5 w-5 items-center justify-center rounded-full bg-purple-100 text-purple-700 ring-4 ring-white">
              <Archive className="w-3 h-3" />
            </span>
            <div className="space-y-1 bg-purple-50/50 p-3.5 rounded-xl border border-purple-200 w-full text-xs">
              <div className="flex items-center justify-between">
                <span className="font-bold text-purple-950">Event Permanently Archived</span>
                <span className="text-[11px] font-semibold text-purple-700 uppercase">Terminal State</span>
              </div>
              <p className="text-purple-900 text-xs">
                Archived by System Administrator. All data permanently frozen in historical governance repository.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
