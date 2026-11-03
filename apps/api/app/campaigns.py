"""Campaigns (brief §5.8): call a respondent list with one form version.

A background scheduler (`run_scheduler`, started with the app) ticks every few seconds. Each
tick, per running campaign, it first reads the outcome of finished calls into the respondent
rows, then dials respondents who are due, inside calling hours and up to the concurrency limit.

Outcome rules:
- completed -> done; refused / opted-out -> stopped (never called again)
- callback -> called again after the minimum gap (the respondent's "when" is kept for display)
- no-answer / busy / failed / partial -> retried after the minimum gap until max attempts
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form as FormField, Header, HTTPException, UploadFile
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.voice.i18n import CODES, LANGUAGES
from app.db import SessionLocal, get_session
from app.models import Campaign, CampaignRespondent, FormVersion, Interview, Project
from app.voice.session import FINAL_STATUSES

router = APIRouter(prefix="/api")

DEFAULTS = {"calling_start": "09:00", "calling_end": "19:00", "max_attempts": 3, "min_gap_minutes": 120,
            "concurrency": 1, "timezone": "Asia/Kolkata"}
STOP_OUTCOMES = {"refused", "opted-out"}
RETRY_OUTCOMES = {"no-answer", "busy", "failed", "partial"}
OUTCOMES = ["completed", "partial", "no-answer", "busy", "callback", "refused", "opted-out", "failed"]
# Language column values: code ("ta"), locale ("ta-IN"), English name ("Tamil") or native name ("தமிழ்").
LANGS = {"eng": "en", "हिंदी": "hi",
         **{k: c for c, (name, native, bcp) in LANGUAGES.items() for k in (c, bcp.lower(), name.lower(), native.lower())}}
STALE_CALL = timedelta(minutes=20)  # a call that never reported back is treated as failed


def _user(x_user: str | None) -> str:
    return (x_user or "").strip() or "anonymous"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite (tests) returns naive datetimes; stored values are always UTC.
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def mask(phone: str) -> str:
    """+91 98••• ••210 — the only form a stored number is ever shown in."""
    d = re.sub(r"[^\d+]", "", phone)
    if len(d) < 8:
        return "•••"
    cc = "+91 " if d.startswith("+91") else (d[:3] + " " if d.startswith("+") else "")
    rest = d[len(cc.strip()):]
    return f"{cc}{rest[:2]}••• ••{rest[-3:]}"


def normalize_phone(raw: str) -> str | None:
    """E.164, with Indian 10-digit mobiles (and 0/91 prefixes) accepted as +91."""
    d = re.sub(r"[\s().-]", "", raw or "")
    if re.fullmatch(r"0?[6-9]\d{9}", d):
        d = "+91" + d[-10:]
    elif re.fullmatch(r"91[6-9]\d{9}", d):
        d = "+" + d
    return d if re.fullmatch(r"\+[1-9]\d{7,14}", d) else None


# ---------------------------------------------------------------------------
# CSV


def read_respondents(data: bytes) -> dict:
    """Validate a respondent CSV (respondent_id, phone, language)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    cols = {(c or "").strip().lower(): c for c in reader.fieldnames or []}
    missing = [c for c in ("respondent_id", "phone", "language") if c not in cols]
    if missing:
        raise HTTPException(422, f"The CSV needs the columns respondent_id, phone, language "
                                 f"(missing: {', '.join(missing)})")
    ok, problems, seen_phone, seen_id = [], [], set(), set()
    counts = {"ok": 0, "invalid_number": 0, "duplicate": 0, "unknown_language": 0}
    for n, raw in enumerate(reader, start=2):  # row 1 is the header
        rid = (raw.get(cols["respondent_id"]) or "").strip()
        phone_raw = (raw.get(cols["phone"]) or "").strip()
        lang_raw = (raw.get(cols["language"]) or "").strip()
        if not (rid or phone_raw or lang_raw):
            continue
        phone = normalize_phone(phone_raw)
        lang = LANGS.get(lang_raw.lower())
        problem = None
        if phone is None:
            problem, kind = "Invalid phone number", "invalid_number"
        elif phone in seen_phone or (rid and rid in seen_id):
            problem, kind = "Duplicate of an earlier row", "duplicate"
        elif lang is None:
            problem, kind = f"Unknown language {lang_raw!r} (use en or hi)", "unknown_language"
        if problem:
            counts[kind] += 1
            # Invalid numbers are shown as typed so they can be fixed; valid ones stay masked.
            problems.append({"row": n, "respondent_id": rid, "phone": mask(phone) if phone else phone_raw,
                             "language": lang_raw, "problem": problem, "kind": kind})
            continue
        seen_phone.add(phone)
        seen_id.add(rid)
        counts["ok"] += 1
        ok.append({"row": n, "respondent_id": rid or f"row{n}", "phone": phone, "language": lang})
    langs = {c: sum(1 for r in ok if r["language"] == c) for c in CODES if any(r["language"] == c for r in ok)}
    preview = sorted([{**r, "phone": mask(r["phone"]), "problem": None} for r in ok[:8]] + problems[:12],
                     key=lambda r: r["row"])
    return {"rows": ok, "problems": problems, "counts": counts, "languages": langs, "preview": preview}


