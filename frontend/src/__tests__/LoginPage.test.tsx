import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { LoginPage } from '@/pages/LoginPage'

describe('LoginPage Component', () => {
  it('renders login form and title', () => {
    render(
      <BrowserRouter>
        <LoginPage />
      </BrowserRouter>
    )

    expect(screen.getByText('CampusConnect')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('user@college.edu')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('••••••••••••')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('populates fields when clicking quick login preset', () => {
    render(
      <BrowserRouter>
        <LoginPage />
      </BrowserRouter>
    )

    const secretaryBtn = screen.getByRole('button', { name: 'Secretary' })
    fireEvent.click(secretaryBtn)

    const emailInput = screen.getByPlaceholderText('user@college.edu') as HTMLInputElement
    const passInput = screen.getByPlaceholderText('••••••••••••') as HTMLInputElement

    expect(emailInput.value).toBe('secretary@college.edu')
    expect(passInput.value).toBe('Pass123!Secure')
  })
})
