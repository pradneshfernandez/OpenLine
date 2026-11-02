"""KoboToolbox export (brief §5.11).

Connect with a server URL and API token (KPI, e.g. https://kf.kobotoolbox.org), pick the
deployed project that matches the form, then send approved interviews as submissions through
the KoboCAT JSON API (`POST <kc>/api/v1/submissions`). Each interview gets a stable instanceID,
so a resend replaces rather than duplicates on Kobo's side.

The token is stored server-side and never returned; the UI only sees "••••abcd".
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Form, FormVersion, Interview, Project
from app.review import effective_answers, parse_index

router = APIRouter(prefix="/api")

NAMESPACE = uuid.UUID("6f1c3c1e-6a4b-4b0e-9a55-5e0b8f6a7c21")


class KoboError(Exception):
    pass


def http(method: str, url: str, token: str, body: dict | None = None) -> dict:
    """JSON request with Kobo token auth. Tests replace this function."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Token {token}", "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        if e.code in (401, 403):
            raise KoboError("Kobo rejected the API token (check it under Account settings › Security)") from e
        raise KoboError(f"Kobo returned {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise KoboError(f"Couldn't reach {urlparse(url).netloc}: {e.reason}") from e


def _project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Project not found")
    return p


def ser_kobo(p: Project) -> dict:
    k = p.kobo or {}
    token = k.get("token") or ""
    return {"connected": bool(k.get("server_url") and token), "server_url": k.get("server_url", ""),
            "token_masked": f"••••{token[-4:]}" if token else "", "asset_uid": k.get("asset_uid", ""),
            "asset_name": k.get("asset_name", ""), "kc_url": k.get("kc_url", "")}


def list_assets(server_url: str, token: str) -> list[dict]:
    res = http("GET", f"{server_url}/api/v2/assets/?asset_type=survey&limit=200&format=json", token)
    return [{"uid": a["uid"], "name": a.get("name") or a["uid"], "deployed": bool(a.get("has_deployment")),
             "submissions": a.get("deployment__submission_count")} for a in res.get("results", [])]


class ConnectIn(BaseModel):
    server_url: str = Field(min_length=8)
    token: str | None = None  # omit to keep the saved one


@router.get("/projects/{project_id}/kobo")
def get_kobo(project_id: int, db: Session = Depends(get_session)):
    return ser_kobo(_project(db, project_id))


@router.put("/projects/{project_id}/kobo")
async def connect(project_id: int, body: ConnectIn, db: Session = Depends(get_session)):
    p = _project(db, project_id)
    server = body.server_url.strip().rstrip("/")
    if not server.startswith(("https://", "http://")):
        server = "https://" + server
    token = (body.token or "").strip() or (p.kobo or {}).get("token", "")
    if not token:
        raise HTTPException(422, "Enter the API token")
    try:
        assets = await asyncio.to_thread(list_assets, server, token)
    except KoboError as e:
        raise HTTPException(502, str(e)) from e
    keep = (p.kobo or {}) if (p.kobo or {}).get("server_url") == server else {}
    p.kobo = {**keep, "server_url": server, "token": token}
    db.commit()
    return ser_kobo(p) | {"assets": assets}


@router.delete("/projects/{project_id}/kobo")
def disconnect(project_id: int, db: Session = Depends(get_session)):
    p = _project(db, project_id)
    p.kobo = {}
    db.commit()
    return ser_kobo(p)


@router.get("/projects/{project_id}/kobo/assets")
async def assets(project_id: int, db: Session = Depends(get_session)):
    k = _project(db, project_id).kobo or {}
    if not k.get("token"):
        raise HTTPException(409, "Not connected to KoboToolbox")
    try:
        return await asyncio.to_thread(list_assets, k["server_url"], k["token"])
    except KoboError as e:
        raise HTTPException(502, str(e)) from e


class AssetIn(BaseModel):
    asset_uid: str


@router.put("/projects/{project_id}/kobo/asset")
async def pick_asset(project_id: int, body: AssetIn, db: Session = Depends(get_session)):
    p = _project(db, project_id)
    k = p.kobo or {}
    if not k.get("token"):
        raise HTTPException(409, "Not connected to KoboToolbox")
    try:
        a = await asyncio.to_thread(http, "GET", f"{k['server_url']}/api/v2/assets/{body.asset_uid}/?format=json", k["token"])
    except KoboError as e:
        raise HTTPException(502, str(e)) from e
    ident = a.get("deployment__identifier") or ""
    kc = f"{urlparse(ident).scheme}://{urlparse(ident).netloc}" if ident else k["server_url"].replace("://kf.", "://kc.")
    p.kobo = {**k, "asset_uid": body.asset_uid, "asset_name": a.get("name") or body.asset_uid, "kc_url": kc}
    db.commit()
    return ser_kobo(p)


# ---------------------------------------------------------------------------
# Submissions


def submission(i: Interview, asset_uid: str) -> dict:
    """Nest flat answers (name, name[2]) under their groups and repeats, as Kobo expects."""
    paths = {q.name: q.group_path for q in i.form_version.questions}
    out: dict = {}
    for key, value in effective_answers(i).items():
        if value is None or value == "":
            continue
        name, index = parse_index(key)
        node = out
        rep = 0
        for g in paths.get(name, []):
            if g["type"] == "repeat":
                lst = node.setdefault(g["name"], [])
                n = index[rep] if rep < len(index) else 0
                rep += 1
                while len(lst) <= n:
                    lst.append({})
                node = lst[n]
            else:
                node = node.setdefault(g["name"], {})
        node[name] = value
    out["meta"] = {"instanceID": f"uuid:{uuid.uuid5(NAMESPACE, f'interview-{i.id}')}"}
    return {"id": asset_uid, "submission": out}


def send_one(i: Interview, kobo: dict) -> None:
    try:
        http("POST", f"{kobo['kc_url']}/api/v1/submissions", kobo["token"], submission(i, kobo["asset_uid"]))
        i.kobo_state, i.kobo_error, i.kobo_sent_at = "sent", "", datetime.now(timezone.utc)
    except KoboError as e:
        i.kobo_state, i.kobo_error = "failed", str(e)


def _ready(db: Session, project_id: int) -> dict:
    k = _project(db, project_id).kobo or {}
    if not (k.get("token") and k.get("asset_uid")):
        raise HTTPException(409, "Connect to KoboToolbox and pick a project first")
    return k


def ser_export_row(i: Interview) -> dict:
    return {"id": i.id, "participant_label": i.participant_label, "language": i.language,
            "form_id": i.form_version.form.id, "form_title": i.form_version.form.title,
            "version_no": i.form_version.version_no, "status": i.status, "review_state": i.review_state,
            "answers": len(effective_answers(i)), "started_at": (i.started_at or i.created_at).isoformat(),
            "kobo_state": i.kobo_state, "kobo_error": i.kobo_error,
            "kobo_sent_at": i.kobo_sent_at.isoformat() if i.kobo_sent_at else None}


def _approved(db: Session, project_id: int, form_id: int | None = None) -> list[Interview]:
    q = (select(Interview).join(FormVersion).join(Form)
         .where(Form.project_id == project_id, Interview.review_state == "approved").order_by(Interview.id.desc()))
    if form_id:
        q = q.where(Form.id == form_id)
    return list(db.scalars(q))


@router.get("/projects/{project_id}/kobo/interviews")
def export_list(project_id: int, form_id: int | None = None, db: Session = Depends(get_session)):
    return [ser_export_row(i) for i in _approved(db, project_id, form_id)]


@router.post("/interviews/{interview_id}/kobo")
async def send_interview(interview_id: int, db: Session = Depends(get_session)):
    i = db.get(Interview, interview_id)
    if i is None:
        raise HTTPException(404)
    if i.review_state != "approved":
        raise HTTPException(409, "Only approved interviews are sent to KoboToolbox")
    k = _ready(db, i.form_version.form.project_id)
    await asyncio.to_thread(send_one, i, k)
    db.commit()
    return ser_export_row(i)


class SendAllIn(BaseModel):
    form_id: int | None = None
    include_sent: bool = False


@router.post("/projects/{project_id}/kobo/send")
async def send_all(project_id: int, body: SendAllIn, db: Session = Depends(get_session)):
    k = _ready(db, project_id)
    todo = [i for i in _approved(db, project_id, body.form_id) if body.include_sent or i.kobo_state != "sent"]
    for i in todo:
        await asyncio.to_thread(send_one, i, k)
        db.commit()
    return {"sent": sum(1 for i in todo if i.kobo_state == "sent"),
            "failed": sum(1 for i in todo if i.kobo_state == "failed")}
