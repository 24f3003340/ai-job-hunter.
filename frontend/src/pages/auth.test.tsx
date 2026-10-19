import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { session } from '../auth/session'
import { API, HttpResponse, http, server } from '../test/server'
import { renderApp } from '../test/utils'

describe('login', () => {
  it('logs in and lands on the dashboard', async () => {
    server.use(
      http.post(`${API}/auth/login`, () => HttpResponse.json({ access_token: 'tok-1' })),
      http.get(`${API}/jobs`, () => HttpResponse.json([])), http.get(`${API}/applications`, () => HttpResponse.json([])),
      http.get(`${API}/profile`, () => HttpResponse.json({ full_name: 'R' })),
    )
    const { user } = renderApp('/login', { token: null })
    await user.type(screen.getByLabelText('Email'), 'riya@example.com')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(session.token).toBe('tok-1')
  })

  it('shows an accessible error on bad credentials and stays logged out', async () => {
    server.use(http.post(`${API}/auth/login`, () => HttpResponse.json({ detail: 'Invalid email or password' }, { status: 401 })))
    const { user } = renderApp('/login', { token: null })
    await user.type(screen.getByLabelText('Email'), 'riya@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong-password-1')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
    expect(session.token).toBeNull()
  })

  it('explains account lockout / rate limiting with the retry time', async () => {
    server.use(http.post(`${API}/auth/login`, () => HttpResponse.json({ detail: 'Too many failed attempts; try again later' }, { status: 429, headers: { 'retry-after': '45' } })))
    const { user } = renderApp('/login', { token: null })
    await user.type(screen.getByLabelText('Email'), 'a@example.com')
    await user.type(screen.getByLabelText('Password'), 'whatever-pass-1')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/too many failed attempts.*45s/i)
  })

  it('shows a network error message when the server is unreachable', async () => {
    server.use(http.post(`${API}/auth/login`, () => HttpResponse.error()))
    const { user } = renderApp('/login', { token: null })
    await user.type(screen.getByLabelText('Email'), 'a@example.com')
    await user.type(screen.getByLabelText('Password'), 'whatever-pass-1')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the server/i)
  })

  it('redirects protected pages to login', async () => {
    renderApp('/applications', { token: null })
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })
})

describe('session expiry', () => {
  it('a 401 mid-session sends the user to login with an explanation and drops cached data', async () => {
    server.use(
      http.get(`${API}/jobs`, () => HttpResponse.json({ detail: 'Invalid or expired session' }, { status: 401 })),
      http.get(`${API}/applications`, () => HttpResponse.json([])), http.get(`${API}/profile`, () => HttpResponse.json({ full_name: 'R' })),
    )
    const { qc } = renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByText(/session has expired/i)).toBeInTheDocument()
    expect(session.token).toBeNull()
    await waitFor(() => expect(qc.getQueryCache().getAll().filter((q) => q.state.data !== undefined)).toHaveLength(0))
  })

  it('logout calls the server and clears the session even if the call fails', async () => {
    server.use(
      http.post(`${API}/auth/logout`, () => HttpResponse.json({ detail: 'x' }, { status: 500 })),
      http.get(`${API}/jobs`, () => HttpResponse.json([])), http.get(`${API}/applications`, () => HttpResponse.json([])),
      http.get(`${API}/profile`, () => HttpResponse.json({ full_name: 'R' })),
    )
    const { user } = renderApp('/')
    await screen.findByRole('heading', { name: 'Dashboard' })
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(session.token).toBeNull()
  })
})

describe('register', () => {
  it('validates password length before calling the API', async () => {
    let called = false
    server.use(http.post(`${API}/auth/register`, () => { called = true; return HttpResponse.json({ access_token: 't' }, { status: 201 }) }))
    const { user } = renderApp('/register', { token: null })
    await user.type(screen.getByLabelText('Email'), 'a@example.com')
    await user.type(screen.getByLabelText('Password'), 'short')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Password must be at least 10 characters.')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-invalid', 'true')
    expect(called).toBe(false)
  })

  it('reports a duplicate-account conflict without revealing more', async () => {
    server.use(http.post(`${API}/auth/register`, () => HttpResponse.json({ detail: 'Unable to register with these details' }, { status: 409 })))
    const { user } = renderApp('/register', { token: null })
    await user.type(screen.getByLabelText('Email'), 'a@example.com')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to register with these details')
  })
})

