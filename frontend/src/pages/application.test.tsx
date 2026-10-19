import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { API, HttpResponse, http, server } from '../test/server'
import { appFx, jobFx, renderApp, resumeFx } from '../test/utils'

const cleanResume = { ...resumeFx, review_status: 'clean', unresolved_claims: [], claims: [resumeFx.claims[1]] }

function mock(app: object, extra: Parameters<typeof server.use> = []) {
  server.use(
    http.get(`${API}/applications/a1`, () => HttpResponse.json(app)),
    http.get(`${API}/jobs/j1`, () => HttpResponse.json(jobFx)),
    http.get(`${API}/resumes/r1`, () => HttpResponse.json(cleanResume)),
    http.get(`${API}/jobs/j1/resumes`, () => HttpResponse.json([{ ...cleanResume, id: 'r1' }, { ...cleanResume, id: 'r0', version_number: 1 }])),
    ...extra,
  )
}

describe('application review', () => {
  it('approve is disabled until the explicit approval box is ticked', async () => {
    let approved = false
    mock(appFx, [http.post(`${API}/applications/a1/approve`, () => { approved = true; return HttpResponse.json({ ...appFx, status: 'approved', package_hash: 'abc' }) })])
    const { user } = renderApp('/applications/a1')
    const btn = await screen.findByRole('button', { name: 'Approve this package' })
    expect(btn).toBeDisabled()
    await user.click(screen.getByLabelText(/I have reviewed the job, resume, cover letter and answers/))
    expect(btn).toBeEnabled()
    await user.click(btn)
    await waitFor(() => expect(approved).toBe(true))
  })

  it('shows backend blockers (e.g. unreviewed claims) and surfaces refusal on approve', async () => {
    mock({ ...appFx, blockers: ['Resume has factual claims awaiting your review (status: needs_review)'] },
      [http.post(`${API}/applications/a1/approve`, () => HttpResponse.json({ detail: { detail: 'Application is not ready for approval', blockers: ['Resume has factual claims awaiting your review (status: needs_review)'] } }, { status: 422 }))])
    const { user } = renderApp('/applications/a1')
    await screen.findByText('Before you can approve:')
    expect(screen.getAllByText(/factual claims awaiting your review/).length).toBeGreaterThan(0)
    await user.click(screen.getByLabelText(/I have reviewed/))
    await user.click(screen.getByRole('button', { name: 'Approve this package' }))
    expect(await screen.findByText('Application is not ready for approval')).toBeInTheDocument()
  })

  it('editing answers of an APPROVED application warns first, then tells the user the approval was withdrawn', async () => {
    let state = { ...appFx, status: 'approved' }
    mock(state, [])
    server.use(
      http.get(`${API}/applications/a1`, () => HttpResponse.json(state)),
      http.put(`${API}/applications/a1/answers`, async () => { state = { ...state, status: 'ready_for_review' }; return HttpResponse.json(state) }),
    )
    const { user } = renderApp('/applications/a1')
    await screen.findByText(/It has not been sent anywhere/)
    await user.type(await screen.findByLabelText('Your answer'), ' a lot')
    await user.click(screen.getByRole('button', { name: 'Save answers' }))
    const dialog = await screen.findByRole('dialog', { name: /withdraw your approval/i })
    await user.click(within(dialog).getByRole('button', { name: 'Make the change' }))
    expect(await screen.findByText(/Your approval was withdrawn because the application changed/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Approve this package' })).toBeDisabled() // must re-tick and re-approve
    expect(screen.getByLabelText(/I have reviewed/)).not.toBeChecked()
  })

  it('switching resume version on an approved application also withdraws approval', async () => {
    let state = { ...appFx, status: 'approved' }
    server.use(
      http.get(`${API}/applications/a1`, () => HttpResponse.json(state)), http.get(`${API}/jobs/j1`, () => HttpResponse.json(jobFx)),
      http.get(`${API}/resumes/r1`, () => HttpResponse.json(cleanResume)),
      http.get(`${API}/jobs/j1/resumes`, () => HttpResponse.json([{ ...cleanResume, id: 'r1' }, { ...cleanResume, id: 'r0', version_number: 1 }])),
      http.put(`${API}/applications/a1/resume`, () => { state = { ...state, status: 'ready_for_review', resume_version_id: 'r0' }; return HttpResponse.json(state) }),
    )
    const { user } = renderApp('/applications/a1')
    await user.selectOptions(await screen.findByLabelText('Use version'), 'r0')
    await user.click(await screen.findByRole('button', { name: 'Make the change' }))
    expect(await screen.findByText(/approval was withdrawn/i)).toBeInTheDocument()
  })

  it('a submit refused because the package changed tells the user to re-approve', async () => {
    mock({ ...appFx, status: 'approved' }, [http.post(`${API}/applications/a1/submit`, () => HttpResponse.json({ detail: 'Application changed since approval; review and approve again' }, { status: 409 }))])
    const { user } = renderApp('/applications/a1')
    await user.click(await screen.findByRole('button', { name: /Check package/ }))
    expect(await screen.findByText(/package changed since you approved it/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Application changed since approval/).length).toBeGreaterThan(0)
  })

  it('"submit" never claims success: it returns the manual path and the status stays "not yet applied"', async () => {
    mock({ ...appFx, status: 'approved' }, [http.post(`${API}/applications/a1/submit`, () => HttpResponse.json({ ...appFx, status: 'approved', submission: 'manual_required', detail: 'No authorized connector for this source. Apply at the official link, then record it.' }))])
    const { user } = renderApp('/applications/a1')
    await user.click(await screen.findByRole('button', { name: /Check package/ }))
    expect(await screen.findByText(/No authorized connector/)).toBeInTheDocument()
    expect(screen.getByText('Approved by you – not yet applied')).toBeInTheDocument()
    expect(screen.queryByText(/^Submitted$/)).not.toBeInTheDocument()
    const link = screen.getByRole('link', { name: /Open official application page/ })
    expect(link).toHaveAttribute('href', 'https://acme.example/apply')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('recording "I applied" needs confirmation and is sent as user-reported', async () => {
    let body: unknown
    mock({ ...appFx, status: 'approved' }, [http.patch(`${API}/applications/a1/status`, async ({ request }) => { body = await request.json(); return HttpResponse.json({ ...appFx, status: 'submitted', submission_method: 'manual_user_reported' }) })])
    const { user } = renderApp('/applications/a1')
    await user.click(await screen.findByRole('button', { name: 'Record that I applied' }))
    const dialog = screen.getByRole('dialog', { name: /record that you applied/i })
    expect(body).toBeUndefined()
    expect(within(dialog).getByText(/cannot verify it/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Yes, I applied' }))
    await waitFor(() => expect(body).toMatchObject({ status: 'submitted', user_reported_submission: true }))
  })

  it('blocks stale content: no cover letter text is invented', async () => {
    mock({ ...appFx, cover_letter_id: 'cl1' })
    renderApp('/applications/a1')
    expect(await screen.findByText(/API does not expose its text/)).toBeInTheDocument()
  })

  it('shows a clear error for a missing application', async () => {
    server.use(http.get(`${API}/applications/zzz`, () => HttpResponse.json({ detail: 'Application not found' }, { status: 404 })))
    renderApp('/applications/zzz')
    expect(await screen.findByRole('alert')).toHaveTextContent('Application not found')
  })
})

describe('tracker honesty', () => {
  it('labels statuses truthfully and only shows "Applied" for user-reported submissions', async () => {
    server.use(
      http.get(`${API}/applications`, () => HttpResponse.json([
        { ...appFx, id: 'a1', status: 'approved' },
        { ...appFx, id: 'a2', status: 'submitted', submission_method: 'manual_user_reported', submitted_at: '2026-03-01T00:00:00Z' },
        { ...appFx, id: 'a3', status: 'ready_for_review', manual_application_url: 'javascript:alert(1)' },
      ])),
      http.get(`${API}/jobs`, () => HttpResponse.json([jobFx])),
    )
    renderApp('/applications')
    const rows = await screen.findAllByRole('row')
    expect(within(rows[1]).getByText('Approved by you – not yet applied')).toBeInTheDocument()
    expect(within(rows[2]).getByText('Applied (reported by you)')).toBeInTheDocument()
    expect(within(rows[2]).getByText('reported by you')).toBeInTheDocument()
    expect(within(rows[1]).getByRole('link', { name: 'Open' })).toHaveAttribute('href', 'https://acme.example/apply')
    expect(within(rows[3]).queryByRole('link', { name: 'Open' })).toBeNull() // javascript: URL is never linked
    expect(screen.queryByText(/^Submitted$/)).not.toBeInTheDocument() // also not in the status filter menu
  })

  it('filters by status', async () => {
    server.use(
      http.get(`${API}/applications`, () => HttpResponse.json([{ ...appFx, id: 'a1', status: 'approved' }, { ...appFx, id: 'a2', status: 'interview' }])),
      http.get(`${API}/jobs`, () => HttpResponse.json([jobFx])),
    )
    const { user } = renderApp('/applications')
    await screen.findAllByRole('row')
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'interview')
    expect(screen.getAllByRole('row')).toHaveLength(2)
  })

  it('has an empty state', async () => {
    server.use(http.get(`${API}/applications`, () => HttpResponse.json([])), http.get(`${API}/jobs`, () => HttpResponse.json([])))
    renderApp('/applications')
    expect(await screen.findByText(/No applications yet/)).toBeInTheDocument()
  })
})
