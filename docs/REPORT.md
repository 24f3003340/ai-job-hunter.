# Phase 2 report

Baseline before changes: 20 passed. Final: **136 passed, 0 failed** (`pytest -q`, ~19 s). The original 20 tests
are unchanged and pass.

## Completed and tested
| Area | Evidence |
|---|---|
| Alembic: baseline (0001) + phase-2 (0002) | fresh `upgrade head` has zero drift from models; upgrade from 0001 with seeded data preserves rows and backfills `version_number`; downgrade works (`test_migrations.py`). Also smoke-run on a migrated SQLite DB |
| Rate limiting (global, auth, upload, generation) | `test_security_flows.py`, `test_documents.py`, `test_resumes.py` |
| Password reset (hashed, 30 min, single use, voids older tokens, revokes sessions, throttled, uniform response) | 8 tests |
| E-mail verification (expiring, single use, resend cooldown + hourly cap, gate on approve/submit) | 4 tests |
| Audit events for register/login/lockout/reset/verify/consent/upload/parse/confirm/resume/review/download/approve | asserted for reset + lockout; others written in code |
| Production config validation | 10 tests |
| PDF/DOCX upload: content sniffing, extension match, size/page limits, PDF active content, encrypted PDF, DOCX macros, zip bombs, path-safe names, private 0600 storage, temp cleanup | `test_documents.py` |
| Malware scanning via ClamAV `INSTREAM` | tested against a fake clamd socket (clean / FOUND / unreachable / required-but-missing) |
| CV parsing → draft → flags → user confirmation | education, skills, experience, projects, certifications, dates; scanned PDF and parser-crash handling; injection lines dropped and flagged |
| Education status never auto-completed | parser unit tests + API tests |
| Resume generation, immutable versions, history, change summary, warnings | `test_resumes.py` |
| Claim traceability + review workflow; PDF/DOCX export | `test_resumes.py` |
| External provider path (consent, data minimisation, bad output → 502) | mocked `httpx` transport |
| Application integration, approval-hash invalidation, no fake submission | `test_application_resume.py` |

A real bug was found by the tests and fixed: PDF bullet glyphs (control / private-use characters) were stripped, turning
bullets into headings.

## Not implemented
* OCR for scanned PDFs (they are rejected with a clear message).
* LLM-assisted CV parsing (parsing is rule-based; accuracy depends on CV layout and English headings).
* Stored export files / `documents` rows for generated PDFs (exports are rendered on demand).
* Cover-letter and screening-answer generation; the edit endpoint takes structured claims, not a rich editor.
* SMTP delivery is implemented but untested against a real server. Object storage / signed URLs (local disk only).
* Redis-backed rate limiting; a periodic job for `purge_stale_temp` (function exists).
* Frontend, browser automation, submission connectors (deliberately out of scope).

## Known limitations
* **Traceability is heuristic.** It checks cited-evidence existence, numbers, named terms, seniority wording,
  degree-completion wording and word overlap. It cannot detect a paraphrase that is subtly false. "Accept" means the user
  attests the claim; the system does not verify it.
* The real Anthropic call is implemented but has **never been run against the live API** (no key/network in tests).
* Migrations were exercised on SQLite only; PostgreSQL was not available in this environment.
* PDF active-content detection is a byte scan; content hidden in compressed object streams may not be caught.
  ClamAV is the intended control and is **not configured by default** (`scan_status: not_configured`).
* Hidden/white-on-white text in a PDF is extracted like visible text; the user sees all parsed content in the preview.
* In-process rate limiter is per worker and resets on restart. Login lockout is per account (can be abused to lock a
  victim out; reset-by-email clears it).
* Salary currency is assumed INR; email-verification gating is off by default in development.
* Job-level duplicate detection and matching from Phase 1 are unchanged.


---

# Phase F report - real-environment validation

Baseline before changes: 136 passed (SQLite). After: **181 unit tests** (136 original, unchanged, + 45 new) pass on SQLite
**and** on PostgreSQL 16, **25 integration tests** pass, 5 opt-in external tests are written and skipped.

