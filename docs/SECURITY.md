# Security checklist

Legend: ✅ implemented **and tested here** · 🟡 implemented, tested only against a local stand-in · ⬜ not done / not verifiable here.

## Authentication & accounts
- ✅ Argon2 hashing; server-side sessions (logout revokes); lockout after 5 failures; constant-work login for unknown e-mails
- ✅ Password reset: random 256-bit token, stored SHA-256 only, 30 min, single use (race-tested on PostgreSQL), older tokens voided, all sessions revoked, uniform response, per-account throttle
- ✅ E-mail verification: expiring single-use token, resend cooldown + hourly cap; gate on approve/submit when `REQUIRE_VERIFIED_EMAIL`
- ⬜ MFA, OAuth, password-breach checks, session listing/revocation UI, CAPTCHA
- ⬜ Login lockout can be used to lock out a victim (mitigated by reset flow + IP rate limit; no per-IP+account scheme)

## Secrets & logging
- ✅ API key and SMTP password are `SecretStr` (masked in repr/dumps); never in responses, logs, or provider error text (tested with canaries)
- ✅ No backend logs message bodies, tokens or addresses; delivery failures log only the exception class (tested)
- ✅ Production startup refuses unsafe config (sqlite, http URLs, wildcard CORS, console mail, plaintext SMTP, no rate limits, process-local limiter, missing ClamAV decision, missing keys)
- 🟡 Uvicorn/proxy access logs are outside the app: make sure they do not log request bodies
- ⬜ Secret manager / key rotation procedure; `.env` is the only mechanism

## Transport & mail
- ✅ SMTP: STARTTLS or implicit TLS with certificate **and hostname** verification; credentials never sent before TLS; plaintext only with no credentials outside production; header-injection guarded
- 🟡 Verified against a local aiosmtpd (self-signed CA), **not** a production provider; SPF/DKIM/DMARC deliverability is unverified
- 🟡 TLS termination: `deploy/Caddyfile` (HSTS, CSP, nosniff, frame-ancestors none, XFF overwrite, body limit, token-redacted logs) is exercised via the CI compose job and a Python gateway stand-in; **no public certificate/DNS has been issued**
- ✅ Frontend CSP: strict policy served as a header by the gateway and the browser E2E fails on any CSP violation; Caddy/Vite policies are kept identical by a test

## Uploads
- ✅ Content sniffing + extension match, size/page/zip-bomb limits, PDF active content and encrypted PDFs, DOCX macros rejected; private 0600 storage with random names; atomic writes; temp cleanup; authenticated owner-only download
- ✅ Production fails closed if no scanner is configured (unless `ALLOW_UNSCANNED_UPLOADS=true`) or the scanner is down
- 🟡 ClamAV `INSTREAM`/`PING` protocol tested against a fake clamd only; **real clamd + EICAR test written (`tests/external`) but not run**
- ⬜ Content-disarm/sandboxed parsing of hostile documents, encryption at rest for stored CVs, object storage with signed URLs

## AI / data protection
- ✅ External provider requires explicit, revocable consent; payload excludes name/e-mail/phone fields and redacts them in free text (tested on the actual outbound body)
- ✅ Model output cannot set facts: schema-bounded, evidence-checked, unsupported claims need user review
- ✅ Timeouts, 429/5xx retry with capped backoff, malformed/truncated output → clean 502/503/504 and no version created
- 🟡 Same behaviour against the **real** Anthropic API is unverified (`tests/external/test_anthropic_live.py` requires a key)
- ⬜ Vendor/DPA review, data-retention schedule, India DPDP/consumer-law review (needs legal input)

## Rate limiting & abuse
- ✅ Redis sliding window (atomic Lua, server clock) shared across workers — **verified with 3 real uvicorn workers: exactly 10/30 allowed**
- ✅ Failure policy: critical endpoints fail closed (503) or enforce per process; never silently skipped; circuit breaker
- 🟡 Redis auth/TLS (`rediss://`), Sentinel/Cluster and eviction policy were not tested (single local Redis 7.0)
- ⬜ Per-user API quotas for expensive endpoints beyond the limits above; WAF/bot protection

## Database
- ✅ Schema from Alembic verified on SQLite and PostgreSQL 16: zero drift, upgrade-with-data, downgrade, FK cascades, constraint races
- ⬜ Backups/restore drills, row-level security, connection-pool tuning, other PostgreSQL versions / managed services

## Deployment & backups
- ✅ Production config refuses to start unsafely; staging runs with `JOBHUNTER_ENV=production`
- ✅ Uploads volume mounted only in the backend; no web route maps to it (tested over HTTPS)
- ✅ Backup + encrypted backup + `verify_restore.sh` (row counts, Alembic revision, file checksums); tamper / wrong passphrase / lost file are detected
- ✅ Deleted accounts can be re-applied after restoring an older backup (`reapply_deletions.py`)
- ⬜ Scheduled/off-site backups, key management for `BACKUP_PASSPHRASE`, PITR/WAL archiving

## Operational
- ✅ `/health/ready` reports DB, limiter, scanner (no secrets)
- ⬜ Error monitoring, metrics, alerting, audit-log retention/export, dependency vulnerability scanning (`pip-audit`), container image hardening
