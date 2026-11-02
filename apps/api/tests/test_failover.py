"""LLM failover: the backup model takes over when the main one fails mid-call (deep dive: LLM failover).

Pipecat's failover strategy only switches on errors it treats as permanent (bad key, bad request).
The failures that actually happen mid-call (quota, rate limit, 5xx, network) must switch too.
"""

import asyncio

import pytest
from pipecat.frames.frames import Frame, TextFrame
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.service_switcher import ServiceSwitcherStrategyFailover
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.utils.errors import ErrorCategory

from app.voice.bot import fail_over_on


class FakeLLM(LLMService):
    def __init__(self, name: str, fail_with: ErrorCategory | None = None, exception: Exception | None = None):
        super().__init__(name=name)
        self.fail_with = fail_with
        self.exception = exception
        self.seen: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TextFrame):
            self.seen.append(frame.text)
            if self.exception is not None:  # the way GoogleLLMService reports API errors
                await self.push_error(f"Unknown error occurred: {self.exception}", exception=self.exception)
                return
            if self.fail_with is not None:
                await self.push_error(f"{self.name} failed", category=self.fail_with)
                return
        await self.push_frame(frame, direction)


async def _run(category: ErrorCategory, with_fix: bool):
    main, backup = FakeLLM("main", fail_with=category), FakeLLM("backup")
    switcher = LLMSwitcher(llms=[main, backup], strategy_type=ServiceSwitcherStrategyFailover)
    if with_fix:
        fail_over_on(main)
    await run_test(switcher, frames_to_send=[TextFrame("first answer")])
    return switcher.strategy.active_service, main, backup


@pytest.mark.parametrize("category", [ErrorCategory.QUOTA, ErrorCategory.RATE_LIMIT,
                                      ErrorCategory.SERVER, ErrorCategory.CONNECTIVITY])
def test_mid_call_failures_switch_to_the_backup(category):
    active, main, backup = asyncio.run(_run(category, with_fix=True))
    assert active is backup
    assert not main.is_usable


@pytest.mark.parametrize("category", [ErrorCategory.QUOTA, ErrorCategory.SERVER])
def test_without_the_fix_pipecat_stays_on_the_failing_model(category):
    """Documents why fail_over_on exists: by default only permanent errors switch."""
    active, main, _ = asyncio.run(_run(category, with_fix=False))
    assert active is main


def test_permanent_errors_switch_even_without_the_fix():
    active, _, backup = asyncio.run(_run(ErrorCategory.AUTHENTICATION, with_fix=False))
    assert active is backup


def _gemini_error(code: int, status: str):
    from google.genai import errors
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "message": "x", "status": status}})


async def _run_gemini(exc: Exception):
    main, backup = FakeLLM("gemini", exception=exc), FakeLLM("backup")
    switcher = LLMSwitcher(llms=[main, backup], strategy_type=ServiceSwitcherStrategyFailover)
    fail_over_on(main)
    await run_test(switcher, frames_to_send=[TextFrame("first answer")])
    return switcher.strategy.active_service, backup


@pytest.mark.parametrize("code,status", [(429, "RESOURCE_EXHAUSTED"), (503, "UNAVAILABLE"),
                                         (500, "INTERNAL"), (401, "UNAUTHENTICATED")])
def test_real_gemini_api_errors_switch_to_the_backup(code, status):
    """google-genai keeps the HTTP code in `.code`, which Pipecat doesn't read (it'd be UNKNOWN)."""
    active, backup = asyncio.run(_run_gemini(_gemini_error(code, status)))
    assert active is backup


def test_an_unrecognised_error_does_not_switch():
    active, backup = asyncio.run(_run_gemini(RuntimeError("tool call returned odd JSON")))
    assert active is not backup


def test_rate_limited_models_come_back_after_the_cooldown_and_rerun_the_turn():
    """Live finding (Nov 3): main timed out, the backup (same Gemini key) hit 429, the call went silent."""
    async def go():
        main, backup = FakeLLM("main", ErrorCategory.CONNECTIVITY), FakeLLM("backup", ErrorCategory.RATE_LIMIT)
        switcher = LLMSwitcher(llms=[main, backup], strategy_type=ServiceSwitcherStrategyFailover)
        reruns = []

        async def rerun_if_stuck(service):
            if switcher.strategy.active_service is service:
                reruns.append(service.name)

        for s in (main, backup):
            fail_over_on(s, cooldown=0.2, on_restored=rerun_if_stuck)
        await run_test(switcher, frames_to_send=[TextFrame("answer"), SleepFrame(sleep=0.1), TextFrame("answer again")])
        down = (main.is_usable, backup.is_usable)
        await asyncio.sleep(0.5)
        return down, (main.is_usable, backup.is_usable), reruns, switcher.strategy.active_service

    down, up, reruns, active = asyncio.run(go())
    assert down == (False, False)          # both benched
    assert up == (True, True)              # both back after the cooldown
    assert reruns == [active.name]         # the stuck turn is re-run once, on the active model


def test_permanent_errors_are_not_restored():
    async def go():
        main, backup = FakeLLM("main", ErrorCategory.AUTHENTICATION), FakeLLM("backup")
        switcher = LLMSwitcher(llms=[main, backup], strategy_type=ServiceSwitcherStrategyFailover)
        fail_over_on(main, cooldown=0.1)
        await run_test(switcher, frames_to_send=[TextFrame("answer")])
        await asyncio.sleep(0.3)
        return main.is_usable
    assert asyncio.run(go()) is False