@router.post("/projects/{project_id}/campaigns/validate")
async def validate_csv(project_id: int, file: UploadFile = File(...)):
    res = read_respondents(await file.read())
    return {k: v for k, v in res.items() if k != "rows"} | {"filename": file.filename}


class CampaignSettings(BaseModel):
    calling_start: str = Field("09:00", pattern=r"^\d{2}:\d{2}$")
    calling_end: str = Field("19:00", pattern=r"^\d{2}:\d{2}$")
    max_attempts: int = Field(3, ge=1, le=10)
    min_gap_minutes: int = Field(120, ge=5, le=7 * 24 * 60)
    concurrency: int = Field(1, ge=1, le=5)
    timezone: str = "Asia/Kolkata"


@router.post("/projects/{project_id}/campaigns")
async def create_campaign(project_id: int, name: str = FormField(...), form_version_id: int = FormField(...),
                          settings: str = FormField("{}"), start: bool = FormField(False),
                          file: UploadFile = File(...), db: Session = Depends(get_session),
                          x_user: str | None = Header(None)):
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    version = db.get(FormVersion, form_version_id)
    if version is None or version.xform_xml is None or version.form.project_id != project_id:
        raise HTTPException(404, "Form version not found")
    cfg = CampaignSettings(**json.loads(settings or "{}"))
    parsed = read_respondents(await file.read())
    if not parsed["rows"]:
        raise HTTPException(422, "No valid respondents in the CSV")
    c = Campaign(project_id=project_id, name=name.strip() or "Untitled campaign", form_version_id=version.id,
                 settings=cfg.model_dump(), csv_filename=file.filename or "", rejected_rows=parsed["problems"],
                 created_by=_user(x_user), status="draft")
    c.respondents = [CampaignRespondent(respondent_id=r["respondent_id"], phone=r["phone"], language=r["language"])
                     for r in parsed["rows"]]
    db.add(c)
    if start:
        c.status, c.started_at = "running", now_utc()
    db.commit()
    return ser_campaign(c)


# ---------------------------------------------------------------------------
# Read


def _counts(c: Campaign) -> dict:
    out = {o: 0 for o in OUTCOMES}
    for r in c.respondents:
        if r.last_outcome in out:
            out[r.last_outcome] += 1
    return out


def ser_campaign(c: Campaign) -> dict:
    rs = c.respondents
    return {
        "id": c.id, "name": c.name, "status": c.status, "settings": {**DEFAULTS, **(c.settings or {})},
        "form": {"id": c.form_version.form.id, "title": c.form_version.form.title,
                 "version_id": c.form_version_id, "version_no": c.form_version.version_no},
        "total": len(rs), "completed": sum(1 for r in rs if r.last_outcome == "completed"),
        "done": sum(1 for r in rs if r.state in ("done", "stopped")),
        "calling": sum(1 for r in rs if r.state == "calling"),
        "outcomes": _counts(c), "csv_filename": c.csv_filename, "left_out": len(c.rejected_rows or []),
        "created_by": c.created_by, "created_at": c.created_at.isoformat(),
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "finished_at": c.finished_at.isoformat() if c.finished_at else None,
    }


def ser_respondent(r: CampaignRespondent) -> dict:
    return {"id": r.id, "respondent_id": r.respondent_id, "phone": mask(r.phone), "language": r.language,
            "state": r.state, "attempts": r.attempts, "last_outcome": r.last_outcome,
            "next_attempt_at": _aware(r.next_attempt_at).isoformat() if r.next_attempt_at else None,
            "callback_when": r.callback_when, "interview_ids": [i.id for i in r.interviews]}


@router.get("/projects/{project_id}/campaigns")
def list_campaigns(project_id: int, db: Session = Depends(get_session)):
    rows = db.scalars(select(Campaign).where(Campaign.project_id == project_id).order_by(Campaign.id.desc()))
    return [ser_campaign(c) for c in rows]


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_session)):
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404)
    live = [i for r in c.respondents for i in r.interviews if i.status not in FINAL_STATUSES]
    upcoming = sorted((r for r in c.respondents if r.state == "waiting" and r.attempts > 0),
                      key=lambda r: _aware(r.next_attempt_at) or now_utc())
    return ser_campaign(c) | {
        "in_window": in_calling_hours(c, now_utc()),
        "in_progress": [{"interview_id": i.id, "status": i.status, "respondent_id": r.respondent_id,
                         "phone": mask(r.phone), "language": i.language,
                         "started_at": (i.started_at or i.created_at).isoformat()}
                        for r in c.respondents for i in r.interviews if i in live],
        "upcoming": [ser_respondent(r) for r in upcoming[:20]],
        "respondents": [ser_respondent(r) for r in c.respondents],
        "rejected_rows": c.rejected_rows or [],
    }


