import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

describe('EventDetailPage Execution & Post-Event Report UI', () => {
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

  it('renders execution tab and quick-status banner when event status is APPROVED', async () => {
    const mockEvent = {
      id: 'event-123',
      title: 'Autonomous Drone Challenge',
      description: 'Annual campus drone racing event.',
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

    const mockConfirmed = {
      id: 'conf-123',
      event_request_id: 'event-123',
      title: 'Autonomous Drone Challenge',
      event_type: 'TECHNICAL',
      event_date: '2026-09-25T09:00:00Z',
      start_time: '2026-09-25T09:00:00Z',
      end_time: '2026-09-25T17:00:00Z',
      status: 'SCHEDULED',
      club_id: 'club-1',
      created_at: '2026-09-20T00:00:00Z',
    }

    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/events/event-123') {
        return Promise.resolve({ data: mockEvent })
      }
      if (url === '/events/event-123/confirmed') {
        return Promise.resolve({ data: mockConfirmed })
      }
      if (url === '/halls') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/events/event-123/documents') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/events/event-123/resources') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/events/event-123/evidence') {
        return Promise.resolve({ data: [] })
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    render(
      <MemoryRouter initialEntries={['/events/event-123']}>
        <Routes>
          <Route path="/events/:id" element={<EventDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Autonomous Drone Challenge')).toBeInTheDocument()
      expect(screen.getByText('Event Proposal Confirmed & Scheduled')).toBeInTheDocument()
      expect(screen.getByText(/Execution & Report/i)).toBeInTheDocument()
    })
  })

  it('renders certified status when post-event report has been certified', async () => {
    const mockEvent = {
      id: 'event-456',
      title: 'Hackathon 2026',
      description: 'Campus hackathon.',
      event_type: 'TECHNICAL',
      status: 'APPROVED',
      academic_year: '2025-2026',
      submitted_by: 'sec-1',
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
      club: {
        id: 'club-1',
        name: 'Coding Club',
        slug: 'coding',
        academic_year: '2025-2026',
        is_active: true,
        created_at: '2026-09-20T00:00:00Z',
      },
    }

    const mockConfirmed = {
      id: 'conf-456',
      event_request_id: 'event-456',
      title: 'Hackathon 2026',
      event_type: 'TECHNICAL',
      event_date: '2026-09-21T09:00:00Z',
      start_time: '2026-09-21T09:00:00Z',
      end_time: '2026-09-21T17:00:00Z',
      status: 'COMPLETED',
      club_id: 'club-1',
      created_at: '2026-09-20T00:00:00Z',
      post_event_report: {
        id: 'rep-1',
        event_id: 'conf-456',
        revision_number: 1,
        actual_attendance: 250,
        summary: 'Hackathon successfully conducted with 50 teams.',
        objectives_achieved: 'Prototype software deployed.',
        status: 'CERTIFIED',
        submitted_by: 'sec-1',
        submitted_at: '2026-09-21T18:00:00Z',
        certified_by: 'fa-1',
        certified_at: '2026-09-21T19:00:00Z',
        certification_remarks: 'Verified physical attendance and awards.',
        created_at: '2026-09-21T18:00:00Z',
        updated_at: '2026-09-21T19:00:00Z',
      },
    }

    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/events/event-456') {
        return Promise.resolve({ data: mockEvent })
      }
      if (url === '/events/event-456/confirmed') {
        return Promise.resolve({ data: mockConfirmed })
      }
      if (url === '/halls') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/events/event-456/documents') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/events/event-456/resources') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/events/event-456/evidence') {
        return Promise.resolve({ data: [] })
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`))
    })

    render(
      <MemoryRouter initialEntries={['/events/event-456']}>
        <Routes>
          <Route path="/events/:id" element={<EventDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Hackathon 2026')).toBeInTheDocument()
      expect(screen.getByText('Event execution concluded. Post-event report submitted.')).toBeInTheDocument()
    })
  })
})
