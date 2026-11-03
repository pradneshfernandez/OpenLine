"""Telephony (Twilio outbound + media stream WebSocket) and interview results API."""

from __future__ import annotations

import asyncio
import csv
import io
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.voice.i18n import LangCode
from app.db import get_session
from app.models import Form, FormVersion, Interview
from app.voice.config import voice_settings
from app.voice.session import FINAL_STATUSES

router = APIRouter()

TWILIO_FINAL = {"no-answer": "no-answer", "busy": "busy", "failed": "failed", "canceled": "failed"}


def _user(x_user: str | None) -> str:
    return (x_user or "").strip() or "anonymous"


# ---------------------------------------------------------------------------
# Dialler


class CallIn(BaseModel):
    to: str = Field(pattern=r"^\+[1-9]\d{6,14}$", description="E.164 number, e.g. +9198xxxxxxxx")
    form_version_id: int
    language: LangCode = "en"
    participant_label: str = ""


def _twiml(ws_url: str, interview_id: int) -> str:
    return (
        "<Response><Connect>"
        f"<Stream url={quoteattr(ws_url)}>"
        f'<Parameter name="interview_id" value="{interview_id}"/>'
        "</Stream></Connect></Response>"
    )


CALL_KEYS = ("twilio_account_sid", "twilio_auth_token", "twilio_from_number", "public_base_url",
             "gnani_api_key", "llm_api_key")


class CallError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _dial(to: str, twiml: str, status_callback: str) -> str:
    """Place the Twilio call and return its SID. Tests replace this function."""
    from twilio.rest import Client

    cfg = voice_settings()
    client = Client(cfg.twilio_account_sid, cfg.twilio_auth_token)
    call = client.calls.create(
        to=to, from_=cfg.twilio_from_number, twiml=twiml, status_callback=status_callback,
        status_callback_event=["initiated", "ringing", "answered", "completed"])
    return call.sid


async def place_call(db: Session, version: FormVersion, to: str, language: str, label: str, user: str,
                     campaign_respondent_id: int | None = None) -> Interview:
    """Create the Interview row and dial. Shared by the "Start a call" panel and campaigns."""
    cfg = voice_settings()
    missing = cfg.missing(*CALL_KEYS)
    if missing:
        raise CallError(503, f"Calling is not configured; set {', '.join(missing)} in apps/api/.env")
    interview = Interview(form_version_id=version.id, language=language, channel="phone",
                          participant_label=label, created_by=user,
                          campaign_respondent_id=campaign_respondent_id)
    db.add(interview)
    db.commit()

    base = cfg.public_base_url.rstrip("/")
    ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    try:
        sid = await asyncio.to_thread(_dial, to, _twiml(ws_url, interview.id),
                                      f"{base}/api/calls/status?interview_id={interview.id}")
    except Exception as e:  # Twilio REST errors: permissions, unverified numbers, ...
        interview.status, interview.error = "failed", str(e)
        db.commit()
        raise CallError(502, f"Twilio could not place the call: {e}") from e
    interview.call_sid = sid
    db.commit()
    return interview


@router.post("/api/calls")
async def create_call(body: CallIn, db: Session = Depends(get_session), x_user: str | None = Header(None)):
    version = db.get(FormVersion, body.form_version_id)
    if version is None or version.xform_xml is None:
        raise HTTPException(404, "Form version not found (or it is the unconverted original)")
    try:
        interview = await place_call(db, version, body.to, body.language, body.participant_label, _user(x_user))
    except CallError as e:
        raise HTTPException(e.status, e.message) from e
    # The phone number itself is never stored.
    return {"interview_id": interview.id, "call_sid": interview.call_sid, "status": interview.status}


@router.post("/api/calls/status")
async def call_status(request: Request, interview_id: int, db: Session = Depends(get_session)):
    """Twilio statusCallback: record ringing / no-answer / busy / failed / completed."""
    cfg = voice_settings()
    form = dict(await request.form())
    if cfg.twilio_auth_token:
        from twilio.request_validator import RequestValidator

        url = f"{cfg.public_base_url.rstrip('/')}{request.url.path}?{request.url.query}"
        if not RequestValidator(cfg.twilio_auth_token).validate(
                url, form, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "Invalid Twilio signature")
    interview = db.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(404)
    status = str(form.get("CallStatus", ""))
    interview.twilio_status = status
    if status in TWILIO_FINAL and interview.status not in FINAL_STATUSES:
        interview.status = TWILIO_FINAL[status]
    elif status == "ringing" and interview.status == "queued":
        interview.status = "ringing"
    db.commit()
    return {"ok": True}


