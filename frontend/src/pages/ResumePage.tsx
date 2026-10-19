import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { profileApi, resumesApi } from '../api/endpoints'
import type { Claim, Profile, ResumeDetail } from '../api/types'
import { Alert, Badge, ErrorAlert, Loading, PageTitle } from '../components/ui'
import { resolveEvidence } from '../lib/evidence'
import { REVIEW_LABEL, formatDate } from '../lib/labels'

function ClaimCard({ resume, claim, profile }: { resume: ResumeDetail; claim: Claim; profile: Profile | undefined }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const review = useMutation({
    mutationFn: (d: 'accept' | 'reject') => resumesApi.review(resume.id, claim.id, d, note),
    onSuccess: (r) => { qc.setQueryData(['resume', resume.id], r); void qc.invalidateQueries({ queryKey: ['resumes', resume.job_id] }); void qc.invalidateQueries({ queryKey: ['applications'] }) },
  })
  const comparable = profile && profile.profile_version === resume.source_profile_version
  return (
    <li className="card" aria-label={`Statement ${claim.id}`}>
      <p className="plain" style={{ marginTop: 0 }}><strong>“{claim.text}”</strong></p>
      {claim.status === 'needs_review' && (
        <>
          <Alert kind="warn">
            <strong>Not fully supported by your profile.</strong>
            <ul>{claim.reasons.map((r) => <li key={r.code}>{r.message}</li>)}</ul>
          </Alert>
        </>
      )}
      <div><span className="muted">Evidence from your profile:</span>
        {claim.evidence.length === 0 ? <> <Badge kind="danger">none cited</Badge></> : (
          <ul>
            {claim.evidence.map((ref) => {
              const text = profile && comparable ? resolveEvidence(profile, ref) : null
              return <li key={ref}><code>{ref}</code>{text !== null ? <> — <span className="plain">{text}</span></> : <span className="muted"> — text unavailable{profile && !comparable ? ' (profile changed since this version)' : ''}</span>}</li>
            })}
          </ul>
        )}
      </div>
      {claim.status === 'needs_review' && (
        <>
          {claim.decision && <p>Your decision: <Badge kind={claim.decision === 'accept' ? 'ok' : 'danger'}>{claim.decision === 'accept' ? 'Accepted (you vouch it is true)' : 'Rejected'}</Badge></p>}
          <ErrorAlert error={review.error} />
          <div className="field">
            <label htmlFor={`note-${claim.id}`}>Note (optional)</label>
            <input id={`note-${claim.id}`} type="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="row">
            <button onClick={() => review.mutate('accept')} disabled={review.isPending}>Accept – this is true</button>
            <button className="danger" onClick={() => review.mutate('reject')} disabled={review.isPending}>Reject</button>
          </div>
          <p className="hint">Accepting means <em>you</em> confirm the statement is accurate; the system cannot verify it. Rejecting blocks this version from approval – edit your profile and generate a new version.</p>
        </>
      )}
    </li>
  )
}

