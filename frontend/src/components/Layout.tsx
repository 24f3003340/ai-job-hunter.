import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/AuthContext'
import { session } from '../auth/session'
import { Alert, ErrorAlert, Loading } from './ui'

export function RequireAuth() {
  const { authenticated } = useAuth()
  const loc = useLocation()
  if (!authenticated) {
    return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search, expired: session.wasExpired() }} />
  }
  return <Shell />
}

function VerifyBanner() {
  const { me } = useAuth()
  const [sent, setSent] = useState(false)
  const resend = useMutation({ mutationFn: authApi.resendVerification, onSuccess: () => setSent(true) })
  if (!me || me.email_verified) return null
  return (
    <Alert kind="warn">
      Your email address is not verified yet. Some actions (approving or submitting applications) may be blocked until it is.{' '}
      {sent ? 'A new verification email was requested.' : (
        <button className="link" onClick={() => resend.mutate()} disabled={resend.isPending}>Resend verification email</button>)}
      {resend.error && <ErrorAlert error={resend.error} />}
    </Alert>
  )
}

function Shell() {
  const { me, meLoading, signOut } = useAuth()
  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="app">
        <div className="bar">
          <Link className="brand" to="/">AI Job Hunter</Link>
          <nav aria-label="Main">
            <ul>
              <li><NavLink to="/" end>Dashboard</NavLink></li>
              <li><NavLink to="/jobs">Jobs</NavLink></li>
              <li><NavLink to="/profile">Profile</NavLink></li>
              <li><NavLink to="/cv">CV</NavLink></li>
              <li><NavLink to="/applications">Applications</NavLink></li>
              <li><NavLink to="/settings">Settings</NavLink></li>
            </ul>
          </nav>
          <span className="muted">{me?.email}</span>
          <button className="secondary" onClick={() => void signOut()}>Log out</button>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {meLoading ? <Loading /> : (<><VerifyBanner /><Outlet /></>)}
      </main>
    </>
  )
}

export function PublicShell() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <main id="main" tabIndex={-1} style={{ maxWidth: 460 }}><Outlet /></main>
    </>
  )
}
