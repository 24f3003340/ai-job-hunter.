import { useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { Certification, Education, EduStatus, Experience, Preferences, Project, ProfileData, Skill } from '../api/types'
import { Alert, Field, TextField } from './ui'

type K<T> = T & { _k: number }
type EduDraft = Omit<Education, 'status'> & { status: EduStatus | ''; hint?: string }

export interface ProfileDraft {
  full_name: string; phone: string
  education: K<EduDraft>[]; experience: K<Experience>[]; projects: K<Project>[]; skills: K<Skill>[]; certifications: K<Certification>[]
  preferences: Preferences
}

export const EMPTY_PREFS: Preferences = {
  target_titles: [], min_salary_monthly: null, cities: [], remote_ok: true, relocation_ok: false,
  experience_years: null, excluded_employers: [], excluded_locations: [],
}

let counter = 0
const k = () => ++counter
const tag = <T,>(xs: T[]): K<T>[] => xs.map((x) => ({ ...x, _k: k() }))

/** Build a draft. Education status is copied as given - never defaulted or inferred. */
export function toDraft(p: Partial<Omit<ProfileData, 'education'>> & { education?: (Omit<Education, 'status'> & { status: EduStatus | null; hint?: string })[] }): ProfileDraft {
  return {
    full_name: p.full_name ?? '', phone: p.phone ?? '',
    education: tag((p.education ?? []).map((e) => ({ ...e, status: e.status ?? '' as const }))),
    experience: tag(p.experience ?? []), projects: tag(p.projects ?? []), skills: tag(p.skills ?? []),
    certifications: tag(p.certifications ?? []), preferences: p.preferences ?? EMPTY_PREFS,
  }
}

const DATE = /^\d{4}(-(0[1-9]|1[0-2]))?$/
const strip = <T extends { _k: number }>(x: T): Omit<T, '_k'> => { const { _k, ...rest } = x; void _k; return rest }
const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)
const csv = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
const num = (s: string) => (s.trim() === '' ? null : Number(s))

export function validate(d: ProfileDraft): Record<string, string> {
  const e: Record<string, string> = {}
  if (!d.full_name.trim()) e.full_name = 'Enter your full name.'
  d.education.forEach((x, i) => {
    if (!x.degree.trim()) e[`edu.${i}.degree`] = 'Enter the degree.'
    if (!x.status) e[`edu.${i}.status`] = 'Choose completed or in progress. This is never guessed for you.'
    for (const f of ['start_date', 'end_date'] as const) if (x[f] && !DATE.test(x[f]!)) e[`edu.${i}.${f}`] = 'Use YYYY or YYYY-MM.'
  })
  d.experience.forEach((x, i) => {
    for (const f of ['start_date', 'end_date'] as const) if (x[f] && !DATE.test(x[f]!)) e[`exp.${i}.${f}`] = 'Use YYYY or YYYY-MM.'
  })
  d.certifications.forEach((x, i) => {
    if (!x.name.trim()) e[`cert.${i}.name`] = 'Enter the certification name.'
    if (x.date && !DATE.test(x.date)) e[`cert.${i}.date`] = 'Use YYYY or YYYY-MM.'
  })
  d.skills.forEach((x, i) => { if (!x.name.trim()) e[`skill.${i}`] = 'Enter a skill or remove this row.' })
  return e
}

export function fromDraft(d: ProfileDraft): ProfileData {
  return {
    full_name: d.full_name.trim(), phone: d.phone.trim(),
    education: d.education.map((x) => { const { _k, hint, ...r } = x; void _k; void hint; return { ...r, status: x.status as EduStatus } }),
    experience: d.experience.map(strip), projects: d.projects.map(strip),
    skills: d.skills.map(strip).filter((s) => s.name.trim()), certifications: d.certifications.map(strip),
    preferences: d.preferences,
  }
}

function Section<T extends { _k: number }>({ legend, items, onAdd, addLabel, children }: {
  legend: string; items: T[]; onAdd: () => void; addLabel: string; children: (item: T, i: number) => ReactNode
}) {
  return (
    <fieldset>
      <legend>{legend}</legend>
      {items.length === 0 && <p className="muted">None added.</p>}
      {items.map((it, i) => <div key={it._k} className="card">{children(it, i)}</div>)}
      <button type="button" className="secondary" onClick={onAdd}>{addLabel}</button>
    </fieldset>
  )
}

