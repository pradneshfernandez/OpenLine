"""A full phone-path call where the respondent switches between English, Hindi and Tamil.

    STT_AUTO_LANGUAGE=true uv run uvicorn app.main:app --port 8001     # server with indic-auto
    uv run python scripts/codeswitch_call.py --url ws://localhost:8001/ws --form-version 9

Answers the trial form like a respondent: consent and age in English, then the three mixed
answers from scripts/codeswitch_check.py (household size, ration card, main problem), and
"no" to the school question so the child repeat is skipped. Prints the stored answers.
"""

import argparse
import asyncio
import audioop
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import websockets  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Answer, Interview  # noqa: E402
from scripts.codeswitch_check import ANSWERS, GAP, tts  # noqa: E402

RATE, FRAME = 8000, 160


def script() -> list[bytes]:
    one = lambda lang, text: tts(text, lang)  # noqa: E731
    mixed = lambda name: GAP.join(tts(t, lang) for lang, t in ANSWERS[name][0])  # noqa: E731
    return [one("en-IN", "Yes, I agree."), one("en-IN", "Thirty two."), mixed("hh_size"),
            one("en-IN", "No."), mixed("ration_card"), mixed("main_problem")]


async def call(url: str, interview_id: int, answers: list[bytes], seconds: float):
    sid = f"MZcs{interview_id}"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(json.dumps({"event": "start", "sequenceNumber": "1", "streamSid": sid, "start": {
            "streamSid": sid, "accountSid": "ACsim", "callSid": f"SIM{interview_id:06d}", "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": RATE, "channels": 1},
            "customParameters": {"interview_id": str(interview_id)}}}))
        loop = asyncio.get_running_loop()
        state = {"agent_at": 0.0, "queue": list(answers)}

        async def receive():
            try:
                async for msg in ws:
                    if json.loads(msg).get("event") == "media":
                        state["agent_at"] = loop.time()
            except websockets.ConnectionClosed:
                pass

        recv = asyncio.create_task(receive())
        start, seq, pending = loop.time(), 2, b""
        try:
            while loop.time() - start < seconds and not recv.done():
                quiet = state["agent_at"] and loop.time() - state["agent_at"] > 1.5
                if not pending and quiet and state["queue"]:
                    pending, state["agent_at"] = state["queue"].pop(0), 0.0
                chunk, pending = (pending[:FRAME * 2], pending[FRAME * 2:]) if pending else (b"", b"")
                payload = base64.b64encode(audioop.lin2ulaw(chunk.ljust(FRAME * 2, b"\x00"), 2)).decode()
                await ws.send(json.dumps({"event": "media", "streamSid": sid, "sequenceNumber": str(seq),
                                          "media": {"track": "inbound", "payload": payload}}))
                seq += 1
                await asyncio.sleep(FRAME / RATE)
            await ws.send(json.dumps({"event": "stop", "streamSid": sid}))
        except websockets.ConnectionClosed:
            pass
        recv.cancel()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8001/ws")
    ap.add_argument("--form-version", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=180)
    args = ap.parse_args()
    answers = script()
    with SessionLocal() as db:
        i = Interview(form_version_id=args.form_version, language="en", channel="phone",
                      participant_label="code-switch check", created_by="codeswitch_call")
        db.add(i)
        db.commit()
        interview_id = i.id
    print(f"interview {interview_id}")
    asyncio.run(call(args.url, interview_id, answers, args.seconds))
    with SessionLocal() as db:
        i = db.get(Interview, interview_id)
        print(f"status: {i.status}")
        for a in db.query(Answer).filter(Answer.interview_id == interview_id).order_by(Answer.id):
            print(f"  {a.question_name:<16} value={a.value!r:<12} heard={a.heard_text!r}")


if __name__ == "__main__":
    main()
