import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { documentsApi } from '../api/endpoints'
import type { DocumentMeta, ParsePreview, ProfileData } from '../api/types'
import { ProfileForm, toDraft } from '../components/ProfileForm'
import { Alert, Badge, Empty, ErrorAlert, Field, Loading, Modal, PageTitle } from '../components/ui'
import { formatDate } from '../lib/labels'

function ScanBadge({ s }: { s: string }) {
  if (s === 'clean') return <Badge kind="ok">Malware scan: clean</Badge>
  if (s === 'not_configured') return <Badge kind="warn">Not scanned for malware</Badge>
  return <Badge kind="danger">Scan status: {s}</Badge>
}

export function CvListPage() {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [toDelete, setToDelete] = useState<DocumentMeta | null>(null)
  const q = useQuery({ queryKey: ['documents'], queryFn: documentsApi.list })
  const upload = useMutation({
    mutationFn: (f: File) => documentsApi.upload(f),
    onSuccess: () => { setFile(null); void qc.invalidateQueries({ queryKey: ['documents'] }) },
  })
  const remove = useMutation({
    mutationFn: (id: string) => documentsApi.remove(id),
    onSuccess: () => { setToDelete(null); void qc.invalidateQueries({ queryKey: ['documents'] }) },
  })
  const [dlError, setDlError] = useState<unknown>(null)

  const pick = (f: File | null) => {
    setFileError('')
    if (f && !/\.(pdf|docx)$/i.test(f.name)) { setFileError('Choose a PDF or DOCX file.'); setFile(null); return }
    setFile(f)
  }
  return (
    <>
      <PageTitle>CV upload</PageTitle>
      <p>Upload a text-based PDF or DOCX. Your original file is stored unchanged. Nothing from it becomes part of your profile until you review and confirm it.</p>
      <form className="card" onSubmit={(e) => { e.preventDefault(); if (!file) { setFileError('Choose a file first.'); return } upload.mutate(file) }} aria-label="Upload CV">
        <ErrorAlert error={upload.error} />
        {upload.isSuccess && upload.data && (
          <Alert kind="ok">
            Uploaded {upload.data.filename}. {upload.data.scan_status === 'not_configured' && 'Note: malware scanning is not configured on this server, so this file was not scanned. '}
            <Link to={`/cv/${upload.data.id}`}>Review and parse it</Link>.
          </Alert>
        )}
        <Field label="CV file (PDF or DOCX)" error={fileError} hint="Scanned/image-only PDFs cannot be read; OCR is not supported.">
          {(p) => <input {...p} type="file" accept=".pdf,.docx" onChange={(e) => pick(e.target.files?.[0] ?? null)} />}
        </Field>
        <button type="submit" disabled={upload.isPending}>{upload.isPending ? 'Uploading…' : 'Upload'}</button>
      </form>

      <h2>Your documents</h2>
      {q.isLoading && <Loading />}
      <ErrorAlert error={q.error} />
      <ErrorAlert error={dlError} />
      {q.data?.length === 0 && <Empty>No CV uploaded yet.</Empty>}
      <ul className="clean">
        {q.data?.map((d) => (
          <li key={d.id}>
            <div className="row">
              <strong>{d.filename}</strong> <span className="muted">{formatDate(d.created_at)} · {(d.size_bytes / 1024).toFixed(0)} KB</span>
              <ScanBadge s={d.scan_status} /> <Badge>{d.parsing_status}</Badge>
            </div>
            <div className="row">
              <Link className="btn" to={`/cv/${d.id}`}>Review &amp; parse</Link>
              <button className="secondary" onClick={() => documentsApi.downloadOriginal(d.id, d.filename).then(() => setDlError(null), setDlError)}>Download original</button>
              <button className="secondary" onClick={() => setToDelete(d)}>Delete</button>
            </div>
          </li>
        ))}
      </ul>
      {toDelete && (
        <Modal title="Delete this document?" onClose={() => setToDelete(null)}>
          <p>This permanently deletes {toDelete.filename} and its parsing drafts. Your profile and existing resumes are not changed.</p>
          <ErrorAlert error={remove.error} />
          <div className="row end">
            <button className="secondary" onClick={() => setToDelete(null)}>Cancel</button>
            <button className="danger" onClick={() => remove.mutate(toDelete.id)} disabled={remove.isPending}>Delete document</button>
          </div>
        </Modal>
      )}
    </>
  )
}

function draftFromPreview(p: ParsePreview) {
  const c = p.parsed
  return toDraft({
    full_name: c.full_name, phone: c.phone,
    // status is exactly what the parser was sure of (in_progress) or null. A "suggested" status is only a hint.
    education: c.education.map((e) => ({
      degree: e.degree, institution: e.institution, start_date: e.start_date, end_date: e.end_date, verified: false,
      status: e.status,
      hint: e.status ? undefined : e.suggested_status
        ? `The parser suggests “${e.suggested_status === 'completed' ? 'completed' : 'in progress'}” but could not confirm it. Please choose.`
        : 'The parser could not tell. Please choose.',
    })),
    experience: c.experience.map(({ confidence: _c, ...r }) => { void _c; return r }),
    projects: c.projects.map(({ confidence: _c, ...r }) => { void _c; return r }),
    skills: c.skills, certifications: c.certifications,
  })
}

