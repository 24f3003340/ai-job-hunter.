import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { captureToken, register, seedAccount, spaNavigate, uniqueEmail } from './helpers'

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']

async function audit(page: Page, label: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).analyze()
  const msg = r.violations.map((v) => `${v.id} (${v.impact}): ${v.help}\n    ` + v.nodes.slice(0, 3).map((n) => n.target.join(' ') + ' → ' + (n.failureSummary ?? '').split('\n').slice(1, 3).join(' ')).join('\n    '))
  expect(msg, `axe violations on ${label}`).toEqual([])
}

async function headingStructure(page: Page, label: string) {
  const levels = await page.$$eval('main h1, main h2, main h3, main h4', (hs) => hs.map((h) => Number(h.tagName[1])))
  expect(levels.filter((l) => l === 1), `${label}: exactly one h1`).toHaveLength(1)
  levels.forEach((l, i) => { if (i > 0) expect(l - levels[i - 1], `${label}: heading levels must not skip (${levels.join(',')})`).toBeLessThanOrEqual(1) })
}

async function landmarks(page: Page, label: string) {
  await expect(page.getByRole('main'), `${label}: main landmark`).toHaveCount(1)
}

for (const scheme of ['light', 'dark'] as const) {
  test(`every screen passes axe (WCAG 2.2 AA incl. contrast), headings and landmarks - ${scheme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme })
    const tok = captureToken(page)

    // public screens
    for (const p of ['/login', '/register', '/forgot-password']) {
      await page.goto(p)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await audit(page, p); await headingStructure(page, p); await landmarks(page, p)
    }
    await page.goto('/reset-password?token=not-a-real-token-123456')
    await audit(page, '/reset-password'); await headingStructure(page, '/reset-password')
    await page.goto('/verify-email?token=not-a-real-token-123456')
    await expect(page.getByRole('alert')).toBeVisible()
    await audit(page, '/verify-email (error state)')

    // authenticated screens with real data
    const email = uniqueEmail(`a11y-${scheme}`)
    await register(page, email)
    const d = await seedAccount(page, tok.get(), email)
    const routes: [string, string][] = [
      ['/', 'Dashboard'], ['/jobs', 'Jobs'], ['/jobs/new', 'Add a job'], [`/jobs/${d.job.id}`, 'NLP Engineer'], ['/profile', 'Profile'],
      ['/cv', 'CV upload'], [`/cv/${d.doc.id}`, 'Review parsed CV'], [`/resumes/${d.resume.id}`, 'Resume version 1'],
      [`/resumes/${d.flagged.id}`, 'Resume version 2'], ['/applications', 'Applications'], [`/applications/${d.app.id}`, 'Review application'], ['/settings', 'Settings'],
    ]
    for (const [route, title] of routes) {
      await spaNavigate(page, route)
      await expect(page.getByRole('heading', { level: 1, name: new RegExp(title) })).toBeVisible()
      await expect(page.getByText('Loading…')).toHaveCount(0)
      await audit(page, route); await headingStructure(page, route); await landmarks(page, route)
    }

    // CV draft with warnings expanded, and a dialog
    await spaNavigate(page, `/cv/${d.doc.id}`)
    await page.getByRole('button', { name: /Parse (this document|again)/ }).click()
    await expect(page.getByText(/Things to check/)).toBeVisible()
    await audit(page, '/cv/:id with warnings')
    await spaNavigate(page, '/settings')
    await page.getByRole('button', { name: 'Delete my account…' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await audit(page, 'delete-account dialog')
  })
}

test('keyboard focus is always visible and the tab order follows the page', async ({ page }) => {
  await page.goto('/login')
  const seen: string[] = []
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab')
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null
      if (!el || el === document.body) return null
      const cs = getComputedStyle(el)
      const label = (el as HTMLInputElement).labels?.[0]?.textContent
      return { name: (el.getAttribute('aria-label') || label || el.textContent || el.tagName).trim().slice(0, 30), outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2 }
    })
    expect(info, 'focus must land on an element').not.toBeNull()
    expect(info!.outline, `focus indicator visible on "${info!.name}"`).toBe(true)
    seen.push(info!.name)
  }
  expect(seen[0]).toBe('Skip to main content')
  expect(seen.slice(1, 4)).toEqual(['Email', 'Password', 'Log in'])  // DOM order == visual order
})

test('forms are fully operable by keyboard: register with Tab/Enter only', async ({ page }) => {
  await page.goto('/register')
  await page.keyboard.press('Tab')       // skip link
  await page.keyboard.press('Tab')       // email
  await page.keyboard.type(uniqueEmail('kbdonly'))
  await page.keyboard.press('Tab')
  await page.keyboard.type('correct-horse-battery')
  await page.keyboard.press('Enter')     // submit from the keyboard
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
})

test('errors are announced: validation summary takes focus and fields reference their messages', async ({ page }) => {
  const tok = captureToken(page)
  await register(page, uniqueEmail('errs'))
  await spaNavigate(page, '/profile')
  await page.getByRole('button', { name: 'Add education' }).click()
  await page.getByRole('button', { name: 'Save profile' }).click()
  const summary = page.getByRole('alert').filter({ hasText: 'Please fix' })
  await expect(summary).toBeFocused()
  const status = page.getByLabel('Status')
  await expect(status).toHaveAttribute('aria-invalid', 'true')
  await expect(status).toHaveAccessibleDescription(/never guessed/)
  void tok
})

for (const width of [320, 640]) {   // WCAG 1.4.10 reflow: 320px wide == 400% zoom of a 1280px window; 640px == 200%
  test(`reflow at ${width}px (zoom equivalent): no horizontal scrolling, nothing clipped`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    const tok = captureToken(page)
    const email = uniqueEmail(`zoom${width}`)
    await register(page, email)
    const d = await seedAccount(page, tok.get(), email)
    for (const route of ['/', '/jobs', `/jobs/${d.job.id}`, '/profile', '/cv', `/resumes/${d.flagged.id}`, '/applications', `/applications/${d.app.id}`, '/settings']) {
      await spaNavigate(page, route)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await expect(page.getByText('Loading…')).toHaveCount(0)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `${route} overflows at ${width}px`).toBeLessThanOrEqual(1)
    }
  })
}

test('text can be enlarged: 200% default font size keeps every control usable', async ({ page }) => {
  await register(page, uniqueEmail('font'))
  // CSSOM assignment (an injected <style> tag would, rightly, be blocked by the deployment's strict CSP)
  await page.evaluate(() => { document.documentElement.style.setProperty('font-size', '200%', 'important') })
  await spaNavigate(page, '/settings')
  await expect(page.getByRole('button', { name: 'Log out' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Delete my account…' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
})
