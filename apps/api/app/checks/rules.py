"""Phone-compatibility checks.

Each check is a function `(ctx) -> Iterable[Issue]`, registered with @check. Checks only
read question attributes, so they work on ORM Question rows and on plain dataclasses
(used in unit tests) alike.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.xlsform.text import spoken_text, word_count

BLOCKER, WARNING, INFO = "blocker", "warning", "info"

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "max_words": 40,
    "max_options": 6,
    "max_call_minutes": 30,
    "words_per_minute": 130,
    "seconds_per_answer": 8,
    "dont_know_refuse_codes": ["-98", "-99", "98", "99", "-88", "888", "999", "dk", "refused", "refuse", "dont_know"],
    "disabled_checks": [],
}

UNSUPPORTED_TYPES = {"geopoint", "geotrace", "geoshape", "image", "video", "barcode", "file",
                     "osm", "start-geopoint"}
BACKGROUND_TYPES = {"start", "end", "today", "deviceid", "subscriberid", "simserial",
                    "phonenumber", "username", "email", "audit", "calculate", "hidden",
                    "background-audio", "background-geopoint", "xml-external", "csv-external"}
SELECT_TYPES = {"select_one", "select_multiple", "rank"}
NUMBER_TYPES = {"integer", "decimal"}

_ENUMERATOR = re.compile(
    r"\b(enumerator|interviewer|surveyor|do not read|don'?t read|not read (?:out|aloud)|"
    r"read (?:out )?(?:the )?(?:options|choices|answers|list)|"
    r"do not prompt|probe|instructions?\s*:)\b",
    re.I,
)
_VISUAL = re.compile(
    r"\b(show(?:n|ing|s)?|point(?:ing)? (?:to|at)|tick(?:ing|ed)?|circl(?:e|ing|ed)|"
    r"(?:show(?:ing)? (?:the |this |a )?|this |the )cards?|pictures?|images?|look at|see (?:the|this|below)|"
    r"(?:on|in) the (?:screen|tablet))\b",
    re.I,
)
_QUESTION_START = re.compile(
    r"^(do|does|did|are|is|was|were|have|has|had|can|could|will|would|should|how|what|"
    r"when|where|which|who|whom|whose|why)\b",
    re.I,
)
_DK_LABEL = re.compile(r"\b(don'?t know|do not know|refuse[ds]?|no answer|prefer not)\b", re.I)


@dataclass
class Issue:
    check_code: str
    severity: str
    message: str
    suggestion: str
    question_name: str | None = None


@dataclass
class Context:
    questions: list[Any]
    choice_lists: dict[str, list[dict]]  # list_name -> [{name, labels, media}]
    languages: list[str]
    default_language: str
    thresholds: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))

    def label(self, q) -> str:
        return text_in(q.labels, self.default_language)

    def options(self, q) -> list[dict]:
        return self.choice_lists.get(q.choice_list or "", [])

    def asked(self) -> Iterable[Any]:
        """Questions the phone agent will speak (not groups, not background, not excluded)."""
        for q in self.questions:
            if q.not_used_by_phone or q.kind in ("group", "repeat", "background"):
                continue
            yield q


def text_in(texts: dict[str, str], lang: str) -> str:
    if not texts:
        return ""
    return texts.get(lang) or next((v for v in texts.values() if v), "")


CHECKS: dict[str, tuple[str, Callable[[Context], Iterable[Issue]]]] = {}


def check(code: str, title: str):
    def wrap(fn):
        CHECKS[code] = (title, fn)
        return fn

    return wrap


@check("unsupported_type", "Unsupported question type")
def unsupported_type(ctx: Context):
    for q in ctx.questions:
        if q.not_used_by_phone:
            continue
        is_signature = q.type == "image" and "signature" in (q.appearance or "")
        if q.type in UNSUPPORTED_TYPES or is_signature:
            what = "signature" if is_signature else q.type
            yield Issue(
                "unsupported_type", BLOCKER,
                f"'{q.name}' is a {what} question, which cannot be answered over the phone.",
                "Replace it with a spoken question (e.g. ask for the village name instead of "
                "a GPS point) or mark it \"not used by phone\".",
                q.name,
            )


@check("image_only", "Image-only question or options")
def image_only(ctx: Context):
    for q in ctx.asked():
        has_image = bool(q.media.get("image") or q.media.get("big-image"))
        if has_image and not any(spoken_text(v) for v in q.labels.values()):
            yield Issue("image_only", BLOCKER,
                        f"'{q.name}' has only an image and no text to read out.",
                        "Add spoken question text.", q.name)
        bad = [c["name"] for c in ctx.options(q)
               if (c.get("media", {}).get("image") or c.get("media", {}).get("big-image"))
               and not any(spoken_text(v) for v in c.get("labels", {}).values())]
        if bad:
            yield Issue("image_only", BLOCKER,
                        f"Options {', '.join(bad)} of '{q.name}' are images with no text.",
                        "Add a spoken label to each option.", q.name)


def _uppercase_instruction(text: str) -> bool:
    """True when most of the letters in the text are capitals (e.g. 'PROBE FOR DETAILS')."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    if len(words) < 3:
        return False
    upper = [w for w in words if w.isupper()]
    return len(upper) / len(words) > 0.6


