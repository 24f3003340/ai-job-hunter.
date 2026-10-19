import { expect, test } from './fixtures'
import { PASSWORD, captureToken, shot, latestMailToken, register, spaNavigate, uniqueEmail } from './helpers'

test('wrong password and unknown user get the same message; lockout is explained', async ({ page }) => {
  const email = uniqueEmail('lock')
  await register(page, email)
  await page.getByRole('button', { name: 'Log out' }).click()
  await shot(page, '01-login.png')
  for (const [e, n] of [[email, 1], ['nobody@example.com', 2]] as const) {
    await page.getByLabel('Email').fill(e)
    await page.getByLabel('Password').fill('wrong-password-123')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page.getByRole('alert')).toContainText('Invalid email or password')
    expect(n).toBeGreaterThan(0)
  }
  for (let i = 0; i < 4; i++) { // 5th failure for the real account locks it
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill('wrong-password-123')
    await page.getByRole('button', { name: 'Log in' }).click()
  }
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('alert')).toContainText(/too many failed attempts/i)
})

test('password reset by e-mail: single use, old password stops working', async ({ page }) => {
  const email = uniqueEmail('reset')
  await register(page, email)
  await page.getByRole('button', { name: 'Log out' }).click()
  await page.getByRole('link', { name: 'Forgot your password?' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByRole('button', { name: 'Send reset email' }).click()
  await expect(page.getByText(/if that account exists/i)).toBeVisible()
  const token = latestMailToken(email, 'Reset your password')

  await page.goto(`/reset-password?token=${token}`)
  await expect(page).not.toHaveURL(/token=/)
  await page.getByLabel('New password', { exact: true }).fill('brand-new-password-1')
  await page.getByLabel('Repeat new password').fill('brand-new-password-1')
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByText(/password changed/i)).toBeVisible()

  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid email or password')
  await page.getByLabel('Password').fill('brand-new-password-1')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  // the same link cannot be used twice
  await page.getByRole('button', { name: 'Log out' }).click()
  await page.goto(`/reset-password?token=${token}`)
  await page.getByLabel('New password', { exact: true }).fill('another-password-22')
  await page.getByLabel('Repeat new password').fill('another-password-22')
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByRole('alert')).toContainText(/invalid or expired/i)
})

test('a session revoked on the server sends the user to login with an explanation', async ({ page }) => {
  const tok = captureToken(page)
  await register(page, uniqueEmail('expire'))
  await shot(page, '02-dashboard.png')
  // revoke the session behind the UI's back (as if it expired / was logged out elsewhere)
  const r = await page.request.post('/api/v1/auth/logout', { headers: { Authorization: `Bearer ${tok.get()}` } })
  expect(r.status()).toBe(204)
  await page.getByRole('link', { name: 'Jobs', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible()
  await expect(page.getByText(/session has expired/i)).toBeVisible()
  await spaNavigate(page, '/applications')
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible() // protected pages stay protected
})

test('keyboard: skip link works and Escape closes dialogs', async ({ page }) => {
  const kbdEmail = uniqueEmail('kbd')
  await register(page, kbdEmail)
  await page.goto('/login') // fresh load: first Tab must reach the skip link
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('main')).toBeFocused()
  await page.getByLabel('Email').fill('x@example.com')
  await page.getByLabel('Password').fill('not-a-real-password')
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible()
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible() // reload dropped the in-memory session
  await page.getByLabel('Email').fill(kbdEmail)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()  // redirected back to where the user was going
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await page.getByRole('button', { name: 'Delete my account…' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Delete my account…' })).toBeFocused()
})

test('mobile viewport: pages fit the screen without horizontal scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await register(page, uniqueEmail('mobile'))
  for (const name of ['Jobs', 'Profile', 'CV', 'Applications', 'Settings']) {
    await page.getByRole('link', { name, exact: true }).click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `${name} overflows horizontally`).toBeLessThanOrEqual(1)
  }
  await shot(page, '09-mobile-settings.png', false)
})
