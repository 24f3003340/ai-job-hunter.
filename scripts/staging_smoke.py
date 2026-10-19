#!/usr/bin/env python3
"""HTTP-level end-to-end smoke test of a RUNNING deployment (no browser). Leaves its test account and data in place
(so backups/restores have real content); pass --cleanup to delete the account at the end.

    STAGING_URL=https://localhost:8443 STAGING_MAIL_DIR=.staging/mail [STAGING_INSECURE=1] python scripts/staging_smoke.py
For a real staging host with a real mailbox, paste the verification token when asked: STAGING_TOKEN_FROM=prompt.
Exit status 0 = every step passed.
"""
import argparse
import io
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

URL = os.environ.get("STAGING_URL", "https://localhost:8443").rstrip("/")
MAIL_DIR = Path(os.environ.get("STAGING_MAIL_DIR", ".staging/mail"))
VERIFY = os.environ.get("STAGING_INSECURE") != "1"
P = f"{URL}/api/v1"
CV = """Riya Sharma
riya.sharma@example.com | +91 98765 43210
EDUCATION
B.Tech in Computer Science, Example Institute of Technology, Jaipur 2022 - Expected 2027
SKILLS
Languages: Python, JavaScript, SQL
Frameworks: LangChain, React, FastAPI
EXPERIENCE
ML Intern at Acme Labs Jun 2024 - Aug 2024
- Built a RAG prototype over 500 documents using LangChain
- Reduced response time by 30%
PROJECTS
Resume Ranker | Python, NLP
- Ranked resumes with TF-IDF and cosine similarity
"""
results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  - ' + detail) if detail and not ok else ''}", flush=True)
    if not ok:
        raise SystemExit(finish())


def finish() -> int:
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} steps passed")
    return 1 if bad else 0


def mail_token(email: str, subject: str) -> str:
    if os.environ.get("STAGING_TOKEN_FROM") == "prompt":  # real mailbox: copy the token= value from the link in the e-mail
        return input(f"Paste the token from the '{subject}' e-mail sent to {email}: ").strip()
    for _ in range(60):
        for f in sorted(MAIL_DIR.glob("*.eml"), key=lambda p: p.stat().st_mtime, reverse=True):
            raw = f.read_text(errors="replace").replace("=\n", "").replace("=3D", "=")
            if f"To: {email}" in raw and subject in raw and (m := re.search(r"token=([\w-]+)", raw)):
                return m.group(1)
        time.sleep(0.5)
    raise SystemExit(f"no '{subject}' mail for {email} in {MAIL_DIR}")


