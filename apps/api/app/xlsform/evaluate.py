"""Evaluate XLSForm expressions (relevant, constraint, repeat_count, calculation).

Temporary, for the stage 2 trial runner: it covers comparisons, and/or, arithmetic and the
common functions. The plan is to replace the runner with ODK's xforms-engine, at which
point this module goes away. Parsing reuses the tree built in plain_logic (on top of
pyxform's expression lexer), so both agree on the syntax.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from app.xlsform.plain_logic import ParseError, _Parser, _tokens

Resolve = Callable[[str], Any]


class EvalError(Exception):
    pass


def parse(expr: str):
    try:
        return _Parser(_tokens(expr.strip())).parse()
    except (ParseError, IndexError) as e:
        raise EvalError(f"cannot parse {expr!r}: {e}") from e


def evaluate(expr: str, resolve: Resolve, current: Any = None) -> Any:
    """Evaluate an expression; `resolve(name)` returns the answer for ${name} (None if unanswered)."""
    return _Eval(resolve, current).ev(parse(expr))


def truthy(v: Any) -> bool:
    """XPath boolean(): numbers are true unless 0/NaN, strings unless empty."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return not (v == 0 or (isinstance(v, float) and math.isnan(v)))
    return str(v) != ""


def number(v: Any) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return math.nan


def string(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (list, tuple)):
        return " ".join(string(x) for x in v)
    return str(v)


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class _Eval:
    def __init__(self, resolve: Resolve, current: Any):
        self.resolve = resolve
        self.current = current

    def ev(self, n) -> Any:
        kind = n[0]
        if kind == "ref":
            return self.resolve(n[1])
        if kind == "self":
            return self.current
        if kind == "num":
            return float(n[1])
        if kind == "str":
            return n[1]
        if kind == "raw":
            # Excel writes booleans as TRUE/FALSE; other bare paths are empty node-sets here.
            return {"TRUE": True, "FALSE": False}.get(n[1].upper(), "")
        if kind == "paren":
            return self.ev(n[1])
        if kind == "neg":
            return -number(self.ev(n[1]))
        if kind == "and":
            return all(truthy(self.ev(x)) for x in n[1])
        if kind == "or":
            return any(truthy(self.ev(x)) for x in n[1])
        if kind == "cmp":
            return self.cmp(n[1], self.ev(n[2]), self.ev(n[3]))
        if kind == "math":
            a, b = number(self.ev(n[2])), number(self.ev(n[3]))
            op = n[1]
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "div":
                return a / b if b else math.nan
            if op == "mod":
                return math.fmod(a, b) if b else math.nan
        if kind == "call":
            return self.call(n[1], n[2])
        raise EvalError(f"unsupported expression part: {n!r}")

    def cmp(self, op: str, a: Any, b: Any) -> bool:
        if op in ("=", "!="):
            if _is_numeric(a) or _is_numeric(b) or isinstance(a, bool) or isinstance(b, bool):
                if isinstance(a, bool) or isinstance(b, bool):
                    eq = truthy(a) == truthy(b)
                else:
                    x, y = number(a), number(b)
                    eq = x == y if not (math.isnan(x) or math.isnan(y)) else string(a) == string(b)
            else:
                eq = string(a) == string(b)
            return eq if op == "=" else not eq
        x, y = number(a), number(b)
        if math.isnan(x) or math.isnan(y):
            return False
        return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]

    def call(self, name: str, args: list) -> Any:
        a = [self.ev(x) for x in args]
        if name == "selected":
            return string(a[1]) in string(a[0]).split()
        if name == "count-selected":
            return float(len(string(a[0]).split()))
        if name == "not":
            return not truthy(a[0])
        if name == "true":
            return True
        if name == "false":
            return False
        if name == "boolean":
            return truthy(a[0])
        if name == "string-length":
            return float(len(string(a[0] if a else self.current)))
        if name in ("number", "int"):
            v = number(a[0])
            return float(math.trunc(v)) if name == "int" and not math.isnan(v) else v
        if name == "round":
            v = number(a[0])
            places = int(number(a[1])) if len(a) > 1 else 0
            return round(v, places)
        if name == "string":
            return string(a[0])
        if name == "concat":
            return "".join(string(x) for x in a)
        if name == "coalesce":
            return a[0] if string(a[0]) != "" else a[1]
        if name == "if":
            return a[1] if truthy(a[0]) else a[2]
        if name == "today":
            return date.today().isoformat()
        if name == "now":
            return datetime.now().isoformat(timespec="seconds")
        if name == "regex":
            import re

            return re.search(string(a[1]), string(a[0])) is not None
        if name == "contains":
            return string(a[1]) in string(a[0])
        if name == "jr:choice-name":
            return string(a[0])
        raise EvalError(f"unsupported function {name}()")
