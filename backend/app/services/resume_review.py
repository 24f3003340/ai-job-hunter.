from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ClaimReview, ResumeVersion


def latest_decisions(db: Session, version_id) -> dict[str, str]:
    rows = db.scalars(select(ClaimReview).where(ClaimReview.resume_version_id == version_id)
                      .order_by(ClaimReview.created_at, ClaimReview.id))
    return {r.claim_id: r.decision for r in rows}  # later rows overwrite earlier ones


def review_state(db: Session, v: ResumeVersion) -> dict:
    """Effective factual-review status, derived (the version row itself is immutable).

    clean        - every claim is consistent with its cited evidence
    reviewed     - flagged claims exist and the user accepted (attested to) all of them
    needs_review - at least one flagged claim has no decision yet
    rejected     - the user rejected a flagged claim; create a new version to proceed
    """
    decisions = latest_decisions(db, v.id)
    flagged = [c["id"] for c in (v.claims_json or []) if c["status"] == "needs_review"]
    rejected = [c for c in flagged if decisions.get(c) == "reject"]
    unresolved = [c for c in flagged if c not in decisions]
    if rejected:
        status = "rejected"
    elif unresolved:
        status = "needs_review"
    else:
        status = "reviewed" if flagged else "clean"
    return {"status": status, "unresolved": unresolved, "rejected": rejected, "decisions": decisions}


BLOCKING = {"needs_review", "rejected"}
