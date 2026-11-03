"""Every language Gnani supports can be a call language: phrases, mapping, demo form, STT settings."""

import re

import pytest

from app import services
from app.db import SessionLocal
from app.models import Interview
from app.voice.i18n import BCP47, CODES, LANGUAGES, PHRASES, lang_code, phrase
from app.voice.runner import pick_language
from app.voice.services import LANGUAGES as STT_LANGUAGES
from app.voice.services import stt_candidates
from tests.test_demo import ready  # noqa: F401  (fixture)


def test_the_ten_gnani_languages():
    from gnani.stt.client import STREAM_SUPPORTED_LANGUAGES
    from gnani.tts.client import SUPPORTED_TTS_LANGUAGES

    assert set(BCP47.values()) == set(STREAM_SUPPORTED_LANGUAGES) == SUPPORTED_TTS_LANGUAGES - {"auto"}
    assert set(STT_LANGUAGES) == set(CODES)


def test_every_language_has_every_phrase_with_the_same_placeholders():
    for code in CODES:
        assert PHRASES[code].keys() == PHRASES["en"].keys(), code
        for key, en in PHRASES["en"].items():
            assert set(re.findall(r"{\w+}", PHRASES[code][key])) == set(re.findall(r"{\w+}", en)), (code, key)
    assert "Tamil" not in phrase("ta", "greeting", org="X", study="Y")


@pytest.mark.parametrize("value,code", [("ta", "ta"), ("ta-IN", "ta"), ("Tamil (ta)", "ta"), ("தமிழ்", "ta"),
                                        ("Marathi", "mr"), ("मराठी", "mr"), ("हिन्दी", "hi"), ("pa-IN", "pa"),
                                        ("Kannada (kn)", "kn"), ("default", "en"), ("french", "en")])
def test_language_names_map_to_codes(value, code):
    assert lang_code(value) == code


def test_form_language_is_picked_for_the_call():
    keys = ["English (en)", "Hindi (hi)", "Tamil (ta)", "ಕನ್ನಡ"]
    assert pick_language(keys, keys[0], "ta") == "Tamil (ta)"
    assert pick_language(keys, keys[0], "kn") == "ಕನ್ನಡ"
    assert pick_language(keys, keys[0], "hi-IN") == "Hindi (hi)"
    assert pick_language(keys, keys[0], "bn") == "English (en)"   # not in the form: its default


def test_auto_language_listens_for_the_call_language():
    assert stt_candidates("ta", "en-IN,hi-IN,ta-IN") == ["en-IN", "hi-IN", "ta-IN"]
    assert stt_candidates("kn", "en-IN,hi-IN,ta-IN") == ["kn-IN", "en-IN", "hi-IN"]
    assert stt_candidates("en", "en-IN,hi-IN") == ["en-IN", "hi-IN"]


def test_demo_form_is_phone_ready_in_every_language(client, ready):  # noqa: F811
    for code in CODES:
        r = client.post("/api/demo/calls", json={"language": code})
        assert r.status_code == 200, (code, r.text)
        with SessionLocal() as db:
            i = db.get(Interview, r.json()["interview_id"])
            report = services.latest_report(db, i.form_version_id)
            assert report.status == "ready", (code, [(x.check_code, x.message) for x in report.issues])
            i.status = "completed"
            db.commit()
    assert client.post("/api/demo/calls", json={"language": "fr"}).status_code == 422


def test_demo_form_has_every_language():
    from openpyxl import load_workbook

    wb = load_workbook(services.__file__.replace("app/services.py", "sample_forms/demo/openline_demo.xlsx"))
    header = [c.value for c in wb["survey"][1]]
    for code, (name, *_) in LANGUAGES.items():
        assert f"label::{name} ({code})" in header