export function ProfileForm({ initial, onSubmit, busy, submitLabel, showPreferences, children }: {
  initial: ProfileDraft; onSubmit: (d: ProfileData) => void; busy?: boolean; submitLabel: string
  showPreferences?: boolean; children?: ReactNode
}) {
  const [d, setD] = useState<ProfileDraft>(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const summary = useRef<HTMLDivElement>(null)
  const set = <K2 extends keyof ProfileDraft>(key: K2, v: ProfileDraft[K2]) => setD((p) => ({ ...p, [key]: v }))
  const upd = (key: 'education' | 'experience' | 'projects' | 'skills' | 'certifications', i: number, patch: Record<string, unknown>) =>
    setD((p) => ({ ...p, [key]: (p[key] as unknown as object[]).map((x, j) => (j === i ? { ...x, ...patch } : x)) }) as ProfileDraft)
  const del = (key: 'education' | 'experience' | 'projects' | 'skills' | 'certifications', i: number) =>
    setD((p) => ({ ...p, [key]: (p[key] as unknown[]).filter((_, j) => j !== i) }) as ProfileDraft)
  const add = (key: 'education' | 'experience' | 'projects' | 'skills' | 'certifications', item: object) =>
    setD((p) => ({ ...p, [key]: [...(p[key] as unknown[]), { ...item, _k: k() }] }) as ProfileDraft)
  const P = d.preferences
  const setP = (patch: Partial<Preferences>) => set('preferences', { ...P, ...patch })

  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    const errs = validate(d)
    setErrors(errs)
    if (Object.keys(errs).length) { setTimeout(() => summary.current?.focus(), 0); return }
    onSubmit(fromDraft(d))
  }
  const errList = Object.values(errors)

  return (
    <form onSubmit={submit} aria-label="Profile" noValidate>
      {errList.length > 0 && (
        <div ref={summary} tabIndex={-1} role="alert" className="alert error">
          <strong>Please fix {errList.length} problem{errList.length > 1 ? 's' : ''}:</strong>
          <ul>{errList.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </div>
      )}
      <fieldset>
        <legend>About you</legend>
        <TextField label="Full name" value={d.full_name} onChange={(v) => set('full_name', v)} required error={errors.full_name} autoComplete="name" />
        <TextField label="Phone" value={d.phone} onChange={(v) => set('phone', v)} autoComplete="tel" />
      </fieldset>

      <Section legend="Education" items={d.education} addLabel="Add education"
        onAdd={() => add('education', { degree: '', institution: '', status: '', start_date: null, end_date: null, verified: false })}>
        {(x, i) => (<>
          <TextField label="Degree" value={x.degree} onChange={(v) => upd('education', i, { degree: v })} required error={errors[`edu.${i}.degree`]} />
          <TextField label="Institution" value={x.institution} onChange={(v) => upd('education', i, { institution: v })} />
          <Field label="Status" error={errors[`edu.${i}.status`]}
            hint={x.hint}>
            {(p) => (
              <select {...p} value={x.status} onChange={(e) => upd('education', i, { status: e.target.value as EduStatus | '' })}>
                <option value="">Choose status…</option>
                <option value="in_progress">In progress (not yet completed)</option>
                <option value="completed">Completed</option>
              </select>
            )}
          </Field>
          <div className="row">
            <TextField label="Start (YYYY or YYYY-MM)" value={x.start_date ?? ''} onChange={(v) => upd('education', i, { start_date: v || null })} error={errors[`edu.${i}.start_date`]} />
            <TextField label="End or expected end" value={x.end_date ?? ''} onChange={(v) => upd('education', i, { end_date: v || null })} error={errors[`edu.${i}.end_date`]} />
          </div>
          <button type="button" className="secondary" onClick={() => del('education', i)} aria-label={`Remove education ${i + 1}`}>Remove</button>
        </>)}
      </Section>

      <Section legend="Experience" items={d.experience} addLabel="Add experience"
        onAdd={() => add('experience', { title: '', employer: '', start_date: null, end_date: null, current: false, description: '', bullets: [] })}>
        {(x, i) => (<>
          <TextField label="Job title" value={x.title} onChange={(v) => upd('experience', i, { title: v })} />
          <TextField label="Employer" value={x.employer} onChange={(v) => upd('experience', i, { employer: v })} />
          <div className="row">
            <TextField label="Start (YYYY or YYYY-MM)" value={x.start_date ?? ''} onChange={(v) => upd('experience', i, { start_date: v || null })} error={errors[`exp.${i}.start_date`]} />
            <TextField label="End" value={x.end_date ?? ''} onChange={(v) => upd('experience', i, { end_date: v || null })} error={errors[`exp.${i}.end_date`]} />
          </div>
          <div className="check"><input type="checkbox" id={`cur-${x._k}`} checked={x.current} onChange={(e) => upd('experience', i, { current: e.target.checked })} /><label htmlFor={`cur-${x._k}`}>I currently work here</label></div>
          <Field label="Description">{(p) => <textarea {...p} value={x.description} onChange={(e) => upd('experience', i, { description: e.target.value })} />}</Field>
          <Field label="Achievements / bullets" hint="One per line. Only list things that are true; resumes can only reuse what you write here.">
            {(p) => <textarea {...p} value={x.bullets.join('\n')} onChange={(e) => upd('experience', i, { bullets: lines(e.target.value) })} />}
          </Field>
          <button type="button" className="secondary" onClick={() => del('experience', i)} aria-label={`Remove experience ${i + 1}`}>Remove</button>
        </>)}
      </Section>

      <Section legend="Projects" items={d.projects} addLabel="Add project"
        onAdd={() => add('projects', { name: '', description: '', bullets: [], technologies: [], url: null })}>
        {(x, i) => (<>
          <TextField label="Project name" value={x.name} onChange={(v) => upd('projects', i, { name: v })} />
          <Field label="Description">{(p) => <textarea {...p} value={x.description} onChange={(e) => upd('projects', i, { description: e.target.value })} />}</Field>
          <Field label="Bullets" hint="One per line.">{(p) => <textarea {...p} value={x.bullets.join('\n')} onChange={(e) => upd('projects', i, { bullets: lines(e.target.value) })} />}</Field>
          <TextField label="Technologies (comma separated)" value={x.technologies.join(', ')} onChange={(v) => upd('projects', i, { technologies: csv(v) })} />
          <TextField label="URL" value={x.url ?? ''} onChange={(v) => upd('projects', i, { url: v || null })} />
          <button type="button" className="secondary" onClick={() => del('projects', i)} aria-label={`Remove project ${i + 1}`}>Remove</button>
        </>)}
      </Section>

      <Section legend="Skills" items={d.skills} addLabel="Add skill" onAdd={() => add('skills', { name: '', level: null, verified: false })}>
        {(x, i) => (<>
          <div className="row">
            <TextField label="Skill" value={x.name} onChange={(v) => upd('skills', i, { name: v })} error={errors[`skill.${i}`]} />
            <Field label="Level">
              {(p) => (
                <select {...p} value={x.level ?? ''} onChange={(e) => upd('skills', i, { level: (e.target.value || null) as Skill['level'] })}>
                  <option value="">Not specified</option><option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option><option value="advanced">Advanced</option>
                </select>
              )}
            </Field>
            <button type="button" className="secondary" onClick={() => del('skills', i)} aria-label={`Remove skill ${x.name || i + 1}`}>Remove</button>
          </div>
        </>)}
      </Section>

      <Section legend="Certifications" items={d.certifications} addLabel="Add certification" onAdd={() => add('certifications', { name: '', issuer: '', date: null })}>
        {(x, i) => (<>
          <TextField label="Name" value={x.name} onChange={(v) => upd('certifications', i, { name: v })} error={errors[`cert.${i}.name`]} />
          <TextField label="Issuer" value={x.issuer} onChange={(v) => upd('certifications', i, { issuer: v })} />
          <TextField label="Date (YYYY or YYYY-MM)" value={x.date ?? ''} onChange={(v) => upd('certifications', i, { date: v || null })} error={errors[`cert.${i}.date`]} />
          <button type="button" className="secondary" onClick={() => del('certifications', i)} aria-label={`Remove certification ${i + 1}`}>Remove</button>
        </>)}
      </Section>

      {showPreferences && (
        <fieldset>
          <legend>Job preferences</legend>
          <TextField label="Target job titles (comma separated)" value={P.target_titles.join(', ')} onChange={(v) => setP({ target_titles: csv(v) })} />
          <TextField label="Minimum salary (INR per month)" type="number" value={P.min_salary_monthly?.toString() ?? ''} onChange={(v) => setP({ min_salary_monthly: num(v) })} />
          <TextField label="Years of experience" type="number" value={P.experience_years?.toString() ?? ''} onChange={(v) => setP({ experience_years: num(v) })} />
          <TextField label="Preferred cities (comma separated)" value={P.cities.join(', ')} onChange={(v) => setP({ cities: csv(v) })} />
          <div className="check"><input id="pref-remote" type="checkbox" checked={P.remote_ok} onChange={(e) => setP({ remote_ok: e.target.checked })} /><label htmlFor="pref-remote">Open to remote work</label></div>
          <div className="check"><input id="pref-reloc" type="checkbox" checked={P.relocation_ok} onChange={(e) => setP({ relocation_ok: e.target.checked })} /><label htmlFor="pref-reloc">Willing to relocate</label></div>
          <TextField label="Excluded employers (comma separated)" value={P.excluded_employers.join(', ')} onChange={(v) => setP({ excluded_employers: csv(v) })} />
          <TextField label="Excluded locations (comma separated)" value={P.excluded_locations.join(', ')} onChange={(v) => setP({ excluded_locations: csv(v) })} />
        </fieldset>
      )}

      {children}
      <button type="submit" disabled={busy}>{busy ? 'Saving…' : submitLabel}</button>
    </form>
  )
}

export function InProgressNote() {
  return <Alert kind="info">Education marked “in progress” stays in progress everywhere, including on generated resumes. Nothing is changed to “completed” unless you choose it.</Alert>
}
