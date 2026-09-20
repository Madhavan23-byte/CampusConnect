import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { NotificationBell } from '@/components/NotificationBell'
import { apiClient } from '@/lib/apiClient'

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    patch: vi.fn(),
  },
}))

describe('NotificationBell Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders bell button and fetches unread count', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { unread_count: 3 } })

    render(<NotificationBell />)

    const button = screen.getByLabelText('Notifications')
    expect(button).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('3')).toBeInTheDocument()
    })
  })

  it('opens dropdown and displays notifications on click', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: { unread_count: 1 } })
      .mockResolvedValueOnce({
        data: [
          {
            id: 'n1',
            title: 'Action Required',
            message: 'Your approval is needed for Robotics Fest',
            notification_type: 'APPROVAL_REQUIRED',
            is_read: false,
            created_at: new Date().toISOString(),
          },
        ],
      })

    render(<NotificationBell />)

    const button = screen.getByLabelText('Notifications')
    fireEvent.click(button)

    await waitFor(() => {
      expect(screen.getByText('Action Required')).toBeInTheDocument()
      expect(screen.getByText(/Your approval is needed/)).toBeInTheDocument()
    })
  })
})
