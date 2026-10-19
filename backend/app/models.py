import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _ts(**kw) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, **kw)


class User(Base):
    __tablename__ = "users"
    id = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    account_status: Mapped[str] = mapped_column(String(20), default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = _ts()
    updated_at = _ts(onupdate=utcnow)


class AuthSession(Base):
    """Server-side session so logout genuinely invalidates the token."""

    __tablename__ = "auth_sessions"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at = _ts()


class AuthToken(Base):
    """Single-use, hashed, expiring tokens for password reset and e-mail verification."""

    __tablename__ = "auth_tokens"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(30))  # password_reset | email_verify
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = _ts()


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    education_json: Mapped[list] = mapped_column(JSON, default=list)
    experience_json: Mapped[list] = mapped_column(JSON, default=list)
    projects_json: Mapped[list] = mapped_column(JSON, default=list)
    skills_json: Mapped[list] = mapped_column(JSON, default=list)
    certifications_json: Mapped[list] = mapped_column(JSON, default=list)
    preferences_json: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at = _ts(onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "source", "external_job_id"),)
    id = _id()
    # Jobs are user-scoped in the personal phase; shared catalogs can come with connectors.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(100), default="manual")
    external_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(300), default="")
    remote: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    required_skills_json: Mapped[list] = mapped_column(JSON, default=list)
    preferred_skills_json: Mapped[list] = mapped_column(JSON, default=list)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(10), nullable=True)  # month | year
    experience_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    requires_degree_completed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    application_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2000), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closing_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at = _ts()
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|stale|needs_verification|expired
    content_hash: Mapped[str] = mapped_column(String(64))


class Document(Base):
    """An uploaded original (e.g. master CV). Never modified after upload."""

    __tablename__ = "documents"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[str] = mapped_column(String(30), default="cv")
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(String(20), default="not_configured")  # clean|not_configured|error
    parsing_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|parsed|unreadable|failed
    created_at = _ts()


class CvParse(Base):
    """A parsing draft. Becomes profile data only through the explicit confirm step."""

    __tablename__ = "cv_parses"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    parser_version: Mapped[str] = mapped_column(String(20))
    parsed_json: Mapped[dict] = mapped_column(JSON, default=dict)
    flags_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|confirmed|superseded
    created_at = _ts()
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResumeVersion(Base):
    """Immutable once created. Edits and regenerations create a new version; review decisions
    are appended to claim_reviews instead of mutating this row."""

    __tablename__ = "resume_versions"
    __table_args__ = (UniqueConstraint("user_id", "job_id", "version_number", name="uq_resume_versions_user_job_version"),)
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_profile_version: Mapped[int] = mapped_column(Integer)
    profile_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    claims_json: Mapped[list] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    change_summary_json: Mapped[list] = mapped_column(JSON, default=list)
    generation_source: Mapped[str] = mapped_column(String(20), default="legacy")  # generated|user_edit|legacy
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_status: Mapped[str] = mapped_column(String(20), default="complete")
    # Initial value only; the effective status is derived from claims + claim_reviews.
    factual_review_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at = _ts()


class ClaimReview(Base):
    """Append-only user decisions on flagged resume claims; the latest per claim wins."""

    __tablename__ = "claim_reviews"
    id = _id()
    resume_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resume_versions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    claim_id: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(10))  # accept | reject
    note: Mapped[str] = mapped_column(Text, default="")
    created_at = _ts()


class CoverLetter(Base):
    __tablename__ = "cover_letters"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at = _ts()


class Application(Base):
    __tablename__ = "applications"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resume_versions.id"), nullable=True)
    cover_letter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cover_letters.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="discovered")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    confirmation_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submission_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at = _ts()
    updated_at = _ts(onupdate=utcnow)
    answers = relationship("ApplicationAnswer", cascade="all, delete-orphan", lazy="selectin")


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"
    id = _id()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source_of_truth: Mapped[str] = mapped_column(String(30), default="user")  # user|profile|ai_draft
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at = _ts()


class ApplicationApproval(Base):
    __tablename__ = "application_approvals"
    id = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    package_hash: Mapped[str] = mapped_column(String(64))
    approved_at = _ts()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_method: Mapped[str] = mapped_column(String(30), default="explicit_ui")


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id = _id()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30))
    event_type: Mapped[str] = mapped_column(String(50))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at = _ts()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = _id()
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)  # no FK: survives deletion
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp = _ts()
    safe_metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
