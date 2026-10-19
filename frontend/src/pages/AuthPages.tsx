import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/AuthContext'
import { session } from '../auth/session'
import { Alert, ErrorAlert, PageTitle, TextField } from '../components/ui'

export function LoginPage() {
  const { signIn, authenticated } = useAuth()
  const loc = useLocation()
  const state = loc.state as { from?: string; expired?: boolean; notice?: string } | null
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const expired = !!state?.expired || session.wasExpired()
  const [flash] = useState(() => session.takeFlash())
  const m = useMutation({
    mutationFn: () => authApi.login(email.trim(), password),
    onSuccess: (r) => signIn(r.access_token),
  })
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate() }
  // Once signed in, go back to where the user was heading (a single place decides the redirect, so it cannot race).
  if (authenticated) return <Navigate to={state?.from && state.from !== '/login' ? state.from : '/'} replace />
  return (
    <>
      <PageTitle>Log in</PageTitle>
      {expired && <Alert kind="warn">Your session has expired or was signed out. Please log in again.</Alert>}
      {(state?.notice ?? flash) && <Alert kind="ok">{state?.notice ?? flash}</Alert>}
      <form onSubmit={submit} noValidate={false} aria-label="Log in">
        <ErrorAlert error={m.error} />
        <TextField label="Email" type="email" value={email} onChange={setEmail} required autoComplete="email" />
        <TextField label="Password" type="password" value={password} onChange={setPassword} required autoComplete="current-password" />
        <button type="submit" disabled={m.isPending}>{m.isPending ? 'Logging in…' : 'Log in'}</button>
      </form>
      <p><Link to="/forgot-password">Forgot your password?</Link></p>
      <p>No account? <Link to="/register">Create one</Link></p>
    </>
  )
}

export function RegisterPage() {
  const { signIn, authenticated } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState(false)
  const tooShort = password.length < 10
  const m = useMutation({
    mutationFn: () => authApi.register(email.trim(), password),
    onSuccess: (r) => signIn(r.access_token),
  })
  const submit = (e: FormEvent) => { e.preventDefault(); setTouched(true); if (!tooShort) m.mutate() }
  if (authenticated) return <Navigate to="/" replace />
  const fe = m.error instanceof ApiError ? m.error.fieldErrors : {}
  return (
    <>
      <PageTitle>Create your account</PageTitle>
      <form onSubmit={submit} aria-label="Create account">
        <ErrorAlert error={m.error} />
        <TextField label="Email" type="email" value={email} onChange={setEmail} required autoComplete="email" error={fe.email} />
        <TextField label="Password" type="password" value={password} onChange={setPassword} required autoComplete="new-password"
          hint="At least 10 characters." error={touched && tooShort ? 'Password must be at least 10 characters.' : fe.password} />
        <button type="submit" disabled={m.isPending}>{m.isPending ? 'Creating…' : 'Create account'}</button>
      </form>
      <p>Already registered? <Link to="/login">Log in</Link></p>
    </>
  )
}

const attempted = new Set<string>() // StrictMode runs effects twice; the token is single-use, so only ever send it once

export function VerifyEmailPage() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [token] = useState(() => params.get('token') ?? '')
  const [state, setState] = useState<'idle' | 'working' | 'ok' | 'error'>(token ? 'working' : 'error')
  const [err, setErr] = useState<unknown>(token ? null : new ApiError('This link is missing its token.', 400))
  useEffect(() => {
    if (!token) return
    nav('/verify-email', { replace: true }) // keep the token out of history / Referer
    if (attempted.has(token)) return
    attempted.add(token)
    authApi.verifyEmail(token).then(async () => {
      // an in-flight (pre-verification) account request would otherwise be reused by the refetch and land stale
      await qc.cancelQueries({ queryKey: ['me'] })
      await qc.invalidateQueries({ queryKey: ['me'] })
      setState('ok')
    }, (e) => { setErr(e); setState('error') })
  }, [token, nav, qc])
  return (
    <>
      <PageTitle>Verify your email</PageTitle>
      {state === 'working' && <p role="status">Verifying…</p>}
      {state === 'ok' && <Alert kind="ok">Your email address is verified. <Link to="/">Continue</Link></Alert>}
      {state === 'error' && (<><ErrorAlert error={err} /><p>The link may have expired or already been used. Log in and use “Resend verification email”.</p><p><Link to="/login">Log in</Link></p></>)}
    </>
  )
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const m = useMutation({ mutationFn: () => authApi.requestReset(email.trim()) })
  return (
    <>
      <PageTitle>Reset your password</PageTitle>
      {m.isSuccess ? (
        <Alert kind="ok">If that account exists, a reset email has been sent. The link expires in 30 minutes and works once.</Alert>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); m.mutate() }} aria-label="Request password reset">
          <ErrorAlert error={m.error} />
          <TextField label="Email" type="email" value={email} onChange={setEmail} required autoComplete="email" />
          <button type="submit" disabled={m.isPending}>{m.isPending ? 'Sending…' : 'Send reset email'}</button>
        </form>
      )}
      <p><Link to="/login">Back to log in</Link></p>
    </>
  )
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [token] = useState(() => params.get('token') ?? '')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [touched, setTouched] = useState(false)
  useEffect(() => { if (token) nav('/reset-password', { replace: true }) }, [token, nav])
  const m = useMutation({
    mutationFn: () => authApi.confirmReset(token, pw),
    onSuccess: () => nav('/login', { replace: true, state: { notice: 'Password changed. Log in with your new password.' } }),
  })
  const short = pw.length < 10, mismatch = pw !== pw2
  if (!token && !m.isSuccess) return (<><PageTitle>Choose a new password</PageTitle><Alert kind="error">This reset link is missing its token. <Link to="/forgot-password">Request a new one</Link>.</Alert></>)
  return (
    <>
      <PageTitle>Choose a new password</PageTitle>
      <form onSubmit={(e) => { e.preventDefault(); setTouched(true); if (!short && !mismatch) m.mutate() }} aria-label="Set new password">
        <ErrorAlert error={m.error} />
        <TextField label="New password" type="password" value={pw} onChange={setPw} required autoComplete="new-password"
          hint="At least 10 characters." error={touched && short ? 'Password must be at least 10 characters.' : undefined} />
        <TextField label="Repeat new password" type="password" value={pw2} onChange={setPw2} required autoComplete="new-password"
          error={touched && mismatch ? 'Passwords do not match.' : undefined} />
        <button type="submit" disabled={m.isPending}>{m.isPending ? 'Saving…' : 'Change password'}</button>
      </form>
      <p className="muted">Changing your password signs you out everywhere.</p>
    </>
  )
}
