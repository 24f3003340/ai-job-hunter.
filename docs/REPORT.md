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
