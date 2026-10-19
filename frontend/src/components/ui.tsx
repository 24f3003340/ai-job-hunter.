import { useEffect, useId, useRef, type ReactNode } from 'react'
import { ApiError, errorMessage } from '../api/client'

// On a fresh page load focus stays at the top so the first Tab reaches the "Skip to main content" link; on every
// later in-app navigation focus moves to the new page heading so keyboard/screen-reader users land on the new page.
let firstPageLoad = true
export function resetFocusBehaviourForTests() { firstPageLoad = true }

export function PageTitle({ children }: { children: string }) {
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    document.title = `${children} – AI Job Hunter`
    // (cleared on a timer so React StrictMode's double-invoked dev effect behaves like production)
    if (firstPageLoad) setTimeout(() => { firstPageLoad = false }, 0)
    else ref.current?.focus()
  }, [children])
  return <h1 ref={ref} tabIndex={-1}>{children}</h1>
}

export function Alert({ kind, children, role }: { kind: 'error' | 'warn' | 'ok' | 'info'; children: ReactNode; role?: 'alert' | 'status' }) {
  return <div className={`alert ${kind}`} role={role ?? (kind === 'error' ? 'alert' : 'status')}>{children}</div>
}

/** Renders an API/network error, including backend `blockers` lists. */
export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null
  const blockers = error instanceof ApiError ? error.blockers : []
  return (
    <Alert kind="error">
      {errorMessage(error)}
      {blockers.length > 0 && <ul>{blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
    </Alert>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <p role="status" aria-live="polite" className="muted">{label}</p>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="card muted">{children}</p>
}

export function Badge({ kind, children }: { kind?: 'ok' | 'warn' | 'danger'; children: ReactNode }) {
  return <span className={`badge ${kind ?? ''}`}>{children}</span>
}

interface FieldProps {
  label: string; hint?: string; error?: string; children: (p: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => ReactNode
}
export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId()
  const hintId = `${id}-hint`, errId = `${id}-err`
  const described = [hint ? hintId : '', error ? errId : ''].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-describedby': described, 'aria-invalid': error ? true : undefined })}
      {hint && <p id={hintId} className="hint">{hint}</p>}
      {error && <p id={errId} className="err">{error}</p>}
    </div>
  )
}

export function TextField({ label, value, onChange, type = 'text', hint, error, required, autoComplete, minLength }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; hint?: string; error?: string
  required?: boolean; autoComplete?: string; minLength?: number
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(p) => <input {...p} type={type} value={value} onChange={(e) => onChange(e.target.value)} required={required}
        autoComplete={autoComplete} minLength={minLength} />}
    </Field>
  )
}

/** Accessible modal: labelled, Escape closes, focus moves in and is restored. */
export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const titleId = useId()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('input,button,select,textarea')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab' && ref.current) { // keep focus inside
        const f = [...ref.current.querySelectorAll<HTMLElement>('button,input,select,textarea,a[href]')].filter((x) => !x.hasAttribute('disabled'))
        if (!f.length) return
        const first = f[0], last = f[f.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); prev?.focus() }
  }, [onClose])
  return (
    <div className="modal-backdrop">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref}>
        <h2 id={titleId} style={{ marginTop: 0 }}>{title}</h2>
        {children}
      </div>
    </div>
  )
}
