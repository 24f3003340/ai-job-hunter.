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
