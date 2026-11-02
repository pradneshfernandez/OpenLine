from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form as FormField, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services, storage
from app.checks.engine import merged_thresholds
from app.checks.rules import CHECKS
from app.db import get_session
from app.models import EditLog, Form, FormVersion, PhoneCheckReport, PhoneIssue, Project

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]


def _user(x_user: str | None) -> str:
    return (x_user or "").strip() or "anonymous"


# ---------------------------------------------------------------------------
# Serialisers


def ser_version(v: FormVersion, full: bool = False) -> dict[str, Any]:
    out = {
        "id": v.id, "form_id": v.form_id, "version_no": v.version_no,
        "parent_version": v.parent_version, "created_by": v.created_by,
        "created_at": v.created_at.isoformat(), "message": v.message,
        "original_filename": v.original_filename, "has_xform": v.xform_xml is not None,
        "summary": v.summary, "languages": v.languages,
    }
    if full:
        out |= {
            "pyxform_warnings": v.pyxform_warnings, "platform_warnings": v.platform_warnings,
            "excluded_rows": v.excluded_rows,
        }
    return out


def ser_question(q) -> dict[str, Any]:
    return {c: getattr(q, c) for c in (
        "id", "position", "number", "row", "name", "type", "raw_type", "kind", "group_path",
        "labels", "hints", "choice_list", "required", "required_raw", "constraint",
        "constraint_message", "relevant", "relevant_plain", "calculation", "repeat_count",
        "default", "appearance", "media", "extra", "read_aloud", "hint_read_aloud",
        "not_used_by_phone",
    )}


