import React from 'react'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'

interface CloseoutBlockersListProps {
  blockers: string[]
  warnings?: string[]
}

const HUMAN_BLOCKER_MAP: Record<string, { title: string; desc: string }> = {
  REPORT_NOT_CERTIFIED: {
    title: 'Post-Event Report Not Certified',
    desc: 'The Faculty Advisor must review and certify the post-event delivery report in the Execution tab.',
  },
  SETTLEMENT_MISSING: {
    title: 'Financial Settlement Missing',
    desc: 'Club Secretary must prepare and submit the financial settlement in the Settlement tab.',
  },
  SETTLEMENT_NOT_SETTLED: {
    title: 'Settlement Not Fully Settled',
    desc: 'Financial settlement must be in SETTLED status with zero outstanding reimbursement or refund balance.',
  },
  PENDING_EXPENSES: {
    title: 'Unverified Expenses Remaining',
    desc: 'All actual expense claims must be verified or disallowed by Finance Officer.',
  },
  EXPENSES_PENDING_AUDIT: {
    title: 'Expenses Pending Audit',
    desc: 'All submitted actual expense claims must be audited before closeout clearance.',
  },
  PENDING_PAYMENTS: {
    title: 'Outstanding Settlement Balance Due',
    desc: 'Reimbursement disbursement or advance refund payment has not been fully cleared.',
  },
  ADVANCE_NOT_SETTLED: {
    title: 'Cash Advance Unsettled',
    desc: 'Disbursed cash advances must be reconciled through verified expenses or refund receipts.',
  },
  INCOME_NOT_VERIFIED: {
    title: 'Unverified Event Income',
    desc: 'Recorded event revenues must be verified by the Finance Officer.',
  },
  HALL_BOOKING_NOT_ENDED: {
    title: 'Venue Reservation In Progress',
    desc: 'The scheduled booking window for the venue has not yet concluded.',
  },
  RECONCILIATION_ISSUE: {
    title: 'Financial Reconciliation Discrepancy',
    desc: 'Sanctioned grant, expenditures, and income do not balance accurately.',
  },
  EVENT_NOT_COMPLETED: {
    title: 'Event Not Completed',
    desc: 'Event execution must be marked as COMPLETED before beginning closeout.',
  },
}

export const CloseoutBlockersList: React.FC<CloseoutBlockersListProps> = ({ blockers, warnings = [] }) => {
  if (blockers.length === 0 && warnings.length === 0) {
    return (
      <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-start gap-3">
        <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
        <div className="space-y-0.5 text-xs text-emerald-900">
          <p className="font-bold">Zero Outstanding Blockers</p>
          <p className="text-emerald-800">
            All statutory prerequisites including execution delivery, financial settlement, expense audits, and venue clearance have been satisfied.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {blockers.length > 0 && (
        <div className="space-y-2.5">
          <div className="flex items-center gap-2 text-xs text-amber-900 font-bold">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
            <span>Active Closeout Blockers ({blockers.length})</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" data-testid="closeout-blockers-list">
            {blockers.map((blockerKey) => {
              const info = HUMAN_BLOCKER_MAP[blockerKey] || {
                title: blockerKey.replace(/_/g, ' '),
                desc: 'Prerequisite condition must be satisfied before closeout can proceed.',
              }

              return (
                <div
                  key={blockerKey}
                  className="p-3.5 rounded-xl border border-amber-200 bg-amber-50/60 flex flex-col justify-between space-y-1.5"
                >
                  <div className="flex items-center gap-2 text-xs font-bold text-amber-950">
                    <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
                    <span>{info.title}</span>
                  </div>
                  <p className="text-[11px] text-amber-800 leading-relaxed pl-4">
                    {info.desc}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="space-y-2 pt-2">
          <div className="text-xs font-semibold text-surface-600">
            Advisory Warnings ({warnings.length}):
          </div>
          <ul className="list-disc list-inside text-xs text-surface-600 space-y-1 pl-1">
            {warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
