"""Upload, versioning, editing, phone checks and diffs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from deepdiff import DeepDiff
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.checks.engine import merged_thresholds, run_checks, status_for
from app.config import settings
from app.models import (
    ChoiceList,
    EditLog,
    Form,
    FormVersion,
    PhoneCheckReport,
    PhoneIssue,
    Project,
    Question,
)
from app.xlsform.convert import ConversionResult, Message, describe, run_pyxform, xform_identity
from app.xlsform.parse import ParsedForm, parse_form, platform_extras, summarize
from app.xlsform.workbook import (
    CellEdit,
    WorkbookError,
    apply_edits,
    load_xlsform,
    neutralise_rows,
    sniff_file_type,
    version_stamp,
    xls_to_xlsx,
)


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, errors: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.errors = errors or []


@dataclass
class UploadOutcome:
    form: Form
    version: FormVersion | None  # the usable version, if conversion succeeded
    original: FormVersion
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    platform_warnings: list[dict] = field(default_factory=list)
    platform_rows: list[dict] = field(default_factory=list)


def default_project(session: Session) -> Project:
    project = session.scalar(select(Project).order_by(Project.id))
    if project is None:
        project = Project(name="Default project", owner="", settings={})
        session.add(project)
        session.commit()
    return project


# ---------------------------------------------------------------------------
# Upload


def _check_upload(filename: str, data: bytes) -> str:
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ServiceError(f"The file is larger than {settings.max_upload_mb} MB.", 413)
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise ServiceError("Only XLSForm files (.xlsx or .xls) can be uploaded.", 415)
    try:
        return sniff_file_type(data)
    except WorkbookError as e:
        raise ServiceError(str(e), 415) from e


def upload_form(
    session: Session, project: Project, filename: str, data: bytes, user: str,
    exclude_platform_rows: bool = False, form: Form | None = None,
) -> UploadOutcome:
    """Store the original unchanged, then try to build a usable version from it.

    For a new form the original is version 0. Re-uploading into an existing form stores
    the new original and creates the next version from it.
    """
    file_type = _check_upload(filename, data)
    original_rel = storage.save_bytes(data, "originals", "." + file_type)
    if form is None:
        form = Form(project_id=project.id, title=filename.rsplit(".", 1)[0], form_id="")
        session.add(form)
        session.flush()
        original = FormVersion(
            form=form, version_no=0, created_by=user, original_file=original_rel,
            original_filename=filename, message="Original upload",
        )
        session.add(original)
        session.flush()
    else:
        original = FormVersion(  # placeholder, not persisted: the new original lives on the new version
            form_id=form.id, version_no=-1, original_file=original_rel, original_filename=filename,
        )
    outcome = _build_version(session, form, original, data, file_type, user, exclude_platform_rows)
    session.commit()
    return outcome


def convert_original(session: Session, form: Form, user: str, exclude_platform_rows: bool) -> UploadOutcome:
    """Retry conversion of a form's version 0 (e.g. after choosing to exclude SurveyCTO rows)."""
    original = next((v for v in form.versions if v.version_no == 0), None)
    if original is None:
        raise ServiceError("This form has no original upload.", 404)
    if any(v.version_no > 0 for v in form.versions):
        raise ServiceError("This form already has a usable version.", 409)
    data = storage.read_bytes(original.original_file)
    outcome = _build_version(session, form, original, data, sniff_file_type(data), user, exclude_platform_rows)
    session.commit()
    return outcome


def _build_version(
    session: Session, form: Form, original: FormVersion, data: bytes, file_type: str,
    user: str, exclude_platform_rows: bool,
) -> UploadOutcome:
    try:
        xlsx = data if file_type == "xlsx" else xls_to_xlsx(data)
        wb = load_xlsform(xlsx)
        parsed = parse_form(wb)
    except Exception as e:  # unreadable workbook, missing survey sheet, ...
        msg = describe(str(e), "error").to_dict()
        return UploadOutcome(form, None, original, errors=[msg])

    p_warnings, p_rows = platform_extras(wb, parsed)
    excluded_names = [r["name"] for r in p_rows] if exclude_platform_rows else []
    result = _convert(xlsx, parsed, excluded_names)
    if not result.ok:
        errors = [_with_context(m.to_dict(), parsed) for m in result.errors]
        if p_rows and not exclude_platform_rows:
            # pyxform stops at the first unknown type, without a row number. List every
            # platform-specific row so the user can mark them all at once.
            errors += [
                Message("error", "survey", r["row"],
                        f"'{r['name']}' uses the {r['platform']} type '{r['type']}'.", "").to_dict()
                for r in p_rows
            ]
        return UploadOutcome(form, None, original, errors=errors,
                             warnings=[m.to_dict() for m in result.warnings],
                             platform_warnings=p_warnings, platform_rows=p_rows)

    prev = max(form.versions, key=lambda v: v.version_no, default=None)
    version = FormVersion(
        form=form,
        version_no=(prev.version_no + 1) if prev else 1,
        parent_version=prev.id if prev else None,
        created_by=user,
        message="Uploaded" if original.version_no == 0 else f"Re-uploaded {original.original_filename}",
        original_file=original.original_file,
        original_filename=original.original_filename,
        xlsx_file=storage.save_bytes(xlsx, "versions", ".xlsx"),
        xform_xml=result.xform,
        pyxform_warnings=[m.to_dict() for m in result.warnings],
        platform_warnings=p_warnings,
        languages=parsed.languages,
        excluded_rows=excluded_names,
    )
    _fill_version(session, form, version, parsed, result, flags={})
    run_phone_check(session, version)
    return UploadOutcome(form, version, original,
                         warnings=version.pyxform_warnings, platform_warnings=p_warnings,
                         platform_rows=p_rows)


