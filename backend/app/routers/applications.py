from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user
from ..models import (Application, ApplicationAnswer, ApplicationApproval, ApplicationEvent, CoverLetter, Job,
                      ResumeVersion, User, utcnow)
from ..schemas import AnswerIn, ApplicationCreate, StatusUpdate
from ..services.applications import (MANUAL_TRANSITIONS, STATUSES, active_approval, blockers, package_hash,
                                     record_event, revoke_approval)

router = APIRouter(tags=["applications"])


def _owned(db: Session, user: User, app_id: UUID) -> Application:
    app = db.get(Application, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(404, "Application not found")
    return app


def _view(db: Session, app: Application) -> dict:
    job = db.get(Job, app.job_id)
    return {
        "id": app.id, "job_id": app.job_id, "status": app.status, "submitted_at": app.submitted_at,
        "submission_method": app.submission_method, "confirmation_reference": app.confirmation_reference,
        "resume_version_id": app.resume_version_id, "cover_letter_id": app.cover_letter_id,
        "answers": [{"question": a.question, "answer": a.answer, "source_of_truth": a.source_of_truth,
                     "user_confirmed": a.user_confirmed} for a in app.answers],
        "blockers": blockers(db, app) if app.status in ("discovered", "match_evaluated", "ready_for_review") else [],
        "manual_application_url": job.application_url, "notes": app.notes,
    }


def _own_linked(db: Session, model, obj_id, user: User, job_id, label: str):
    if obj_id is None:
        return
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id or obj.job_id != job_id:
        raise HTTPException(422, f"{label} not found for this job")


@router.post("/applications", status_code=201)
def create_application(body: ApplicationCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, body.job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    if db.scalar(select(Application).where(Application.user_id == user.id, Application.job_id == job.id,
                                           Application.status.notin_(["closed", "withdrawn"]))):
        raise HTTPException(409, "An active application for this job already exists")
    _own_linked(db, ResumeVersion, body.resume_version_id, user, job.id, "Resume version")
    _own_linked(db, CoverLetter, body.cover_letter_id, user, job.id, "Cover letter")
    app = Application(user_id=user.id, job_id=job.id, resume_version_id=body.resume_version_id,
                      cover_letter_id=body.cover_letter_id, status="discovered")
    app.answers = [ApplicationAnswer(**a.model_dump()) for a in body.answers]
    db.add(app)
    db.flush()
    record_event(db, app, "ready_for_review", "draft_created")
    audit(db, user.id, "application_created", "application", app.id)
    db.commit()
    return _view(db, app)


@router.get("/applications")
def list_applications(status: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Application).where(Application.user_id == user.id)
    if status:
        stmt = stmt.where(Application.status == status)
    return [_view(db, a) for a in db.scalars(stmt.order_by(Application.created_at.desc()))]


@router.get("/applications/{app_id}")
def get_application(app_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _owned(db, user, app_id)
    events = db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)
                        .order_by(ApplicationEvent.created_at)).all()
    return {**_view(db, app), "history": [
        {"from": e.previous_status, "to": e.new_status, "type": e.event_type, "at": e.created_at} for e in events]}


@router.put("/applications/{app_id}/answers")
def replace_answers(app_id: UUID, answers: list[AnswerIn], user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    app = _owned(db, user, app_id)
    if app.status not in ("discovered", "match_evaluated", "ready_for_review", "approved", "submission_failed"):
        raise HTTPException(409, "Answers can no longer be edited")
    revoke_approval(db, app, "answers changed")  # a material change invalidates approval
    app.answers = [ApplicationAnswer(**a.model_dump()) for a in answers]
    db.commit()
    return _view(db, app)


@router.post("/applications/{app_id}/approve")
def approve(app_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _owned(db, user, app_id)
    if app.status != "ready_for_review":
        raise HTTPException(409, f"Cannot approve an application in status '{app.status}'")
    problems = blockers(db, app)
    if problems:
        raise HTTPException(422, {"detail": "Application is not ready for approval", "blockers": problems})
    digest = package_hash(db, app)
    db.add(ApplicationApproval(user_id=user.id, application_id=app.id, package_hash=digest))
    record_event(db, app, "approved", "approved", package_hash=digest)
    audit(db, user.id, "application_approved", "application", app.id)
    db.commit()
    return {**_view(db, app), "package_hash": digest}


@router.post("/applications/{app_id}/submit")
def submit(app_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _owned(db, user, app_id)
    if app.status in ("submitted", "submission_in_progress"):
        return _view(db, app)  # idempotent: never re-submit
    if app.status != "approved":
        raise HTTPException(409, "Application must be approved before submission")
    appr = active_approval(db, app)
    if appr is None or appr.package_hash != package_hash(db, app):
        revoke_approval(db, app, "package changed since approval")
        db.commit()
        raise HTTPException(409, "Application changed since approval; review and approve again")
    job = db.get(Job, app.job_id)
    if job.status == "expired":
        raise HTTPException(409, "Job listing is expired")
    # No authorized submission connectors exist yet. Never mark as submitted on our own:
    # hand the user the official link; they can record a manual submission via PATCH.
    return {**_view(db, app), "submission": "manual_required",
            "detail": "No authorized connector for this source. Apply at the official link, "
                      "then record it with PATCH /applications/{id}/status (user_reported_submission)."}


@router.patch("/applications/{app_id}/status")
def update_status(app_id: UUID, body: StatusUpdate, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    app = _owned(db, user, app_id)
    if body.status not in STATUSES:
        raise HTTPException(422, "Unknown status")
    if body.status == "submitted":
        if app.status != "approved" or not body.user_reported_submission:
            raise HTTPException(409, "Only an approved application can be recorded as submitted, "
                                     "with user_reported_submission=true")
        app.submitted_at, app.submission_method = utcnow(), "manual_user_reported"
        record_event(db, app, "submitted", "user_reported_submission")
    elif body.status not in MANUAL_TRANSITIONS.get(app.status, set()):
        raise HTTPException(409, f"Cannot move from '{app.status}' to '{body.status}'")
    else:
        if app.status == "approved":
            revoke_approval(db, app, "user moved status")
        record_event(db, app, body.status, "status_changed")
    if body.note:
        app.notes = body.note
    db.commit()
    return _view(db, app)
