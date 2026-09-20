import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { WorkflowPendingPage } from '@/pages/WorkflowPendingPage'
import { apiClient } from '@/lib/apiClient'

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

describe('WorkflowPendingPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders empty state when no items pending', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: [] })

    render(
      <BrowserRouter>
        <WorkflowPendingPage />
      </BrowserRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Your queue is clear!')).toBeInTheDocument()
    })
  })

  it('renders pending review items in table', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: [
        {
          step_id: 'step-123',
          instance_id: 'inst-1',
          event_request_id: 'ev-1',
          event_title: 'Annual Coding Championship',
          club_name: 'Coding Club',
          step_order: 1,
          step_name: 'Faculty Advisor Review',
          version_number: 1,
          submitted_at: '2026-09-20T00:00:00Z',
          assigned_to: 'FACULTY_ADVISOR',
        },
      ],
    })

    render(
      <BrowserRouter>
        <WorkflowPendingPage />
      </BrowserRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Annual Coding Championship')).toBeInTheDocument()
      expect(screen.getByText('Coding Club')).toBeInTheDocument()
      expect(screen.getByText(/Step 1: Faculty Advisor Review/)).toBeInTheDocument()
      expect(screen.getByText(/Review Step/)).toBeInTheDocument()
    })
  })
})
