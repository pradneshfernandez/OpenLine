"""Read and write XLSForm workbooks with openpyxl (xlrd for legacy .xls).

Column headers are interpreted with pyxform's own header parser and alias tables, so
SurveyCTO/ODK/Kobo spellings ("relevance", "constraint message", "media:image",
"label::English (en)") resolve the same way pyxform resolves them.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

import openpyxl
import xlrd
from openpyxl.workbook import Workbook
from pyxform import aliases
from pyxform import constants as pc
from pyxform.parsing.sheet_headers import process_header
from pyxform.question import MultipleChoiceQuestion, Option
from pyxform.survey import Survey
from pyxform.xls2json_backends import xls_value_to_unicode, xlsx_value_to_str

SURVEY_COLUMNS = set(MultipleChoiceQuestion.get_slot_names())
CHOICE_COLUMNS = set(Option.get_slot_names()) | {"list_name", "list name"}
SETTINGS_COLUMNS = set(Survey.get_slot_names())

XLSX_MAGIC = b"PK\x03\x04"
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Translatable text fields, keyed by the first header token pyxform produces.
TEXT_FIELDS = {
    ("label",): "label",
    ("hint",): "hint",
    ("guidance_hint",): "guidance_hint",
    ("bind", "jr:constraintMsg"): "constraint_message",
    ("bind", "jr:requiredMsg"): "required_message",
}
BIND_FIELDS = {
    "relevant": "relevant",
    "required": "required",
    "constraint": "constraint",
    "calculate": "calculation",
    "readonly": "read_only",
}
CONTROL_FIELDS = {"appearance": "appearance", "jr:count": "repeat_count"}
MEDIA_KINDS = {"image", "big-image", "audio", "video"}


class WorkbookError(Exception):
    pass


def sniff_file_type(data: bytes) -> str:
    """Detect .xlsx vs .xls from the file content (extensions are often wrong)."""
    if data.startswith(XLSX_MAGIC):
        return "xlsx"
    if data.startswith(XLS_MAGIC):
        return "xls"
    raise WorkbookError("The file is not an Excel workbook (.xlsx or .xls).")


def xls_to_xlsx(data: bytes) -> bytes:
    """Convert a legacy .xls workbook to .xlsx, keeping every sheet and cell value."""
    book = xlrd.open_workbook(file_contents=data)
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in book.sheets():
        ws = wb.create_sheet(title=sheet.name)
        for r in range(sheet.nrows):
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    continue
                value = xls_value_to_unicode(cell.value, cell.ctype, book.datemode)
                ws.cell(row=r + 1, column=c + 1, value=value)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@dataclass
class Column:
    index: int  # 1-based openpyxl column index
    header: str
    tokens: tuple[str, ...]
    known: bool  # pyxform recognises this column


@dataclass
class Sheet:
    name: str
    columns: list[Column]
    rows: list[tuple[int, dict[str, str]]]  # (sheet row number, {header: value})

    def column(self, header: str) -> Column | None:
        return next((c for c in self.columns if c.header == header), None)


@dataclass
class XLSForm:
    sheets: dict[str, Sheet]  # lower-cased sheet name -> Sheet
    sheet_names: list[str]
    settings: dict[str, str] = field(default_factory=dict)

    @property
    def survey(self) -> Sheet:
        if "survey" not in self.sheets:
            raise WorkbookError("The workbook has no 'survey' sheet.")
        return self.sheets["survey"]

    @property
    def choices(self) -> Sheet | None:
        return self.sheets.get("choices")


def _parse_columns(headers: list[str | None], sheet: str) -> list[Column]:
    aliases_map, expected = {
        "survey": (aliases.survey_header, SURVEY_COLUMNS),
        "choices": (aliases.list_header, CHOICE_COLUMNS),
        "settings": (aliases.settings_header, SETTINGS_COLUMNS),
    }.get(sheet, ({}, set()))
    use_double_colon = any("::" in h for h in headers if h)
    cols = []
    for i, h in enumerate(headers, start=1):
        if h is None or not str(h).strip():
            continue
        h = str(h).strip()
        _, tokens = process_header(h, use_double_colon, aliases_map, expected)
        first = tokens[0]
        known = first in expected or first in ("bind", "control", "media", "body", "instance")
        cols.append(Column(index=i, header=h, tokens=tuple(tokens), known=known))
    return cols


def load_xlsform(xlsx: bytes) -> XLSForm:
    """Load a workbook's form sheets using cached cell values (like pyxform does)."""
    wb = openpyxl.load_workbook(io.BytesIO(xlsx), data_only=True, read_only=True)
    sheets: dict[str, Sheet] = {}
    for ws in wb.worksheets:
        key = ws.title.strip().lower()
        if key not in ("survey", "choices", "settings", "external_choices", "entities"):
            continue
        it = ws.iter_rows(values_only=True)
        try:
            headers = list(next(it))
        except StopIteration:
            sheets[key] = Sheet(ws.title, [], [])
            continue
        cols = _parse_columns(headers, key)
        rows = []
        for rownum, values in enumerate(it, start=2):
            row = {}
            for c in cols:
                v = values[c.index - 1] if c.index - 1 < len(values) else None
                if v is not None:
                    s = xlsx_value_to_str(v).strip()
                    if s:
                        row[c.header] = s
            if row:
                rows.append((rownum, row))
        sheets[key] = Sheet(ws.title, cols, rows)
    settings: dict[str, str] = {}
    if "settings" in sheets and sheets["settings"].rows:
        for c in sheets["settings"].columns:
            v = sheets["settings"].rows[0][1].get(c.header)
            if v:
                settings[c.tokens[0] if len(c.tokens) == 1 else c.header] = v
    names = list(wb.sheetnames)
    wb.close()
    return XLSForm(sheets=sheets, sheet_names=names, settings=settings)


