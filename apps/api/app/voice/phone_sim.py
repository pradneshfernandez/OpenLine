"""Phone simulator: talk to the bot through the real phone path, without a carrier.

Open `/phone-sim` on a laptop (localhost) or on a phone (via `ngrok http 8000`, since the mic
needs HTTPS). The page records the mic, band-limits it to 300–3400 Hz, downsamples it to 8 kHz,
mu-law encodes it in 20 ms frames, and sends Twilio's media stream messages to `/ws`. So the bot
runs exactly as on a Twilio call (TwilioFrameSerializer, 8 kHz STT/TTS, Smart Turn at 8 kHz).
Only the carrier network itself (jitter, its own codecs and noise suppression) is missing; the page
can drop a share of frames to imitate packet loss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Form, FormVersion, Interview

router = APIRouter()

PAGE = Path(__file__).resolve().parent.parent / "static" / "phone_sim.html"
SIM_CALL_PREFIX = "SIM"  # call_sid of simulated calls: no Twilio REST hang-up for these


class SimCallIn(BaseModel):
    form_version_id: int
    language: Literal["en", "hi"] = "en"
    label: str = Field("phone sim", max_length=200)


@router.get("/phone-sim", include_in_schema=False)
def phone_sim_page():
    return FileResponse(PAGE, media_type="text/html")


@router.get("/api/phone-sim/forms")
def sim_forms(db: Session = Depends(get_session)):
    """Latest version of each form, for the simulator's picker."""
    out = []
    for f in db.scalars(select(Form).order_by(Form.created_at.desc())):
        versions = [v for v in f.versions if v.version_no > 0]
        if not versions:
            continue
        v = max(versions, key=lambda v: v.version_no)
        out.append({"form_id": f.id, "title": f.title, "version_id": v.id, "version_no": v.version_no,
                    "languages": v.languages})
    return out


@router.post("/api/phone-sim/calls")
def create_sim_call(body: SimCallIn, db: Session = Depends(get_session), x_user: str | None = Header(None)):
    if db.get(FormVersion, body.form_version_id) is None:
        raise HTTPException(404, "Form version not found")
    interview = Interview(form_version_id=body.form_version_id, language=body.language, channel="phone",
                          participant_label=body.label or "phone sim",
                          created_by=(x_user or "").strip() or "phone sim")
    version = db.get(FormVersion, body.form_version_id)
    db.add(interview)
    db.commit()
    return {"interview_id": interview.id, "form_id": version.form_id,
            "call_sid": f"{SIM_CALL_PREFIX}{interview.id:06d}"}