export function CvDetailPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const doc = useQuery({ queryKey: ['document', id], queryFn: () => documentsApi.get(id) })
  const latest = useQuery({
    queryKey: ['parse', id], retry: false,
    queryFn: async () => { try { return await documentsApi.latestParse(id) } catch (e) { if (e instanceof ApiError && e.status === 404) return null; throw e } },
  })
  const parse = useMutation({ mutationFn: () => documentsApi.parse(id), onSuccess: (p) => { qc.setQueryData(['parse', id], p); setAcks({}); setOk(false); void qc.invalidateQueries({ queryKey: ['documents'] }) } })
  const [acks, setAcks] = useState<Record<string, boolean>>({})
  const [understood, setOk] = useState(false)
  const [gateError, setGateError] = useState('')
  const confirm = useMutation({
    mutationFn: (b: { preview: ParsePreview; profile: ProfileData }) =>
      documentsApi.confirm(id, { parse_id: b.preview.parse_id, acknowledged_flags: Object.keys(acks).filter((k) => acks[k]), profile: b.profile }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['profile'] }); void qc.invalidateQueries({ queryKey: ['parse', id] }) },
  })
  const preview = parse.data ?? latest.data ?? null
  const warnings = preview?.flags.filter((f) => f.severity === 'warning') ?? []
  const infos = preview?.flags.filter((f) => f.severity === 'info') ?? []
  const unreadable = parse.error instanceof ApiError && parse.error.status === 422

  const onSubmit = (profile: ProfileData) => {
    if (!preview) return
    const missing = warnings.filter((w) => !acks[w.id])
    if (missing.length) { setGateError(`Acknowledge all ${warnings.length} warnings before confirming (${missing.length} left).`); return }
    if (!understood) { setGateError('Tick the box to confirm you have checked the details above.'); return }
    setGateError('')
    confirm.mutate({ preview, profile })
  }

  return (
    <>
      <PageTitle>Review parsed CV</PageTitle>
      {doc.isLoading && <Loading />}
      <ErrorAlert error={doc.error} />
      {doc.data && <p><strong>{doc.data.filename}</strong> <ScanBadge s={doc.data.scan_status} /></p>}
      <div className="row">
        <button onClick={() => parse.mutate()} disabled={parse.isPending}>{parse.isPending ? 'Parsing…' : preview ? 'Parse again' : 'Parse this document'}</button>
        <Link to="/cv">Back to documents</Link>
      </div>
      <ErrorAlert error={parse.error} />
      {unreadable && <Alert kind="info">You can fill in your details manually on the <Link to="/profile">Profile</Link> page instead.</Alert>}
      {latest.isLoading && <Loading />}
      <ErrorAlert error={latest.error} />

      {confirm.isSuccess ? (
        <Alert kind="ok">Saved to your profile (version {confirm.data.profile_version}). <Link to="/profile">View profile</Link> · <Link to="/jobs">Find jobs</Link></Alert>
      ) : preview && (
        <>
          <Alert kind="warn">This is an automatic draft and may contain mistakes. It is <strong>not</strong> part of your profile until you confirm it below.</Alert>
          {preview.flags.length > 0 && (
            <section aria-labelledby="flags-h" className="card">
              <h2 id="flags-h" style={{ marginTop: 0 }}>Things to check</h2>
              {warnings.length > 0 && <p>Tick each warning once you have checked it.</p>}
              {warnings.map((f) => (
                <div className="check" key={f.id}>
                  <input id={`ack-${f.id}`} type="checkbox" checked={!!acks[f.id]} onChange={(e) => setAcks({ ...acks, [f.id]: e.target.checked })} />
                  <label htmlFor={`ack-${f.id}`}><Badge kind="warn">Warning</Badge> {f.message} <span className="muted">({f.path})</span></label>
                </div>
              ))}
              {infos.length > 0 && <ul>{infos.map((f) => <li key={f.id}><Badge>Note</Badge> {f.message}</li>)}</ul>}
            </section>
          )}
          <ErrorAlert error={confirm.error} />
          {gateError && <Alert kind="error">{gateError}</Alert>}
          <ProfileForm key={preview.parse_id} initial={draftFromPreview(preview)} onSubmit={onSubmit} busy={confirm.isPending}
            submitLabel="Confirm and save to profile">
            <div className="check">
              <input id="understood" type="checkbox" checked={understood} onChange={(e) => setOk(e.target.checked)} />
              <label htmlFor="understood">I have checked these details. Saving replaces the education, experience, projects, skills and certifications in my profile with what is shown here.</label>
            </div>
          </ProfileForm>
        </>
      )}
    </>
  )
}