@router.websocket("/ws")
async def media_stream(websocket: WebSocket):
    """Twilio media stream: read the `start` message, then run the survey bot on it."""
    from pipecat.runner.utils import parse_telephony_websocket
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

    from app.voice.bot import run_interview

    await websocket.accept()
    transport_type, call_data = await parse_telephony_websocket(websocket)
    params = call_data.get("body", {}) or {}
    interview_id = int(params.get("interview_id", 0))
    from app.config import settings as app_settings
    from app.demo import is_demo_call

    if app_settings.demo_only and not is_demo_call(interview_id):
        await websocket.close(code=1008)
        return
    logger.info(f"Media stream start: {transport_type} call={call_data.get('call_id')} interview={interview_id}")
    try:
        cfg = voice_settings()
        # Hang-up uses the Twilio REST API, so it needs credentials; without them (local
        # simulated calls) the stream is simply closed.
        # The browser phone simulator (`/phone-sim`) sends call ids starting with "SIM": no REST hang-up.
        simulated = str(call_data.get("call_id", "")).startswith("SIM")
        has_creds = bool(cfg.twilio_account_sid and cfg.twilio_auth_token) and not simulated
        serializer = TwilioFrameSerializer(
            stream_sid=call_data["stream_id"], call_sid=call_data["call_id"],
            account_sid=cfg.twilio_account_sid or None, auth_token=cfg.twilio_auth_token or None,
            params=TwilioFrameSerializer.InputParams(auto_hang_up=has_creds))
        transport = FastAPIWebsocketTransport(websocket=websocket, params=FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False, serializer=serializer))
        await run_interview(transport, interview_id, sample_rate=8000)
    except Exception as e:
        logger.exception(f"Interview {interview_id} failed: {e}")
        _mark_failed(interview_id, f"{type(e).__name__}: {e}")


