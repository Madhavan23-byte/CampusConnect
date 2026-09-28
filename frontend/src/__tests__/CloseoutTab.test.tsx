import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import { CloseoutTab } from '@/components/closeout/CloseoutTab'
import { apiClient } from '@/lib/apiClient'
import type { EventClosureDetailResponse } from '@/types'

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  registerAuthStoreHooks: vi.fn(),
}))

describe('CloseoutTab Component (Phase 2.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const createMockDetail = (
    overrides?: Partial<EventClosureDetailResponse>
  ): EventClosureDetailResponse => ({
    event_id: 'ev-100',
    event_status: 'COMPLETED',
    is_archived: false,
    eligibility: {
      eligible: true,
      blockers: [],
      warnings: [],
      event_status: 'COMPLETED',
      settlement_status: 'SETTLED',
      report_status: 'CERTIFIED',
      venue_status: {
        has_booking: true,
        booking_ended: true,
        hall_id: 'hall-1',
      },
      event_id: 'ev-100',
      settlement_id: 'set-1',
      report_id: 'rep-1',
    },
    closure: null,
    revisions: [],
    latest_request: null,
    ...overrides,
  })

  // 1. Closeout tab renders
  it('1. Closeout tab renders with main container and header', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: createMockDetail() })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('closeout-tab-container')).toBeInTheDocument()
    })
    expect(screen.getByText('Event Closeout & Governance')).toBeInTheDocument()
  })

  // 2. Loading state
  it('2. displays loading state while fetching closeout details', () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}))

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    expect(screen.getByTestId('closeout-loading-state')).toBeInTheDocument()
  })

  // 3. Ready state
  it('3. displays ready state with green badge and zero blockers', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        eligibility: {
          eligible: true,
          blockers: [],
          warnings: [],
          event_status: 'COMPLETED',
          settlement_status: 'SETTLED',
          report_status: 'CERTIFIED',
          venue_status: { has_booking: true, booking_ended: true },
          event_id: 'ev-100',
        },
      }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('closeout-primary-status-badge')).toHaveTextContent('READY FOR CLOSEOUT')
    })
    expect(screen.getByTestId('closeout-eligibility-badge')).toHaveTextContent('Ready for Closeout')
    expect(screen.getByText('Zero Outstanding Blockers')).toBeInTheDocument()
  })

  // 4. Blocked state
  it('4. displays blocked state with active blockers and human-readable explanations', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        eligibility: {
          eligible: false,
          blockers: ['REPORT_NOT_CERTIFIED', 'SETTLEMENT_NOT_SETTLED', 'PENDING_EXPENSES'],
          warnings: ['Review receipts carefully'],
          event_status: 'COMPLETED',
          settlement_status: 'DRAFT',
          report_status: 'SUBMITTED',
          venue_status: { has_booking: true, booking_ended: true },
          event_id: 'ev-100',
        },
      }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('closeout-eligibility-badge')).toHaveTextContent('Closeout Blocked')
    })
    expect(screen.getByText(/Active Closeout Blockers \(3\)/)).toBeInTheDocument()
    expect(screen.getByText('Post-Event Report Not Certified')).toBeInTheDocument()
    expect(screen.getByText('Settlement Not Fully Settled')).toBeInTheDocument()
    expect(screen.getByText('Unverified Expenses Remaining')).toBeInTheDocument()
    expect(screen.getByText(/Review receipts carefully/)).toBeInTheDocument()
  })

  // 5. Request closeout visible to Secretary
  it('5. shows Request Closeout button for Club Secretary when eligible', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: createMockDetail() })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('request-closeout-button')).toBeInTheDocument()
    })
  })

  // 6. Certification visible only to authorized authority (Dean / Principal)
  it('6. shows Certify Closeout only to authorized institutional authorities', async () => {
    const requestedState = createMockDetail({
      event_status: 'CLOSURE_REQUESTED',
    })

    // Secretary should NOT see certify button
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: requestedState })
    const { unmount } = render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.queryByTestId('certify-closeout-button')).not.toBeInTheDocument()
    })
    unmount()

    // Dean SHOULD see certify button
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: requestedState })
    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="DEAN_STUDENT_AFFAIRS"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('certify-closeout-button')).toBeInTheDocument()
    })
  })

  // 7. Advisor delegation behavior
  it('7. allows Faculty Advisor to view, certify and reject when closure requested', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'CLOSURE_REQUESTED',
      }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="FACULTY_ADVISOR"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('certify-closeout-button')).toBeInTheDocument()
      expect(screen.getByTestId('reject-closeout-button')).toBeInTheDocument()
    })
  })

  // 8. Reject action
  it('8. allows Dean to reject closeout with mandatory reason', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'CLOSURE_REQUESTED',
      }),
    })
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { event_id: 'ev-100', status: 'COMPLETED', message: 'Closeout rejected.' },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="DEAN_STUDENT_AFFAIRS"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('reject-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('reject-closeout-button'))

    const reasonInput = screen.getByLabelText(/Rejection Justification/i)
    fireEvent.change(reasonInput, { target: { value: 'Discrepancy in attendance numbers.' } })

    const confirmBtn = screen.getByRole('button', { name: /Confirm Rejection/i })
    expect(confirmBtn).not.toBeDisabled()

    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/closure/reject',
        { reason: 'Discrepancy in attendance numbers.' }
      )
    })
  })

  // 9. Reopen request
  it('9. allows Secretary to petition for reopening with mandatory reason', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'CLOSED',
      }),
    })
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { event_id: 'ev-100', status: 'CLOSED', message: 'Reopening requested.' },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('request-reopen-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('request-reopen-button'))

    const reasonInput = screen.getByLabelText(/Reopening Justification/i)
    fireEvent.change(reasonInput, { target: { value: 'Late vendor tax invoice submitted.' } })

    const submitBtn = screen.getByRole('button', { name: /Submit Reopen Petition/i })
    expect(submitBtn).not.toBeDisabled()

    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/closure/reopen-request',
        { reason: 'Late vendor tax invoice submitted.' }
      )
    })
  })

  // 10. Reopen approval
  it('10. allows Dean to approve reopening with statutory justification', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'CLOSED',
        latest_request: {
          requested_by: 'sec-1',
          requested_at: '2026-09-28T10:00:00Z',
          remarks: 'Vendor invoice revision',
        },
      }),
    })
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { event_id: 'ev-100', status: 'COMPLETED', message: 'Reopening approved.' },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="DEAN_STUDENT_AFFAIRS"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('approve-reopen-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('approve-reopen-button'))

    const reasonInput = screen.getByLabelText(/Executive Approval Justification/i)
    fireEvent.change(reasonInput, { target: { value: 'Executive approval granted for tax refund.' } })

    const confirmBtn = screen.getByRole('button', { name: /Confirm & Approve Reopen/i })
    expect(confirmBtn).not.toBeDisabled()

    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/events/ev-100/closure/reopen-approve',
        { reason: 'Executive approval granted for tax refund.' }
      )
    })
  })

  // 11. Archive action for System Admin
  it('11. allows System Admin to archive closed event', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'CLOSED',
      }),
    })
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { event_id: 'ev-100', status: 'ARCHIVED', message: 'Event archived.' },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="SYSTEM_ADMIN"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('archive-event-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('archive-event-button'))

    const confirmBtn = screen.getByRole('button', { name: /Confirm & Archive Event/i })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/events/ev-100/archive', {})
    })
  })

  // 12. Unauthorized role action hidden
  it('12. hides unauthorized actions from roles (System Admin, Finance Officer, Secretary)', async () => {
    const closedState = createMockDetail({ event_status: 'CLOSED' })

    // System Admin cannot see certify, reject, or reopen-approve
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: closedState })
    const { unmount } = render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="SYSTEM_ADMIN"
      />
    )

    await waitFor(() => {
      expect(screen.queryByTestId('certify-closeout-button')).not.toBeInTheDocument()
      expect(screen.queryByTestId('reject-closeout-button')).not.toBeInTheDocument()
      expect(screen.queryByTestId('approve-reopen-button')).not.toBeInTheDocument()
    })
    unmount()

    // Finance Officer cannot approve reopen or archive
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: closedState })
    const { unmount: unmountFO } = render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="FINANCE_OFFICER"
      />
    )

    await waitFor(() => {
      expect(screen.queryByTestId('approve-reopen-button')).not.toBeInTheDocument()
      expect(screen.queryByTestId('archive-event-button')).not.toBeInTheDocument()
    })
    unmountFO()

    // Secretary cannot certify or archive
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: closedState })
    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.queryByTestId('certify-closeout-button')).not.toBeInTheDocument()
      expect(screen.queryByTestId('archive-event-button')).not.toBeInTheDocument()
    })
  })

  // 13. 403 handling
  it('13. displays 403 Forbidden state when user lacks access', async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce({
      response: { status: 403, data: { message: 'Access denied' } },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('closeout-forbidden-state')).toBeInTheDocument()
    })
    expect(screen.getByText(/Closeout Access Restricted \(403\)/)).toBeInTheDocument()
  })

  // 14. 404 handling
  it('14. displays 404 Not Found state when closeout record is missing', async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce({
      response: { status: 404, data: { message: 'Event not found' } },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('closeout-not-found-state')).toBeInTheDocument()
    })
    expect(screen.getByText('Closeout Record Not Found')).toBeInTheDocument()
  })

  // 15. 409 stale-state handling
  it('15. handles 409 Conflict by displaying warning banner and refreshing server state', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: createMockDetail({ event_status: 'CLOSURE_REQUESTED' }) })
      .mockResolvedValueOnce({ data: createMockDetail({ event_status: 'CLOSED' }) })

    vi.mocked(apiClient.post).mockRejectedValueOnce({
      response: { status: 409, data: { message: 'Event already certified by Principal.' } },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="DEAN_STUDENT_AFFAIRS"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('certify-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('certify-closeout-button'))

    // Check attestation
    const checkbox = screen.getByLabelText(/I confirm that the event venue has been cleared/i)
    fireEvent.click(checkbox)

    fireEvent.click(screen.getByRole('button', { name: /Confirm & Certify Closeout/i }))

    await waitFor(() => {
      expect(screen.getByTestId('closeout-conflict-warning')).toBeInTheDocument()
    })
    expect(apiClient.get).toHaveBeenCalledTimes(2)
  })

  // 16. 422 validation handling
  it('16. displays validation error message when server returns 422', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({ event_status: 'CLOSURE_REQUESTED' }),
    })

    vi.mocked(apiClient.post).mockRejectedValueOnce({
      response: { status: 422, data: { message: 'Venue clearance attestation must be true.' } },
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="DEAN_STUDENT_AFFAIRS"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('certify-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('certify-closeout-button'))
    fireEvent.click(screen.getByLabelText(/I confirm that the event venue has been cleared/i))
    fireEvent.click(screen.getByRole('button', { name: /Confirm & Certify Closeout/i }))

    await waitFor(() => {
      expect(screen.getByTestId('closeout-error-message')).toBeInTheDocument()
    })
    expect(screen.getByText('Venue clearance attestation must be true.')).toBeInTheDocument()
  })

  // 17. Certification attestation required
  it('17. enforces that the venue cleared attestation checkbox must be checked before certifying', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({ event_status: 'CLOSURE_REQUESTED' }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="DEAN_STUDENT_AFFAIRS"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('certify-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('certify-closeout-button'))

    const confirmBtn = screen.getByRole('button', { name: /Confirm & Certify Closeout/i })
    expect(confirmBtn).toBeDisabled()

    const checkbox = screen.getByLabelText(/I confirm that the event venue has been cleared/i)
    fireEvent.click(checkbox)

    expect(confirmBtn).not.toBeDisabled()
  })

  // 18. Rejection reason required
  it('18. requires rejection reason to be at least 5 characters', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({ event_status: 'CLOSURE_REQUESTED' }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSURE_REQUESTED"
        userRole="DEAN_STUDENT_AFFAIRS"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('reject-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('reject-closeout-button'))

    const confirmBtn = screen.getByRole('button', { name: /Confirm Rejection/i })
    expect(confirmBtn).toBeDisabled()

    const textarea = screen.getByLabelText(/Rejection Justification/i)
    fireEvent.change(textarea, { target: { value: 'No' } })
    expect(confirmBtn).toBeDisabled()

    fireEvent.change(textarea, { target: { value: 'Valid justification provided' } })
    expect(confirmBtn).not.toBeDisabled()
  })

  // 19. Reopen reason required
  it('19. requires reopen request reason to be at least 5 characters', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({ event_status: 'CLOSED' }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('request-reopen-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('request-reopen-button'))

    const submitBtn = screen.getByRole('button', { name: /Submit Reopen Petition/i })
    expect(submitBtn).toBeDisabled()

    const textarea = screen.getByLabelText(/Reopening Justification/i)
    fireEvent.change(textarea, { target: { value: 'test' } })
    expect(submitBtn).toBeDisabled()

    fireEvent.change(textarea, { target: { value: 'Proper justification for reopening' } })
    expect(submitBtn).not.toBeDisabled()
  })

  // 20. CLOSED read-only mode
  it('20. displays locked read-only banner when event is CLOSED', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'CLOSED',
        closure: {
          id: 'cls-1',
          event_id: 'ev-100',
          settlement_id: 'set-1',
          post_event_report_id: 'rep-1',
          certified_by: 'dean-1',
          certified_at: '2026-09-28T12:00:00Z',
          closure_notes: 'Fully settled.',
          venue_cleared: true,
          certificate_manifest_hash: 'sha256:abc1234567890',
          created_at: '2026-09-28T12:00:00Z',
          updated_at: '2026-09-28T12:00:00Z',
        },
      }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('closeout-closed-banner')).toBeInTheDocument()
    })
    expect(screen.getByText(/Event Closed & Locked/i)).toBeInTheDocument()
    expect(screen.getByText(/Event data is locked after institutional closeout/i)).toBeInTheDocument()
  })

  // 21. ARCHIVED read-only mode
  it('21. displays archived banner and suppresses operational action buttons when ARCHIVED', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'ARCHIVED',
        is_archived: true,
      }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="ARCHIVED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('closeout-archived-banner')).toBeInTheDocument()
    })
    expect(screen.getByText(/Event Archived/i)).toBeInTheDocument()
    expect(screen.queryByTestId('closeout-action-buttons')).not.toBeInTheDocument()
    expect(screen.getByText('Immutable Historical Archive')).toBeInTheDocument()
  })

  // 22. History / revision rendering
  it('22. renders closure certificate and revisions history timeline', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({
        event_status: 'CLOSED',
        closure: {
          id: 'cls-1',
          event_id: 'ev-100',
          settlement_id: 'set-1',
          post_event_report_id: 'rep-1',
          certified_by: 'dean-user-id',
          certified_at: '2026-09-28T11:00:00Z',
          closure_notes: 'All items verified.',
          venue_cleared: true,
          certificate_manifest_hash: 'sha256:fedcba9876543210',
          created_at: '2026-09-28T11:00:00Z',
          updated_at: '2026-09-28T11:00:00Z',
        },
        revisions: [
          {
            id: 'rev-1',
            event_id: 'ev-100',
            closure_id: 'cls-1',
            revision_number: 1,
            reopened_by: 'principal-user-id',
            reopened_at: '2026-09-28T14:00:00Z',
            reopening_reason: 'Audit of supplementary invoice needed.',
            snapshot_data: {},
            created_at: '2026-09-28T14:00:00Z',
          },
        ],
      }),
    })

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="CLOSED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByText('Closeout Audit & Revision History')).toBeInTheDocument()
    })
    expect(screen.getByText('Statutory Closeout Certified')).toBeInTheDocument()
    expect(screen.getByText(/Revision #1 Archived & Reopened/)).toBeInTheDocument()
    expect(screen.getByText(/"Audit of supplementary invoice needed\."/)).toBeInTheDocument()
  })

  // 23. Mutation loading state
  it('23. renders loading spinner during in-flight mutation', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({ event_status: 'COMPLETED' }),
    })
    vi.mocked(apiClient.post).mockReturnValue(new Promise(() => {}))

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('request-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('request-closeout-button'))
    fireEvent.click(screen.getByRole('button', { name: /Submit Closeout Petition/i }))

    expect(screen.getByText('Submitting Petition...')).toBeInTheDocument()
  })

  // 24. Mutation success refresh
  it('24. displays success message and refreshes details upon mutation success', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: createMockDetail({ event_status: 'COMPLETED' }) })
      .mockResolvedValueOnce({ data: createMockDetail({ event_status: 'CLOSURE_REQUESTED' }) })

    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { event_id: 'ev-100', status: 'CLOSURE_REQUESTED', message: 'Closeout requested successfully.' },
    })

    const onUpdateMock = vi.fn()

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
        onEventUpdated={onUpdateMock}
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('request-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('request-closeout-button'))
    fireEvent.click(screen.getByRole('button', { name: /Submit Closeout Petition/i }))

    await waitFor(() => {
      expect(screen.getByTestId('closeout-success-message')).toBeInTheDocument()
    })
    expect(screen.getByText('Closeout requested successfully.')).toBeInTheDocument()
    expect(apiClient.get).toHaveBeenCalledTimes(2)
    expect(onUpdateMock).toHaveBeenCalledTimes(1)
  })

  // 25. No duplicate mutation on double click
  it('25. disables action buttons during submission to prevent duplicate mutations', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: createMockDetail({ event_status: 'COMPLETED' }),
    })

    let resolvePost: (value: unknown) => void = () => {}
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve
      })
    )

    render(
      <CloseoutTab
        eventId="ev-100"
        eventStatus="COMPLETED"
        userRole="CLUB_SECRETARY"
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('request-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('request-closeout-button'))
    const submitBtn = screen.getByRole('button', { name: /Submit Closeout Petition/i })

    fireEvent.click(submitBtn)
    fireEvent.click(submitBtn) // Rapid double click

    expect(apiClient.post).toHaveBeenCalledTimes(1)

    // Cleanup
    await act(async () => {
      resolvePost({ data: { event_id: 'ev-100', status: 'CLOSURE_REQUESTED', message: 'Success' } })
    })
    await waitFor(() => {
      expect(screen.getByTestId('closeout-success-message')).toBeInTheDocument()
    })
  })
})