# ---------------------------------------------------------------------------
# Languages


def default_language_key(form: XLSForm) -> str:
    """Language that untagged columns (`label`, `hint`, `constraint_message`) belong to.

    `settings.default_language` if set. Otherwise, when every used label column is tagged
    (`label::English (en)`), untagged hint/message columns belong to the first label language,
    not to pyxform's "default", which would show up as a language with no question text.
    """
    explicit = form.settings.get("default_language")
    if explicit:
        return explicit
    tagged: list[str] = []
    for sheet in (form.survey, form.choices):
        if not sheet:
            continue
        for c in sheet.columns:
            if c.tokens[0] != "label" or not any(c.header in row for _, row in sheet.rows):
                continue
            if len(c.tokens) == 1:
                return pc.DEFAULT_LANGUAGE_VALUE
            if c.tokens[1] not in tagged:
                tagged.append(c.tokens[1])
    return tagged[0] if tagged else pc.DEFAULT_LANGUAGE_VALUE


def languages(form: XLSForm) -> list[str]:
    """Languages from `label::<Language> (code)` style columns, in column order."""
    default = default_language_key(form)
    seen: list[str] = []
    for sheet in (form.survey, form.choices):
        if not sheet:
            continue
        for c in sheet.columns:
            if c.tokens[0] in ("label", "hint") or tuple(c.tokens[:2]) in TEXT_FIELDS:
                lang = _lang_of(c.tokens, default)
                used = any(c.header in row for _, row in sheet.rows)
                if lang and used and lang not in seen:
                    seen.append(lang)
    return seen


def _lang_of(tokens: tuple[str, ...], default: str) -> str | None:
    if tokens[0] in ("label", "hint", "guidance_hint"):
        return tokens[1] if len(tokens) > 1 else default
    if tokens[0] == "bind" and len(tokens) >= 2 and tokens[1] in ("jr:constraintMsg", "jr:requiredMsg"):
        return tokens[2] if len(tokens) > 2 else default
    if tokens[0] == "media":
        return tokens[2] if len(tokens) > 2 else None
    return None


def classify(col: Column, default_lang: str) -> tuple[str, str | None, str | None]:
    """Return (field, language, media_kind) for a column, e.g. ("label", "Hindi (hi)", None)."""
    t = col.tokens
    for prefix, name in TEXT_FIELDS.items():
        if t[: len(prefix)] == prefix:
            return name, _lang_of(t, default_lang), None
    if t[0] == "media" and len(t) >= 2:
        return "media", t[2] if len(t) > 2 else None, t[1]
    if t[0] == "bind" and len(t) >= 2 and t[1] in BIND_FIELDS:
        return BIND_FIELDS[t[1]], None, None
    if t[0] == "control" and len(t) >= 2 and t[1] in CONTROL_FIELDS:
        return CONTROL_FIELDS[t[1]], None, None
    if len(t) == 1:
        return t[0], None, None
    return col.header, None, None


# ---------------------------------------------------------------------------
# Writing edited versions


@dataclass
class CellEdit:
    sheet: str  # "survey" | "choices"
    row: int
    field: str  # label | hint | constraint_message | required | relevant | constraint
    lang: str | None
    value: str


FORM_SHEETS = ("survey", "choices", "settings")


