import audioop
import io
import wave

from app.voice.second_pass import clip_wav, map_value, respondent_audio, values_differ
from tests.test_runner import make_runner


def test_map_value_per_type():
    r = make_runner()
    r.start("hi")
    q = r.by_name
    assert map_value(r, q["age"], "मेरी उम्र 45 है।") == "45"
    assert map_value(r, q["school_type"], "सरकारी स्कूल") == "government"
    assert map_value(r, q["school_type"], "Private school.") == "private"
    assert map_value(r, q["ration_card"], "Yes, we have one.") == "yes"
    assert map_value(r, q["ration_card"], "hmm") is None
    assert map_value(r, q["main_problem"], "water supply") == "water supply"


def test_values_differ():
    assert values_differ({"type": "select_one"}, "no", "yes")
    assert not values_differ({"type": "integer"}, "34", "34")
    assert not values_differ({"type": "select_one"}, "no", None)  # nothing recognised: no flag
    assert not values_differ({"type": "text"}, "water", "water supply")


def test_clip_uses_respondent_channel():
    rate = 8000
    left = b"\x10\x00" * rate * 4
    stereo = audioop.add(audioop.tostereo(left, 2, 1, 0), audioop.tostereo(b"\x20\x00" * rate * 4, 2, 0, 1), 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(rate); wf.writeframes(stereo)
    pcm, r = respondent_audio(buf.getvalue())
    assert r == rate and pcm[:2] == b"\x10\x00"
    with wave.open(io.BytesIO(clip_wav(pcm, rate, 1.0, 2.0))) as wf:
        assert abs(wf.getnframes() / rate - 1.6) < 0.01  # 0.3 s padding each side
