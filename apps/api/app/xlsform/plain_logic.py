"""Explain XLSForm expressions (relevant / constraint) in plain language.

Tokenising uses pyxform's own expression lexer (pyxform.parsing.expression), so we agree
with pyxform on what a reference, literal or function call is. A small recursive-descent
parser on top builds a tree that is rendered as English, e.g.

    ${age} >= 18 and selected(${consent}, 'yes')
    -> Only if age is 18 or more and consent is "Yes"
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pyxform.parsing.expression import parse_expression

# lookup(name) -> (question type, {choice code: label}) or None if unknown.
Lookup = Callable[[str], "tuple[str, dict[str, str]] | None"]


@dataclass
class Tok:
    type: str
    value: str


class ParseError(Exception):
    pass


def _tokens(expr: str) -> list[Tok]:
    out: list[Tok] = []
    for t in parse_expression(expr):
        if t.type == "WHITESPACE":
            continue
        # The lexer splits ">=" / "<=" into two OPS_COMP tokens; join them back.
        if t.type == "OPS_COMP" and out and out[-1].type == "OPS_COMP" and t.value == "=":
            out[-1] = Tok("OPS_COMP", out[-1].value + "=")
            continue
        out.append(Tok(t.type, t.value.strip() if t.type in ("OPS_BOOL", "OPS_MATH") else t.value))
    return out


class _Parser:
    def __init__(self, tokens: list[Tok]):
        self.t = tokens
        self.i = 0

    def peek(self) -> Tok | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> Tok:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end")
        self.i += 1
        return tok

    def parse(self):
        node = self.or_()
        if self.peek() is not None:
            raise ParseError(f"unexpected {self.peek().value!r}")
        return node

    def _binary(self, sub, kind: str, ops: tuple[str, ...]):
        items = [sub()]
        while (p := self.peek()) and p.type in ("OPS_BOOL",) and p.value in ops:
            self.take()
            items.append(sub())
        return items[0] if len(items) == 1 else (kind, items)

    def or_(self):
        return self._binary(self.and_, "or", ("or",))

    def and_(self):
        return self._binary(self.cmp, "and", ("and",))

    def cmp(self):
        left = self.add()
        p = self.peek()
        if p and p.type == "OPS_COMP":
            op = self.take().value
            return ("cmp", op, left, self.add())
        return left

    def add(self):
        left = self.unary()
        while (p := self.peek()) and p.type == "OPS_MATH":
            op = self.take().value
            left = ("math", op, left, self.unary())
        return left

    def unary(self):
        p = self.peek()
        if p and p.type == "OPS_MATH" and p.value == "-":
            self.take()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        tok = self.take()
        if tok.type == "PYXFORM_REF":
            return ("ref", tok.value[2:-1].removeprefix("last-saved#"))
        if tok.type == "NUMBER":
            return ("num", tok.value)
        if tok.type == "SYSTEM_LITERAL":
            return ("str", tok.value[1:-1])
        if tok.type == "OPEN_PAREN":
            node = self.or_()
            if self.take().type != "CLOSE_PAREN":
                raise ParseError("missing )")
            return ("paren", node)
        if tok.type == "FUNC_CALL":
            name = tok.value[:-1]
            args = []
            if self.peek() and self.peek().type == "CLOSE_PAREN":
                self.take()
                return ("call", name, args)
            while True:
                args.append(self.or_())
                nxt = self.take()
                if nxt.type == "CLOSE_PAREN":
                    return ("call", name, args)
                if nxt.type != "COMMA":
                    raise ParseError("bad function arguments")
        if tok.type == "SELF_REF":
            return ("self",)
        if tok.type in ("NAME", "PARENT_REF", "PATH_SEP", "DATE", "DATETIME", "TIME"):
            return ("raw", tok.value)
        raise ParseError(f"unexpected {tok.value!r}")


_CMP = {
    "=": "{l} is {r}",
    "!=": "{l} is not {r}",
    ">": "{l} is more than {r}",
    ">=": "{l} is {r} or more",
    "<": "{l} is less than {r}",
    "<=": "{l} is {r} or less",
}
_NEGATE = {"=": "!=", "!=": "=", ">": "<=", ">=": "<", "<": ">=", "<=": ">"}
_MATH = {"+": "plus", "-": "minus", "*": "times", "div": "divided by", "mod": "modulo"}


class _Renderer:
    def __init__(self, lookup: Lookup | None, self_name: str | None):
        self.lookup = lookup or (lambda _n: None)
        self.self_name = self_name

    def choice_label(self, ref_node, code: str) -> str:
        if ref_node and ref_node[0] == "ref":
            info = self.lookup(ref_node[1])
            if info and code in info[1]:
                return f'"{info[1][code]}"'
        return f'"{code}"'

    def r(self, n, top: bool = False) -> str:
        kind = n[0]
        if kind == "ref":
            return n[1]
        if kind == "self":
            return self.self_name or "this answer"
        if kind == "num":
            return n[1]
        if kind == "str":
            return f'"{n[1]}"'
        if kind == "raw":
            return n[1]
        if kind == "paren":
            inner = self.r(n[1])
            return inner if top or n[1][0] not in ("and", "or") else f"({inner})"
        if kind == "neg":
            return f"minus {self.r(n[1])}"
        if kind in ("and", "or"):
            parts = []
            for item in n[1]:
                s = self.r(item)
                if item[0] in ("and", "or") or (item[0] == "paren" and item[1][0] in ("and", "or")):
                    s = f"({s})" if not s.startswith("(") else s
                parts.append(s)
            return f" {kind} ".join(parts)
        if kind == "math":
            return f"{self.r(n[2])} {_MATH.get(n[1], n[1])} {self.r(n[3])}"
        if kind == "cmp":
            return self.cmp(n[1], n[2], n[3])
        if kind == "call":
            return self.call(n[1], n[2])
        raise ParseError(kind)

    def cmp(self, op: str, left, right) -> str:
        if right[0] == "str" and right[1] == "":
            if op == "=":
                return f"{self.r(left)} is not answered"
            if op == "!=":
                return f"{self.r(left)} is answered"
        if left[0] == "str" and right[0] in ("ref", "self"):
            left, right = right, left
        r_text = self.choice_label(left, right[1]) if right[0] in ("str", "num") and left[0] == "ref" and self._is_select(left) else self.r(right)
        return _CMP.get(op, "{l} " + op + " {r}").format(l=self.r(left), r=r_text)

    def _is_select(self, ref_node) -> bool:
        info = self.lookup(ref_node[1])
        return bool(info and info[0].startswith("select"))

    def call(self, name: str, args: list) -> str:
        if name == "selected" and len(args) == 2:
            target, value = args
            code = value[1] if value[0] in ("str", "num") else None
            label = self.choice_label(target, code) if code is not None else self.r(value)
            info = self.lookup(target[1]) if target[0] == "ref" else None
            verb = "is" if info and info[0] == "select_one" else "includes"
            return f"{self.r(target)} {verb} {label}"
        if name == "not" and len(args) == 1:
            inner = args[0]
            while inner[0] == "paren":
                inner = inner[1]
            if inner[0] == "call" and inner[1] == "selected" and len(inner[2]) == 2:
                text = self.call("selected", inner[2])
                return text.replace(" includes ", " does not include ", 1).replace(" is ", " is not ", 1)
            if inner[0] == "cmp":
                return self.cmp(_NEGATE.get(inner[1], inner[1]), inner[2], inner[3])
            return f"not ({self.r(inner, top=True)})"
        if name == "count-selected" and len(args) == 1:
            return f"the number of options chosen in {self.r(args[0])}"
        if name == "string-length" and len(args) == 1:
            return f"the length of {self.r(args[0])}"
        if name in ("today", "now") and not args:
            return name
        if name in ("true", "false") and not args:
            return name
        if name == "if" and len(args) == 3:
            return f"{self.r(args[1])} if {self.r(args[0])}, otherwise {self.r(args[2])}"
        if name in ("int", "number", "string", "coalesce", "round") and args:
            return ", ".join(self.r(a) for a in args) if len(args) == 1 else f"{name}({', '.join(self.r(a) for a in args)})"
        return f"{name}({', '.join(self.r(a) for a in args)})"


def explain(expr: str | None, lookup: Lookup | None = None, self_name: str | None = None) -> str:
    """Render an expression in plain English, or '' if empty. Falls back to the raw text."""
    if not expr or not expr.strip():
        return ""
    try:
        tree = _Parser(_tokens(expr.strip())).parse()
        return _Renderer(lookup, self_name).r(tree, top=True)
    except (ParseError, IndexError, TypeError):
        return expr.strip()


def explain_relevant(expr: str | None, lookup: Lookup | None = None) -> str:
    text = explain(expr, lookup)
    if not text:
        return ""
    if text == (expr or "").strip():
        return f"Only if: {text}"
    return f"Only if {text}"
