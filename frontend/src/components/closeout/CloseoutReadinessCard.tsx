import React from 'react'
import type { CloseoutEligibilityInfo } from '@/types'
import { CloseoutBlockersList } from './CloseoutBlockersList'
import { ShieldCheck, ShieldAlert } from 'lucide-react'

interface CloseoutReadinessCardProps {
  eligibility: CloseoutEligibilityInfo | null
  isClosedOrArchived?: boolean
}

export const CloseoutReadinessCard: React.FC<CloseoutReadinessCardProps> = ({
  eligibility,
  isClosedOrArchived = false,
}) => {
  if (!eligibility) return null

  const { eligible, blockers, warnings, venue_status, report_status, settlement_status } = eligibility

  return (
    <div className="card p-6 bg-white border border-surface-200 rounded-2xl shadow-sm space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-100 pb-4">
        <div>
          <h3 className="text-sm font-bold text-surface-900 flex items-center gap-2">
            {eligible ? (
              <ShieldCheck className="w-5 h-5 text-emerald-600" />
            ) : (
              <ShieldAlert className="w-5 h-5 text-amber-600" />
            )}
            Institutional Closeout Eligibility
          </h3>
          <p className="text-xs text-surface-500 mt-0.5">
            Statutory prerequisites evaluation computed by backend authority.
          </p>
        </div>

        <span
          data-testid="closeout-eligibility-badge"
          className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider self-start sm:self-auto ${
            isClosedOrArchived
              ? 'bg-surface-100 text-surface-700 border border-surface-300'
              : eligible
              ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
              : 'bg-amber-100 text-amber-800 border border-amber-300'
          }`}
        >
          {isClosedOrArchived
            ? 'Closeout Fulfilled'
            : eligible
            ? 'Ready for Closeout'
            : 'Closeout Blocked'}
        </span>
      </div>

      {/* Quick prerequisite status pills */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="p-3 bg-surface-50 rounded-xl border border-surface-200 flex items-center justify-between">
          <span className="text-xs font-medium text-surface-600">Post-Event Report</span>
          <span
            className={`text-xs font-bold px-2 py-0.5 rounded ${
              report_status === 'CERTIFIED'
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-amber-100 text-amber-800'
            }`}
          >
            {report_status === 'CERTIFIED' ? 'Certified' : report_status || 'Pending'}
          </span>
        </div>

        <div className="p-3 bg-surface-50 rounded-xl border border-surface-200 flex items-center justify-between">
          <span className="text-xs font-medium text-surface-600">Settlement</span>
          <span
            className={`text-xs font-bold px-2 py-0.5 rounded ${
              settlement_status === 'SETTLED'
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-amber-100 text-amber-800'
            }`}
          >
            {settlement_status === 'SETTLED' ? 'Settled' : settlement_status || 'Incomplete'}
          </span>
        </div>

        <div className="p-3 bg-surface-50 rounded-xl border border-surface-200 flex items-center justify-between">
          <span className="text-xs font-medium text-surface-600">Venue Booking</span>
          <span
            className={`text-xs font-bold px-2 py-0.5 rounded ${
              !venue_status.has_booking || venue_status.booking_ended
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-amber-100 text-amber-800'
            }`}
          >
            {!venue_status.has_booking
              ? 'No Venue'
              : venue_status.booking_ended
              ? 'Concluded'
              : 'In Progress'}
          </span>
        </div>
      </div>

      {/* Blockers list or success banner */}
      <CloseoutBlockersList blockers={blockers} warnings={warnings} />
    </div>
  )
}
