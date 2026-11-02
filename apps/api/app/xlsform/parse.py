"""Build the question list and choice lists of a form from its XLSForm sheets.

We read the sheets ourselves (openpyxl + pyxform's header parser) rather than relying on
pyxform's internal JSON, which is not a stable interface. The XForm XML produced by
pyxform remains the master copy of the form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pyxform import aliases
from pyxform.parsing.sheet_headers import to_snake_case
from pyxform.question_type_dictionary import QUESTION_TYPE_DICT

from app.xlsform.plain_logic import explain_relevant
from app.xlsform.workbook import XLSForm, classify, default_language_key, languages

CANONICAL_TYPES = [
    "text", "integer", "decimal", "range", "date", "time", "datetime", "geopoint",
    "geotrace", "geoshape", "image", "audio", "video", "file", "barcode", "note",
    "acknowledge", "trigger", "calculate", "hidden", "start", "end", "today", "deviceid",
    "subscriberid", "simserial", "phonenumber", "username", "email", "audit",
    "background-audio", "background-geopoint", "start-geopoint", "osm", "xml-external",
    "csv-external",
]  # fmt: skip
SELECT_CANONICAL = {"select one": "select_one", "select all that apply": "select_multiple",
                    "rank": "rank", "select one external": "select_one_external"}
_SELECT_KEYS = sorted(aliases.select, key=len, reverse=True)
BACKGROUND_TYPES = {
    "start", "end", "today", "deviceid", "subscriberid", "simserial", "phonenumber",
    "username", "email", "audit", "calculate", "hidden", "background-audio",
    "background-geopoint", "start-geopoint", "xml-external", "csv-external",
}  # fmt: skip
_TRUE = {"yes", "true", "true()", "1"}


def canonical_type(raw: str) -> tuple[str, str | None, bool]:
    """Return (type, choice_list, known_to_pyxform) for a survey `type` cell."""
    t = " ".join(raw.split())
    low = t.lower()
    for key in _SELECT_KEYS:
        if low.startswith(key + " ") or low.startswith(key.replace(" ", "_") + " "):
            rest = t[len(key) + 1 :].split()
            base = aliases.select[key]
            list_name = rest[0] if rest else None
            return SELECT_CANONICAL.get(base, base.replace(" ", "_")), list_name, True
    snake = to_snake_case(t)
    if snake in ("begin_group", "begin_repeat", "end_group", "end_repeat"):
        return snake, None, True
    if snake in ("begin_lgroup", "begin_looped_group"):
        return "begin_repeat", None, True
    if snake in ("end_lgroup", "end_looped_group"):
        return "end_repeat", None, True
    if t in CANONICAL_TYPES:
        return t, None, True
    entry = QUESTION_TYPE_DICT.get(t) or QUESTION_TYPE_DICT.get(low)
    if entry is not None:
        for c in CANONICAL_TYPES:
            if QUESTION_TYPE_DICT.get(c) == entry:
                return c, None, True
        return low, None, True
    return low, None, False


def kind_of(qtype: str, appearance: str) -> str:
    if qtype in ("begin_group", "begin_repeat"):
        return qtype.removeprefix("begin_")
    if qtype == "note":
        return "note"
    if qtype in BACKGROUND_TYPES:
        return "background"
    return "question"


@dataclass
class ParsedQuestion:
    position: int
    row: int
    name: str
    type: str
    raw_type: str
    kind: str
    known_type: bool
    group_path: list[dict]
    labels: dict[str, str] = field(default_factory=dict)
    hints: dict[str, str] = field(default_factory=dict)
    choice_list: str | None = None
    required: bool = False
    required_raw: str = ""
    constraint: str = ""
    constraint_message: dict[str, str] = field(default_factory=dict)
    relevant: str = ""
    relevant_plain: str = ""
    calculation: str = ""
    repeat_count: str = ""
    default: str = ""
    appearance: str = ""
    media: dict[str, dict[str, str]] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)
    number: int | None = None


@dataclass
class ParsedChoiceList:
    list_name: str
    choices: list[dict]


@dataclass
class ParsedForm:
    questions: list[ParsedQuestion]
    choice_lists: dict[str, ParsedChoiceList]
    languages: list[str]
    default_language: str
    settings: dict[str, str]
    unknown_columns: dict[str, list[str]]


def parse_choices(form: XLSForm, default_lang: str) -> dict[str, ParsedChoiceList]:
    lists: dict[str, ParsedChoiceList] = {}
    sheet = form.choices
    if sheet is None:
        return lists
    list_col = next((c for c in sheet.columns if c.tokens[0] in ("list_name", "list name")), None)
    if list_col is None:
        return lists
    for rownum, row in sheet.rows:
        list_name = row.get(list_col.header)
        if not list_name:
            continue
        choice = {"row": rownum, "name": "", "labels": {}, "media": {}, "extra": {}}
        for c in sheet.columns:
            v = row.get(c.header)
            if v is None or c is list_col:
                continue
            f, lang, media_kind = classify(c, default_lang)
            if f == "name":
                choice["name"] = v
            elif f == "label":
                choice["labels"][lang] = v
            elif f == "media":
                choice["media"].setdefault(media_kind, {})[lang or ""] = v
            else:
                choice["extra"][c.header] = v
        lists.setdefault(list_name, ParsedChoiceList(list_name, [])).choices.append(choice)
    return lists


def parse_form(form: XLSForm) -> ParsedForm:
    default_lang = default_language_key(form)
    langs = languages(form)
    choice_lists = parse_choices(form, default_lang)
    survey = form.survey
    type_col = survey.column("type") or next((c for c in survey.columns if c.tokens[0] == "type"), None)
    name_col = next((c for c in survey.columns if c.tokens[0] == "name"), None)
    unknown_survey = [c.header for c in survey.columns if not c.known]

    questions: list[ParsedQuestion] = []
    stack: list[dict] = []
    number = 0
    for rownum, row in survey.rows:
        raw_type = row.get(type_col.header, "") if type_col else ""
        if not raw_type:
            continue
        qtype, list_name, known = canonical_type(raw_type)
        if qtype in ("end_group", "end_repeat"):
            if stack:
                stack.pop()
            continue
        name = row.get(name_col.header, "") if name_col else ""
        q = ParsedQuestion(
            position=len(questions),
            row=rownum,
            name=name,
            type=qtype,
            raw_type=raw_type,
            kind="",
            known_type=known,
            group_path=[dict(g) for g in stack],
            choice_list=list_name,
        )
        for c in survey.columns:
            v = row.get(c.header)
            if v is None or c is type_col or c is name_col:
                continue
            f, lang, media_kind = classify(c, default_lang)
            if f == "label":
                q.labels[lang] = v
            elif f == "hint":
                q.hints[lang] = v
            elif f == "constraint_message":
                q.constraint_message[lang] = v
            elif f == "media":
                q.media.setdefault(media_kind, {})[lang or ""] = v
            elif f == "required":
                q.required_raw = v
                q.required = v.strip().lower() in _TRUE
            elif f in ("constraint", "relevant", "calculation", "repeat_count", "default", "appearance"):
                setattr(q, f, v)
            else:
                q.extra[c.header] = v
        q.kind = kind_of(qtype, q.appearance)
        if not known:
            q.kind = "unknown"
        if q.kind in ("question", "note", "unknown"):
            number += 1
            q.number = number
        if q.kind in ("group", "repeat"):
            stack.append({"name": name, "type": q.kind, "row": rownum})
        questions.append(q)

    by_name = {q.name: q for q in questions if q.name}

    def lookup(ref: str):
        target = by_name.get(ref)
        if target is None:
            return None
        labels = {}
        if target.choice_list and target.choice_list in choice_lists:
            for ch in choice_lists[target.choice_list].choices:
                lbl = ch["labels"].get(default_lang) or next(iter(ch["labels"].values()), ch["name"])
                labels[ch["name"]] = _short(lbl)
        return target.type, labels

    for q in questions:
        q.relevant_plain = explain_relevant(q.relevant, lookup)

    return ParsedForm(
        questions=questions,
        choice_lists=choice_lists,
        languages=langs,
        default_language=default_lang,
        settings=form.settings,
        unknown_columns={"survey": unknown_survey},
    )


def _short(text: str) -> str:
    from app.xlsform.text import spoken_text

    s = spoken_text(text)
    return s if len(s) <= 60 else s[:57] + "…"


def summarize(parsed: ParsedForm) -> dict:
    qs = parsed.questions
    return {
        "question_count": sum(1 for q in qs if q.kind in ("question", "unknown")),
        "note_count": sum(1 for q in qs if q.kind == "note"),
        "background_count": sum(1 for q in qs if q.kind == "background"),
        "group_count": sum(1 for q in qs if q.kind == "group"),
        "repeat_count": sum(1 for q in qs if q.kind == "repeat"),
        "choice_list_count": len(parsed.choice_lists),
        "languages": parsed.languages,
        "default_language": parsed.default_language,
    }


# ---------------------------------------------------------------------------
# Platform-specific extras (SurveyCTO / KoboToolbox)

SURVEYCTO_TYPES = {
    "caseid", "calculate_here", "text audit", "audio audit", "sensor_statistic",
    "sensor_stream", "speed violations count", "speed violations list",
    "speed violations audit", "comments", "geopoint_offline",
}  # fmt: skip
SURVEYCTO_COLUMNS = {"publishable", "response_note", "minimum_seconds", "note", "disabled",
                     "click_to_edit", "summary"}
_CUSTOM_APPEARANCE = re.compile(r"\bcustom-[\w-]+")
_KOBO_COLUMN = re.compile(r"^(kobo--|\$kuid|\$autoname|\$prev|\$given_name)")


def platform_extras(form: XLSForm, parsed: ParsedForm) -> tuple[list[dict], list[dict]]:
    """Return (warnings, surveycto_rows) describing platform-specific content.

    surveycto_rows are rows pyxform will reject (unknown types) that can be marked
    "not used by phone".
    """
    warnings: list[dict] = []
    sct_rows: list[dict] = []
    for q in parsed.questions:
        raw = " ".join(q.raw_type.lower().split())
        if not q.known_type:
            platform = "SurveyCTO" if raw in SURVEYCTO_TYPES else "another platform"
            sct_rows.append({"row": q.row, "name": q.name, "type": q.raw_type, "platform": platform})
            warnings.append({
                "platform": platform,
                "sheet": "survey",
                "row": q.row,
                "message": f"Question type '{q.raw_type}' ({q.name}) is specific to {platform} "
                           "and is not part of standard XLSForm.",
            })
        m = _CUSTOM_APPEARANCE.search(q.appearance or "")
        if m:
            plugin = m.group(0)
            what = "phone-call plug-in" if "phone-call" in plugin else "field plug-in"
            warnings.append({
                "platform": "SurveyCTO",
                "sheet": "survey",
                "row": q.row,
                "message": f"'{q.name}' uses the SurveyCTO {what} '{plugin}'. Other tools "
                           "ignore it; the phone agent will treat it as a normal question.",
            })
    survey = form.survey
    for c in survey.columns:
        h = c.header.strip()
        if _KOBO_COLUMN.match(h):
            warnings.append({"platform": "KoboToolbox", "sheet": "survey", "row": 1,
                             "message": f"KoboToolbox column '{h}' is kept but not used."})
        elif h.lower() in SURVEYCTO_COLUMNS:
            warnings.append({"platform": "SurveyCTO", "sheet": "survey", "row": 1,
                             "message": f"SurveyCTO column '{h}' is kept but not used."})
    for name in form.sheet_names:
        if name.lower().startswith("surveycto") or name.lower().startswith("help-"):
            warnings.append({"platform": "SurveyCTO", "sheet": name, "row": None,
                             "message": f"Extra sheet '{name}' is kept unchanged."})
    return warnings, sct_rows
