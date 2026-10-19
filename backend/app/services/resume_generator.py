"""Deterministic assembly of a resume from a profile snapshot plus a provider/user `Draft`.

Business rules live here, not in the model: header, education (with status), employers, titles,
dates and certifications are copied from the snapshot; skills can only be reordered from the profile's
own list; every free-text statement becomes a Claim that must cite evidence and is then checked.
"""
import hashlib
import json
import re

from . import traceability
from .ai_provider import job_vocabulary
from .resume_schema import ClaimDraft, Draft

TEMPLATES = {"classic"}


def snapshot_profile(profile, account_email: str) -> dict:
    return {
        "profile_version": profile.profile_version, "full_name": profile.full_name, "phone": profile.phone,
        "email": account_email, "education": profile.education_json or [], "experience": profile.experience_json or [],
        "projects": profile.projects_json or [], "skills": profile.skills_json or [],
        "certifications": profile.certifications_json or [],
    }


def provider_view(snapshot: dict) -> dict:
    """Data minimisation for external providers: no name, e-mail or phone."""
    return {k: v for k, v in snapshot.items() if k not in ("full_name", "phone", "email", "profile_version")}


def job_view(job) -> dict:
    return {"title": job.title, "company": job.company, "location": job.location,
            "description": (job.description or "")[:6000], "required_skills": job.required_skills_json or [],
            "preferred_skills": job.preferred_skills_json or []}


def _idx(ref: str, kind: str, n: int) -> int | None:
    m = re.fullmatch(rf"{kind}\[(\d+)\]", ref)
    return int(m.group(1)) if m and int(m.group(1)) < n else None


class _Claims:
    def __init__(self, snapshot, idx, job_terms):
        self.snapshot, self.idx, self.job_terms, self.items = snapshot, idx, job_terms, []

    def add(self, section: str, c: ClaimDraft) -> dict:
        refs = list(dict.fromkeys(c.evidence))
        reasons = traceability.check_claim(c.text, refs, self.idx, self.snapshot, self.job_terms)
        claim = {"id": f"c{len(self.items) + 1}", "section": section, "text": c.text, "evidence": refs,
                 "status": "needs_review" if reasons else "supported", "reasons": reasons}
        self.items.append(claim)
        return {"id": claim["id"], "text": claim["text"]}


def assemble(snapshot: dict, draft: Draft, job: dict, template: str = "classic"):
    idx = traceability.build_index(snapshot)
    claims = _Claims(snapshot, idx, job_vocabulary(job))
    warnings: list[dict] = []
    summary_changes: list[str] = []

    def warn(code, message, severity="warning"):
        warnings.append({"code": code, "severity": severity, "message": message})

    if draft.model_extra:
        warn("provider_extra_fields_ignored", "Ignored unexpected fields from the drafting step: "
             + ", ".join(sorted(draft.model_extra)))

    # skills: only the profile's own skills; the draft can only influence order
    prof_skills = snapshot["skills"]
    by_name = {s["name"].lower(): i for i, s in enumerate(prof_skills)}
    order: list[int] = []
    for name in draft.skill_order:
        i = by_name.get(name.lower())
        if i is None:
            warn("skill_not_in_profile", f"Dropped skill proposed by the drafting step but absent from your profile: {name}")
        elif i not in order:
            order.append(i)
    order += [i for i in range(len(prof_skills)) if i not in order]
    skills = [{"name": prof_skills[i]["name"], "evidence": [f"skills[{i}]"]} for i in order]
    if order != sorted(order):
        summary_changes.append("Skills reordered to put job-relevant skills first: "
                               + ", ".join(s["name"] for s in skills[:5]))

    summary = claims.add("summary", draft.summary) if draft.summary else None
    if summary:
        summary_changes.append("Added a professional summary")

    def build_section(kind: str, drafts, fields):
        n = len(snapshot[kind])
        by_ref: dict[int, list[ClaimDraft]] = {}
        order_refs: list[int] = []
        for sd in drafts:
            i = _idx(sd.ref, kind, n)
            if i is None:
                warn("unknown_section_ref", f"Ignored a {kind} section with an unknown reference: {sd.ref}")
                continue
            if i not in by_ref:
                order_refs.append(i)
            by_ref.setdefault(i, []).extend(sd.bullets)
        # entries the draft did not mention keep their original bullets as self-cited claims
        for i in range(n):
            if i not in by_ref:
                order_refs.append(i)
                by_ref[i] = [ClaimDraft(text=b, evidence=[f"{kind}[{i}].bullets[{j}]"])
                             for j, b in enumerate(snapshot[kind][i].get("bullets", []))][:8]
        if kind == "experience":
            order_refs = sorted(by_ref)  # employment history keeps its original order
        out = []
        for i in order_refs:
            entry = snapshot[kind][i]
            item = {"ref": f"{kind}[{i}]", **{f: entry.get(f) for f in fields},
                    "bullets": [claims.add(f"{kind}[{i}]", c) for c in by_ref[i]]}
            out.append(item)
            orig = set(entry.get("bullets", []))
            changed = sum(1 for b in item["bullets"] if b["text"] not in orig)
            if changed:
                summary_changes.append(f"{changed} bullet(s) rewritten under {kind}[{i}] "
                                       f"({entry.get('title') or entry.get('name') or ''})")
        if kind == "projects" and order_refs != sorted(order_refs):
            summary_changes.append("Projects reordered by relevance to the job")
        return out

    experience = build_section("experience", draft.experience, ("title", "employer", "start_date", "end_date", "current"))
    projects = build_section("projects", draft.projects, ("name", "technologies", "url"))

    education = [{"ref": f"education[{i}]", **{k: e.get(k) for k in ("degree", "institution", "status", "start_date", "end_date")}}
                 for i, e in enumerate(snapshot["education"])]
    for e in education:
        if e["status"] == "in_progress":
            warn("education_in_progress", f"“{e['degree']}” is shown as in progress; it was not changed.", "info")
    certs = [{"ref": f"certifications[{i}]", **{k: c.get(k) for k in ("name", "issuer", "date")}}
             for i, c in enumerate(snapshot["certifications"])]

    flagged = [c for c in claims.items if c["status"] == "needs_review"]
    if flagged:
        warn("claims_need_review", f"{len(flagged)} statement(s) are not fully supported by your profile and need your review.")
    if not snapshot["experience"] and not snapshot["projects"]:
        warn("no_experience_or_projects", "Profile has no experience or projects to tailor.", "info")

    content = {
        "template": template,
        "header": {"name": snapshot["full_name"], "email": snapshot["email"], "phone": snapshot["phone"]},
        "summary": summary, "skills": skills, "experience": experience, "projects": projects,
        "education": education, "certifications": certs,
    }
    return content, claims.items, warnings, summary_changes


def content_hash(content: dict, claims: list) -> str:
    return hashlib.sha256(json.dumps([content, claims], sort_keys=True, default=str).encode()).hexdigest()
