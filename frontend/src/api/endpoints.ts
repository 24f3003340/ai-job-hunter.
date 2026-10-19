import { api, download } from './client'
import type * as T from './types'

export const authApi = {
  register: (email: string, password: string) => api<{ access_token: string }>('/auth/register', { method: 'POST', json: { email, password }, auth: false }),
  login: (email: string, password: string) => api<{ access_token: string }>('/auth/login', { method: 'POST', json: { email, password }, auth: false }),
  logout: () => api('/auth/logout', { method: 'POST' }),
  me: () => api<T.Me>('/auth/me'),
  verifyEmail: (token: string) => api('/auth/verify-email', { method: 'POST', json: { token }, auth: false }),
  resendVerification: () => api<{ detail: string }>('/auth/resend-verification', { method: 'POST' }),
  requestReset: (email: string) => api<{ detail: string }>('/auth/password-reset/request', { method: 'POST', json: { email }, auth: false }),
  confirmReset: (token: string, new_password: string) => api('/auth/password-reset/confirm', { method: 'POST', json: { token, new_password }, auth: false }),
  grantConsent: () => api('/account/ai-consent', { method: 'POST' }),
  revokeConsent: () => api('/account/ai-consent', { method: 'DELETE' }),
  deleteAccount: () => api('/account', { method: 'DELETE' }),
}

export const profileApi = {
  get: () => api<T.Profile>('/profile'),
  put: (p: T.ProfileData) => api<T.Profile>('/profile', { method: 'PUT', json: p }),
}

export const jobsApi = {
  list: (p: { q?: string; status?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams()
    if (p.q) qs.set('q', p.q)
    if (p.status) qs.set('status', p.status)
    qs.set('limit', String(p.limit ?? 50))
    qs.set('offset', String(p.offset ?? 0))
    return api<T.Job[]>(`/jobs?${qs}`)
  },
  get: (id: string) => api<T.Job>(`/jobs/${id}`),
  create: (j: T.JobInput) => api<T.Job>('/jobs', { method: 'POST', json: j }),
  verify: (id: string) => api<T.Job>(`/jobs/${id}/verify`, { method: 'POST' }),
  match: (id: string) => api<T.MatchReport>(`/jobs/${id}/match`),
}

export const documentsApi = {
  list: () => api<T.DocumentMeta[]>('/documents'),
  get: (id: string) => api<T.DocumentMeta>(`/documents/${id}`),
  upload: (file: File) => { const f = new FormData(); f.append('file', file); f.append('document_type', 'cv'); return api<T.DocumentMeta>('/documents/upload', { method: 'POST', form: f }) },
  parse: (id: string) => api<T.ParsePreview>(`/documents/${id}/parse`, { method: 'POST' }),
  latestParse: (id: string) => api<T.ParsePreview>(`/documents/${id}/parse`),
  confirm: (id: string, body: { parse_id: string; acknowledged_flags: string[]; profile: T.ProfileData }) =>
    api<T.Profile>(`/documents/${id}/parse/confirm`, { method: 'POST', json: body }),
  remove: (id: string) => api(`/documents/${id}`, { method: 'DELETE' }),
  downloadOriginal: (id: string, name: string) => download(`/documents/${id}/download`, name),
}

export const resumesApi = {
  list: (jobId: string) => api<T.ResumeSummary[]>(`/jobs/${jobId}/resumes`),
  generate: (jobId: string) => api<T.ResumeDetail>(`/jobs/${jobId}/resume`, { method: 'POST', json: {} }),
  get: (id: string) => api<T.ResumeDetail>(`/resumes/${id}`),
  review: (id: string, claimId: string, decision: 'accept' | 'reject', note: string) =>
    api<T.ResumeDetail>(`/resumes/${id}/claims/${claimId}/review`, { method: 'POST', json: { decision, note } }),
  download: (id: string, format: 'pdf' | 'docx', allowDraft: boolean, version: number) =>
    download(`/resumes/${id}/download?format=${format}&allow_draft=${allowDraft}`, `resume-v${version}.${format}`),
}

export const applicationsApi = {
  list: (status?: string) => api<T.Application[]>(`/applications${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  get: (id: string) => api<T.ApplicationDetail>(`/applications/${id}`),
  create: (b: { job_id: string; resume_version_id?: string | null; answers?: T.AnswerInput[] }) => api<T.Application>('/applications', { method: 'POST', json: b }),
  setAnswers: (id: string, answers: T.AnswerInput[]) => api<T.Application>(`/applications/${id}/answers`, { method: 'PUT', json: answers }),
  setResume: (id: string, resume_version_id: string) => api<T.Application>(`/applications/${id}/resume`, { method: 'PUT', json: { resume_version_id } }),
  approve: (id: string) => api<T.ApproveResult>(`/applications/${id}/approve`, { method: 'POST' }),
  submit: (id: string) => api<T.SubmitResult>(`/applications/${id}/submit`, { method: 'POST' }),
  setStatus: (id: string, status: string, opts: { note?: string; user_reported_submission?: boolean } = {}) =>
    api<T.Application>(`/applications/${id}/status`, { method: 'PATCH', json: { status, ...opts } }),
}
