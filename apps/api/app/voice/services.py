"""Factories for the speech and language services.

The rest of the voice code never imports Gnani or an LLM provider directly, so either can be
swapped (published pipecat-gnani, a patched fork, or a custom service) in one place.
"""

from __future__ import annotations

from pipecat.transcriptions.language import Language

from app.voice.config import voice_settings
from app.voice.i18n import lang_code

LANGUAGES = {"en": Language.EN_IN, "hi": Language.HI_IN}


GNANI_TTFS_P99 = 1.2


def make_stt(lang: str, sample_rate: int = 8000):
    """Gnani Prisma realtime STT. `format="transcribe"` turns spoken numbers into digits."""
    from pipecat_gnani import GnaniSTTService

    cfg = voice_settings()
    if cfg.stt_auto_language:
        settings = GnaniSTTService.Settings(
            model="prisma-v3.0", language="indic-auto",
            language_candidates=[c.strip() for c in cfg.stt_languages.split(",") if c.strip()],
            format=cfg.stt_format,
        )
    else:
        settings = GnaniSTTService.Settings(
            language=LANGUAGES[lang_code(lang)], format="transcribe",
        )
    # Speech end → final transcript, measured on 8 kHz calls (Nov 3): 0.83–1.06 s. Pipecat uses it as
    # the safety net when no finalized transcript arrives.
    return GnaniSTTService(api_key=cfg.gnani_api_key, sample_rate=sample_rate, settings=settings,
                           ttfs_p99_latency=GNANI_TTFS_P99)


def make_tts(lang: str, voice: str | None = None, speed: float = 1.0, sample_rate: int = 8000):
    """Gnani Timbre streaming TTS (WebSocket, interruptible for barge-in)."""
    from pipecat_gnani import GnaniTTSService

    cfg = voice_settings()
    code = lang_code(lang)
    return GnaniTTSService(
        api_key=cfg.gnani_api_key,
        sample_rate=sample_rate,
        settings=GnaniTTSService.Settings(
            voice=voice or (cfg.voice_hi if code == "hi" else cfg.voice_en),
            model=cfg.tts_model,
            language=LANGUAGES[code],
            speed=speed,
        ),
    )


def tts_speed_delta(speed: float):
    from pipecat_gnani import GnaniTTSService

    return GnaniTTSService.Settings(speed=speed)


_LLM = {
    "groq": ("pipecat.services.groq.llm", "GroqLLMService", "llama-3.3-70b-versatile"),
    "openai": ("pipecat.services.openai.llm", "OpenAILLMService", "gpt-4.1-mini"),
    "anthropic": ("pipecat.services.anthropic.llm", "AnthropicLLMService", "claude-haiku-5-5"),
    "google": ("pipecat.services.google.llm", "GoogleLLMService", "gemini-3.5-flash-lite"),  # ~1.2–1.9 s per answer
}
# Fallback model when LLM_FALLBACK_PROVIDER is the same provider and no LLM_FALLBACK_MODEL is set.
_FALLBACK_MODEL = {"google": "gemini-3.6-flash", "groq": "llama-3.1-8b-instant", "openai": "gpt-4.1-nano"}


def make_llm(system_instruction: str | None = None, fallback: bool = False):
    """The LLM only turns speech into a candidate value; the form runner decides the flow.

    `fallback=True` builds LLM_FALLBACK_PROVIDER instead (step 7); returns None if it isn't
    configured or has no key.
    """
    import importlib

    cfg = voice_settings()
    if fallback:
        provider, model = cfg.llm_fallback_provider, cfg.llm_fallback_model
        if not provider or not cfg.key_for(provider):
            return None
        if not model and provider == cfg.llm_provider:
            model = _FALLBACK_MODEL.get(provider, "")
    else:
        provider, model = cfg.llm_provider, cfg.llm_model
    module, cls_name, default_model = _LLM[provider]
    cls = getattr(importlib.import_module(module), cls_name)
    return cls(
        api_key=cfg.key_for(provider),
        settings=cls.Settings(model=model or default_model, system_instruction=system_instruction),
    )
