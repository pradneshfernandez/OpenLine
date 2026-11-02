"""The generic survey bot: one Pipecat pipeline that runs any stage-1 form version.

    transport.in -> Gnani STT -> user aggregator (+ Silero VAD) -> LLM -> Gnani TTS
                 -> transport.out -> audio recorder -> assistant aggregator

The form version, language and voice are loaded from the Interview row at call start; there
is no code per survey.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.flows import FlowManager
from pipecat.frames.frames import LLMRunFrame, TTSUpdateSettingsFrame
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.service_switcher import ServiceSwitcherStrategyFailover
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner
from pipecat.utils.errors import ErrorCategory, classify_http_status_code

from app.db import SessionLocal
from app.models import FormVersion, Interview
from app.voice.config import voice_settings
from app.voice.flow import SurveyFlow
from app.voice.runner import runner_for_version
from app.voice.services import make_llm, make_stt, make_tts, tts_speed_delta
from app.voice.session import InterviewSession
from app.voice.turns import TurnPolicy


def load_interview(interview_id: int):
    with SessionLocal() as db:
        interview = db.get(Interview, interview_id)
        if interview is None:
            raise ValueError(f"Interview {interview_id} not found")
        version = db.get(FormVersion, interview.form_version_id)
        runner = runner_for_version(version)
        return interview.language, version.form.title, runner


def interview_voice(interview_id: int) -> dict:
    """The project's chosen voice + speed for this interview's language."""
    from app.voice.i18n import lang_code
    from app.voice.speech import project_voices

    with SessionLocal() as db:
        interview = db.get(Interview, interview_id)
        project = interview.form_version.form.project
        return project_voices(project)[lang_code(interview.language)]


# Pipecat's failover only switches on errors it calls permanent (bad key, bad request). The ones
# that actually hit a live call (quota used up, rate limit, 5xx, network) would leave the respondent
# waiting on a model that keeps failing, so those retire the main model for the rest of the call.
MID_CALL_FAILURES = {ErrorCategory.QUOTA, ErrorCategory.RATE_LIMIT, ErrorCategory.SERVER,
                     ErrorCategory.CONNECTIVITY}


def error_category(error) -> ErrorCategory:
    """Pipecat's category, or one read from the HTTP code google-genai keeps in `exception.code`
    (Pipecat doesn't read that attribute, so every Gemini API error arrives as UNKNOWN)."""
    category = error.category or ErrorCategory.UNKNOWN
    code = getattr(error.exception, "code", None)
    if category == ErrorCategory.UNKNOWN and isinstance(code, int):
        category = classify_http_status_code(code)
    return category


LLM_COOLDOWN_SECS = 8.0  # a model benched by a rate limit / timeout is tried again after this


def fail_over_on(llm, cooldown: float = LLM_COOLDOWN_SECS, on_restored=None) -> None:
    """Make `llm` step aside in an LLMSwitcher when a failure hits it mid-call.

    Permanent errors (bad key, bad request) bench it for the rest of the call. Mid-call failures
    (quota, rate limit, 5xx, network) bench it for `cooldown` seconds, then `on_restored(llm)` runs,
    so a call whose models are all rate-limited can re-run the failed turn instead of going silent.
    """
    @llm.event_handler("on_error")
    async def _on_error(processor, error):
        category = error_category(error)
        if not processor.is_usable or not (category in MID_CALL_FAILURES or category.is_permanent):
            return
        logger.warning(f"{processor}: {category.value} error, failing over to the backup LLM")
        await processor.set_usable(False)
        if category.is_permanent:
            return

        async def restore():
            await asyncio.sleep(cooldown)
            await processor.set_usable(True)
            if on_restored is not None:
                await on_restored(processor)

        task = asyncio.create_task(restore())
        _cooldowns.add(task)
        task.add_done_callback(_cooldowns.discard)


_cooldowns: set[asyncio.Task] = set()


async def run_interview(transport: BaseTransport, interview_id: int, sample_rate: int = 8000,
                        handle_sigint: bool = False) -> None:
    cfg = voice_settings()
    lang, study_name, runner = load_interview(interview_id)
    session = InterviewSession(interview_id, runner, lang)
    # A retry of a partial campaign call continues from the first unanswered question.
    from app.voice.recovery import preload_previous_answers

    session.resumed_answers = preload_previous_answers(interview_id, runner)

    stt = make_stt(lang, sample_rate=sample_rate)
    voice = interview_voice(interview_id)
    tts = make_tts(lang, voice=voice["voice"], speed=voice["speed"], sample_rate=sample_rate)
    llm = make_llm()
    backup = make_llm(fallback=True)
    if backup is not None:
        # If the main model stops working mid-call (outage, model retired), switch to the backup
        # and re-run the turn that failed, so the respondent's answer isn't lost.
        main = llm
        llm = LLMSwitcher(llms=[main, backup], strategy_type=ServiceSwitcherStrategyFailover)

        async def _rerun_if_stuck(service):
            # Both models were down: the switcher stayed on this one, so the turn never ran.
            if llm.strategy.active_service is service:
                logger.warning(f"Interview {interview_id}: {service.name} is back, re-running the turn")
                await worker.queue_frame(LLMRunFrame())

        for service in (main, backup):
            fail_over_on(service, on_restored=_rerun_if_stuck)

    context = LLMContext()
    policy = TurnPolicy(sample_rate=sample_rate)  # Smart Turn + per-question waits + interruption rules
    session.policy = policy
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=cfg.vad_stop_secs)),
            user_turn_strategies=policy.strategies(),
            user_idle_timeout=cfg.idle_reprompt_secs,
            user_mute_strategies=[policy.mute]),
    )
    recorder = AudioBufferProcessor(num_channels=2)  # respondent left, agent right

    pipeline = Pipeline([
        transport.input(),
        stt,
        aggregators.user(),
        llm,
        tts,
        transport.output(),
        recorder,
        aggregators.assistant(),
    ])
    latency = UserBotLatencyObserver()
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=sample_rate, audio_out_sample_rate=sample_rate,
                              enable_metrics=True),
        observers=[latency],
    )
    runner = WorkerRunner(handle_sigint=handle_sigint)
    await runner.add_workers(worker)

    async def set_speed(speed: float) -> None:
        await worker.queue_frame(TTSUpdateSettingsFrame(delta=tts_speed_delta(speed), service=tts))

    flow = SurveyFlow(session, study_name, set_speed)
    flow_manager = FlowManager(worker=worker, llm=llm, context_aggregator=aggregators, transport=transport)
    opener: list[asyncio.Task] = []

    if isinstance(llm, LLMSwitcher):
        @llm.strategy.event_handler("on_service_switched")
        async def _on_llm_switched(_strategy, service):
            logger.warning(f"Interview {interview_id}: LLM failed over to {service.name}")
            await worker.queue_frame(LLMRunFrame())

    @latency.event_handler("on_latency_measured")
    async def _on_latency(_observer, seconds):
        session.on_latency(seconds)

    @aggregators.user().event_handler("on_user_turn_idle")
    async def _on_idle(_aggregator):
        node = flow.on_idle()
        if node is not None:
            await flow_manager.set_node_from_config(node)

    @aggregators.user().event_handler("on_user_turn_started")
    async def _on_user_started(_aggregator, *args):
        session.on_user_turn_started()

    @aggregators.user().event_handler("on_user_turn_stopped")
    async def _on_user_stopped(_aggregator, _strategy, message):
        session.on_user_turn_stopped(getattr(message, "content", None))
        if not flow.opened:  # respondent said "hello" before the greeting
            await flow.open(flow_manager)

    @aggregators.assistant().event_handler("on_assistant_turn_stopped")
    async def _on_agent_turn(_aggregator, message):
        session.on_agent_turn(getattr(message, "content", "") or "")

    @recorder.event_handler("on_audio_data")
    async def _on_audio(_buffer, audio, rate, channels):
        session.save_recording(audio, rate, channels)

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client):
        logger.info(f"Interview {interview_id}: connected")
        session.start_clock()
        await recorder.start_recording()
        await flow_manager.initialize(flow.waiting_node())
        opener.append(asyncio.create_task(flow.open_after_wait(flow_manager)))

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client):
        logger.info(f"Interview {interview_id}: disconnected")
        await recorder.stop_recording()
        await runner.cancel()

    try:
        await runner.run()
    finally:
        for t in opener:
            t.cancel()
        session.close()
        logger.info(f"Interview {interview_id}: finished with status {session.final_status or 'partial'}")
        try:  # second pass per answer, now that the recording is saved
            from app.voice.second_pass import run_second_pass

            await run_second_pass(interview_id)
        except Exception as e:
            logger.warning(f"Interview {interview_id}: second pass failed: {e}")
        try:  # full-call transcript (Prisma Batch) from the same recording
            from app.voice.transcript import run_full_transcript

            await run_full_transcript(interview_id)
        except Exception as e:
            logger.warning(f"Interview {interview_id}: full transcript failed: {e}")
