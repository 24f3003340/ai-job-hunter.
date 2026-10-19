from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user
from ..models import CandidateProfile, User
from ..schemas import ProfileIO, ProfileOut

router = APIRouter(tags=["profile"])


def get_profile(db: Session, user: User) -> CandidateProfile:
    p = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if p is None:
        p = CandidateProfile(user_id=user.id)
        db.add(p)
        db.flush()
    return p


def _out(p: CandidateProfile) -> ProfileOut:
    return ProfileOut(
        full_name=p.full_name, phone=p.phone, education=p.education_json, experience=p.experience_json,
        projects=p.projects_json, skills=p.skills_json, certifications=p.certifications_json or [], preferences=p.preferences_json or {},
        profile_version=p.profile_version,
    )


@router.get("/profile", response_model=ProfileOut)
def read_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    db.commit()
    return _out(p)


@router.put("/profile", response_model=ProfileOut)
def update_profile(body: ProfileIO, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    p.full_name, p.phone = body.full_name, body.phone
    p.education_json = [e.model_dump() for e in body.education]
    p.skills_json = [s.model_dump() for s in body.skills]
    p.experience_json = [e.model_dump() for e in body.experience]
    p.projects_json = [x.model_dump() for x in body.projects]
    p.certifications_json = [c.model_dump() for c in body.certifications]
    p.preferences_json = body.preferences.model_dump()
    p.profile_version += 1
    audit(db, user.id, "profile_updated", "profile", p.id, version=p.profile_version)
    db.commit()
    return _out(p)