## Environment actually used
PostgreSQL 16.15 and Redis 7.0.15 as native local processes (`scripts/dev_services.sh`), aiosmtpd 1.4.6 as the SMTP server.
**No Docker daemon, no ClamAV, no Anthropic key, no internet SMTP** were available.

## Verified (observed passing here)
| Claim | How |
|---|---|
| Alembic builds the full schema on an empty PostgreSQL DB with zero model drift, native UUID/timestamptz types | `integration/test_postgres.py` |
| 0001 -> 0002 upgrade on PostgreSQL preserves seeded data, backfills `version_number`, enforces the new unique constraint, downgrades and re-upgrades | same |
| The entire original + new unit suite passes on PostgreSQL (register/login, reset, verification, upload/confirm, generation/versioning, export, approval invalidation, deletion) | `JOBHUNTER_TEST_DATABASE_URL=... pytest` |
| Full journey + account deletion leaves no orphan rows in 13 tables and removes stored files | `test_full_user_journey_and_account_deletion_cascades` |
| Concurrency on PostgreSQL: 8 simultaneous duplicate registrations -> exactly one 201, others 409; 8 simultaneous uses of a reset token -> exactly one succeeds | same file |
| SMTP over STARTTLS and implicit TLS with AUTH delivers verification/reset mail; the links work once; wrong password / untrusted cert / wrong hostname / no-STARTTLS server abort **before credentials are sent** and deliver nothing; throttle caps real mail volume; expired and superseded tokens rejected; SMTP outage does not break signup and leaks no token | `integration/test_smtp.py` (+ mocked `test_mailer.py`) |
| No log line contains tokens, bodies, addresses, API key or SMTP password | caplog assertions with canary values |
| Anthropic provider (HTTP mocked): retries 429/5xx with capped backoff; maps timeouts/429/5xx/401/400/non-JSON/truncated/bad-schema to 504/503/502 with no version created and no response body or key echoed; key only in header; outbound body has no name/e-mail/phone (also redacted inside free text); never constructed without a key; consent revocation blocks it | `test_ai_provider_hardening.py` |
| Redis limiter is atomic (40 threads -> exactly 10 allowed), shared across 4 OS processes (40 attempts -> exactly 15) and across **3 real uvicorn workers (30 requests -> exactly 10 allowed, 20 x 429)**; the in-process limiter let >10 through in the same harness | `integration/test_redis_ratelimit.py` |
| Rate-limit failure policy: with Redis unreachable critical endpoints return 503 (never silently allowed), "local" mode and non-critical scopes still enforce per process, breaker limits retries | `test_ratelimit_backends.py` |
| Production fails closed for unscanned uploads / scanner outage; explicit override is honoured and reported as `not_configured` | `test_ratelimit_backends.py` |

## Defects found and fixed during validation
1. **PostgreSQL-only 500**: a NUL (U+0000) in any text field crashed with `DataError` (SQLite accepts it). Now a 422.
2. **STARTTLS did not verify certificates** (`smtplib.starttls()` with no context). Now verifies chain + hostname.
3. **Dev "console" mailer logged raw token links**; and send errors could abort signup. Console logs metadata only, a `file`
   backend was added, and mail is sent in a background task after commit (also removes a timing signal for account existence).
4. A real SMTP server answered a rejected password with "AUTH not supported"; the mailer now treats that as permanent (no retry).
5. Anthropic errors had no retry/limit handling and the key was a plain `str`; now `SecretStr` with the policy above.
6. Rate limiter was per process only; added Redis backend + fail policy + `/health/ready`.

## Behaviour changes (documented, intended)
* `JOBHUNTER_ENV=production` additionally requires a Redis limiter (or an explicit single-worker override) and TLS SMTP.
  Two config tests were updated to include the new required settings; no assertion was weakened and rejection cases were added.
* Default dev mail backend is `file` instead of `console`.

