# API reference (v0.3)

Base path `/api/v1`. All endpoints except `auth/*` (register, login, password-reset, verify-email) and `/health`
require `Authorization: Bearer <token>`. Foreign or unknown resource IDs always return **404**.
Errors: `401` unauthenticated, `403` verification/consent required, `409` state conflict, `413/415/422` bad input,
`429` rate-limited (with `Retry-After`), `502` AI provider failure.

## Auth
| Method & path | Notes |
|---|---|
| `POST /auth/register` | `{email, password(>=10)}` → `{access_token}`. Sends a verification e-mail. 10/min/IP |
| `POST /auth/login` | Lockout after 5 failures (15 min). 10/min/IP |
| `POST /auth/logout` | Invalidates the server-side session |
| `GET /auth/me` | `{id,email,email_verified,ai_consent}` |
| `POST /auth/password-reset/request` | `{email}` → always `202` with the same body. ≤3 mails/account/hour |
| `POST /auth/password-reset/confirm` | `{token,new_password}` → `204`. Token: 30 min, single-use, stored hashed. Revokes **all** sessions, clears lockout |
| `POST /auth/verify-email` | `{token}` → `204`. Token: 24 h, single-use |
| `POST /auth/resend-verification` | 60 s cooldown, ≤3/hour |
| `POST /account/ai-consent`, `DELETE /account/ai-consent` | Consent to external AI processing |
| `DELETE /account` | Deletes the user, all data and stored files |

## Profile
`GET /profile`, `PUT /profile` — education (each entry needs explicit `status: completed|in_progress`),
experience, projects, skills, certifications, preferences. Each PUT bumps `profile_version`.

## Documents (CV)
| Method & path | Notes |
|---|---|
| `POST /documents/upload` | multipart `file` (PDF/DOCX). Validates content, size, extension match, active content; scans if ClamAV configured. 10/hour/user. Returns `scan_status` = `clean`/`not_configured`/`error` |
| `GET /documents`, `GET /documents/{id}` | Metadata |
| `GET /documents/{id}/download` | Original bytes, `attachment`, `nosniff` |
| `DELETE /documents/{id}` | Removes row and file |
| `POST /documents/{id}/parse` | Creates a **draft** parse `{parse_id, parsed, flags}`; `422 unreadable` for scanned/empty PDFs |
| `GET /documents/{id}/parse` | Latest draft |
| `POST /documents/{id}/parse/confirm` | `{parse_id, acknowledged_flags[], profile}` → writes the (user-corrected) data to the profile. All `warning` flags must be acknowledged |

## Jobs & matching
`POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/verify`, `GET /jobs/{id}/match`.

## Resumes
| Method & path | Notes |
|---|---|
| `POST /jobs/{id}/resume` | `{template:"classic"}` → `201` new immutable version. 20/hour/user. External providers require AI consent |
| `GET /jobs/{id}/resumes` | Version history (newest first) |
| `GET /resumes/{id}` | `content`, `claims[]` (`evidence`, `status`, `reasons`, `decision`), `warnings`, `change_summary`, `review_status` |
| `POST /resumes/{id}/edit` | Body = `Draft` (summary, skill_order, experience[], projects[]). Creates a **new** version; claims are re-validated |
| `POST /resumes/{id}/claims/{claim_id}/review` | `{decision: accept|reject, note}`. Append-only. *accept* = you attest the statement is true |
| `GET /resumes/{id}/download?format=pdf|docx&allow_draft=false` | `409` while `review_status` is `needs_review`/`rejected`, unless `allow_draft=true` (unreviewed claims are prefixed `[UNVERIFIED]`, rejected claims omitted) |

`review_status`: `clean` (all claims consistent with cited evidence) · `reviewed` (flagged claims all accepted) ·
`needs_review` · `rejected`.

## Applications
`POST /applications`, `GET /applications`, `GET /applications/{id}`, `PUT /applications/{id}/answers`,
`PUT /applications/{id}/resume`, `POST /applications/{id}/approve`, `POST /applications/{id}/submit`,
`PATCH /applications/{id}/status`.

* Approval requires: a resume of the same job/user whose `review_status` is `clean`/`reviewed`, confirmed answers,
  an application URL, and a non-expired job. `approve`/`submit` require a verified e-mail when
  `REQUIRE_VERIFIED_EMAIL` is on.
* The approval stores a SHA-256 over: job id + content hash + URL, resume id/content/hash + claim-review decisions,
  cover letter id/text, and all answers. `submit` recomputes it; any difference revokes the approval (`409`).
* `submit` never reports success: with no authorized connector it returns `submission: "manual_required"` and the
  official link; status stays `approved`. Users may record `submitted` only via `PATCH` with
  `user_reported_submission=true` (labelled `manual_user_reported`).

## Operations
| Endpoint | Notes |
|---|---|
| `GET /health` | Liveness only |
| `GET /health/ready` | `200`/`503` with `database`, `rate_limit` (backend, ok, degraded_events) and `malware_scanner` (`configured:false` is reported honestly). Never returns URLs or secrets |

Additional status codes: `503` + `Retry-After` when the rate-limit backend is down (critical endpoints, default fail-closed),
when the AI provider is rate-limited/unconfigured, or when malware scanning is required but unavailable; `504` AI timeout;
`422` for input PostgreSQL cannot store (e.g. NUL characters).
E-mails (verification, reset) are sent after the response in a background task; a mail outage never fails the request.