@check("enumerator_text", "Enumerator-only text in the question")
def enumerator_text(ctx: Context):
    for q in ctx.asked():
        if not q.read_aloud:
            continue
        text = spoken_text(ctx.label(q))
        m = _ENUMERATOR.search(text)
        if m or _uppercase_instruction(text):
            found = f"\"{m.group(0)}\"" if m else "upper-case instructions"
            yield Issue("enumerator_text", WARNING,
                        f"'{q.name}' contains text meant for the enumerator ({found}).",
                        "Move the instruction to the hint, or switch \"read aloud\" off.", q.name)


@check("visual_reference", "Visual reference")
def visual_reference(ctx: Context):
    for q in ctx.asked():
        if not q.read_aloud:
            continue
        m = _VISUAL.search(spoken_text(ctx.label(q)))
        if m:
            yield Issue("visual_reference", WARNING,
                        f"'{q.name}' refers to something visual (\"{m.group(0)}\").",
                        "Reword the question so it works for listening only.", q.name)


def spoken_words(ctx: Context, q) -> int:
    n = word_count(ctx.label(q)) if q.read_aloud else 0
    if q.hint_read_aloud:
        n += word_count(text_in(q.hints, ctx.default_language))
    return n


@check("too_long", "Question too long")
def too_long(ctx: Context):
    limit = ctx.thresholds["max_words"]
    for q in ctx.asked():
        n = spoken_words(ctx, q)
        if n > limit:
            yield Issue("too_long", WARNING,
                        f"'{q.name}' has {n} spoken words (limit {limit}).",
                        "Shorten the question or split it in two.", q.name)


@check("too_many_options", "Too many options to read aloud")
def too_many_options(ctx: Context):
    limit = ctx.thresholds["max_options"]
    for q in ctx.asked():
        if q.type in ("select_one", "select_multiple") and len(ctx.options(q)) > limit:
            yield Issue("too_many_options", WARNING,
                        f"'{q.name}' has {len(ctx.options(q))} options (limit {limit}).",
                        "Ask it open-ended and match the answer to the list, or split it.", q.name)


GRID_GROUP = {"field-list", "table-list"}
GRID_CHILD = {"label", "list-nolabel", "list"}


@check("grid", "Grid / matrix")
def grid(ctx: Context):
    for g in ctx.questions:
        if g.kind != "group" or g.not_used_by_phone:
            continue
        group_app = set((g.appearance or "").split())
        if not group_app & GRID_GROUP:
            continue
        children = [q for q in ctx.questions if q.group_path and q.group_path[-1].get("row") == g.row]
        child_app = {a for q in children for a in (q.appearance or "").split()}
        if "table-list" in group_app or child_app & GRID_CHILD:
            yield Issue("grid", WARNING,
                        f"Group '{g.name}' is laid out as a table, which does not work by voice.",
                        "Turn the table into separate questions.", g.name)


@check("double_question", "Two questions in one")
def double_question(ctx: Context):
    for q in ctx.asked():
        if q.kind == "note" or not q.read_aloud:
            continue
        text = spoken_text(ctx.label(q))
        if text.count("?") >= 2:
            yield Issue("double_question", WARNING,
                        f"'{q.name}' has more than one question mark.",
                        "Split it into two questions.", q.name)
            continue
        parts = re.split(r",?\s+\b(?:and|or)\b\s+", text.rstrip("?"), flags=re.I)
        if len(parts) >= 2 and _QUESTION_START.match(parts[0]) and any(
            _QUESTION_START.match(p) for p in parts[1:]
        ):
            yield Issue("double_question", WARNING,
                        f"'{q.name}' seems to ask two things joined by \"and\"/\"or\".",
                        "Split it into two questions.", q.name)


