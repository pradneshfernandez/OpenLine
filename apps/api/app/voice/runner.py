"""Form runner: decides which question comes next and checks answers.

The bot talks to the runner only through this interface (stage 2 doc §5.2):

    start(lang) / current() / answer(name, value) / code(name, kind) / back(name) /
    next() / finish()

This is the temporary Python runner for the trial. It reads stage 1's stored question list
and supports notes, text/integer/decimal/select questions, groups, repeats (with or without
repeat_count), relevant, constraint, required, calculate and background fields. It will be
replaced by ODK's xforms-engine behind the same interface.

Skip logic is re-evaluated on every step: next() returns the first relevant item in form
order that has no answer yet, so a corrected answer automatically brings in (or drops) the
questions that depend on it. finish() returns only answers that are still relevant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.xlsform.evaluate import EvalError, evaluate, string, truthy
from app.xlsform.text import spoken_text

DK, REFUSED = "dk", "refused"
UNCLEAR = "unclear"  # no valid answer after repeated tries (§5.7); flagged for review
SELECT_TYPES = {"select_one", "select_multiple"}
AUTO_TYPES = {"start", "end", "today", "deviceid", "subscriberid", "simserial", "phonenumber",
              "username", "email", "audit", "hidden", "background-audio", "background-geopoint",
              "start-geopoint", "xml-external", "csv-external"}
ANOTHER = "__another__"  # synthetic yes/no item for repeats without a repeat_count

Index = tuple[int, ...]  # repeat instance path, e.g. (0,) for the first child
Key = tuple[str, Index]


@dataclass
class Item:
    """A question as the bot sees it, already in the call language."""

    name: str
    index: Index
    type: str
    kind: str
    text: str
    hint: str = ""
    options: list[dict] = field(default_factory=list)  # [{name, label}]
    required: bool = False
    constraint_message: str = ""
    repeat: dict | None = None  # {name, label, index (0-based), count}
    first_in_instance: bool = False

    @property
    def key(self) -> Key:
        return (self.name, self.index)

    @property
    def is_note(self) -> bool:
        return self.kind == "note"

    def to_dict(self) -> dict:
        return {"name": self.name, "index": list(self.index), "type": self.type, "kind": self.kind,
                "text": self.text, "hint": self.hint, "options": self.options,
                "required": self.required, "constraint_message": self.constraint_message,
                "repeat": self.repeat}


@dataclass
class Result:
    ok: bool
    message: str = ""
    value: Any = None


@dataclass
class Stored:
    value: Any = None
    code: str | None = None  # dk / refused


@dataclass
class _Node:
    q: dict
    children: list["_Node"] = field(default_factory=list)


def pick_language(languages: list[str], default: str | None, lang: str) -> str:
    """Map a call language ('en', 'hi', 'hi-IN', 'Hindi') to one of the form's language keys."""
    from app.voice.i18n import LANGUAGES, lang_code

    code = lang_code(lang)
    name, native, _ = LANGUAGES[code]
    for key in languages:
        low = key.lower()
        if f"({code})" in low or low == code or low.startswith(name.lower()) or native in key:
            return key
    return default if default in languages else (languages[0] if languages else "default")


