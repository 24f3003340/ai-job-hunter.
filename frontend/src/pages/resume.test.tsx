import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { API, HttpResponse, http, server } from '../test/server'
import { clearDownloads, downloads, profileFx, renderApp, resumeFx } from '../test/utils'

const base = () => server.use(
  http.get(`${API}/resumes/r1`, () => HttpResponse.json(resumeFx)),
  http.get(`${API}/profile`, () => HttpResponse.json(profileFx)),
)

describe('resume studio', () => {
  it('shows flagged claims with reasons and missing evidence, and in-progress education as in progress', async () => {
    base()
    renderApp('/resumes/r1')
    expect(await screen.findByRole('heading', { name: 'Resume version 2' })).toBeInTheDocument()
    const card = screen.getByRole('listitem', { name: 'Statement c1' })
    expect(within(card).getByText(/Not fully supported by your profile/)).toBeInTheDocument()
    expect(within(card).getByText('No supporting profile evidence is cited for this statement.')).toBeInTheDocument()
    expect(within(card).getByText('none cited')).toBeInTheDocument()
    expect(screen.getByText('In progress')).toBeInTheDocument()
    expect(screen.queryByText('Completed')).not.toBeInTheDocument()
  })

  it('resolves cited evidence to profile text when the profile version matches', async () => {
    base()
    const { user } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    await user.click(screen.getByText(/Consistent with your profile/))
    expect(await screen.findByText('experience[0].bullets[0]')).toBeInTheDocument()
    expect(screen.getAllByText(/Built a RAG prototype over 500 documents using LangChain/).length).toBeGreaterThan(1) // claim + evidence
  })

  it('does not pretend to resolve evidence when the profile changed since the version was made', async () => {
    server.use(http.get(`${API}/resumes/r1`, () => HttpResponse.json(resumeFx)), http.get(`${API}/profile`, () => HttpResponse.json({ ...profileFx, profile_version: 9 })))
    const { user } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    await user.click(screen.getByText(/Consistent with your profile/))
    expect(await screen.findByText(/profile changed since this version/)).toBeInTheDocument()
  })

  it('rejecting a claim sends the decision and shows the rejected status', async () => {
    let body: unknown
    server.use(
      http.get(`${API}/profile`, () => HttpResponse.json(profileFx)),
      http.get(`${API}/resumes/r1`, () => HttpResponse.json(resumeFx)),
      http.post(`${API}/resumes/r1/claims/c1/review`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ ...resumeFx, review_status: 'rejected', rejected_claims: ['c1'], unresolved_claims: [],
          claims: resumeFx.claims.map((c) => (c.id === 'c1' ? { ...c, decision: 'reject' } : c)) })
      }),
    )
    const { user } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    await user.type(screen.getByLabelText('Note (optional)'), 'not true')
    await user.click(screen.getByRole('button', { name: 'Reject' }))
    expect(await screen.findByText('Contains a statement you rejected.')).toBeInTheDocument()
    expect(body).toEqual({ decision: 'reject', note: 'not true' })
    expect(screen.getByText('Rejected')).toBeInTheDocument()
  })

  it('accept explains that the user is vouching for the statement', async () => {
    base()
    renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    expect(screen.getByText(/the system cannot verify it/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept – this is true' })).toBeInTheDocument()
  })

  it('downloads a clearly-labelled DRAFT (allow_draft=true) while claims are unreviewed', async () => {
    let url = ''
    clearDownloads()
    server.use(
      http.get(`${API}/profile`, () => HttpResponse.json(profileFx)), http.get(`${API}/resumes/r1`, () => HttpResponse.json(resumeFx)),
      http.get(`${API}/resumes/r1/download`, ({ request }) => { url = request.url; return new HttpResponse('%PDF-', { headers: { 'content-disposition': 'attachment; filename="resume-v2.pdf"' } }) }),
    )
    const { user } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    await user.click(screen.getByRole('button', { name: 'Download draft PDF' }))
    await waitFor(() => expect(downloads()).toEqual(['resume-v2.pdf']))
    expect(url).toContain('format=pdf')
    expect(url).toContain('allow_draft=true')
  })

  it('a clean version downloads without allow_draft', async () => {
    let url = ''
    server.use(
      http.get(`${API}/profile`, () => HttpResponse.json(profileFx)),
      http.get(`${API}/resumes/r1`, () => HttpResponse.json({ ...resumeFx, review_status: 'clean', unresolved_claims: [], claims: [resumeFx.claims[1]] })),
      http.get(`${API}/resumes/r1/download`, ({ request }) => { url = request.url; return new HttpResponse('PK', {}) }),
    )
    const { user } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    await user.click(screen.getByRole('button', { name: 'Download DOCX' }))
    await waitFor(() => expect(url).toContain('format=docx'))
    expect(url).toContain('allow_draft=false')
  })

  it('shows download failures instead of failing silently', async () => {
    server.use(
      http.get(`${API}/profile`, () => HttpResponse.json(profileFx)), http.get(`${API}/resumes/r1`, () => HttpResponse.json(resumeFx)),
      http.get(`${API}/resumes/r1/download`, () => HttpResponse.json({ detail: 'Resume was changed on the server' }, { status: 409 })),
    )
    const { user } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    await user.click(screen.getByRole('button', { name: 'Download draft PDF' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Resume was changed on the server')
    expect(downloads()).toEqual([])
  })

  it('shows network failures on download', async () => {
    server.use(
      http.get(`${API}/profile`, () => HttpResponse.json(profileFx)), http.get(`${API}/resumes/r1`, () => HttpResponse.json(resumeFx)),
      http.get(`${API}/resumes/r1/download`, () => HttpResponse.error()),
    )
    const { user } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    await user.click(screen.getByRole('button', { name: 'Download draft DOCX' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the server/i)
  })

  it('renders resume text as text, never as HTML', async () => {
    const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    server.use(
      http.get(`${API}/profile`, () => HttpResponse.json(profileFx)),
      http.get(`${API}/resumes/r1`, () => HttpResponse.json({ ...resumeFx, content: { ...resumeFx.content, summary: { id: 'c1', text: evil } }, claims: [{ ...resumeFx.claims[0], text: evil }] })),
    )
    const { container } = renderApp('/resumes/r1')
    await screen.findByRole('heading', { name: 'Resume version 2' })
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getAllByText(evil).length).toBeGreaterThan(0)
  })
})
