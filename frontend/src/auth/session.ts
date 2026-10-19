// The session token lives ONLY in this module's memory. It is never written to localStorage/sessionStorage/cookies,
// so XSS cannot read it from storage and it vanishes on reload. (A future httpOnly-cookie session would let the
// session survive reloads; the backend does not offer that yet - see docs/FRONTEND.md.)
let token: string | null = null
const listeners = new Set<() => void>()
let expiredReason = false
let flash: string | null = null // one-shot, in-memory message for the next login screen

export const session = {
  get token() { return token },
  set(value: string) { token = value; expiredReason = false; listeners.forEach((l) => l()) },
  clear() { token = null; listeners.forEach((l) => l()) },
  /** A request came back 401 while we held a token. */
  expire() { if (token) { token = null; expiredReason = true; listeners.forEach((l) => l()) } },
  wasExpired() { return expiredReason },
  setFlash(m: string) { flash = m },
  takeFlash() { const m = flash; flash = null; return m },
  clearExpiredFlag() { expiredReason = false },
  subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn) } },
}
