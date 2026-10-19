# Prioritised work before a public beta

Priorities: **P0** = blocks any public beta (security, legal, data safety); **P1** = needed for a usable beta; **P2** = soon after.
Estimates are rough single-developer days, assume the existing stack, and include tests. Nothing below is implemented unless stated.

## 1. The backend capabilities requested (decisions + plans)

### 1.1 Secure session persistence — **P1 (UX) with a P0 security constraint**
*Today:* bearer token held in JavaScript memory only; a reload logs the user out. That is the safest option but unacceptable UX.
*Options considered*
| Option | Verdict |
|---|---|
| Token in `localStorage`/`sessionStorage` | **Rejected**: readable by any XSS |
| In-memory token + silent refresh via httpOnly refresh cookie (rotating) | Works cross-origin, but two token types and refresh-rotation logic |
| **Opaque server-side session id in an httpOnly, Secure, `SameSite=Lax` cookie (`__Host-` prefix) + CSRF defence** | **Recommended**: the backend already has server-side sessions (revocable, expiring), the deployment is same-origin (Caddy), and JavaScript never sees the credential |

*Plan (≈3 days)*
1. Backend: on login/register also `Set-Cookie: __Host-session=<token>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=<ttl>`. `current_session` accepts the cookie **or** the bearer header (API clients and existing tests keep working).
2. CSRF (cookie auth only): require `X-Requested-With: jobhunter` (or a double-submit `csrf` cookie echoed in `X-CSRF-Token`) on POST/PUT/PATCH/DELETE **and** check `Origin`/`Sec-Fetch-Site` against `JOBHUNTER_CORS_ORIGINS`; bearer-header requests are exempt. Logout clears the cookie. Account deletion/password reset revoke as today.
3. Sliding idle timeout (e.g. 8 h) plus absolute lifetime (e.g. 7 d); rate-limit `/auth/me` probing.
4. Frontend: drop the in-memory token; `credentials: 'same-origin'`; call `/auth/me` on load; send the CSRF header; keep the 401 → "session expired" flow.
5. Tests: cookie flags, CSRF rejected without header / with foreign Origin, logout invalidates cookie, session survives reload (Playwright), bearer path unchanged.
*Acceptance:* reload keeps the session; a cross-site form POST cannot act as the user; no credential visible to `document.cookie` or storage.

### 1.2 Job list: pagination, totals, score sorting — **P1** (≈2 days)
*Gap:* `GET /jobs` returns a bare array (max 200), no total, no sort by score, no remote/salary/experience filters; the UI scores per row (N+1).
*Plan:* add `X-Total-Count` header (keeps the array body backward compatible) and params `sort=recent|score_desc`, `remote`, `min_salary`, `max_experience`, `status`; persist match results in a `job_matches` table keyed by `(user, job, profile_version, job_content_hash)` and recompute lazily on profile/job change; paginate with `limit/offset` (keyset later). Return `score` and `disqualified` in each row so the UI needs no extra calls.
*Acceptance:* 1,000 jobs list in < 300 ms; sorting is stable; totals correct under filters; stale scores impossible after a profile edit (test).

### 1.3 Accurate dashboard analytics — **P1** (≈1 day)
*Gap:* the dashboard counts the first 200 jobs and all applications client-side.
*Plan:* `GET /analytics/overview` returning counts by job status and application status, funnel (drafted → approved → user-reported applied → interview/offer), resume versions generated, claims flagged/accepted/rejected, per-source counts. Keep the spec's rule (FR-13): **never** present user-reported outcomes as verified results; label them separately; no causal claims about resume versions.
*Acceptance:* numbers equal direct SQL counts in tests; isolated per user.

### 1.4 Application job titles — **P1, quick win** (≈0.5 day)
`GET /applications` and `GET /applications/{id}` should include `job: {id, title, company, application_url, status}` via a join. Removes the client-side join limited to 200 jobs. Additive change; add test that foreign users never see titles.

### 1.5 Resume editing UI — **P2** (≈4 days)
Backend `POST /resumes/{id}/edit` exists. UI: per-bullet editor with an evidence picker (profile items), immediate display of the checker's reasons, "save as new version" (never edit in place), diff against the parent, and the same review gate. Needs the evidence text endpoint (§2.3) for a good picker.

