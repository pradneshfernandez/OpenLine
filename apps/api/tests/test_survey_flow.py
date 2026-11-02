"""The survey bot's Flows logic, driven the way the LLM would call its tools (no audio, no LLM).

Each persona card from the stage 2 doc is played through the node handlers; we check what the
agent would say, which node comes next, and what is stored in Answer / Interview.
"""

import asyncio

import pytest

from app.db import SessionLocal
from app.models import Answer, Interview
from app.voice.flow import SurveyFlow
from app.voice.runner import DK, REFUSED
from app.voice.bot import load_interview
from app.voice.session import InterviewSession
from tests.conftest import SAMPLES, upload


@pytest.fixture(scope="module")
def trial_version(client, project_id):
    body = upload(client, project_id, SAMPLES / "trial" / "1_clean_phone_ready.xlsx").json()
    assert body["ok"], body["errors"]
    return body["version"]["id"]


class Bot:
    """Holds the current node and calls its tools like the LLM would."""

    def __init__(self, version_id: int, lang: str):
        with SessionLocal() as db:
            i = Interview(form_version_id=version_id, language=lang, participant_label="test")
            db.add(i)
            db.commit()
            self.interview_id = i.id
        lang_, title, runner = load_interview(self.interview_id)
        self.session = InterviewSession(self.interview_id, runner, lang_)
        self.session.start_clock()
        self.speeds: list[float] = []

        async def set_speed(s):
            self.speeds.append(s)

        self.flow = SurveyFlow(self.session, title, set_speed)
        self.node = None
        self.said: list[str] = []

    def enter(self, node):
        self.node = node
        for a in node.get("pre_actions", []):
            if a["type"] in ("tts_say", "end_conversation"):
                self.said.append(a["text"])
            if a["type"] == "function":
                asyncio.run(a["handler"](a, None))

    def open(self):
        self.enter(self.flow.opening_node())

    def tool(self, name, **args):
        fn = next(f for f in self.node["functions"] if f.name == name)
        result, nxt = asyncio.run(fn.handler(args, None))
        if nxt is not None:
            self.enter(nxt)
        return result

    def answer(self, value, heard="", confidence=0.95, **kw):
        return self.tool("record_answer", value=value, heard_text=heard or str(value), confidence=confidence, **kw)

    @property
    def node_name(self):
        return self.node["name"]

    def interview(self):
        with SessionLocal() as db:
            i = db.get(Interview, self.interview_id)
            return i.status, i.final_answers, {(a.question_name, tuple(a.repeat_index)): a for a in i.answers}