def ser_report(r: PhoneCheckReport | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {
        "id": r.id, "version_id": r.version_id, "run_at": r.run_at.isoformat(),
        "status": r.status, "estimated_minutes": r.estimated_minutes, "thresholds": r.thresholds,
        "counts": {"blocker": r.blocker_count, "warning": r.warning_count, "info": r.info_count},
        "issues": [ser_issue(i) for i in r.issues],
    }


def ser_issue(i: PhoneIssue) -> dict[str, Any]:
    return {c: getattr(i, c) for c in (
        "id", "report_id", "question_name", "check_code", "severity", "message", "suggestion",
        "state", "accepted_reason",
    )} | {"check_title": CHECKS.get(i.check_code, (i.check_code,))[0]}


def ser_log(e: EditLog) -> dict[str, Any]:
    return {"id": e.id, "version_id": e.version_id, "question_name": e.question_name,
            "field": e.field, "old_value": e.old_value, "new_value": e.new_value,
            "user": e.user, "time": e.time.isoformat()}


def ser_upload(session: Session, o: services.UploadOutcome) -> dict[str, Any]:
    return {
        "ok": o.version is not None,
        "form": {"id": o.form.id, "title": o.form.title, "form_id": o.form.form_id},
        "original_version_id": o.original.id,
        "version": ser_version(o.version, full=True) if o.version else None,
        "report": ser_report(services.latest_report(session, o.version.id)) if o.version else None,
        "errors": o.errors, "warnings": o.warnings,
        "platform_warnings": o.platform_warnings, "platform_rows": o.platform_rows,
    }


def _get(session: Session, model, id_: int):
    obj = session.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


def _raise(e: services.ServiceError):
    raise HTTPException(e.status, {"message": e.message, "errors": e.errors})


# ---------------------------------------------------------------------------
# Projects


class ProjectIn(BaseModel):
    name: str
    owner: str = ""


@router.get("/projects")
def list_projects(session: SessionDep):
    services.default_project(session)
    return [{"id": p.id, "name": p.name, "owner": p.owner}
            for p in session.scalars(select(Project).order_by(Project.id))]


@router.post("/projects")
def create_project(body: ProjectIn, session: SessionDep):
    p = Project(name=body.name, owner=body.owner, settings={})
    session.add(p)
    session.commit()
    return {"id": p.id, "name": p.name, "owner": p.owner}


@router.get("/projects/{project_id}/settings")
def get_settings(project_id: int, session: SessionDep):
    p = _get(session, Project, project_id)
    return {"thresholds": merged_thresholds(p.settings),
            "checks": [{"code": c, "title": t} for c, (t, _) in CHECKS.items()]}


@router.put("/projects/{project_id}/settings")
def put_settings(project_id: int, body: dict[str, Any], session: SessionDep):
    p = _get(session, Project, project_id)
    return {"thresholds": services.update_thresholds(session, p, body)}


@router.get("/projects/{project_id}/forms")
def list_forms(project_id: int, session: SessionDep):
    p = _get(session, Project, project_id)
    out = []
    for f in sorted(p.forms, key=lambda f: f.created_at, reverse=True):
        latest = services.latest_version(f)
        report = services.latest_report(session, latest.id) if latest else None
        out.append({
            "id": f.id, "title": f.title, "form_id": f.form_id,
            "created_at": f.created_at.isoformat(),
            "latest_version": ser_version(latest) if latest else None,
            "phone_status": report.status if report else None,
            "estimated_minutes": report.estimated_minutes if report else None,
            "version_count": len([v for v in f.versions if v.version_no > 0]),
        })
    return out


@router.post("/projects/{project_id}/forms/upload")
async def upload(
    project_id: int, session: SessionDep, file: UploadFile = File(...),
    exclude_platform_rows: bool = FormField(False), x_user: str | None = Header(None),
):
    p = _get(session, Project, project_id)
    data = await file.read()
    try:
        o = services.upload_form(session, p, file.filename or "form.xlsx", data, _user(x_user),
                                 exclude_platform_rows)
    except services.ServiceError as e:
        _raise(e)
    return ser_upload(session, o)


# ---------------------------------------------------------------------------
# Forms


@router.get("/forms/{form_id}")
def get_form(form_id: int, session: SessionDep):
    f = _get(session, Form, form_id)
    latest = services.latest_version(f)
    return {
        "id": f.id, "project_id": f.project_id, "title": f.title, "form_id": f.form_id,
        "default_language": f.default_language,
        "latest_version_id": latest.id if latest else None,
        "versions": [ser_version(v) | {"phone_status": (r.status if (r := services.latest_report(session, v.id)) else None)}
                     for v in sorted(f.versions, key=lambda v: v.version_no, reverse=True)],
    }


@router.delete("/forms/{form_id}")
def delete_form(form_id: int, session: SessionDep):
    session.delete(_get(session, Form, form_id))
    session.commit()
    return {"ok": True}


@router.post("/forms/{form_id}/upload")
async def reupload(
    form_id: int, session: SessionDep, file: UploadFile = File(...),
    exclude_platform_rows: bool = FormField(False), x_user: str | None = Header(None),
):
    f = _get(session, Form, form_id)
    data = await file.read()
    try:
        o = services.upload_form(session, f.project, file.filename or "form.xlsx", data,
                                 _user(x_user), exclude_platform_rows, form=f)
    except services.ServiceError as e:
        _raise(e)
    return ser_upload(session, o)


class ConvertIn(BaseModel):
    exclude_platform_rows: bool = True


@router.post("/forms/{form_id}/convert")
def convert(form_id: int, body: ConvertIn, session: SessionDep, x_user: str | None = Header(None)):
    f = _get(session, Form, form_id)
    try:
        o = services.convert_original(session, f, _user(x_user), body.exclude_platform_rows)
    except services.ServiceError as e:
        _raise(e)
    return ser_upload(session, o)


@router.get("/forms/{form_id}/edit-log")
def form_edit_log(form_id: int, session: SessionDep):
    rows = session.scalars(
        select(EditLog).join(FormVersion).where(FormVersion.form_id == form_id)
        .order_by(EditLog.time.desc(), EditLog.id.desc())
    )
    return [ser_log(e) for e in rows]


# ---------------------------------------------------------------------------
# Versions


@router.get("/versions/diff")
def diff(a: int, b: int, session: SessionDep):
    va, vb = _get(session, FormVersion, a), _get(session, FormVersion, b)
    if va.form_id != vb.form_id:
        raise HTTPException(400, "Versions belong to different forms")
    if va.xform_xml is None or vb.xform_xml is None:
        raise HTTPException(400, "Version 0 is the original upload; compare converted versions")
    return {"a": ser_version(va), "b": ser_version(vb), "changes": services.diff_versions(va, vb),
            "xform_a": va.xform_xml, "xform_b": vb.xform_xml}


@router.get("/forms/{form_id}/versions/{version_no}")
def get_version_by_number(form_id: int, version_no: int, session: SessionDep):
    """Same as GET /versions/{id}, addressed the way the UI shows it (form + "v1")."""
    v = session.scalar(select(FormVersion).where(FormVersion.form_id == form_id,
                                                 FormVersion.version_no == version_no))
    if v is None:
        raise HTTPException(404, "Version not found")
    return _version_detail(session, v)


@router.get("/versions/{version_id}")
def get_version(version_id: int, session: SessionDep):
    return _version_detail(session, _get(session, FormVersion, version_id))


def _version_detail(session: Session, v: FormVersion) -> dict[str, Any]:
    return ser_version(v, full=True) | {
        "form": {"id": v.form.id, "title": v.form.title, "form_id": v.form.form_id,
                 "default_language": v.form.default_language, "project_id": v.form.project_id},
        "is_latest": (lv := services.latest_version(v.form)) is not None and lv.id == v.id,
        "questions": [ser_question(q) for q in v.questions],
        "choice_lists": {cl.list_name: cl.choices for cl in v.choice_lists},
        "report": ser_report(services.latest_report(session, v.id)),
    }


@router.get("/versions/{version_id}/download")
def download(version_id: int, session: SessionDep, kind: Literal["original", "xlsx", "xform"] = Query("xlsx")):
    v = _get(session, FormVersion, version_id)
    base = (v.form.form_id or f"form{v.form_id}").replace("/", "_")
    if kind == "original":
        name = v.original_filename or f"{base}-original" + storage.path_of(v.original_file).suffix
        return Response(storage.read_bytes(v.original_file), media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    if kind == "xlsx":
        if not v.xlsx_file:
            raise HTTPException(404, "This version has no converted workbook")
        return Response(storage.read_bytes(v.xlsx_file),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{base}-v{v.version_no}.xlsx"'})
    if not v.xform_xml:
        raise HTTPException(404, "This version has no XForm")
    return Response(v.xform_xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{base}-v{v.version_no}.xml"'})


class Change(BaseModel):
    target: Literal["question", "choice"] = "question"
    question_name: str | None = None
    list_name: str | None = None
    choice_name: str | None = None
    field: str
    lang: str | None = None
    value: Any = None


class EditsIn(BaseModel):
    message: str = ""
    changes: list[Change]


@router.post("/versions/{version_id}/edits")
def save_edits(version_id: int, body: EditsIn, session: SessionDep, x_user: str | None = Header(None)):
    v = _get(session, FormVersion, version_id)
    try:
        nv = services.save_edits(session, v, _user(x_user), body.message,
                                 [c.model_dump() for c in body.changes])
    except services.ServiceError as e:
        _raise(e)
    return {"version": ser_version(nv, full=True),
            "report": ser_report(services.latest_report(session, nv.id))}


@router.get("/versions/{version_id}/edit-log")
def version_edit_log(version_id: int, session: SessionDep):
    rows = session.scalars(select(EditLog).where(EditLog.version_id == version_id).order_by(EditLog.id))
    return [ser_log(e) for e in rows]


@router.get("/versions/{version_id}/phone-check")
def get_report(version_id: int, session: SessionDep):
    _get(session, FormVersion, version_id)
    return ser_report(services.latest_report(session, version_id))


@router.post("/versions/{version_id}/phone-check")
def rerun_report(version_id: int, session: SessionDep):
    v = _get(session, FormVersion, version_id)
    if v.xform_xml is None:
        raise HTTPException(400, "Version 0 is the original upload and cannot be checked")
    r = services.run_phone_check(session, v)
    session.commit()
    return ser_report(r)


# ---------------------------------------------------------------------------
# Issues


class AcceptIn(BaseModel):
    reason: str = ""


@router.post("/issues/{issue_id}/accept")
def accept_issue(issue_id: int, body: AcceptIn, session: SessionDep, x_user: str | None = Header(None)):
    try:
        i = services.set_issue_state(session, _get(session, PhoneIssue, issue_id), _user(x_user), True, body.reason)
    except services.ServiceError as e:
        _raise(e)
    return ser_issue(i)


@router.post("/issues/{issue_id}/reopen")
def reopen_issue(issue_id: int, session: SessionDep, x_user: str | None = Header(None)):
    i = services.set_issue_state(session, _get(session, PhoneIssue, issue_id), _user(x_user), False, "")
    return ser_issue(i)