### 1.5b Evidence text in resume responses — **P2** (≈0.5 day)
Expose the stored profile snapshot's cited passages per claim so the UI can show evidence for *older* versions (today it resolves only against the current profile when versions match).

### 1.6 Cover-letter generation and review — **P1** (≈5 days)
Tables exist (`cover_letters`) and the approval hash already covers a cover letter; there are **no endpoints**.
*Plan:* `POST /jobs/{id}/cover-letter` (rule-based template using only profile facts first; LLM drafting optional behind consent), `GET /cover-letters/{id}`, `GET /jobs/{id}/cover-letters`, immutable versions, the **same claim/evidence/review model as resumes** (every factual sentence cites profile evidence; unsupported ones need review), export (DOCX/PDF), include review state in the approval hash and `blockers`. UI: studio page mirroring the resume page. Never auto-attach.
*Acceptance:* unreviewed claims block approval; approval invalidated by any change; no invented employers/dates/degrees (property tests on the checker).

## 2. Other pre-beta blockers

### P0 — must be done before inviting outside users
| # | Task | Why / how |
|---|---|---|
| P0-1 | **Legal & privacy review (India DPDP Act, consumer law)**, privacy notice, terms, consent wording, retention schedule, DPA/vendor review for SMTP + LLM + hosting | CVs are personal data; consent screen text in the app is placeholder-level today |
| P0-2 | **Real malware scanning** (ClamAV profile) and a passing `tests/external/test_clamav_real.py`; decide whether unscanned mode may exist in beta (recommend: no) | Currently unverified; staging runs with an explicit override |
| P0-3 | **Real SMTP provider** + SPF/DKIM/DMARC; bounce/complaint handling; verify deliverability | Verification/reset e-mails are the only way in; only a local sink has been tested |
| P0-4 | **Scheduled, encrypted, off-site backups** + monthly `verify_restore.sh` drill; documented RPO/RTO | Scripts exist and are verified; scheduling and off-site transport are manual |
| P0-5 | **Monitoring & alerting** (uptime on `/health`, 5xx rate, disk, backup age, cert expiry, queue/Redis down) and log shipping with retention | Nothing is wired up |
| P0-6 | **Data export** (`GET /account/export`) and verified account deletion incl. backups policy | Spec FR-01; deletion exists, export does not |
| P0-7 | **Dependency/vulnerability scanning in CI** (pip-audit, npm audit, container image scan), pinned base images, Dependabot | Not present |
| P0-8 | **Abuse controls**: per-account lockout is per account (DoS-able) — add IP+account scheme, CAPTCHA/PoW on register/reset if abused | Rate limits exist; no abuse handling |
| P0-9 | **Live Anthropic test** (or decide the beta is rule-based only and hide consent UI) | Never run against the real API |

### P1 — needed for a usable beta
* §1.1 session persistence, §1.2 job list, §1.3 analytics, §1.4 titles, §1.6 cover letters.
* Change password / change e-mail while logged in (needs re-auth); list/revoke sessions.
* Job intake beyond manual entry: **only** official/authorized sources; no scraping. Start with user-submitted URLs and one public feed whose terms permit retrieval (spec FR-04). *Not implemented; connectors do not exist.*
* Purge jobs (expired reset/verify tokens, old sessions, `purge_stale_temp`, audit-log retention) — tables grow forever today.
* Admin tooling: user lookup for support without access to CV content, abuse reports, source health (spec §9).
* Load test (e.g. 50 concurrent users, 5 MB uploads) and tune workers/pool sizes; PostgreSQL connection limits.
* Human accessibility audit (screen readers NVDA/JAWS/VoiceOver; automated axe already passes) and content/UX copy review.

### P2 — after beta starts
MFA/OAuth; resume editing UI (§1.5); notifications (interview reminders, closing dates); analytics beyond counts; multi-region/HA PostgreSQL; read replicas; admin dashboards; background worker (Celery) for heavy parsing/LLM calls; Kanban view; i18n.

## 3. Explicit non-goals (unchanged)
No scraping of job boards, no automatic submission to employer sites, no CAPTCHA bypass, no inferred qualifications, no claim that a submission happened unless a verified connector (none exist) confirms it.
