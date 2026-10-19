# Frontend (React + TypeScript + Vite)

Personal-MVP UI for the FastAPI backend. Lives in `frontend/`. No existing frontend existed, so this is a fresh
Vite app. Stack: React 19, React Router 7, TanStack Query 5, plain CSS (no component library). Tests: Vitest +
Testing Library + MSW (mocked network), Playwright (real backend).

## How it talks to the backend (from inspection)
* Auth is a **bearer token** (`Authorization: Bearer …`) returned by `/auth/login` and `/auth/register`.
  The backend sets **no cookies** and has no CSRF mechanism (none is needed for header-token auth); CORS allows only
  the configured origin, without credentials. The client therefore sends `credentials: 'omit'`.
* **Token storage:** in a JavaScript variable only (`src/auth/session.ts`). Never `localStorage`, `sessionStorage` or
  cookies (an ESLint rule forbids them). Consequence: **a page reload logs you out.** Fixing that properly needs an
  httpOnly-cookie session on the backend (see gaps).
* Errors: FastAPI `detail` is a string, a pydantic list, or an object (`{detail, blockers, code, unacknowledged}`).
  `src/api/client.ts` normalises all three, reads `Retry-After`, never displays raw/non-JSON bodies, and turns a
  `401` on an authenticated call into "session expired" (token dropped, query cache cleared, redirect to login).
* File downloads need the bearer header, so they are fetched as blobs and saved (not plain links).

## Endpoint → screen mapping
| Screen (route) | Endpoints used |
|---|---|
| Register `/register`, Login `/login` | `POST /auth/register`, `POST /auth/login` |
| Verify email `/verify-email?token=` | `POST /auth/verify-email` (token removed from the URL immediately); banner: `GET /auth/me`, `POST /auth/resend-verification` |
| Forgot / reset password | `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm` |
| Dashboard `/` | `GET /jobs?limit=200`, `GET /applications`, `GET /profile` (counts computed client-side) |
| Jobs `/jobs` | `GET /jobs?q&status&limit&offset`, `GET /jobs/{id}/match` per row |
| Add job `/jobs/new` | `POST /jobs` |
| Job details `/jobs/:id` | `GET /jobs/{id}`, `GET /jobs/{id}/match`, `POST /jobs/{id}/verify`, `GET /jobs/{id}/resumes`, `POST /jobs/{id}/resume`, `POST /applications` |
| Profile `/profile` | `GET /profile`, `PUT /profile` |
| CV `/cv`, `/cv/:id` | `GET/POST /documents(/upload)`, `GET /documents/{id}`, `GET …/download`, `DELETE /documents/{id}`, `POST/GET /documents/{id}/parse`, `POST …/parse/confirm` |
| Resume `/resumes/:id` | `GET /resumes/{id}`, `POST /resumes/{id}/claims/{cid}/review`, `GET /resumes/{id}/download?format&allow_draft`, `GET /profile` (evidence text) |
| Applications `/applications` | `GET /applications`, `GET /jobs` (to show titles) |
| Application review `/applications/:id` | `GET /applications/{id}`, `GET /jobs/{id}`, `GET /resumes/{id}`, `GET /jobs/{id}/resumes`, `PUT …/answers`, `PUT …/resume`, `POST …/approve`, `POST …/submit`, `PATCH …/status` |
| Settings `/settings` | `GET /auth/me`, `POST/DELETE /account/ai-consent`, `POST /auth/logout`, `DELETE /account` |

Not used (backend supports, no UI yet): `POST /resumes/{id}/edit`, `GET /documents/{id}/parse` is used only to restore a draft.

## Safety decisions
* **Education status is never guessed.** The CV draft pre-selects only `in_progress` when the parser was sure; a
  `suggested: completed` is shown as a hint with the select left empty, and saving requires a choice. The profile editor
  round-trips `status` and `verified` unchanged. Resumes show "In progress" badges.
* **CV confirmation:** every `warning` flag needs a ticked acknowledgement, plus an explicit "I have checked these
  details" box; the exact acknowledged flag ids are sent to the backend, which re-checks.
* **No untrusted HTML.** CV text, job descriptions, resume text and claim text render as React text nodes (`white-space:
  pre-wrap`). `dangerouslySetInnerHTML` is lint-forbidden. Links come only from `safeHttpUrl()` (http/https; `javascript:`
  etc. are dropped) and open with `rel="noopener noreferrer nofollow"`.
* **Claims:** flagged statements show reasons and cited evidence; *Accept* is worded as "you vouch this is true", *Reject*
  blocks the version. Draft downloads are labelled and use `allow_draft=true` only while claims are unresolved.
* **Approval:** needs an explicit checkbox. Editing answers or switching resume on an *approved* application first warns;
  afterwards the UI tells the user the approval was withdrawn (the backend does the revocation) and requires a fresh approval.
* **Honest statuses:** there are no submission connectors. "Check package" never reports success; it shows the backend's
  `manual_required` message and the official link. The only way to reach "submitted" is the user pressing "Record that I
  applied" (confirmation dialog); it is labelled **"Applied (reported by you)"**. The word "Submitted" alone is never shown.
* **Build:** production build injects a strict CSP `<meta>` (`default-src 'self'`, `connect-src 'self'` + API origin).
  Send the same policy as an HTTP header in deployment (also add `frame-ancestors 'none'`).
* **Accessibility:** labelled controls with `aria-describedby`/`aria-invalid`, error summaries that take focus, live
  regions, skip link, focus moved to the page heading on in-app navigation, modal with Escape + focus trap/restore,
  tables with captions/scopes, reduced-motion and dark-mode CSS.

