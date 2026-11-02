"""LLM key resolution: build-plan key names (GROQ_API_KEY, GEMINI_API_KEY) and LLM_API_KEY."""

from app.voice.config import VoiceSettings


def settings(**kw) -> VoiceSettings:
    return VoiceSettings(_env_file=None, **kw)


def test_provider_key_fills_llm_api_key():
    cfg = settings(llm_provider="groq", groq_api_key="gsk")
    assert cfg.llm_api_key == "gsk" and cfg.missing("llm_api_key") == []
    assert settings(llm_provider="google", gemini_api_key="gem").llm_api_key == "gem"


def test_llm_api_key_overrides_main_provider_only():
    cfg = settings(llm_provider="groq", llm_api_key="override", groq_api_key="gsk", gemini_api_key="gem")
    assert cfg.key_for("groq") == "override"
    assert cfg.key_for("google") == "gem"


def test_missing_reports_llm_key():
    assert settings(llm_provider="groq").missing("llm_api_key") == ["LLM_API_KEY"]


def test_fallback_llm_needs_its_own_key(monkeypatch):
    from app.voice import services

    monkeypatch.setattr(services, "voice_settings", lambda: settings(groq_api_key="gsk"))
    assert services.make_llm(fallback=True) is None
    monkeypatch.setattr(services, "voice_settings", lambda: settings(groq_api_key="gsk", gemini_api_key="gem"))
    assert type(services.make_llm(fallback=True)).__name__ == "GoogleLLMService"
    assert type(services.make_llm()).__name__ == "GroqLLMService"