## NOT verified (do not treat as working)
* **Real ClamAV**: protocol code is tested only against a fake clamd. `tests/external/test_clamav_real.py` (EICAR) exists but has never run.
* **Live Anthropic API**: never called. Request/response shapes follow the public Messages API from knowledge, not from a live call.
  `tests/external/test_anthropic_live.py` exists, opt-in, billable.
* **Docker Compose file** and **GitHub Actions workflow**: written, YAML-parsed, never executed.
* **A real mail provider / Mailpit**: only a local aiosmtpd was used; deliverability (SPF/DKIM/DMARC, spam filtering) unknown.
* Redis with auth/TLS (`rediss://`), Sentinel/Cluster, eviction; PostgreSQL other than 16.15 local, managed PG, connection limits.
* Load/performance, backups, monitoring, dependency vulnerability scan, legal/privacy review.

## Production readiness
**Not established.** The checks above passed in a local stand-in environment; the unverified list is the work remaining
before a real deployment. See `docs/SECURITY.md`.

---

# Phase H report — deployment readiness and personal pilot

**Verdict: staging setup delivered and verified in a staging-LIKE environment and (see CI table) on GitHub Actions; NOT production-ready.**
Blockers are listed in `docs/BETA_ROADMAP.md` (P0).

## 1. GitHub Actions — what actually happened
| Fact | Detail |
|---|---|
| The workflow had **already run and failed** (4 runs) | Root cause: `pip install -e '.[dev,integration]'` → *"Multiple top-level packages discovered: app, migrations"*. A local virtualenv had hidden it; it also broke the README install command |
| Fix | `[tool.setuptools.packages.find] include = ["app*"]`; verified in a brand-new virtualenv (196 tests pass from a clean install) |
| Jobs now in `.github/workflows/ci.yml` | `backend-unit`, `backend-integration` (PostgreSQL 16 + Redis 7 service containers), `frontend` (lint, typecheck, build, Vitest), `e2e` (matrix **chromium / firefox / webkit**), `staging-compose` (boots the real Docker Compose stack) |
| First run with the fix (run 5, commit 0a94d00) | **backend-unit ✓, backend-integration ✓, frontend ✓, e2e firefox ✓, e2e webkit ✓, e2e chromium ✗** (one test, password-reset, did not see its success message; passed 8/8 locally; not reproduced). The harness now prints page text and failed API calls into the log on failure so a recurrence explains itself |
| Run 18 (commit 2493c8e) | Compose stack passed the HTTPS smoke test (33/33 steps) and 13/14 browser tests; the Caddy readiness hiding was not yet effective in that run's logs, WebKit `/cv` overflowed by 56px at 320px, Chromium reset test failed (native `required` validation blocked a submit before the value was in the field) |
| **Run 19 (commit 44e0f6d, `workflow_dispatch`)** | **All 7 jobs green, evidence read from the job logs:** backend-unit 196 passed; backend-integration 25 passed (PostgreSQL 16 + Redis 7 service containers); frontend 93 Vitest tests passed; e2e chromium 14/14, firefox 14/14, webkit 14/14 (axe light + dark, keyboard, reflow 320/640, 200% text); staging-compose: Docker Compose stack built and started, smoke test 33/33 over HTTPS through Caddy (including "readiness endpoint is not public"), Playwright against the stack 14/14, encrypted backup + `verify_restore.sh` printed `RESTORE VERIFIED` (Alembic revision 0002, row counts for 13 tables, file hashes) |
| Not covered by any CI run | Let's Encrypt issuance, a real domain/host, a real SMTP provider, ClamAV, the live Anthropic provider (all opt-in / manual, see below). GitHub reports job status as "queued" for these runs, so the evidence above is the log content, not the status badge |

