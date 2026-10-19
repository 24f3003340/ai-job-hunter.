import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { session } from '../auth/session'
import { API, HttpResponse, ME, http, server } from '../test/server'
import { renderApp } from '../test/utils'

describe('settings', () => {
  it('account deletion requires typing the confirmation phrase', async () => {
    let deleted = false
    server.use(http.delete(`${API}/account`, () => { deleted = true; return new HttpResponse(null, { status: 204 }) }))
    const { user } = renderApp('/settings')
    await user.click(await screen.findByRole('button', { name: 'Delete my account…' }))
    const dialog = screen.getByRole('dialog', { name: /delete your account/i })
    const confirm = within(dialog).getByRole('button', { name: 'Permanently delete' })
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Confirmation'), 'delete my')
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Confirmation'), ' account')
    expect(confirm).toBeEnabled()
    await user.click(confirm)
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByText('Your account and all its data were deleted.')).toBeInTheDocument()
    expect(deleted).toBe(true)
    expect(session.token).toBeNull()
  })

  it('Escape cancels the delete dialog and returns focus', async () => {
    const { user } = renderApp('/settings')
    const open = await screen.findByRole('button', { name: 'Delete my account…' })
    await user.click(open)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(open).toHaveFocus()
  })

  it('shows deletion errors and keeps the session', async () => {
    server.use(http.delete(`${API}/account`, () => HttpResponse.json({ detail: 'nope' }, { status: 500 })))
    const { user } = renderApp('/settings')
    await user.click(await screen.findByRole('button', { name: 'Delete my account…' }))
    await user.type(screen.getByLabelText('Confirmation'), 'delete my account')
    await user.click(screen.getByRole('button', { name: 'Permanently delete' }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(session.token).toBe('test-token')
  })

  it('AI consent toggles via the API', async () => {
    const calls: string[] = []
    server.use(
      http.post(`${API}/account/ai-consent`, () => { calls.push('grant'); return new HttpResponse(null, { status: 204 }) }),
      http.delete(`${API}/account/ai-consent`, () => { calls.push('revoke'); return new HttpResponse(null, { status: 204 }) }),
    )
    const { user } = renderApp('/settings')
    const box = await screen.findByLabelText(/I consent to my profile content/)
    expect(box).not.toBeChecked()
    await user.click(box)
    await screen.findByLabelText(/I consent to my profile content/)
    expect(calls).toEqual(['grant'])
  })

  it('unverified users get a banner and can request a new verification email', async () => {
    server.use(http.get(`${API}/auth/me`, () => HttpResponse.json({ ...ME, email_verified: false })), http.post(`${API}/auth/resend-verification`, () => HttpResponse.json({ detail: 'Verification email sent.' }, { status: 202 })))
    const { user } = renderApp('/settings')
    expect(await screen.findByText(/Your email address is not verified yet/)).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Resend verification email' })[0])
    expect(await screen.findByText(/new verification email was requested/)).toBeInTheDocument()
  })
})
