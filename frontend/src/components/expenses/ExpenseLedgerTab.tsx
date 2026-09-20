import React, { useEffect, useState, useCallback } from 'react'
import { apiClient } from '@/lib/apiClient'
import type {
  ActualExpense,
  ExpenseLedgerSummary,
  ActualExpenseCreate,
  ActualExpenseUpdate,
  BillUploadResponse,
  BudgetLineItemCategory,
} from '@/types'
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Upload,
  FileText,
  Check,
  Plus,
  Loader2,
  Download,
  ShieldCheck,
  Building2,
  Calendar,
  FileCheck,
  RefreshCw,
} from 'lucide-react'

interface ExpenseLedgerTabProps {
  eventId: string
  eventStatus: string
  confirmedEventStatus?: string
  isCertified: boolean
  isSecretary: boolean
  isFinanceOfficer: boolean
  isAdmin: boolean
}

type FinanceActionType = 'VERIFY' | 'PARTIAL_VERIFY' | 'QUERY' | 'DISALLOW'

const CATEGORIES: BudgetLineItemCategory[] = [
  'MATERIALS',
  'TRAVEL',
  'PRINTING',
  'FOOD',
  'EQUIPMENT',
  'OTHER',
]

export const ExpenseLedgerTab: React.FC<ExpenseLedgerTabProps> = ({
  eventId,
  confirmedEventStatus,
  isCertified,
  isSecretary,
  isFinanceOfficer,
  isAdmin,
}) => {
  const isEventCompleted = confirmedEventStatus === 'COMPLETED'

  const [ledger, setLedger] = useState<ExpenseLedgerSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Status Filter
  const [statusFilter, setStatusFilter] = useState<string>('ALL')

  // Add / Edit Modal state
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingExpense, setEditingExpense] = useState<ActualExpense | null>(null)
  const [uploadingBill, setUploadingBill] = useState(false)
  const [uploadedBill, setUploadedBill] = useState<BillUploadResponse | null>(null)

  // Form fields
  const [formCategory, setFormCategory] = useState<BudgetLineItemCategory>('MATERIALS')
  const [formDescription, setFormDescription] = useState('')
  const [formVendorName, setFormVendorName] = useState('')
  const [formVendorGstin, setFormVendorGstin] = useState('')
  const [formInvoiceNumber, setFormInvoiceNumber] = useState('')
  const [formInvoiceDate, setFormInvoiceDate] = useState(new Date().toISOString().split('T')[0])
  const [formClaimedAmount, setFormClaimedAmount] = useState('')
  const [formSelectedBillId, setFormSelectedBillId] = useState('')

  // Finance Decision Modal state
  const [financeModalTarget, setFinanceModalTarget] = useState<ActualExpense | null>(null)
  const [financeAction, setFinanceAction] = useState<FinanceActionType>('VERIFY')
  const [financeVerifiedAmount, setFinanceVerifiedAmount] = useState('')
  const [financeRemarks, setFinanceRemarks] = useState('')

  const fetchLedger = useCallback(async () => {
    try {
      setErrorMsg(null)
      const res = await apiClient.get<ExpenseLedgerSummary>(`/events/${eventId}/expenses/summary`)
      setLedger(res.data)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setErrorMsg(e.response?.data?.message || 'Failed to load expense ledger.')
    } finally {
      setLoading(false)
    }
  }, [eventId])

  useEffect(() => {
    fetchLedger()
  }, [fetchLedger])

  // Handle bill file upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadingBill(true)
    setErrorMsg(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await apiClient.post<BillUploadResponse>(
        `/events/${eventId}/expenses/upload-bill`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      setUploadedBill(res.data)
      setFormSelectedBillId(res.data.id)
      setSuccessMsg(`Bill "${res.data.original_filename}" uploaded successfully.`)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setErrorMsg(e.response?.data?.message || 'Failed to upload bill evidence.')
    } finally {
      setUploadingBill(false)
    }
  }

  // Open Add Modal
  const openAddModal = () => {
    setEditingExpense(null)
    setUploadedBill(null)
    setFormCategory('MATERIALS')
    setFormDescription('')
    setFormVendorName('')
    setFormVendorGstin('')
    setFormInvoiceNumber('')
    setFormInvoiceDate(new Date().toISOString().split('T')[0])
    setFormClaimedAmount('')
    setFormSelectedBillId('')
    setErrorMsg(null)
    setShowAddModal(true)
  }

  // Open Edit Modal for DRAFT or QUERIED
  const openEditModal = (exp: ActualExpense) => {
    setEditingExpense(exp)
    setUploadedBill(null)
    setFormCategory(exp.category as BudgetLineItemCategory)
    setFormDescription(exp.description)
    setFormVendorName(exp.vendor_name)
    setFormVendorGstin(exp.vendor_gstin || '')
    setFormInvoiceNumber(exp.invoice_number || '')
    setFormInvoiceDate(exp.invoice_date)
    setFormClaimedAmount(exp.claimed_amount)
    setFormSelectedBillId(exp.bill_document_id)
    setErrorMsg(null)
    setShowAddModal(true)
  }

  // Save Expense (Create or Update)
  const handleSaveExpense = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formSelectedBillId) {
      setErrorMsg('A supporting bill document is mandatory.')
      return
    }
    const claimedNum = parseFloat(formClaimedAmount)
    if (isNaN(claimedNum) || claimedNum <= 0) {
      setErrorMsg('Claimed amount must be greater than 0.')
      return
    }

    setActionLoading(true)
    setErrorMsg(null)
    try {
      if (editingExpense) {
        const payload: ActualExpenseUpdate = {
          category: formCategory,
          description: formDescription.trim(),
          vendor_name: formVendorName.trim(),
          vendor_gstin: formVendorGstin.trim() || null,
          invoice_number: formInvoiceNumber.trim() || null,
          invoice_date: formInvoiceDate,
          claimed_amount: formClaimedAmount,
          bill_document_id: formSelectedBillId,
        }
        await apiClient.patch(`/events/${eventId}/expenses/${editingExpense.id}`, payload)
        setSuccessMsg('Expense line item updated.')
      } else {
        const payload: ActualExpenseCreate = {
          category: formCategory,
          description: formDescription.trim(),
          vendor_name: formVendorName.trim(),
          vendor_gstin: formVendorGstin.trim() || null,
          invoice_number: formInvoiceNumber.trim() || null,
          invoice_date: formInvoiceDate,
          claimed_amount: formClaimedAmount,
          bill_document_id: formSelectedBillId,
        }
        await apiClient.post(`/events/${eventId}/expenses`, payload)
        setSuccessMsg('Expense draft recorded successfully.')
      }
      setShowAddModal(false)
      await fetchLedger()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setErrorMsg(e.response?.data?.message || 'Failed to save expense item.')
    } finally {
      setActionLoading(false)
    }
  }

  // Delete draft expense
  const handleDeleteDraft = async (expId: string) => {
    if (!window.confirm('Are you sure you want to delete this draft expense?')) return
    setActionLoading(true)
    try {
      await apiClient.delete(`/events/${eventId}/expenses/${expId}`)
      setSuccessMsg('Draft expense removed.')
      await fetchLedger()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setErrorMsg(e.response?.data?.message || 'Failed to delete draft expense.')
    } finally {
      setActionLoading(false)
    }
  }

  // Submit Single or All Expenses
  const handleSubmitExpenses = async (expId?: string) => {
    setActionLoading(true)
    setErrorMsg(null)
    try {
      if (expId) {
        await apiClient.post(`/events/${eventId}/expenses/${expId}/submit`)
        setSuccessMsg('Expense submitted to Finance Officer for review.')
      } else {
        await apiClient.post(`/events/${eventId}/expenses/submit`)
        setSuccessMsg('All draft expenses submitted to Finance Officer.')
      }
      await fetchLedger()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setErrorMsg(e.response?.data?.message || 'Failed to submit expenses.')
    } finally {
      setActionLoading(false)
    }
  }

  // Open Finance Action Modal
  const openFinanceModal = (exp: ActualExpense, action: FinanceActionType) => {
    setFinanceModalTarget(exp)
    setFinanceAction(action)
    setFinanceVerifiedAmount('')
    setFinanceRemarks('')
    setErrorMsg(null)
  }

  // Submit Finance Action
  const handleFinanceSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!financeModalTarget) return

    if (financeAction === 'PARTIAL_VERIFY') {
      const vNum = parseFloat(financeVerifiedAmount)
      const cNum = parseFloat(financeModalTarget.claimed_amount)
      if (isNaN(vNum) || vNum <= 0 || vNum >= cNum) {
        setErrorMsg(`Verified amount must be strictly greater than 0 and less than claimed amount (₹${cNum.toFixed(2)}).`)
        return
      }
      if (!financeRemarks.trim()) {
        setErrorMsg('Justification remarks are mandatory for partial verification.')
        return
      }
    } else if (financeAction === 'QUERY' || financeAction === 'DISALLOW') {
      if (!financeRemarks.trim()) {
        setErrorMsg('Detailed remarks are mandatory for this finance decision.')
        return
      }
    }

    setActionLoading(true)
    setErrorMsg(null)
    try {
      if (financeAction === 'VERIFY') {
        await apiClient.post(`/events/${eventId}/expenses/${financeModalTarget.id}/verify`, {
          remarks: financeRemarks.trim() || undefined,
        })
        setSuccessMsg('Expense verified successfully.')
      } else if (financeAction === 'PARTIAL_VERIFY') {
        await apiClient.post(`/events/${eventId}/expenses/${financeModalTarget.id}/partial-verify`, {
          verified_amount: financeVerifiedAmount,
          remarks: financeRemarks.trim(),
        })
        setSuccessMsg('Expense partially verified.')
      } else if (financeAction === 'QUERY') {
        await apiClient.post(`/events/${eventId}/expenses/${financeModalTarget.id}/query`, {
          remarks: financeRemarks.trim(),
        })
        setSuccessMsg('Clarification query sent to Club Secretary.')
      } else if (financeAction === 'DISALLOW') {
        await apiClient.post(`/events/${eventId}/expenses/${financeModalTarget.id}/disallow`, {
          remarks: financeRemarks.trim(),
        })
        setSuccessMsg('Expense disallowed.')
      }
      setFinanceModalTarget(null)
      await fetchLedger()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      setErrorMsg(e.response?.data?.message || 'Failed to process finance decision.')
    } finally {
      setActionLoading(false)
    }
  }

  // Distinct bills in current event for reuse
  const existingBills = ledger?.items
    .filter((e) => e.bill_document_id && e.bill_original_filename)
    .reduce((acc, current) => {
      if (!acc.some((item) => item.id === current.bill_document_id)) {
        acc.push({
          id: current.bill_document_id,
          name: current.bill_original_filename || 'Bill Document',
        })
      }
      return acc
    }, [] as { id: string; name: string }[]) || []

  // Filtered items
  const filteredItems = ledger?.items.filter((item) => {
    if (statusFilter === 'ALL') return true
    return item.status === statusFilter
  }) || []

  const draftItemsCount = ledger?.items.filter((i) => i.status === 'DRAFT').length || 0

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-surface-500">
        <Loader2 className="w-8 h-8 animate-spin text-primary-600 mr-2" />
        <span>Loading actual expense ledger...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Notifications */}
      {errorMsg && (
        <div className="p-4 rounded-lg bg-danger-50 border border-danger-200 text-danger-800 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 mt-0.5 flex-shrink-0 text-danger-600" />
          <div className="flex-1 text-sm font-medium">{errorMsg}</div>
          <button onClick={() => setErrorMsg(null)} className="text-danger-500 hover:text-danger-700">
            &times;
          </button>
        </div>
      )}

      {successMsg && (
        <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 mt-0.5 flex-shrink-0 text-emerald-600" />
          <div className="flex-1 text-sm font-medium">{successMsg}</div>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-500 hover:text-emerald-700">
            &times;
          </button>
        </div>
      )}

      {/* Governance & Precondition Alerts */}
      {!isEventCompleted && (
        <div className="p-4 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 mt-0.5 text-amber-600 flex-shrink-0" />
          <div className="text-sm">
            <span className="font-bold">Expense Ledger Locked:</span> The event must transition to{' '}
            <span className="font-semibold text-amber-950">COMPLETED</span> execution status before actual expense claims
            can be recorded. Current status: <span className="font-semibold">{confirmedEventStatus || 'SCHEDULED'}</span>.
          </div>
        </div>
      )}

      {!isCertified && (
        <div className="p-4 rounded-lg bg-blue-50 border border-blue-200 text-blue-900 flex items-start gap-3">
          <FileCheck className="w-5 h-5 mt-0.5 text-blue-600 flex-shrink-0" />
          <div className="text-sm">
            <span className="font-bold">Faculty Advisor Delivery Certification Pending:</span> While the club may record
            and submit expenses once the event is COMPLETED, Finance Officers cannot make verification decisions until
            the Faculty Advisor certifies event delivery.
          </div>
        </div>
      )}

      {isAdmin && (
        <div className="p-4 rounded-lg bg-surface-100 border border-surface-300 text-surface-700 flex items-start gap-3">
          <ShieldCheck className="w-5 h-5 mt-0.5 text-surface-600 flex-shrink-0" />
          <div className="text-sm">
            <span className="font-bold">System Administrator View (Read-Only):</span> Under statutory segregation of
            duties, administrators cannot approve, verify, or alter financial claims. Verification is strictly reserved
            for authorized Finance Officers.
          </div>
        </div>
      )}

      {/* Financial Summary Cards */}
      {ledger && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-5 rounded-xl border border-surface-200 bg-white shadow-sm">
            <span className="text-xs font-semibold uppercase tracking-wider text-surface-500">Sanctioned Budget</span>
            <p className="text-2xl font-bold text-surface-900 mt-1">
              ₹{parseFloat(ledger.sanctioned_budget).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </p>
            <span className="text-[11px] text-surface-400 mt-1 block">Approved proposal expenditure</span>
          </div>

          <div className="p-5 rounded-xl border border-surface-200 bg-white shadow-sm">
            <span className="text-xs font-semibold uppercase tracking-wider text-surface-500">Total Claimed</span>
            <p className="text-2xl font-bold text-primary-700 mt-1">
              ₹{parseFloat(ledger.total_claimed_spend).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </p>
            <span className="text-[11px] text-surface-400 mt-1 block">Active claims submitted</span>
          </div>

          <div className="p-5 rounded-xl border border-surface-200 bg-white shadow-sm">
            <span className="text-xs font-semibold uppercase tracking-wider text-surface-500">Total Verified</span>
            <p className="text-2xl font-bold text-emerald-700 mt-1">
              ₹{parseFloat(ledger.total_verified_spend).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </p>
            <span className="text-[11px] text-emerald-600 font-medium mt-1 block">Audited &amp; Approved</span>
          </div>

          <div className="p-5 rounded-xl border border-surface-200 bg-white shadow-sm">
            <span className="text-xs font-semibold uppercase tracking-wider text-surface-500">Total Disallowed</span>
            <p className="text-2xl font-bold text-danger-700 mt-1">
              ₹{parseFloat(ledger.total_disallowed_spend).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </p>
            <span className="text-[11px] text-danger-600 font-medium mt-1 block">Rejected / Ineligible</span>
          </div>
        </div>
      )}

      {/* Action Bar & Filter */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pt-2">
        {/* Status Filters */}
        <div className="flex flex-wrap gap-1.5">
          {['ALL', 'DRAFT', 'SUBMITTED', 'VERIFIED', 'PARTIALLY_VERIFIED', 'QUERIED', 'DISALLOWED'].map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                statusFilter === st
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'bg-surface-100 text-surface-600 hover:bg-surface-200'
              }`}
            >
              {st === 'ALL' ? 'All' : st.replace('_', ' ')}
              {ledger && st !== 'ALL' && ledger.status_counts[st] ? ` (${ledger.status_counts[st]})` : ''}
              {ledger && st === 'ALL' ? ` (${ledger.total_expenses_count})` : ''}
            </button>
          ))}
        </div>

        {/* Action Buttons for Secretary */}
        {isSecretary && isEventCompleted && (
          <div className="flex items-center gap-2">
            <button
              onClick={openAddModal}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-semibold shadow-sm transition-colors"
            >
              <Plus className="w-4 h-4" /> Add Expense
            </button>

            {draftItemsCount > 0 && (
              <button
                onClick={() => handleSubmitExpenses()}
                disabled={actionLoading}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 text-sm font-semibold shadow-sm transition-colors disabled:opacity-50"
              >
                {actionLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileCheck className="w-4 h-4" />}
                Submit All Drafts ({draftItemsCount})
              </button>
            )}
          </div>
        )}
      </div>

      {/* Expenses Table */}
      {filteredItems.length === 0 ? (
        <div className="card p-12 text-center text-surface-400 space-y-3">
          <FileText className="w-12 h-12 mx-auto text-surface-300" />
          <p className="text-base font-semibold text-surface-600">No actual expenses found</p>
          <p className="text-xs text-surface-400 max-w-md mx-auto">
            {isSecretary && isEventCompleted
              ? 'Record expenses incurred during the event along with physical bill or invoice evidence.'
              : 'Actual expenses will appear here once submitted by the Club Secretary.'}
          </p>
        </div>
      ) : (
        <div className="card overflow-hidden border border-surface-200 shadow-sm rounded-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="bg-surface-50 border-b border-surface-200 text-surface-600 text-xs uppercase tracking-wider font-semibold">
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4">Category &amp; Description</th>
                  <th className="py-3.5 px-4">Vendor &amp; Invoice</th>
                  <th className="py-3.5 px-4 text-right">Claimed</th>
                  <th className="py-3.5 px-4 text-right">Verified</th>
                  <th className="py-3.5 px-4">Bill Evidence</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-200 bg-white">
                {filteredItems.map((exp) => {
                  const statusColors: Record<string, string> = {
                    DRAFT: 'bg-surface-100 text-surface-700 border-surface-300',
                    SUBMITTED: 'bg-blue-50 text-blue-700 border-blue-200',
                    VERIFIED: 'bg-emerald-50 text-emerald-700 border-emerald-200',
                    PARTIALLY_VERIFIED: 'bg-amber-50 text-amber-700 border-amber-200',
                    QUERIED: 'bg-purple-50 text-purple-700 border-purple-200',
                    DISALLOWED: 'bg-danger-50 text-danger-700 border-danger-200',
                  }

                  const isTerminal = ['VERIFIED', 'PARTIALLY_VERIFIED', 'DISALLOWED'].includes(exp.status)

                  return (
                    <tr key={exp.id} className="hover:bg-surface-50/75 transition-colors">
                      {/* Status */}
                      <td className="py-4 px-4 align-top">
                        <span
                          className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold border ${
                            statusColors[exp.status] || 'bg-surface-100 text-surface-700 border-surface-200'
                          }`}
                        >
                          {exp.status.replace('_', ' ')}
                        </span>
                        {exp.is_flagged_for_review && (
                          <div
                            className="mt-1 flex items-center gap-1 text-[11px] text-amber-600 font-medium"
                            title={exp.review_notes || 'Flagged for review'}
                          >
                            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                            <span className="truncate max-w-[120px]">Flagged</span>
                          </div>
                        )}
                      </td>

                      {/* Category & Description */}
                      <td className="py-4 px-4 align-top">
                        <span className="text-xs font-semibold text-primary-700 uppercase tracking-wider block">
                          {exp.category}
                        </span>
                        <p className="text-sm font-medium text-surface-900 mt-0.5">{exp.description}</p>
                        {exp.query_reason && (
                          <div className="mt-2 p-2.5 bg-purple-50 border border-purple-200 rounded-md text-xs text-purple-900">
                            <span className="font-bold block">Finance Query:</span>
                            {exp.query_reason}
                          </div>
                        )}
                        {exp.finance_remarks && (
                          <div className="mt-1 text-xs text-surface-500 italic">
                            Finance note: {exp.finance_remarks}
                          </div>
                        )}
                      </td>

                      {/* Vendor & Invoice */}
                      <td className="py-4 px-4 align-top text-xs space-y-1">
                        <div className="flex items-center gap-1.5 font-medium text-surface-800">
                          <Building2 className="w-3.5 h-3.5 text-surface-400" />
                          <span>{exp.vendor_name}</span>
                        </div>
                        {exp.invoice_number ? (
                          <div className="text-surface-600">Inv: {exp.invoice_number}</div>
                        ) : (
                          <div className="text-amber-600 italic">No invoice # (Bill attached)</div>
                        )}
                        <div className="flex items-center gap-1 text-surface-400">
                          <Calendar className="w-3 h-3" />
                          <span>{exp.invoice_date}</span>
                        </div>
                      </td>

                      {/* Claimed Amount */}
                      <td className="py-4 px-4 align-top text-right font-bold text-surface-900 text-sm">
                        ₹{parseFloat(exp.claimed_amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </td>

                      {/* Verified / Disallowed Amount */}
                      <td className="py-4 px-4 align-top text-right text-sm">
                        {exp.verified_amount ? (
                          <div>
                            <span className="font-bold text-emerald-700">
                              ₹{parseFloat(exp.verified_amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                            </span>
                            {parseFloat(exp.disallowed_amount) > 0 && (
                              <span className="block text-xs text-danger-600 mt-0.5">
                                Disallowed: ₹
                                {parseFloat(exp.disallowed_amount).toLocaleString('en-IN', {
                                  minimumFractionDigits: 2,
                                })}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-surface-400 text-xs italic">Pending</span>
                        )}
                      </td>

                      {/* Bill Evidence */}
                      <td className="py-4 px-4 align-top">
                        {exp.bill_document_id ? (
                          <a
                            href={`/api/v1/events/${eventId}/documents/${exp.bill_document_id}/download`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs text-primary-600 hover:text-primary-800 font-medium p-1.5 rounded hover:bg-primary-50 transition-colors"
                            title="Download / View Bill Evidence"
                          >
                            <Download className="w-3.5 h-3.5" />
                            <span className="truncate max-w-[130px]">
                              {exp.bill_original_filename || 'View Bill'}
                            </span>
                          </a>
                        ) : (
                          <span className="text-xs text-danger-500 font-medium">Missing Bill</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-4 px-4 align-top text-right">
                        {/* Secretary Actions */}
                        {isSecretary && exp.status === 'DRAFT' && (
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={() => openEditModal(exp)}
                              className="px-2.5 py-1 text-xs font-semibold bg-surface-100 text-surface-700 rounded hover:bg-surface-200"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleSubmitExpenses(exp.id)}
                              className="px-2.5 py-1 text-xs font-semibold bg-primary-50 text-primary-700 rounded hover:bg-primary-100"
                            >
                              Submit
                            </button>
                            <button
                              onClick={() => handleDeleteDraft(exp.id)}
                              className="p-1 text-danger-600 hover:text-danger-800 rounded hover:bg-danger-50"
                              title="Delete Draft"
                            >
                              &times;
                            </button>
                          </div>
                        )}

                        {isSecretary && exp.status === 'QUERIED' && (
                          <button
                            onClick={() => openEditModal(exp)}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-bold bg-purple-600 text-white rounded-lg hover:bg-purple-700 shadow-sm"
                          >
                            <RefreshCw className="w-3 h-3" /> Amend &amp; Resubmit
                          </button>
                        )}

                        {/* Finance Officer Audit Actions */}
                        {isFinanceOfficer && exp.status === 'SUBMITTED' && (
                          <div className="flex flex-col items-end gap-1">
                            {!isCertified ? (
                              <span className="text-[11px] text-amber-700 font-semibold bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                                Awaiting FA Certification
                              </span>
                            ) : (
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => openFinanceModal(exp, 'VERIFY')}
                                  className="px-2 py-1 text-xs font-semibold bg-emerald-600 text-white rounded hover:bg-emerald-700 shadow-sm"
                                >
                                  Verify
                                </button>
                                <button
                                  onClick={() => openFinanceModal(exp, 'PARTIAL_VERIFY')}
                                  className="px-2 py-1 text-xs font-semibold bg-amber-600 text-white rounded hover:bg-amber-700 shadow-sm"
                                >
                                  Partial
                                </button>
                                <button
                                  onClick={() => openFinanceModal(exp, 'QUERY')}
                                  className="px-2 py-1 text-xs font-semibold bg-purple-600 text-white rounded hover:bg-purple-700 shadow-sm"
                                >
                                  Query
                                </button>
                                <button
                                  onClick={() => openFinanceModal(exp, 'DISALLOW')}
                                  className="px-2 py-1 text-xs font-semibold bg-danger-600 text-white rounded hover:bg-danger-700 shadow-sm"
                                >
                                  Disallow
                                </button>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Immutable indicator */}
                        {isTerminal && (
                          <span className="inline-flex items-center gap-1 text-xs text-surface-400 italic">
                            <Check className="w-3.5 h-3.5 text-surface-400" /> Audited (Immutable)
                          </span>
                        )}

                        {exp.status === 'SUBMITTED' && !isFinanceOfficer && (
                          <span className="text-xs text-blue-600 font-medium">In Finance Queue</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add / Edit Expense Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl max-w-xl w-full p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-surface-100 pb-3">
              <h3 className="text-lg font-bold text-surface-900">
                {editingExpense ? (editingExpense.status === 'QUERIED' ? 'Amend Queried Expense' : 'Edit Expense Item') : 'Add Actual Expense Item'}
              </h3>
              <button onClick={() => setShowAddModal(false)} className="text-surface-400 hover:text-surface-600 text-xl font-bold">
                &times;
              </button>
            </div>

            {editingExpense?.query_reason && (
              <div className="p-3 bg-purple-50 border border-purple-200 rounded-lg text-xs text-purple-900">
                <span className="font-bold block">Finance Query Reason:</span>
                {editingExpense.query_reason}
              </div>
            )}

            <form onSubmit={handleSaveExpense} className="space-y-4">
              {/* Supporting Bill Upload or Select */}
              <div className="space-y-2 p-4 bg-surface-50 border border-surface-200 rounded-xl">
                <label className="text-xs font-bold text-surface-800 uppercase tracking-wider block">
                  Mandatory Bill / Invoice Evidence <span className="text-danger-500">*</span>
                </label>

                {existingBills.length > 0 && (
                  <div className="mb-2">
                    <label className="text-xs text-surface-600 block mb-1">
                      Reuse an existing bill uploaded for this event:
                    </label>
                    <select
                      value={formSelectedBillId}
                      onChange={(e) => setFormSelectedBillId(e.target.value)}
                      className="input text-xs w-full"
                    >
                      <option value="">-- Or upload a new bill below --</option>
                      {existingBills.map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 px-3 py-2 bg-white border border-surface-300 rounded-lg cursor-pointer hover:bg-surface-50 text-xs font-medium text-surface-700 shadow-sm">
                    {uploadingBill ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4 text-primary-600" />}
                    <span>{uploadingBill ? 'Uploading...' : 'Upload New Bill (PDF / Image)'}</span>
                    <input
                      type="file"
                      accept=".pdf,.png,.jpg,.jpeg"
                      onChange={handleFileUpload}
                      disabled={uploadingBill}
                      className="hidden"
                    />
                  </label>
                  {uploadedBill && (
                    <span className="text-xs text-emerald-700 font-medium truncate max-w-[200px]">
                      {uploadedBill.original_filename}
                    </span>
                  )}
                  {formSelectedBillId && !uploadedBill && (
                    <span className="text-xs text-primary-700 font-medium">Bill selected</span>
                  )}
                </div>
                <span className="text-[11px] text-surface-400 block">
                  Supported formats: PDF, PNG, JPEG (max 10MB). Exact SHA-256 duplicate bills across events are blocked.
                </span>
              </div>

              {/* Category */}
              <div>
                <label className="text-xs font-semibold text-surface-700 block mb-1">Category *</label>
                <select
                  value={formCategory}
                  onChange={(e) => setFormCategory(e.target.value as BudgetLineItemCategory)}
                  className="input text-sm w-full"
                  required
                >
                  {CATEGORIES.map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>
              </div>

              {/* Description */}
              <div>
                <label className="text-xs font-semibold text-surface-700 block mb-1">Description *</label>
                <input
                  type="text"
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  placeholder="e.g. Stage lighting and acoustic equipment rental"
                  className="input text-sm w-full"
                  required
                />
              </div>

              {/* Vendor Information */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-surface-700 block mb-1">Vendor Name *</label>
                  <input
                    type="text"
                    value={formVendorName}
                    onChange={(e) => setFormVendorName(e.target.value)}
                    placeholder="e.g. Apex Audio Visuals Ltd"
                    className="input text-sm w-full"
                    required
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-surface-700 block mb-1">Vendor GSTIN (Optional)</label>
                  <input
                    type="text"
                    value={formVendorGstin}
                    onChange={(e) => setFormVendorGstin(e.target.value)}
                    placeholder="e.g. 29ABCDE1234F1Z5"
                    className="input text-sm w-full"
                  />
                </div>
              </div>

              {/* Invoice Number & Date */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-surface-700 block mb-1">
                    Invoice Number <span className="text-surface-400 font-normal">(Optional)</span>
                  </label>
                  <input
                    type="text"
                    value={formInvoiceNumber}
                    onChange={(e) => setFormInvoiceNumber(e.target.value)}
                    placeholder="e.g. INV-2026-0042"
                    className="input text-sm w-full"
                  />
                  <span className="text-[10px] text-surface-400 block mt-0.5">
                    If omitted, expense will be flagged for manual review.
                  </span>
                </div>
                <div>
                  <label className="text-xs font-semibold text-surface-700 block mb-1">Invoice Date *</label>
                  <input
                    type="date"
                    value={formInvoiceDate}
                    onChange={(e) => setFormInvoiceDate(e.target.value)}
                    className="input text-sm w-full"
                    required
                  />
                </div>
              </div>

              {/* Claimed Amount */}
              <div>
                <label className="text-xs font-semibold text-surface-700 block mb-1">Claimed Amount (₹) *</label>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={formClaimedAmount}
                  onChange={(e) => setFormClaimedAmount(e.target.value)}
                  placeholder="0.00"
                  className="input text-sm w-full font-semibold"
                  required
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-surface-100">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 text-sm text-surface-600 hover:text-surface-800 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || uploadingBill}
                  className="px-5 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-semibold shadow-sm transition-colors disabled:opacity-50 inline-flex items-center gap-2"
                >
                  {actionLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  {editingExpense ? 'Save Changes' : 'Record Expense'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Finance Action Modal */}
      {financeModalTarget && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-surface-100 pb-3">
              <h3 className="text-lg font-bold text-surface-900">
                {financeAction === 'VERIFY' && 'Verify Actual Expense'}
                {financeAction === 'PARTIAL_VERIFY' && 'Partially Verify Actual Expense'}
                {financeAction === 'QUERY' && 'Query Actual Expense'}
                {financeAction === 'DISALLOW' && 'Disallow Actual Expense'}
              </h3>
              <button
                onClick={() => setFinanceModalTarget(null)}
                className="text-surface-400 hover:text-surface-600 text-xl font-bold"
              >
                &times;
              </button>
            </div>

            <div className="p-3 bg-surface-50 rounded-lg text-xs space-y-1 text-surface-700 border border-surface-200">
              <div>
                <span className="font-semibold">Description:</span> {financeModalTarget.description}
              </div>
              <div>
                <span className="font-semibold">Vendor:</span> {financeModalTarget.vendor_name}
              </div>
              <div>
                <span className="font-semibold">Claimed Amount:</span>{' '}
                <span className="font-bold text-surface-900">
                  ₹{parseFloat(financeModalTarget.claimed_amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </span>
              </div>
            </div>

            <form onSubmit={handleFinanceSubmit} className="space-y-4">
              {financeAction === 'PARTIAL_VERIFY' && (
                <div>
                  <label className="text-xs font-semibold text-surface-700 block mb-1">
                    Verified Amount (₹) <span className="text-danger-500">*</span>
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    max={parseFloat(financeModalTarget.claimed_amount) - 0.01}
                    value={financeVerifiedAmount}
                    onChange={(e) => setFinanceVerifiedAmount(e.target.value)}
                    placeholder="Enter approved amount (< claimed)"
                    className="input text-sm w-full font-semibold"
                    required
                  />
                  <span className="text-[11px] text-surface-400 block mt-0.5">
                    Remaining disallowed amount will be automatically derived as disallowed.
                  </span>
                </div>
              )}

              <div>
                <label className="text-xs font-semibold text-surface-700 block mb-1">
                  Finance Remarks / Justification{' '}
                  {financeAction !== 'VERIFY' ? (
                    <span className="text-danger-500">*</span>
                  ) : (
                    <span className="text-surface-400 font-normal">(Optional)</span>
                  )}
                </label>
                <textarea
                  value={financeRemarks}
                  onChange={(e) => setFinanceRemarks(e.target.value)}
                  placeholder={
                    financeAction === 'QUERY'
                      ? 'Specify why this claim requires amendment or documentation...'
                      : financeAction === 'DISALLOW'
                      ? 'Specify reason for disallowance (ineligible expense, unapproved item, etc.)...'
                      : 'Audit observations or notes...'
                  }
                  rows={3}
                  className="input text-sm w-full resize-none"
                  required={financeAction !== 'VERIFY'}
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-surface-100">
                <button
                  type="button"
                  onClick={() => setFinanceModalTarget(null)}
                  className="px-4 py-2 text-sm text-surface-600 hover:text-surface-800 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className={`px-5 py-2 text-white rounded-lg text-sm font-semibold shadow-sm transition-colors disabled:opacity-50 inline-flex items-center gap-2 ${
                    financeAction === 'VERIFY'
                      ? 'bg-emerald-600 hover:bg-emerald-700'
                      : financeAction === 'PARTIAL_VERIFY'
                      ? 'bg-amber-600 hover:bg-amber-700'
                      : financeAction === 'QUERY'
                      ? 'bg-purple-600 hover:bg-purple-700'
                      : 'bg-danger-600 hover:bg-danger-700'
                  }`}
                >
                  {actionLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                  Confirm Decision
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
