"""Against a REAL clamd. Opt-in:
    JOBHUNTER_TEST_CLAMAV_HOST=127.0.0.1 [JOBHUNTER_TEST_CLAMAV_PORT=3310] pytest -m external tests/external/test_clamav_real.py
Uses the standard EICAR antivirus test string (harmless by design), assembled at runtime so this file is not
itself flagged by scanners. Status: NOT yet run in this project's CI/sandbox (no clamd available) - see docs/REPORT.md."""
import os

import pytest

from app.config import settings
from app.services import uploads
from helpers import make_pdf

HOST = os.environ.get("JOBHUNTER_TEST_CLAMAV_HOST", "")
pytestmark = [pytest.mark.external, pytest.mark.skipif(not HOST, reason="JOBHUNTER_TEST_CLAMAV_HOST not set")]
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE" + "!$H+H*").encode()


@pytest.fixture(autouse=True)
def _point_at_clamd(monkeypatch):
    monkeypatch.setattr(settings, "clamav_host", HOST)
    monkeypatch.setattr(settings, "clamav_port", int(os.environ.get("JOBHUNTER_TEST_CLAMAV_PORT", "3310")))


def test_clamd_alive():
    assert uploads.ping() is True and uploads.scanner_status() == {"configured": True, "ok": True}


def test_clean_document_passes():
    assert uploads.scan(make_pdf()) == "clean"


def test_eicar_is_detected_and_rejected():
    with pytest.raises(uploads.UploadRejected) as e:
        uploads.scan(EICAR)
    assert e.value.status_code == 422


def test_unreachable_scanner_fails_closed_in_production(monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "clamav_port", 1)
    with pytest.raises(uploads.UploadRejected) as e:
        uploads.scan(make_pdf())
    assert e.value.status_code == 503
