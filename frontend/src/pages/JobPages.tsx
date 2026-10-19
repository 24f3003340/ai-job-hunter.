import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { applicationsApi, jobsApi, resumesApi } from '../api/endpoints'
import type { Job, JobInput } from '../api/types'
import { MatchPanel } from '../components/MatchPanel'
import { Alert, Badge, Empty, ErrorAlert, Field, Loading, PageTitle, TextField } from '../components/ui'
import { JOB_STATUS_LABEL, REVIEW_LABEL, formatDate } from '../lib/labels'
import { safeHttpUrl } from '../lib/safeUrl'

const PAGE = 20

function MatchChip({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['match', id], queryFn: () => jobsApi.match(id), staleTime: 60_000 })
  if (q.isLoading) return <span className="muted">Scoring…</span>
  if (q.error || !q.data) return <span className="muted">Score unavailable</span>
  return (
    <span>
      <strong>{q.data.score === null ? 'n/a' : q.data.score}</strong>
      {q.data.disqualified && <> <Badge kind="danger">Disqualifier</Badge></>}
      {q.data.unknown_dimensions.length > 0 && <> <Badge kind="warn">{q.data.unknown_dimensions.length} unknown</Badge></>}
    </span>
  )
}

export function JobsPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? '', status = params.get('status') ?? '', page = Number(params.get('page') ?? 0)
  const [draft, setDraft] = useState(q)
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) { if (v) next.set(k, v); else next.delete(k) }
    setParams(next)
  }
  const list = useQuery({ queryKey: ['jobs', q, status, page], queryFn: () => jobsApi.list({ q, status, limit: PAGE, offset: page * PAGE }) })
  return (
    <>
      <PageTitle>Jobs</PageTitle>
      <div className="row"><Link className="btn" to="/jobs/new">Add a job</Link></div>
      <p className="muted">Jobs are added by you (from an official page or posting). Nothing is scraped or fetched automatically.</p>
      <form className="card row" role="search" aria-label="Filter jobs" onSubmit={(e) => { e.preventDefault(); set({ q: draft, page: '' }) }}>
        <Field label="Search title or company">{(p) => <input {...p} type="search" value={draft} onChange={(e) => setDraft(e.target.value)} />}</Field>
        <Field label="Listing status">
          {(p) => (
            <select {...p} value={status} onChange={(e) => set({ status: e.target.value, page: '' })}>
              <option value="">All</option>
              {Object.entries(JOB_STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          )}
        </Field>
        <button type="submit">Search</button>
      </form>
      {list.isLoading && <Loading />}
      <ErrorAlert error={list.error} />
      {list.data?.length === 0 && <Empty>No jobs found. <Link to="/jobs/new">Add one</Link>.</Empty>}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">Jobs with match scores</caption>
            <thead><tr><th scope="col">Job</th><th scope="col">Location</th><th scope="col">Listing</th><th scope="col">Match</th></tr></thead>
            <tbody>
              {list.data.map((j: Job) => (
                <tr key={j.id}>
                  <td><Link to={`/jobs/${j.id}`}>{j.title}</Link><br /><span className="muted">{j.company}</span></td>
                  <td>{j.location || (j.remote ? 'Remote' : '—')}</td>
                  <td><Badge kind={j.status === 'active' ? 'ok' : j.status === 'expired' ? 'danger' : 'warn'}>{JOB_STATUS_LABEL[j.status] ?? j.status}</Badge></td>
                  <td><MatchChip id={j.id} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <nav aria-label="Pagination" className="row">
        <button className="secondary" disabled={page === 0} onClick={() => set({ page: String(page - 1) })}>Previous</button>
        <span>Page {page + 1}</span>
        <button className="secondary" disabled={(list.data?.length ?? 0) < PAGE} onClick={() => set({ page: String(page + 1) })}>Next</button>
      </nav>
    </>
  )
}

const csv = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
const tri = (v: string): boolean | null => (v === 'yes' ? true : v === 'no' ? false : null)
const numOrNull = (s: string) => (s.trim() === '' ? null : Number(s))

export function JobNewPage() {
  const nav = useNavigate()
  const [f, setF] = useState({ title: '', company: '', location: '', remote: '', description: '', req: '', pref: '', smin: '', smax: '',
    period: '', exp: '', degree: '', url: '' })
  const [err, setErr] = useState<Record<string, string>>({})
  const m = useMutation({
    mutationFn: (j: JobInput) => jobsApi.create(j),
    onSuccess: (j) => nav(`/jobs/${j.id}`),
  })
  const up = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }))
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: Record<string, string> = {}
    if (!f.title.trim()) errs.title = 'Enter the job title.'
    if (!f.company.trim()) errs.company = 'Enter the employer.'
    if (f.url && !safeHttpUrl(f.url)) errs.url = 'Enter a full http(s) address.'
    if ((f.smin || f.smax) && !f.period) errs.period = 'Choose whether the salary is per month or per year.'
    setErr(errs)
    if (Object.keys(errs).length) return
    m.mutate({
      title: f.title.trim(), company: f.company.trim(), location: f.location, remote: tri(f.remote), description: f.description,
      required_skills: csv(f.req), preferred_skills: csv(f.pref), salary_min: numOrNull(f.smin), salary_max: numOrNull(f.smax),
      salary_period: (f.period || null) as 'month' | 'year' | null, experience_min: numOrNull(f.exp),
      requires_degree_completed: tri(f.degree), application_url: f.url || null,
    })
  }
  const fe = m.error instanceof ApiError ? m.error.fieldErrors : {}
  return (
    <>
      <PageTitle>Add a job</PageTitle>
      <p>Enter what the posting says. Leave a field blank if the posting doesn’t say – unknown values are shown as unknown, never assumed.</p>
      <form onSubmit={submit} aria-label="Add job">
        <ErrorAlert error={m.error} />
        <TextField label="Job title" value={f.title} onChange={up('title')} required error={err.title ?? fe.title} />
        <TextField label="Employer" value={f.company} onChange={up('company')} required error={err.company ?? fe.company} />
        <TextField label="Location" value={f.location} onChange={up('location')} />
        <Field label="Remote?">{(p) => <select {...p} value={f.remote} onChange={(e) => up('remote')(e.target.value)}><option value="">Not stated</option><option value="yes">Remote allowed</option><option value="no">On-site</option></select>}</Field>
        <TextField label="Official application link" value={f.url} onChange={up('url')} error={err.url} hint="Paste the employer’s or job board’s own page. You will apply there yourself." />
        <Field label="Description" hint="Pasted text is shown as plain text only.">{(p) => <textarea {...p} value={f.description} onChange={(e) => up('description')(e.target.value)} />}</Field>
        <TextField label="Required skills (comma separated)" value={f.req} onChange={up('req')} />
        <TextField label="Preferred skills (comma separated)" value={f.pref} onChange={up('pref')} />
        <div className="row">
          <TextField label="Salary min" type="number" value={f.smin} onChange={up('smin')} />
          <TextField label="Salary max" type="number" value={f.smax} onChange={up('smax')} />
          <Field label="Salary period" error={err.period}>{(p) => <select {...p} value={f.period} onChange={(e) => up('period')(e.target.value)}><option value="">Not stated</option><option value="month">Per month</option><option value="year">Per year</option></select>}</Field>
        </div>
        <TextField label="Minimum experience (years)" type="number" value={f.exp} onChange={up('exp')} />
        <Field label="Requires a completed degree?">{(p) => <select {...p} value={f.degree} onChange={(e) => up('degree')(e.target.value)}><option value="">Not stated</option><option value="yes">Yes, completed degree required</option><option value="no">No</option></select>}</Field>
        <button type="submit" disabled={m.isPending}>{m.isPending ? 'Saving…' : 'Add job'}</button>
      </form>
    </>
  )
}