@router.get("/campaigns/{campaign_id}/problems.csv")
def problems_csv(campaign_id: int, db: Session = Depends(get_session)):
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row", "respondent_id", "phone", "language", "problem"])
    for p in c.rejected_rows or []:
        w.writerow([p["row"], p["respondent_id"], p["phone"], p["language"], p["problem"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="campaign-{c.id}-problems.csv"'})


class ActionIn(BaseModel):
    action: str = Field(pattern="^(start|pause|resume|finish)$")


@router.post("/campaigns/{campaign_id}/action")
def campaign_action(campaign_id: int, body: ActionIn, db: Session = Depends(get_session)):
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404)
    allowed = {"start": {"draft"}, "pause": {"running"}, "resume": {"paused"}, "finish": {"draft", "running", "paused"}}
    if c.status not in allowed[body.action]:
        raise HTTPException(409, f"Can't {body.action} a campaign that is {c.status}")
    if body.action in ("start", "resume"):
        c.status = "running"
        c.started_at = c.started_at or now_utc()
    elif body.action == "pause":
        c.status = "paused"
    else:
        c.status, c.finished_at = "finished", now_utc()
    db.commit()
    return ser_campaign(c)


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_session)):
    """Drafts and finished campaigns only. Interviews it made are kept (they lose the link)."""
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404)
    if c.status not in ("draft", "finished"):
        raise HTTPException(409, "Pause and finish the campaign before deleting it")
    for r in c.respondents:
        for i in r.interviews:
            i.campaign_respondent_id = None
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Scheduler


def in_calling_hours(c: Campaign, now: datetime) -> bool:
    s = {**DEFAULTS, **(c.settings or {})}
    local = now.astimezone(ZoneInfo(s["timezone"])).time()
    start, end = (time.fromisoformat(s["calling_start"]), time.fromisoformat(s["calling_end"]))
    return start <= local < end


def sync_respondent(r: CampaignRespondent, c: Campaign, now: datetime) -> None:
    """Read the latest call's outcome into the respondent row."""
    if r.state != "calling" or not r.interviews:
        return
    i = r.interviews[-1]
    status = i.status
    if status not in FINAL_STATUSES:
        if now - _aware(i.created_at) < STALE_CALL or status == "in-progress":
            return
        status = i.status = "failed"
        i.error = i.error or "No status from the telephony provider"
    s = {**DEFAULTS, **(c.settings or {})}
    # The gap runs from when the call ended, not from when this tick noticed it.
    base = min(_aware(i.ended_at) or now, now)
    gap = timedelta(minutes=s["min_gap_minutes"])
    r.last_outcome = status
    if status == "completed":
        r.state = "done"
    elif status in STOP_OUTCOMES:
        r.state = "stopped"
    elif status == "callback":
        r.callback_when = i.callback_when
        r.state, r.next_attempt_at = "waiting", base + gap
    elif r.attempts < s["max_attempts"]:
        r.state, r.next_attempt_at = "waiting", base + gap
    else:
        r.state = "done"


async def tick(now: datetime | None = None) -> int:
    """One scheduler pass over all running campaigns. Returns the number of calls placed."""
    from app.voice.calls import CallError, place_call

    now = now or now_utc()
    placed = 0
    with SessionLocal() as db:
        for c in db.scalars(select(Campaign).where(Campaign.status == "running")):
            for r in c.respondents:
                sync_respondent(r, c, now)
            db.commit()
            if all(r.state in ("done", "stopped") for r in c.respondents):
                c.status, c.finished_at = "finished", now
                db.commit()
                continue
            if not in_calling_hours(c, now):
                continue
            s = {**DEFAULTS, **(c.settings or {})}
            free = s["concurrency"] - sum(1 for r in c.respondents if r.state == "calling")
            due = [r for r in c.respondents if r.state == "waiting"
                   and (r.next_attempt_at is None or _aware(r.next_attempt_at) <= now)
                   and (r.attempts < s["max_attempts"] or r.last_outcome == "callback")]
            for r in due[:max(0, free)]:
                r.attempts += 1
                r.state = "calling"
                db.commit()
                try:
                    await place_call(db, c.form_version, r.phone, r.language,
                                     f"{c.name} · {r.respondent_id}", "campaign", campaign_respondent_id=r.id)
                    placed += 1
                except CallError as e:
                    logger.warning(f"Campaign {c.id}: call to respondent {r.respondent_id} failed: {e.message}")
                    if e.status == 503:  # calling not configured: pause instead of burning attempts
                        r.attempts -= 1
                        r.state = "waiting"
                        c.status = "paused"
                        db.commit()
                        break
                    db.refresh(r)  # place_call marked the interview failed; next tick schedules a retry
    return placed


async def run_scheduler(interval: float = 10.0) -> None:
    while True:
        try:
            await tick()
        except Exception as e:  # never let one bad tick stop the loop
            logger.exception(f"Campaign scheduler tick failed: {e}")
        await asyncio.sleep(interval)
