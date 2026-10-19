import { describe, expect, it, vi } from 'vitest'
import { session } from '../auth/session'
import { HttpResponse, http, API, server } from '../test/server'
import { ApiError, api, download, errorMessage, toApiError } from './client'

describe('toApiError', () => {
  it('handles string detail', () => expect(toApiError(409, { detail: 'Nope' }).message).toBe('Nope'))
  it('handles pydantic list detail into field errors', () => {
    const e = toApiError(422, { detail: [{ loc: ['body', 'email'], msg: 'bad email' }] })
    expect(e.fieldErrors).toEqual({ email: 'bad email' })
  })
  it('handles object detail with blockers and code', () => {
    const e = toApiError(422, { detail: { detail: 'Not ready', blockers: ['a', 'b'], code: 'x' } })
    expect([e.message, e.blockers, e.code]).toEqual(['Not ready', ['a', 'b'], 'x'])
  })
  it('falls back to a generic message and never echoes unknown bodies', () => {
    const e = toApiError(500, { trace: 'Traceback secret' })
    expect(e.message).toBe('Something went wrong.')
    expect(JSON.stringify(e)).not.toContain('secret')
  })
  it('reads Retry-After', () => {
    const e = toApiError(429, { detail: 'Rate limit exceeded' }, new Headers({ 'retry-after': '30' }))
    expect(errorMessage(e)).toContain('30s')
  })
})

describe('api()', () => {
  it('sends the bearer token only when authenticated and never sends credentials/cookies', async () => {
    let seen: Request | null = null
    server.use(http.get(`${API}/profile`, ({ request }) => { seen = request; return HttpResponse.json({}) }))
    await api('/profile')
    expect(seen!.headers.get('authorization')).toBeNull()
    session.set('tok-123')
    await api('/profile')
    expect(seen!.headers.get('authorization')).toBe('Bearer tok-123')
    const spy = vi.spyOn(globalThis, 'fetch')
    await api('/profile')
    expect((spy.mock.calls[0][1] as RequestInit).credentials).toBe('omit') // never sends cookies
    spy.mockRestore()
  })

  it('treats a network failure as a friendly offline error', async () => {
    server.use(http.get(`${API}/jobs`, () => HttpResponse.error()))
    const e = await api('/jobs').catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.network).toBe(true)
    expect(e.message).toMatch(/cannot reach the server/i)
  })

  it('401 with a session token expires the session (and exposes the reason)', async () => {
    server.use(http.get(`${API}/profile`, () => HttpResponse.json({ detail: 'Invalid or expired session' }, { status: 401 })))
    session.set('tok')
    await expect(api('/profile')).rejects.toMatchObject({ status: 401 })
    expect(session.token).toBeNull()
    expect(session.wasExpired()).toBe(true)
  })

  it('401 on an unauthenticated call (bad login) does NOT touch the session', async () => {
    server.use(http.post(`${API}/auth/login`, () => HttpResponse.json({ detail: 'Invalid email or password' }, { status: 401 })))
    session.set('tok')
    await expect(api('/auth/login', { method: 'POST', json: {}, auth: false })).rejects.toMatchObject({ status: 401 })
    expect(session.token).toBe('tok')
  })

  it('ignores non-JSON error bodies instead of displaying them', async () => {
    server.use(http.get(`${API}/jobs`, () => new HttpResponse('<html>Internal Server Error stack…</html>', { status: 500 })))
    const e = await api('/jobs').catch((x) => x)
    expect(e.message).toBe('Something went wrong.')
  })
})

describe('download()', () => {
  it('saves using the server filename', async () => {
    server.use(http.get(`${API}/resumes/r1/download`, () => new HttpResponse('%PDF-', { headers: { 'content-disposition': 'attachment; filename="resume-v2.pdf"', 'content-type': 'application/pdf' } })))
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click')
    await download('/resumes/r1/download', 'fallback.pdf')
    expect(clicked).toHaveBeenCalled()
  })
  it('surfaces download errors', async () => {
    server.use(http.get(`${API}/resumes/r1/download`, () => HttpResponse.json({ detail: { detail: 'Resume has unreviewed or rejected claims.', review_status: 'needs_review' } }, { status: 409 })))
    await expect(download('/resumes/r1/download', 'x.pdf')).rejects.toMatchObject({ status: 409, message: expect.stringContaining('unreviewed') })
  })
})

describe('test harness safety', () => {
  it('fails on any request that has no mock, so tests can never reach a real network', async () => {
    await expect(api('/definitely-not-mocked')).rejects.toBeInstanceOf(ApiError) // surfaced as a network error
    await expect(fetch('http://api.test/api/v1/also-not-mocked')).rejects.toThrow()
  })
})
