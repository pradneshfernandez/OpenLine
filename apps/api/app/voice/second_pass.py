"""Second pass per answer (stage 2 doc §5.6.1).

After the call, each answer's clip is cut from the respondent channel of the recording and
sent to Prisma v3.0 REST with the question as context: `keywords` = option labels, `topic` =
question text, `previous_text` = what the agent asked. The result is mapped to a value the same
way as during the call; answers whose second-pass value differs are flagged for review.
"""

from __future__ import annotations

import audioop
import io
import re
import wave

import aiohttp
from loguru import logger
from sqlalchemy import select

from app import storage
from app.db import SessionLocal
from app.models import Answer, Interview
from app.voice.config import voice_settings
from app.voice.i18n import lang_code
from app.voice.runner import FormRunner, runner_for_version
from app.voice.services import LANGUAGES
from app.xlsform.text import spoken_text

MAX_CLIP_SECS = 29.5  # Prisma REST takes clips under 30 s
PAD_SECS = 0.3


def respondent_audio(wav_bytes: bytes) -> tuple[bytes, int]:
    """PCM16 mono of the respondent (left channel of the call recording)."""
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        rate, channels, frames = wf.getframerate(), wf.getnchannels(), wf.readframes(wf.getnframes())
    if channels == 2:
        frames = audioop.tomono(frames, 2, 1, 0)
    return frames, rate


def clip_wav(pcm: bytes, rate: int, start: float, end: float) -> bytes:
    start = max(0.0, start - PAD_SECS)
    end = min(end + PAD_SECS, start + MAX_CLIP_SECS, len(pcm) / 2 / rate)
    a, b = int(start * rate) * 2, int(end * rate) * 2
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm[a:b])
    return buf.getvalue()


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", " ", spoken_text(s).lower()).strip()


def map_value(runner: FormRunner, question: dict, text: str) -> str | None:
    """Map a transcript to a value for the question, without an LLM.

    select_one: the option whose label (any language) or code appears in the transcript.
    integer/decimal: the first number. text: the transcript itself.
    """
    if not text:
        return None
    t = question["type"]
    if t in ("integer", "decimal"):
        m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
        if not m:
            return None
        num = float(m.group(0))
        return str(int(num)) if num.is_integer() else str(num)
    if t == "select_one":
        heard = f" {_norm(text)} "
        best = None
        for c in runner.choice_lists.get(question.get("choice_list") or "", []):
            for label in [c["name"], *(c.get("labels") or {}).values()]:
                lab = _norm(label)
                if lab and f" {lab} " in heard and (best is None or len(lab) > best[1]):
                    best = (c["name"], len(lab))
        return best[0] if best else None
    return text.strip()


def values_differ(question: dict, stored: str | None, second: str | None) -> bool:
    if second is None or stored is None:
        return False
    if question["type"] == "text":
        return False  # free text is compared by a person, not flagged automatically
    return stored.strip().lower() != second.strip().lower()


async def transcribe(clip: bytes, lang: str, keywords: list[str], topic: str, previous_text: str) -> str:
    from pipecat_gnani._common import GNANI_STT_REST_URL
    from pipecat_gnani.stt import GnaniHttpSTTSettings, _build_rest_fields

    cfg = voice_settings()
    settings = GnaniHttpSTTSettings(
        model="prisma-v3.0", language=LANGUAGES[lang_code(lang)], format="transcribe",
        keywords=keywords or None, topic=topic[:500] or None, previous_text=previous_text[:500] or None,
        language_candidates=None, speaker_names=None, itn_native_numerals=None,
    )
    fields = _build_rest_fields(settings)  # validated by the fork, same as live STT
    form = aiohttp.FormData()
    form.add_field("audio_file", clip, filename="answer.wav", content_type="audio/wav")
    for k, v in fields.items():
        form.add_field(k, v)
    async with aiohttp.ClientSession() as http:
        async with http.post(GNANI_STT_REST_URL, data=form, headers={"X-API-Key-ID": cfg.gnani_api_key}) as r:
            if r.status != 200:
                raise RuntimeError(f"Prisma REST {r.status}: {await r.text()}")
            return ((await r.json()).get("transcript") or "").strip()


async def run_second_pass(interview_id: int) -> dict:
    """Re-transcribe every answer of an interview; returns counts."""
    with SessionLocal() as db:
        interview = db.get(Interview, interview_id)
        if interview is None or not interview.recording_file:
            return {"done": 0, "flagged": 0, "skipped": "no recording"}
        runner = runner_for_version(interview.form_version)
        runner.start(interview.language)
        lang = interview.language
        pcm, rate = respondent_audio(storage.read_bytes(interview.recording_file))
        answers = list(db.scalars(select(Answer).where(Answer.interview_id == interview_id)))
        done = flagged = 0
        for a in answers:
            q = runner.by_name.get(a.question_name)
            if q is None or a.t_answer_start is None or a.t_answer_end is None or a.code:
                continue
            item = runner._item(q, tuple(a.repeat_index), None)
            keywords = [o["label"] for o in item.options if not runner.is_dk_code(o["name"])]
            try:
                text = await transcribe(clip_wav(pcm, rate, a.t_answer_start, a.t_answer_end),
                                        lang, keywords, item.text, item.text)
            except Exception as e:
                logger.warning(f"second pass failed for {a.question_name}: {e}")
                continue
            a.second_pass_text = text
            a.second_pass_value = map_value(runner, q, text)
            a.flagged = values_differ(q, a.value, a.second_pass_value)
            done += 1
            flagged += a.flagged
        db.commit()
    logger.info(f"Interview {interview_id}: second pass on {done} answers, {flagged} flagged")
    return {"done": done, "flagged": flagged}