def apply_edits(xlsx: bytes, edits: list[CellEdit], version_stamp: str | None = None) -> bytes:
    """Write cell edits into a copy of the workbook, keeping every sheet and column.

    Excel formulas in the form sheets are replaced by their cached values first: openpyxl
    cannot recalculate, and pyxform / KoboToolbox / ODK Central read cached values, so a
    re-saved formula would otherwise read as empty.
    """
    wb = openpyxl.load_workbook(io.BytesIO(xlsx))
    cached = openpyxl.load_workbook(io.BytesIO(xlsx), data_only=True)
    by_key = {ws.title.strip().lower(): ws for ws in wb.worksheets}
    for key in FORM_SHEETS:
        ws = by_key.get(key)
        if ws is None:
            continue
        cws = cached[ws.title]
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.value = cws.cell(row=cell.row, column=cell.column).value

    form = load_xlsform(xlsx)
    default_lang = default_language_key(form)
    for e in edits:
        ws = by_key.get(e.sheet)
        sheet = form.sheets.get(e.sheet)
        if ws is None or sheet is None:
            raise WorkbookError(f"Sheet '{e.sheet}' not found.")
        col = _find_column(sheet, e.field, e.lang, default_lang)
        if col is None:
            col = _add_column(ws, sheet, e.field, e.lang)
        ws.cell(row=e.row, column=col, value=e.value if e.value != "" else None)

    if version_stamp is not None:
        _set_setting(wb, by_key, "version", version_stamp)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _find_column(sheet: Sheet, field_name: str, lang: str | None, default_lang: str) -> int | None:
    matches = [c for c in sheet.columns if classify(c, default_lang)[:2] == (field_name, lang)]
    # Prefer an explicit "label::Lang" column over a plain "label" column.
    matches.sort(key=lambda c: _lang_of(c.tokens, None) is None)
    return matches[0].index if matches else None


HEADER_FOR_FIELD = {
    "label": "label",
    "hint": "hint",
    "constraint_message": "constraint_message",
    "required": "required",
    "relevant": "relevant",
    "constraint": "constraint",
}


def _add_column(ws, sheet: Sheet, field_name: str, lang: str | None) -> int:
    base = HEADER_FOR_FIELD.get(field_name)
    if base is None:
        raise WorkbookError(f"Cannot add a column for '{field_name}'.")
    header = base if lang in (None, pc.DEFAULT_LANGUAGE_VALUE) else f"{base}::{lang}"
    idx = ws.max_column + 1
    ws.cell(row=1, column=idx, value=header)
    sheet.columns.append(Column(idx, header, tuple(header.split("::")), True))
    return idx


def _set_setting(wb, by_key, key: str, value: str) -> None:
    ws = by_key.get("settings")
    if ws is None:
        ws = wb.create_sheet("settings")
        by_key["settings"] = ws
    for cell in ws[1]:
        if cell.value is not None and str(cell.value).strip().lower() == key:
            ws.cell(row=2, column=cell.column, value=value)
            return
    idx = (ws.max_column + 1) if ws.max_row >= 1 and any(c.value for c in ws[1]) else 1
    ws.cell(row=1, column=idx, value=key)
    ws.cell(row=2, column=idx, value=value)


def version_stamp() -> str:
    """A new settings.version so ODK Central / Kobo accept the re-upload as an update."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def neutralise_rows(xlsx: bytes, rows: list[int]) -> bytes:
    """Copy of the workbook where the given survey rows become empty `calculate` rows.

    Used only for the pyxform conversion of rows marked "not used by phone" (e.g.
    SurveyCTO-only types); the stored workbook keeps those rows untouched. Turning them
    into calculates keeps `${name}` references elsewhere in the form valid.
    """
    wb = openpyxl.load_workbook(io.BytesIO(xlsx))
    ws = next(w for w in wb.worksheets if w.title.strip().lower() == "survey")
    form = load_xlsform(xlsx)
    type_col = form.survey.column("type")
    calc_col = next(
        (c for c in form.survey.columns if c.tokens[:2] == ("bind", "calculate")), None
    )
    if calc_col is None:
        calc_idx = ws.max_column + 1
        ws.cell(row=1, column=calc_idx, value="calculation")
    else:
        calc_idx = calc_col.index
    keep = {"name", "type"}
    for r in rows:
        for c in form.survey.columns:
            if c.header not in keep and c.index != calc_idx:
                ws.cell(row=r, column=c.index, value=None)
        ws.cell(row=r, column=type_col.index, value="calculate")
        if not ws.cell(row=r, column=calc_idx).value:
            ws.cell(row=r, column=calc_idx, value="''")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
