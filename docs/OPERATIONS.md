# Operational checklist

How to run the application responsibly during a personal pilot / staging, and what is still missing for a public beta.
Legend: ✅ built and tested in this repo · 🔧 you must set it up (procedure given) · ⬜ not built yet (tracked in `BETA_ROADMAP.md`).

## 1. Logging
| | Item |
|---|---|
| ✅ | No log line contains passwords, session tokens, reset/verification tokens, API keys, SMTP passwords, e-mail bodies, or CV contents (tested with canary values). Mail failures log only the exception class. Provider errors never echo response bodies |
| ✅ | Caddy access logs (JSON) redact `?token=` on e-mailed frontend URLs and drop `Authorization`/`Cookie` headers |
| ✅ | `audit_events` table records security-relevant actions (register, login/lockout, reset, verification, consent, upload, parse, confirm, resume generation/review/download, approvals, account deletion) with non-sensitive metadata |
| ✅ | Account deletions also emit `account_deleted user_id=<uuid>` (no personal data) so they can be replayed after a restore (§5) |
| 🔧 | Ship container logs off the host (journald → Loki/ELK/Cloud logging) and keep **≥ 90 days**; protect them like production data. Set Docker log rotation (`max-size`, `max-file`) so a full disk cannot take the site down |
| 🔧 | Review rules: never log request bodies at the proxy; never raise log level to DEBUG in production |
| ⬜ | Structured (JSON) application logs with request ids; audit-log retention/export policy |

## 2. Monitoring and alerting
| | Item |
|---|---|
| ✅ | `GET /health` (liveness) and `GET /health/ready` (database, rate-limit backend, malware scanner; `degraded_events` counts rate-limiter outages). Compose healthchecks use them; Caddy hides `/health/ready` from the internet |
| 🔧 | External uptime probe on `https://<host>/health` every minute (page on 2 failures) |
| 🔧 | Alerts: HTTP 5xx rate, backend restarts, disk > 80 %, PostgreSQL connections/locks, Redis down (`/health/ready` shows `rate_limit.ok=false` and critical endpoints return 503), **certificate expiry < 14 days**, **last successful backup > 26 h**, restore drill overdue |
| 🔧 | Check weekly: `docker compose ps`, disk usage of the `uploads` and `pg_data` volumes, `docker compose logs backend | grep -c "rate-limit backend unavailable"` |
| ⬜ | Metrics endpoint/tracing/dashboards; error tracking (e.g. Sentry) with PII scrubbing |

## 3. Rate limits and abuse
| | Item |
|---|---|
| ✅ | Redis-backed sliding windows shared by all workers: auth endpoints 10/min/IP, uploads 10/h/user, resume generation 20/h/user, global 300/min/IP. Critical endpoints **fail closed** (503) if Redis is down; others degrade to per-process limits. Tuned via `RATE_LIMIT_*` |
| ✅ | Login lockout per account (5 failures → 15 min), uniform login/reset responses (no account enumeration), reset/verification e-mail throttles |
| ✅ | Caddy overwrites `X-Forwarded-For`, so a client cannot choose its own rate-limit identity (tested) |
| 🔧 | Never raise the limits in staging/production for convenience (CI does so only in throwaway stacks) |
| 🔧 | Watch for lockout abuse (many `account_locked` audit events for one account) and register/reset floods; block offending IPs at the firewall |
| ⬜ | CAPTCHA/proof-of-work on register/reset, IP+account lockout scheme, bot protection/WAF |