@check("missing_translation", "Missing translation")
def missing_translation(ctx: Context):
    if len(ctx.languages) < 2:
        return
    for q in ctx.asked():
        for field_name, texts in (("question text", q.labels), ("hint", q.hints)):
            filled = [lang for lang in ctx.languages if (texts or {}).get(lang)]
            missing = [lang for lang in ctx.languages if not (texts or {}).get(lang)]
            if filled and missing:
                yield Issue("missing_translation", WARNING,
                            f"'{q.name}' {field_name} is missing in {', '.join(missing)}.",
                            "Add the translation.", q.name)
        opts_missing = sorted({lang for c in ctx.options(q) for lang in ctx.languages
                               if c.get("labels") and not c["labels"].get(lang)})
        if opts_missing:
            yield Issue("missing_translation", WARNING,
                        f"Some options of '{q.name}' are missing in {', '.join(opts_missing)}.",
                        "Add the translation.", q.name)


@check("no_dont_know", "No \"don't know\" / \"refuse\" option")
def no_dont_know(ctx: Context):
    codes = {str(c).strip().lower() for c in ctx.thresholds["dont_know_refuse_codes"]}
    for q in ctx.asked():
        if not q.required or q.type not in SELECT_TYPES:
            continue
        opts = ctx.options(q)
        has = any(str(c["name"]).strip().lower() in codes
                  or any(_DK_LABEL.search(spoken_text(v)) for v in c.get("labels", {}).values())
                  for c in opts)
        if opts and not has:
            yield Issue("no_dont_know", INFO,
                        f"'{q.name}' is required but has no \"don't know\" or \"refuse\" option.",
                        "Add the codes your team uses (e.g. -98 / -99).", q.name)


@check("number_no_range", "Number with no range")
def number_no_range(ctx: Context):
    for q in ctx.asked():
        if q.type in NUMBER_TYPES and not (q.constraint or "").strip():
            yield Issue("number_no_range", INFO,
                        f"'{q.name}' is a number with no allowed range.",
                        "Add a range constraint so spoken numbers can be checked.", q.name)


@check("repeat_no_count", "Repeat with no count")
def repeat_no_count(ctx: Context):
    for q in ctx.questions:
        if q.kind == "repeat" and not q.not_used_by_phone and not (q.repeat_count or "").strip():
            yield Issue("repeat_no_count", INFO,
                        f"Repeat '{q.name}' has no repeat_count.",
                        "The agent will ask \"anyone else?\"; add a count question if known.", q.name)


@check("background_field", "Background fields")
def background_field(ctx: Context):
    for q in ctx.questions:
        if q.type in BACKGROUND_TYPES or q.kind == "background":
            yield Issue("background_field", INFO,
                        f"'{q.name}' ({q.type}) is not spoken; it is recorded automatically or skipped.",
                        "No action needed.", q.name)


def estimate_minutes(ctx: Context) -> float:
    """Words read aloud / words-per-minute, plus a fixed time per answer."""
    words = 0
    answers = 0
    max_opts = ctx.thresholds["max_options"]
    for q in ctx.asked():
        words += spoken_words(ctx, q)
        if q.kind != "note":
            answers += 1
            opts = ctx.options(q)
            if q.type in SELECT_TYPES and 0 < len(opts) <= max_opts:
                words += sum(word_count(text_in(c.get("labels", {}), ctx.default_language))
                             for c in opts)
    seconds = words / ctx.thresholds["words_per_minute"] * 60 + answers * ctx.thresholds["seconds_per_answer"]
    return round(seconds / 60, 1)


@check("long_call", "Long call")
def long_call(ctx: Context):
    minutes = estimate_minutes(ctx)
    limit = ctx.thresholds["max_call_minutes"]
    if minutes > limit:
        yield Issue("long_call", WARNING,
                    f"Estimated call length is {minutes} minutes (limit {limit}).",
                    "Shorten the form or split it into two calls.", None)
