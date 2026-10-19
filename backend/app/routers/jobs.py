import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Job, User, utcnow
from ..schemas import JobIn, JobOut
from ..services.matching import evaluate
from .profile import get_profile

router = APIRouter(tags=["jobs"])


def _canon_url(url: str | None) -> str | None:
    return url.split("#")[0].split("?")[0].rstrip("/").lower() if url else None


def _hash(body: JobIn) -> str:
    keys = ("title", "company", "location", "description", "required_skills", "preferred_skills",
            "salary_min", "salary_max", "salary_period", "experience_min", "application_url")
    data = body.model_dump(include=set(keys))
    data["application_url"] = _canon_url(body.application_url)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _owned_job(db: Session, user: User, job_id: UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "Job not found")  # same response for foreign and missing IDs
    return job


@router.post("/jobs", response_model=JobOut, status_code=201)
def add_job(body: JobIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Manual / user-submitted vacancy. Deduplicates on source id, canonical URL, then title+company+location."""
    canon = _canon_url(body.application_url)
    q = select(Job).where(Job.user_id == user.id)
    conds = []
    if body.external_job_id:
        conds.append((Job.source == body.source) & (Job.external_job_id == body.external_job_id))
    if canon:
        conds.append(Job.canonical_url == canon)
    conds.append((Job.title.ilike(body.title)) & (Job.company.ilike(body.company)) & (Job.location.ilike(body.location)))
    existing = db.scalar(q.where(or_(*conds)))
    new_hash = _hash(body)
    if existing:
        if existing.content_hash != new_hash:
            raise HTTPException(409, {"detail": "Duplicate job with changed content", "job_id": str(existing.id)})
        return existing
    job = Job(
        user_id=user.id, source=body.source, external_job_id=body.external_job_id, title=body.title,
        company=body.company, location=body.location, remote=body.remote, employment_type=body.employment_type,
        description=body.description, required_skills_json=body.required_skills,
        preferred_skills_json=body.preferred_skills, salary_min=body.salary_min, salary_max=body.salary_max,
        salary_period=body.salary_period, experience_min=body.experience_min, experience_max=body.experience_max,
        requires_degree_completed=body.requires_degree_completed, application_url=body.application_url,
        canonical_url=canon, closing_date=body.closing_date, content_hash=new_hash,
        # Manual entries are unverified until the user/connector confirms them.
        status="needs_verification",
    )
    db.add(job)
    db.commit()
    return job


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    q: str | None = None, status: str | None = None, limit: int = Query(50, le=200), offset: int = 0,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    stmt = select(Job).where(Job.user_id == user.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company.ilike(like)))
    if status:
        stmt = stmt.where(Job.status == status)
    return db.scalars(stmt.order_by(Job.first_seen_at.desc()).limit(limit).offset(offset)).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _owned_job(db, user, job_id)


@router.post("/jobs/{job_id}/verify", response_model=JobOut)
def mark_verified(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """User confirms the listing is live at its source."""
    job = _owned_job(db, user, job_id)
    job.status, job.last_verified_at = "active", utcnow()
    db.commit()
    return job


@router.get("/jobs/{job_id}/match")
def match(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = _owned_job(db, user, job_id)
    report = evaluate(job, get_profile(db, user))
    db.commit()
    return report
