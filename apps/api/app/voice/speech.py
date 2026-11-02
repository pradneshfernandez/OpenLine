"""Agent voices per language, and one-shot Gnani Timbre synthesis.

Used by the editor's "Listen" button, the Settings voice preview, and simulated respondents
(who speak their answers into the bot like a caller would).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import storage
from app.db import get_session
from app.models import Project
from app.voice.config import voice_settings
from app.voice.i18n import lang_code

router = APIRouter(prefix="/api")

BCP47 = {"en": "en-IN", "hi": "hi-IN"}


def voice_list() -> list[str]:
    from gnani.tts.client import GnaniTTSClient

    return GnaniTTSClient.supported_voices(voice_settings().tts_model)


def project_voices(project: Project | None) -> dict[str, dict]:
    """Voice + speed per call language; project choices over the .env defaults."""
    cfg = voice_settings()
    saved = (project.voices if project else None) or {}
    out = {}
    for code, default in (("en", cfg.voice_en), ("hi", cfg.voice_hi)):
        v = saved.get(code) or {}
        out[code] = {"voice": v.get("voice") or default, "speed": float(v.get("speed") or 1.0)}
    return out


def synthesize(text: str, lang: str, voice: str, speed: float = 1.0, sample_rate: int = 24000,
               container: Literal["wav", "raw"] = "wav") -> bytes:
    """Timbre REST synthesis, cached on disk by its inputs (the same sentence is asked often)."""
    from gnani.tts.client import AudioConfig, GnaniTTSClient

    cfg = voice_settings()
    if not cfg.gnani_api_key:
        raise RuntimeError("Set GNANI_API_KEY in apps/api/.env")
    code = lang_code(lang)
    key = hashlib.sha256(json.dumps([text, code, voice, speed, sample_rate, container, cfg.tts_model]).encode()).hexdigest()
    rel = f"tts/{key}.{container}"
    if storage.path_of(rel).exists():
        return storage.read_bytes(rel)
    audio = GnaniTTSClient(api_key=cfg.gnani_api_key).synthesize(
        text, voice=voice, model=cfg.tts_model, language=BCP47[code], speed=speed,
        audio_config=AudioConfig(sample_rate=sample_rate, container=container))
    path = storage.path_of(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return audio


# ---------------------------------------------------------------------------
# API


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    lang: str = "en"
    voice: str | None = None
    speed: float | None = Field(None, ge=0.7, le=1.3)
    project_id: int | None = None


@router.post("/tts")
async def speak(body: SpeakIn, db: Session = Depends(get_session)):
    """WAV of `text` in the agent's voice for that language (or the given voice)."""
    code = lang_code(body.lang)
    chosen = project_voices(db.get(Project, body.project_id) if body.project_id else None)[code]
    voice = body.voice or chosen["voice"]
    if voice not in voice_list():
        raise HTTPException(422, f"Unknown voice {voice!r}")
    try:
        audio = await asyncio.to_thread(synthesize, body.text, code, voice, body.speed or chosen["speed"])
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except Exception as e:  # Gnani API errors
        raise HTTPException(502, f"Gnani TTS failed: {e}") from e
    return Response(audio, media_type="audio/wav")


@router.get("/voices")
def voices():
    return {"model": voice_settings().tts_model, "voices": voice_list()}


class VoiceIn(BaseModel):
    voice: str
    speed: float = Field(1.0, ge=0.7, le=1.3)


@router.get("/projects/{project_id}/voices")
def get_voices(project_id: int, db: Session = Depends(get_session)):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404)
    return project_voices(p)


@router.put("/projects/{project_id}/voices")
def put_voices(project_id: int, body: dict[Literal["en", "hi"], VoiceIn], db: Session = Depends(get_session)):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404)
    known = set(voice_list())
    for code, v in body.items():
        if v.voice not in known:
            raise HTTPException(422, f"Unknown voice {v.voice!r} for {code}")
    p.voices = {**(p.voices or {}), **{code: v.model_dump() for code, v in body.items()}}
    db.commit()
    return project_voices(p)
