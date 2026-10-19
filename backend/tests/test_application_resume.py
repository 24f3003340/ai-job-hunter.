import pytest
from sqlalchemy import select

from app.main import app
from app.models import ApplicationEvent, CoverLetter, Job, User
from app.services.ai_provider import get_provider
from app.services.resume_schema import ClaimDraft, Draft
from conftest import register
from helpers import confirm_payload, make_pdf, upload
from test_resumes import JOB, FakeProvider, use_provider, _clear_provider  # noqa: F401

P = "/api/v1"
ANSWERS = [{"question": "Why us?", "answer": "I like NLP", "user_confirmed": True}]


@pytest.fixture()
def ready(client, auth):
    doc = upload(client, auth, make_pdf(), "cv.pdf").json()
    prev = client.post(f"{P}/documents/{doc['id']}/parse", headers=auth).json()
    client.post(f"{P}/documents/{doc['id']}/parse/confirm", headers=auth, json=confirm_payload(prev))
    job = client.post(f"{P}/jobs", headers=auth, json=JOB).json()
    client.post(f"{P}/jobs/{job['id']}/verify", headers=auth)
    return job


def resume(client, auth, job_id, provider=None):
    if provider:
        use_provider(provider)
    r = client.post(f"{P}/jobs/{job_id}/resume", headers=auth, json={})
    app.dependency_overrides.pop(get_provider, None)
    return r.json()


def draft_app(client, auth, job, rv, answers=ANSWERS):
    r = client.post(f"{P}/applications", headers=auth,
                    json={"job_id": job["id"], "resume_version_id": rv["id"], "answers": answers})
    assert r.status_code == 201, r.text
    return r.json()


def approve(client, auth, a):
    return client.post(f"{P}/applications/{a['id']}/approve", headers=auth)


def submit(client, auth, a):
    return client.post(f"{P}/applications/{a['id']}/submit", headers=auth)


def flagged_resume(client, auth, job_id):
    return resume(client, auth, job_id, FakeProvider(Draft(summary=ClaimDraft(text="Award-winning engineer", evidence=[]))))


def test_generated_resume_flows_into_approved_package(client, auth, ready):
    rv = resume(client, auth, ready["id"])
    a = draft_app(client, auth, ready, rv)
    assert a["resume_version_id"] == rv["id"] and a["blockers"] == []
    r = approve(client, auth, a)
    assert r.status_code == 200 and len(r.json()["package_hash"]) == 64
    s = submit(client, auth, a)
    assert s.status_code == 200 and s.json()["submission"] == "manual_required" and s.json()["status"] == "approved"


def test_unreviewed_claims_block_approval_until_accepted(client, auth, ready):
    rv = flagged_resume(client, auth, ready["id"])
    a = draft_app(client, auth, ready, rv)
    assert any("factual claims" in b for b in a["blockers"])
    r = approve(client, auth, a)
    assert r.status_code == 422 and r.json()["detail"]["blockers"]
    client.post(f"{P}/resumes/{rv['id']}/claims/{rv['claims'][0]['id']}/review", headers=auth, json={"decision": "accept"})
    assert approve(client, auth, a).status_code == 200


def test_rejected_claim_blocks_forever_for_that_version(client, auth, ready):
    rv = flagged_resume(client, auth, ready["id"])
    a = draft_app(client, auth, ready, rv)
    client.post(f"{P}/resumes/{rv['id']}/claims/{rv['claims'][0]['id']}/review", headers=auth, json={"decision": "reject"})
    assert approve(client, auth, a).status_code == 422


def test_review_change_after_approval_invalidates_it(client, auth, ready):
    rv = flagged_resume(client, auth, ready["id"])
    a = draft_app(client, auth, ready, rv)
    cid = rv["claims"][0]["id"]
    client.post(f"{P}/resumes/{rv['id']}/claims/{cid}/review", headers=auth, json={"decision": "accept"})
    assert approve(client, auth, a).status_code == 200
    client.post(f"{P}/resumes/{rv['id']}/claims/{cid}/review", headers=auth, json={"decision": "reject"})
    r = submit(client, auth, a)
    assert r.status_code == 409
    assert client.get(f"{P}/applications/{a['id']}", headers=auth).json()["status"] == "ready_for_review"


