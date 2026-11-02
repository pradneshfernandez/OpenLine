"""Pipecat Flows nodes for a survey: one node per question, created at runtime.

The form runner decides what comes next; the LLM only turns speech into a candidate value for
the current question via that node's tools. Question text is spoken verbatim with `tts_say`
(the LLM never paraphrases the question), and nodes don't run the LLM on entry.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from pipecat.flows import ContextStrategy, ContextStrategyConfig, FlowManager, FlowsFunctionSchema, NodeConfig

from app.voice.config import voice_settings
from app.voice.i18n import LANGUAGE_NAMES, lang_code, phrase
from app.voice.runner import ANOTHER, DK, REFUSED, UNCLEAR, Item
from app.voice.session import InterviewSession

AFFIRMATIVE = {"yes", "1", "agree", "true"}
MAX_SPOKEN_OPTIONS = 6
MAX_INVALID = 3  # invalid answers to one question before it's recorded as 'unclear' (§5.7)

SpeedSetter = Callable[[float], Awaitable[None]]


def number_mismatch(item: Item, value: Any, heard: str) -> Any | None:
    """For number questions: the value to confirm when the transcript's digits don't include it.

    Prisma writes numbers as digits ("char nahi paanch" -> "4 nahi 5"), so a value the LLM gives
    that appears nowhere among those digits needs the respondent's confirmation.
    """
    if item.type not in ("integer", "decimal") or value is None:
        return None
    digits = re.findall(r"\d+(?:\.\d+)?", (heard or "").replace(",", ""))
    if not digits:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if any(abs(float(d) - v) < 1e-9 for d in digits):
        return None
    return int(v) if v.is_integer() else v


def _escape(text: str) -> str:
    """Flows renders {{ key }} placeholders in spoken text; form text must not be rendered."""
    return text.replace("{{", "\\{{")


class SurveyFlow:
    def __init__(self, session: InterviewSession, study_name: str, set_speed: SpeedSetter):
        self.s = session
        self.runner = session.runner
        self.lang = lang_code(session.lang)
        self.study_name = study_name
        self.set_speed = set_speed
        self.cfg = voice_settings()
        self.opened = False
        self.consent_name: str | None = None
        self.idle_count = 0  # silences in a row on the current question
        self.invalid: dict[tuple, int] = {}  # invalid answers per question

    # ------------------------------------------------------------------ prompts

    def role_message(self) -> str:
        language = LANGUAGE_NAMES[self.lang]
        return (
            f"You are a polite telephone survey interviewer for {self.study_name}. Speak only "
            f"{language}. Ask exactly the question you are given, in your own natural words only if "
            "needed for clarity, never changing its meaning. Never skip, add or answer questions "
            "yourself. Never read text marked for the interviewer. When the respondent answers, call "
            "`record_answer`. Keep every turn short. The question text is read to the respondent by "
            "the system; do not read the next question yourself."
        )

    def options_for_llm(self, item: Item) -> list[dict]:
        return [o for o in item.options if not self.runner.is_dk_code(o["name"])]

    def spoken(self, item: Item, prefix: str = "") -> str:
        parts = [prefix] if prefix else []
        rep = item.repeat
        if item.first_in_instance and rep and item.name != ANOTHER and (rep.get("count") or 0) != 1:
            parts.append(phrase(self.lang, "next_instance", label=rep["label"], n=rep["index"] + 1))
        parts.append(item.text)
        opts = self.options_for_llm(item)
        if item.type in ("select_one", "select_multiple") and 3 <= len(opts) <= MAX_SPOKEN_OPTIONS:
            labels = [o["label"] for o in opts]
            parts.append(", ".join(labels[:-1]) + f" {phrase(self.lang, 'or')} {labels[-1]}?")
        return " ".join(p.strip() for p in parts if p and p.strip())

    def answers_so_far(self) -> str:
        """One line the LLM needs for corrections: earlier answers, by variable name."""
        done = []
        for (name, index), stored in self.runner.answers.items():
            if name == ANOTHER:
                continue
            key = name + "".join(f"[{i + 1}]" for i in index)
            value = stored.code or (" ".join(stored.value) if isinstance(stored.value, list) else stored.value)
            done.append(f"{key}={value}")
        return ", ".join(done[-15:])

    def prompt_for(self, item: Item) -> str:
        lines = [f'Current question "{item.name}" (type {item.type}) has just been read to the '
                 f'respondent: "{item.text}"', "Wait for the answer."]
        if (so_far := self.answers_so_far()):
            lines.append(f"Answers so far: {so_far}.")
        opts = self.options_for_llm(item)
        if opts:
            lines.append("Options (code = label): " + "; ".join(f"{o['name']} = {o['label']}" for o in opts))
            lines.append(
                "Map the answer to exactly one option code. If you are not sure (confidence below "
                f"{self.cfg.confirm_below_confidence}), ask the respondent to confirm, then call "
                "record_answer with confirmed=true.")
        if item.type == "integer":
            lines.append("The answer is a whole number. Use the digits the respondent said; convert "
                         "number words (in any language) to digits.")
        elif item.type == "decimal":
            lines.append("The answer is a number.")
        elif item.type == "text":
            lines.append("Record what the respondent said, in their words. Do not paraphrase or translate.")
        if item.constraint_message:
            lines.append(f"Allowed answers: {item.constraint_message}")
        lines.append(
            "If the respondent asks to hear the question again call repeat_question; asks you to "
            "speak slower call slow_down; says they don't know or don't want to answer call "
            "dont_know_or_refuse; wants to change an earlier answer call correct_answer; asks to be "
            "called later call call_back_later. If they ask what the question means, explain it "
            "briefly without changing its meaning. If a tool returns status 'invalid' or "
            "'confirm', say its 'say' text and wait for the answer.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ nodes

    def waiting_node(self) -> NodeConfig:
        return {
            "name": "waiting",
            "role_message": self.role_message(),
            "task_messages": [{"role": "developer", "content":
                               "The call has just connected. Do not say anything and do not reply."}],
            "functions": [],
            "respond_immediately": False,
        }

    def opening_node(self) -> NodeConfig:
        first = self.runner.start(self.s.lang)
        greeting = phrase(self.lang, "greeting", org=self.cfg.survey_org, study=self.study_name)
        if self.s.resumed_answers:
            greeting = f"{greeting} {phrase(self.lang, 'resume')}"
        if first is None:
            return self.end_node("completed", greeting)
        prefix, first = self._collect_notes(first, greeting)
        if first is None:
            return self.end_node("completed", prefix)
        if "consent" in first.name.lower():
            self.consent_name = first.name
        return self.question_node(first, prefix, name="opening")

    def question_node(self, item: Item, prefix: str = "", name: str | None = None) -> NodeConfig:
        text = self.spoken(item, prefix)
        # The consent statement is read in full: the respondent can't interrupt it.
        protect = name == "opening" and item.name == self.consent_name

        async def mark(action: dict, flow_manager: FlowManager) -> None:
            if self.s.node_name != item.name:
                self.idle_count = 0
            self.s.node_name = item.name
            self.s.mark_question(item)
            self.s.asking(item, protect=protect)

        return {
            "name": name or f"q:{item.name}{list(item.index) if item.index else ''}",
            # Each question starts from a fresh context (role + this question + a one-line summary of
            # answers so far), so prompts stay small and fast however long the form is.
            "role_message": self.role_message(),
            "context_strategy": ContextStrategyConfig(strategy=ContextStrategy.RESET),
            "task_messages": [{"role": "developer", "content": self.prompt_for(item)}],
            "functions": self.functions(item),
            "pre_actions": [{"type": "function", "handler": mark},
                            {"type": "tts_say", "text": _escape(text)}],
            "respond_immediately": False,
        }

    def end_node(self, status: str, prefix: str = "", when: str = "") -> NodeConfig:
        goodbye = {"completed": "goodbye", "refused": "refused_goodbye",
                   "callback": "callback_goodbye", "partial": "no_response_goodbye"}[status]

        async def finish(action: dict, flow_manager: FlowManager) -> None:
            self.s.node_name = "end"
            self.s.asking(None, protect=True)  # let the goodbye finish
            extra = {"callback_when": when} if when else {}
            if extra:
                self.s.set_status(status, **extra)
            self.s.finish(status)

        text = " ".join(t for t in (prefix, phrase(self.lang, goodbye)) if t)
        return {
            "name": "end",
            "task_messages": [{"role": "developer", "content": "The interview is over. Say nothing."}],
            "functions": [],
            "pre_actions": [{"type": "function", "handler": finish},
                            {"type": "end_conversation", "text": _escape(text)}],
            "respond_immediately": False,
        }

    def _collect_notes(self, item: Item | None, prefix: str = "") -> tuple[str, Item | None]:
        """Notes are spoken and need no answer: fold them into the next question's speech."""
        parts = [prefix] if prefix else []
        while item is not None and item.is_note:
            if item.text:
                parts.append(item.text)
            item = self.runner.next()
        return " ".join(parts), item

    def advance(self, prefix: str = "") -> NodeConfig:
        prefix, item = self._collect_notes(self.runner.next(), prefix)
        if item is None:
            return self.end_node("completed", prefix)
        return self.question_node(item, prefix)

    # ------------------------------------------------------------------ tools

    def value_schema(self, item: Item) -> dict[str, Any]:
        if item.name == ANOTHER:
            return {"type": "string", "enum": ["yes", "no"]}
        codes = [o["name"] for o in self.options_for_llm(item)]
        if item.type == "select_one":
            return {"type": "string", "enum": codes, "description": "Option code"}
        if item.type == "select_multiple":
            return {"type": "array", "items": {"type": "string", "enum": codes}}
        if item.type == "integer":
            return {"type": "integer"}
        if item.type == "decimal":
            return {"type": "number"}
        return {"type": "string"}

    def functions(self, item: Item) -> list[FlowsFunctionSchema]:
        fns = [
            FlowsFunctionSchema(
                name="record_answer",
                description="Record the respondent's answer to the current question.",
                properties={
                    "value": self.value_schema(item),
                    "heard_text": {"type": "string", "description": "What the respondent said, word for word"},
                    "confidence": {"type": "number", "description": "0 to 1: how sure you are of the value"},
                    "confirmed": {"type": "boolean", "description": "True if the respondent confirmed this value"},
                },
                required=["value", "heard_text", "confidence"],
                handler=self.handle_record_answer,
            ),
            FlowsFunctionSchema(
                name="repeat_question", description="Say the current question again.",
                properties={}, required=[], handler=self.handle_repeat),
            FlowsFunctionSchema(
                name="slow_down", description="Speak more slowly for the rest of the call.",
                properties={}, required=[], handler=self.handle_slow_down),
            FlowsFunctionSchema(
                name="dont_know_or_refuse",
                description="The respondent doesn't know the answer, or doesn't want to answer.",
                properties={"kind": {"type": "string", "enum": [DK, REFUSED]},
                            "heard_text": {"type": "string"}},
                required=["kind"], handler=self.handle_dk_refuse),
            FlowsFunctionSchema(
                name="call_back_later",
                description="The respondent asks to be called back at another time.",
                properties={"when": {"type": "string", "description": "When to call back, as said"}},
                required=[], handler=self.handle_call_back),
        ]
        answered = [n for n in self.runner.answered_names() if n != item.name]
        if answered:
            fns.insert(1, FlowsFunctionSchema(
                name="correct_answer",
                description="The respondent wants to change their answer to an earlier question.",
                properties={"question_name": {"type": "string", "enum": answered},
                            "value": {"type": "string", "description": "The new answer (option code or value)"},
                            "heard_text": {"type": "string"}},
                required=["question_name", "value"], handler=self.handle_correct))
        return fns

    async def handle_record_answer(self, args: dict, flow_manager: FlowManager):
        item = self.runner.current()
        if item is None:
            return {"status": "error", "error": "no current question"}, None
        self.s.count_attempt(item)
        value = args.get("value")
        confidence = args.get("confidence")
        confirmed = bool(args.get("confirmed"))
        heard = args.get("heard_text") or ""
        if (item.type == "select_one" and not confirmed and confidence is not None
                and confidence < self.cfg.confirm_below_confidence):
            label = next((o["label"] for o in item.options if o["name"] == value), value)
            return {"status": "confirm", "say": f"{label}?"}, None
        if not confirmed and (check := number_mismatch(item, value, heard)) is not None:
            # The digits the speech model heard disagree with the LLM's number: ask, don't guess.
            return {"status": "confirm", "say": f"{check}?"}, None
        res = self.runner.answer(item.name, value)
        if not res.ok:
            logger.info(f"{item.name}: invalid answer {value!r}: {res.message}")
            self.invalid[item.key] = self.invalid.get(item.key, 0) + 1
            if self.invalid[item.key] >= MAX_INVALID and item.name != self.consent_name:
                # Don't loop forever: record "unclear", flag it for review and move on.
                self.runner.code(item.name, UNCLEAR)
                self.s.save_answer(item, code=UNCLEAR, heard_text=heard, confidence=confidence, flagged=True)
                return {"status": "ok"}, self.advance(phrase(self.lang, "move_on"))
            return {"status": "invalid", "say": res.message}, None
        self.s.save_answer(item, value=res.value, heard_text=heard, confidence=confidence, confirmed=confirmed)
        if item.name == self.consent_name and str(res.value).lower() not in AFFIRMATIVE:
            return {"status": "ok"}, self.end_node("refused")
        return {"status": "ok"}, self.advance()

    async def handle_correct(self, args: dict, flow_manager: FlowManager):
        name = args["question_name"]
        target = self.runner.back(name)
        if target is None:
            return {"status": "error", "error": f"{name} has not been answered"}, None
        self.s.count_attempt(target)
        res = self.runner.answer(name, args.get("value"))
        if not res.ok:
            return {"status": "invalid", "say": res.message}, self.question_node(target)
        self.s.save_answer(target, value=res.value, heard_text=args.get("heard_text", ""), corrected=True)
        if name == self.consent_name and str(res.value).lower() not in AFFIRMATIVE:
            return {"status": "ok"}, self.end_node("refused")
        return {"status": "ok", "corrected": name}, self.advance()

    async def handle_repeat(self, args: dict, flow_manager: FlowManager):
        item = self.runner.current()
        return {"status": "ok"}, self.question_node(item) if item else None

    async def handle_slow_down(self, args: dict, flow_manager: FlowManager):
        await self.set_speed(0.85)
        item = self.runner.current()
        return {"status": "ok"}, self.question_node(item) if item else None

    async def handle_dk_refuse(self, args: dict, flow_manager: FlowManager):
        item = self.runner.current()
        if item is None:
            return {"status": "error"}, None
        kind = args.get("kind", DK)
        self.runner.code(item.name, kind)
        self.s.save_answer(item, code=kind, heard_text=args.get("heard_text", ""))
        if item.name == self.consent_name:
            return {"status": "ok"}, self.end_node("refused")
        return {"status": "ok"}, self.advance()

    def on_idle(self) -> NodeConfig | None:
        """The respondent said nothing after the question: ask again, then give up politely."""
        item = self.runner.current()
        if not self.opened or item is None or self.s.node_name == "end":
            return None
        self.idle_count += 1
        if self.idle_count > self.cfg.idle_reprompts:
            return self.end_node("partial")
        return self.question_node(item, phrase(self.lang, "still_there"))

    async def handle_call_back(self, args: dict, flow_manager: FlowManager):
        return {"status": "ok"}, self.end_node("callback", when=args.get("when", ""))

    # ------------------------------------------------------------------ opening

    async def open(self, flow_manager: FlowManager) -> None:
        """Leave the waiting node: greet, then read the consent / first question."""
        if self.opened:
            return
        self.opened = True
        await flow_manager.set_node_from_config(self.opening_node())

    async def open_after_wait(self, flow_manager: FlowManager) -> None:
        """Wait up to hello_wait_secs for the respondent to say hello, then open anyway."""
        await asyncio.sleep(self.cfg.hello_wait_secs)
        await self.open(flow_manager)
