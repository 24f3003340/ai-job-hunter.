"""Deterministic, explainable job matching (FR-07). No LLM involvement.

Unknown dimensions are reported as unknown and excluded from the weighted
average (weights renormalised); the report states how much of the score rests
on known data. Hard constraints are returned separately and never hidden by a
high numeric score.
"""
import re
from dataclasses import dataclass, field

WEIGHTS = {
    "skills": 0.30,
    "experience": 0.20,
    "role": 0.15,
    "salary": 0.15,
    "location": 0.10,
    "education": 0.10,
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#. ]", " ", s.lower()).strip()


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if t}


def monthly_inr(amount: float | None, period: str | None) -> float | None:
    if amount is None or period not in ("month", "year"):
        return None
    return amount if period == "month" else amount / 12


@dataclass
class MatchReport:
    score: float | None
    components: dict[str, float | None]
    unknown_dimensions: list[str]
    known_weight: float
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    eligibility_warnings: list[str] = field(default_factory=list)
    salary_confidence: str = "unknown"
    freshness: str = "active"
    disqualified: bool = False
    explanation: str = ""


def _skills(job_skills: list[str], profile_skills: list[dict]):
    have = {_norm(s["name"]): s["name"] for s in profile_skills if s.get("name")}
    matched = [s for s in job_skills if _norm(s) in have]
    missing = [s for s in job_skills if _norm(s) not in have]
    return matched, missing


def evaluate(job, profile) -> MatchReport:
    prefs = profile.preferences_json or {}
    comps: dict[str, float | None] = {}
    hard: list[str] = []
    warnings: list[str] = []

    # Skills: required weigh 2x preferred. No skills listed -> unknown.
    req, pref = job.required_skills_json or [], job.preferred_skills_json or []
    m_req, x_req = _skills(req, profile.skills_json or [])
    m_pref, x_pref = _skills(pref, profile.skills_json or [])
    denom = 2 * len(req) + len(pref)
    comps["skills"] = None if denom == 0 else 100 * (2 * len(m_req) + len(m_pref)) / denom
    if x_req:
        warnings.append(f"Missing required skills: {', '.join(x_req)}")

    # Experience
    years = prefs.get("experience_years")
    if job.experience_min is None or years is None:
        comps["experience"] = None
    else:
        gap = job.experience_min - years
        comps["experience"] = 100.0 if gap <= 0 else max(0.0, 100 - 35 * gap)
        if gap > 0:
            warnings.append(f"Asks for {job.experience_min:g}+ years; profile lists {years:g}")

    # Role relevance
    targets = prefs.get("target_titles") or []
    if not targets:
        comps["role"] = None
    else:
        jt = _tokens(job.title)
        comps["role"] = 100 * max(len(jt & _tokens(t)) / max(len(_tokens(t)), 1) for t in targets)

    # Salary (normalised to INR/month; salary currency assumed INR in this phase)
    floor = prefs.get("min_salary_monthly")
    top = monthly_inr(job.salary_max if job.salary_max is not None else job.salary_min, job.salary_period)
    if floor is None or top is None:
        comps["salary"] = None
    else:
        comps["salary"] = 100.0 if top >= floor else max(0.0, 100 * top / floor - 20)
        if top < floor:
            warnings.append("Posted salary is below your minimum")
    salary_confidence = "unknown" if top is None else "stated"

    # Location
    cities = [_norm(c) for c in prefs.get("cities") or []]
    loc = _norm(job.location or "")
    if job.remote is None and not loc:
        comps["location"] = None
    elif job.remote and prefs.get("remote_ok", True):
        comps["location"] = 100.0
    elif any(c in loc for c in cities):
        comps["location"] = 100.0
    elif prefs.get("relocation_ok"):
        comps["location"] = 60.0
    else:
        comps["location"] = 0.0
        warnings.append("Location does not match preferences and relocation is not enabled")

    # Education / eligibility
    if job.requires_degree_completed is None:
        comps["education"] = None
    else:
        completed = any(e.get("status") == "completed" for e in profile.education_json or [])
        comps["education"] = 100.0 if (completed or not job.requires_degree_completed) else 0.0
        if job.requires_degree_completed and not completed:
            hard.append("Job requires a completed degree; none is recorded as completed in your profile")

    # Hard constraints from user exclusions
    if _norm(job.company) in [_norm(e) for e in prefs.get("excluded_employers") or []]:
        hard.append(f"Employer '{job.company}' is on your exclusion list")
    for ex in prefs.get("excluded_locations") or []:
        if _norm(ex) and _norm(ex) in _norm(job.location or ""):
            hard.append(f"Location excluded: {ex}")
    if job.status == "expired":
        hard.append("Listing is expired")

    known = {k: v for k, v in comps.items() if v is not None}
    known_weight = sum(WEIGHTS[k] for k in known)
    score = None if not known else round(sum(WEIGHTS[k] * v for k, v in known.items()) / known_weight, 1)
    unknown = [k for k, v in comps.items() if v is None]

    expl = [f"Score {score if score is not None else 'n/a'} based on {round(known_weight * 100)}% of the scoring weight."]
    if unknown:
        expl.append(f"Unknown (not assumed to match): {', '.join(unknown)}.")
    if hard:
        expl.append("Disqualifying requirements are listed separately and apply regardless of score.")

    return MatchReport(
        score=score, components={k: (None if v is None else round(v, 1)) for k, v in comps.items()},
        unknown_dimensions=unknown, known_weight=round(known_weight, 2),
        matched_skills=m_req + m_pref, missing_skills=x_req + x_pref, hard_constraints=hard,
        eligibility_warnings=warnings, salary_confidence=salary_confidence, freshness=job.status,
        disqualified=bool(hard), explanation=" ".join(expl),
    )
