import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { ExpenseLedgerTab } from '@/components/expenses/ExpenseLedgerTab'
import { apiClient } from '@/lib/apiClient'

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  registerAuthStoreHooks: vi.fn(),
}))

describe('ExpenseLedgerTab Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const mockLedgerSummary = {
    event_id: 'ev-123',
    sanctioned_budget: '50000.00',
    total_claimed_spend: '25000.00',
    total_verified_spend: '20000.00',
    total_disallowed_spend: '5000.00',
    total_expenses_count: 2,
    status_counts: {
      SUBMITTED: 1,
      VERIFIED: 1,
    },
    category_breakdown: [
      {
        category: 'MATERIALS',
        claimed_amount: '15000.00',
        verified_amount: '15000.00',
        disallowed_amount: '0.00',
        count: 1,
      },
      {
        category: 'FOOD',
        claimed_amount: '10000.00',
        verified_amount: '5000.00',
        disallowed_amount: '5000.00',
        count: 1,
      },
    ],
    can_submit: true,
    can_audit: false,
    delivery_certified: true,
    items: [
      {
        id: 'exp-1',
        event_id: 'ev-123',
        budget_line_item_id: null,
        category: 'MATERIALS',
        description: 'Robot chassis kits and Arduino microcontrollers',
        vendor_name: 'RoboSupplies India',
        vendor_gstin: '29AAAAA0000A1Z5',
        invoice_number: 'RSI-2026-99',
        invoice_date: '2026-09-21',
        claimed_amount: '15000.00',
        verified_amount: '15000.00',
        disallowed_amount: '0.00',
        status: 'VERIFIED',
        bill_document_id: 'doc-1',
        submitted_by: 'sec-1',
        submitted_by_name: 'Club Secretary',
        submitted_by_email: 'secretary@college.edu',
        submitted_at: '2026-09-21T10:00:00Z',
        verified_by: 'fo-1',
        verified_by_name: 'Finance Officer',
        verified_by_email: 'finance@college.edu',
        verified_at: '2026-09-21T12:00:00Z',
        finance_remarks: 'Verified against hardware delivery voucher.',
        query_reason: null,
        is_flagged_for_review: false,
        review_notes: null,
        bill_original_filename: 'robo_chassis_invoice.pdf',
        created_at: '2026-09-21T09:00:00Z',
        updated_at: '2026-09-21T12:00:00Z',
      },
      {
        id: 'exp-2',
        event_id: 'ev-123',
        budget_line_item_id: null,
        category: 'FOOD',
        description: 'Participant lunch catering',
        vendor_name: 'Campus Kitchens',
        vendor_gstin: null,
        invoice_number: null,
        invoice_date: '2026-09-21',
        claimed_amount: '10000.00',
        verified_amount: null,
        disallowed_amount: '0.00',
        status: 'SUBMITTED',
        bill_document_id: 'doc-2',
        submitted_by: 'sec-1',
        submitted_by_name: 'Club Secretary',
        submitted_by_email: 'secretary@college.edu',
        submitted_at: '2026-09-21T10:30:00Z',
        verified_by: null,
        verified_by_name: null,
        verified_by_email: null,
        verified_at: null,
        finance_remarks: null,
        query_reason: null,
        is_flagged_for_review: true,
        review_notes: 'Missing invoice number; bill document attached.',
        bill_original_filename: 'catering_receipt.pdf',
        created_at: '2026-09-21T09:30:00Z',
        updated_at: '2026-09-21T10:30:00Z',
      },
    ],
  }

  it('renders ledger financial summary cards and items list', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: mockLedgerSummary })

    render(
      <ExpenseLedgerTab
        eventId="ev-123"
        eventStatus="APPROVED"
        confirmedEventStatus="COMPLETED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText(/Sanctioned Budget/i)).toBeInTheDocument()
      expect(screen.getByText(/Total Claimed/i)).toBeInTheDocument()
      expect(screen.getByText(/Total Verified/i)).toBeInTheDocument()
      expect(screen.getByText(/Total Disallowed/i)).toBeInTheDocument()
      expect(screen.getByText('Robot chassis kits and Arduino microcontrollers')).toBeInTheDocument()
      expect(screen.getByText('Participant lunch catering')).toBeInTheDocument()
      expect(screen.getByText('robo_chassis_invoice.pdf')).toBeInTheDocument()
    })
  })

  it('renders locked banner when event execution is not yet completed', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: mockLedgerSummary })

    render(
      <ExpenseLedgerTab
        eventId="ev-123"
        eventStatus="APPROVED"
        confirmedEventStatus="SCHEDULED"
        isCertified={false}
        isSecretary={true}
        isFinanceOfficer={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText(/Expense Ledger Locked:/i)).toBeInTheDocument()
      expect(screen.queryByText('+ Add Expense')).not.toBeInTheDocument()
    })
  })

  it('renders Finance Officer audit buttons when delivery is certified', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: mockLedgerSummary })

    render(
      <ExpenseLedgerTab
        eventId="ev-123"
        eventStatus="APPROVED"
        confirmedEventStatus="COMPLETED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Verify')).toBeInTheDocument()
      expect(screen.getByText('Partial')).toBeInTheDocument()
      expect(screen.getByText('Query')).toBeInTheDocument()
      expect(screen.getByText('Disallow')).toBeInTheDocument()
    })
  })

  it('renders awaiting certification indicator when delivery is not certified for Finance Officer', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: mockLedgerSummary })

    render(
      <ExpenseLedgerTab
        eventId="ev-123"
        eventStatus="APPROVED"
        confirmedEventStatus="COMPLETED"
        isCertified={false}
        isSecretary={false}
        isFinanceOfficer={true}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Awaiting FA Certification')).toBeInTheDocument()
      expect(screen.queryByText('Verify')).not.toBeInTheDocument()
    })
  })

  it('renders system administrator read-only view alert and prevents audit action buttons', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: mockLedgerSummary })

    render(
      <ExpenseLedgerTab
        eventId="ev-123"
        eventStatus="APPROVED"
        confirmedEventStatus="COMPLETED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isAdmin={true}
      />
    )

    await waitFor(() => {
      expect(screen.getByText(/System Administrator View \(Read-Only\):/i)).toBeInTheDocument()
      expect(screen.queryByText('Verify')).not.toBeInTheDocument()
      expect(screen.queryByText('+ Add Expense')).not.toBeInTheDocument()
    })
  })
})
