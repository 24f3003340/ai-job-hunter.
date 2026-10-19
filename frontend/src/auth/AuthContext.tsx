import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react'
import { authApi } from '../api/endpoints'
import type { Me } from '../api/types'
import { session } from './session'

interface Ctx {
  authenticated: boolean
  me: Me | undefined
  meLoading: boolean
  signIn: (token: string) => void
  signOut: () => Promise<void>
}
const AuthCtx = createContext<Ctx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const token = useSyncExternalStore(session.subscribe, () => session.token)
  const meQuery = useQuery({ queryKey: ['me'], queryFn: authApi.me, enabled: !!token, retry: false })

  // Whenever the session disappears (logout, expiry), drop every cached server response so nothing leaks to the next user.
  useEffect(() => { if (!token) qc.clear() }, [token, qc])

  const signIn = useCallback((t: string) => { qc.clear(); session.set(t) }, [qc])
  const signOut = useCallback(async () => {
    try { await authApi.logout() } catch { /* the token is dropped locally either way */ }
    session.clear()
  }, [])

  const value = useMemo<Ctx>(() => ({
    authenticated: !!token, me: meQuery.data, meLoading: !!token && meQuery.isLoading, signIn, signOut,
  }), [token, meQuery.data, meQuery.isLoading, signIn, signOut])
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}

export function useAuth(): Ctx {
  const c = useContext(AuthCtx)
  if (!c) throw new Error('useAuth outside AuthProvider')
  return c
}
