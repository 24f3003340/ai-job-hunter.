from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    level: Literal["beginner", "intermediate", "advanced"] | None = None
    verified: bool = False


class EducationIn(BaseModel):
    degree: str
    institution: str = ""
    status: Literal["completed", "in_progress"]  # never inferred
    verified: bool = False


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
    experience: list[dict] = []
    projects: list[dict] = []
    skills: list[SkillIn] = []
    preferences: Preferences = Preferences()


class ProfileOut(ProfileIO):
    profile_version: int


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
