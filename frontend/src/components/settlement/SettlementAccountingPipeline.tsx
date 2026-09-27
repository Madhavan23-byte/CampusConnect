import React from 'react'
import type { FinancialSettlement } from '@/types'
import {
  ArrowDown,
  Minus,
  Equal,
  Receipt,
  TrendingUp,
  Scale,
  CreditCard,
  CheckCircle2,
} from 'lucide-react'

interface SettlementAccountingPipelineProps {
  settlement: FinancialSettlement
}

export const SettlementAccountingPipeline: React.FC<SettlementAccountingPipelineProps> = ({
  settlement,
}) => {
  const formatCurrency = (val?: string | number | null) => {
    if (val === undefined || val === null || val === '') return '₹0.00'
    const num = typeof val === 'number' ? val : parseFloat(val)
    if (isNaN(num)) return '₹0.00'
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2,
    }).format(num)
  }

  return (
    <div className="card p-5 bg-white border border-surface-200 space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 border-b border-surface-200 pb-3">
        <div>
          <h4 className="text-sm font-bold text-surface-900 flex items-center gap-2">
            <Scale className="w-4 h-4 text-primary-600" />
            Statutory Settlement Accounting Pipeline
          </h4>
          <p className="text-xs text-surface-500">
            Institutional deficit and cash reconciliation rules applied by Settlement Service.
          </p>
        </div>
        <span className="text-[11px] font-semibold text-surface-500 bg-surface-100 px-2 py-0.5 rounded">
          Authoritative Engine Data
        </span>
      </div>

      {/* Visual Pipeline Steps */}
      <div className="grid grid-cols-1 md:grid-cols-6 gap-3 items-center">
        {/* Step 1: Verified Expenditure */}
        <div className="p-3 bg-surface-50 rounded-lg border border-surface-200 text-center space-y-1">
          <span className="text-[10px] font-bold text-surface-500 uppercase tracking-wider block">
            1. Verified Spend
          </span>
          <div className="flex items-center justify-center gap-1 text-emerald-700">
            <Receipt className="w-3.5 h-3.5" />
            <span className="text-sm font-extrabold">
              {formatCurrency(settlement.total_verified_expenditure)}
            </span>
          </div>
          <span className="text-[10px] text-surface-400 block truncate">Total audited bills</span>
        </div>

        {/* Separator / Minus */}
        <div className="hidden md:flex justify-center text-surface-400">
          <Minus className="w-4 h-4" />
        </div>

        {/* Step 2: Actual Verified Income */}
        <div className="p-3 bg-surface-50 rounded-lg border border-surface-200 text-center space-y-1">
          <span className="text-[10px] font-bold text-surface-500 uppercase tracking-wider block">
            2. Verified Income
          </span>
          <div className="flex items-center justify-center gap-1 text-blue-700">
            <TrendingUp className="w-3.5 h-3.5" />
            <span className="text-sm font-extrabold">
              {formatCurrency(settlement.total_verified_income)}
            </span>
          </div>
          <span className="text-[10px] text-surface-400 block truncate">Self-generated revenue</span>
        </div>

        {/* Separator / Equal */}
        <div className="hidden md:flex justify-center text-surface-400">
          <Equal className="w-4 h-4" />
        </div>

        {/* Step 3: Net Deficit */}
        <div className="p-3 bg-primary-50/50 rounded-lg border border-primary-200 text-center space-y-1">
          <span className="text-[10px] font-bold text-primary-700 uppercase tracking-wider block">
            3. Net Deficit (D)
          </span>
          <span className="text-sm font-extrabold text-primary-900 block">
            {formatCurrency(settlement.net_deficit)}
          </span>
          <span className="text-[10px] text-primary-600 block truncate">max(0, Spend - Income)</span>
        </div>

        {/* Separator / Arrow */}
        <div className="hidden md:flex justify-center text-surface-400">
          <ArrowDown className="w-4 h-4 rotate-[-90deg]" />
        </div>
      </div>

      {/* Second Row: Payout, Advance, Balance */}
      <div className="grid grid-cols-1 md:grid-cols-6 gap-3 items-center pt-2 border-t border-surface-100">
        {/* Step 4: Institutional Payout */}
        <div className="p-3 bg-surface-50 rounded-lg border border-surface-200 text-center space-y-1">
          <span className="text-[10px] font-bold text-surface-500 uppercase tracking-wider block">
            4. Institutional Payout
          </span>
          <span className="text-sm font-extrabold text-surface-800 block">
            {formatCurrency(settlement.institutional_payout)}
          </span>
          <span className="text-[10px] text-surface-400 block truncate">min(Grant, Deficit)</span>
        </div>

        {/* Separator / Minus */}
        <div className="hidden md:flex justify-center text-surface-400">
          <Minus className="w-4 h-4" />
        </div>

        {/* Step 5: Cash Advance Disbursed */}
        <div className="p-3 bg-orange-50/50 rounded-lg border border-orange-200 text-center space-y-1">
          <span className="text-[10px] font-bold text-orange-700 uppercase tracking-wider block">
            5. Cash Advance (A)
          </span>
          <div className="flex items-center justify-center gap-1 text-orange-800">
            <CreditCard className="w-3.5 h-3.5" />
            <span className="text-sm font-extrabold">
              {formatCurrency(settlement.cash_advance_disbursed)}
            </span>
          </div>
          <span className="text-[10px] text-orange-600 block truncate">Pre-event disbursement</span>
        </div>

        {/* Separator / Equal */}
        <div className="hidden md:flex justify-center text-surface-400">
          <Equal className="w-4 h-4" />
        </div>

        {/* Step 6: Settlement Balance */}
        <div
          className={`p-3 rounded-lg border text-center space-y-1 md:col-span-2 ${
            settlement.settlement_type === 'REIMBURSEMENT_DUE'
              ? 'bg-purple-50 border-purple-300'
              : settlement.settlement_type === 'REFUND_DUE'
              ? 'bg-amber-50 border-amber-300'
              : 'bg-emerald-50 border-emerald-300'
          }`}
        >
          <span
            className={`text-[10px] font-bold uppercase tracking-wider block ${
              settlement.settlement_type === 'REIMBURSEMENT_DUE'
                ? 'text-purple-800'
                : settlement.settlement_type === 'REFUND_DUE'
                ? 'text-amber-800'
                : 'text-emerald-800'
            }`}
          >
            6. Final Balance (Payout - Advance)
          </span>
          <div className="flex items-center justify-center gap-1.5">
            {settlement.status === 'SETTLED' && (
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            )}
            <span
              className={`text-base font-black ${
                settlement.settlement_type === 'REIMBURSEMENT_DUE'
                  ? 'text-purple-900'
                  : settlement.settlement_type === 'REFUND_DUE'
                  ? 'text-amber-900'
                  : 'text-emerald-900'
              }`}
            >
              {formatCurrency(settlement.settlement_balance)}
            </span>
          </div>
          <span className="text-[10px] font-medium text-surface-600 block">
            {settlement.settlement_type === 'REIMBURSEMENT_DUE'
              ? `Reimbursement Due: ${formatCurrency(settlement.reimbursement_due)} (College → Club)`
              : settlement.settlement_type === 'REFUND_DUE'
              ? `Refund Due: ${formatCurrency(settlement.refund_due)} (Club → College)`
              : 'Zero Balance (Balanced Settlement)'}
          </span>
        </div>
      </div>
    </div>
  )
}
