"""Stage 1 data model. FormVersion rows (and their questions/choices) are never updated
after creation; edits always create a new version."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    owner: Mapped[str] = mapped_column(String(200), default="")
    # Phone-check thresholds; merged over app.checks.rules.DEFAULT_THRESHOLDS.
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # Agent voice per call language: {"en": {"voice": "Nalini", "speed": 1.0}, "hi": {...}}.
    voices: Mapped[dict] = mapped_column(JSON, default=dict)
    # KoboToolbox connection: {"server_url", "token", "asset_uid", "asset_name"}. The token is
    # never sent back to the browser.
    kobo: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    forms: Mapped[list["Form"]] = relationship(back_populates="project")


class Form(Base):
    __tablename__ = "form"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    title: Mapped[str] = mapped_column(String(500), default="")
    form_id: Mapped[str] = mapped_column(String(200), default="")
    default_language: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="forms")
    versions: Mapped[list["FormVersion"]] = relationship(
        back_populates="form", order_by="FormVersion.version_no", cascade="all, delete-orphan"
    )


class FormVersion(Base):
    __tablename__ = "form_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("form.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[int | None] = mapped_column(
        ForeignKey("form_version.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    message: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(500), default="")
    original_file: Mapped[str] = mapped_column(String(500))
    xlsx_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    xform_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    pyxform_warnings: Mapped[list] = mapped_column(JSON, default=list)
    # Our own analysis of the upload: platform extras, languages, summary counts.
    platform_warnings: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    # Names of survey rows marked "not used by phone" (e.g. SurveyCTO-only rows).
    excluded_rows: Mapped[list] = mapped_column(JSON, default=list)

    form: Mapped[Form] = relationship(back_populates="versions")
    questions: Mapped[list["Question"]] = relationship(
        order_by="Question.position", cascade="all, delete-orphan"
    )
    choice_lists: Mapped[list["ChoiceList"]] = relationship(cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "question"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("form_version.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(200))
    raw_type: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(30))
    group_path: Mapped[list] = mapped_column(JSON, default=list)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    hints: Mapped[dict] = mapped_column(JSON, default=dict)
    choice_list: Mapped[str | None] = mapped_column(String(200), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    required_raw: Mapped[str] = mapped_column(String(500), default="")
    constraint: Mapped[str] = mapped_column(Text, default="")
    constraint_message: Mapped[dict] = mapped_column(JSON, default=dict)
    relevant: Mapped[str] = mapped_column(Text, default="")
    relevant_plain: Mapped[str] = mapped_column(Text, default="")
    calculation: Mapped[str] = mapped_column(Text, default="")
    repeat_count: Mapped[str] = mapped_column(String(500), default="")
    default: Mapped[str] = mapped_column(String(500), default="")
    appearance: Mapped[str] = mapped_column(String(500), default="")
    media: Mapped[dict] = mapped_column(JSON, default=dict)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    read_aloud: Mapped[bool] = mapped_column(Boolean, default=True)
    hint_read_aloud: Mapped[bool] = mapped_column(Boolean, default=False)
    not_used_by_phone: Mapped[bool] = mapped_column(Boolean, default=False)


class ChoiceList(Base):
    __tablename__ = "choice_list"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("form_version.id", ondelete="CASCADE"))
    list_name: Mapped[str] = mapped_column(String(200))
    choices: Mapped[list] = mapped_column(JSON, default=list)


class PhoneCheckReport(Base):
    __tablename__ = "phone_check_report"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("form_version.id", ondelete="CASCADE"))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(30))
    blocker_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    info_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_minutes: Mapped[float] = mapped_column(Float, default=0)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)

    issues: Mapped[list["PhoneIssue"]] = relationship(
        order_by="PhoneIssue.id", cascade="all, delete-orphan"
    )


class PhoneIssue(Base):
    __tablename__ = "phone_issue"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("phone_check_report.id", ondelete="CASCADE")
    )
    question_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    check_code: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="open")
    accepted_reason: Mapped[str] = mapped_column(Text, default="")


class EditLog(Base):
    __tablename__ = "edit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("form_version.id", ondelete="CASCADE"))
    question_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field: Mapped[str] = mapped_column(String(200))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    user: Mapped[str] = mapped_column(String(200), default="")
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Stage 2: phone interviews


class Interview(Base):
    __tablename__ = "interview"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_version.id", ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(20))
    participant_label: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(20), default="phone")  # phone | browser
    call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # queued / ringing / in-progress / completed / partial / refused / callback /
    # no-answer / busy / failed
    status: Mapped[str] = mapped_column(String(30), default="queued")
    twilio_status: Mapped[str] = mapped_column(String(30), default="")
    callback_when: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recording_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_answers: Mapped[dict] = mapped_column(JSON, default=dict)  # runner.finish()
    error: Mapped[str] = mapped_column(Text, default="")
    # Full-call transcript (Prisma Batch, voice/transcript.py): none / running / done / failed.
    transcript_state: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    transcript: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")  # [{start, end, speaker, text, language}]
    transcript_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Set when this call continued an earlier partial call to the same respondent.
    resumed_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("interview.id", ondelete="SET NULL"), nullable=True)
    campaign_respondent_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaign_respondent.id", ondelete="SET NULL"), nullable=True)
    simulation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_run.id", ondelete="CASCADE"), nullable=True)
    persona: Mapped[str] = mapped_column(String(30), default="")  # simulated respondents only
    answer_key: Mapped[dict] = mapped_column(JSON, default=dict)  # simulated respondents only
    # Review of the whole interview: pending / approved / rejected.
    review_state: Mapped[str] = mapped_column(String(20), default="pending")
    review_reason: Mapped[str] = mapped_column(Text, default="")
    # KoboToolbox export: not_sent / sent / failed.
    kobo_state: Mapped[str] = mapped_column(String(20), default="not_sent")
    kobo_error: Mapped[str] = mapped_column(Text, default="")
    kobo_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    form_version: Mapped[FormVersion] = relationship()
    campaign_respondent: Mapped["CampaignRespondent | None"] = relationship(
        foreign_keys=[campaign_respondent_id], viewonly=True)
    answers: Mapped[list["Answer"]] = relationship(order_by="Answer.id", cascade="all, delete-orphan")
    turns: Mapped[list["TurnLog"]] = relationship(order_by="TurnLog.id", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answer"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview.id", ondelete="CASCADE"))
    question_name: Mapped[str] = mapped_column(String(200))
    repeat_index: Mapped[list] = mapped_column(JSON, default=list)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)  # dk / refused
    heard_text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    still_relevant: Mapped[bool] = mapped_column(Boolean, default=True)
    # Seconds from the start of the recording, so the answer clip can be cut later.
    t_question: Mapped[float | None] = mapped_column(Float, nullable=True)
    t_answer_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    t_answer_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Second pass: the answer clip re-transcribed with the question as context.
    second_pass_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    second_pass_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    # Supervisor review. The raw value above is never overwritten; an edit lives in
    # reviewed_value. review_state: pending / approved / rejected / edited.
    review_state: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_reason: Mapped[str] = mapped_column(Text, default="")


class TurnLog(Base):
    __tablename__ = "turn_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview.id", ondelete="CASCADE"))
    t: Mapped[float] = mapped_column(Float)  # seconds from the start of the call
    speaker: Mapped[str] = mapped_column(String(20))  # agent / respondent / system
    text: Mapped[str] = mapped_column(Text, default="")
    node_name: Mapped[str] = mapped_column(String(200), default="")
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class ReviewLog(Base):
    """Every review action: approve / reject / edit an answer, approve an interview."""

    __tablename__ = "review_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview.id", ondelete="CASCADE"))
    answer_id: Mapped[int | None] = mapped_column(ForeignKey("answer.id", ondelete="CASCADE"), nullable=True)
    action: Mapped[str] = mapped_column(String(30))  # approved / rejected / edited / interview_approved
    subject: Mapped[str] = mapped_column(String(200), default="")  # question_name[n] or "interview"
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[str] = mapped_column(String(200), default="")
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Campaigns


class Campaign(Base):
    __tablename__ = "campaign"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    name: Mapped[str] = mapped_column(String(300))
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_version.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/running/paused/finished
    # calling_start / calling_end ("09:00"), max_attempts, min_gap_minutes, concurrency, timezone
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    csv_filename: Mapped[str] = mapped_column(String(500), default="")
    rejected_rows: Mapped[list] = mapped_column(JSON, default=list)  # [{row, respondent_id, problem}]
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    form_version: Mapped[FormVersion] = relationship()
    respondents: Mapped[list["CampaignRespondent"]] = relationship(
        order_by="CampaignRespondent.id", cascade="all, delete-orphan", back_populates="campaign")


class CampaignRespondent(Base):
    """One row of the respondent CSV. The phone number is stored because retries need it, but
    the API only ever returns it masked."""

    __tablename__ = "campaign_respondent"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    respondent_id: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(10))
    # waiting (to be called) / calling / done (completed or out of attempts) / stopped (refused,
    # opted out: never called again)
    state: Mapped[str] = mapped_column(String(20), default="waiting")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_outcome: Mapped[str] = mapped_column(String(30), default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    callback_when: Mapped[str] = mapped_column(String(200), default="")

    campaign: Mapped[Campaign] = relationship(back_populates="respondents")
    interviews: Mapped[list[Interview]] = relationship(
        order_by="Interview.id", foreign_keys="Interview.campaign_respondent_id")


# ---------------------------------------------------------------------------
# Simulated respondents


class SimulationRun(Base):
    __tablename__ = "simulation_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_version_id: Mapped[int] = mapped_column(ForeignKey("form_version.id", ondelete="CASCADE"))
    # runs, personas [cooperative, vague, correcting, mixed], languages [en, hi]
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued/running/finished/failed
    error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    form_version: Mapped[FormVersion] = relationship()
    interviews: Mapped[list[Interview]] = relationship(
        order_by="Interview.id", foreign_keys="Interview.simulation_run_id")
