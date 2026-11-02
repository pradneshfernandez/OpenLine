"""Phone simulator: browser mic over the Twilio media-stream protocol to /ws, no carrier."""

from app.db import SessionLocal
from app.models import Interview
from tests.test_survey_flow import trial_version  # noqa: F401  (fixture)


def test_page_and_form_picker(client, trial_version):  # noqa: F811
    page = client.get("/phone-sim")
    assert page.status_code == 200 and "8 kHz" in page.text and "audio/x-mulaw" in page.text
    forms = client.get("/api/phone-sim/forms").json()
    assert any(f["version_id"] == trial_version for f in forms)


def test_sim_call_creates_a_phone_interview_with_a_sim_call_id(client, trial_version):  # noqa: F811
    r = client.post("/api/phone-sim/calls", json={"form_version_id": trial_version, "language": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["call_sid"].startswith("SIM")  # /ws skips the Twilio REST hang-up for these
    with SessionLocal() as db:
        i = db.get(Interview, body["interview_id"])
        assert (i.channel, i.language, i.status, i.created_by) == ("phone", "hi", "queued", "tester")


def test_unknown_form_version_is_rejected(client):
    assert client.post("/api/phone-sim/calls", json={"form_version_id": 999999}).status_code == 404
    assert client.post("/api/phone-sim/calls", json={"form_version_id": 1, "language": "fr"}).status_code == 422