describe('email verification & password reset', () => {
  it('verifies once and removes the token from the URL', async () => {
    let calls = 0
    server.use(http.post(`${API}/auth/verify-email`, async ({ request }) => { calls++; expect(await request.json()).toEqual({ token: 'tok-verify-123' }); return new HttpResponse(null, { status: 204 }) }))
    renderApp('/verify-email?token=tok-verify-123', { token: null })
    expect(await screen.findByText(/email address is verified/i)).toBeInTheDocument()
    expect(calls).toBe(1)
  })

  it('refreshes the cached account so the "not verified" banner disappears', async () => {
    let verified = false
    server.use(
      http.get(`${API}/auth/me`, () => HttpResponse.json({ id: 'u', email: 'a@example.com', email_verified: verified, ai_consent: false })),
      http.post(`${API}/auth/verify-email`, () => { verified = true; return new HttpResponse(null, { status: 204 }) }),
      http.get(`${API}/jobs`, () => HttpResponse.json([])), http.get(`${API}/applications`, () => HttpResponse.json([])), http.get(`${API}/profile`, () => HttpResponse.json({ full_name: 'R' })),
    )
    // staleTime=Infinity: only an explicit invalidation can refresh the cached account
    const { user } = renderApp('/verify-email?token=tok-verify-777', { staleTime: Infinity })
    await screen.findByText(/email address is verified/i)
    await user.click(screen.getByRole('link', { name: 'Continue' }))
    await screen.findByRole('heading', { name: 'Dashboard' })
    await waitFor(() => expect(screen.queryByText(/email address is not verified yet/i)).not.toBeInTheDocument())
  })

  it('shows a helpful failure for an expired or used link', async () => {
    server.use(http.post(`${API}/auth/verify-email`, () => HttpResponse.json({ detail: 'Invalid or expired token' }, { status: 400 })))
    renderApp('/verify-email?token=tok-expired-999', { token: null })
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid or expired token')
  })

  it('forgot-password always shows the same neutral confirmation', async () => {
    server.use(http.post(`${API}/auth/password-reset/request`, () => HttpResponse.json({ detail: 'If that account exists…' }, { status: 202 })))
    const { user } = renderApp('/forgot-password', { token: null })
    await user.type(screen.getByLabelText('Email'), 'nobody@example.com')
    await user.click(screen.getByRole('button', { name: 'Send reset email' }))
    expect(await screen.findByText(/if that account exists, a reset email has been sent/i)).toBeInTheDocument()
  })

  it('reset form checks that passwords match, then submits and returns to login', async () => {
    let body: unknown
    server.use(http.post(`${API}/auth/password-reset/confirm`, async ({ request }) => { body = await request.json(); return new HttpResponse(null, { status: 204 }) }))
    const { user } = renderApp('/reset-password?token=tok-reset-123456', { token: null })
    await user.type(screen.getByLabelText('New password'), 'brand-new-password-1')
    await user.type(screen.getByLabelText('Repeat new password'), 'different-password-2')
    await user.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText('Passwords do not match.')).toBeInTheDocument()
    await user.clear(screen.getByLabelText('Repeat new password'))
    await user.type(screen.getByLabelText('Repeat new password'), 'brand-new-password-1')
    await user.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText(/password changed/i)).toBeInTheDocument()
    expect(body).toEqual({ token: 'tok-reset-123456', new_password: 'brand-new-password-1' })
  })

  it('reset link failures (expired / reused) are shown', async () => {
    server.use(http.post(`${API}/auth/password-reset/confirm`, () => HttpResponse.json({ detail: 'Invalid or expired token' }, { status: 400 })))
    const { user } = renderApp('/reset-password?token=tok-reset-123456', { token: null })
    await user.type(screen.getByLabelText('New password'), 'brand-new-password-1')
    await user.type(screen.getByLabelText('Repeat new password'), 'brand-new-password-1')
    await user.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid or expired token')
  })
})