def _mark_failed(interview_id: int, error: str) -> None:
    """A bot that crashes before or during the call must not leave the interview 'queued'."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        interview = db.get(Interview, interview_id)
        if interview is not None and interview.status not in FINAL_STATUSES:
            interview.status, interview.error = "failed", error[:2000]
            db.commit()


# ---------------------------------------------------------------------------
# Results


def ser_interview(i: Interview) -> dict:
    return {
        "id": i.id, "form_version_id": i.form_version_id, "language": i.language,
        "participant_label": i.participant_label, "channel": i.channel, "call_sid": i.call_sid,
        "status": i.status, "twilio_status": i.twilio_status, "callback_when": i.callback_when,
        "created_by": i.created_by, "created_at": i.created_at.isoformat(),
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "ended_at": i.ended_at.isoformat() if i.ended_at else None,
        "has_recording": bool(i.recording_file), "error": i.error,
        "review_state": i.review_state, "review_reason": i.review_reason, "persona": i.persona,
        "simulation_run_id": i.simulation_run_id, "kobo_state": i.kobo_state,
        "campaign_id": i.campaign_respondent.campaign_id if i.campaign_respondent_id else None,
        "resumed_from_id": i.resumed_from_id, "transcript_state": i.transcript_state,
    }


@router.get("/api/forms/{form_id}/interviews")
def list_interviews(form_id: int, db: Session = Depends(get_session)):
    rows = db.scalars(select(Interview).join(FormVersion).where(FormVersion.form_id == form_id)
                      .order_by(Interview.created_at.desc()))
    out = []
    for i in rows:
        lat = [t.latency_ms for t in i.turns if t.latency_ms is not None]
        out.append(ser_interview(i) | {
            "version_no": i.form_version.version_no,
            "answer_count": sum(1 for a in i.answers if a.still_relevant),
            "flagged_count": sum(1 for a in i.answers if a.still_relevant and a.flagged),
            "avg_latency_ms": round(sum(lat) / len(lat)) if lat else None,
        })
    return out


@router.get("/api/interviews/{interview_id}")
def get_interview(interview_id: int, db: Session = Depends(get_session)):
    i = db.get(Interview, interview_id)
    if i is None:
        raise HTTPException(404)
    order = {q.name: q.position for q in i.form_version.questions}
    labels = {q.name: q.labels for q in i.form_version.questions}
    answers = sorted(i.answers, key=lambda a: (order.get(a.question_name, 1e9), a.repeat_index))
    return ser_interview(i) | {
        "form": {"id": i.form_version.form_id, "title": i.form_version.form.title,
                 "version_no": i.form_version.version_no},
        "final_answers": i.final_answers,
        "answers": [{c: getattr(a, c) for c in (
            "id", "question_name", "repeat_index", "value", "code", "heard_text", "confidence",
            "confirmed", "corrected", "attempts", "still_relevant", "t_question", "t_answer_start",
            "t_answer_end", "second_pass_text", "second_pass_value", "flagged", "review_state",
            "reviewed_value", "review_reason")} | {"labels": labels.get(a.question_name, {})} for a in answers],
        "turns": [{c: getattr(t, c) for c in ("id", "t", "speaker", "text", "node_name", "latency_ms")}
                  for t in i.turns],
        "transcript": i.transcript or [],
        "transcript_error": i.transcript_error,
    }


@router.post("/api/interviews/{interview_id}/second-pass")
async def second_pass(interview_id: int):
    """Re-transcribe each answer clip with Prisma v3.0 REST and flag mismatches."""
    from app.voice.second_pass import run_second_pass

    if not voice_settings().gnani_api_key:
        raise HTTPException(503, "Set GNANI_API_KEY in apps/api/.env")
    return await run_second_pass(interview_id)


@router.post("/api/interviews/{interview_id}/transcript")
async def full_transcript(interview_id: int):
    """Transcribe the whole recording with Gnani Prisma Batch (one file per channel)."""
    from app.voice.transcript import run_full_transcript

    if not voice_settings().gnani_api_key:
        raise HTTPException(503, "Set GNANI_API_KEY in apps/api/.env")
    res = await run_full_transcript(interview_id)
    if res["status"] == "error":
        raise HTTPException(404, res["error"])
    if res["status"] == "skipped":
        raise HTTPException(409, res["error"])
    return res


@router.get("/api/interviews/{interview_id}/recording")
def recording(interview_id: int, db: Session = Depends(get_session)):
    i = db.get(Interview, interview_id)
    if i is None or not i.recording_file:
        raise HTTPException(404, "No recording")
    return Response(storage.read_bytes(i.recording_file), media_type="audio/wav",
                    headers={"Content-Disposition": f'inline; filename="interview-{i.id}.wav"'})


@router.get("/api/forms/{form_id}/interviews.csv")
def export_csv(form_id: int, db: Session = Depends(get_session)):
    """One row per interview; answer columns use the form's variable names (repeats as name[n]).
    Reviewer edits replace the raw value and rejected answers are left blank."""
    from app.review import effective_answers

    form = db.get(Form, form_id)
    if form is None:
        raise HTTPException(404)
    rows = list(db.scalars(select(Interview).join(FormVersion).where(FormVersion.form_id == form_id)
                           .order_by(Interview.id)))
    order: dict[str, int] = {}
    for v in form.versions:
        for q in v.questions:
            order.setdefault(q.name, q.position)
    keys = sorted({k for i in rows for k in (i.final_answers or {})},
                  key=lambda k: (order.get(k.split("[")[0], 1e9), k))
    meta = ["interview_id", "form_version", "participant_label", "language", "status", "review_state",
            "started_at", "ended_at"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(meta + keys)
    for i in rows:
        fa = effective_answers(i)  # reviewer edits applied; raw answers stay in the database
        w.writerow([i.id, i.form_version.version_no, i.participant_label, i.language, i.status, i.review_state,
                    i.started_at.isoformat() if i.started_at else "", i.ended_at.isoformat() if i.ended_at else ""]
                   + ["" if fa.get(k) is None else fa.get(k) for k in keys])
    name = (form.form_id or f"form{form.id}").replace("/", "_")
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}-interviews.csv"'})


@router.get("/api/voice/status")
def voice_status():
    """What is configured, so the UI can say what is missing before a call."""
    cfg = voice_settings()
    return {
        "gnani": bool(cfg.gnani_api_key), "llm": bool(cfg.llm_api_key), "llm_provider": cfg.llm_provider,
        "twilio": bool(cfg.twilio_account_sid and cfg.twilio_auth_token and cfg.twilio_from_number),
        "llm_fallback": cfg.llm_fallback_provider if cfg.key_for(cfg.llm_fallback_provider) else None,
        "exotel": bool(cfg.exotel_account_sid and cfg.exotel_api_key and cfg.exotel_api_token),
        "public_base_url": cfg.public_base_url,
        "missing": cfg.missing("gnani_api_key", "llm_api_key", "twilio_account_sid", "twilio_auth_token",
                               "twilio_from_number", "public_base_url"),
    }
