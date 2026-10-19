"""Contracts for resume generation.

`Draft` is the ONLY shape an AI provider (or a user edit) may supply: free text claims, each citing
profile evidence, plus orderings. It has no fields for education, employers, titles, dates or
certifications, so those can never come from model output; the assembler copies them from the
profile snapshot.
"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]


class ClaimDraft(BaseModel):
    text: Text
    evidence: list[Annotated[str, StringConstraints(max_length=80)]] = Field(default=[], max_length=10)


class SectionDraft(BaseModel):
    ref: Annotated[str, StringConstraints(max_length=40)]  # e.g. "experience[0]" / "projects[2]"
    bullets: list[ClaimDraft] = Field(default=[], max_length=8)


class Draft(BaseModel):
    model_config = ConfigDict(extra="allow")  # unexpected keys are reported, never used

    summary: ClaimDraft | None = None
    skill_order: list[Annotated[str, StringConstraints(max_length=100)]] = Field(default=[], max_length=100)
    experience: list[SectionDraft] = Field(default=[], max_length=30)
    projects: list[SectionDraft] = Field(default=[], max_length=30)
