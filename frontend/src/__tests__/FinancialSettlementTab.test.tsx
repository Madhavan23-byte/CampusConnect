import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { FinancialSettlementTab } from '@/components/settlement/FinancialSettlementTab'
import { apiClient } from '@/lib/apiClient'
import type { FinancialSettlementDetail, CashAdvance, ActualIncome, SettlementPayment, SettlementRevision } from '@/types'

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  registerAuthStoreHooks: vi.fn(),
}))

describe('FinancialSettlementTab Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const mockSettlement: FinancialSettlementDetail = {
    id: 'set-1',
    event_id: 'ev-100',
    approved_version_id: 'ver-1',
    sanctioned_grant: '50000.00',
    sanctioned_expenditure: '60000.00',
    expected_income: '10000.00',
    total_claimed_expenditure: '45000.00',
    total_verified_expenditure: '40000.00',
    total_disallowed_expenditure: '5000.00',
    total_verified_income: '8000.00',
    net_deficit: '32000.00',
    institutional_payout: '32000.00',
    cash_advance_disbursed: '20000.00',
    settlement_balance: '12000.00',
    reimbursement_due: '12000.00',
    refund_due: '0.00',
    settlement_type: 'REIMBURSEMENT_DUE',
    status: 'DRAFT',
    prepared_by: 'user-sec',
    submitted_at: null,
    audited_by: null,
    audited_at: null,
    finance_remarks: null,
    query_reason: null,
    created_at: '2026-09-24T10:00:00Z',
    updated_at: '2026-09-24T10:00:00Z',
    payments: [],
    revisions: [],
  }

  const mockAdvance: CashAdvance = {
    id: 'adv-1',
    event_id: 'ev-100',
    recipient_id: 'user-sec',
    amount_requested: '20000.00',
    amount_approved: '20000.00',
    amount_disbursed: '20000.00',
    status: 'DISBURSED',
    notes: 'Urgent hardware purchase advance',
    rejection_reason: null,
    approved_by: 'user-fo',
    disbursed_by: 'user-fo',
    disbursement_date: '2026-09-20T10:00:00Z',
    payment_reference: 'UTR-2026-BANK-001',
    created_at: '2026-09-18T10:00:00Z',
    updated_at: '2026-09-20T10:00:00Z',
  }

  const mockIncomes: ActualIncome[] = [
    {
      id: 'inc-1',
      event_id: 'ev-100',
      source_type: 'REGISTRATION_FEE',
      description: 'Delegate registration tickets',
      payer_name: 'Delegates Portal',
      amount: '8000.00',
      received_date: '2026-09-22',
      reference_number: 'REC-001',
      evidence_document_id: 'doc-inc-1',
      status: 'VERIFIED',
      recorded_by: 'user-sec',
      verified_by: 'user-fo',
      verified_at: '2026-09-23T10:00:00Z',
      finance_remarks: 'Verified against bank transaction',
      created_at: '2026-09-22T10:00:00Z',
      updated_at: '2026-09-23T10:00:00Z',
    },
  ]

  const mockClosure = {
    eligible: false,
    blockers: ['SETTLEMENT_NOT_SETTLED', 'PENDING_PAYMENTS'],
    event_id: 'ev-100',
    settlement_id: 'set-1',
  }

  const setupDefaultMocks = (overrides = {}) => {
    const s = { ...mockSettlement, ...overrides }
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/settlement')) return Promise.resolve({ data: s })
      if (url.endsWith('/advances')) return Promise.resolve({ data: mockAdvance })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: mockIncomes })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: s.payments || [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: s.revisions || [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.reject(new Error('Unknown url: ' + url))
    })
  }

  // =========================================================================
  // 1. ROLE TESTS
  // =========================================================================

  it('1. Secretary sees advance request when no advance exists', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/advances')) return Promise.resolve({ data: null })
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Request Cash Advance')).toBeInTheDocument()
    })
  })

  it('2. Secretary sees income record button', async () => {
    setupDefaultMocks()
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Record Income')).toBeInTheDocument()
    })
  })

  it('3. Secretary sees prepare and submit buttons when in DRAFT', async () => {
    setupDefaultMocks({ status: 'DRAFT' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Recalculate Draft')).toBeInTheDocument()
      expect(screen.getByText('Submit for Finance Audit')).toBeInTheDocument()
    })
  })

  it('4. Secretary cannot see Finance action controls', async () => {
    setupDefaultMocks({ status: 'UNDER_AUDIT' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.queryByText('Approve Settlement')).not.toBeInTheDocument()
      expect(screen.queryByText('Raise Audit Query')).not.toBeInTheDocument()
      expect(screen.queryByText('Record Reimbursement Payment')).not.toBeInTheDocument()
    })
  })

  it('5. Finance sees advance action buttons when advance is requested or approved', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/advances')) {
        return Promise.resolve({
          data: { ...mockAdvance, status: 'REQUESTED', amount_approved: null, amount_disbursed: '0.00' },
        })
      }
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Approve Advance')).toBeInTheDocument()
      expect(screen.getByText('Reject Advance')).toBeInTheDocument()
    })
  })

  it('6. Finance sees income verification controls for recorded rows', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/incomes')) {
        return Promise.resolve({
          data: [{ ...mockIncomes[0], status: 'RECORDED' }],
        })
      }
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/advances')) return Promise.resolve({ data: mockAdvance })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Verify')).toBeInTheDocument()
      expect(screen.getByText('Reject')).toBeInTheDocument()
    })
  })

  it('7. Finance sees audit approve and query buttons when UNDER_AUDIT', async () => {
    setupDefaultMocks({ status: 'UNDER_AUDIT' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Approve Settlement')).toBeInTheDocument()
      expect(screen.getByText('Raise Audit Query')).toBeInTheDocument()
    })
  })

  it('8. Finance sees record reimbursement payment button when PENDING_REIMBURSEMENT', async () => {
    setupDefaultMocks({ status: 'PENDING_REIMBURSEMENT', settlement_type: 'REIMBURSEMENT_DUE' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Record Reimbursement Payment')).toBeInTheDocument()
    })
  })

  it('9. Principal can see reopen account button on SETTLED settlement', async () => {
    setupDefaultMocks({ status: 'SETTLED', settlement_balance: '0.00' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={true}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Reopen Account')).toBeInTheDocument()
    })
  })

  it('10. System Admin has no financial mutation actions', async () => {
    setupDefaultMocks({ status: 'UNDER_AUDIT' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={true}
      />
    )

    await waitFor(() => {
      expect(screen.queryByText('Approve Settlement')).not.toBeInTheDocument()
      expect(screen.queryByText('Record Income')).not.toBeInTheDocument()
      expect(screen.queryByText('Submit for Finance Audit')).not.toBeInTheDocument()
    })
  })

  // =========================================================================
  // 2. STATE TESTS
  // =========================================================================

  it('11. Unprepared state (404) shows onboarding card for Secretary', async () => {
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/settlement')) {
        return Promise.reject({ response: { status: 404, data: { message: 'Not prepared' } } })
      }
      return Promise.resolve({ data: null })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Financial Settlement Not Prepared')).toBeInTheDocument()
      expect(screen.getByText('Prepare Draft Settlement')).toBeInTheDocument()
    })
  })

  it('12. DRAFT state displays Draft badge and submit button', async () => {
    setupDefaultMocks({ status: 'DRAFT' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Draft')).toBeInTheDocument()
      expect(screen.getByText('Submit for Finance Audit')).toBeInTheDocument()
    })
  })

  it('13. UNDER_AUDIT state displays Under Audit badge', async () => {
    setupDefaultMocks({ status: 'UNDER_AUDIT' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Under Audit')).toBeInTheDocument()
    })
  })

  it('14. QUERIED state displays query reason banner', async () => {
    setupDefaultMocks({ status: 'QUERIED', query_reason: 'Bill invoice mismatch in Catering' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Finance Audit Query Raised')).toBeInTheDocument()
      expect(screen.getByText('"Bill invoice mismatch in Catering"')).toBeInTheDocument()
    })
  })

  it('15. APPROVED state displays Approved badge', async () => {
    setupDefaultMocks({ status: 'APPROVED' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getAllByText(/Approved/i).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('16. PENDING_REIMBURSEMENT state displays Pending Reimbursement badge and direction', async () => {
    setupDefaultMocks({ status: 'PENDING_REIMBURSEMENT', settlement_type: 'REIMBURSEMENT_DUE' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Pending Reimbursement')).toBeInTheDocument()
      expect(screen.getByText(/Direction: Institution → Club/i)).toBeInTheDocument()
    })
  })

  it('17. PENDING_REFUND state displays Pending Refund badge and refund direction', async () => {
    setupDefaultMocks({
      status: 'PENDING_REFUND',
      settlement_type: 'REFUND_DUE',
      settlement_balance: '-5000.00',
      refund_due: '5000.00',
      reimbursement_due: '0.00',
    })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Pending Refund')).toBeInTheDocument()
      expect(screen.getByText(/Direction: Club → Institution/i)).toBeInTheDocument()
      expect(screen.getByText('Record Refund Receipt')).toBeInTheDocument()
    })
  })

  it('18. SETTLED state displays Settled badge and zero balance indication', async () => {
    setupDefaultMocks({
      status: 'SETTLED',
      settlement_balance: '0.00',
      settlement_type: 'BALANCED',
    })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getAllByText(/Settled/i).length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText(/Balanced/i).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('19. REOPENED state displays Reopened badge', async () => {
    setupDefaultMocks({ status: 'REOPENED' })
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Reopened')).toBeInTheDocument()
    })
  })

  // =========================================================================
  // 3. ERROR TESTS
  // =========================================================================

  it('20. 403 Forbidden displays Access Denied message banner', async () => {
    ;vi.mocked(apiClient.get).mockImplementation(() => {
      return Promise.reject({ response: { status: 403, data: { message: 'Forbidden' } } })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText(/Access Denied: You are not authorized/i)).toBeInTheDocument()
    })
  })

  it('21. 409 Conflict displays stale data warning banner with recalculate button', async () => {
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/settlement')) {
        return Promise.reject({ response: { status: 409, data: { message: 'Settlement state is stale' } } })
      }
      return Promise.resolve({ data: null })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText(/Financial Data Outdated \(Conflict 409\)/i)).toBeInTheDocument()
      expect(screen.getByText('Recalculate Settlement')).toBeInTheDocument()
    })
  })

  // =========================================================================
  // 4. WORKFLOW TESTS
  // =========================================================================

  it('22. Secretary requests cash advance through modal form', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/advances')) return Promise.resolve({ data: null })
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: mockAdvance })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Request Cash Advance')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Request Cash Advance'))
    expect(screen.getByPlaceholderText('e.g. 5000')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('e.g. 5000'), { target: { value: '15000' } })
    fireEvent.change(screen.getByPlaceholderText(/Explain why pre-event advance is required/i), {
      target: { value: 'Hardware procurement advance for workshop' },
    })

    fireEvent.click(screen.getByText('Submit Request'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/advances',
        expect.objectContaining({ amount_requested: '15000' })
      )
    })
  })

  it('23. Secretary submits draft settlement for audit', async () => {
    setupDefaultMocks({ status: 'DRAFT' })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...mockSettlement, status: 'UNDER_AUDIT' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Submit for Finance Audit')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Submit for Finance Audit'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/events/ev-100/settlement/submit')
    })
  })

  it('24. Finance Officer audits settlement with APPROVE action', async () => {
    setupDefaultMocks({ status: 'UNDER_AUDIT' })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...mockSettlement, status: 'APPROVED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Approve Settlement')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Approve Settlement'))
    expect(screen.getByText('Confirm Approval')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Confirm Approval'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/settlement/audit',
        expect.objectContaining({ action: 'APPROVE' })
      )
    })
  })

  it('25. Finance Officer audits settlement with QUERY action', async () => {
    setupDefaultMocks({ status: 'UNDER_AUDIT' })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...mockSettlement, status: 'QUERIED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Raise Audit Query')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Raise Audit Query'))
    expect(screen.getByPlaceholderText(/Specify the discrepancy or missing evidence/i)).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText(/Specify the discrepancy or missing evidence/i), {
      target: { value: 'Missing itemized receipt for audio vendor' },
    })

    fireEvent.click(screen.getByText('Send Audit Query'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/settlement/audit',
        expect.objectContaining({ action: 'QUERY', query_reason: 'Missing itemized receipt for audio vendor' })
      )
    })
  })

  // =========================================================================
  // 5. CLOSURE READINESS TESTS
  // =========================================================================

  it('26. Blocked closure displays blocker diagnosis list', async () => {
    setupDefaultMocks()
    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Closure Blocked')).toBeInTheDocument()
      expect(screen.getByText('Settlement Incomplete')).toBeInTheDocument()
      expect(screen.getByText('Outstanding Balance Due')).toBeInTheDocument()
    })
  })

  it('27. Eligible closure displays eligible badge and clearance notice', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/settlement/closure-eligibility')) {
        return Promise.resolve({ data: { eligible: true, blockers: [], event_id: 'ev-100', settlement_id: 'set-1' } })
      }
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/advances')) return Promise.resolve({ data: mockAdvance })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: mockIncomes })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      return Promise.resolve({ data: null })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Eligible for Closure')).toBeInTheDocument()
      expect(screen.getByText(/All Statutory Closeout Conditions Satisfied/i)).toBeInTheDocument()
    })
  })

  // =========================================================================
  // 6. ADDITIONAL WORKFLOW, ERROR, & DIRECTIONAL TESTS (28-42)
  // =========================================================================

  it('28. 422 Unprocessable Entity maps validation error cleanly in cash advance form', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/advances')) return Promise.resolve({ data: null })
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })
    ;vi.mocked(apiClient.post).mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: 'Amount requested cannot exceed sanctioned grant',
        },
      },
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Request Cash Advance')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Request Cash Advance'))
    fireEvent.change(screen.getByPlaceholderText('e.g. 5000'), { target: { value: '99999' } })
    fireEvent.change(screen.getByPlaceholderText(/Explain why pre-event advance is required/i), {
      target: { value: 'Advance exceeds grant' },
    })
    fireEvent.click(screen.getByText('Submit Request'))

    await waitFor(() => {
      expect(screen.getByText(/Amount requested cannot exceed sanctioned grant/i)).toBeInTheDocument()
    })
  })

  it('29. Finance Officer approves cash advance workflow', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/advances')) {
        return Promise.resolve({
          data: { ...mockAdvance, status: 'REQUESTED', amount_approved: null, amount_disbursed: '0.00' },
        })
      }
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...mockAdvance, status: 'APPROVED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Approve Advance')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Approve Advance'))
    expect(screen.getByText('Approve Cash Advance')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Confirm Approval'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/advances/adv-1/approve',
        expect.objectContaining({ amount_approved: '20000.00' })
      )
    })
  })

  it('30. Finance Officer rejects cash advance workflow with mandatory reason', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/advances')) {
        return Promise.resolve({
          data: { ...mockAdvance, status: 'REQUESTED', amount_approved: null, amount_disbursed: '0.00' },
        })
      }
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...mockAdvance, status: 'REJECTED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Reject Advance')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Reject Advance'))
    expect(screen.getByText('Reject Cash Advance')).toBeInTheDocument()

    const confirmBtn = screen.getByText('Confirm Rejection')

    fireEvent.change(screen.getByPlaceholderText(/Provide audit reason/i), {
      target: { value: 'Excessive advance request' },
    })

    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/advances/adv-1/reject',
        expect.objectContaining({ rejection_reason: 'Excessive advance request' })
      )
    })
  })

  it('31. Finance Officer disburses approved cash advance with payment reference', async () => {
    const approvedAdvance = { ...mockAdvance, status: 'APPROVED' }
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/advances')) return Promise.resolve({ data: approvedAdvance })
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/incomes')) return Promise.resolve({ data: mockIncomes })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...approvedAdvance, status: 'DISBURSED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Disburse Funds')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Disburse Funds'))
    expect(screen.getByText('Disburse Cash Advance')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('e.g. UTR-2026-BANK-001'), {
      target: { value: 'UTR-DISB-7788' },
    })

    fireEvent.click(screen.getByText('Confirm Disbursement'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/advances/adv-1/disburse',
        expect.objectContaining({
          amount_disbursed: '20000.00',
          payment_reference: 'UTR-DISB-7788',
        })
      )
    })
  })

  it('32. Secretary uploads income evidence and records actual income', async () => {
    setupDefaultMocks()
    ;vi.mocked(apiClient.post).mockImplementation((url: string) => {
      if (url.endsWith('/incomes/upload-evidence')) {
        return Promise.resolve({
          data: {
            document_id: 'doc-uploaded-1',
            filename: 'receipt.pdf',
            file_size: 1024,
            message: 'Uploaded',
          },
        })
      }
      if (url.endsWith('/incomes')) {
        return Promise.resolve({ data: mockIncomes[0] })
      }
      return Promise.resolve({ data: {} })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Record Income')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Record Income'))
    expect(screen.getByText('Record Actual Event Income')).toBeInTheDocument()

    const file = new File(['proof'], 'receipt.pdf', { type: 'application/pdf' })
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(fileInput).toBeInTheDocument()

    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/incomes/upload-evidence',
        expect.any(FormData),
        expect.any(Object)
      )
      expect(screen.getByText(/Income evidence uploaded successfully/i)).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('e.g. 1500.00'), { target: { value: '8000.00' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. Acme Tech Solutions Pvt Ltd'), {
      target: { value: 'Tech Sponsor Corp' },
    })
    fireEvent.change(screen.getByPlaceholderText('e.g. Title sponsorship fee for hackathon'), {
      target: { value: 'Annual tech fest sponsorship' },
    })
    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement
    if (dateInput) {
      fireEvent.change(dateInput, { target: { value: '2026-09-24' } })
    }

    fireEvent.click(screen.getByText('Save Income Entry'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/incomes',
        expect.objectContaining({
          amount: '8000.00',
          payer_name: 'Tech Sponsor Corp',
          evidence_document_id: 'doc-uploaded-1',
        })
      )
    })
  })

  it('33. Finance Officer verifies recorded income record', async () => {
    const unverifiedIncome = { ...mockIncomes[0], status: 'RECORDED' }
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [unverifiedIncome] })
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/advances')) return Promise.resolve({ data: mockAdvance })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...unverifiedIncome, status: 'VERIFIED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Verify')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Verify'))
    expect(screen.getByText('Verify Actual Income')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Confirm Verification'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/incomes/inc-1/verify',
        expect.any(Object)
      )
    })
  })

  it('34. Finance Officer rejects recorded income with mandatory audit reason', async () => {
    const unverifiedIncome = { ...mockIncomes[0], status: 'RECORDED' }
    setupDefaultMocks()
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/incomes')) return Promise.resolve({ data: [unverifiedIncome] })
      if (url.endsWith('/settlement')) return Promise.resolve({ data: mockSettlement })
      if (url.endsWith('/advances')) return Promise.resolve({ data: mockAdvance })
      if (url.endsWith('/settlement/payments')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/revisions')) return Promise.resolve({ data: [] })
      if (url.endsWith('/settlement/closure-eligibility')) return Promise.resolve({ data: mockClosure })
      return Promise.resolve({ data: null })
    })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...unverifiedIncome, status: 'REJECTED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Reject')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Reject'))
    expect(screen.getByText('Reject Actual Income')).toBeInTheDocument()

    const confirmBtn = screen.getByText('Confirm Rejection')

    fireEvent.change(screen.getByPlaceholderText(/State reason \(min 5 chars\)/i), {
      target: { value: 'Invalid tax invoice document' },
    })

    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/incomes/inc-1/reject',
        expect.objectContaining({ rejection_reason: 'Invalid tax invoice document' })
      )
    })
  })

  it('35. Secretary recalculates settlement figures via prepare endpoint', async () => {
    setupDefaultMocks({ status: 'DRAFT' })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: mockSettlement })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={true}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Recalculate Draft')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Recalculate Draft'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/events/ev-100/settlement/prepare')
    })
  })

  it('36. Principal reopens settled settlement with mandatory audit reason', async () => {
    setupDefaultMocks({ status: 'SETTLED', settlement_balance: '0.00' })
    ;vi.mocked(apiClient.post).mockResolvedValue({ data: { ...mockSettlement, status: 'REOPENED' } })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={true}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Reopen Account')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Reopen Account'))
    expect(screen.getByText('Reopen Settled Settlement')).toBeInTheDocument()

    const confirmBtn = screen.getByText('Confirm Reopen')

    fireEvent.change(
      screen.getByPlaceholderText(/State the audit justification/i),
      { target: { value: 'Late audit objection by university finance inspection' } }
    )

    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/settlement/reopen',
        expect.objectContaining({
          reopening_reason: 'Late audit objection by university finance inspection',
        })
      )
    })
  })

  it('37. Finance Officer uploads payment proof and records reimbursement payment', async () => {
    setupDefaultMocks({ status: 'PENDING_REIMBURSEMENT', settlement_type: 'REIMBURSEMENT_DUE' })
    ;vi.mocked(apiClient.post).mockImplementation((url: string) => {
      if (url.endsWith('/settlement/upload-proof')) {
        return Promise.resolve({
          data: {
            document_id: 'doc-proof-100',
            filename: 'voucher.pdf',
            file_size: 2048,
            message: 'Proof uploaded',
          },
        })
      }
      if (url.endsWith('/settlement/payments')) {
        return Promise.resolve({
          data: {
            id: 'pay-new',
            payment_type: 'REIMBURSEMENT_DISBURSEMENT',
            amount: '12000.00',
            payment_method: 'NEFT',
            transaction_reference: 'UTR-REIMB-5566',
            transaction_date: '2026-09-25',
            proof_document_id: 'doc-proof-100',
          },
        })
      }
      return Promise.resolve({ data: {} })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Record Reimbursement Payment')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Record Reimbursement Payment'))
    expect(screen.getByText('Record Settlement Transaction')).toBeInTheDocument()

    // Upload proof
    const file = new File(['proof data'], 'voucher.pdf', { type: 'application/pdf' })
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(fileInput).toBeInTheDocument()

    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/settlement/upload-proof',
        expect.any(FormData),
        expect.any(Object)
      )
      expect(screen.getByText(/Payment proof voucher uploaded/i)).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('e.g. UTR-2026-NEFT-991'), {
      target: { value: 'UTR-REIMB-5566' },
    })

    fireEvent.click(screen.getByText('Confirm Transaction'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/settlement/payments',
        expect.objectContaining({
          payment_type: 'REIMBURSEMENT_DISBURSEMENT',
          transaction_reference: 'UTR-REIMB-5566',
          proof_document_id: 'doc-proof-100',
        })
      )
    })
  })

  it('38. Payment history displays recorded payment transactions', async () => {
    const mockPay = [
      {
        id: 'pay-1',
        payment_type: 'REIMBURSEMENT_DISBURSEMENT',
        amount: '12000.00',
        payment_method: 'NEFT',
        transaction_reference: 'UTR-2026-NEFT-8899',
        transaction_date: '2026-09-24',
        proof_document_id: 'doc-proof-1',
        notes: 'Final reimbursement disbursement',
        created_at: '2026-09-24T12:00:00Z',
      },
    ]
    setupDefaultMocks({ payments: mockPay as unknown as SettlementPayment[] })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Settlement Liquidation & Payment Ledger')).toBeInTheDocument()
      expect(screen.getByText('UTR-2026-NEFT-8899')).toBeInTheDocument()
      expect(screen.getByText('Final reimbursement disbursement')).toBeInTheDocument()
    })
  })

  it('39. Revision history displays historical audit snapshots upon expanding', async () => {
    const mockRev = [
      {
        id: 'rev-1',
        revision_number: 1,
        reopened_by: 'user-fo',
        reopening_reason: 'Audit correction on catering invoice',
        snapshot: {
          sanctioned_grant: '50000.00',
          settlement_balance: '25000.00',
        },
        created_at: '2026-09-24T15:00:00Z',
      },
    ]
    setupDefaultMocks({ revisions: mockRev as unknown as SettlementRevision[] })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={false}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText(/Immutable Audit Revision History/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText(/Immutable Audit Revision History/i))

    await waitFor(() => {
      expect(screen.getByText(/Revision #1/i)).toBeInTheDocument()
      expect(screen.getByText(/Audit correction on catering invoice/i)).toBeInTheDocument()
    })
  })

  it('40. 404 Unprepared state displays waiting notice for non-Secretary roles', async () => {
    ;vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.endsWith('/settlement')) {
        return Promise.reject({ response: { status: 404, data: { message: 'Not prepared' } } })
      }
      return Promise.resolve({ data: null })
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Financial Settlement Not Prepared')).toBeInTheDocument()
      expect(screen.queryByText('Prepare Draft Settlement')).not.toBeInTheDocument()
    })
  })

  it('41. Directional reimbursement locks payment direction to REIMBURSEMENT_DISBURSEMENT', async () => {
    setupDefaultMocks({ status: 'PENDING_REIMBURSEMENT', settlement_type: 'REIMBURSEMENT_DUE' })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Record Reimbursement Payment')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Record Reimbursement Payment'))

    await waitFor(() => {
      expect(screen.getByText(/Direction: Institution → Club/i)).toBeInTheDocument()
    })
  })

  it('42. Directional refund locks payment direction to ADVANCE_REFUND_RECEIPT', async () => {
    setupDefaultMocks({
      status: 'PENDING_REFUND',
      settlement_type: 'REFUND_DUE',
      settlement_balance: '-5000.00',
      refund_due: '5000.00',
      reimbursement_due: '0.00',
    })

    render(
      <FinancialSettlementTab
        eventId="ev-100"
        eventStatus="APPROVED"
        isCertified={true}
        isSecretary={false}
        isFinanceOfficer={true}
        isPrincipal={false}
        isAdmin={false}
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Record Refund Receipt')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Record Refund Receipt'))

    await waitFor(() => {
      expect(screen.getByText(/Direction: Club → Institution/i)).toBeInTheDocument()
    })
  })
})
