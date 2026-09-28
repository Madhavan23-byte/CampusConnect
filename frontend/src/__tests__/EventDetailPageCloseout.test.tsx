import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { EventDetailPage } from '@/pages/EventDetailPage'
import { apiClient } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  registerAuthStoreHooks: vi.fn(),
}))

describe('EventDetailPage Closeout Integration (Phase 2.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      user: {
        id: 'sec-1',
        email: 'secretary@college.edu',
        full_name: 'Club Secretary',
        role: 'CLUB_SECRETARY',
        is_active: true,
        email_verified: true,
        created_at: '2026-09-20T00:00:00Z',
      },
      accessToken: 'mock-token',
      isAuthenticated: true,
    })
  })

  const baseEvent = {
    id: 'ev-test-1',
    title: 'Robotics Workshop 2026',
    description: 'Autonomous robotics workshop.',
    event_type: 'TECHNICAL',
    status: 'APPROVED',
    academic_year: '2025-2026',
    submitted_by: 'sec-1',
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
    club: {
      id: 'club-1',
      name: 'Robotics Club',
      slug: 'robotics',
      academic_year: '2025-2026',
      is_active: true,
      created_at: '2026-09-20T00:00:00Z',
    },
  }

  const baseClosureDetail = {
    event_id: 'ev-test-1',
    event_status: 'COMPLETED',
    is_archived: false,
    eligibility: {
      eligible: true,
      blockers: [],
      warnings: [],
      event_status: 'COMPLETED',
      settlement_status: 'SETTLED',
      report_status: 'CERTIFIED',
      venue_status: { has_booking: true, booking_ended: true },
      event_id: 'ev-test-1',
    },
    closure: null,
    revisions: [],
    latest_request: null,
  }

  it('renders Closeout tab button in EventDetailPage and switches to CloseoutTab on click', async () => {
    const mockConfirmed = {
      id: 'conf-1',
      event_request_id: 'ev-test-1',
      title: 'Robotics Workshop 2026',
      event_type: 'TECHNICAL',
      event_date: '2026-09-25T09:00:00Z',
      start_time: '2026-09-25T09:00:00Z',
      end_time: '2026-09-25T17:00:00Z',
      status: 'COMPLETED',
      club_id: 'club-1',
      created_at: '2026-09-20T00:00:00Z',
    }

    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/events/ev-test-1') return Promise.resolve({ data: baseEvent })
      if (url === '/events/ev-test-1/confirmed') return Promise.resolve({ data: mockConfirmed })
      if (url === '/events/ev-test-1/closure') return Promise.resolve({ data: baseClosureDetail })
      if (url === '/halls') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/documents') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/resources') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/evidence') return Promise.resolve({ data: [] })
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    render(
      <MemoryRouter initialEntries={['/events/ev-test-1']}>
        <Routes>
          <Route path="/events/:id" element={<EventDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByTestId('tab-closeout-button')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('tab-closeout-button'))

    await waitFor(() => {
      expect(screen.getByTestId('closeout-tab-container')).toBeInTheDocument()
    })
    expect(screen.getByText('Event Closeout & Governance')).toBeInTheDocument()
  })

  it('renders locked read-only banner when confirmed event is CLOSED', async () => {
    const mockConfirmed = {
      id: 'conf-1',
      event_request_id: 'ev-test-1',
      title: 'Robotics Workshop 2026',
      event_type: 'TECHNICAL',
      event_date: '2026-09-25T09:00:00Z',
      start_time: '2026-09-25T09:00:00Z',
      end_time: '2026-09-25T17:00:00Z',
      status: 'CLOSED',
      club_id: 'club-1',
      created_at: '2026-09-20T00:00:00Z',
    }

    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/events/ev-test-1') return Promise.resolve({ data: baseEvent })
      if (url === '/events/ev-test-1/confirmed') return Promise.resolve({ data: mockConfirmed })
      if (url === '/events/ev-test-1/closure') {
        return Promise.resolve({
          data: {
            ...baseClosureDetail,
            event_status: 'CLOSED',
          },
        })
      }
      if (url === '/halls') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/documents') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/resources') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/evidence') return Promise.resolve({ data: [] })
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    render(
      <MemoryRouter initialEntries={['/events/ev-test-1']}>
        <Routes>
          <Route path="/events/:id" element={<EventDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByTestId('event-detail-closed-banner')).toBeInTheDocument()
    })
    expect(screen.getByText(/Event Closed & Locked/i)).toBeInTheDocument()
  })

  it('renders permanent archived banner when confirmed event is ARCHIVED', async () => {
    const mockConfirmed = {
      id: 'conf-1',
      event_request_id: 'ev-test-1',
      title: 'Robotics Workshop 2026',
      event_type: 'TECHNICAL',
      event_date: '2026-09-25T09:00:00Z',
      start_time: '2026-09-25T09:00:00Z',
      end_time: '2026-09-25T17:00:00Z',
      status: 'ARCHIVED',
      club_id: 'club-1',
      created_at: '2026-09-20T00:00:00Z',
    }

    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/events/ev-test-1') return Promise.resolve({ data: baseEvent })
      if (url === '/events/ev-test-1/confirmed') return Promise.resolve({ data: mockConfirmed })
      if (url === '/events/ev-test-1/closure') {
        return Promise.resolve({
          data: {
            ...baseClosureDetail,
            event_status: 'ARCHIVED',
            is_archived: true,
          },
        })
      }
      if (url === '/halls') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/documents') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/resources') return Promise.resolve({ data: [] })
      if (url === '/events/ev-test-1/evidence') return Promise.resolve({ data: [] })
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    render(
      <MemoryRouter initialEntries={['/events/ev-test-1']}>
        <Routes>
          <Route path="/events/:id" element={<EventDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByTestId('event-detail-archived-banner')).toBeInTheDocument()
    })
    expect(screen.getByText(/Event Archived/i)).toBeInTheDocument()
  })
})
