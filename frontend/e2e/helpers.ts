import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
import { expect, type Page } from '@playwright/test'

export const E2E_DIR = path.resolve(__dirname, '../.e2e')
export const MAIL_DIR = path.join(E2E_DIR, 'data/mail')
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
