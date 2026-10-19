import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { safeHttpUrl } from '../lib/safeUrl'
import { API, HttpResponse, http, server } from '../test/server'
import { appFx, jobFx, matchFx, renderApp } from '../test/utils'

describe('safeHttpUrl', () => {
  it.each([['https://a.example/x', 'https://a.example/x'], ['http://a.example', 'http://a.example/'], ['javascript:alert(1)', null], ['data:text/html,<script>', null], ['vbscript:x', null], ['//evil.example', null], ['', null], [null, null]])('%s', (i, o) => {
    expect(safeHttpUrl(i as string | null)).toBe(o)
  })
})

describe('job details', () => {
  const mock = (job: object = jobFx) => server.use(
    http.get(`${API}/jobs/j1`, () => HttpResponse.json(job)), http.get(`${API}/jobs/j1/match`, () => HttpResponse.json(matchFx)),
    http.get(`${API}/jobs/j1/resumes`, () => HttpResponse.json([])), http.get(`${API}/applications`, () => HttpResponse.json([])),
  )

  it('puts disqualifiers first and marks unknown data as unknown, not as a match', async () => {
    mock()
    renderApp('/jobs/j1')
    const alert = await screen.findByText(/Disqualifying requirements/)
    expect(alert.closest('[role=alert]')).toHaveTextContent(/apply no matter how high the score is/)
    expect(screen.getByText(/Job requires a completed degree/)).toBeInTheDocument()
    expect(screen.getAllByText('Unknown – not assumed to match')).toHaveLength(2) // experience + salary
    expect(screen.getByText('62.5')).toBeInTheDocument()
    expect(screen.getAllByText(/based on 65% of the scoring weight/).length).toBeGreaterThan(0)
    const lists = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(lists).toEqual(expect.arrayContaining(['Matched skills', 'Missing skills', 'Concerns']))
    expect(screen.getByText('Kubernetes', { selector: 'li' })).toBeInTheDocument()
    expect(screen.getByText('Python', { selector: 'li' })).toBeInTheDocument()
  })

  it('renders hostile description text inertly', async () => {
    mock({ ...jobFx, description: '<img src=x onerror=alert(1)><a href="javascript:alert(2)">click</a>', application_url: 'javascript:alert(3)' })
    const { container } = renderApp('/jobs/j1')
    await screen.findByText(/<img src=x onerror=alert\(1\)>/)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(screen.getByText('No valid application link on file.')).toBeInTheDocument()
  })

  it('unverified listings ask the user to verify instead of pretending they are live', async () => {
    mock({ ...jobFx, status: 'needs_verification', last_verified_at: null })
    renderApp('/jobs/j1')
    expect(await screen.findByText(/has not been verified/)).toBeInTheDocument()
    expect(screen.getAllByText('Not yet verified').length).toBeGreaterThan(0)
  })

  it('generating a resume surfaces consent / profile errors from the backend', async () => {
    mock()
    server.use(http.post(`${API}/jobs/j1/resume`, () => HttpResponse.json({ detail: { detail: 'Consent to AI processing is required', code: 'ai_consent_required' } }, { status: 403 })))
    const { user } = renderApp('/jobs/j1')
    await user.click(await screen.findByRole('button', { name: 'Generate tailored resume' }))
    expect(await screen.findByText('Consent to AI processing is required')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /AI consent in Settings/ })).toBeInTheDocument()
  })

  it('creating a draft application navigates to the review page and sends no answers silently', async () => {
    mock()
    server.use(
      http.get(`${API}/jobs/j1/resumes`, () => HttpResponse.json([{ id: 'r1', version_number: 1, review_status: 'clean', created_at: '2026-01-01T00:00:00Z' }])),
      http.post(`${API}/applications`, async ({ request }) => { expect(await request.json()).toEqual({ job_id: 'j1', resume_version_id: 'r1' }); return HttpResponse.json(appFx, { status: 201 }) }),
      http.get(`${API}/applications/a1`, () => HttpResponse.json(appFx)), http.get(`${API}/resumes/r1`, () => HttpResponse.json({ id: 'r1', version_number: 1, review_status: 'clean', claims: [], content: {}, warnings: [], change_summary: [], unresolved_claims: [], rejected_claims: [] })),
    )
    const { user } = renderApp('/jobs/j1')
    await user.click(await screen.findByRole('button', { name: /Create draft with resume version 1/ }))
    expect(await screen.findByRole('heading', { name: 'Review application' })).toBeInTheDocument()
  })
})

describe('job list', () => {
  it('shows score with disqualifier and unknown badges, and an empty state', async () => {
    server.use(http.get(`${API}/jobs`, () => HttpResponse.json([jobFx])), http.get(`${API}/jobs/j1/match`, () => HttpResponse.json(matchFx)))
    renderApp('/jobs')
    const row = (await screen.findAllByRole('row'))[1]
    expect(await within(row).findByText('Disqualifier')).toBeInTheDocument()
    expect(within(row).getByText('2 unknown')).toBeInTheDocument()
    expect(within(row).getByText('Verified active')).toBeInTheDocument()
  })

  it('search sends the query to the backend', async () => {
    const seen: string[] = []
    server.use(http.get(`${API}/jobs`, ({ request }) => { seen.push(new URL(request.url).searchParams.get('q') ?? ''); return HttpResponse.json([]) }))
    const { user } = renderApp('/jobs')
    await screen.findByText(/No jobs found/)
    await user.type(screen.getByLabelText('Search title or company'), 'nlp{enter}')
    await screen.findByText(/No jobs found/)
    expect(seen).toContain('nlp')
  })

  it('shows a server error state', async () => {
    server.use(http.get(`${API}/jobs`, () => HttpResponse.json({}, { status: 503 })))
    renderApp('/jobs')
    expect(await screen.findByRole('alert')).toHaveTextContent(/temporarily unavailable/i)
  })
})
