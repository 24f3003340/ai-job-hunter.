"""Anthropic provider failure handling, outbound payload and secrecy. All HTTP is mocked."""
import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings, settings
from app.main import app
from app.services.ai_provider import AnthropicProvider, get_provider
from conftest import register
from helpers import confirm_payload, make_pdf, upload

P = "/api/v1"
KEY = "sk-test-CANARY-KEY-0000"
CANARY = "RESPONSE-BODY-CANARY"
OK_BODY = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(
    {"summary": None, "skill_order": ["Python"], "experience": [], "projects": []})}]}


@pytest.fixture()
def ready(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    doc = upload(client, auth, make_pdf(), "cv.pdf").json()
    prev = client.post(f"{P}/documents/{doc['id']}/parse", headers=auth).json()
    client.post(f"{P}/documents/{doc['id']}/parse/confirm", headers=auth, json=confirm_payload(prev))
    client.post(f"{P}/account/ai-consent", headers=auth)
    job = client.post(f"{P}/jobs", headers=auth, json={"title": "NLP Engineer", "company": "Acme",
                                                       "required_skills": ["Python"]}).json()
    yield job
    app.dependency_overrides.pop(get_provider, None)


def wire(responses, sleeps=None, calls=None):
    """Provider whose HTTP layer replays `responses` (Response or Exception) in order."""
    queue = list(responses)

    def handler(request):
        if calls is not None:
            calls.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    prov = AnthropicProvider(client=httpx.Client(transport=httpx.MockTransport(handler)),
                             sleep=(sleeps.append if sleeps is not None else (lambda s: None)))
    app.dependency_overrides[get_provider] = lambda: prov
    return prov


def gen(client, auth, job):
    return client.post(f"{P}/jobs/{job['id']}/resume", headers=auth, json={})


def test_retries_rate_limit_then_succeeds(client, auth, ready):
    sleeps, calls = [], []
    wire([httpx.Response(429, headers={"retry-after": "2"}, text=CANARY), httpx.Response(200, json=OK_BODY)], sleeps, calls)
    assert gen(client, auth, ready).status_code == 201 and len(calls) == 2 and sleeps == [2]


def test_persistent_rate_limit_maps_to_503_with_retry_after(client, auth, ready):
    wire([httpx.Response(429, headers={"retry-after": "7"}, text=CANARY)] * 2)
    r = gen(client, auth, ready)
    assert r.status_code == 503 and r.headers["retry-after"] == "7" and CANARY not in r.text


def test_sleep_is_capped(client, auth, ready):
    sleeps = []
    wire([httpx.Response(429, headers={"retry-after": "600"}), httpx.Response(200, json=OK_BODY)], sleeps)
    gen(client, auth, ready)
    assert sleeps == [5]


@pytest.mark.parametrize("responses,code", [
    ([httpx.ReadTimeout("t"), httpx.ReadTimeout("t")], 504),
    ([httpx.ConnectError("c"), httpx.ConnectError("c")], 502),
    ([httpx.Response(529, text=CANARY)] * 2, 502),
    ([httpx.Response(400, text=CANARY)], 502),
    ([httpx.Response(200, text="<html>" + CANARY)], 502),
    ([httpx.Response(200, json={"stop_reason": "max_tokens", "content": [{"type": "text", "text": "{"}]})], 502),
    ([httpx.Response(200, json={"content": "nope"})], 502),
    ([httpx.Response(200, json={"content": [{"type": "text", "text": '{"experience": [{"ref": 5}]}'}]})], 502),
])
def test_failures_map_to_clean_errors_and_create_no_version(client, auth, ready, responses, code):
    wire(responses)
    r = gen(client, auth, ready)
    assert r.status_code == code and CANARY not in r.text and KEY not in r.text
    assert client.get(f"{P}/jobs/{ready['id']}/resumes", headers=auth).json() == []


def test_rejected_credentials_are_not_retried_and_never_echoed(client, auth, ready, caplog):
    calls = []
    wire([httpx.Response(401, text=f"invalid x-api-key {KEY}")], calls=calls)
    with caplog.at_level(logging.DEBUG):
        r = gen(client, auth, ready)
    assert r.status_code == 502 and len(calls) == 1
    assert KEY not in r.text and KEY not in caplog.text and "credentials" in caplog.text


def test_api_key_travels_only_in_header_and_never_in_payload(client, auth, ready):
    calls = []
    wire([httpx.Response(200, json=OK_BODY)], calls=calls)
    gen(client, auth, ready)
    assert calls[0].headers["x-api-key"] == KEY and KEY not in calls[0].content.decode()


def test_outbound_payload_excludes_and_redacts_personal_data(client, auth, ready):
    p = client.get(f"{P}/profile", headers=auth).json()
    p["experience"][0]["bullets"][0] = "Built a RAG demo; contact Riya Sharma at riya.sharma@example.com or +91 98765 43210"
    p["projects"][0]["description"] = "Maintained by riya sharma"
    client.put(f"{P}/profile", headers=auth, json=p)
    calls = []
    wire([httpx.Response(200, json=OK_BODY)], calls=calls)
    assert gen(client, auth, ready).status_code == 201
    sent = calls[0].content.decode()
    for private in ("Riya", "riya", "Sharma", "riya.sharma@example.com", "98765", "43210", "@example.com"):
        assert private not in sent, private
    assert sent.count("[REDACTED]") >= 3 and "Built a RAG demo" in sent
    assert json.loads(sent)["model"] == settings.anthropic_model


def test_unconfigured_key_never_calls_out(client, auth, ready, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    app.dependency_overrides.pop(get_provider, None)

    def forbidden(*a, **k):
        raise AssertionError("provider was constructed / network call attempted")
    monkeypatch.setattr(AnthropicProvider, "__init__", forbidden)
    assert gen(client, auth, ready).status_code == 503


def test_consent_revocation_blocks_external_provider(client, auth, ready):
    client.delete(f"{P}/account/ai-consent", headers=auth)
    calls = []
    wire([httpx.Response(200, json=OK_BODY)], calls=calls)
    r = gen(client, auth, ready)
    assert r.status_code == 403 and calls == []


def test_secrets_are_masked_in_repr_and_dumps():
    s = Settings(_env_file=None, anthropic_api_key=KEY, smtp_password="smtp-pw-CANARY")
    assert isinstance(s.anthropic_api_key, SecretStr)
    dumped = repr(s) + str(s.model_dump()) + s.model_dump_json()
    assert KEY not in dumped and "smtp-pw-CANARY" not in dumped
