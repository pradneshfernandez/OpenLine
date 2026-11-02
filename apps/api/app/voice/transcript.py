"""Full-call transcript (brief §5.6.2): the whole recording through Gnani Prisma Batch.

The recording is stereo (respondent left, agent right; see bot.py). Each channel is uploaded as
its own mono file, so every segment's speaker is known for certain rather than guessed by
diarization, and the two lists are merged by start time. Long calls are cut into chunks that fit
the batch API's 10 MB per-file limit; chunk offsets are added back to the segment times.

Runs automatically after each call (bot.py) and on demand from the interview page.
"""

from __future__ import annotations

import array
import asyncio
import io
import wave

from loguru import logger

from app import storage
from app.db import SessionLocal
from app.models import Interview
from app.voice.config import voice_settings
from app.voice.i18n import lang_code

MODEL = "prisma-v3.0"
MAX_FILE_BYTES = 9 * 1024 * 1024  # API limit is 10 MB per file; keep headroom for the header
WAIT_SECS = 900
CHANNELS = ("respondent", "agent")  # left, right


def batch_language(lang: str) -> str:
    """Hindi calls are often Hinglish: let Prisma v3 decide per segment between the two."""
    return "hi-IN,en-IN" if lang_code(lang) == "hi" else "en-IN"


def split_channels(wav_bytes: bytes) -> tuple[int, list[tuple[str, array.array]]]:
    """Stereo WAV -> [(speaker, samples)]. A mono recording is returned as one 'call' channel."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"Expected 16-bit audio, got {width * 8}-bit")
    samples = array.array("h")
    samples.frombytes(frames[: len(frames) // 2 * 2])
    if channels == 1:
        return rate, [("call", samples)]
    return rate, [(CHANNELS[c] if c < 2 else f"channel{c + 1}", samples[c::channels])
                  for c in range(min(channels, 2))]


def mono_wav(samples: array.array, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def make_files(wav_bytes: bytes, max_bytes: int = MAX_FILE_BYTES) -> list[tuple[str, bytes, str, float]]:
    """[(file name, wav bytes, speaker, offset seconds)] ready for one batch job."""
    rate, chans = split_channels(wav_bytes)
    per_chunk = max(rate, (max_bytes - 44) // 2)
    out = []
    for speaker, samples in chans:
        for n, start in enumerate(range(0, max(len(samples), 1), per_chunk)):
            chunk = samples[start:start + per_chunk]
            if len(chunk) < rate // 4:  # under 0.25 s: nothing to transcribe
                continue
            out.append((f"{speaker}_{n:02}.wav", mono_wav(chunk, rate), speaker, start / rate))
    return out


def merge(results: list[tuple[str, float, list]]) -> list[dict]:
    """[(speaker, offset, segments)] -> one time-ordered list of {start, end, speaker, text}."""
    rows = []
    for speaker, offset, segments in results:
        for s in segments:
            text = (s.text or "").strip()
            if text:
                rows.append({"start": round(s.start + offset, 2), "end": round(s.end + offset, 2),
                             "speaker": speaker, "text": text, "language": s.language})
    return sorted(rows, key=lambda r: (r["start"], r["speaker"]))


def _transcribe_sync(files: list[tuple[str, bytes, str, float]], language: str, api_key: str) -> list[dict]:
    from gnani.stt import GnaniSTTBatchClient  # type: ignore[import-untyped]

    client = GnaniSTTBatchClient(api_key)
    job = client.create_job([(name, data) for name, data, _, _ in files], language, model=MODEL)
    job.wait(timeout=WAIT_SECS, progress=False, raise_on_failure=False)
    by_name = {f.name: f for f in job.files()}
    results, failed = [], []
    for name, _, speaker, offset in files:
        f = by_name.get(name)
        if f is None or not f.ok:
            failed.append(f"{name}: {getattr(f, 'error', None) or getattr(f, 'status', 'missing')}")
            continue
        results.append((speaker, offset, f.segments))
    if failed and not results:
        raise RuntimeError("; ".join(failed))
    if failed:
        logger.warning(f"Transcript job {job.id}: some chunks failed: {'; '.join(failed)}")
    return merge(results)


def _set(interview_id: int, **fields) -> None:
    with SessionLocal() as db:
        i = db.get(Interview, interview_id)
        for k, v in fields.items():
            setattr(i, k, v)
        db.commit()


async def run_full_transcript(interview_id: int) -> dict:
    """Transcribe the interview's recording and store it on the interview. Returns a summary."""
    with SessionLocal() as db:
        i = db.get(Interview, interview_id)
        if i is None:
            return {"status": "error", "error": "No such interview"}
        if not i.recording_file:
            return {"status": "skipped", "error": "No recording"}
        rel, lang = i.recording_file, i.language
    key = voice_settings().gnani_api_key
    if not key:
        return {"status": "skipped", "error": "GNANI_API_KEY is not set"}
    _set(interview_id, transcript_state="running", transcript_error="")
    try:
        files = make_files(storage.read_bytes(rel))
        if not files:
            _set(interview_id, transcript_state="done", transcript=[])
            return {"status": "done", "segments": 0}
        segments = await asyncio.to_thread(_transcribe_sync, files, batch_language(lang), key)
    except Exception as e:
        logger.warning(f"Interview {interview_id}: full transcript failed: {e}")
        _set(interview_id, transcript_state="failed", transcript_error=str(e)[:2000])
        return {"status": "failed", "error": str(e)}
    _set(interview_id, transcript_state="done", transcript=segments)
    logger.info(f"Interview {interview_id}: full transcript, {len(segments)} segments")
    return {"status": "done", "segments": len(segments)}