## Run
```
cd frontend
cp .env.example .env            # placeholders only; VITE_* values are public
npm install
npm run dev                     # http://localhost:5173 ; /api is proxied to http://127.0.0.1:8000 (same origin, no CORS)
# in another shell, the backend:  cd ../backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app
```
Production: `npm run build` → serve `dist/` behind a reverse proxy that also forwards `/api` to the backend (same origin).
To use a different origin set `VITE_API_URL=https://api.example.com/api/v1` at build time and add the site origin to the
backend's `JOBHUNTER_CORS_ORIGINS`.

## Tests and checks (all from `frontend/`)
| What | Command |
|---|---|
| Lint (ESLint + jsx-a11y + security rules) | `npm run lint` |
| Type check | `npm run typecheck` |
| Production build | `npm run build` |
| Unit/component tests (MSW-mocked network; any unmocked request fails) | `npm test` |
| End-to-end, all browsers installed locally (real FastAPI + SQLite + Vite; no external services) | `npx playwright test` (set `E2E_BROWSERS=chromium,firefox,webkit` after `npx playwright install`) |
| End-to-end against a running deployment | `E2E_EXTERNAL=1 E2E_BASE_URL=https://host E2E_MAIL_DIR=<sink dir> npx playwright test` |
| Accessibility audit only (axe WCAG 2.2 AA incl. contrast, light+dark, headings, focus, reflow 320/640 px, 200 % text) | `npx playwright test e2e/a11y.spec.ts` |

The E2E suite starts the backend itself (`e2e/backend.sh`: temp SQLite DB, file-based mail, rule-based AI, no scanner) and
uses a preinstalled Chromium if found (`PW_CHROMIUM_PATH` to override, otherwise `npx playwright install chromium`).
It needs the backend virtualenv (`backend/.venv`) with `reportlab` (already a backend dependency).

## Manual verification checklist
1. Register → banner "email not verified" → open `.eml` in `backend/var/mail/` (dev) → follow link → banner disappears.
2. Upload a PDF → "not scanned" notice appears (no ClamAV) → Parse → warnings must be ticked → statuses chosen → saved.
3. Profile shows the degree still "In progress"; reload the page → you are logged out (by design).
4. Add a job; description containing `<b>` or `<img>` shows as literal text; an invalid `javascript:` link is not clickable.
5. Generate a resume; download PDF/DOCX; open the file and check education wording.
6. Make a version with an unsupported claim (API `POST /resumes/{id}/edit`) → approval blocked until accepted.
7. Approve → edit an answer → warning dialog → approval withdrawn → re-approve → "Check package" → official link → "Record that I applied".
8. Tracker shows "Applied (reported by you)", never "Submitted".
9. Keyboard only: Tab to "Skip to main content"; open/close the delete dialog with Enter/Escape; zoom to 200% and on a 375 px viewport.
10. Screen reader pass (NVDA/VoiceOver) on login, CV confirmation and claim review — **not done in this project**.

Screenshots from the E2E run: `docs/screenshots/` (login, dashboard, CV draft with warnings, job match, resume, claim review, application review, tracker, mobile).

## Backend gaps found (not invented; documented, not worked around silently)
1. **No cookie/refresh session** → in-memory token, reload = logout. Needs httpOnly SameSite cookie (+ CSRF) or a refresh flow.
2. **No cover-letter endpoints** (create/read/list/update). Applications can carry a `cover_letter_id`, but its text cannot be shown or written.
3. **No analytics/overview endpoint** (`/analytics/overview` in the spec). Dashboard counts come from the first 200 jobs + all applications.
4. **`GET /jobs` has no total count, sort-by-score, or remote/salary/experience filters**; scores are fetched per row (N+1 calls).
5. **`GET /applications` omits job title/company**; the UI joins client-side with `/jobs` (max 200).
6. **No evidence text in resume responses** (the profile snapshot is stored but not exposed); the UI resolves evidence only against the *current* profile when its version matches.
7. No job edit/delete, application delete, change-password / change-email while logged in, session list, data export, notifications, interview/reminder endpoints.
8. No endpoint telling the client which AI provider is active, so the consent text is generic.
9. The resume **edit** endpoint exists but has no UI yet.

## Accessibility results (Phase H)
`e2e/a11y.spec.ts` runs in a real browser (so contrast is actually measured): **every screen** — public pages, dashboard, jobs, job
detail, profile, CV list and draft with warnings, both resume versions, applications, application review, settings and the delete
dialog — passes axe `wcag2a/aa`, `wcag21a/aa`, `wcag22aa` and best-practice rules in **light and dark** mode. It also asserts one `h1`
per page with no skipped heading levels, a `main` landmark, a visible focus ring on every tab stop with DOM order = visual order,
keyboard-only registration, validation-summary focus + `aria-describedby`/`aria-invalid`, no horizontal scroll at 320 px and 640 px
widths (WCAG 1.4.10 reflow ≈ 400 %/200 % zoom) and a usable settings page at 200 % font size.
The audit found and fixed one real defect: white text on the light-red *danger* button in dark mode (contrast 2.28:1).
Browser matrix: Chromium locally; **Chromium, Firefox and WebKit in CI** (see `docs/REPORT.md` for the run that proved it).

## Not verified
No screen-reader testing by a human (NVDA/JAWS/VoiceOver); automated axe cannot judge reading order meaning, link text quality or
cognitive load; no visual-regression tests; the CSP/reverse-proxy setup has been exercised on a staging-like stack and (via CI) the
compose stack, but not on a public domain with a real certificate; all backend caveats in `docs/REPORT.md` still apply.
