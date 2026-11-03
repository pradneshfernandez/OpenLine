"""Turn-taking and interruption rules for a survey call (component deep dive §1–2).

- **End of turn**: Smart Turn v3.2 judges from the audio whether the answer sounds finished
  (trained on English and Hindi among others, not Tamil). Its `stop_secs` is the longest silence
  we wait when it isn't; that wait depends on the question: a yes/no answer is short, a number or
  an open answer often comes after a pause.
- **Unfinished words**: Smart Turn reads intonation, and a fragment said with a falling tone
  ("We are five people and.") sounds finished to it. Measured Nov 3 on Gnani TTS clips at 8 kHz:
  every complete answer was called complete, but only ~1 in 4 unfinished ones was caught. So a
  transcript that ends on a connecting word ("and", "the", "umm", "और", "लेकिन", a trailing
  comma) keeps the line open for the question's silence wait, whatever Smart Turn said.
- **Interruptions** need at least 2 words while the agent is speaking, so a backchannel
  ("haan", "hmm", "accha") doesn't stop it. When the agent is silent, one word is an answer.
- **Protected speech**: while the consent statement (and the goodbye) is read, the respondent's
  audio is muted so the statement is always heard in full. Muted speech is dropped, not queued.
"""

from __future__ import annotations

import asyncio
import re
import time

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, Frame
from pipecat.turns.user_mute.base_user_mute_strategy import BaseUserMuteStrategy
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from app.voice.runner import ANOTHER, Item

INTERRUPT_MIN_WORDS = 2

# Longest silence (seconds) before the turn ends anyway, when Smart Turn says "not finished".
WAIT_SHORT = 1.2   # yes / no, "another one?"
WAIT_CHOICE = 2.0  # pick one of a few options
WAIT_NUMBER = 2.8  # numbers: people pause to count or correct themselves
WAIT_OPEN = 3.5    # open text, multi-select lists


def silence_wait(item: Item | None) -> float:
    """How long to wait in silence, by what kind of answer the question expects."""
    if item is None:
        return WAIT_CHOICE
    if item.name == ANOTHER:
        return WAIT_SHORT
    if item.type == "select_one":
        return WAIT_SHORT if len(item.options) <= 3 else WAIT_CHOICE
    if item.type in ("integer", "decimal"):
        return WAIT_NUMBER
    if item.type in ("text", "select_multiple"):
        return WAIT_OPEN
    return WAIT_CHOICE


class ProtectedSpeechMute(BaseUserMuteStrategy):
    """Mutes the respondent while the agent reads protected speech (consent, goodbye)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.protect = False
        self._bot_speaking = False

    async def process_frame(self, frame: Frame) -> bool:
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self.protect = False  # protection covers one statement
        return self.protect and self._bot_speaking


class VerdictKeepingStopStrategy(TurnAnalyzerUserTurnStopStrategy):
    """Smart Turn stop strategy that survives a turn starting after the respondent stopped.

    Our start strategy is transcript-based (two words to interrupt), so the user turn often starts
    only when the final transcript lands, after VAD already reported the stop and Smart Turn gave its
    verdict. Pipecat resets both at turn start and then falls back to a fixed timer
    (STT p99 − VAD stop_secs = 0.8 s) that ignores Smart Turn. Keeping the verdict ends a finished
    answer as soon as the finalized transcript arrives, and keeps waiting when Smart Turn said the
    respondent wasn't done (a thinking pause).
    """

    async def handle_user_turn_started(self):
        if self._vad_stopped and not self._vad_user_speaking:
            self._text = ""  # the turn is the speech VAD just ended: keep its end-of-turn verdict
            return
        await super().handle_user_turn_started()


# Words an answer doesn't end on: the respondent is mid-sentence or thinking.
HANGING_WORDS = frozenset("""
and or but so because the a an of to in on at from with for my our is are was were um umm uh uhh
er hmm like about maybe then
aur ya lekin par toh ki ka ke mein se matlab yaani jaise
और या लेकिन पर तो कि की का के में से मतलब यानी जैसे
அப்புறம் ஆனா மற்றும் அதாவது அப்படின்னா
""".split())
_TRAILING = re.compile(r"(,|…|\.\.\.|-|–)\s*$")
_PUNCT = ".,!?;:…\"'()[]।|-–—"


def sounds_unfinished(text: str) -> bool:
    """True when a transcript stops mid-sentence: a trailing comma/ellipsis or a connecting word."""
    text = (text or "").strip()
    if not text:
        return False
    if _TRAILING.search(text):
        return True
    last = text.split()[-1].strip(_PUNCT).lower()
    return last in HANGING_WORDS


class TranscriptAwareStopStrategy(VerdictKeepingStopStrategy):
    """Keeps the line open when Smart Turn says "done" but the words say otherwise.

    If the final transcript ends on a connecting word, the turn ends only after the question's
    silence wait (counted from when the respondent stopped), unless they carry on speaking.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._speech_end = 0.0
        self._hold_task: asyncio.Task | None = None
        self._hold_done = False

    def _silence_wait(self) -> float:
        return float(self._turn_analyzer.params.stop_secs)

    async def _handle_vad_user_stopped_speaking(self, frame):
        self._speech_end = (getattr(frame, "timestamp", 0) or time.time()) - getattr(frame, "stop_secs", 0)
        await super()._handle_vad_user_stopped_speaking(frame)

    async def _discard_pending_end_of_turn(self):
        await self._cancel_hold()
        self._hold_done = False
        await super()._discard_pending_end_of_turn()

    async def _cancel_hold(self):
        if self._hold_task:
            await self.task_manager.cancel_task(self._hold_task)
            self._hold_task = None

    async def _maybe_trigger_user_turn_stopped(self):
        if self._turn_complete and not self._hold_done and sounds_unfinished(self._text):
            if self._hold_task is None:
                left = max(0.0, self._silence_wait() - (time.time() - (self._speech_end or time.time())))
                self._hold_task = self.task_manager.create_task(self._hold(left), f"{self}::_hold")
            return
        await super()._maybe_trigger_user_turn_stopped()

    async def _hold(self, seconds: float):
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        self._hold_task = None
        self._hold_done = True
        if self._text:
            await self.trigger_user_turn_stopped()


class TurnPolicy:
    """Owns the turn analyzer and mute strategy for one call; the flow tells it what's being asked."""

    def __init__(self, sample_rate: int | None = None):
        self.analyzer = LocalSmartTurnAnalyzerV3(sample_rate=sample_rate,
                                                 params=SmartTurnParams(stop_secs=WAIT_CHOICE))
        self.mute = ProtectedSpeechMute()
        self.wait = WAIT_CHOICE

    def strategies(self) -> UserTurnStrategies:
        return UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=INTERRUPT_MIN_WORDS)],
            stop=[TranscriptAwareStopStrategy(turn_analyzer=self.analyzer)],
        )

    def asking(self, item: Item | None, protect: bool = False) -> None:
        """Called as each question (or the consent statement) starts being spoken."""
        self.wait = silence_wait(item)
        set_silence_wait(self.analyzer, self.wait)
        self.mute.protect = protect

    def protect_next(self) -> None:
        self.mute.protect = True


def set_silence_wait(analyzer: LocalSmartTurnAnalyzerV3, seconds: float) -> None:
    # SmartTurn reads stop_secs once at construction (into _stop_ms); there's no public setter,
    # so both are updated together here. Covered by tests/test_turns.py.
    analyzer._params.stop_secs = seconds
    analyzer._stop_ms = seconds * 1000
