"""Crash recovery (brief §5.7 "Server crash mid-call").

- `close_interrupted_calls()` runs at startup. A call that was `in-progress` when the server
  stopped can't continue (its media WebSocket is gone), so it is marked `partial`, with the
  answers already saved (each answer is written the moment it's accepted). Campaigns then treat
  it like any other partial call and retry it.
- `preload_previous_answers()` runs when a call starts. If the same campaign respondent has an
  earlier `partial` call on the same form version, its answers are loaded into the runner and
  copied into the new interview, so the call resumes from the first unanswered question instead
  of starting over. Consent is never carried over: every call asks for it again.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Answer, Interview
from app.voice.runner import FormRunner, Item, Stored, flat_name

INTERRUPTED = "The server restarted during the call"
LIVE_STATUSES = ("in-progress",)


def answers_from_rows(rows: list[Answer]) -> dict[str, str | None]:
    """Flat final answers (name[n] for repeats) from saved Answer rows."""
    return {flat_name(a.question_name, tuple(a.repeat_index or [])): a.code or a.value
            for a in rows if a.still_relevant}


def close_interrupted_calls() -> int:
    """Mark calls left `in-progress` by a crash as `partial`. Returns how many were closed."""
    n = 0
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for i in db.scalars(select(Interview).where(Interview.status.in_(LIVE_STATUSES),
                                                    Interview.simulation_run_id.is_(None))):
            i.status = "partial" if i.started_at else "failed"
            i.error = i.error or INTERRUPTED
            i.ended_at = i.ended_at or now
            i.final_answers = answers_from_rows(i.answers)
            n += 1
        db.commit()
    if n:
        logger.warning(f"Closed {n} call(s) interrupted by a server restart")
    return n


def previous_partial(db, interview: Interview) -> Interview | None:
    """The latest earlier partial call to the same campaign respondent on the same form version."""
    if not interview.campaign_respondent_id:
        return None
    return db.scalars(
        select(Interview).where(
            Interview.campaign_respondent_id == interview.campaign_respondent_id,
            Interview.form_version_id == interview.form_version_id,
            Interview.id != interview.id,
            Interview.created_at <= interview.created_at,
            Interview.status == "partial",
        ).order_by(Interview.created_at.desc(), Interview.id.desc())
    ).first()


def _coerced(runner: FormRunner, a: Answer):
    q = runner.by_name.get(a.question_name)
    if q is None or a.value is None:
        return None
    item = Item(name=q["name"], index=tuple(a.repeat_index or []), type=q["type"], kind=q["kind"], text="")
    value, err = runner._coerce(item, a.value)
    return None if err else value


def preload_previous_answers(interview_id: int, runner: FormRunner) -> int:
    """Load a previous partial call's answers into `runner` and this interview. Returns the count.

    Call before `runner.start()`: the runner then asks the first question that has no answer.
    """
    with SessionLocal() as db:
        interview = db.get(Interview, interview_id)
        prev = previous_partial(db, interview) if interview else None
        if prev is None:
            return 0
        rows = [a for a in prev.answers if a.still_relevant and (a.code or a.value is not None)]
        loaded = []
        for a in rows:
            if a.question_name not in runner.by_name or "consent" in a.question_name.lower():
                continue
            value = _coerced(runner, a)
            if value is None and not a.code:
                continue
            runner.answers[(a.question_name, tuple(a.repeat_index or []))] = Stored(value, a.code)
            loaded.append(a)
        existing = {(a.question_name, tuple(a.repeat_index or [])) for a in interview.answers}
        for a in loaded:
            if (a.question_name, tuple(a.repeat_index or [])) in existing:
                continue
            db.add(Answer(interview_id=interview_id, question_name=a.question_name,
                          repeat_index=list(a.repeat_index or []), value=a.value, code=a.code,
                          heard_text=a.heard_text, confidence=a.confidence, confirmed=a.confirmed,
                          corrected=a.corrected, attempts=a.attempts, flagged=a.flagged,
                          second_pass_text=a.second_pass_text, second_pass_value=a.second_pass_value))
        interview.resumed_from_id = prev.id
        db.commit()
    if loaded:
        logger.info(f"Interview {interview_id}: resuming from interview {prev.id} with {len(loaded)} answers")
    return len(loaded)
