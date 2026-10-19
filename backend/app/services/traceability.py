"""Evidence index and claim checks.

This is a *heuristic* consistency check, not proof of truth. It catches the common ways generated
text drifts from the source (no evidence, dangling references, numbers or technologies that the cited
passage does not contain, seniority wording, degree-completion wording over an in-progress degree).
A claim that passes is only "consistent with the cited text"; a claim that fails is routed to the
user, who must accept (attest) or reject it.
"""
import re

_STOP = set("with that this from have into over using used their they were been which while also than then "
            "such each other more most some work worked team teams across within build built made make".split())
_SENIORITY = re.compile(r"\b(led|lead|leading|managed|manager|head of|senior|principal|architected|owned|founded|"
                        r"directed|spearheaded|mentored)\b", re.I)
_COMPLETION = re.compile(r"\b(graduat\w*|completed|earned|holds?|received|awarded|obtained)\b", re.I)
_DEGREE_WORD = re.compile(r"\b(degree|b\.?tech|m\.?tech|bachelor\w*|master\w*|b\.?sc|m\.?sc|mba|ph\.?d|diploma|"
                          r"b\.?e\b|bca|mca)\b", re.I)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.]*[A-Za-z0-9+#]|[A-Za-z]")


def _t(x) -> str:
    return "" if x is None else str(x)


def build_index(profile: dict) -> dict[str, str]:
    """ref -> text. Parent refs (e.g. experience[0]) include their children's text."""
    idx: dict[str, str] = {"profile.full_name": _t(profile.get("full_name"))}
    for i, s in enumerate(profile.get("skills", [])):
        idx[f"skills[{i}]"] = _t(s.get("name"))
    for i, e in enumerate(profile.get("education", [])):
        idx[f"education[{i}]"] = " ".join(_t(e.get(k)) for k in ("degree", "institution", "status", "start_date", "end_date"))
    for sec, head in (("experience", ("title", "employer", "description", "start_date", "end_date")),
                      ("projects", ("name", "description", "url"))):
        for i, e in enumerate(profile.get(sec, [])):
            parts = [_t(e.get(k)) for k in head]
            parts += [_t(t) for t in e.get("technologies", [])]
            for j, b in enumerate(e.get("bullets", [])):
                idx[f"{sec}[{i}].bullets[{j}]"] = _t(b)
                parts.append(_t(b))
            idx[f"{sec}[{i}]"] = " ".join(p for p in parts if p)
    for i, c in enumerate(profile.get("certifications", [])):
        idx[f"certifications[{i}]"] = " ".join(_t(c.get(k)) for k in ("name", "issuer", "date"))
    return idx


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


def _nums(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("%") for n in _NUM.findall(text)}


def _tech_terms(text: str, job_terms: set[str]) -> set[str]:
    """Tokens that look like named technologies/proper terms (LangChain, NLP, C++, Node.js) or job skills."""
    out = set()
    for m in _WORD.finditer(text):
        w = m.group(0)
        lw = w.lower().strip(".")
        starts_sentence = m.start() == 0
        camel = bool(re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", w))
        caps = len(w) >= 2 and w.isupper()
        sym = bool(re.search(r"[+#]|\.[a-z]{1,3}$", w)) and len(w) > 1
        if camel or caps or sym or lw in job_terms or (w[0].isupper() and not starts_sentence):
            out.add(lw)
    return out


def check_claim(text: str, refs: list[str], idx: dict[str, str], profile: dict, job_terms: set[str]) -> list[dict]:
    reasons: list[dict] = []

    def add(code, msg):
        reasons.append({"code": code, "message": msg})

    if not refs:
        add("no_evidence", "No supporting profile evidence is cited for this statement.")
        return reasons
    missing = [r for r in refs if r not in idx]
    if missing:
        add("unknown_evidence", f"Cited evidence does not exist in the profile: {', '.join(missing)}")
    cited = " ".join(idx[r] for r in refs if r in idx)
    if not cited.strip():
        return reasons or [{"code": "empty_evidence", "message": "Cited evidence is empty."}]

    cited_words = _words(cited)
    bad_nums = sorted(n for n in _nums(text) - _nums(cited))
    if bad_nums:
        add("number_unsupported", f"Figures not present in the cited evidence: {', '.join(bad_nums)}")
    bad_terms = sorted(t for t in _tech_terms(text, job_terms) if t not in cited_words and t not in _STOP)
    if bad_terms:
        add("term_unsupported", f"Terms not present in the cited evidence: {', '.join(bad_terms)}")
    if _SENIORITY.search(text) and not _SENIORITY.search(cited):
        add("seniority_unsupported", "Leadership/ownership wording is not supported by the cited evidence.")

    content = {w for w in _words(text) if len(w) >= 4 and w not in _STOP}
    if content and len(content & cited_words) / len(content) < 0.4:
        add("weak_overlap", "Little of this statement's wording appears in the cited evidence.")

    if _COMPLETION.search(text) and _DEGREE_WORD.search(text):
        edu = [(r, profile["education"][int(m.group(1))]) for r in refs
               if (m := re.match(r"education\[(\d+)\]", r)) and int(m.group(1)) < len(profile.get("education", []))]
        if not edu:
            add("education_claim_unsupported", "Degree wording without citing an education entry.")
        elif any(e.get("status") != "completed" for _, e in edu):
            add("education_status_conflict", "Wording implies a completed degree, but the cited education is in progress.")
    return reasons
