"""Application package hashing, approval and status rules (FR-10, FR-11)."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .resume_review import BLOCKING, review_state
from ..models import Application, ApplicationApproval, ApplicationEvent, CoverLetter, Job, ResumeVersion, utcnow

STATUSES = [
    "discovered", "match_evaluated", "ready_for_review", "approved", "submission_in_progress",
    "submitted", "submission_failed", "interview", "rejected", "withdrawn", "offer_received", "closed",
]

# Statuses a user may set directly via PATCH. 'approved' only via the approve endpoint;
# 'submitted' only via submit or an explicit user-reported manual submission.
MANUAL_TRANSITIONS = {
    "discovered": {"match_evaluated", "ready_for_review", "withdrawn", "closed"},
    "match_evaluated": {"ready_for_review", "withdrawn", "closed"},
    "ready_for_review": {"withdrawn", "closed"},
    "approved": {"ready_for_review", "withdrawn", "closed"},
    "submission_failed": {"ready_for_review", "withdrawn", "closed"},
    "submitted": {"interview", "rejected", "withdrawn", "offer_received", "closed"},
    "interview": {"rejected", "withdrawn", "offer_received", "closed"},
    "offer_received": {"withdrawn", "closed"},
    "rejected": {"closed"},
    "withdrawn": {"closed"},
    "closed": set(),
}


def package_hash(db: Session, app: Application) -> str:
    """Hash of everything the user approved: exact job content, CV version, letter and answers."""
    job = db.get(Job, app.job_id)
    resume = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    letter = db.get(CoverLetter, app.cover_letter_id) if app.cover_letter_id else None
    payload = {
        "job_id": str(job.id), "job_content_hash": job.content_hash, "application_url": job.application_url,
        "resume_id": str(resume.id) if resume else None, "resume": resume.content_json if resume else None,
        "resume_hash": resume.content_hash if resume else None,
        # review decisions are part of what the user approved: changing one invalidates the approval
        "resume_review": sorted(review_state(db, resume)["decisions"].items()) if resume else None,
        "cover_letter_id": str(letter.id) if letter else None, "cover_letter": letter.content if letter else None,
        "answers": sorted(([a.question, a.answer] for a in app.answers)),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def record_event(db: Session, app: Application, new_status: str, event_type: str, **meta) -> None:
    db.add(ApplicationEvent(
        application_id=app.id, previous_status=app.status, new_status=new_status,
        event_type=event_type, metadata_json=meta,
    ))
    app.status = new_status


def active_approval(db: Session, app: Application) -> ApplicationApproval | None:
    return db.scalar(
        select(ApplicationApproval)
        .where(ApplicationApproval.application_id == app.id, ApplicationApproval.revoked_at.is_(None))
        .order_by(ApplicationApproval.approved_at.desc())
    )


def revoke_approval(db: Session, app: Application, reason: str) -> None:
    appr = active_approval(db, app)
    if appr is None:
        return
    appr.revoked_at = utcnow()
    if app.status == "approved":
        record_event(db, app, "ready_for_review", "approval_revoked", reason=reason)


def blockers(db: Session, app: Application) -> list[str]:
    """Reasons an application cannot be approved yet."""
    out = []
    job = db.get(Job, app.job_id)
    if job.status == "expired":
        out.append("Job listing is expired")
    if not job.application_url:
        out.append("Job has no verified application URL")
    out += resume_blockers(db, app)
    unconfirmed = [a.question for a in app.answers if not a.user_confirmed]
    if unconfirmed:
        out.append(f"{len(unconfirmed)} answer(s) not confirmed by you")
    return out


def resume_blockers(db: Session, app: Application) -> list[str]:
    if app.resume_version_id is None:
        return ["No tailored resume attached"]
    resume = db.get(ResumeVersion, app.resume_version_id)
    if resume is None or resume.user_id != app.user_id or resume.job_id != app.job_id:
        return ["Attached resume does not belong to this job"]
    state = review_state(db, resume)
    if state["status"] in BLOCKING:
        return [f"Resume has factual claims awaiting your review (status: {state['status']})"]
    return []
