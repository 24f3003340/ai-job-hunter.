import { session } from '../auth/session'

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) || '/api/v1'

export class ApiError extends Error {
  status: number
  code?: string
  blockers: string[]
  unacknowledged: string[]
  fieldErrors: Record<string, string>
  retryAfter?: number
  network: boolean
  constructor(message: string, status: number, extra: Partial<ApiError> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.blockers = extra.blockers ?? []
    this.unacknowledged = extra.unacknowledged ?? []
    this.fieldErrors = extra.fieldErrors ?? {}
    this.code = extra.code
    this.retryAfter = extra.retryAfter
    this.network = extra.network ?? false
  }
}

const GENERIC: Record<number, string> = {
  400: 'The request was not accepted.',
  401: 'Please sign in again.',
  403: 'You are not allowed to do that.',
  404: 'That item was not found.',
  409: 'That action conflicts with the current state. Reload and try again.',
  410: 'The stored file is no longer available.',
  413: 'That file is too large.',
  415: 'That file type is not supported.',
  422: 'Some of the information was not valid.',
  429: 'Too many requests. Please wait a moment and try again.',
  502: 'An upstream service failed. Try again shortly.',
  503: 'The service is temporarily unavailable. Try again shortly.',
  504: 'An upstream service timed out. Try again shortly.',
}

/** Turn FastAPI's many `detail` shapes into one safe ApiError. Never echoes raw bodies or stack traces. */
export function toApiError(status: number, body: unknown, headers?: Headers): ApiError {
  const retryAfter = headers?.get('retry-after') ? Number(headers.get('retry-after')) || undefined : undefined
  const detail = typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined
  let message = GENERIC[status] ?? 'Something went wrong.'
  const extra: Partial<ApiError> = { retryAfter }
  if (typeof detail === 'string') {
    message = detail
  } else if (Array.isArray(detail)) {
    const fe: Record<string, string> = {}
    for (const d of detail as { loc?: unknown[]; msg?: string }[]) {
      const field = String(d.loc?.[d.loc.length - 1] ?? 'form')
      fe[field] = d.msg ?? 'Invalid value'
    }
    extra.fieldErrors = fe
    message = 'Please correct the highlighted fields.'
  } else if (detail && typeof detail === 'object') {
    const d = detail as { detail?: unknown; blockers?: unknown; code?: unknown; unacknowledged?: unknown }
    if (typeof d.detail === 'string') message = d.detail
    if (Array.isArray(d.blockers)) extra.blockers = d.blockers.map(String)
    if (Array.isArray(d.unacknowledged)) extra.unacknowledged = d.unacknowledged.map(String)
    if (typeof d.code === 'string') extra.code = d.code
  }
  return new ApiError(message, status, extra)
}

interface Options {
  method?: string
  json?: unknown
  form?: FormData
  auth?: boolean // default true; false for login/register/reset endpoints (a 401 there means bad credentials)
  signal?: AbortSignal
}

async function send(path: string, opts: Options): Promise<Response> {
  const headers: Record<string, string> = {}
  const auth = opts.auth ?? true
  if (auth && session.token) headers.Authorization = `Bearer ${session.token}`
  let body: BodyInit | undefined
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json) }
  else if (opts.form) body = opts.form
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, { method: opts.method ?? 'GET', headers, body, signal: opts.signal, credentials: 'omit' })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0, { network: true })
  }
  if (!res.ok) {
    let parsed: unknown = null
    try { parsed = await res.json() } catch { /* non-JSON error body: ignore it, never display it */ }
    if (res.status === 401 && auth && session.token) session.expire()
    throw toApiError(res.status, parsed, res.headers)
  }
  return res
}

export async function api<T = void>(path: string, opts: Options = {}): Promise<T> {
  const res = await send(path, opts)
  if (res.status === 204) return undefined as T
  try { return (await res.json()) as T } catch { throw new ApiError('The server sent an unreadable response.', res.status) }
}

/** Authenticated file download (bearer header means a plain <a href> cannot be used). */
export async function download(path: string, fallbackName: string): Promise<void> {
  const res = await send(path, {})
  const blob = await res.blob()
  const cd = res.headers.get('content-disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = name.replace(/[^\w.\- ]/g, '_')
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429 && e.retryAfter) return `${e.message} (try again in about ${e.retryAfter}s)`
    return e.message
  }
  return 'Something went wrong.'
}