_ERROR_COLUMNS = {"relevant": "relevant", "constraint": "constraint", "calculation": "calculation",
                  "required": "required_raw", "choice_filter": None, "repeat_count": "repeat_count"}


def _with_context(err: dict, parsed: ParsedForm) -> dict:
    """Add the question name, and the offending expression, to a pyxform error with a row."""
    if err.get("sheet") != "survey" or not err.get("row"):
        return err
    q = next((q for q in parsed.questions if q.row == err["row"]), None)
    if q is None:
        return err
    err["question"] = q.name
    for col, attr in _ERROR_COLUMNS.items():
        if f"'{col}'" in err["original"] and attr and getattr(q, attr, ""):
            err["message"] += f" ({col} of '{q.name}' is: {getattr(q, attr)})"
            break
    return err


def _convert(xlsx: bytes, parsed: ParsedForm, excluded_names: list[str]) -> ConversionResult:
    rows = [q.row for q in parsed.questions if q.name in set(excluded_names)]
    return run_pyxform(neutralise_rows(xlsx, rows) if rows else xlsx)


def _fill_version(
    session: Session, form: Form, version: FormVersion, parsed: ParsedForm,
    result: ConversionResult, flags: dict[str, dict[str, bool]],
) -> None:
    """Attach questions / choice lists to a new version and refresh the form header."""
    title, form_id, _ = xform_identity(result.xform)
    form.title = title or form.title
    form.form_id = form_id or form.form_id
    form.default_language = parsed.default_language
    excluded = set(version.excluded_rows)
    version.summary = {**summarize(parsed), "title": form.title, "form_id": form.form_id,
                       "xform_version": parsed.settings.get("version")}
    session.add(version)
    session.flush()
    for q in parsed.questions:
        f = flags.get(q.name, {})
        session.add(Question(
            version_id=version.id, position=q.position, number=q.number, row=q.row,
            name=q.name, type=q.type, raw_type=q.raw_type, kind=q.kind,
            group_path=q.group_path, labels=q.labels, hints=q.hints,
            choice_list=q.choice_list, required=q.required, required_raw=q.required_raw,
            constraint=q.constraint, constraint_message=q.constraint_message,
            relevant=q.relevant, relevant_plain=q.relevant_plain, calculation=q.calculation,
            repeat_count=q.repeat_count, default=q.default, appearance=q.appearance,
            media=q.media, extra=q.extra,
            read_aloud=f.get("read_aloud", True),
            hint_read_aloud=f.get("hint_read_aloud", False),
            not_used_by_phone=f.get("not_used_by_phone", q.name in excluded),
        ))
    for cl in parsed.choice_lists.values():
        session.add(ChoiceList(version_id=version.id, list_name=cl.list_name, choices=cl.choices))
    session.flush()
    session.refresh(version)


# ---------------------------------------------------------------------------
# Editing

QUESTION_TEXT_FIELDS = {"label", "hint", "constraint_message"}
QUESTION_RAW_FIELDS = {"relevant", "constraint"}
QUESTION_FLAG_FIELDS = {"read_aloud", "hint_read_aloud", "not_used_by_phone"}
ATTR = {"label": "labels", "hint": "hints", "constraint_message": "constraint_message"}


def latest_version(form: Form) -> FormVersion | None:
    usable = [v for v in form.versions if v.version_no > 0]
    return max(usable, key=lambda v: v.version_no) if usable else None


