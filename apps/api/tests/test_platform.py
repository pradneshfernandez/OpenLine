"""Campaigns, review, KoboToolbox export, simulated respondents and voices — without phones,
Kobo or Gnani: the dialler, Kobo HTTP and TTS are replaced with fakes."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app import campaigns, kobo, simulation
from app.db import SessionLocal
from app.models import Answer, Campaign, FormVersion, Interview
from app.voice import calls
from app.voice.config import VoiceSettings
from tests.conftest import SAMPLES, upload

CSV = (b"respondent_id,phone,language\n"
       b"R1,98765 43210,hi\n"
       b"R2,+919812345678,English\n"
       b"R3,12345,en\n"
       b"R4,9876543210,hi\n"
       b"R5,+919800011122,french\n"
       b"R6,+919800011133,en\n")


@pytest.fixture(scope="module")
def version_id(client, project_id):
    body = upload(client, project_id, SAMPLES / "trial" / "1_clean_phone_ready.xlsx").json()
    assert body["ok"], body["errors"]
    return body["version"]["id"]


@pytest.fixture()
def calling(monkeypatch):
    """Calling configured, Twilio replaced: every dial succeeds and is recorded."""
    cfg = VoiceSettings(gnani_api_key="g", llm_api_key="l", twilio_account_sid="AC1", twilio_auth_token="t",
                        twilio_from_number="+15005550006", public_base_url="https://example.ngrok.app")
    monkeypatch.setattr(calls, "voice_settings", lambda: cfg)
    dialled = []
    monkeypatch.setattr(calls, "_dial", lambda to, twiml, cb: dialled.append(to) or f"CA{len(dialled)}")
    return dialled


def _finish(interview_id: int, status: str, when: str = "", at: datetime | None = None):
    with SessionLocal() as db:
        i = db.get(Interview, interview_id)
        i.status, i.callback_when = status, when
        i.ended_at = at or datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)
        db.commit()


# ---------------------------------------------------------------------------
# Campaigns


def test_csv_validation_counts_and_masks(client, project_id):
    r = client.post(f"/api/projects/{project_id}/campaigns/validate", files={"file": ("r.csv", CSV)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"] == {"ok": 3, "invalid_number": 1, "duplicate": 1, "unknown_language": 1}
    assert body["languages"] == {"en": 2, "hi": 1}
    assert "98765" not in str(body) and "+91 98••• ••210" in str(body)  # valid numbers only masked
    assert any(p["phone"] == "12345" for p in body["problems"])  # an invalid one is shown to fix it


def test_csv_needs_columns(client, project_id):
    r = client.post(f"/api/projects/{project_id}/campaigns/validate", files={"file": ("r.csv", b"id,mobile\n1,2\n")})
    assert r.status_code == 422 and "respondent_id" in r.json()["detail"]


def test_campaign_runs_retries_and_stops(client, project_id, version_id, calling):
    r = client.post(f"/api/projects/{project_id}/campaigns", files={"file": ("wave1.csv", CSV)}, data={
        "name": "Wave 1", "form_version_id": str(version_id), "start": "true",
        "settings": '{"concurrency": 2, "max_attempts": 2, "min_gap_minutes": 60, '
                    '"calling_start": "00:00", "calling_end": "23:59"}'})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert r.json()["total"] == 3 and r.json()["left_out"] == 3

    t0 = datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)
    assert asyncio.run(campaigns.tick(t0)) == 2  # concurrency 2
    assert asyncio.run(campaigns.tick(t0)) == 0  # both lines busy
    detail = client.get(f"/api/campaigns/{cid}").json()
    assert len(detail["in_progress"]) == 2
    assert "98765" not in str(detail)
    r1, r2, r3 = detail["respondents"]
    _finish(r1["interview_ids"][0], "no-answer")
    _finish(r2["interview_ids"][0], "refused")
    assert asyncio.run(campaigns.tick(t0)) == 1  # R6 now; R1 waits for the gap
    detail = client.get(f"/api/campaigns/{cid}").json()
    by = {r["respondent_id"]: r for r in detail["respondents"]}
    assert by["R1"]["state"] == "waiting" and by["R1"]["last_outcome"] == "no-answer"
    assert by["R2"]["state"] == "stopped"  # refused: never called again
    assert [u["respondent_id"] for u in detail["upcoming"]] == ["R1"]

    _finish(by["R6"]["interview_ids"][0], "callback", "tomorrow 6 pm")
    later = t0 + timedelta(minutes=61)
    assert asyncio.run(campaigns.tick(later)) == 2  # R1 retry + R6 callback
    detail = client.get(f"/api/campaigns/{cid}").json()
    by = {r["respondent_id"]: r for r in detail["respondents"]}
    assert by["R1"]["attempts"] == 2 and by["R6"]["callback_when"] == "tomorrow 6 pm"
    _finish(by["R1"]["interview_ids"][-1], "busy")
    _finish(by["R6"]["interview_ids"][-1], "completed")
    asyncio.run(campaigns.tick(later + timedelta(minutes=1)))
    detail = client.get(f"/api/campaigns/{cid}").json()
    by = {r["respondent_id"]: r for r in detail["respondents"]}
    assert by["R1"]["state"] == "done"  # out of attempts
    assert detail["status"] == "finished"
    assert detail["outcomes"]["completed"] == 1 and detail["outcomes"]["refused"] == 1
    assert len(calling) == 5


def test_campaign_respects_calling_hours_and_pause(client, project_id, version_id, calling):
    r = client.post(f"/api/projects/{project_id}/campaigns", files={"file": ("w.csv", CSV)}, data={
        "name": "Hours", "form_version_id": str(version_id), "start": "false",
        "settings": '{"calling_start": "09:00", "calling_end": "19:00"}'})
    cid = r.json()["id"]
    night = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)  # 22:30 in India
    assert asyncio.run(campaigns.tick(night)) == 0  # draft
    assert client.post(f"/api/campaigns/{cid}/action", json={"action": "start"}).json()["status"] == "running"
    assert asyncio.run(campaigns.tick(night)) == 0  # outside calling hours
    assert client.post(f"/api/campaigns/{cid}/action", json={"action": "pause"}).json()["status"] == "paused"
    assert asyncio.run(campaigns.tick(night.replace(hour=6))) == 0  # paused
    assert client.post(f"/api/campaigns/{cid}/action", json={"action": "pause"}).status_code == 409
    assert client.delete(f"/api/campaigns/{cid}").status_code == 409  # paused, not finished
    client.post(f"/api/campaigns/{cid}/action", json={"action": "finish"})
    assert client.delete(f"/api/campaigns/{cid}").json() == {"ok": True}
    assert client.get(f"/api/campaigns/{cid}").status_code == 404


def test_campaign_pauses_when_calling_not_configured(client, project_id, version_id):
    r = client.post(f"/api/projects/{project_id}/campaigns", files={"file": ("w.csv", CSV)}, data={
        "name": "No keys", "form_version_id": str(version_id), "start": "true",
        "settings": '{"calling_start": "00:00", "calling_end": "23:59"}'})
    cid = r.json()["id"]
    asyncio.run(campaigns.tick())
    d = client.get(f"/api/campaigns/{cid}").json()
    assert d["status"] == "paused" and all(x["attempts"] == 0 for x in d["respondents"])


# ---------------------------------------------------------------------------
# Review + effective answers


def _interview_with_answers(version_id: int) -> int:
    with SessionLocal() as db:
        i = Interview(form_version_id=version_id, language="hi", status="completed", participant_label="rev",
                      final_answers={"consent": "yes", "age": "45", "hh_size": "6", "child_age[1]": "9"})
        i.answers = [
            Answer(question_name="consent", value="yes", confidence=0.98, attempts=1),
            Answer(question_name="age", value="45", confidence=0.55, attempts=1),  # low confidence
            Answer(question_name="hh_size", value="6", confidence=0.9, attempts=3),  # >2 attempts
            Answer(question_name="child_age", repeat_index=[0], value="9", confidence=0.9, attempts=1,
                   flagged=True, second_pass_value="19"),  # mismatch
        ]
        db.add(i)
        db.commit()
        return i.id


def test_review_queue_actions_and_log(client, project_id, version_id):
    iid = _interview_with_answers(version_id)
    q = client.get(f"/api/projects/{project_id}/review", params={"interview_id": iid}).json()
    group = next(g for g in q["groups"] if g["interview"]["id"] == iid)
    keys = {a["key"]: a for a in group["answers"]}
    assert set(keys) == {"age", "hh_size", "child_age[1]"}
    assert keys["child_age[1]"]["flags"] == ["mismatch"]
    assert client.get(f"/api/projects/{project_id}/review/count").json()["pending"] >= 3

    assert client.post(f"/api/answers/{keys['age']['id']}/review", json={"action": "reject"}).status_code == 422
    assert client.post(f"/api/answers/{keys['age']['id']}/review",
                       json={"action": "edit", "value": "47", "reason": "Listened twice"}).status_code == 200
    assert client.post(f"/api/answers/{keys['hh_size']['id']}/review",
                       json={"action": "reject", "reason": "Answering for someone else"}).status_code == 200
    r = client.post(f"/api/interviews/{iid}/review", json={"action": "approve"}).json()
    assert r["review_state"] == "approved" and r["approved_answers"] >= 1  # consent + child_age

    with SessionLocal() as db:
        i = db.get(Interview, iid)
        from app.review import effective_answers
        eff = effective_answers(i)
        assert eff["age"] == "47" and eff["hh_size"] is None and eff["child_age[1]"] == "9"
        assert i.final_answers["age"] == "45"  # raw value kept
    edited = client.get(f"/api/projects/{project_id}/review", params={"state": "edited", "interview_id": iid}).json()
    assert edited["groups"][0]["answers"][0]["reviewed_value"] == "47"
    log = client.get(f"/api/projects/{project_id}/review/log").json()
    assert [e["action"] for e in log[:3]] == ["interview_approved", "rejected", "edited"]
    assert log[2]["old_value"] == "45" and log[2]["new_value"] == "47" and log[2]["user"] == "tester"


# ---------------------------------------------------------------------------
# KoboToolbox


def test_kobo_connect_pick_and_send(client, project_id, version_id, monkeypatch):
    sent = []

    def fake_http(method, url, token, body=None):
        assert token == "tok1234"
        if url.endswith("/api/v2/assets/?asset_type=survey&limit=200&format=json"):
            return {"results": [{"uid": "aBc", "name": "Household services", "has_deployment": True}]}
        if "/api/v2/assets/aBc/" in url:
            return {"name": "Household services", "deployment__identifier": "https://kc.example.org/me/forms/aBc"}
        if url == "https://kc.example.org/api/v1/submissions":
            sent.append(body)
            return {"message": "Successful submission."}
        raise AssertionError(url)

    monkeypatch.setattr(kobo, "http", fake_http)
    r = client.put(f"/api/projects/{project_id}/kobo", json={"server_url": "kf.example.org", "token": "tok1234"})
    assert r.status_code == 200, r.text
    assert r.json()["assets"][0]["uid"] == "aBc" and "tok1234" not in r.text and r.json()["token_masked"] == "••••1234"
    r = client.put(f"/api/projects/{project_id}/kobo/asset", json={"asset_uid": "aBc"}).json()
    assert r["kc_url"] == "https://kc.example.org" and r["asset_name"] == "Household services"

    iid = _interview_with_answers(version_id)
    assert client.post(f"/api/interviews/{iid}/kobo").status_code == 409  # not approved yet
    client.post(f"/api/interviews/{iid}/review", json={"action": "approve"})
    rows = client.get(f"/api/projects/{project_id}/kobo/interviews").json()
    assert any(x["id"] == iid and x["kobo_state"] == "not_sent" for x in rows)
    res = client.post(f"/api/projects/{project_id}/kobo/send", json={}).json()
    assert res["failed"] == 0 and res["sent"] >= 1
    sub = next(s for s in sent if s["submission"]["main"]["age"] == "45")
    assert sub["id"] == "aBc"
    assert sub["submission"]["consent"] == "yes"
    assert sub["submission"]["main"]["child"] == [{"child_age": "9"}]  # repeat nested in its group
    assert sub["submission"]["meta"]["instanceID"].startswith("uuid:")
    assert client.get(f"/api/projects/{project_id}/kobo").json()["connected"]
    assert client.delete(f"/api/projects/{project_id}/kobo").json()["connected"] is False


# ---------------------------------------------------------------------------
# Simulated respondents


def test_answer_key_follows_the_form(version_id):
    with SessionLocal() as db:
        v = db.get(FormVersion, version_id)
        key = simulation.make_answer_key(v, "en", seed=3)
        again = simulation.make_answer_key(v, "en", seed=3)
        hi = simulation.make_answer_key(v, "hi", seed=3)
    a = key["answers"]
    assert key == again  # deterministic per seed
    assert a["consent"] == "yes"  # consents, so the survey continues
    assert 18 <= int(a["age"]) <= 70
    assert a["children_school"] in ("yes", "no")
    if a["children_school"] == "yes" and a.get("num_children", "dk") != "dk":
        n = int(a["num_children"])
        assert 1 <= n < int(a["hh_size"])
        assert all(f"child_age[{k}]" in a for k in range(1, n + 1))
    assert any("हाँ" in s["say"] or "हां" in s["say"] for s in hi["script"] if s["name"] == "consent")


def test_personas_say_the_answer_differently():
    import random

    step = {"name": "age", "type": "integer", "value": "34", "say": "34", "options": []}
    rnd = random.Random(1)
    assert simulation.utterance(step, "cooperative", "en", rnd) == "34"
    assert simulation.utterance(step, "vague", "en", rnd) == "Umm... I think it's 34"
    assert simulation.utterance(step, "correcting", "en", rnd) == "36... no sorry, 34"
    assert simulation.utterance(step, "mixed", "en", rnd) == "Haan ji, 34"
    assert simulation.utterance(step, "correcting", "hi", rnd) == "36... नहीं नहीं, 34"


def test_simulation_report_scores_against_key(client, project_id, version_id):
    from app.models import SimulationRun

    with SessionLocal() as db:
        run = SimulationRun(form_version_id=version_id, settings={"runs": 2, "personas": ["cooperative"],
                                                                  "languages": ["en"]}, status="finished")
        db.add(run)
        db.commit()
        t = datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)
        for n, got_age in enumerate(["34", "43"]):
            i = Interview(form_version_id=version_id, language="en", channel="simulated", persona="cooperative",
                          simulation_run_id=run.id, status="completed", started_at=t, ended_at=t + timedelta(seconds=60),
                          answer_key={"answers": {"consent": "yes", "age": "34"},
                                      "script": [{"name": "consent"}, {"name": "age"}]},
                          final_answers={"consent": "yes", "age": got_age})
            i.answers = [Answer(question_name="consent", value="yes", attempts=1),
                         Answer(question_name="age", value=got_age, heard_text=f"heard {got_age}", attempts=1 + n)]
            db.add(i)
        db.commit()
        run_id = run.id
    r = client.get(f"/api/simulations/{run_id}").json()
    rep = r["report"]
    assert rep["accuracy"] == {"correct": 3, "total": 4, "rate": 0.75}
    assert rep["completion_rate"] == 1.0 and rep["reasks"] == 1
    assert rep["seconds_per_question"] == 30.0
    assert [g["question"] for g in rep["grid"]] == ["consent", "age"]
    assert rep["grid"][1]["en"] == {"correct": 1, "total": 2}
    assert rep["misses"][0]["expected"] == "34" and rep["misses"][0]["got"] == "43"
    assert any(x["id"] == run_id for x in client.get(f"/api/projects/{project_id}/simulations").json())


def test_simulation_needs_keys(client, project_id, version_id):
    r = client.post(f"/api/projects/{project_id}/simulations", json={"form_version_id": version_id, "runs": 2})
    assert r.status_code == 503 and "LLM_API_KEY" in r.json()["detail"]


def test_answer_key_preview(client, version_id):
    r = client.get(f"/api/form-versions/{version_id}/answer-key", params={"persona": "vague"}).json()
    assert r["script"][0]["name"] == "consent" and r["script"][1]["utterance"].startswith("Umm")


# ---------------------------------------------------------------------------
# Voices + Listen


def test_voices_saved_per_language(client, project_id):
    assert "Nalini" in client.get("/api/voices").json()["voices"]
    r = client.put(f"/api/projects/{project_id}/voices", json={"hi": {"voice": "Kaveri", "speed": 0.9}})
    assert r.status_code == 200 and r.json()["hi"] == {"voice": "Kaveri", "speed": 0.9}
    assert client.put(f"/api/projects/{project_id}/voices", json={"en": {"voice": "Nobody"}}).status_code == 422


def test_listen_uses_project_voice(client, project_id, monkeypatch):
    from app.voice import speech

    seen = {}
    monkeypatch.setattr(speech, "synthesize", lambda text, lang, voice, speed: seen.update(
        text=text, lang=lang, voice=voice, speed=speed) or b"RIFFfake")
    client.put(f"/api/projects/{project_id}/voices", json={"hi": {"voice": "Kaveri", "speed": 0.9}})
    r = client.post("/api/tts", json={"text": "आपकी उम्र क्या है?", "lang": "hi", "project_id": project_id})
    assert r.status_code == 200 and r.content == b"RIFFfake" and r.headers["content-type"] == "audio/wav"
    assert seen == {"text": "आपकी उम्र क्या है?", "lang": "hi", "voice": "Kaveri", "speed": 0.9}


def test_campaign_scheduler_does_not_touch_other_statuses(version_id):
    with SessionLocal() as db:
        assert all(c.status in ("draft", "running", "paused", "finished") for c in db.query(Campaign))


def test_dont_know_persona_and_noise_bed(version_id):
    import numpy as np

    with SessionLocal() as db:
        v = db.get(FormVersion, version_id)
        keys = [simulation.make_answer_key(v, "en", seed=s, persona="dont_know") for s in range(6)]
    answers = [val for k in keys for q, val in k["answers"].items() if q != "consent"]
    assert "dk" in answers and any(val != "dk" for val in answers)
    assert all(k["answers"]["consent"] == "yes" for k in keys)  # never refuses consent

    silence = b"\x00" * 320
    assert simulation.NoiseBed(None).mix(silence) == silence  # clean line
    for snr in (15.0, 5.0):
        bed = simulation.NoiseBed(snr, seed=1)
        out = np.frombuffer(b"".join(bed.mix(silence) for _ in range(50)), dtype=np.int16).astype(float)
        rms = np.sqrt(np.mean(out ** 2))
        assert abs(20 * np.log10(simulation.SPEECH_RMS / rms) - snr) < 1.5


def test_report_breaks_down_by_noise_persona_and_delay(client, version_id):
    from app.models import SimulationRun, TurnLog

    with SessionLocal() as db:
        run = SimulationRun(form_version_id=version_id, settings={"runs": 2}, status="finished")
        db.add(run)
        db.commit()
        for noise, got in (("clean", "34"), ("5db", "44")):
            i = Interview(form_version_id=version_id, language="en", channel="simulated", persona="vague",
                          simulation_run_id=run.id, status="completed", final_answers={"age": got},
                          answer_key={"answers": {"age": "34"}, "script": [], "noise": noise})
            i.turns = [TurnLog(t=1, speaker="agent", text="?", latency_ms=1200),
                       TurnLog(t=2, speaker="agent", text="?", latency_ms=1800)]
            db.add(i)
        db.commit()
        run_id = run.id
    rep = client.get(f"/api/simulations/{run_id}").json()["report"]
    assert rep["by_noise"] == [{"noise": "clean", "correct": 1, "total": 1}, {"noise": "5db", "correct": 0, "total": 1}]
    assert rep["by_persona"] == [{"persona": "vague", "correct": 1, "total": 2}]
    assert rep["reply_delay"]["avg"] == 1.5 and rep["reply_delay"]["turns"] == 4


def test_scoring_ignores_punctuation_and_order():
    n = simulation._norm
    assert n("बिजली कटौती।") == n("बिजली कटौती")
    assert n("Water supply.") == n("water supply")
    assert n("34") == n(34.0) and n("a b") == n("b a")
    assert n("34") != n("43")