def test_card_a_completes_with_card_answers(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    assert b.node_name == "opening" and "automated survey call" in b.said[0] and "Do you agree" in b.said[0]
    assert b.node["respond_immediately"] is False
    for v in ["yes", 34, 5, "yes", 2]:
        assert b.answer(v)["status"] == "ok"
    assert "child number 1" in b.said[-1] and "How old is this child?" in b.said[-1]
    b.answer(8)
    assert "Government school, Private school or Other?" in b.said[-1]
    b.answer("government")
    assert "child number 2" in b.said[-1]
    for v in [12, "government", "yes", "water supply"]:
        b.answer(v)
    assert b.node_name == "end" and "Thank you" in b.said[-1]
    status, final, rows = b.interview()
    assert status == "completed"
    assert final["age"] == 34 and final["hh_size"] == 5 and final["child_age[2]"] == 12
    assert final["ration_card"] == "yes" and final["main_problem"] == "water supply"
    assert rows[("age", ())].heard_text == "34" and rows[("age", ())].t_question is not None


def test_card_b_hindi(trial_version):
    b = Bot(trial_version, "hi")
    b.open()
    assert b.said[0].startswith("नमस्ते") and "क्या आप भाग लेने के लिए सहमत हैं" in b.said[0]
    for v in ["yes", 45, 6, "yes", 1, 10, "private", "no", "बेरोज़गारी"]:
        assert b.answer(v)["status"] == "ok"
    status, final, _ = b.interview()
    assert status == "completed" and final["school_type[1]"] == "private" and final["main_problem"] == "बेरोज़गारी"


def test_card_c_correction_and_dont_know(trial_version):
    b = Bot(trial_version, "hi")
    b.open()
    b.answer("yes"); b.answer(30); b.answer(4)
    assert b.node_name == "q:children_school"
    tools = [f.name for f in b.node["functions"]]
    assert "correct_answer" in tools
    assert b.tool("correct_answer", question_name="hh_size", value="5")["status"] == "ok"
    assert b.node_name == "q:children_school"  # continues from the right place
    b.answer("no")
    assert b.node_name == "q:ration_card"  # children questions skipped
    b.tool("dont_know_or_refuse", kind=DK, heard_text="pata nahi")
    b.answer("bijli ka bill")
    status, final, rows = b.interview()
    assert status == "completed"
    assert final["hh_size"] == 5 and final["ration_card"] == "dk" and "num_children" not in final
    assert rows[("hh_size", ())].corrected


def test_card_d_invalid_repeat_slow_refuse(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    b.answer("yes")
    r = b.answer(200, heard="two hundred")
    assert r == {"status": "invalid", "say": "Please tell me an age between 18 and 100."}
    assert b.node_name == "q:age"
    n_said = len(b.said)
    b.tool("repeat_question")
    assert len(b.said) == n_said + 1 and b.said[-1] == "How old are you?"
    b.tool("slow_down")
    assert b.speeds == [0.85]
    b.answer(40)
    b.answer(3); b.answer("no")
    b.tool("dont_know_or_refuse", kind=REFUSED)
    b.answer("roads")
    status, final, rows = b.interview()
    assert status == "completed" and final["ration_card"] == "refused"
    assert rows[("age", ())].attempts == 2


def test_card_e_declines_at_consent(trial_version):
    b = Bot(trial_version, "hi")
    b.open()
    b.answer("no", heard="nahi")
    assert b.node_name == "end" and "कोई बात नहीं" in b.said[-1]
    status, final, _ = b.interview()
    assert status == "refused" and set(final) == {"start", "end", "consent"}


def test_low_confidence_select_is_confirmed_first(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    r = b.answer("yes", confidence=0.4)
    assert r["status"] == "confirm" and b.node_name == "opening"
    assert b.answer("yes", confidence=0.4, confirmed=True)["status"] == "ok"
    _, _, rows = b.interview()
    assert rows[("consent", ())].confirmed


def test_call_back_later(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    b.answer("yes")
    b.tool("call_back_later", when="tomorrow evening")
    status, _, _ = b.interview()
    with SessionLocal() as db:
        assert db.get(Interview, b.interview_id).callback_when == "tomorrow evening"
    assert status == "callback"


def test_record_answer_schema_is_typed(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    schema = next(f for f in b.node["functions"] if f.name == "record_answer").properties["value"]
    assert schema == {"type": "string", "enum": ["yes", "no"], "description": "Option code"}
    b.answer("yes")
    schema = next(f for f in b.node["functions"] if f.name == "record_answer").properties["value"]
    assert schema == {"type": "integer"}


def test_partial_when_call_drops(trial_version):
    b = Bot(trial_version, "en")
    b.open()
    b.answer("yes"); b.answer(50)
    b.session.close()
    status, final, _ = b.interview()
    assert status == "partial" and final["age"] == 50


def test_calls_api_requires_configuration(client, trial_version):
    r = client.post("/api/calls", json={"to": "+15005550006", "form_version_id": trial_version, "language": "en"})
    assert r.status_code == 503 and "TWILIO_ACCOUNT_SID" in r.json()["detail"]
    assert client.post("/api/calls", json={"to": "12345", "form_version_id": trial_version}).status_code == 422


def test_calls_api_places_twilio_call(client, trial_version, monkeypatch):
    from app.voice import calls
    from app.voice.config import VoiceSettings

    cfg = VoiceSettings(gnani_api_key="g", llm_api_key="l", twilio_account_sid="AC1", twilio_auth_token="t",
                        twilio_from_number="+15005550006", public_base_url="https://example.ngrok.app")
    monkeypatch.setattr(calls, "voice_settings", lambda: cfg)
    created = {}

    class FakeCalls:
        def create(self, **kw):
            created.update(kw)
            return type("Call", (), {"sid": "CA123"})()

    class FakeClient:
        def __init__(self, *a):
            self.calls = FakeCalls()

    import twilio.rest
    monkeypatch.setattr(twilio.rest, "Client", FakeClient)
    r = client.post("/api/calls", json={"to": "+919800000000", "form_version_id": trial_version,
                                         "language": "hi", "participant_label": "Card B"})
    assert r.status_code == 200, r.text
    iid = r.json()["interview_id"]
    assert 'url="wss://example.ngrok.app/ws"' in created["twiml"]
    assert f'name="interview_id" value="{iid}"' in created["twiml"]
    assert created["status_callback"].endswith(f"/api/calls/status?interview_id={iid}")
    detail = client.get(f"/api/interviews/{iid}").json()
    assert detail["call_sid"] == "CA123" and detail["participant_label"] == "Card B"
    assert "+9198" not in str(detail)  # the number is not stored

    # Status webhook: unsigned requests are rejected when a token is configured.
    assert client.post(f"/api/calls/status?interview_id={iid}", data={"CallStatus": "no-answer"}).status_code == 403
    from twilio.request_validator import RequestValidator
    url = f"https://example.ngrok.app/api/calls/status?interview_id={iid}"
    sig = RequestValidator("t").compute_signature(url, {"CallStatus": "no-answer"})
    ok = client.post(f"/api/calls/status?interview_id={iid}", data={"CallStatus": "no-answer"},
                     headers={"X-Twilio-Signature": sig})
    assert ok.status_code == 200
    assert client.get(f"/api/interviews/{iid}").json()["status"] == "no-answer"


def test_results_and_csv(client, trial_version):
    b = Bot(trial_version, "en")
    b.open()
    for v in ["yes", 34, 5, "yes", 1, 8, "government", "yes", "water supply"]:
        b.answer(v)
    form_id = client.get(f"/api/versions/{trial_version}").json()["form"]["id"]
    rows = client.get(f"/api/forms/{form_id}/interviews").json()
    assert any(r["id"] == b.interview_id and r["status"] == "completed" for r in rows)
    detail = client.get(f"/api/interviews/{b.interview_id}").json()
    assert [a["question_name"] for a in detail["answers"]][:3] == ["consent", "age", "hh_size"]
    csv_text = client.get(f"/api/forms/{form_id}/interviews.csv").text
    header = csv_text.splitlines()[0].split(",")
    assert header[:8] == ["interview_id", "form_version", "participant_label", "language", "status",
                          "review_state", "started_at", "ended_at"]
    assert {"consent", "age", "hh_size", "child_age[1]", "school_type[1]", "ration_card", "main_problem"} <= set(header)
