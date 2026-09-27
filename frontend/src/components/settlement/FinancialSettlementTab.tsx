import React, { useEffect, useState, useCallback } from 'react'
import { apiClient } from '@/lib/apiClient'
import type {
  FinancialSettlementDetail,
  CashAdvance,
  ActualIncome,
  SettlementPayment,
  SettlementRevision,
  ClosureEligibility,
} from '@/types'
import {
  SettlementSummaryCards,
} from './SettlementSummaryCards'
import {
  SettlementAccountingPipeline,
} from './SettlementAccountingPipeline'
import {
  CashAdvanceCard,
} from './CashAdvanceCard'
import {
  ActualIncomeSection,
} from './ActualIncomeSection'
import {
  SettlementLifecycleActions,
} from './SettlementLifecycleActions'
import {
  SettlementPaymentsSection,
} from './SettlementPaymentsSection'
import {
  SettlementRevisionsSection,
} from './SettlementRevisionsSection'
import {
  ClosureReadinessCard,
} from './ClosureReadinessCard'
import {
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  Scale,
} from 'lucide-react'

interface FinancialSettlementTabProps {
  eventId: string
  eventStatus: string
  confirmedEventStatus?: string
  isCertified: boolean
  isSecretary: boolean
  isFinanceOfficer: boolean
  isPrincipal: boolean
  isAdmin: boolean
}

