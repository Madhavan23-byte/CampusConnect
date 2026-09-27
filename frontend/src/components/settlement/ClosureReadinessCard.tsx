import React from 'react'
import type { ClosureEligibility } from '@/types'
import {
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react'

interface ClosureReadinessCardProps {
  closure: ClosureEligibility | null
}

const BLOCKER_LABELS: Record<string, { title: string; desc: string }> = {
  SETTLEMENT_MISSING: {
    title: 'Settlement Not Prepared',
    desc: 'The Club Secretary must prepare and submit the financial settlement.',
  },
  SETTLEMENT_NOT_SETTLED: {
    title: 'Settlement Incomplete',
    desc: 'Settlement must reach SETTLED status with zero outstanding balance.',
  },
  PENDING_PAYMENTS: {
    title: 'Outstanding Balance Due',
    desc: 'Reimbursement or refund payment has not been fully liquidated.',
  },
  REPORT_NOT_CERTIFIED: {
    title: 'Post-Event Delivery Uncertified',
    desc: 'Faculty Advisor must certify post-event delivery in the Execution tab.',
  },
  EXPENSES_PENDING_AUDIT: {
    title: 'Expenses Pending Audit',
    desc: 'All actual expense vouchers must be verified or disallowed by Finance.',
  },
}

export const ClosureReadinessCard: React.FC<ClosureReadinessCardProps> = ({ closure }) => {
  if (!closure) return null

  return (
    <div className="card p-5 bg-white border border-surface-200 space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-surface-200 pb-3">
        <div>
          <h4 className="text-sm font-bold text-surface-900 flex items-center gap-2">
            {closure.eligible ? (
              <ShieldCheck className="w-4 h-4 text-emerald-600" />
            ) : (
              <ShieldAlert className="w-4 h-4 text-amber-600" />
            )}
            Institutional Event Closure Readiness
          </h4>
          <p className="text-xs text-surface-500">
            Automated compliance evaluation for permanent institutional closeout (Read-Only).
          </p>
        </div>

        <span
          className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider self-start sm:self-auto ${
            closure.eligible
              ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
              : 'bg-amber-100 text-amber-800 border border-amber-300'
          }`}
        >
          {closure.eligible ? 'Eligible for Closure' : 'Closure Blocked'}
        </span>
      </div>

      {closure.eligible ? (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
          <div className="space-y-0.5 text-xs text-emerald-900">
            <p className="font-bold">All Statutory Closeout Conditions Satisfied</p>
            <p className="text-emerald-800">
              Financial settlement is fully settled, all payments are liquidated, delivery is certified, and all bills are audited. This event is ready for institutional closeout.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-amber-900 font-semibold">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            Active Closeout Blockers ({closure.blockers.length}):
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {closure.blockers.map((b) => {
              const info = BLOCKER_LABELS[b] || {
                title: b.replace(/_/g, ' '),
                desc: 'Condition required before closeout clearance.',
              }

              return (
                <div
                  key={b}
                  className="p-3 rounded-lg border border-amber-200 bg-amber-50/50 space-y-1"
                >
                  <div className="flex items-center gap-1.5 text-xs font-bold text-amber-900">
                    <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
                    <span>{info.title}</span>
                  </div>
                  <p className="text-[11px] text-amber-800 pl-3.5 leading-relaxed">{info.desc}</p>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
