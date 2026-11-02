"""Robustness (§5.7) and the full-call transcript (§5.6.2), without audio, LLM or network.

- an answer that stays invalid is recorded as "unclear", flagged, and the call moves on
- calls left in progress by a crash are closed as partial with their saved answers
- a retry of a partial campaign call resumes from the first unanswered question (consent re-asked)
- the transcript splits the stereo recording by channel, chunks it, and merges segments by time
"""

import array
import asyncio
import io
import wave
from dataclasses import dataclass
from types import SimpleNamespace

from app import storage
from app.db import SessionLocal
from app.models import Answer, Campaign, CampaignRespondent, FormVersion, Interview
from app.voice import transcript as tr
from app.voice.recovery import close_interrupted_calls, preload_previous_answers
from app.voice.runner import UNCLEAR
from tests.test_survey_flow import Bot, trial_version  # noqa: F401  (fixture)


def test_invalid_three_times_is_recorded_as_unclear_and_flagged(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    b.answer("yes")
    assert b.node_name.startswith("q:age")
    for _ in range(2):
        assert b.answer(200)["status"] == "invalid"
    assert b.node_name.startswith("q:age")
    assert b.answer(200)["status"] == "ok"  # third invalid answer: give up on this question
    assert b.node_name.startswith("q:hh_size") and "move on" in b.said[-1]
    _, _, rows = b.interview()
    age = rows[("age", ())]
    assert age.code == UNCLEAR and age.flagged and age.value is None
    for v in [5, "no", "yes", "water supply"]:
        b.answer(v)
    status, final, _ = b.interview()
    assert status == "completed" and final["age"] == UNCLEAR


def test_consent_is_never_given_up_on(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    for _ in range(4):
        b.answer("maybe")
    assert b.node_name == "opening"  # still asking for consent


def test_crashed_call_is_closed_as_partial(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    b.answer("yes")
    b.answer(34)
    with SessionLocal() as db:
        assert db.get(Interview, b.interview_id).status == "in-progress"
    assert close_interrupted_calls() >= 1
    with SessionLocal() as db:
        i = db.get(Interview, b.interview_id)
        assert i.status == "partial" and "restarted" in i.error and i.ended_at is not None
        assert i.final_answers["age"] == "34" and i.final_answers["consent"] == "yes"


def _respondent(version_id: int) -> int:
    with SessionLocal() as db:
        v = db.get(FormVersion, version_id)
        c = Campaign(project_id=v.form.project_id, name="resume test", form_version_id=version_id)
        c.respondents = [CampaignRespondent(respondent_id="R1", phone="+910000000000", language="en")]
        db.add(c)
        db.commit()
        return c.respondents[0].id


def test_retry_resumes_from_first_unanswered_question(trial_version):
    rid = _respondent(trial_version)
    first = Bot(trial_version, "en")
    with SessionLocal() as db:
        db.get(Interview, first.interview_id).campaign_respondent_id = rid
        db.commit()
    first.open()
    for v in ["yes", 34, 5]:
        first.answer(v)
    first.session.close()  # call dropped
    assert first.interview()[0] == "partial"

    second = Bot(trial_version, "en")
    with SessionLocal() as db:
        db.get(Interview, second.interview_id).campaign_respondent_id = rid
        db.commit()
    second.session.resumed_answers = preload_previous_answers(second.interview_id, second.flow.runner)
    assert second.session.resumed_answers == 2  # age and hh_size; consent is asked again
    second.open()
    assert "continue where we left off" in second.said[0] and "Do you agree" in second.said[0]
    second.answer("yes")
    assert "school" in second.said[-1].lower()  # straight to the question after hh_size
    for v in ["no", "yes", "water supply"]:
        second.answer(v)
    status, final, rows = second.interview()
    assert status == "completed" and final["age"] == 34 and final["hh_size"] == 5
    assert rows[("age", ())].heard_text == "34"
    with SessionLocal() as db:
        assert db.get(Interview, second.interview_id).resumed_from_id == first.interview_id


def test_no_resume_outside_campaigns(trial_version):
    b = Bot(trial_version, "en")
    assert preload_previous_answers(b.interview_id, b.flow.runner) == 0


# ---------------------------------------------------------------- full-call transcript


def _stereo_wav(seconds: float, rate: int = 8000) -> bytes:
    n = int(seconds * rate)
    samples = array.array("h", [0] * (2 * n))
    for k in range(n):
        samples[2 * k] = 100     # respondent (left)
        samples[2 * k + 1] = -100  # agent (right)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def test_make_files_splits_channels_and_chunks():
    files = tr.make_files(_stereo_wav(10), max_bytes=8000 * 2 * 4 + 44)  # 4 s per chunk
    names = [f[0] for f in files]
    assert names == ["respondent_00.wav", "respondent_01.wav", "respondent_02.wav",
                     "agent_00.wav", "agent_01.wav", "agent_02.wav"]
    assert [f[3] for f in files[:3]] == [0.0, 4.0, 8.0]
    rate, chans = tr.split_channels(files[3][1])
    assert rate == 8000 and chans[0][0] == "call" and set(chans[0][1]) == {-100}


@dataclass
class Seg:
    start: float
    end: float
    text: str
    language: str | None = None


def test_merge_orders_by_time_and_adds_offsets():
    rows = tr.merge([("respondent", 0.0, [Seg(2.1, 4.9, "I am 34")]),
                     ("agent", 0.0, [Seg(0.0, 2.0, "How old are you?"), Seg(5.0, 6.0, "  ")]),
                     ("agent", 4.0, [Seg(1.0, 2.0, "Thank you")])])
    assert [(r["speaker"], r["text"], r["start"]) for r in rows] == [
        ("agent", "How old are you?", 0.0), ("respondent", "I am 34", 2.1), ("agent", "Thank you", 5.0)]


def test_batch_language():
    assert tr.batch_language("hi") == "hi-IN,en-IN" and tr.batch_language("en") == "en-IN"


def test_run_full_transcript_stores_segments(trial_version, monkeypatch, client):
    b = Bot(trial_version, "hi")
    with SessionLocal() as db:
        db.get(Interview, b.interview_id).recording_file = storage.save_bytes(_stereo_wav(2), "recordings", ".wav")
        db.commit()
    seen = {}

    def fake(files, language, key):
        seen.update(files=[f[0] for f in files], language=language, key=key)
        return [{"start": 0.0, "end": 1.0, "speaker": "agent", "text": "नमस्ते", "language": "hi-IN"}]

    monkeypatch.setattr(tr, "voice_settings", lambda: SimpleNamespace(gnani_api_key="k"))
    monkeypatch.setattr(tr, "_transcribe_sync", fake)
    assert asyncio.run(tr.run_full_transcript(b.interview_id)) == {"status": "done", "segments": 1}
    assert seen == {"files": ["respondent_00.wav", "agent_00.wav"], "language": "hi-IN,en-IN", "key": "k"}
    body = client.get(f"/api/interviews/{b.interview_id}").json()
    assert body["transcript_state"] == "done" and body["transcript"][0]["text"] == "नमस्ते"

    def boom(*a):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(tr, "_transcribe_sync", boom)
    assert asyncio.run(tr.run_full_transcript(b.interview_id))["status"] == "failed"
    body = client.get(f"/api/interviews/{b.interview_id}").json()
    assert body["transcript_state"] == "failed" and "upload failed" in body["transcript_error"]


def test_transcript_without_recording_is_skipped(trial_version, monkeypatch, client):
    b = Bot(trial_version, "en")
    monkeypatch.setattr(tr, "voice_settings", lambda: SimpleNamespace(gnani_api_key="k"))
    assert asyncio.run(tr.run_full_transcript(b.interview_id))["status"] == "skipped"
    assert client.post(f"/api/interviews/{b.interview_id}/transcript").status_code == 503  # no key in tests
