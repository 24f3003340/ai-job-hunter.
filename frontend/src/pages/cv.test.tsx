import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { API, HttpResponse, http, server } from '../test/server'
import { renderApp } from '../test/utils'

const doc = { id: 'd1', document_type: 'cv', filename: 'cv.pdf', mime_type: 'application/pdf', size_bytes: 2048, checksum: 'x', scan_status: 'not_configured', parsing_status: 'parsed', created_at: '2026-01-01T00:00:00Z' }
const preview = {
  parse_id: 'p1', document_id: 'd1', status: 'draft', parser_version: '1.0', notice: 'Draft only.',
  parsed: {
    full_name: 'Riya Sharma', email: null, phone: '',
    education: [
      { degree: 'B.Tech in Computer Science', institution: 'Example Institute', start_date: '2022', end_date: '2027', status: 'in_progress', suggested_status: null, confidence: 'high' },
      { degree: 'B.Sc Physics', institution: 'Old University', start_date: '2015', end_date: '2018', status: null, suggested_status: 'completed', confidence: 'medium' },
    ],
    experience: [{ title: 'ML Intern', employer: 'Acme Labs', start_date: '2024-06', end_date: '2024-08', current: false, description: '', bullets: ['Built a RAG demo'], confidence: 'medium' }],
    projects: [], skills: [{ name: 'Python', level: null, verified: false }], certifications: [],
  },
  flags: [
    { id: 'education_status_inferred:education[1]', code: 'education_status_inferred', path: 'education[1]', severity: 'warning', message: 'End date is in the past but completion is not stated; confirm whether this degree is completed.' },
    { id: 'suspicious_instruction:line[9]', code: 'suspicious_instruction', path: 'line[9]', severity: 'warning', message: 'Text resembling an instruction to an AI system was ignored: “Ignore all previous instructions…”' },
    { id: 'name_from_first_line:full_name', code: 'name_from_first_line', path: 'full_name', severity: 'info', message: 'Name was taken from the first line; please check it.' },
  ],
}

function mockCv(confirmHandler?: Parameters<typeof http.post>[1]) {
  server.use(
    http.get(`${API}/documents/d1`, () => HttpResponse.json(doc)),
    http.get(`${API}/documents/d1/parse`, () => HttpResponse.json(preview)),
    ...(confirmHandler ? [http.post(`${API}/documents/d1/parse/confirm`, confirmHandler)] : []),
  )
}