def save_edits(session: Session, base: FormVersion, user: str, message: str, changes: list[dict]) -> FormVersion:
    form = base.form
    latest = latest_version(form)
    if latest is None or latest.id != base.id:
        raise ServiceError("This is not the latest version. Reload and apply your edits again.", 409)
    if not changes:
        raise ServiceError("No changes to save.")

    questions = {q.name: q for q in base.questions if q.name}
    lists = {cl.list_name: cl for cl in base.choice_lists}
    flags = {q.name: {"read_aloud": q.read_aloud, "hint_read_aloud": q.hint_read_aloud,
                      "not_used_by_phone": q.not_used_by_phone} for q in base.questions}
    cell_edits: list[CellEdit] = []
    log: list[dict] = []

    for ch in changes:
        target = ch.get("target", "question")
        fld = ch.get("field")
        lang = ch.get("lang")
        value = ch.get("value")
        if target == "choice":
            cl = lists.get(ch.get("list_name", ""))
            choice = next((c for c in cl.choices if c["name"] == ch.get("choice_name")), None) if cl else None
            if choice is None or fld != "label":
                raise ServiceError(f"Cannot edit option {ch.get('list_name')}/{ch.get('choice_name')}.")
            old = choice["labels"].get(lang, "")
            value = str(value or "")
            if old != value:
                cell_edits.append(CellEdit("choices", choice["row"], "label", lang, value))
                log.append(dict(question_name=f"{cl.list_name}/{choice['name']}",
                                field=f"option label [{lang}]", old_value=old, new_value=value))
            continue

        q = questions.get(ch.get("question_name", ""))
        if q is None:
            raise ServiceError(f"Unknown question '{ch.get('question_name')}'.")
        if fld in QUESTION_TEXT_FIELDS:
            old = getattr(q, ATTR[fld]).get(lang, "")
            value = str(value or "")
            if old != value:
                cell_edits.append(CellEdit("survey", q.row, fld, lang, value))
                log.append(dict(question_name=q.name, field=f"{fld} [{lang}]", old_value=old, new_value=value))
        elif fld in QUESTION_RAW_FIELDS:
            old = getattr(q, fld) or ""
            value = str(value or "").strip()
            if old != value:
                cell_edits.append(CellEdit("survey", q.row, fld, None, value))
                log.append(dict(question_name=q.name, field=fld, old_value=old, new_value=value))
        elif fld == "required":
            new = bool(value)
            if new != q.required:
                cell_edits.append(CellEdit("survey", q.row, "required", None, "yes" if new else ""))
                log.append(dict(question_name=q.name, field="required",
                                old_value=q.required_raw or "", new_value="yes" if new else ""))
        elif fld in QUESTION_FLAG_FIELDS:
            new = bool(value)
            if new != flags[q.name][fld]:
                flags[q.name][fld] = new
                log.append(dict(question_name=q.name, field=fld,
                                old_value=str(not new).lower(), new_value=str(new).lower()))
        else:
            raise ServiceError(f"The field '{fld}' cannot be edited in this stage.")

    if not log:
        raise ServiceError("Nothing changed.")

    base_xlsx = storage.read_bytes(base.xlsx_file)
    new_xlsx = apply_edits(base_xlsx, cell_edits, version_stamp()) if cell_edits else base_xlsx
    parsed = parse_form(load_xlsform(new_xlsx))
    before = [q.name for q in base.questions]
    after = [q.name for q in parsed.questions]
    if before != after:  # guard: stage 1 never renames, adds or removes questions
        raise ServiceError("This edit would change variable names; it was not saved.", 422)

    result = _convert(new_xlsx, parsed, list(base.excluded_rows))
    if not result.ok:
        raise ServiceError("pyxform rejected the edited form, so it was not saved.", 422,
                           [_with_context(m.to_dict(), parsed) for m in result.errors])

    version = FormVersion(
        form=form, version_no=base.version_no + 1, parent_version=base.id,
        created_by=user, message=message or f"{len(log)} change(s)",
        original_file=base.original_file, original_filename=base.original_filename,
        xlsx_file=storage.save_bytes(new_xlsx, "versions", ".xlsx"),
        xform_xml=result.xform, pyxform_warnings=[m.to_dict() for m in result.warnings],
        platform_warnings=base.platform_warnings, languages=parsed.languages,
        excluded_rows=list(base.excluded_rows),
    )
    _fill_version(session, form, version, parsed, result, flags)
    for entry in log:
        session.add(EditLog(version_id=version.id, user=user, **entry))
    run_phone_check(session, version)
    session.commit()
    return version


# ---------------------------------------------------------------------------
# Phone check


