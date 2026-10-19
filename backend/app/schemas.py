from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class EmailOnly(BaseModel):
    email: EmailStr


class TokenBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ResetConfirm(TokenBody):
    new_password: str = Field(min_length=10, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    level: Literal["beginner", "intermediate", "advanced"] | None = None
    verified: bool = False


DateStr = Annotated[str, StringConstraints(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$")]  # YYYY or YYYY-MM


class EducationIn(BaseModel):
    degree: str = Field(min_length=1, max_length=300)
    institution: str = Field(default="", max_length=300)
    status: Literal["completed", "in_progress"]  # always explicit; never inferred
    start_date: DateStr | None = None
    end_date: DateStr | None = None
    verified: bool = False


class ExperienceIn(BaseModel):
    title: str = Field(default="", max_length=300)
    employer: str = Field(default="", max_length=300)
    start_date: DateStr | None = None
    end_date: DateStr | None = None
    current: bool = False
    description: str = Field(default="", max_length=5000)
    bullets: list[Annotated[str, StringConstraints(max_length=1000)]] = Field(default=[], max_length=30)


class ProjectIn(BaseModel):
    name: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    bullets: list[Annotated[str, StringConstraints(max_length=1000)]] = Field(default=[], max_length=30)
    technologies: list[str] = Field(default=[], max_length=40)
    url: str | None = None


class CertificationIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    issuer: str = Field(default="", max_length=300)
    date: DateStr | None = None


class Preferences(BaseModel):
    target_titles: list[str] = []
    min_salary_monthly: float | None = None
    cities: list[str] = []
    remote_ok: bool = True
    relocation_ok: bool = False
    experience_years: float | None = None
    excluded_employers: list[str] = []
    excluded_locations: list[str] = []


class ProfileIO(BaseModel):
    full_name: str = ""
    phone: str = ""
    education: list[EducationIn] = []
    experience: list[ExperienceIn] = []
    projects: list[ProjectIn] = []
    skills: list[SkillIn] = []
    certifications: list[CertificationIn] = []
    preferences: Preferences = Preferences()


class ProfileOut(ProfileIO):
    profile_version: int


class ConfirmCv(BaseModel):
    parse_id: UUID
    acknowledged_flags: list[str] = []
    profile: ProfileIO


class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    location: str = ""
    remote: bool | None = None
    employment_type: str | None = None
    description: str = Field(default="", max_length=50_000)
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: Literal["month", "year"] | None = None
    experience_min: float | None = None
    experience_max: float | None = None
    requires_degree_completed: bool | None = None
    application_url: str | None = None
    source: str = "manual"
    external_job_id: str | None = None
    closing_date: datetime | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    company: str
    location: str
    remote: bool | None
    description: str
    salary_min: float | None
    salary_max: float | None
    salary_period: str | None
    experience_min: float | None
    application_url: str | None
    status: str
    source: str
    first_seen_at: datetime
    last_verified_at: datetime | None
    closing_date: datetime | None


class AnswerIn(BaseModel):
    question: str = Field(min_length=1)
    answer: str
    source_of_truth: Literal["user", "profile", "ai_draft"] = "user"
    user_confirmed: bool = False


class ApplicationCreate(BaseModel):
    job_id: UUID
    resume_version_id: UUID | None = None
    cover_letter_id: UUID | None = None
    answers: list[AnswerIn] = []


class StatusUpdate(BaseModel):
    status: str
    note: str = ""
    user_reported_submission: bool = False


class ResumeGenerateIn(BaseModel):
    template: str = "classic"


class ReviewIn(BaseModel):
    decision: Literal["accept", "reject"]
    note: str = Field(default="", max_length=1000)


class SetResumeIn(BaseModel):
    resume_version_id: UUID