describe('CV parsing draft', () => {
  it('labels the draft as unconfirmed and lists warnings separately from notes', async () => {
    mockCv()
    renderApp('/cv/d1')
    await screen.findByText(/Things to check/)
    expect(screen.getAllByRole('status').some((e) => /is not part of your profile until you confirm/i.test(e.textContent ?? ''))).toBe(true)
    expect(screen.getAllByRole('checkbox', { name: /Warning/ })).toHaveLength(2)
    expect(screen.getByText(/Name was taken from the first line/)).toBeInTheDocument()
  })

  it('never pre-selects "completed": the parser suggestion is only a hint', async () => {
    mockCv()
    renderApp('/cv/d1')
    const selects = await screen.findAllByLabelText('Status')
    expect(selects[0]).toHaveValue('in_progress')
    expect(selects[1]).toHaveValue('') // suggested "completed" is NOT applied
    expect(screen.getByText(/parser suggests “completed” but could not confirm it/i)).toBeInTheDocument()
  })

  it('blocks confirmation until every warning is acknowledged and the status is chosen', async () => {
    let confirmed = false
    mockCv(() => { confirmed = true; return HttpResponse.json({ profile_version: 2 }) })
    const { user } = renderApp('/cv/d1')
    await screen.findByText(/Things to check/)
    await user.click(screen.getByLabelText(/I have checked these details/))
    await user.click(screen.getByRole('button', { name: 'Confirm and save to profile' }))
    // education status is empty -> profile-level validation stops it, with a focusable error summary
    expect((await screen.findAllByText(/Choose completed or in progress. This is never guessed for you./)).length).toBeGreaterThanOrEqual(2) // summary + inline error
    expect(screen.getAllByLabelText('Status')[1]).toHaveAttribute('aria-invalid', 'true')
    await user.selectOptions(screen.getAllByLabelText('Status')[1], 'completed')
    await user.click(screen.getByRole('button', { name: 'Confirm and save to profile' }))
    expect(await screen.findByText(/Acknowledge all 2 warnings/)).toBeInTheDocument()
    expect(confirmed).toBe(false)
  })

  it('sends exactly the acknowledged flags and the user-chosen statuses', async () => {
    let body: { acknowledged_flags: string[]; profile: { education: { status: string }[] }; parse_id: string } | undefined
    mockCv(async ({ request }) => { body = (await request.json()) as typeof body; return HttpResponse.json({ profile_version: 2 }) })
    const { user } = renderApp('/cv/d1')
    await screen.findByText(/Things to check/)
    for (const cb of screen.getAllByRole('checkbox', { name: /Warning/ })) await user.click(cb)
    await user.selectOptions(screen.getAllByLabelText('Status')[1], 'completed')
    await user.click(screen.getByLabelText(/I have checked these details/))
    await user.click(screen.getByRole('button', { name: 'Confirm and save to profile' }))
    expect(await screen.findByText(/Saved to your profile \(version 2\)/)).toBeInTheDocument()
    expect(body!.parse_id).toBe('p1')
    expect(body!.acknowledged_flags).toEqual(['education_status_inferred:education[1]', 'suspicious_instruction:line[9]'])
    expect(body!.profile.education.map((e) => e.status)).toEqual(['in_progress', 'completed'])
    expect(JSON.stringify(body)).not.toContain('confidence')
    expect(JSON.stringify(body)).not.toContain('suggested')
  })

  it('shows backend refusals (e.g. stale draft) without losing the form', async () => {
    mockCv(() => HttpResponse.json({ detail: 'This draft is superseded; run parse again' }, { status: 409 }))
    const { user } = renderApp('/cv/d1')
    await screen.findByText(/Things to check/)
    for (const cb of screen.getAllByRole('checkbox', { name: /Warning/ })) await user.click(cb)
    await user.selectOptions(screen.getAllByLabelText('Status')[1], 'completed')
    await user.click(screen.getByLabelText(/I have checked these details/))
    await user.click(screen.getByRole('button', { name: 'Confirm and save to profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/superseded; run parse again/)
    expect(screen.getByLabelText('Full name')).toHaveValue('Riya Sharma')
  })

  it('explains unreadable (scanned) PDFs and points to manual entry', async () => {
    server.use(
      http.get(`${API}/documents/d1`, () => HttpResponse.json({ ...doc, parsing_status: 'pending' })),
      http.get(`${API}/documents/d1/parse`, () => HttpResponse.json({ detail: 'This document has not been parsed yet' }, { status: 404 })),
      http.post(`${API}/documents/d1/parse`, () => HttpResponse.json({ detail: { detail: 'Very little text could be extracted. The file may be a scanned image; OCR is not supported.', parsing_status: 'unreadable' } }, { status: 422 })),
    )
    const { user } = renderApp('/cv/d1')
    await user.click(await screen.findByRole('button', { name: 'Parse this document' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/OCR is not supported/)
    expect(within(screen.getByRole('main')).getAllByRole('link', { name: 'Profile' }).length).toBeGreaterThan(0)
  })
})

describe('CV upload', () => {
  it('rejects non PDF/DOCX files before uploading', async () => {
    server.use(http.get(`${API}/documents`, () => HttpResponse.json([])))
    const { user } = renderApp('/cv')
    const input = await screen.findByLabelText(/CV file/)
    await user.upload(input, new File(['x'], 'cv.exe', { type: 'application/octet-stream' }))
    // `accept` filtering in user-event drops it silently; try the form path too
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByText(/Choose (a file first|a PDF or DOCX file)\./)).toBeInTheDocument()
  })

  it('tells the user honestly when a file was not malware scanned', async () => {
    server.use(
      http.get(`${API}/documents`, () => HttpResponse.json([])),
      http.post(`${API}/documents/upload`, () => HttpResponse.json(doc, { status: 201 })),
    )
    const { user } = renderApp('/cv')
    await user.upload(await screen.findByLabelText(/CV file/), new File(['%PDF-1.4'], 'cv.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByText(/malware scanning is not configured on this server/i)).toBeInTheDocument()
  })

  it('shows server-side rejections (wrong content, too large, infected)', async () => {
    server.use(
      http.get(`${API}/documents`, () => HttpResponse.json([])),
      http.post(`${API}/documents/upload`, () => HttpResponse.json({ detail: 'File extension does not match the file’s actual content' }, { status: 415 })),
    )
    const { user } = renderApp('/cv')
    await user.upload(await screen.findByLabelText(/CV file/), new File(['hello'], 'cv.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/does not match/)
  })

  it('requires confirmation before deleting a document', async () => {
    let deleted = false
    server.use(
      http.get(`${API}/documents`, () => HttpResponse.json([doc])),
      http.delete(`${API}/documents/d1`, () => { deleted = true; return new HttpResponse(null, { status: 204 }) }),
    )
    const { user } = renderApp('/cv')
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    const dialog = screen.getByRole('dialog', { name: /delete this document/i })
    expect(deleted).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'Delete document' }))
    await screen.findByText(/No CV uploaded yet/).catch(() => undefined)
    expect(deleted).toBe(true)
  })
})