export function JobDetailPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const job = useQuery({ queryKey: ['job', id], queryFn: () => jobsApi.get(id) })
  const match = useQuery({ queryKey: ['match', id], queryFn: () => jobsApi.match(id) })
  const resumes = useQuery({ queryKey: ['resumes', id], queryFn: () => resumesApi.list(id), staleTime: 0 })
  const apps = useQuery({ queryKey: ['applications'], queryFn: () => applicationsApi.list() })
  const verify = useMutation({ mutationFn: () => jobsApi.verify(id), onSuccess: (j) => { qc.setQueryData(['job', id], j); void qc.invalidateQueries({ queryKey: ['match', id] }) } })
  const gen = useMutation({ mutationFn: () => resumesApi.generate(id), onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ['resumes', id] }); nav(`/resumes/${r.id}`) } })
  const createApp = useMutation({
    mutationFn: (resumeId: string | null) => applicationsApi.create({ job_id: id, resume_version_id: resumeId }),
    onSuccess: (a) => { void qc.invalidateQueries({ queryKey: ['applications'] }); nav(`/applications/${a.id}`) },
  })
  const j = job.data
  const existing = apps.data?.find((a) => a.job_id === id && !['closed', 'withdrawn'].includes(a.status))
  const url = safeHttpUrl(j?.application_url)
  const latest = resumes.data?.[0]

  return (
    <>
      <PageTitle>{j ? `${j.title} – ${j.company}` : 'Job'}</PageTitle>
      {job.isLoading && <Loading />}
      <ErrorAlert error={job.error} />
      {j && (
        <>
          <div className="card">
            <p><Badge kind={j.status === 'active' ? 'ok' : j.status === 'expired' ? 'danger' : 'warn'}>{JOB_STATUS_LABEL[j.status] ?? j.status}</Badge>{' '}
              <span className="muted">Added {formatDate(j.first_seen_at)} · last verified {formatDate(j.last_verified_at)}</span></p>
            {j.status !== 'active' && j.status !== 'expired' && (
              <Alert kind="warn">This listing has not been verified. Check the official page, then confirm it is still open.
                <div><button onClick={() => verify.mutate()} disabled={verify.isPending}>I checked – the listing is live</button></div>
                <ErrorAlert error={verify.error} />
              </Alert>
            )}
            <p>{j.location || (j.remote ? 'Remote' : 'Location not stated')} · Salary: {j.salary_min || j.salary_max ? `${j.salary_min ?? '?'}–${j.salary_max ?? '?'} per ${j.salary_period ?? '(period not stated)'}` : 'not stated'} · Experience: {j.experience_min ?? 'not stated'}</p>
            <p>{url ? <a href={url} target="_blank" rel="noopener noreferrer nofollow">Official application page (opens in a new tab)</a> : <span className="muted">No valid application link on file.</span>}</p>
            <h2>Description</h2>
            {/* Plain text only. React escapes it; it is never injected as HTML. */}
            <p className="plain">{j.description || 'No description provided.'}</p>
          </div>

          {match.isLoading && <Loading label="Calculating match…" />}
          <ErrorAlert error={match.error} />
          {match.data && <MatchPanel m={match.data} />}

          <section aria-labelledby="res-h" className="card">
            <h2 id="res-h" style={{ marginTop: 0 }}>Tailored resumes</h2>
            <p>Each generation creates a new, unchangeable version built only from your profile.</p>
            <ErrorAlert error={gen.error} />
            {gen.error instanceof ApiError && gen.error.code === 'ai_consent_required' && <p><Link to="/settings">Review AI consent in Settings</Link></p>}
            <button onClick={() => gen.mutate()} disabled={gen.isPending}>{gen.isPending ? 'Generating…' : 'Generate tailored resume'}</button>
            {resumes.isLoading && <Loading />}
            {resumes.data?.length === 0 && <p className="muted">No versions yet.</p>}
            <ul className="clean">
              {resumes.data?.map((r) => (
                <li key={r.id}><Link to={`/resumes/${r.id}`}>Version {r.version_number}</Link> · {formatDate(r.created_at)} ·{' '}
                  <Badge kind={r.review_status === 'clean' || r.review_status === 'reviewed' ? 'ok' : 'warn'}>{REVIEW_LABEL[r.review_status]}</Badge></li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="app-h" className="card">
            <h2 id="app-h" style={{ marginTop: 0 }}>Application</h2>
            {existing ? <p>You already have an application for this job. <Link to={`/applications/${existing.id}`}>Open it</Link>.</p> : (
              <>
                <p>Create a draft to review the resume and answers. Nothing is sent anywhere.</p>
                <ErrorAlert error={createApp.error} />
                <button onClick={() => createApp.mutate(latest?.id ?? null)} disabled={createApp.isPending}>
                  {latest ? `Create draft with resume version ${latest.version_number}` : 'Create draft (no resume yet)'}
                </button>
              </>
            )}
          </section>
        </>
      )}
    </>
  )
}
