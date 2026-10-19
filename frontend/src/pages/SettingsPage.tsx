import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/AuthContext'
import { session } from '../auth/session'
import { Alert, Badge, ErrorAlert, Modal, PageTitle } from '../components/ui'

export function SettingsPage() {
  const { me, signOut } = useAuth()
  const qc = useQueryClient()
  const nav = useNavigate()
  const [confirmText, setConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const resend = useMutation({ mutationFn: authApi.resendVerification })
  const consent = useMutation({
    mutationFn: (on: boolean) => (on ? authApi.grantConsent() : authApi.revokeConsent()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  })
  const del = useMutation({
    mutationFn: authApi.deleteAccount,
    onSuccess: () => { session.setFlash('Your account and all its data were deleted.'); session.clear(); nav('/login', { replace: true }) },
  })
  const phrase = 'delete my account'
  return (
    <>
      <PageTitle>Settings</PageTitle>
      <section className="card" aria-labelledby="acct-h">
        <h2 id="acct-h" style={{ marginTop: 0 }}>Account</h2>
        <p>Signed in as <strong>{me?.email}</strong>. Email: {me?.email_verified ? <Badge kind="ok">verified</Badge> : <Badge kind="warn">not verified</Badge>}</p>
        {!me?.email_verified && (<>
          <ErrorAlert error={resend.error} />
          {resend.isSuccess && <Alert kind="ok">{resend.data.detail}</Alert>}
          <button className="secondary" onClick={() => resend.mutate()} disabled={resend.isPending}>Resend verification email</button>
        </>)}
        <p className="muted">There is no change-password option while signed in yet. To change your password, log out and use “Forgot your password?”.</p>
        <button className="secondary" onClick={() => void signOut()}>Log out</button>
      </section>

      <section className="card" aria-labelledby="ai-h">
        <h2 id="ai-h" style={{ marginTop: 0 }}>AI processing consent</h2>
        <p>By default resumes are drafted locally and your data stays on this server. If the server is configured to use an external AI provider, it only does so after you consent here (your name and contact details are never sent).</p>
        <ErrorAlert error={consent.error} />
        <div className="check">
          <input id="consent" type="checkbox" checked={!!me?.ai_consent} disabled={consent.isPending} onChange={(e) => consent.mutate(e.target.checked)} />
          <label htmlFor="consent">I consent to my profile content being processed by an external AI provider</label>
        </div>
      </section>

      <section className="card" aria-labelledby="del-h">
        <h2 id="del-h" style={{ marginTop: 0 }}>Delete account</h2>
        <p>Permanently deletes your account, profile, uploaded CVs, resumes and applications. This cannot be undone. (A data export is not available yet.)</p>
        <button className="danger" onClick={() => setDeleting(true)}>Delete my account…</button>
      </section>

      {deleting && (
        <Modal title="Delete your account?" onClose={() => { setDeleting(false); setConfirmText('') }}>
          <p>This permanently removes all your data. Type <strong>{phrase}</strong> to confirm.</p>
          <ErrorAlert error={del.error} />
          <div className="field"><label htmlFor="del-confirm">Confirmation</label><input id="del-confirm" type="text" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} autoComplete="off" /></div>
          <div className="row end">
            <button className="secondary" onClick={() => { setDeleting(false); setConfirmText('') }}>Cancel</button>
            <button className="danger" disabled={confirmText.trim().toLowerCase() !== phrase || del.isPending} onClick={() => del.mutate()}>Permanently delete</button>
          </div>
        </Modal>
      )}
    </>
  )
}
