from sqlalchemy.orm import Session

from .models import AuditEvent


def audit(db: Session, user_id, action: str, resource_type: str, resource_id=None, **meta) -> None:
    """Record an event. Callers must pass only non-sensitive metadata (no CV text, secrets)."""
    db.add(AuditEvent(
        user_id=user_id, action=action, resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None, safe_metadata_json=meta,
    ))
