"""Voice / telephony settings, read from the environment (or apps/api/.env).

Variable names follow the build plan: GNANI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY,
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, EXOTEL_*, PUBLIC_BASE_URL.
LLM_API_KEY still works and overrides the provider-specific key for LLM_PROVIDER.
Never commit keys or phone numbers.
"""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["groq", "openai", "anthropic", "google"]


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gnani_api_key: str = ""
    llm_provider: LLMProvider = "groq"
    llm_api_key: str = ""  # resolved from the provider-specific key below when empty
    llm_model: str = ""
    llm_fallback_provider: LLMProvider | Literal[""] = "google"  # step 7: used when the main LLM fails
    llm_fallback_model: str = ""

    groq_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    public_base_url: str = ""  # e.g. https://abcd.ngrok-free.app

    # Exotel (step 6, when credentials arrive): Voicebot applet → wss://<public_base_url>/ws
    exotel_account_sid: str = ""
    exotel_api_key: str = ""
    exotel_api_token: str = ""
    exotel_subdomain: str = "api.exotel.com"  # api.in.exotel.com for the Mumbai cluster
    exotel_caller_id: str = ""
    exotel_app_id: str = ""  # App Bazaar flow id with the Voicebot applet

    tts_model: str = "timbre-v2.5"
    voice_en: str = "Nalini"
    voice_hi: str = "Nalini"  # also the default for the other Indian languages
    stt_auto_language: bool = False  # Prisma v3.0 indic-auto for mid-call language switching
    # With auto language: the 2-4 languages Prisma may hear (respondents switch between them mid-sentence).
    stt_languages: str = "en-IN,hi-IN,ta-IN"
    # "transcribe" writes numbers as digits (the number check relies on that); "codemix" keeps English
    # words in Latin script but writes numbers as words.
    stt_format: str = "transcribe"

    survey_org: str = "the research team"
    # Smart Turn decides the end of a turn; VAD only marks pauses, at the 0.2 s it was trained with.
    vad_stop_secs: float = 0.2
    hello_wait_secs: float = 3.0
    # Silence after a question before it's asked again; after IDLE_REPROMPTS re-asks the call ends (partial).
    idle_reprompt_secs: float = 8.0
    idle_reprompts: int = 2
    confirm_below_confidence: float = 0.7

    def key_for(self, provider: str) -> str:
        """API key for an LLM provider; LLM_API_KEY applies to the main provider only."""
        if provider == self.llm_provider and self.llm_api_key:
            return self.llm_api_key
        return {
            "groq": self.groq_api_key, "google": self.gemini_api_key,
            "openai": self.openai_api_key, "anthropic": self.anthropic_api_key,
        }.get(provider, "")

    @model_validator(mode="after")
    def _resolve_llm_key(self):
        # Only one key set (e.g. just GEMINI_API_KEY)? Use that provider instead of failing on the default.
        if not self.llm_api_key and not self.key_for(self.llm_provider):
            self.llm_provider = next((p for p in ("groq", "google", "openai", "anthropic") if self.key_for(p)),
                                     self.llm_provider)
        if not self.llm_api_key:
            self.llm_api_key = self.key_for(self.llm_provider)
        return self

    def missing(self, *names: str) -> list[str]:
        return [n.upper() for n in names if not getattr(self, n)]


@lru_cache
def voice_settings() -> VoiceSettings:
    return VoiceSettings()