## 2. Deployment artifacts (code in the repo)
`deploy/Dockerfile.backend`, `Dockerfile.web` (Vite build → Caddy), `Caddyfile`, `docker-compose.staging.yml`, `docker-compose.ci.yml`
(test-only TLS SMTP sink), `.env.staging.example`, `deploy/scripts/{backup,restore,verify_restore}.sh`, `backend/scripts/{verify_storage,reapply_deletions}.py`,
`scripts/{staging_local.sh,staging_gateway.py,smtp_sink.py,staging_smoke.py}`, docs `DEPLOYMENT.md`, `OPERATIONS.md`, `BETA_ROADMAP.md`.

## 3. Verified locally (this sandbox: no Docker daemon)
A staging-like stack was run natively by `scripts/staging_local.sh`: **PostgreSQL 16 + password-protected Redis 7 + FastAPI with `JOBHUNTER_ENV=production` and 2 workers + HTTPS gateway (stand-in for Caddy) + STARTTLS/AUTH SMTP**, `REQUIRE_VERIFIED_EMAIL=true`.

| Check | Result |
|---|---|
| Production config validation accepts the staging environment (and the compose-built environment, by test) | ✓ |
| `scripts/staging_smoke.py` (33 steps over HTTPS: health, CSP/HSTS headers, readiness hidden, register, **verification gate blocks resume generation**, e-mail over STARTTLS, single-use token, login, CV upload, honest scan status, owner-only download, parse → draft, in-progress degree preserved, profile confirm, match with missing skill + disqualifier + unknown salary, resume clean, PDF/DOCX export, unsupported claim flagged, clean export blocked, claim accepted, approval, edit-after-approval withdraws it, submit never claims success, user-reported tracking, cross-user isolation) | **33/33** |
| Playwright against that deployment (`E2E_EXTERNAL=1`): journey, auth/reset/lockout/session-expiry/keyboard/mobile, accessibility — plus a guard that fails any test on a CSP violation or uncaught page error | **14/14** |
| Headers: HSTS, CSP, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy; `/health/ready` → 404 externally; SPA fallback; immutable asset caching; 6 MB body limit → 413; stored file keys are not web-reachable (SPA shell returned) | ✓ |
| `X-Forwarded-For` spoofing: 12 logins each claiming a different IP with a 5/min auth limit → **five 401 then 429**, one Redis key for the real client, shared by both workers | ✓ (after fixing my own stand-in, see §5) |
| Redis killed under load: login (critical) → **503**, SPA → 200, global API → per-process fallback, `/health/ready` → `degraded`; Redis restarted → recovers, login 401 again | ✓ |
| Backup → encrypted backup → `verify_restore.sh` (Alembic revision, 12 table row counts, every upload's size + SHA-256, no orphans) | ✓ RESTORE VERIFIED |
| Negative restore tests: flipped byte in `db.dump` → manifest failure; wrong passphrase → refused; upload file deleted from archive → "missing file" failure | ✓ all detected |
| Deletion replay: `reapply_deletions.py` (users + their files, idempotent, dry-run) | ✓ (unit-tested + dry-run on the staging DB) |

Local test matrix (exact commands in §6): backend **196 passed** on SQLite, **196 on PostgreSQL 16**, **25 integration**; frontend lint/typecheck/build clean, **93 Vitest**, **14 Playwright (Chromium)** in dev mode and **14** against the deployed-like stack.

## 4. Accessibility and browsers
* `e2e/a11y.spec.ts`: axe WCAG 2.2 A/AA + best-practice on **every screen, light and dark**, headings/landmarks, visible focus order, keyboard-only registration, error announcement (`aria-invalid`/`aria-describedby`, summary focus), reflow at 320 px and 640 px, 200 % text.
* Found and fixed a real defect: **dark-mode danger button contrast 2.28:1** (needs 4.5:1). jsdom could never have caught it.
* Browsers: Chromium locally; Firefox and WebKit run in CI (not installable in this sandbox). **No human screen-reader testing was done.**

## 5. Defects found during Phase H (and fixed)
1. CI could not install the backend (package discovery) — see §1.
2. Dark-mode contrast on destructive buttons (WCAG 1.4.3).
3. Restore verification script could not import the app (caught by running it); and its first run verified an *empty* dataset (E2E deletes its account) — a seeded smoke test now leaves real data.
4. My own staging tooling: leftover processes from a hung start silently served old code on the ports (script now refuses to start on busy ports and kills leftovers by command line); and the gateway's uvicorn trusted client-supplied `X-Forwarded-For` (now `--no-proxy-headers`). Both were found by checking process lists and rate-limit keys rather than trusting a green run.
5. A test injected an inline `<style>`, which the deployed strict CSP correctly blocked → test now uses CSSOM.

## 6. Exact commands
```bash
# backend (from backend/)
python -m venv .venv && .venv/bin/pip install -e '.[dev,integration]'
.venv/bin/python -m pytest -q                                       # 196 (SQLite)
eval "$(../scripts/dev_services.sh start)"                           # PostgreSQL + Redis, no Docker
.venv/bin/python -m pytest -q                                       # 196 on PostgreSQL (JOBHUNTER_TEST_DATABASE_URL set)
.venv/bin/python -m pytest -q -m integration                         # 25
# frontend (from frontend/)
npm ci && npm run lint && npm run typecheck && npm run build && npm test   # 93
npx playwright test                                                  # 14 (Chromium); E2E_BROWSERS=chromium,firefox,webkit after `npx playwright install`
# staging-like stack, no Docker (from repo root)
scripts/staging_local.sh start
STAGING_URL=https://localhost:8443 STAGING_MAIL_DIR=.staging/mail STAGING_INSECURE=1 backend/.venv/bin/python scripts/staging_smoke.py
(cd frontend && E2E_EXTERNAL=1 E2E_BASE_URL=https://localhost:8443 E2E_MAIL_DIR=$PWD/../.staging/mail npx playwright test)
PGHOST=127.0.0.1 PGPORT=5434 PGUSER=jobhunter PGPASSWORD=stagingpw PGDATABASE=jobhunter STORAGE_DIR=$PWD/.staging/storage BACKUP_DIR=$PWD/.staging/backups \
  VERIFY_PYTHON=$PWD/backend/.venv/bin/python BACKUP_PASSPHRASE=... sh -c 'B=$(deploy/scripts/backup.sh); BACKUP=$B deploy/scripts/verify_restore.sh'
scripts/staging_local.sh stop
# real compose stack (needs Docker): see docs/DEPLOYMENT.md §B
```

## 7. Verified vs. unverified integrations
| Integration | Status |
|---|---|
| PostgreSQL 16 | **Verified** locally and in CI (service container) |
| Redis 7 (limits, multi-worker, outage) | **Verified** locally and in CI; password auth verified locally; TLS/Sentinel/Cluster **not** |
| SMTP over STARTTLS/SSL with verification + AUTH | **Verified** against a local aiosmtpd (local + CI); **a real provider is not**; SPF/DKIM/DMARC/deliverability **not** |
| Caddy, Dockerfiles, compose file | Exercised only through the CI `staging-compose` job (status below); never run on a real host; **Let's Encrypt issuance not tested** |
| HTTPS/CSP/headers | Verified through the Python gateway stand-in (CSP taken from the Caddyfile; drift test) and, via CI, through real Caddy with its internal CA |
| ClamAV | **Unverified** (opt-in `tests/external/test_clamav_real.py`; production profile exists in compose but was never started) |
| Live Anthropic API | **Unverified** (opt-in `tests/external/test_anthropic_live.py`, billable); mocked HTTP only |
| Firefox / WebKit | **Verified in CI only**: 14/14 each in run 19 (not run in the authoring sandbox) |
| Off-site backup transport, scheduled backups, monitoring, alerting | **Not built** (procedures in OPERATIONS.md) |

## 8. Remaining blockers
See `docs/BETA_ROADMAP.md` (P0-1 … P0-9). In short: legal/privacy review, real malware scanning, real mail provider + DKIM, scheduled off-site backups with a restore drill, monitoring/alerting, data export, dependency scanning, abuse controls, and the live-AI decision.