export const FinancialSettlementTab: React.FC<FinancialSettlementTabProps> = ({
  eventId,
  isSecretary,
  isFinanceOfficer,
  isPrincipal,
  isAdmin,
}) => {
  void isAdmin // Reserved for admin audit logging
  const [settlement, setSettlement] = useState<FinancialSettlementDetail | null>(null)
  const [advance, setAdvance] = useState<CashAdvance | null>(null)
  const [incomes, setIncomes] = useState<ActualIncome[]>([])
  const [payments, setPayments] = useState<SettlementPayment[]>([])
  const [revisions, setRevisions] = useState<SettlementRevision[]>([])
  const [closure, setClosure] = useState<ClosureEligibility | null>(null)

  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [isStale, setIsStale] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const loadAll = useCallback(async (isManualRefresh = false) => {
    if (isManualRefresh) setRefreshing(true)
    else setLoading(true)
    setMessage(null)

    try {
      // 1. Fetch Settlement Detail (handles 404 cleanly)
      try {
        const res = await apiClient.get<FinancialSettlementDetail>(
          `/events/${eventId}/settlement`
        )
        setSettlement(res.data)
        setPayments(res.data.payments || [])
        setRevisions(res.data.revisions || [])
        setIsStale(false)
      } catch (err: unknown) {
        const e = err as { response?: { status?: number; data?: { message?: string } } }
        if (e.response?.status === 404) {
          setSettlement(null)
          setPayments([])
          setRevisions([])
        } else if (e.response?.status === 409) {
          setIsStale(true)
        } else {
          throw err
        }
      }

      // 2. Fetch Cash Advance
      try {
        const advRes = await apiClient.get<CashAdvance | null>(
          `/events/${eventId}/advances`
        )
        setAdvance(advRes.data)
      } catch {
        setAdvance(null)
      }

      // 3. Fetch Incomes
      try {
        const incRes = await apiClient.get<ActualIncome[]>(
          `/events/${eventId}/incomes`
        )
        setIncomes(incRes.data || [])
      } catch {
        setIncomes([])
      }

      // 4. Fetch Payments if not already populated
      try {
        const payRes = await apiClient.get<SettlementPayment[]>(
          `/events/${eventId}/settlement/payments`
        )
        if (payRes.data) setPayments(payRes.data)
      } catch {
        // payments might 404 if settlement not prepared
      }

      // 5. Fetch Revisions if not already populated
      try {
        const revRes = await apiClient.get<SettlementRevision[]>(
          `/events/${eventId}/settlement/revisions`
        )
        if (revRes.data) setRevisions(revRes.data)
      } catch {
        // revisions might 404 if settlement not prepared
      }

      // 6. Fetch Closure Eligibility
      try {
        const cloRes = await apiClient.get<ClosureEligibility>(
          `/events/${eventId}/settlement/closure-eligibility`
        )
        setClosure(cloRes.data)
      } catch {
        setClosure(null)
      }
    } catch (err: unknown) {
      const e = err as { response?: { status?: number; data?: { message?: string } } }
      if (e.response?.status === 403) {
        setMessage({
          type: 'error',
          text: 'Access Denied: You are not authorized to view financial settlement records for this event.',
        })
      } else {
        setMessage({
          type: 'error',
          text: e.response?.data?.message || 'Failed to load settlement data.',
        })
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [eventId])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-surface-500 gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-primary-600" />
        <span className="text-sm font-medium">Loading financial settlement ledger...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Top Banner & Refresh Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-surface-900 flex items-center gap-2">
            <Scale className="w-5 h-5 text-primary-600" />
            Financial Settlement &amp; Closeout Ledger
          </h2>
          <p className="text-xs text-surface-500 mt-0.5">
            Phase 2.3 Post-Event Financial Reconciliation, Cash Advances, Incomes, and Payment Liquidation.
          </p>
        </div>

        <button
          onClick={() => loadAll(true)}
          disabled={refreshing}
          className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5 self-start sm:self-auto"
          title="Refresh latest figures from Settlement Service"
        >
          {refreshing ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
          Refresh Data
        </button>
      </div>

      {/* Global Message Banner */}
      {message && (
        <div
          className={`p-3.5 rounded-lg flex items-center gap-2.5 text-xs ${
            message.type === 'success'
              ? 'bg-success-50 border border-success-500 text-success-800'
              : 'bg-danger-50 border border-danger-500 text-danger-800'
          }`}
        >
          {message.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 text-success-600" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 text-danger-600" />
          )}
          <span>{message.text}</span>
        </div>
      )}

      {/* 1. Settlement Lifecycle & Governance Actions */}
      <SettlementLifecycleActions
        eventId={eventId}
        settlement={settlement}
        isSecretary={isSecretary}
        isFinanceOfficer={isFinanceOfficer}
        isPrincipal={isPrincipal}
        isStale={isStale}
        onRefresh={() => loadAll(true)}
        setMessage={setMessage}
      />

      {/* 2. Executive Summary Cards (Rendered if settlement prepared) */}
      {settlement && <SettlementSummaryCards settlement={settlement} />}

      {/* 3. Accounting Pipeline Breakdown (Rendered if settlement prepared) */}
      {settlement && <SettlementAccountingPipeline settlement={settlement} />}

      {/* 4. Operational Grid: Cash Advance (Left) + Actual Income (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        <CashAdvanceCard
          eventId={eventId}
          advance={advance}
          isSecretary={isSecretary}
          isFinanceOfficer={isFinanceOfficer}
          onRefresh={() => loadAll(true)}
          setMessage={setMessage}
        />

        <ActualIncomeSection
          eventId={eventId}
          incomes={incomes}
          isSecretary={isSecretary}
          isFinanceOfficer={isFinanceOfficer}
          onRefresh={() => loadAll(true)}
          setMessage={setMessage}
        />
      </div>

      {/* 5. Settlement Payments & Directional Liquidation */}
      {settlement && (
        <SettlementPaymentsSection
          eventId={eventId}
          settlement={settlement}
          payments={payments}
          isFinanceOfficer={isFinanceOfficer}
          onRefresh={() => loadAll(true)}
          setMessage={setMessage}
        />
      )}

      {/* 6. Immutable Audit Revision History */}
      <SettlementRevisionsSection revisions={revisions} />

      {/* 7. Institutional Event Closure Readiness Card */}
      <ClosureReadinessCard closure={closure} />
    </div>
  )
}
