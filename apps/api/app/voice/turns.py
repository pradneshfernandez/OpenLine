"""Turn-taking and interruption rules for a survey call (component deep dive §1–2).

- **End of turn** is decided by Smart Turn v3.2 (audio-based, covers English and Hindi). Its
  `stop_secs` is the longest silence we wait when the model thinks the respondent isn't done
  ("hmm… char… nahi, paanch"). That wait depends on the question: a yes/no answer is short,
  a number or an open answer often comes after a pause.
- **Interruptions** need at least 2 words while the agent is speaking, so a backchannel
  ("haan", "hmm", "accha") doesn't stop it. When the agent is silent, one word is an answer.
- **Protected speech**: while the consent statement (and the goodbye) is read, the respondent's
  audio is muted so the statement is always heard in full. Muted speech is dropped, not queued.
"""

from __future__ import annotations

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
            stop=[VerdictKeepingStopStrategy(turn_analyzer=self.analyzer)],
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