## 4. Backups and restore (see `DEPLOYMENT.md` §D)
- 🔧 Schedule `deploy/scripts/backup.sh` at least daily (cron/systemd timer) with `BACKUP_PASSPHRASE` set; copy the result **off the host** (object storage with versioning; different account/region).
- 🔧 Retention: keep **≤ 30 days** of daily backups (privacy: deleted users disappear from backups after that window); document RPO (≤ 24 h) and RTO (target ≤ 4 h).
- ✅ `verify_restore.sh` proves a backup restores and matches (row counts, Alembic revision, every file's checksum); detects tampering/loss.
- 🔧 Run the drill **monthly** and after any schema change; record date + result. Store the passphrase separately from backups.
- 🔧 Back up `deploy/.env.staging` (secrets) separately in a password manager — it is deliberately not in the repo or backups.

## 5. Account deletion and data lifecycle
| | Item |
|---|---|
| ✅ | `DELETE /account` removes the user and every owned row (cascade) **and the stored upload files**; sessions are revoked; verified on PostgreSQL (no orphans in 13 tables) |
| ✅ | After restoring an older backup, replay deletions: `cat <logs since backup> \| python backend/scripts/reapply_deletions.py [--dry-run]` (idempotent; removes users and their files) |
| 🔧 | Keep the log archive that contains `account_deleted` lines for at least as long as backups are retained |
| 🔧 | Tell users (privacy notice) that backups expire within 30 days and that audit events keep only an opaque user id and action |
| ⬜ | Self-service data export (`GET /account/export`), scheduled purge of expired tokens/sessions/stale temp files and audit-log retention |

## 6. Privacy and security hygiene
- ✅ Data minimisation to AI providers (no name/e-mail/phone, redaction inside text), explicit revocable consent, rule-based local drafting by default.
- ✅ CVs are private: owner-only authenticated download, never served statically, not reachable from the web tier.
- ✅ Honest UI: uploads are labelled "not scanned" when no scanner is configured; applications are never shown as submitted unless the user reported it.
- 🔧 Maintain a record of processing (what is stored, why, how long, which vendors), and a vendor list: hosting, SMTP provider, LLM provider (if enabled).
- 🔧 Patch cadence: OS weekly; rebuild images monthly (`docker compose build --pull`); review `pip-audit` / `npm audit` output (⬜ not yet automated in CI).
- 🔧 Rotate secrets at least every 6 months and immediately after any suspected exposure: edit `deploy/.env.staging`, `docker compose up -d`; rotating the SMTP/AI keys needs no downtime; rotating the DB/Redis password requires changing it in the service too.
- 🔧 Restrict SSH (keys only), enable automatic security updates, keep Docker socket private.
- ⬜ Legal review (DPDP Act, terms, privacy notice) — **blocks any public beta**.

## 7. Incident response runbook (small team)
1. **Detect/declare** — alert, user report, or log anomaly. Record time, reporter, symptom in an incident log. One person is incident lead.
2. **Contain** (minutes):
   * Suspected credential/key leak → rotate the secret now (§6), then `docker compose up -d`.
   * Suspected account takeover/abuse → lock accounts (`UPDATE users SET account_status='locked' WHERE id=…`; locked users cannot authenticate), revoke sessions (`DELETE FROM auth_sessions WHERE user_id=…`).
   * Active attack/flood → block at firewall/Caddy; lower limits; if needed take the site down (`docker compose stop web`) — data stays safe.
   * Malicious upload suspected → delete the document (`DELETE /documents/{id}` or SQL + remove the object file); scan the storage volume with ClamAV.
3. **Preserve evidence**: copy logs and `audit_events` for the window; snapshot the volume before changing it.
4. **Assess scope**: which accounts/data? Use `audit_events` + access logs. Remember CVs, contact details, education and employment data are personal data.
5. **Recover**: patch/fix, restore from a verified backup if data was damaged (`restore.sh`, then `reapply_deletions.py`), run `scripts/staging_smoke.py`, watch logs.
6. **Notify**: if personal data may have been exposed, notify affected users and the relevant authority **within the legal deadline** (confirm requirements with counsel — DPDP/CERT-In obligations; this repo does not provide legal advice). Keep the notice factual: what, when, what data, what you did, what users should do.
7. **Review within 5 working days**: timeline, root cause, what detection would have caught it earlier, owner + due date for each fix; update this document and the tests.

Contacts to fill in before the pilot: incident lead, backup person, hosting support, SMTP provider support, legal counsel.

## 8. Release checklist (every deployment)
- [ ] CI green on the commit (backend unit + integration, frontend, E2E on Chromium/Firefox/WebKit, `staging-compose`)
- [ ] Backup taken and `verify_restore.sh` passed within the last 24 h (required before schema changes)
- [ ] `$COMPOSE config --quiet` clean; no `CHANGE_ME` left; `.env.staging` mode 600
- [ ] Deploy; `migrate` exited 0; backend healthy; `scripts/staging_smoke.py` passed
- [ ] `/health/ready` (from the host) shows `database.ok`, `rate_limit.backend=redis ok`, and the expected scanner state
- [ ] Spot-check logs for errors; confirm no secrets in logs
