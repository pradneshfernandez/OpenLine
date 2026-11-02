from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.checks.rules import BLOCKER, CHECKS, DEFAULT_THRESHOLDS, INFO, WARNING, Context, Issue, estimate_minutes

READY, READY_WITH_WARNINGS, NOT_READY = "ready", "ready_with_warnings", "not_ready"


@dataclass
class CheckResult:
    status: str
    issues: list[Issue]
    counts: dict[str, int]
    estimated_minutes: float
    thresholds: dict[str, Any]


def merged_thresholds(overrides: dict | None) -> dict[str, Any]:
    out = dict(DEFAULT_THRESHOLDS)
    for k, v in (overrides or {}).items():
        if k in out and v is not None:
            out[k] = v
    return out


def run_checks(questions, choice_lists, languages, default_language, thresholds=None) -> CheckResult:
    th = merged_thresholds(thresholds)
    ctx = Context(questions=list(questions), choice_lists=choice_lists, languages=languages,
                  default_language=default_language, thresholds=th)
    issues: list[Issue] = []
    for code, (_title, fn) in CHECKS.items():
        if code in th["disabled_checks"]:
            continue
        issues.extend(fn(ctx))
    counts = {s: sum(1 for i in issues if i.severity == s) for s in (BLOCKER, WARNING, INFO)}
    return CheckResult(status_for(issues), issues, counts, estimate_minutes(ctx), th)


def status_for(issues, accepted: set[tuple[str | None, str]] | None = None) -> str:
    """Ready / Ready with warnings / Not ready, ignoring issues accepted with a reason."""
    accepted = accepted or set()
    open_ = [i for i in issues if (i.question_name, i.check_code) not in accepted]
    if any(i.severity == BLOCKER for i in open_):
        return NOT_READY
    if any(i.severity == WARNING for i in open_):
        return READY_WITH_WARNINGS
    return READY
