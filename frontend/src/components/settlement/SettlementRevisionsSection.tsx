import React, { useState } from 'react'
import type { SettlementRevision } from '@/types'
import {
  RotateCcw,
  ChevronDown,
  ChevronUp,
  Calendar,
} from 'lucide-react'

interface SettlementRevisionsSectionProps {
  revisions: SettlementRevision[]
}

export const SettlementRevisionsSection: React.FC<SettlementRevisionsSectionProps> = ({
  revisions,
}) => {
  const [expanded, setExpanded] = useState(false)

  const formatCurrency = (val?: unknown) => {
    if (val === undefined || val === null || val === '') return '₹0.00'
    const num = typeof val === 'number' ? val : parseFloat(String(val))
    if (isNaN(num)) return '₹0.00'
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2,
    }).format(num)
  }

  if (revisions.length === 0) return null

  return (
    <div className="card bg-white border border-surface-200 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-center justify-between text-left hover:bg-surface-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <RotateCcw className="w-4 h-4 text-orange-600" />
          <h4 className="text-sm font-bold text-surface-900">
            Immutable Audit Revision History ({revisions.length})
          </h4>
        </div>
        <div className="flex items-center gap-2 text-surface-400">
          <span className="text-xs text-surface-500">
            {expanded ? 'Hide snapshots' : 'Show revision snapshots'}
          </span>
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {expanded && (
        <div className="p-5 border-t border-surface-200 space-y-4 bg-surface-50/50">
          <p className="text-xs text-surface-500">
            Cryptographic snapshots preserved upon reopening for audit transparency.
          </p>

          <div className="space-y-3">
            {revisions.map((rev) => {
              const snap = (rev.snapshot_data || {}) as Record<string, unknown>
              return (
                <div
                  key={rev.id}
                  className="card p-4 bg-white border border-surface-200 space-y-3 shadow-xs"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 border-b border-surface-100 pb-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-orange-100 text-orange-800">
                        Revision #{rev.revision_number}
                      </span>
                      <span className="text-xs font-semibold text-surface-800">
                        Historical Snapshot
                      </span>
                    </div>

                    <div className="flex items-center gap-3 text-[11px] text-surface-400">
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        {new Date(rev.created_at).toLocaleString()}
                      </span>
                    </div>
                  </div>

                  <div className="text-xs bg-amber-50/50 p-2.5 rounded border border-amber-200 text-amber-900">
                    <span className="font-bold block text-[10px] text-amber-800 uppercase tracking-wider mb-0.5">
                      Reopening Reason:
                    </span>
                    <p className="italic">"{rev.reopening_reason}"</p>
                  </div>

                  {/* Frozen Financial Metrics */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-[11px]">
                    <div className="p-2 bg-surface-50 rounded border border-surface-100">
                      <span className="text-[10px] text-surface-400 block font-medium">Verified Spend</span>
                      <span className="font-bold text-surface-800">
                        {formatCurrency(snap.total_verified_expenditure)}
                      </span>
                    </div>
                    <div className="p-2 bg-surface-50 rounded border border-surface-100">
                      <span className="text-[10px] text-surface-400 block font-medium">Verified Income</span>
                      <span className="font-bold text-surface-800">
                        {formatCurrency(snap.total_verified_income)}
                      </span>
                    </div>
                    <div className="p-2 bg-surface-50 rounded border border-surface-100">
                      <span className="text-[10px] text-surface-400 block font-medium">Net Deficit</span>
                      <span className="font-bold text-surface-800">
                        {formatCurrency(snap.net_deficit)}
                      </span>
                    </div>
                    <div className="p-2 bg-surface-50 rounded border border-surface-100">
                      <span className="text-[10px] text-surface-400 block font-medium">Frozen Balance</span>
                      <span className="font-bold text-purple-700">
                        {formatCurrency(snap.settlement_balance)}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
