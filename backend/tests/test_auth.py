from conftest import register

P = "/api/v1"


def test_requires_auth(client):
    assert client.get(f"{P}/profile").status_code == 401
    assert client.get(f"{P}/applications").status_code == 401


def test_logout_invalidates_session(client, auth):
    assert client.get(f"{P}/profile", headers=auth).status_code == 200
    assert client.post(f"{P}/auth/logout", headers=auth).status_code == 204
    assert client.get(f"{P}/profile", headers=auth).status_code == 401


def test_login_lockout(client, auth):
    for _ in range(5):
        r = client.post(f"{P}/auth/login", json={"email": "a@example.com", "password": "wrong-password-1"})
        assert r.status_code == 401
    r = client.post(f"{P}/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 429


def test_duplicate_registration_rejected(client, auth):
    r = client.post(f"{P}/auth/register", json={"email": "A@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 409


def test_user_isolation(client, auth):
    job = client.post(f"{P}/jobs", headers=auth, json={"title": "ML Engineer", "company": "X"}).json()
    other = register(client, "b@example.com")
    assert client.get(f"{P}/jobs/{job['id']}", headers=other).status_code == 404
    assert client.get(f"{P}/jobs/{job['id']}/match", headers=other).status_code == 404
    assert client.post(f"{P}/applications", headers=other, json={"job_id": job["id"]}).status_code == 404
    assert client.get(f"{P}/jobs", headers=other).json() == []


def test_account_deletion(client, auth):
    client.post(f"{P}/jobs", headers=auth, json={"title": "ML Engineer", "company": "X"})
    assert client.delete(f"{P}/account", headers=auth).status_code == 204
    assert client.get(f"{P}/profile", headers=auth).status_code == 401
