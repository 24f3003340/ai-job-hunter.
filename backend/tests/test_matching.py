from types import SimpleNamespace as NS

from app.services.matching import evaluate


def job(**kw):
    base = dict(title="Python ML Engineer", company="Acme", location="Jaipur", remote=None, status="active",
                required_skills_json=["Python", "NLP"], preferred_skills_json=["React"], salary_min=None,
                salary_max=None, salary_period=None, experience_min=None, requires_degree_completed=None)
    return NS(**{**base, **kw})


def profile(**prefs):
    return NS(skills_json=[{"name": "python"}, {"name": "NLP"}], education_json=[{"status": "in_progress"}],
              preferences_json={"target_titles": ["ML Engineer"], "cities": ["Jaipur"], "min_salary_monthly": 50000,
                                "experience_years": 0, **prefs})


def test_unknowns_not_assumed_to_match():
    r = evaluate(job(), profile())
    assert "salary" in r.unknown_dimensions and "experience" in r.unknown_dimensions
    assert r.components["salary"] is None
    assert r.known_weight < 1


def test_missing_skills_and_matches():
    r = evaluate(job(), profile())
    assert r.matched_skills == ["Python", "NLP"] and r.missing_skills == ["React"]


def test_in_progress_degree_is_hard_constraint_despite_high_score():
    r = evaluate(job(requires_degree_completed=True), profile())
    assert r.disqualified and r.hard_constraints
    assert r.score is not None and r.score > 50  # high score does not hide the constraint


def test_salary_normalised_from_annual():
    ok = evaluate(job(salary_max=720000, salary_period="year"), profile())  # 60k/month
    low = evaluate(job(salary_max=240000, salary_period="year"), profile())  # 20k/month
    assert ok.components["salary"] == 100 and low.components["salary"] < 100
    assert any("below" in w for w in low.eligibility_warnings)


def test_excluded_employer():
    r = evaluate(job(), profile(excluded_employers=["acme"]))
    assert r.disqualified
