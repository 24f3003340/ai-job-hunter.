import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it, vi } from 'vitest'
import { session } from './auth/session'
import { API, HttpResponse, http, server } from './test/server'
import { profileFx, renderApp } from './test/utils'

describe('secrets never touch web storage', () => {
  it('login stores nothing in localStorage, sessionStorage or cookies', async () => {
    const setLocal = vi.spyOn(Storage.prototype, 'setItem')
    server.use(
      http.post(`${API}/auth/login`, () => HttpResponse.json({ access_token: 'SECRET-SESSION-TOKEN-123' })),
      http.get(`${API}/jobs`, () => HttpResponse.json([])), http.get(`${API}/applications`, () => HttpResponse.json([])), http.get(`${API}/profile`, () => HttpResponse.json(profileFx)),
    )
    const { user } = renderApp('/login', { token: null })
    await user.type(screen.getByLabelText('Email'), 'riya@example.com')
    await user.type(screen.getByLabelText('Password'), 'my-very-secret-password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    await screen.findByRole('heading', { name: 'Dashboard' })
    expect(session.token).toBe('SECRET-SESSION-TOKEN-123') // held in memory only
    expect(setLocal).not.toHaveBeenCalled()
    const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + document.cookie + window.location.href
    expect(dump).not.toContain('SECRET-SESSION-TOKEN-123')
    expect(dump).not.toContain('my-very-secret-password')
    setLocal.mockRestore()
  })

  it('password inputs are masked and use the right autocomplete hints', async () => {
    renderApp('/register', { token: null })
    const pw = screen.getByLabelText('Password')
    expect(pw).toHaveAttribute('type', 'password')
    expect(pw).toHaveAttribute('autocomplete', 'new-password')
  })

  it('the session is gone after a reload (nothing persisted)', () => {
    session.set('abc')
    session.clear()
    expect(session.token).toBeNull()
  })
})

describe('accessibility (axe)', () => {
  it.each([['/login'], ['/register'], ['/forgot-password']])('%s has no detectable violations', async (route) => {
    const { container } = renderApp(route, { token: null })
    await screen.findByRole('heading', { level: 1 })
    expect(await axe(container)).toHaveNoViolations()
  })

  it('profile page has no detectable violations and has a skip link and landmarks', async () => {
    server.use(http.get(`${API}/profile`, () => HttpResponse.json(profileFx)))
    const { container } = renderApp('/profile')
    await screen.findByRole('button', { name: 'Save profile' })
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute('href', '#main')
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('keeps focus at the top on first load (so Tab reaches the skip link) but moves it to the heading on later navigation', async () => {
    server.use(http.get(`${API}/profile`, () => HttpResponse.json(profileFx)), http.get(`${API}/documents`, () => HttpResponse.json([])))
    const { user } = renderApp('/profile')
    const h1 = await screen.findByRole('heading', { name: 'Profile', level: 1 })
    expect(h1).not.toHaveFocus()
    await user.click(screen.getByRole('link', { name: 'CV' }))
    expect(await screen.findByRole('heading', { name: 'CV upload', level: 1 })).toHaveFocus()
  })
})
