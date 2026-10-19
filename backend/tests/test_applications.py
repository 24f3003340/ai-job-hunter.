from app.models import CoverLetter, ResumeVersion

P = "/api/v1"


def setup_app(client, auth, session_factory, answers=None, with_resume=True):
    job = client.post(f"{P}/jobs", headers=auth, json={
        "title": "ML Engineer", "company": "Acme", "application_url": "https://acme.example/apply"}).json()
    client.post(f"{P}/jobs/{job['id']}/verify", headers=auth)
    body = {"job_id": job["id"], "answers": answers if answers is not None else
            [{"question": "Why us?", "answer": "I like ML", "user_confirmed": True}]}
    if with_resume:
        with session_factory() as s:
            from app.models import Job, User
            from sqlalchemy import select
            user = s.scalar(select(User))
            rv = ResumeVersion(user_id=user.id, job_id=__import__("uuid").UUID(job["id"]), source_profile_version=1, content_json={"a": 1})
            s.add(rv)
            s.commit()
            body["resume_version_id"] = str(rv.id)
    return job, client.post(f"{P}/applications", headers=auth, json=body).json()


def test_cannot_approve_with_unconfirmed_answer(client, auth, session_factory):
    _, app = setup_app(client, auth, session_factory,
                       answers=[{"question": "Q", "answer": "A", "user_confirmed": False}])
    r = client.post(f"{P}/applications/{app['id']}/approve", headers=auth)
    assert r.status_code == 422 and r.json()["detail"]["blockers"]


def test_cannot_approve_without_resume(client, auth, session_factory):
    _, app = setup_app(client, auth, session_factory, with_resume=False)
    assert client.post(f"{P}/applications/{app['id']}/approve", headers=auth).status_code == 422


def test_submit_requires_approval(client, auth, session_factory):
    _, app = setup_app(client, auth, session_factory)
    assert client.post(f"{P}/applications/{app['id']}/submit", headers=auth).status_code == 409


def test_approve_then_submit_is_manual_and_not_marked_submitted(client, auth, session_factory):
    _, app = setup_app(client, auth, session_factory)
    assert client.post(f"{P}/applications/{app['id']}/approve", headers=auth).status_code == 200
    r = client.post(f"{P}/applications/{app['id']}/submit", headers=auth)
    assert r.status_code == 200 and r.json()["submission"] == "manual_required"
    assert r.json()["status"] == "approved"
    assert r.json()["manual_application_url"] == "https://acme.example/apply"


def test_editing_answers_revokes_approval(client, auth, session_factory):
    _, app = setup_app(client, auth, session_factory)
    client.post(f"{P}/applications/{app['id']}/approve", headers=auth)
    r = client.put(f"{P}/applications/{app['id']}/answers", headers=auth,
                   json=[{"question": "Why us?", "answer": "Changed", "user_confirmed": True}])
    assert r.json()["status"] == "ready_for_review"
    assert client.post(f"{P}/applications/{app['id']}/submit", headers=auth).status_code == 409


def test_tampered_package_blocks_submit(client, auth, session_factory):
    _, app = setup_app(client, auth, session_factory)
    client.post(f"{P}/applications/{app['id']}/approve", headers=auth)
    with session_factory() as s:  # simulate a change that bypasses the answers endpoint
        from app.models import ApplicationAnswer
        a = s.query(ApplicationAnswer).one()
        a.answer = "Sneaky edit"
        s.commit()
    assert client.post(f"{P}/applications/{app['id']}/submit", headers=auth).status_code == 409
    assert client.get(f"{P}/applications/{app['id']}", headers=auth).json()["status"] == "ready_for_review"


def test_user_cannot_mark_submitted_without_approval_or_flag(client, auth, session_factory):
    _, app = setup_app(client, auth, session_factory)
    r = client.patch(f"{P}/applications/{app['id']}/status", headers=auth,
                     json={"status": "submitted", "user_reported_submission": True})
    assert r.status_code == 409
    client.post(f"{P}/applications/{app['id']}/approve", headers=auth)
    r = client.patch(f"{P}/applications/{app['id']}/status", headers=auth, json={"status": "submitted"})
    assert r.status_code == 409
    r = client.patch(f"{P}/applications/{app['id']}/status", headers=auth,
                     json={"status": "submitted", "user_reported_submission": True})
    assert r.status_code == 200 and r.json()["submission_method"] == "manual_user_reported"


def test_duplicate_active_application_rejected(client, auth, session_factory):
    job, _ = setup_app(client, auth, session_factory)
    assert client.post(f"{P}/applications", headers=auth, json={"job_id": job["id"]}).status_code == 409


def test_job_dedup_by_url(client, auth):
    j = {"title": "A", "company": "B", "application_url": "https://x.example/job/1?utm=1"}
    a = client.post(f"{P}/jobs", headers=auth, json=j).json()
    b = client.post(f"{P}/jobs", headers=auth, json={**j, "application_url": "https://x.example/job/1"}).json()
    assert a["id"] == b["id"]
