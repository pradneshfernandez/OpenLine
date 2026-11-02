"""Public demo (/demo): mock survey over the browser phone line, safe to share in demo-only mode."""

import pytest

from app import demo, services
from app.config import settings
from app.db import SessionLocal
from app.models import Interview
from tests.test_survey_flow import trial_version  # noqa: F401  (fixture)


class _Ready:
    stt_auto_language, stt_languages = False, ""

    def missing(self, *_):
        return []


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(demo, "voice_settings", lambda: _Ready())


def test_page_and_engine_are_served(client):
    page = client.get("/demo")
    assert page.status_code == 200 and "PhoneLine.dial" in page.text
    js = client.get("/static/phone_line.js")
    assert js.status_code == 200 and "audio/x-mulaw" in js.text


def test_start_needs_keys(client):
    assert client.get("/api/demo/status").json()["ready"] is False   # tests run without keys
    assert client.post("/api/demo/calls", json={"language": "en"}).status_code == 503


def test_demo_form_is_phone_ready_and_uploaded_once(client, ready):
    a = client.post("/api/demo/calls", json={"language": "hi"}).json()
    b = client.post("/api/demo/calls", json={"language": "en"}).json()
    with SessionLocal() as db:
        ia, ib = db.get(Interview, a["interview_id"]), db.get(Interview, b["interview_id"])
        assert ia.form_version_id == ib.form_version_id                # one demo form
        assert (ia.created_by, ia.channel, ia.language) == ("demo", "phone", "hi")
        report = services.latest_report(db, ia.form_version_id)
        assert report.status == "ready", [(i.check_code, i.severity, i.message) for i in report.issues]
        for i in (ia, ib):  # free the lines for the next tests
            i.status = "completed"
        db.commit()
    assert a["call_sid"].startswith("SIM")


def test_lines_are_limited(client, ready, monkeypatch):
    with SessionLocal() as db:  # start from no live demo calls
        for i in db.query(Interview).filter(Interview.created_by == "demo"):
            i.status = "completed"
        db.commit()
    monkeypatch.setattr(settings, "demo_max_calls", 1)
    first = client.post("/api/demo/calls", json={"language": "en"})
    assert first.status_code == 200
    assert client.post("/api/demo/calls", json={"language": "en"}).status_code == 429
    live = client.get(f"/api/demo/calls/{first.json()['interview_id']}").json()
    assert live["status"] == "queued" and live["turns"] == [] and live["answers"] == []
    with SessionLocal() as db:
        db.get(Interview, first.json()["interview_id"]).status = "completed"
        db.commit()


def test_only_demo_calls_are_visible(client, trial_version):  # noqa: F811
    with SessionLocal() as db:
        i = Interview(form_version_id=trial_version, language="en", created_by="tester")
        db.add(i)
        db.commit()
        other = i.id
    assert client.get(f"/api/demo/calls/{other}").status_code == 404
    assert client.get(f"/api/demo/calls/{other}/recording").status_code == 404
    assert not demo.is_demo_call(other)


def test_demo_only_mode_hides_the_rest_of_the_api(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_only", True)
    assert client.get("/demo").status_code == 200
    assert client.get("/api/demo/status").status_code == 200
    assert client.get("/static/phone_line.js").status_code == 200
    for path in ("/api/projects", "/phone-sim", "/api/phone-sim/forms", "/docs", "/api/voice/status"):
        assert client.get(path).status_code == 404, path
