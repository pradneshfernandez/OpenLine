"""Run pyxform and translate its errors/warnings into plain language with sheet + row."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from pyxform.errors import PyXFormError
from pyxform.xls2xform import convert

_ROW = re.compile(r"\[row\s*:\s*(\d+)\]\s*")
_SHEET = re.compile(r"(?:On|on|In|in) the '([\w-]+)' sheet")
_SHEET_ALT = re.compile(r"\b(survey|choices|settings|entities|external_choices) sheet\b", re.I)

# Rewrites for pyxform messages that are terse or technical. Matched against the
# message after the "[row : n]" prefix is removed.
_PLAIN = [
    (
        re.compile(r"Unknown question type '([^']+)'"),
        "The question type '{0}' is not a standard XLSForm type. It may be specific to "
        "another platform (e.g. SurveyCTO). Change the type, or mark the row \"not used by phone\".",
    ),
    (
        re.compile(r"There has been a problem trying to replace \$\{(\w+)\} with the XPath"),
        "A formula refers to ${{{0}}}, but there is no question with that name. Check the spelling.",
    ),
    (
        re.compile(r"Unmatched begin statement: (\w+)"),
        "A 'begin {0}' row has no matching 'end {0}' row.",
    ),
    (
        re.compile(r"Unmatched end statement"),
        "An 'end group' or 'end repeat' row has no matching 'begin' row above it.",
    ),
    (
        re.compile(r"List name not in choices sheet: (\S+)"),
        "The choice list '{0}' is used in the survey sheet but is missing from the choices sheet.",
    ),
]


@dataclass
class Message:
    level: str  # "error" | "warning"
    sheet: str | None
    row: int | None
    message: str  # plain-language
    original: str

    def to_dict(self) -> dict:
        return asdict(self)


def describe(text: str, level: str) -> Message:
    text = str(text).strip()
    row_m = _ROW.search(text)
    row = int(row_m.group(1)) if row_m else None
    body = _ROW.sub("", text).strip()
    sheet_m = _SHEET.search(body) or _SHEET_ALT.search(body)
    sheet = sheet_m.group(1).lower() if sheet_m else ("survey" if row else None)
    plain = body
    for pattern, template in _PLAIN:
        m = pattern.search(body)
        if m:
            plain = template.format(*m.groups())
            break
    return Message(level=level, sheet=sheet, row=row, message=plain, original=text)


@dataclass
class ConversionResult:
    ok: bool
    xform: str | None
    errors: list[Message]
    warnings: list[Message]


def run_pyxform(xlsx: bytes) -> ConversionResult:
    warnings: list[str] = []
    try:
        result = convert(xlsform=xlsx, warnings=warnings, pretty_print=True, file_type=".xlsx")
    except PyXFormError as e:
        return ConversionResult(False, None, [describe(str(e), "error")], _warnings(warnings))
    except Exception as e:  # pyxform can raise plain exceptions on malformed sheets
        return ConversionResult(
            False, None, [describe(f"{type(e).__name__}: {e}", "error")], _warnings(warnings)
        )
    return ConversionResult(True, result.xform, [], _warnings(warnings))


def _warnings(raw: list[str]) -> list[Message]:
    out = []
    for w in raw:
        # pyxform sometimes joins several warnings with newlines.
        for part in str(w).split("\n"):
            if part.strip():
                out.append(describe(part, "warning"))
    return out


_NS = {"h": "http://www.w3.org/1999/xhtml", "x": "http://www.w3.org/2002/xforms"}


def xform_identity(xform: str) -> tuple[str, str, str | None]:
    """Read (title, form_id, version) from the XForm, which is the master copy."""
    root = ET.fromstring(xform.encode())
    title = root.findtext("h:head/h:title", default="", namespaces=_NS)
    instance = root.find("h:head/x:model/x:instance", _NS)
    form_id, version = "", None
    if instance is not None and len(instance):
        data = instance[0]
        form_id = data.get("id", "")
        version = data.get("version")
    return title, form_id, version
