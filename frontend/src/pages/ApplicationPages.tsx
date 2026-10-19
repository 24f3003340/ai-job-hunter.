import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { applicationsApi, jobsApi, resumesApi } from '../api/endpoints'
import type { AnswerInput, ApplicationDetail } from '../api/types'
import { Alert, Badge, Empty, ErrorAlert, Loading, Modal, PageTitle } from '../components/ui'
import { REVIEW_LABEL, applicationStatusLabel, formatDate } from '../lib/labels'
import { safeHttpUrl } from '../lib/safeUrl'

export function ApplicationsPage() {
  const [status, setStatus] = useState('')
  const apps = useQuery({ queryKey: ['applications'], queryFn: () => applicationsApi.list() })
  const jobs = useQuery({ queryKey: ['jobs', 'all'], queryFn: () => jobsApi.list({ limit: 200 }) })
  const jobById = new Map(jobs.data?.map((j) => [j.id, j]))
  const rows = apps.data?.filter((a) => !status || a.status === status) ?? []
  const statuses = [...new Set(apps.data?.map((a) => a.status) ?? [])]
  return (
    <>
      <PageTitle>Applications</PageTitle>
      <Alert kind="info">This app does not apply to jobs for you. “Applied” means <em>you</em> reported applying on the employer’s own site.</Alert>
      {apps.isLoading && <Loading />}
      <ErrorAlert error={apps.error} />
      {apps.data && apps.data.length > 0 && (
        <div className="field" style={{ maxWidth: 320 }}>
          <label htmlFor="status-filter">Filter by status</label>
          <select id="status-filter" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {statuses.map((s) => <option key={s} value={s}>{applicationStatusLabel(s)}</option>)}
          </select>
        </div>
      )}
      {apps.data?.length === 0 && <Empty>No applications yet. Open a <Link to="/jobs">job</Link> and create a draft.</Empty>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">Application tracker</caption>
            <thead><tr><th scope="col">Job</th><th scope="col">Status</th><th scope="col">Applied</th><th scope="col">Official page</th><th scope="col"><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {rows.map((a) => {
                const j = jobById.get(a.job_id)
                const url = safeHttpUrl(a.manual_application_url)
                return (
                  <tr key={a.id}>
                    <td>{j ? <><Link to={`/jobs/${j.id}`}>{j.title}</Link><br /><span className="muted">{j.company}</span></> : <span className="muted">Job {a.job_id.slice(0, 8)}…</span>}</td>
                    <td><Badge kind={a.status === 'submitted' ? 'ok' : a.status === 'ready_for_review' ? 'warn' : undefined}>{applicationStatusLabel(a.status, a.submission_method)}</Badge></td>
                    <td>{a.status === 'submitted' ? <>{formatDate(a.submitted_at)}<br /><span className="muted">{a.submission_method === 'manual_user_reported' ? 'reported by you' : ''}</span></> : '—'}</td>
                    <td>{url ? <a href={url} target="_blank" rel="noopener noreferrer nofollow">Open</a> : '—'}</td>
                    <td><Link to={`/applications/${a.id}`}>Review</Link></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

// Mirrors backend MANUAL_TRANSITIONS for presentation only; the backend remains the authority.
const NEXT: Record<string, string[]> = {
  submitted: ['interview', 'rejected', 'offer_received', 'withdrawn', 'closed'],
  interview: ['rejected', 'offer_received', 'withdrawn', 'closed'],
  offer_received: ['withdrawn', 'closed'], rejected: ['closed'], withdrawn: ['closed'],
  approved: ['withdrawn', 'closed'], ready_for_review: ['withdrawn', 'closed'], discovered: ['withdrawn', 'closed'], match_evaluated: ['withdrawn', 'closed'],
  submission_failed: ['withdrawn', 'closed'],
}
const EDITABLE = ['discovered', 'match_evaluated', 'ready_for_review', 'approved', 'submission_failed']

export function ApplicationReviewPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const app = useQuery({ queryKey: ['application', id], queryFn: () => applicationsApi.get(id) })
  const a = app.data
  const job = useQuery({ queryKey: ['job', a?.job_id], queryFn: () => jobsApi.get(a!.job_id), enabled: !!a })
  const resume = useQuery({ queryKey: ['resume', a?.resume_version_id], queryFn: () => resumesApi.get(a!.resume_version_id!), enabled: !!a?.resume_version_id })
  const versions = useQuery({ queryKey: ['resumes', a?.job_id], queryFn: () => resumesApi.list(a!.job_id), enabled: !!a, staleTime: 0 })

  const [answers, setAnswers] = useState<AnswerInput[] | null>(null)
  const [notice, setNotice] = useState<string>('')
  const [approveChecked, setApproveChecked] = useState(false)
  const [confirmApplied, setConfirmApplied] = useState(false)
  const [pendingEdit, setPendingEdit] = useState<null | (() => void)>(null)
  const [manualInfo, setManualInfo] = useState<string>('')
  const shown = answers ?? a?.answers ?? []

  const refresh = (data: ApplicationDetail | { status: string }) => {
    void qc.invalidateQueries({ queryKey: ['application', id] })
    void qc.invalidateQueries({ queryKey: ['applications'] })
    return data
  }
  /** Detect that an edit silently withdrew a previous approval (backend revokes it on any material change). */
  const afterEdit = (before: string | undefined, after: { status: string }) => {
    if (before === 'approved' && after.status !== 'approved') setNotice('Your approval was withdrawn because the application changed. Review it again and re-approve.')
    setApproveChecked(false)
    refresh(after)
  }
  const saveAnswers = useMutation({ mutationFn: () => applicationsApi.setAnswers(id, shown), onSuccess: (r) => { afterEdit(a?.status, r); setAnswers(null) } })
  const switchResume = useMutation({ mutationFn: (rid: string) => applicationsApi.setResume(id, rid), onSuccess: (r) => afterEdit(a?.status, r) })
  const approve = useMutation({ mutationFn: () => applicationsApi.approve(id), onSuccess: (r) => { setNotice(''); setManualInfo(''); refresh(r) }, onError: () => refresh({ status: '' }) })
  const submit = useMutation({
    mutationFn: () => applicationsApi.submit(id),
    onSuccess: (r) => { setManualInfo(r.detail ?? ''); refresh(r) },
    onError: () => { setNotice('The package changed since you approved it, or is no longer eligible. Review it and approve again.'); refresh({ status: '' }) },
  })
  const setStatus = useMutation({ mutationFn: (v: { status: string; reported?: boolean }) => applicationsApi.setStatus(id, v.status, { user_reported_submission: v.reported }), onSuccess: (r) => { setConfirmApplied(false); refresh(r) } })

  const editable = !!a && EDITABLE.includes(a.status)
  const guardEdit = (fn: () => void) => { if (a?.status === 'approved') setPendingEdit(() => fn); else fn() }
  const url = safeHttpUrl(a?.manual_application_url) ?? safeHttpUrl(job.data?.application_url)
  const allConfirmed = shown.every((x) => x.user_confirmed)
  const R = resume.data

  return (
    <>
      <PageTitle>Review application</PageTitle>
      {app.isLoading && <Loading />}
      <ErrorAlert error={app.error} />
      {notice && <Alert kind="warn">{notice}</Alert>}
      {a && (
        <>
          <p><Badge kind={a.status === 'approved' ? 'ok' : 'warn'}>{applicationStatusLabel(a.status, a.submission_method)}</Badge> · <Link to="/applications">All applications</Link></p>

          <section className="card" aria-labelledby="job-h">
            <h2 id="job-h" style={{ marginTop: 0 }}>1. Job</h2>
            {job.data ? <p><Link to={`/jobs/${job.data.id}`}>{job.data.title}</Link> at {job.data.company} · {job.data.location || 'location not stated'}<br />
              {url ? <a href={url} target="_blank" rel="noopener noreferrer nofollow">Official application page (opens in a new tab)</a> : <span className="muted">No valid application link on file.</span>}</p> : <Loading />}
          </section>

          <section className="card" aria-labelledby="res-h">
            <h2 id="res-h" style={{ marginTop: 0 }}>2. Resume</h2>
            {!a.resume_version_id && <Alert kind="warn">No tailored resume is attached. <Link to={`/jobs/${a.job_id}`}>Generate one</Link>, then attach it below.</Alert>}
            {R && <p>Version {R.version_number} · <Badge kind={R.review_status === 'clean' || R.review_status === 'reviewed' ? 'ok' : 'warn'}>{REVIEW_LABEL[R.review_status]}</Badge> · <Link to={`/resumes/${R.id}`}>Open to review statements</Link></p>}
            {editable && versions.data && versions.data.length > 0 && (
              <div className="row">
                <label htmlFor="ver">Use version</label>
                <select id="ver" value={a.resume_version_id ?? ''} onChange={(e) => e.target.value && guardEdit(() => switchResume.mutate(e.target.value))}>
                  <option value="">Choose…</option>
                  {versions.data.map((v) => <option key={v.id} value={v.id}>Version {v.version_number} ({formatDate(v.created_at)})</option>)}
                </select>
              </div>
            )}
            <ErrorAlert error={switchResume.error} />
          </section>

          <section className="card" aria-labelledby="cl-h">
            <h2 id="cl-h" style={{ marginTop: 0 }}>3. Cover letter</h2>
            {a.cover_letter_id ? <p>A cover letter is attached, but the API does not expose its text, so it cannot be shown or edited here. Approval still covers it exactly.</p> : <p className="muted">No cover letter attached. (Creating cover letters is not available yet.)</p>}
          </section>

          <section className="card" aria-labelledby="ans-h">
            <h2 id="ans-h" style={{ marginTop: 0 }}>4. Screening answers</h2>
            <p className="muted">Write only answers you know to be true. Legal, eligibility and salary questions should be answered by you, never guessed.</p>
            {shown.length === 0 && <p className="muted">No answers yet.</p>}
            {shown.map((x, i) => (
              <fieldset key={i} disabled={!editable}>
                <legend>Question {i + 1}</legend>
                <div className="field"><label htmlFor={`q-${i}`}>Question</label><input id={`q-${i}`} type="text" value={x.question} onChange={(e) => setAnswers(shown.map((y, j) => j === i ? { ...y, question: e.target.value } : y))} /></div>
                <div className="field"><label htmlFor={`a-${i}`}>Your answer</label><textarea id={`a-${i}`} value={x.answer} onChange={(e) => setAnswers(shown.map((y, j) => j === i ? { ...y, answer: e.target.value, user_confirmed: false } : y))} /></div>
                <div className="check"><input id={`c-${i}`} type="checkbox" checked={x.user_confirmed} onChange={(e) => setAnswers(shown.map((y, j) => j === i ? { ...y, user_confirmed: e.target.checked } : y))} /><label htmlFor={`c-${i}`}>I confirm this answer is accurate</label></div>
                <button type="button" className="secondary" onClick={() => setAnswers(shown.filter((_, j) => j !== i))} aria-label={`Remove question ${i + 1}`}>Remove</button>
              </fieldset>
            ))}
            {editable && (
              <div className="row">
                <button type="button" className="secondary" onClick={() => setAnswers([...shown, { question: '', answer: '', source_of_truth: 'user', user_confirmed: false }])}>Add a question</button>
                <button type="button" disabled={answers === null || saveAnswers.isPending || shown.some((x) => !x.question.trim())} onClick={() => guardEdit(() => saveAnswers.mutate())}>Save answers</button>
              </div>
            )}
            <ErrorAlert error={saveAnswers.error} />
          </section>

          {(a.blockers.length > 0 || (a.status === 'ready_for_review' && !allConfirmed)) && (
            <Alert kind="warn"><strong>Before you can approve:</strong>
              <ul>{a.blockers.map((b) => <li key={b}>{b}</li>)}{!allConfirmed && <li>Save your answers after confirming each one</li>}</ul></Alert>
          )}

          {a.status === 'ready_for_review' && (
            <section className="card" aria-labelledby="appr-h">
              <h2 id="appr-h" style={{ marginTop: 0 }}>5. Approve</h2>
              <p>Approval is tied to this exact job, resume version, cover letter and answers. Any later change withdraws it.</p>
              <ErrorAlert error={approve.error} />
              <div className="check"><input id="approve-check" type="checkbox" checked={approveChecked} onChange={(e) => setApproveChecked(e.target.checked)} /><label htmlFor="approve-check">I have reviewed the job, resume, cover letter and answers above and I approve this exact package.</label></div>
              <button disabled={!approveChecked || approve.isPending || answers !== null} onClick={() => approve.mutate()}>{approve.isPending ? 'Approving…' : 'Approve this package'}</button>
              {answers !== null && <p className="hint">Save your answer edits before approving.</p>}
            </section>
          )}

          {a.status === 'approved' && (
            <section className="card" aria-labelledby="sub-h">
              <h2 id="sub-h" style={{ marginTop: 0 }}>6. Apply</h2>
              <Alert kind="info">You approved this package. <strong>It has not been sent anywhere.</strong> This app cannot submit applications; you apply on the employer’s own site.</Alert>
              <ErrorAlert error={submit.error} />
              <div className="row">
                <button onClick={() => submit.mutate()} disabled={submit.isPending}>Check package &amp; get official link</button>
                {url && <a className="btn secondary" href={url} target="_blank" rel="noopener noreferrer nofollow">Open official application page</a>}
              </div>
              {manualInfo && <Alert kind="info">{manualInfo}</Alert>}
              <h3>Already applied?</h3>
              <button className="secondary" onClick={() => setConfirmApplied(true)}>Record that I applied</button>
            </section>
          )}

          {(NEXT[a.status]?.length ?? 0) > 0 && a.status !== 'approved' && a.status !== 'ready_for_review' && (
            <section className="card"><h2 style={{ marginTop: 0 }}>Update status</h2>
              <ErrorAlert error={setStatus.error} />
              <div className="row">{NEXT[a.status].map((s) => <button key={s} className="secondary" onClick={() => setStatus.mutate({ status: s })}>{applicationStatusLabel(s)}</button>)}</div></section>
          )}

          {a.history.length > 0 && (
            <section aria-labelledby="hist-h"><h2 id="hist-h">History</h2>
              <ol>{a.history.map((h, i) => <li key={i}>{formatDate(h.at)} — {h.type.replace(/_/g, ' ')}: {h.from ? applicationStatusLabel(h.from) : 'start'} → {applicationStatusLabel(h.to)}</li>)}</ol></section>
          )}

          {confirmApplied && (
            <Modal title="Record that you applied?" onClose={() => setConfirmApplied(false)}>
              <p>Only continue if you have actually submitted this application on the employer’s site. This app cannot verify it; the record will say “reported by you”.</p>
              <ErrorAlert error={setStatus.error} />
              <div className="row end">
                <button className="secondary" onClick={() => setConfirmApplied(false)}>Cancel</button>
                <button onClick={() => setStatus.mutate({ status: 'submitted', reported: true })} disabled={setStatus.isPending}>Yes, I applied</button>
              </div>
            </Modal>
          )}
          {pendingEdit && (
            <Modal title="This will withdraw your approval" onClose={() => setPendingEdit(null)}>
              <p>You approved the current package. Changing it means you will need to review and approve again.</p>
              <div className="row end">
                <button className="secondary" onClick={() => setPendingEdit(null)}>Cancel</button>
                <button onClick={() => { pendingEdit(); setPendingEdit(null) }}>Make the change</button>
              </div>
            </Modal>
          )}
        </>
      )}
    </>
  )
}
