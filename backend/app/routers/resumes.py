from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user, verified_user
from ..models import ClaimReview, Job, ResumeVersion, User
from ..ratelimit import limit_user
from ..schemas import ResumeGenerateIn, ReviewIn
from ..services import resume_export, resume_generator as gen
from ..services.ai_provider import DraftProvider, ProviderError, get_provider
from ..services.resume_review import BLOCKING, review_state
from ..services.resume_schema import Draft
from .jobs import _owned_job
from .profile import get_profile

router = APIRouter(tags=["resumes"])


def _owned_resume(db: Session, user: User, rid: UUID) -> ResumeVersion:
    v = db.get(ResumeVersion, rid)
    if v is None or v.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    return v


def _summary(db: Session, v: ResumeVersion) -> dict:
    st = review_state(db, v)
    return {"id": v.id, "job_id": v.job_id, "version_number": v.version_number, "parent_version_id": v.parent_version_id,
            "source_profile_version": v.source_profile_version, "generation_source": v.generation_source,
            "provider": v.provider, "review_status": st["status"], "created_at": v.created_at,
            "content_hash": v.content_hash}


def _detail(db: Session, v: ResumeVersion) -> dict:
    st = review_state(db, v)
    claims = [{**c, "decision": st["decisions"].get(c["id"])} for c in v.claims_json]
    return {**_summary(db, v), "content": v.content_json, "claims": claims, "warnings": v.warnings_json,
            "change_summary": v.change_summary_json, "unresolved_claims": st["unresolved"],
            "rejected_claims": st["rejected"]}


def _create_version(db, user, job, profile, draft: Draft, *, source: str, provider, parent: ResumeVersion | None,
                    template: str) -> ResumeVersion:
    snapshot = gen.snapshot_profile(profile, user.email)
    content, claims, warnings, changes = gen.assemble(snapshot, draft, gen.job_view(job), template)
    if parent is not None and parent.source_profile_version != profile.profile_version:
        warnings.append({"code": "profile_changed", "severity": "info",
                         "message": "Your profile changed since the previous version; this version uses the current profile."})
    n = (db.scalar(select(func.max(ResumeVersion.version_number)).where(
        ResumeVersion.user_id == user.id, ResumeVersion.job_id == job.id)) or 0) + 1
    v = ResumeVersion(
        user_id=user.id, job_id=job.id, version_number=n, parent_version_id=parent.id if parent else None,
        source_profile_version=profile.profile_version, profile_snapshot_json=snapshot, content_json=content,
        claims_json=claims, warnings_json=warnings, change_summary_json=changes, generation_source=source,
        provider=getattr(provider, "name", None), model_name=getattr(provider, "model", None),
        content_hash=gen.content_hash(content, claims),
        factual_review_status="needs_review" if any(c["status"] == "needs_review" for c in claims) else "clean")
    db.add(v)
    return v


@router.post("/jobs/{job_id}/resume", status_code=201,
             dependencies=[limit_user("generate", "rate_limit_generate")])
def generate_resume(job_id: UUID, body: ResumeGenerateIn = ResumeGenerateIn(),
                    user: User = Depends(verified_user), db: Session = Depends(get_db),
                    provider: DraftProvider = Depends(get_provider)):
    job = _owned_job(db, user, job_id)
    profile = get_profile(db, user)
    if not (profile.full_name and (profile.experience_json or profile.projects_json or profile.skills_json)):
        raise HTTPException(422, "Complete and confirm your profile (name plus skills, experience or projects) first")
    if body.template not in gen.TEMPLATES:
        raise HTTPException(422, "Unknown template")
    if provider.external and user.ai_consent_at is None:
        raise HTTPException(403, {"detail": "Consent to AI processing is required", "code": "ai_consent_required"})
    snapshot = gen.snapshot_profile(profile, user.email)
    try:
        draft = provider.draft(gen.provider_view(snapshot), gen.job_view(job))
    except ProviderError as exc:
        audit(db, user.id, "resume_generation_failed", "job", job.id, provider=provider.name)
        db.commit()
        code = {"rate_limited": 503, "timeout": 504}.get(exc.kind, 502)
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(code, f"Resume drafting failed: {exc}", headers=headers)
    v = _create_version(db, user, job, profile, draft, source="generated", provider=provider, parent=None,
                        template=body.template)
    audit(db, user.id, "resume_generated", "resume", v.id, job_id=str(job.id), provider=provider.name)
    db.commit()
    return _detail(db, v)


@router.get("/jobs/{job_id}/resumes")
def list_versions(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = _owned_job(db, user, job_id)
    rows = db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user.id, ResumeVersion.job_id == job.id)
                      .order_by(ResumeVersion.version_number.desc()))
    return [_summary(db, v) for v in rows]


@router.get("/resumes/{resume_id}")
def get_resume(resume_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, _owned_resume(db, user, resume_id))


@router.post("/resumes/{resume_id}/edit", status_code=201)
def edit_resume(resume_id: UUID, draft: Draft, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Editing never mutates a version: it validates the edit and stores it as a new version."""
    parent = _owned_resume(db, user, resume_id)
    job = db.get(Job, parent.job_id)
    v = _create_version(db, user, job, get_profile(db, user), draft, source="user_edit", provider=None, parent=parent,
                        template=parent.content_json.get("template", "classic"))
    audit(db, user.id, "resume_edited", "resume", v.id, parent=str(parent.id))
    db.commit()
    return _detail(db, v)


@router.post("/resumes/{resume_id}/claims/{claim_id}/review")
def review_claim(resume_id: UUID, claim_id: str, body: ReviewIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """accept = you attest the statement is true; reject = it must not be used (create a new version)."""
    v = _owned_resume(db, user, resume_id)
    claim = next((c for c in v.claims_json if c["id"] == claim_id), None)
    if claim is None:
        raise HTTPException(404, "Claim not found")
    if claim["status"] != "needs_review":
        raise HTTPException(409, "Only flagged claims need review")
    db.add(ClaimReview(resume_version_id=v.id, user_id=user.id, claim_id=claim_id, decision=body.decision, note=body.note))
    audit(db, user.id, "claim_reviewed", "resume", v.id, claim=claim_id, decision=body.decision)
    db.commit()
    return _detail(db, v)


@router.get("/resumes/{resume_id}/download")
def download_resume(resume_id: UUID, format: Literal["pdf", "docx"] = "pdf", allow_draft: bool = False,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = _owned_resume(db, user, resume_id)
    st = review_state(db, v)
    if st["status"] in BLOCKING and not allow_draft:
        raise HTTPException(409, {"detail": "Resume has unreviewed or rejected claims. Review them, or pass "
                                            "allow_draft=true for a draft with [UNVERIFIED] markers.",
                                  "review_status": st["status"]})
    if format == "pdf":
        body, media = resume_export.to_pdf(v.content_json, v.claims_json, st), "application/pdf"
    else:
        body = resume_export.to_docx(v.content_json, v.claims_json, st)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    audit(db, user.id, "resume_downloaded", "resume", v.id, format=format)
    db.commit()
    return Response(body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="resume-v{v.version_number}.{format}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        "X-Review-Status": st["status"]})