def make_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in CV.split("\n"):
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()
    http = httpx.Client(verify=VERIFY, timeout=30)
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    pw = "correct-horse-battery"

    r = http.get(f"{URL}/health")
    step("health", r.status_code == 200 and r.json()["status"] == "ok")
    r = http.get(f"{URL}/")
    step("SPA served over HTTPS with CSP + HSTS", r.status_code == 200 and "content-security-policy" in r.headers
         and "strict-transport-security" in r.headers and "<div id=\"root\">" in r.text)
    step("readiness endpoint is not public", http.get(f"{URL}/health/ready").status_code == 404)

    r = http.post(f"{P}/auth/register", json={"email": email, "password": pw})
    step("register", r.status_code == 201)
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    step("starts unverified", http.get(f"{P}/auth/me", headers=h).json()["email_verified"] is False)
    gate_job = http.post(f"{P}/jobs", headers=h, json={"title": "Gate check", "company": "Acme"}).json()
    r = http.post(f"{P}/jobs/{gate_job['id']}/resume", headers=h, json={})
    step("unverified user is blocked from sensitive actions (verification gate)", r.status_code == 403, f"got {r.status_code}")
    token = mail_token(email, "Verify your email")
    step("verification e-mail delivered over SMTP", bool(token))
    step("verify e-mail", http.post(f"{P}/auth/verify-email", json={"token": token}).status_code == 204)
    step("verification token is single-use", http.post(f"{P}/auth/verify-email", json={"token": token}).status_code == 400)
    step("verified flag set", http.get(f"{P}/auth/me", headers=h).json()["email_verified"] is True)
    step("login", http.post(f"{P}/auth/login", json={"email": email, "password": pw}).status_code == 200)
    step("wrong password rejected", http.post(f"{P}/auth/login", json={"email": email, "password": "nope-nope-nope"}).status_code == 401)

    pdf = make_pdf()
    r = http.post(f"{P}/documents/upload", headers=h, files={"file": ("cv.pdf", pdf, "application/pdf")})
    step("CV upload", r.status_code == 201, r.text[:200])
    doc = r.json()
    step("scan status reported honestly", doc["scan_status"] in ("clean", "not_configured"))
    step("original downloadable and identical", http.get(f"{P}/documents/{doc['id']}/download", headers=h).content == pdf)
    step("stored file is not publicly reachable", http.get(f"{URL}/{doc['id']}").headers["content-type"].startswith("text/html")
         and http.get(f"{P}/documents/{doc['id']}/download").status_code == 401)
    prev = http.post(f"{P}/documents/{doc['id']}/parse", headers=h).json()
    step("CV parsed to a draft", prev["parsed"]["full_name"] == "Riya Sharma" and prev["status"] == "draft")
    edu = [{**{k: e[k] for k in ("degree", "institution", "start_date", "end_date")}, "status": e["status"] or "completed"} for e in prev["parsed"]["education"]]
    step("in-progress degree detected, not auto-completed", prev["parsed"]["education"][0]["status"] == "in_progress")
    body = {"parse_id": prev["parse_id"], "acknowledged_flags": [f["id"] for f in prev["flags"]], "profile": {
        "full_name": prev["parsed"]["full_name"], "phone": prev["parsed"]["phone"], "education": edu,
        "experience": [{k: v for k, v in x.items() if k != "confidence"} for x in prev["parsed"]["experience"]],
        "projects": [{k: v for k, v in x.items() if k != "confidence"} for x in prev["parsed"]["projects"]],
        "skills": prev["parsed"]["skills"], "certifications": []}}
    r = http.post(f"{P}/documents/{doc['id']}/parse/confirm", headers=h, json=body)
    step("profile confirmed", r.status_code == 200 and r.json()["education"][0]["status"] == "in_progress", r.text[:200])

    job = http.post(f"{P}/jobs", headers=h, json={"title": "NLP Engineer", "company": "Acme", "location": "Jaipur",
          "application_url": "https://acme.example/careers/nlp", "required_skills": ["Python", "LangChain", "Kubernetes"],
          "requires_degree_completed": True}).json()
    http.post(f"{P}/jobs/{job['id']}/verify", headers=h)
    m = http.get(f"{P}/jobs/{job['id']}/match", headers=h).json()
    step("match: missing skill + disqualifier (degree in progress) + unknown salary",
         "Kubernetes" in m["missing_skills"] and m["disqualified"] and m["components"]["salary"] is None)

    rv = http.post(f"{P}/jobs/{job['id']}/resume", headers=h, json={})
    step("resume generated and clean", rv.status_code == 201 and rv.json()["review_status"] == "clean", rv.text[:200])
    rv = rv.json()
    step("resume keeps degree in progress", rv["content"]["education"][0]["status"] == "in_progress")
    for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK")):
        r = http.get(f"{P}/resumes/{rv['id']}/download", headers=h, params={"format": fmt})
        step(f"export {fmt}", r.status_code == 200 and r.content.startswith(magic))
    r = http.post(f"{P}/resumes/{rv['id']}/edit", headers=h, json={"summary": {"text": "Award-winning engineer", "evidence": []}})
    flagged = r.json()
    step("unsupported claim flagged on an edited version", r.status_code == 201 and flagged["review_status"] == "needs_review")
    step("clean export blocked until reviewed", http.get(f"{P}/resumes/{flagged['id']}/download", headers=h).status_code == 409)
    cid = flagged["claims"][0]["id"]
    r = http.post(f"{P}/resumes/{flagged['id']}/claims/{cid}/review", headers=h, json={"decision": "accept"})
    step("claim accepted by user", r.json()["review_status"] == "reviewed")

    app = http.post(f"{P}/applications", headers=h, json={"job_id": job["id"], "resume_version_id": flagged["id"],
          "answers": [{"question": "Why?", "answer": "I like RAG.", "user_confirmed": True}]}).json()
    r = http.post(f"{P}/applications/{app['id']}/approve", headers=h)
    step("approval", r.status_code == 200 and r.json()["status"] == "approved")
    http.put(f"{P}/applications/{app['id']}/answers", headers=h, json=[{"question": "Why?", "answer": "Changed.", "user_confirmed": True}])
    step("edit after approval withdraws it", http.get(f"{P}/applications/{app['id']}", headers=h).json()["status"] == "ready_for_review")
    http.post(f"{P}/applications/{app['id']}/approve", headers=h)
    r = http.post(f"{P}/applications/{app['id']}/submit", headers=h).json()
    step("submit never claims success", r["submission"] == "manual_required" and r["status"] == "approved")
    r = http.patch(f"{P}/applications/{app['id']}/status", headers=h, json={"status": "submitted", "user_reported_submission": True})
    step("user-reported application tracked", r.json()["submission_method"] == "manual_user_reported")
    apps = http.get(f"{P}/applications", headers=h).json()
    step("tracker lists it", len(apps) == 1 and apps[0]["status"] == "submitted")

    other = http.post(f"{P}/auth/register", json={"email": f"other-{uuid.uuid4().hex[:6]}@example.com", "password": pw}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    step("another user cannot read the CV, resume or application",
         all(http.get(u, headers=oh).status_code == 404 for u in (f"{P}/documents/{doc['id']}", f"{P}/resumes/{rv['id']}", f"{P}/applications/{app['id']}")))

    if args.cleanup:
        step("account deletion", http.delete(f"{P}/account", headers=h).status_code == 204)
        step("deleted account cannot log in", http.post(f"{P}/auth/login", json={"email": email, "password": pw}).status_code == 401)
    else:
        print(f"(left account {email} in place for backup/restore checks)")
    return finish()


if __name__ == "__main__":
    sys.exit(main())
