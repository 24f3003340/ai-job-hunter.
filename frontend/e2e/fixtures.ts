import { test as base, expect } from '@playwright/test'

/**
 * Every test fails if the page reports a CSP violation or an uncaught error (catches policy breakage on a real deployment).
 * On failure it also prints the visible page text and any failed API calls, so CI logs explain themselves
 * (trace artifacts are not always retrievable).
 */
export const test = base.extend<{ _guard: void }>({
  _guard: [async ({ page }, use, testInfo) => {
    const problems: string[] = []
    const api: string[] = []
    const log: string[] = []
    page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
    page.on('console', (m) => {
      if (m.type() === 'error' && /content security policy|refused to (apply|load|execute)/i.test(m.text())) problems.push(`csp: ${m.text()}`)
    })
    page.on('request', (r) => { if (r.url().includes('/api/')) log.push(`> ${r.method()} ${new URL(r.url()).pathname}`) })
    page.on('console', (m) => log.push(`console.${m.type()}: ${m.text().slice(0, 200)}`))
    page.on('response', (r) => { if (r.url().includes('/api/')) log.push(`< ${r.status()} ${new URL(r.url()).pathname}`) })
    page.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) api.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`) })
    page.on('requestfailed', (r) => { if (r.url().includes('/api/')) api.push(`FAILED ${r.method()} ${new URL(r.url()).pathname}: ${r.failure()?.errorText}`) })
    await use()
    if (testInfo.status !== testInfo.expectedStatus) {
      const text = await page.locator('body').innerText({ timeout: 2000 }).catch(() => '(page unavailable)')
      console.log(`--- diagnostics for "${testInfo.title}" [${testInfo.project.name}]\nurl: ${page.url()}\nAPI errors: ${JSON.stringify(api)}\nevents:\n${log.slice(-40).join('\n')}\npage text:\n${text.slice(0, 1500)}\n---`)
    }
    expect(problems, 'browser reported CSP violations or uncaught errors').toEqual([])
  }, { auto: true }],
})
export { expect }
