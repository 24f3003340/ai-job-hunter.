import { expect, test } from './fixtures'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { E2E_DIR, captureToken, shot, latestMailToken, register, spaNavigate, uniqueEmail } from './helpers'

test.describe.configure({ mode: 'serial' })

const email = uniqueEmail('journey')
const API = '/api/v1'

test('CV → profile → job → resume → claim review → approval → honest tracking (real backend)', async ({ page }) => {
  const tok = captureToken(page)

  // ---- account + email verification ----------------------------------------------------------
  await register(page, email)
  await expect(page.getByText('Your email address is not verified yet')).toBeVisible()
  const vtoken = latestMailToken(email, 'Verify your email')
  await spaNavigate(page, `/verify-email?token=${vtoken}`)
  await expect(page.getByText('Your email address is verified')).toBeVisible()
  await expect(page).not.toHaveURL(/token=/) // token removed from the address bar
  await page.getByRole('link', { name: 'Continue' }).click()
  await expect(page.getByText('Your email address is not verified yet')).toHaveCount(0)

  // ---- CV upload → draft → warnings → explicit confirmation ----------------------------------
  await page.getByRole('link', { name: 'CV', exact: true }).click()
  await page.getByLabel(/CV file/).setInputFiles(path.join(E2E_DIR, 'cv.pdf'))
  await page.getByRole('button', { name: 'Upload' }).click()
  await expect(page.getByText(/malware scanning is not configured/i)).toBeVisible() // honest about no scanner
  await page.getByRole('link', { name: 'Review and parse it' }).click()
  await page.getByRole('button', { name: 'Parse this document' }).click()
  await expect(page.getByText(/is not part of your profile until you confirm/i)).toBeVisible()
  await expect(page.getByLabel('Full name')).toHaveValue('Riya Sharma')

  const statuses = page.getByLabel('Status')
  await expect(statuses.nth(0)).toHaveValue('in_progress')   // B.Tech: expected 2027
  await expect(statuses.nth(1)).toHaveValue('')              // B.Sc 2015-2018: NOT auto-completed
  await expect(page.getByText(/parser suggests “completed” but could not confirm it/i)).toBeVisible()
  // the injected "ignore all previous instructions" line was dropped and reported
  await expect(page.getByText(/resembling an instruction to an AI system was ignored/)).toBeVisible()
  await shot(page, '03-cv-draft.png')

  // confirming without acknowledging fails with a clear message
  await page.getByLabel(/I have checked these details/).check()
  await statuses.nth(1).selectOption('completed')
  await page.getByRole('button', { name: 'Confirm and save to profile' }).click()
  await expect(page.getByText(/Acknowledge all \d+ warnings/)).toBeVisible()
  for (const cb of await page.getByRole('checkbox', { name: /Warning/ }).all()) await cb.check()
  await page.getByRole('button', { name: 'Confirm and save to profile' }).click()
  await expect(page.getByText(/Saved to your profile \(version 2\)/)).toBeVisible()

  // ---- profile keeps in-progress vs completed ------------------------------------------------
  await page.getByRole('link', { name: 'View profile' }).click()
  await expect(page.getByLabel('Status').nth(0)).toHaveValue('in_progress')
  await expect(page.getByLabel('Status').nth(1)).toHaveValue('completed')

  // ---- add a job whose posting demands a COMPLETED degree → disqualifier is shown ------------
  await page.getByRole('link', { name: 'Jobs', exact: true }).click()
  await page.getByRole('link', { name: 'Add a job' }).click()
  await page.getByLabel('Job title').fill('NLP Engineer')
  await page.getByLabel('Employer').fill('Acme')
  await page.getByLabel('Location').fill('Jaipur')
  await page.getByLabel('Official application link').fill('https://acme.example/careers/nlp')
  await page.getByLabel('Description').fill('Build RAG systems. <img src=x onerror=alert(1)>')
  await page.getByLabel('Required skills (comma separated)').fill('Python, LangChain, Kubernetes')
  await page.getByLabel('Requires a completed degree?').selectOption('yes')
  await page.getByRole('button', { name: 'Add job' }).click()
  await expect(page.getByRole('heading', { name: /NLP Engineer/ })).toBeVisible()
  await expect(page.getByText('<img src=x onerror=alert(1)>')).toBeVisible()   // inert text, not an element
  await expect(page.locator('main img')).toHaveCount(0)
  await expect(page.getByText('Unknown – not assumed to match').first()).toBeVisible() // salary unknown
  await expect(page.getByText('Missing skills')).toBeVisible()
  await expect(page.getByText(/has not been verified/)).toBeVisible()
  await page.getByRole('button', { name: 'I checked – the listing is live' }).click()
  await expect(page.getByText('Verified active').first()).toBeVisible()
  await shot(page, '04-job-detail-match.png')
  const jobUrl = page.url()

  // ---- generate a resume (rule-based, fully evidence-backed) ---------------------------------
  await page.getByRole('button', { name: 'Generate tailored resume' }).click()
  await expect(page.getByRole('heading', { name: 'Resume version 1' })).toBeVisible()
  await expect(page.getByText('All statements consistent with your profile.')).toBeVisible()
  await expect(page.getByText('In progress').first()).toBeVisible()  // B.Tech never shown as completed
  const pdf = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download PDF' }).click()
  const pdfFile = await pdf
  expect(pdfFile.suggestedFilename()).toBe('resume-v1.pdf')
  expect(readFileSync(await pdfFile.path() as string).subarray(0, 5).toString()).toBe('%PDF-')
  const docx = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download DOCX' }).click()
  expect((await docx).suggestedFilename()).toBe('resume-v1.docx')
  await shot(page, '05-resume.png')

  // ---- a version with an unsupported claim (made via the API's edit endpoint) ----------------
  const resumeId = page.url().split('/').pop()!
  const edit = await page.request.post(`${API}/resumes/${resumeId}/edit`, {
    headers: { Authorization: `Bearer ${tok.get()}` },
    data: { summary: { text: 'Award-winning engineer', evidence: [] } },
  })
  expect(edit.status()).toBe(201)
  const flaggedId = (await edit.json()).id as string
  await spaNavigate(page, `/resumes/${flaggedId}`)
  await expect(page.getByRole('heading', { name: 'Resume version 2' })).toBeVisible()
  await expect(page.getByText('Statements need your review.')).toBeVisible()
  await expect(page.getByText('No supporting profile evidence is cited for this statement.')).toBeVisible()
  await shot(page, '06-claim-review.png')

  // clean download is refused by the backend and the UI offers only a labelled draft
  await expect(page.getByRole('button', { name: 'Download draft PDF' })).toBeVisible()

  // ---- application: unreviewed claim blocks approval ----------------------------------------
  await spaNavigate(page, new URL(jobUrl).pathname)
  await page.getByRole('button', { name: /Create draft with resume version 2/ }).click()
  await expect(page.getByRole('heading', { name: 'Review application' })).toBeVisible()
  await expect(page.getByText(/factual claims awaiting your review/).first()).toBeVisible()
  const appPath = new URL(page.url()).pathname

  // review the claim: accept (the user vouches for it)
  await spaNavigate(page, `/resumes/${flaggedId}`)
  await page.getByRole('button', { name: 'Accept – this is true' }).click()
  await expect(page.getByText('Flagged statements accepted by you.')).toBeVisible()

  // ---- answers → explicit approval ------------------------------------------------------------
  await spaNavigate(page, appPath)
  await page.getByRole('button', { name: 'Add a question' }).click()
  await page.getByLabel('Question', { exact: true }).fill('Why do you want this role?')
  await page.getByLabel('Your answer').fill('I enjoy building RAG systems.')
  await page.getByLabel('I confirm this answer is accurate').check()
  await page.getByRole('button', { name: 'Save answers' }).click()
  await expect(page.getByRole('button', { name: 'Approve this package' })).toBeDisabled()
  await page.getByLabel(/I have reviewed the job, resume, cover letter and answers/).check()
  await shot(page, '07-application-review.png')
  await page.getByRole('button', { name: 'Approve this package' }).click()
  await expect(page.locator('.badge', { hasText: 'Approved by you – not yet applied' })).toBeVisible()
  await expect(page.getByText(/It has not been sent anywhere/)).toBeVisible()

  // ---- material edit after approval withdraws the approval ----------------------------------
  await page.getByLabel('Your answer').fill('I enjoy building RAG systems and shipping them.')
  await page.getByLabel('I confirm this answer is accurate').check()
  await page.getByRole('button', { name: 'Save answers' }).click()
  await page.getByRole('button', { name: 'Make the change' }).click()
  await expect(page.getByText(/Your approval was withdrawn because the application changed/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve this package' })).toBeVisible()

  // ---- re-approve; "submit" is honest: no connector, no fake success -------------------------
  await page.getByLabel(/I have reviewed the job/).check()
  await page.getByRole('button', { name: 'Approve this package' }).click()
  await page.getByRole('button', { name: /Check package/ }).click()
  await expect(page.getByText(/No authorized connector for this source/)).toBeVisible()
  await expect(page.locator('.badge', { hasText: 'Approved by you – not yet applied' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open official application page' }).first()).toHaveAttribute('href', 'https://acme.example/careers/nlp')

  // ---- the user reports applying; tracker says so honestly ------------------------------------
  await page.getByRole('button', { name: 'Record that I applied' }).click()
  await page.getByRole('button', { name: 'Yes, I applied' }).click()
  await expect(page.locator('.badge', { hasText: 'Applied (reported by you)' })).toBeVisible()
  await page.getByRole('link', { name: 'Applications', exact: true }).first().click()
  await expect(page.getByRole('cell', { name: 'Applied (reported by you)' })).toBeVisible()
  await expect(page.getByText(/^Submitted$/)).toHaveCount(0)
  await shot(page, '08-tracker.png')

  // ---- settings: delete account really deletes -------------------------------------------------
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await page.getByRole('button', { name: 'Delete my account…' }).click()
  await page.getByLabel('Confirmation').fill('delete my account')
  await page.getByRole('button', { name: 'Permanently delete' }).click()
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('correct-horse-battery')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid email or password')
})
