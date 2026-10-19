import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
import { expect, type Page } from '@playwright/test'

export const E2E_DIR = path.resolve(__dirname, '../.e2e')
export const MAIL_DIR = process.env.E2E_MAIL_DIR ?? path.join(E2E_DIR, 'data/mail')
export const SHOTS = path.resolve(__dirname, '../../docs/screenshots')
export const PASSWORD = 'correct-horse-battery'
export const uniqueEmail = (p: string) => `${p}-${Date.now()}-${Math.floor(Math.random() * 1e4)}@example.com`

/** The newest e-mail the backend wrote to its file outbox for this recipient, and the token in its link. */
export function latestMailToken(to: string, subjectIncludes: string): string {
  for (let i = 0; i < 50; i++) {
    let files: string[] = []
    try { files = readdirSync(MAIL_DIR).filter((f) => f.endsWith('.eml')) } catch { /* not created yet */ }
    const mails = files.map((f) => ({ f, t: statSync(path.join(MAIL_DIR, f)).mtimeMs, raw: readFileSync(path.join(MAIL_DIR, f), 'utf8') }))
      .filter((m) => m.raw.includes(`To: ${to}`) && m.raw.includes(subjectIncludes)).sort((a, b) => b.t - a.t)
    if (mails[0]) {
      const body = mails[0].raw.replace(/=\r?\n/g, '').replace(/=3D/g, '=')
      const m = /token=([\w-]+)/.exec(body)
      if (m) return m[1]
    }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100)
  }
  throw new Error(`no ${subjectIncludes} mail for ${to}`)
}

/** In-app (client-side) navigation: keeps the in-memory session, unlike page.goto which reloads. */
export async function spaNavigate(page: Page, url: string) {
  await page.evaluate((u) => { window.history.pushState({}, '', u); window.dispatchEvent(new PopStateEvent('popstate')) }, url)
}

/** Capture the bearer token the app sends, so tests can act on the backend "behind the UI's back". */
export function captureToken(page: Page): { get: () => string } {
  let token = ''
  page.on('request', (r) => { const a = r.headers()['authorization']; if (a?.startsWith('Bearer ')) token = a.slice(7) })
  return { get: () => token }
}

export async function register(page: Page, email: string) {
  await page.goto('/register')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
}

export async function shot(page: Page, name: string, fullPage = true) {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: path.join(SHOTS, name), fullPage })
}

/** Seed realistic data through the API (as a user would via the UI) so every screen has content to audit. */
export async function seedAccount(page: Page, token: string) {
  const H = { Authorization: `Bearer ${token}` }
  const cv = path.join(E2E_DIR, 'cv.pdf')
  const up = await page.request.post('/api/v1/documents/upload', { headers: H, multipart: { document_type: 'cv', file: { name: 'cv.pdf', mimeType: 'application/pdf', buffer: readFileSync(cv) } } })
  const doc = await up.json()
  const prev = await (await page.request.post(`/api/v1/documents/${doc.id}/parse`, { headers: H })).json()
  const strip = (x: Record<string, unknown>) => { const { confidence: _c, ...r } = x; void _c; return r }
  await page.request.post(`/api/v1/documents/${doc.id}/parse/confirm`, { headers: H, data: {
    parse_id: prev.parse_id, acknowledged_flags: prev.flags.map((f: { id: string }) => f.id),
    profile: { full_name: prev.parsed.full_name, phone: prev.parsed.phone,
      education: prev.parsed.education.map((e: Record<string, string>) => ({ degree: e.degree, institution: e.institution, start_date: e.start_date, end_date: e.end_date, status: e.status ?? 'completed' })),
      experience: prev.parsed.experience.map(strip), projects: prev.parsed.projects.map(strip), skills: prev.parsed.skills, certifications: prev.parsed.certifications } } })
  const job = await (await page.request.post('/api/v1/jobs', { headers: H, data: { title: 'NLP Engineer', company: 'Acme', location: 'Jaipur', application_url: 'https://acme.example/apply', required_skills: ['Python', 'Kubernetes'], requires_degree_completed: true, description: 'Build RAG systems.' } })).json()
  const resume = await (await page.request.post(`/api/v1/jobs/${job.id}/resume`, { headers: H, data: {} })).json()
  const flagged = await (await page.request.post(`/api/v1/resumes/${resume.id}/edit`, { headers: H, data: { summary: { text: 'Award-winning engineer', evidence: [] } } })).json()
  const app = await (await page.request.post('/api/v1/applications', { headers: H, data: { job_id: job.id, resume_version_id: resume.id, answers: [{ question: 'Why this role?', answer: 'I enjoy RAG.', user_confirmed: true }] } })).json()
  return { doc, job, resume, flagged, app }
}
