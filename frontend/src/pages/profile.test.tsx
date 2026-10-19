import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { API, HttpResponse, http, server } from '../test/server'
import { profileFx, renderApp } from '../test/utils'

describe('profile editor', () => {
  it('preserves in-progress vs completed exactly as stored when saving', async () => {
    let body: { education: { status: string; verified: boolean }[] } | undefined
    server.use(
      http.get(`${API}/profile`, () => HttpResponse.json({ ...profileFx, education: [...profileFx.education, { degree: 'Class XII', institution: 'School', status: 'completed', start_date: '2019', end_date: '2021', verified: true }] })),
      http.put(`${API}/profile`, async ({ request }) => { body = (await request.json()) as typeof body; return HttpResponse.json({ ...profileFx, profile_version: 4 }) }),
    )
    const { user } = renderApp('/profile')
    const selects = await screen.findAllByLabelText('Status')
    expect(selects.map((s) => (s as HTMLSelectElement).value)).toEqual(['in_progress', 'completed'])
    await user.click(screen.getByRole('button', { name: 'Save profile' }))
    await screen.findByText(/Profile saved \(version 4\)/)
    expect(body!.education.map((e) => e.status)).toEqual(['in_progress', 'completed'])
    expect(body!.education.every((e) => e.verified)).toBe(true) // flags are carried through, not dropped
  })

  it('refuses to save an education entry without an explicit status', async () => {
    let put = false
    server.use(http.get(`${API}/profile`, () => HttpResponse.json(profileFx)), http.put(`${API}/profile`, () => { put = true; return HttpResponse.json(profileFx) }))
    const { user } = renderApp('/profile')
    await screen.findByRole('button', { name: 'Save profile' })
    await user.click(screen.getByRole('button', { name: 'Add education' }))
    await user.type(screen.getByLabelText('Degree', { selector: '#' + (screen.getAllByLabelText('Degree')[1] as HTMLElement).id }), 'MBA')
    await user.click(screen.getByRole('button', { name: 'Save profile' }))
    const summary = await screen.findByRole('alert')
    expect(summary).toHaveTextContent(/Choose completed or in progress/)
    expect(summary).toHaveFocus() // keyboard users land on the error summary
    expect(put).toBe(false)
  })

  it('validates date format and shows field-level errors', async () => {
    server.use(http.get(`${API}/profile`, () => HttpResponse.json(profileFx)))
    const { user } = renderApp('/profile')
    await screen.findByRole('button', { name: 'Save profile' })
    const end = screen.getAllByLabelText('End or expected end')[0]
    await user.clear(end); await user.type(end, 'next year')
    await user.click(screen.getByRole('button', { name: 'Save profile' }))
    expect((await screen.findAllByText('Use YYYY or YYYY-MM.')).length).toBeGreaterThan(0)
    expect(end).toHaveAttribute('aria-invalid', 'true')
    expect(end).toHaveAccessibleDescription('Use YYYY or YYYY-MM.')
  })

  it('shows server validation errors without discarding edits', async () => {
    server.use(http.get(`${API}/profile`, () => HttpResponse.json(profileFx)), http.put(`${API}/profile`, () => HttpResponse.json({ detail: 'Request contains a value the database cannot store' }, { status: 422 })))
    const { user } = renderApp('/profile')
    const name = await screen.findByLabelText('Full name')
    await user.clear(name); await user.type(name, 'Riya S.')
    await user.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText(/cannot store/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Full name')).toHaveValue('Riya S.'))
  })
})