class FormRunner:
    def __init__(self, questions: list[dict], choice_lists: dict[str, list[dict]],
                 languages: list[str], default_language: str | None,
                 dk_codes: tuple[str, ...] = ("-98", "98", "dk", "dont_know"),
                 refused_codes: tuple[str, ...] = ("-99", "99", "refused", "refuse")):
        self.questions = [q for q in questions if q.get("name")]
        self.by_name = {q["name"]: q for q in self.questions}
        self.choice_lists = choice_lists
        self.languages = languages
        self.default_language = default_language
        self.lang = default_language or (languages[0] if languages else "default")
        self.dk_codes, self.refused_codes = dk_codes, refused_codes
        self.answers: dict[Key, Stored] = {}
        self.seen_notes: set[Key] = set()
        self.started_at: str | None = None
        self._current: Item | None = None
        self._warned: set[str] = set()
        self._tree = self._build_tree()

    # ------------------------------------------------------------------ interface

    def start(self, lang: str) -> Item | None:
        self.lang = pick_language(self.languages, self.default_language, lang)
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self.next()

    def current(self) -> Item | None:
        return self._current

    def next(self) -> Item | None:
        """The first relevant item without an answer, or None when the form is done."""
        for item in self._walk():
            if item.is_note:
                if item.key in self.seen_notes:
                    continue
                self.seen_notes.add(item.key)
                self._current = item
                return item
            if item.key not in self.answers:
                self._current = item
                return item
        self._current = None
        return None

    def answer(self, name: str, value: Any) -> Result:
        item = self._item_for(name)
        if item is None:
            return Result(False, f"There is no question called {name} at this point.")
        if item.name == ANOTHER:
            return self._answer_another(item, value)
        coerced, err = self._coerce(item, value)
        if err:
            return Result(False, err)
        if coerced in (None, "", []):
            if item.required:
                return Result(False, self._msg("required"))
        q = self.by_name[item.name]
        if q.get("constraint") and coerced not in (None, ""):
            try:
                ok = truthy(evaluate(q["constraint"], self._resolver(item.index), current=coerced))
            except EvalError as e:
                logger.warning(f"constraint of {item.name} not evaluated: {e}")
                ok = True
            if not ok:
                return Result(False, item.constraint_message or self._msg("invalid"))
        self.answers[item.key] = Stored(coerced)
        return Result(True, value=coerced)

    def code(self, name: str, kind: str) -> Result:
        item = self._item_for(name)
        if item is None:
            return Result(False, f"There is no question called {name} at this point.")
        if kind not in (DK, REFUSED, UNCLEAR):
            return Result(False, "kind must be 'dk', 'refused' or 'unclear'")
        self.answers[item.key] = Stored(None, kind)
        return Result(True)

    def back(self, name: str) -> Item | None:
        """Go back to an earlier question (latest instance) so its answer can be changed."""
        for item in reversed(list(self._walk())):
            if item.name == name and item.key in self.answers:
                self._current = item
                return item
        return None

    def finish(self) -> dict[str, Any]:
        """Flat answers keyed by variable name (repeats as name[1], name[2], …).

        Only answers that are still relevant are returned; dk/refused appear as their code.
        """
        out: dict[str, Any] = {}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for item in self._walk(include_auto=True):
            q = self.by_name.get(item.name)
            if q is None:
                continue
            col = flat_name(item.name, item.index)
            if q["type"] == "start":
                out[col] = self.started_at
            elif q["type"] == "end":
                out[col] = now
            elif q["type"] == "today":
                out[col] = now[:10]
            elif q["type"] == "calculate":
                out[col] = string(self._calc(item))
            elif item.key in self.answers:
                s = self.answers[item.key]
                out[col] = s.code if s.code else s.value
        return out

    def answered_names(self) -> list[str]:
        return sorted({name for (name, _), s in self.answers.items() if name != ANOTHER})

    def stored(self, item: Item) -> Stored | None:
        return self.answers.get(item.key)

    # ------------------------------------------------------------------ structure

    def _build_tree(self) -> list[_Node]:
        root: list[_Node] = []
        stack: list[tuple[int, list[_Node]]] = [(-1, root)]
        for q in self.questions:
            depth = len(q.get("group_path") or [])
            while len(stack) > 1 and stack[-1][0] >= depth:
                stack.pop()
            node = _Node(q)
            stack[-1][1].append(node)
            if q["kind"] in ("group", "repeat"):
                stack.append((depth, node.children))
        return root

    def _walk(self, include_auto: bool = False):
        yield from self._walk_nodes(self._tree, (), None, include_auto, {"first": False})

    def _walk_nodes(self, nodes: list[_Node], index: Index, repeat: dict | None,
                    include_auto: bool, instance: dict):
        """Yield relevant items in form order. `instance["first"]` is True until the first
        spoken item of the current repeat instance has been yielded."""
        for node in nodes:
            q = node.q
            if q.get("not_used_by_phone") and not include_auto:
                continue
            if not self._relevant(q, index):
                continue
            kind = q["kind"]
            if kind == "group":
                yield from self._walk_nodes(node.children, index, repeat, include_auto, instance)
                continue
            if kind == "repeat":
                yield from self._walk_repeat(node, index, include_auto)
                continue
            if q["type"] in AUTO_TYPES or q["type"] == "calculate":
                if include_auto:
                    yield self._item(q, index, repeat)
                continue
            item = self._item(q, index, repeat)
            item.first_in_instance = instance["first"]
            instance["first"] = False
            yield item

    def _walk_repeat(self, node: _Node, index: Index, include_auto: bool):
        q = node.q
        label = self._text(q.get("labels") or {}, index) or q["name"]
        if (q.get("repeat_count") or "").strip():
            try:
                count = int(float(string(evaluate(q["repeat_count"], self._resolver(index)))) or 0)
            except (EvalError, ValueError):
                count = 0
            for i in range(max(count, 0)):
                rep = {"name": q["name"], "label": label, "index": i, "count": count}
                yield from self._walk_nodes(node.children, index + (i,), rep, include_auto, {"first": True})
            return
        # No repeat_count: ask "anyone else?" after each instance.
        i = 0
        while True:
            rep = {"name": q["name"], "label": label, "index": i, "count": None}
            yield from self._walk_nodes(node.children, index + (i,), rep, include_auto, {"first": True})
            another = Item(ANOTHER, index + (i,), "select_one", "question",
                           self._msg("another", label=label), required=True,
                           options=[{"name": "yes", "label": self._msg("yes")},
                                    {"name": "no", "label": self._msg("no")}],
                           repeat={**rep, "name": q["name"]})
            stored = self.answers.get(another.key)
            if stored is None:
                if not include_auto:
                    yield another
                return
            if stored.value != "yes":
                return
            i += 1

    def _item(self, q: dict, index: Index, repeat: dict | None) -> Item:
        options = []
        if q["type"] in SELECT_TYPES and q.get("choice_list"):
            for c in self.choice_lists.get(q["choice_list"], []):
                options.append({"name": c["name"], "label": self._text(c.get("labels") or {}, index) or c["name"]})
        return Item(
            name=q["name"], index=index, type=q["type"], kind=q["kind"],
            text=self._text(q.get("labels") or {}, index),
            hint=self._text(q.get("hints") or {}, index),
            options=options, required=bool(q.get("required")),
            constraint_message=self._text(q.get("constraint_message") or {}, index),
            repeat=repeat,
        )

    def _item_for(self, name: str) -> Item | None:
        cur = self._current
        if cur is not None and cur.name == name:
            return cur
        for item in self._walk():
            if item.name == name:
                return item
        return None

    # ------------------------------------------------------------------ values

    def _resolver(self, index: Index):
        def resolve(name: str) -> Any:
            q = self.by_name.get(name)
            if q is None:
                return None
            depth = sum(1 for g in q.get("group_path") or [] if g.get("type") == "repeat")
            idx = index[:depth] if len(index) >= depth else index + (0,) * (depth - len(index))
            if q["type"] == "calculate":
                return self._calc(Item(name, idx, "calculate", "background", ""))
            s = self.answers.get((name, idx))
            if s is None or s.code:
                return "" if s is None else s.code
            v = s.value
            return " ".join(v) if isinstance(v, list) else v
        return resolve

    def _calc(self, item: Item) -> Any:
        q = self.by_name[item.name]
        if not q.get("calculation"):
            return ""
        try:
            return evaluate(q["calculation"], self._resolver(item.index))
        except EvalError:
            return ""

    def _relevant(self, q: dict, index: Index) -> bool:
        expr = (q.get("relevant") or "").strip()
        if not expr:
            return True
        try:
            return truthy(evaluate(expr, self._resolver(index)))
        except EvalError as e:
            if q["name"] not in self._warned:
                self._warned.add(q["name"])
                logger.warning(f"relevant of {q['name']} not evaluated, treated as true: {e}")
            return True

    def _text(self, texts: dict[str, str], index: Index) -> str:
        raw = texts.get(self.lang) or texts.get(self.default_language or "") or next(
            (v for v in texts.values() if v), "")
        resolve = self._resolver(index)
        raw = re.sub(r"\$\{([^}]+)\}", lambda m: string(resolve(m.group(1))), raw)
        return spoken_text(raw)

    def _coerce(self, item: Item, value: Any) -> tuple[Any, str | None]:
        if value is None:
            return None, None
        t = item.type
        if t == "integer":
            m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
            if not m:
                return None, self._msg("number")
            num = float(m.group(0))
            if not num.is_integer():
                return None, self._msg("whole_number")
            return int(num), None
        if t == "decimal":
            m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
            return (float(m.group(0)), None) if m else (None, self._msg("number"))
        if t == "select_one":
            name = self._match_option(item, value)
            return (name, None) if name is not None else (None, self._msg("option"))
        if t == "select_multiple":
            values = value if isinstance(value, list) else str(value).split()
            names = [self._match_option(item, v) for v in values]
            if any(n is None for n in names):
                return None, self._msg("option")
            return names, None
        return str(value).strip(), None

    def _match_option(self, item: Item, value: Any) -> str | None:
        v = str(value).strip()
        q = self.by_name.get(item.name)
        choices = self.choice_lists.get(q.get("choice_list") or "", []) if q else []
        for c in choices:
            if c["name"] == v:
                return c["name"]
        low = v.lower()
        for c in choices:
            if c["name"].lower() == low or any(spoken_text(lbl).lower() == low for lbl in (c.get("labels") or {}).values()):
                return c["name"]
        return None

    def _answer_another(self, item: Item, value: Any) -> Result:
        v = str(value).strip().lower()
        if v not in ("yes", "no"):
            return Result(False, self._msg("option"))
        self.answers[item.key] = Stored(v)
        return Result(True, value=v)

    def is_dk_code(self, option_name: str) -> str | None:
        n = option_name.lower()
        if n in self.dk_codes:
            return DK
        if n in self.refused_codes:
            return REFUSED
        return None

    def _msg(self, key: str, **kw) -> str:
        from app.voice.i18n import phrase

        return phrase(self.lang, key, **kw)


def flat_name(name: str, index: Index) -> str:
    return name + "".join(f"[{i + 1}]" for i in index)


def runner_for_version(version) -> FormRunner:
    """Build a runner from a stage 1 FormVersion (questions and choice lists from the DB)."""
    from app.api.routes import ser_question

    return FormRunner(
        questions=[ser_question(q) for q in version.questions],
        choice_lists={cl.list_name: cl.choices for cl in version.choice_lists},
        languages=version.languages,
        default_language=version.form.default_language,
    )
