"""Supervisor review of interview answers (brief §5.9).

Flagged answers are queued for review; a reviewer approves, rejects (with a reason) or edits
(with a reason). The raw answer is never overwritten: an edit is stored in `reviewed_value` and
exports use `effective_answers()`. Every action is written to ReviewLog.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Answer, Form, FormVersion, Interview, ReviewLog
from app.voice.config import voice_settings

router = APIRouter(prefix="/api")

REVIEWABLE = {"completed", "partial", "callback", "refused"}  # interviews with answers to review


def _user(x_user: str | None) -> str:
    return (x_user or "").strip() or "anonymous"


def flat_key(a: Answer) -> str:
    return a.question_name + "".join(f"[{i + 1}]" for i in a.repeat_index)


def answer_flags(a: Answer) -> list[str]:
    """Flags that send an answer to the review queue."""
    flags = []
    if a.confidence is not None and a.confidence < voice_settings().confirm_below_confidence:
        flags.append("low_confidence")
    if a.code == "unclear":  # no valid answer after repeated tries (voice/flow.py)
        flags.append("unclear")
    elif a.flagged:
        flags.append("mismatch")
    if a.attempts > 2:
        flags.append("attempts")
    if a.corrected:
        flags.append("corrected")
    return flags


def needs_review(a: Answer) -> bool:
    return a.still_relevant and bool(answer_flags(a))


def effective_answers(i: Interview) -> dict:
    """final_answers with reviewer edits applied and rejected answers blanked."""
    out = dict(i.final_answers or {})
    for a in i.answers:
        key = flat_key(a)
        if key not in out:
            continue
        if a.review_state == "edited":
            out[key] = a.reviewed_value
        elif a.review_state == "rejected":
            out[key] = None
    return out


def ser_review_answer(a: Answer, labels: dict) -> dict:
    return {
        "id": a.id, "question_name": a.question_name, "key": flat_key(a), "repeat_index": a.repeat_index,
        "value": a.value, "code": a.code, "heard_text": a.heard_text, "confidence": a.confidence,
        "attempts": a.attempts, "corrected": a.corrected, "confirmed": a.confirmed, "flagged": a.flagged,
        "second_pass_text": a.second_pass_text, "second_pass_value": a.second_pass_value,
        "t_question": a.t_question, "t_answer_start": a.t_answer_start, "t_answer_end": a.t_answer_end,
        "flags": answer_flags(a), "review_state": a.review_state, "reviewed_value": a.reviewed_value,
        "review_reason": a.review_reason, "labels": labels,
    }


def ser_log(e: ReviewLog) -> dict:
    return {"id": e.id, "interview_id": e.interview_id, "answer_id": e.answer_id, "action": e.action,
            "subject": e.subject, "old_value": e.old_value, "new_value": e.new_value, "reason": e.reason,
            "user": e.user, "time": e.time.isoformat()}


def _interviews(db: Session, project_id: int, form_id: int | None = None):
    q = (select(Interview).join(FormVersion).join(Form)
         .where(Form.project_id == project_id, Interview.status.in_(REVIEWABLE))
         .order_by(Interview.id.desc()))
    if form_id:
        q = q.where(Form.id == form_id)
    return list(db.scalars(q))


@router.get("/projects/{project_id}/review")
def review_queue(project_id: int, state: str = "pending", flag: str | None = None, question: str | None = None,
                 language: str | None = None, interview_id: int | None = None, form_id: int | None = None,
                 db: Session = Depends(get_session)):
    """Flagged answers grouped by interview, with counts per review state for the tabs."""
    counts = {"pending": 0, "approved": 0, "rejected": 0, "edited": 0}
    groups, questions, forms = [], set(), {}
    for i in _interviews(db, project_id, form_id):
        forms[i.form_version.form.id] = i.form_version.form.title
        labels = {q.name: q.labels for q in i.form_version.questions}
        flagged = [a for a in i.answers if needs_review(a)]
        for a in flagged:
            counts[a.review_state] = counts.get(a.review_state, 0) + 1
            questions.add(a.question_name)
        if language and i.language != language or interview_id and i.id != interview_id:
            continue
        rows = [a for a in flagged if a.review_state == state
                and (not flag or flag in answer_flags(a)) and (not question or a.question_name == question)]
        if rows:
            groups.append({
                "interview": {"id": i.id, "participant_label": i.participant_label, "language": i.language,
                              "version_no": i.form_version.version_no, "form_id": i.form_version.form.id,
                              "form_title": i.form_version.form.title, "has_recording": bool(i.recording_file),
                              "started_at": (i.started_at or i.created_at).isoformat(), "status": i.status,
                              "review_state": i.review_state,
                              "pending": sum(1 for a in flagged if a.review_state == "pending")},
                "answers": [ser_review_answer(a, labels.get(a.question_name, {})) for a in rows],
            })
    return {"counts": counts, "groups": groups, "questions": sorted(questions),
            "forms": [{"id": k, "title": v} for k, v in forms.items()]}


@router.get("/projects/{project_id}/review/count")
def review_count(project_id: int, db: Session = Depends(get_session)):
    return {"pending": sum(1 for i in _interviews(db, project_id) for a in i.answers
                           if needs_review(a) and a.review_state == "pending")}


class AnswerReviewIn(BaseModel):
    action: Literal["approve", "reject", "edit", "reset"]
    value: str | None = None
    reason: str = ""


@router.post("/answers/{answer_id}/review")
def review_answer(answer_id: int, body: AnswerReviewIn, db: Session = Depends(get_session),
                  x_user: str | None = Header(None)):
    a = db.get(Answer, answer_id)
    if a is None:
        raise HTTPException(404)
    reason = body.reason.strip()
    if body.action in ("reject", "edit") and not reason:
        raise HTTPException(422, "A reason is required to reject or edit an answer")
    if body.action == "edit" and (body.value is None or not body.value.strip()):
        raise HTTPException(422, "Enter the reviewed value")
    shown = a.reviewed_value if a.review_state == "edited" else (a.code or a.value)
    if body.action == "approve":
        a.review_state, a.reviewed_value, a.review_reason = "approved", None, reason
    elif body.action == "reject":
        a.review_state, a.reviewed_value, a.review_reason = "rejected", None, reason
    elif body.action == "edit":
        a.review_state, a.reviewed_value, a.review_reason = "edited", body.value.strip(), reason
    else:
        a.review_state, a.reviewed_value, a.review_reason = "pending", None, ""
    action = {"approve": "approved", "reject": "rejected", "edit": "edited", "reset": "reopened"}[body.action]
    db.add(ReviewLog(interview_id=a.interview_id, answer_id=a.id, action=action, subject=flat_key(a),
                     old_value=shown, new_value=a.reviewed_value if body.action == "edit" else None,
                     reason=reason, user=_user(x_user)))
    db.commit()
    return ser_review_answer(a, {})


class InterviewReviewIn(BaseModel):
    action: Literal["approve", "reject", "reset"]
    reason: str = ""


@router.post("/interviews/{interview_id}/review")
def review_interview(interview_id: int, body: InterviewReviewIn, db: Session = Depends(get_session),
                     x_user: str | None = Header(None)):
    """Approve a whole interview: every still-pending answer is approved with it."""
    i = db.get(Interview, interview_id)
    if i is None:
        raise HTTPException(404)
    if body.action == "reject" and not body.reason.strip():
        raise HTTPException(422, "A reason is required to reject an interview")
    approved = 0
    if body.action == "approve":
        for a in i.answers:
            if a.still_relevant and a.review_state == "pending":
                a.review_state = "approved"
                approved += 1
    i.review_state = {"approve": "approved", "reject": "rejected", "reset": "pending"}[body.action]
    i.review_reason = body.reason.strip()
    db.add(ReviewLog(interview_id=i.id, action=f"interview_{i.review_state}", subject="interview",
                     new_value=f"{approved} answers approved" if body.action == "approve" else None,
                     reason=body.reason.strip(), user=_user(x_user)))
    db.commit()
    return {"id": i.id, "review_state": i.review_state, "approved_answers": approved}


@router.get("/projects/{project_id}/review/log")
def review_log(project_id: int, limit: int = 50, db: Session = Depends(get_session)):
    rows = db.scalars(select(ReviewLog).join(Interview).join(FormVersion).join(Form)
                      .where(Form.project_id == project_id).order_by(ReviewLog.id.desc()).limit(limit))
    return [ser_log(e) for e in rows]


def parse_index(key: str) -> tuple[str, list[int]]:
    """'child_age[2]' -> ('child_age', [1])."""
    return key.split("[")[0], [int(n) - 1 for n in re.findall(r"\[(\d+)\]", key)]