def run_phone_check(session: Session, version: FormVersion) -> PhoneCheckReport:
    project = version.form.project
    choice_lists = {cl.list_name: cl.choices for cl in version.choice_lists}
    result = run_checks(version.questions, choice_lists, version.languages,
                        version.form.default_language or "default", project.settings)

    # Carry "accepted" decisions forward from the form's previous report, and mark
    # issues that no longer occur as fixed there.
    previous = session.scalar(
        select(PhoneCheckReport).join(FormVersion)
        .where(FormVersion.form_id == version.form_id)
        .order_by(PhoneCheckReport.run_at.desc(), PhoneCheckReport.id.desc())
    )
    accepted: dict[tuple, str] = {}
    current_keys = {(i.question_name, i.check_code) for i in result.issues}
    if previous is not None:
        for old in previous.issues:
            key = (old.question_name, old.check_code)
            if old.state == "accepted":
                accepted[key] = old.accepted_reason
            elif old.state == "open" and key not in current_keys:
                old.state = "fixed"

    report = PhoneCheckReport(
        version_id=version.id, thresholds=result.thresholds,
        status=status_for(result.issues, set(accepted)),
        blocker_count=result.counts["blocker"], warning_count=result.counts["warning"],
        info_count=result.counts["info"], estimated_minutes=result.estimated_minutes,
    )
    session.add(report)
    session.flush()
    for i in result.issues:
        key = (i.question_name, i.check_code)
        session.add(PhoneIssue(
            report_id=report.id, question_name=i.question_name, check_code=i.check_code,
            severity=i.severity, message=i.message, suggestion=i.suggestion,
            state="accepted" if key in accepted else "open",
            accepted_reason=accepted.get(key, ""),
        ))
    session.flush()
    session.refresh(report)
    return report


def latest_report(session: Session, version_id: int) -> PhoneCheckReport | None:
    return session.scalar(
        select(PhoneCheckReport).where(PhoneCheckReport.version_id == version_id)
        .order_by(PhoneCheckReport.run_at.desc(), PhoneCheckReport.id.desc())
    )


def set_issue_state(session: Session, issue: PhoneIssue, user: str, accept: bool, reason: str) -> PhoneIssue:
    if accept and not reason.strip():
        raise ServiceError("Please give a reason for accepting this issue.")
    report = session.get(PhoneCheckReport, issue.report_id)
    old_state = issue.state
    issue.state = "accepted" if accept else "open"
    issue.accepted_reason = reason.strip() if accept else ""
    session.add(EditLog(
        version_id=report.version_id, question_name=issue.question_name,
        field=f"phone issue {issue.check_code}", old_value=old_state,
        new_value=f"accepted: {issue.accepted_reason}" if accept else "open", user=user,
    ))
    accepted = {(i.question_name, i.check_code) for i in report.issues if i.state == "accepted"}
    report.status = status_for(report.issues, accepted)
    session.commit()
    return issue


def update_thresholds(session: Session, project: Project, values: dict[str, Any]) -> dict:
    merged = merged_thresholds({**(project.settings or {}), **values})
    project.settings = merged
    session.commit()
    return merged


# ---------------------------------------------------------------------------
# Diff

DIFF_FIELDS = ["type", "labels", "hints", "choice_list", "required", "constraint",
               "constraint_message", "relevant", "appearance", "default", "media",
               "read_aloud", "hint_read_aloud", "not_used_by_phone"]


def _snapshot(version: FormVersion) -> dict[str, Any]:
    return {
        "questions": {q.name or f"row {q.row}": {f: getattr(q, f) for f in DIFF_FIELDS}
                      for q in version.questions},
        "choices": {cl.list_name: {c["name"]: c["labels"] for c in cl.choices}
                    for cl in version.choice_lists},
    }


def diff_versions(a: FormVersion, b: FormVersion) -> list[dict]:
    """Field-level differences from version a to version b, computed with DeepDiff."""
    dd = DeepDiff(_snapshot(a), _snapshot(b), view="tree", verbose_level=2)
    rows = []
    for change_type, items in dd.items():
        for item in items:
            path = item.path(output_format="list")
            section, *rest = path
            if section == "questions":
                subject = rest[0] if rest else ""
                fld = ".".join(str(p) for p in rest[1:]) or "(question)"
            else:
                subject = "/".join(str(p) for p in rest[:2])
                fld = "option label" + (f" [{rest[2]}]" if len(rest) > 2 else "")
            old = item.t1 if not _missing(item.t1) else None
            new = item.t2 if not _missing(item.t2) else None
            rows.append({"section": section, "subject": subject, "field": fld,
                         "change": change_type, "old": _fmt(old), "new": _fmt(new)})
    rows.sort(key=lambda r: (r["section"] != "questions", r["subject"], r["field"]))
    return rows


def _missing(v) -> bool:
    return type(v).__name__ == "NotPresent"


def _fmt(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)
