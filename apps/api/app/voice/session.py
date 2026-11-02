"""Per-call state: timing, answer storage, turn log, status and recording."""

from __future__ import annotations

import io
import time
import wave
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from app import storage
from app.db import SessionLocal
from app.models import Answer, Interview, TurnLog
from app.voice.runner import ANOTHER, FormRunner, Item

FINAL_STATUSES = {"completed", "refused", "callback", "partial", "no-answer", "busy", "failed", "opted-out"}


class InterviewSession:
    def __init__(self, interview_id: int, runner: FormRunner, lang: str):
        self.interview_id = interview_id
        self.runner = runner
        self.lang = lang
        self._t0: float | None = None
        self.attempts: dict[tuple, int] = {}
        self.question_started: dict[tuple, float] = {}
        self.user_turn_start: float | None = None
        self.user_turn_end: float | None = None
        self.last_heard: str = ""
        self.pending_latency_ms: float | None = None
        self.node_name: str = ""
        self.final_status: str | None = None
        self.policy = None  # TurnPolicy, set by the bot; absent in text-only tests
        self.resumed_answers = 0  # answers carried over from an earlier partial call

    def asking(self, item: Item | None, protect: bool = False) -> None:
        """A question (or protected statement) is about to be spoken: tune turn-taking for it."""
        if self.policy is not None:
            self.policy.asking(item, protect=protect)

    # ------------------------------------------------------------------ time

    def start_clock(self) -> None:
        if self._t0 is None:
            self._t0 = time.monotonic()
            self._update(status="in-progress", started_at=datetime.now(timezone.utc))

    def now(self) -> float:
        return round(time.monotonic() - self._t0, 3) if self._t0 is not None else 0.0

    def mark_question(self, item: Item) -> None:
        self.question_started[item.key] = self.now()

    # ------------------------------------------------------------------ events

    def on_user_turn_started(self) -> None:
        self.user_turn_start = self.now()

    def on_user_turn_stopped(self, text: str | None) -> None:
        self.user_turn_end = self.now()
        if text:
            self.last_heard = text
            self.log_turn("respondent", text)

    def on_agent_turn(self, text: str) -> None:
        if text and text.strip():
            self.log_turn("agent", text.strip(), latency_ms=self.pending_latency_ms)
            self.pending_latency_ms = None

    def on_latency(self, seconds: float) -> None:
        self.pending_latency_ms = round(seconds * 1000, 1)

    # ------------------------------------------------------------------ storage

    def log_turn(self, speaker: str, text: str, latency_ms: float | None = None) -> None:
        with SessionLocal() as db:
            db.add(TurnLog(interview_id=self.interview_id, t=self.now(), speaker=speaker,
                           text=text, node_name=self.node_name, latency_ms=latency_ms))
            db.commit()

    def count_attempt(self, item: Item) -> int:
        self.attempts[item.key] = self.attempts.get(item.key, 0) + 1
        return self.attempts[item.key]

    def save_answer(self, item: Item, *, value=None, code: str | None = None, heard_text: str = "",
                    confidence: float | None = None, confirmed: bool = False, corrected: bool = False,
                    flagged: bool = False) -> None:
        if item.name == ANOTHER:
            return
        with SessionLocal() as db:
            rows = db.scalars(select(Answer).where(
                Answer.interview_id == self.interview_id, Answer.question_name == item.name))
            row = next((r for r in rows if list(r.repeat_index) == list(item.index)), None)
            if row is None:
                row = Answer(interview_id=self.interview_id, question_name=item.name,
                             repeat_index=list(item.index))
                db.add(row)
            row.value = None if value is None else (" ".join(value) if isinstance(value, list) else str(value))
            row.code = code
            row.heard_text = heard_text or self.last_heard
            row.confidence = confidence
            row.confirmed = confirmed
            row.corrected = row.corrected or corrected
            row.flagged = flagged
            row.attempts = self.attempts.get(item.key, 1)
            row.t_question = self.question_started.get(item.key)
            row.t_answer_start = self.user_turn_start
            row.t_answer_end = self.user_turn_end
            db.commit()

    def set_status(self, status: str, **fields) -> None:
        if status in FINAL_STATUSES:
            self.final_status = status
        self._update(status=status, **fields)

    def finish(self, status: str) -> dict:
        """Close the interview: flat answers from the runner, stale answers flagged."""
        answers = self.runner.finish()
        live = {(k.split("[")[0], tuple(int(i) - 1 for i in _indices(k))) for k in answers}
        with SessionLocal() as db:
            for row in db.scalars(select(Answer).where(Answer.interview_id == self.interview_id)):
                row.still_relevant = (row.question_name, tuple(row.repeat_index)) in live
            db.commit()
        self.set_status(status, final_answers=answers, ended_at=datetime.now(timezone.utc))
        return answers

    def close(self) -> None:
        """Called when the pipeline stops. A call that ended early is 'partial'."""
        if self.final_status is None:
            answers = self.runner.finish()
            self.set_status("partial" if self._t0 is not None else "failed",
                            final_answers=answers, ended_at=datetime.now(timezone.utc))

    def save_recording(self, audio: bytes, sample_rate: int, num_channels: int) -> None:
        if not audio:
            return
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio)
        rel = storage.save_bytes(buf.getvalue(), "recordings", ".wav")
        self._update(recording_file=rel, recording_sample_rate=sample_rate)
        logger.info(f"Interview {self.interview_id}: recording saved ({len(audio)} bytes)")

    def _update(self, **fields) -> None:
        with SessionLocal() as db:
            interview = db.get(Interview, self.interview_id)
            for k, v in fields.items():
                setattr(interview, k, v)
            db.commit()


def _indices(flat: str) -> list[str]:
    import re

    return re.findall(r"\[(\d+)\]", flat)
