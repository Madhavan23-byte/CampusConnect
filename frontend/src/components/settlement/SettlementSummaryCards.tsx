import React from 'react'
import type { FinancialSettlement } from '@/types'
import {
  Banknote,
  TrendingDown,
  TrendingUp,
  Receipt,
  AlertCircle,
  CheckCircle2,
  Clock,
  RotateCcw,
  Scale,
  CreditCard,
} from 'lucide-react'

interface SettlementSummaryCardsProps {
  settlement: FinancialSettlement
}

export const SettlementSummaryCards: React.FC<SettlementSummaryCardsProps> = ({ settlement }) => {
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

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'DRAFT':
        return (
          <span className="badge bg-surface-100 text-surface-700 border border-surface-300">
            <Clock className="w-3 h-3 text-surface-500" /> Draft
          </span>
        )
      case 'UNDER_AUDIT':
        return (
          <span className="badge bg-blue-100 text-blue-800 border border-blue-300">
            <Clock className="w-3 h-3 text-blue-600 animate-spin" /> Under Audit
          </span>
        )
      case 'APPROVED':
        return (
          <span className="badge bg-green-100 text-green-800 border border-green-300">
            <CheckCircle2 className="w-3 h-3 text-green-600" /> Approved
          </span>
        )
      case 'QUERIED':
        return (
          <span className="badge bg-red-100 text-red-800 border border-red-300">
            <AlertCircle className="w-3 h-3 text-red-600" /> Queried
          </span>
        )
      case 'PENDING_REIMBURSEMENT':
        return (
          <span className="badge bg-purple-100 text-purple-800 border border-purple-300">
            <TrendingUp className="w-3 h-3 text-purple-600" /> Pending Reimbursement
          </span>
        )
      case 'PENDING_REFUND':
        return (
          <span className="badge bg-amber-100 text-amber-800 border border-amber-300">
            <TrendingDown className="w-3 h-3 text-amber-600" /> Pending Refund
          </span>
        )
      case 'SETTLED':
        return (
          <span className="badge bg-emerald-100 text-emerald-800 border border-emerald-300">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" /> Settled
          </span>
        )
      case 'REOPENED':
        return (
          <span className="badge bg-orange-100 text-orange-800 border border-orange-300">
            <RotateCcw className="w-3 h-3 text-orange-600" /> Reopened
          </span>
        )
      default:
        return <span className="badge bg-surface-100 text-surface-600">{status}</span>
    }
  }

  const getTypeBadge = (type: string) => {
    switch (type) {
      case 'REIMBURSEMENT_DUE':
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-purple-50 text-purple-700 border border-purple-200">
            Reimbursement Due
          </span>
        )
      case 'REFUND_DUE':
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
            Refund Due
          </span>
        )
      case 'BALANCED':
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
            Balanced
          </span>
        )
      default:
        return <span className="px-2 py-0.5 rounded text-[11px] bg-surface-100">{type}</span>
    }
  }

  return (
    <div className="space-y-4">
      {/* Top Banner: Status & Settlement Position */}
      <div className="card p-5 bg-white flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <h3 className="text-base font-bold text-surface-900">Financial Settlement Position</h3>
            {getStatusBadge(settlement.status)}
            {getTypeBadge(settlement.settlement_type)}
          </div>
          <p className="text-xs text-surface-500">
            Authoritative figures calculated and reconciled by Finance Settlement Service.
          </p>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <span className="text-[11px] font-medium text-surface-500 block uppercase tracking-wider">
              Settlement Balance
            </span>
            <span
              className={`text-xl font-extrabold ${
                settlement.settlement_type === 'REIMBURSEMENT_DUE'
                  ? 'text-purple-700'
                  : settlement.settlement_type === 'REFUND_DUE'
                  ? 'text-amber-700'
                  : 'text-surface-900'
              }`}
            >
              {formatCurrency(settlement.settlement_balance)}
            </span>
          </div>
        </div>
      </div>

      {/* Grid of Key Financial Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Sanctioned Grant */}
        <div className="card p-4 bg-white border border-surface-200">
          <div className="flex items-center justify-between text-surface-500 mb-2">
            <span className="text-xs font-semibold">Sanctioned Grant (G)</span>
            <Banknote className="w-4 h-4 text-primary-600" />
          </div>
          <div className="text-lg font-bold text-surface-900">
            {formatCurrency(settlement.sanctioned_grant)}
          </div>
          <div className="text-[11px] text-surface-500 mt-1">
            Budget ceiling: {formatCurrency(settlement.sanctioned_expenditure)}
          </div>
        </div>

        {/* Card 2: Verified Spend */}
        <div className="card p-4 bg-white border border-surface-200">
          <div className="flex items-center justify-between text-surface-500 mb-2">
            <span className="text-xs font-semibold">Verified Spend (E_v)</span>
            <Receipt className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="text-lg font-bold text-emerald-700">
            {formatCurrency(settlement.total_verified_expenditure)}
          </div>
          <div className="text-[11px] text-surface-500 mt-1">
            Claimed: {formatCurrency(settlement.total_claimed_expenditure)}
          </div>
        </div>

        {/* Card 3: Actual Verified Income */}
        <div className="card p-4 bg-white border border-surface-200">
          <div className="flex items-center justify-between text-surface-500 mb-2">
            <span className="text-xs font-semibold">Verified Income (I_a)</span>
            <TrendingUp className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-lg font-bold text-blue-700">
            {formatCurrency(settlement.total_verified_income)}
          </div>
          <div className="text-[11px] text-surface-500 mt-1">
            Expected: {formatCurrency(settlement.expected_income)}
          </div>
        </div>

        {/* Card 4: Disbursed Cash Advance */}
        <div className="card p-4 bg-white border border-surface-200">
          <div className="flex items-center justify-between text-surface-500 mb-2">
            <span className="text-xs font-semibold">Cash Advance Disbursed (A)</span>
            <CreditCard className="w-4 h-4 text-orange-600" />
          </div>
          <div className="text-lg font-bold text-orange-700">
            {formatCurrency(settlement.cash_advance_disbursed)}
          </div>
          <div className="text-[11px] text-surface-500 mt-1 flex items-center gap-1">
            <Scale className="w-3 h-3" /> Payout cap: {formatCurrency(settlement.institutional_payout)}
          </div>
        </div>
      </div>
    </div>
  )
}