def test_switching_resume_version_revokes_approval(client, auth, ready):
    v1, v2 = resume(client, auth, ready["id"]), resume(client, auth, ready["id"])
    a = draft_app(client, auth, ready, v1)
    approve(client, auth, a)
    r = client.put(f"{P}/applications/{a['id']}/resume", headers=auth, json={"resume_version_id": v2["id"]})
    assert r.status_code == 200 and r.json()["status"] == "ready_for_review" and r.json()["resume_version_id"] == v2["id"]
    assert submit(client, auth, a).status_code == 409  # old approval is gone
    assert approve(client, auth, a).status_code == 200  # fresh approval of the new package


def test_resume_must_belong_to_same_job_and_user(client, auth, ready, session_factory):
    other_job = client.post(f"{P}/jobs", headers=auth, json={**JOB, "title": "Other", "application_url": "https://x.example/o"}).json()
    wrong_job_rv = resume(client, auth, other_job["id"])
    r = client.post(f"{P}/applications", headers=auth, json={"job_id": ready["id"], "resume_version_id": wrong_job_rv["id"]})
    assert r.status_code == 422
    intruder = register(client, "b@example.com")
    rv = resume(client, auth, ready["id"])
    ij = client.post(f"{P}/jobs", headers=intruder, json=JOB).json()
    assert client.post(f"{P}/applications", headers=intruder,
                       json={"job_id": ij["id"], "resume_version_id": rv["id"]}).status_code == 422
    a = draft_app(client, auth, ready, rv)
    assert client.put(f"{P}/applications/{a['id']}/resume", headers=intruder,
                      json={"resume_version_id": rv["id"]}).status_code == 404
    assert client.put(f"{P}/applications/{a['id']}/resume", headers=auth,
                      json={"resume_version_id": wrong_job_rv["id"]}).status_code == 422


def test_cover_letter_change_after_approval_blocks_submission(client, auth, ready, session_factory):
    rv = resume(client, auth, ready["id"])
    with session_factory() as s:
        uid = s.scalar(select(User.id))
        cl = CoverLetter(user_id=uid, job_id=__import__("uuid").UUID(ready["id"]), content="Dear team")
        s.add(cl)
        s.commit()
        clid = str(cl.id)
    a = client.post(f"{P}/applications", headers=auth, json={
        "job_id": ready["id"], "resume_version_id": rv["id"], "cover_letter_id": clid, "answers": ANSWERS}).json()
    assert approve(client, auth, a).status_code == 200
    with session_factory() as s:
        s.get(CoverLetter, __import__("uuid").UUID(clid)).content = "Dear team, now with extra claims"
        s.commit()
    assert submit(client, auth, a).status_code == 409


def test_job_change_after_approval_blocks_submission(client, auth, ready, session_factory):
    rv = resume(client, auth, ready["id"])
    a = draft_app(client, auth, ready, rv)
    approve(client, auth, a)
    with session_factory() as s:
        s.get(Job, __import__("uuid").UUID(ready["id"])).content_hash = "changed-upstream"
        s.commit()
    assert submit(client, auth, a).status_code == 409


def test_answers_change_after_approval_blocks_submission(client, auth, ready):
    a = draft_app(client, auth, ready, resume(client, auth, ready["id"]))
    approve(client, auth, a)
    client.put(f"{P}/applications/{a['id']}/answers", headers=auth,
               json=[{"question": "Why us?", "answer": "different", "user_confirmed": True}])
    assert submit(client, auth, a).status_code == 409


def test_nothing_is_ever_marked_submitted_automatically(client, auth, ready, session_factory):
    a = draft_app(client, auth, ready, resume(client, auth, ready["id"]))
    assert submit(client, auth, a).status_code == 409  # unapproved package cannot be submitted
    approve(client, auth, a)
    for _ in range(2):
        assert submit(client, auth, a).json()["submission"] == "manual_required"
    final = client.get(f"{P}/applications/{a['id']}", headers=auth).json()
    assert final["status"] == "approved" and final["submitted_at"] is None and final["confirmation_reference"] is None
    with session_factory() as s:
        assert not [e for e in s.scalars(select(ApplicationEvent)) if e.new_status in ("submitted", "submission_in_progress")]
    # the failure states cannot be self-asserted by the client either
    for st in ("submission_failed", "submitted"):
        assert client.patch(f"{P}/applications/{a['id']}/status", headers=auth, json={"status": st}).status_code == 409
