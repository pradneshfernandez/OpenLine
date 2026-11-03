"""Public demo: try OpenLine in the browser with a short mock survey (/demo).

The page records the mic and speaks the Twilio media-stream protocol to /ws (8 kHz mu-law, see
static/phone_line.js), so visitors hit the real phone pipeline. It polls /api/demo/calls/{id} for the
live conversation and answers. Only demo interviews are visible through these routes.

Sharing it publicly: set FORMS_DEMO_ONLY=true and tunnel port 8000 (e.g. `ngrok http 8000`). Then
only /demo, /api/demo/*, /static/* and /ws (for demo calls) answer; the rest of the API is hidden.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services, storage
from app.voice.i18n import LangCode
from app.config import settings
from app.db import get_session
from app.models import Form, Interview, Project
from app.voice.config import voice_settings

router = APIRouter()

HERE = Path(__file__).resolve().parent
PAGE = HERE / "static" / "demo.html"
FORM_FILE = HERE.parent / "sample_forms" / "demo" / "openline_demo.xlsx"
DEMO_FORM_ID = "openline_demo"
DEMO_USER = "demo"
LIVE = ("queued", "in-progress")
STALE_AFTER = timedelta(minutes=10)  # a demo call still "live" after this doesn't hold a line


class DemoStart(BaseModel):
    language: LangCode = "en"


def demo_version(db: Session):
    """The demo form's latest version, uploading sample_forms/demo/openline_demo.xlsx the first time."""
    form = db.scalar(select(Form).where(Form.form_id == DEMO_FORM_ID).order_by(Form.id))
    data = FORM_FILE.read_bytes()
    if form is not None and (v := services.latest_version(form)) is not None:
        if storage.read_bytes(v.original_file) == data:
            return v
        out = services.upload_form(db, form.project, FORM_FILE.name, data, DEMO_USER, form=form)  # the file changed
        if out.version is None:
            raise HTTPException(500, f"Demo form didn't convert: {out.errors}")
        db.commit()
        return out.version
    project = db.scalar(select(Project).order_by(Project.id)) or Project(name="Demo")
    db.add(project)
    db.flush()
    out = services.upload_form(db, project, FORM_FILE.name, data, DEMO_USER)
    if out.version is None:
        raise HTTPException(500, f"Demo form didn't convert: {out.errors}")
    db.commit()
    return out.version


def _demo_interview(db: Session, interview_id: int) -> Interview:
    i = db.get(Interview, interview_id)
    if i is None or i.created_by != DEMO_USER:
        raise HTTPException(404)
    return i


@router.get("/demo", include_in_schema=False)
def demo_page():
    return FileResponse(PAGE, media_type="text/html")


@router.get("/api/demo/status")
def demo_status(db: Session = Depends(get_session)):
    cfg = voice_settings()
    missing = cfg.missing("gnani_api_key", "llm_api_key")
    since = datetime.now(timezone.utc) - STALE_AFTER
    live = db.scalar(select(func.count()).select_from(Interview).where(
        Interview.created_by == DEMO_USER, Interview.status.in_(LIVE), Interview.created_at >= since))
    return {"ready": not missing, "missing": missing, "live_calls": live,
            "max_calls": settings.demo_max_calls, "languages_mixed": cfg.stt_auto_language,
            "stt_languages": cfg.stt_languages if cfg.stt_auto_language else ""}


@router.post("/api/demo/calls")
def start_demo_call(body: DemoStart, db: Session = Depends(get_session)):
    status = demo_status(db)
    if not status["ready"]:
        raise HTTPException(503, f"The demo isn't configured: set {', '.join(status['missing'])}")
    if status["live_calls"] >= settings.demo_max_calls:
        raise HTTPException(429, "All demo lines are busy. Please try again in a minute.")
    version = demo_version(db)
    i = Interview(form_version_id=version.id, language=body.language, channel="phone",
                  participant_label="demo visitor", created_by=DEMO_USER)
    db.add(i)
    db.commit()
    return {"interview_id": i.id, "call_sid": f"SIM{i.id:06d}"}


@router.get("/api/demo/calls/{interview_id}")
def demo_call(interview_id: int, db: Session = Depends(get_session)):
    """The live state of one demo call: what was said, what was saved, and how."""
    i = _demo_interview(db, interview_id)
    questions = {q.name: q for q in i.form_version.questions}
    lang_label = lambda q: (q.labels or {}).get(  # noqa: E731
        next((k for k in (q.labels or {}) if k.endswith(f"({i.language})")), ""), "") if q else ""
    answers = sorted(i.answers, key=lambda a: (questions[a.question_name].position
                                               if a.question_name in questions else 1e9, a.repeat_index))
    return {
        "id": i.id, "status": i.status, "language": i.language, "has_recording": bool(i.recording_file),
        "transcript_state": i.transcript_state,
        "turns": [{"t": t.t, "speaker": t.speaker, "text": t.text, "node": t.node_name,
                   "latency_ms": t.latency_ms} for t in i.turns],
        "answers": [{"question": a.question_name, "label": lang_label(questions.get(a.question_name))
                     or a.question_name, "value": a.value, "code": a.code, "heard_text": a.heard_text,
                     "confirmed": a.confirmed, "corrected": a.corrected, "attempts": a.attempts,
                     "still_relevant": a.still_relevant, "flagged": a.flagged,
                     "second_pass_text": a.second_pass_text, "second_pass_value": a.second_pass_value}
                    for a in answers],
    }


@router.get("/api/demo/calls/{interview_id}/recording")
def demo_recording(interview_id: int, db: Session = Depends(get_session)):
    i = _demo_interview(db, interview_id)
    if not i.recording_file:
        raise HTTPException(404)
    return Response(storage.read_bytes(i.recording_file), media_type="audio/wav")


# Paths a public demo server answers when FORMS_DEMO_ONLY=true.
PUBLIC_PREFIXES = ("/api/demo/", "/static/")


def is_public(path: str) -> bool:
    return path in ("/demo", "/ws") or path.startswith(PUBLIC_PREFIXES)


def is_demo_call(interview_id: int) -> bool:
    """For /ws in demo-only mode: only queued demo interviews may be run."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        i = db.get(Interview, interview_id)
        return i is not None and i.created_by == DEMO_USER and i.status == "queued"