export function ResumePage() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['resume', id], queryFn: () => resumesApi.get(id) })
  const profile = useQuery({ queryKey: ['profile'], queryFn: profileApi.get })
  const [dlError, setDlError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const r = q.data
  const blocked = r ? r.review_status === 'needs_review' || r.review_status === 'rejected' : false

  const dl = async (format: 'pdf' | 'docx') => {
    if (!r) return
    setBusy(true); setDlError(null)
    try { await resumesApi.download(r.id, format, blocked, r.version_number) } catch (e) { setDlError(e) } finally { setBusy(false) }
  }
  const flagged = r?.claims.filter((c) => c.status === 'needs_review') ?? []
  const supported = r?.claims.filter((c) => c.status === 'supported') ?? []
  const c = r?.content

  return (
    <>
      <PageTitle>{r ? `Resume version ${r.version_number}` : 'Resume'}</PageTitle>
      {q.isLoading && <Loading />}
      <ErrorAlert error={q.error} />
      {r && c && (
        <>
          <p><Link to={`/jobs/${r.job_id}`}>← Back to job</Link> · Created {formatDate(r.created_at)} · built from profile version {r.source_profile_version} · source: {r.generation_source}{r.provider ? ` (${r.provider})` : ''}</p>
          <Alert kind={blocked ? 'warn' : 'ok'}>
            <strong>{REVIEW_LABEL[r.review_status]}.</strong>{' '}
            {blocked ? `${r.unresolved_claims.length} statement(s) need a decision before this version can be approved or cleanly downloaded.` : 'This is a consistency check against your profile, not proof that every statement is true.'}
          </Alert>
          {r.warnings.filter((w) => w.severity !== 'info').map((w) => <Alert kind="warn" key={w.code}>{w.message}</Alert>)}
          {r.warnings.filter((w) => w.severity === 'info').length > 0 && <ul>{r.warnings.filter((w) => w.severity === 'info').map((w) => <li key={w.code}>{w.message}</li>)}</ul>}

          <section className="card" aria-labelledby="dl-h">
            <h2 id="dl-h" style={{ marginTop: 0 }}>Download</h2>
            <ErrorAlert error={dlError} />
            {blocked && <p className="muted">Unreviewed statements will be marked “[UNVERIFIED]” in a draft download; rejected statements are left out.</p>}
            <div className="row">
              <button onClick={() => void dl('pdf')} disabled={busy}>{blocked ? 'Download draft PDF' : 'Download PDF'}</button>
              <button className="secondary" onClick={() => void dl('docx')} disabled={busy}>{blocked ? 'Download draft DOCX' : 'Download DOCX'}</button>
            </div>
          </section>

          <section className="card" aria-labelledby="chg-h">
            <h2 id="chg-h" style={{ marginTop: 0 }}>What changed</h2>
            {r.change_summary.length ? <ul>{r.change_summary.map((s) => <li key={s}>{s}</li>)}</ul> : <p className="muted">Your profile content was used as-is.</p>}
          </section>

          <section className="card" aria-labelledby="prev-h">
            <h2 id="prev-h" style={{ marginTop: 0 }}>Preview (plain text)</h2>
            <p className="plain"><strong>{c.header.name}</strong> · {c.header.email} · {c.header.phone}</p>
            {c.summary && <p className="plain"><em>{c.summary.text}</em></p>}
            {c.skills.length > 0 && <><h3>Skills</h3><p>{c.skills.map((s) => s.name).join(', ')}</p></>}
            {c.experience.length > 0 && <h3>Experience</h3>}
            {c.experience.map((e) => (<div key={e.ref}><p><strong>{e.title}</strong> — {e.employer} <span className="muted">({e.start_date ?? '?'} – {e.current ? 'present' : e.end_date ?? '?'})</span></p><ul>{e.bullets.map((b) => <li key={b.id} className="plain">{b.text}</li>)}</ul></div>))}
            {c.projects.length > 0 && <h3>Projects</h3>}
            {c.projects.map((p) => (<div key={p.ref}><p><strong>{p.name}</strong> <span className="muted">{p.technologies.join(', ')}</span></p><ul>{p.bullets.map((b) => <li key={b.id} className="plain">{b.text}</li>)}</ul></div>))}
            {c.education.length > 0 && <h3>Education</h3>}
            <ul>{c.education.map((e) => <li key={e.ref}>{e.degree}, {e.institution} — <Badge kind={e.status === 'completed' ? 'ok' : 'warn'}>{e.status === 'completed' ? 'Completed' : 'In progress'}</Badge> {e.start_date ?? ''}–{e.end_date ?? ''}</li>)}</ul>
            {c.certifications.length > 0 && <><h3>Certifications</h3><ul>{c.certifications.map((x) => <li key={x.ref}>{x.name} {x.issuer && `– ${x.issuer}`} {x.date ?? ''}</li>)}</ul></>}
          </section>

          <section aria-labelledby="claims-h">
            <h2 id="claims-h">Statements and their evidence</h2>
            {flagged.length === 0 && <p>No statements were flagged.</p>}
            {flagged.length > 0 && <><h3>Need your review ({flagged.length})</h3><ul className="clean">{flagged.map((cl) => <ClaimCard key={cl.id} resume={r} claim={cl} profile={profile.data} />)}</ul></>}
            {supported.length > 0 && (
              <details>
                <summary>Consistent with your profile ({supported.length})</summary>
                <ul className="clean">{supported.map((cl) => <ClaimCard key={cl.id} resume={r} claim={cl} profile={profile.data} />)}</ul>
              </details>
            )}
          </section>
        </>
      )}
    </>
  )
}
