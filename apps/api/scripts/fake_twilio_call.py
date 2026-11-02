"""Pretend to be Twilio: open the /ws media stream like a real call, without a phone.

    uv run python scripts/fake_twilio_call.py --form-version 9 --lang en --seconds 20 \
        [--say "yes" --say "34" ...] [--out call.wav]

Sends Twilio's `connected` / `start` / `media` / `stop` messages (8 kHz mu-law) to the local
server, plays optional respondent answers (spoken by Gnani TTS) after each agent turn, and
writes what the agent said to a WAV file. Useful to check the phone path end to end before
using real Twilio minutes, and the basis for simulated respondents.
"""

import argparse
import asyncio
import audioop
import base64
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import websockets  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Interview  # noqa: E402

RATE = 8000
FRAME = 160  # 20 ms of 8 kHz mu-law, as Twilio sends


async def synthesize(text: str, lang: str) -> bytes:
    """PCM16 8 kHz audio of `text`, via the same Gnani TTS the bot uses."""
    from scripts.gnani_smoke import Collect, run  # reuse the tiny pipeline helper
    from pipecat.frames.frames import TTSAudioRawFrame, TTSSpeakFrame

    from app.voice.services import make_tts

    sink = Collect(TTSAudioRawFrame)
    await run([make_tts(lang, voice="Kaveri", sample_rate=RATE), sink], [TTSSpeakFrame(text)], wait=5)
    return b"".join(f.audio for f in sink.frames)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--form-version", type=int, required=True)
    ap.add_argument("--lang", choices=["en", "hi"], default="en")
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--say", action="append", default=[], help="respondent answers, in order")
    ap.add_argument("--url", default="ws://localhost:8000/ws")
    ap.add_argument("--out", default="fake_call_agent.wav")
    args = ap.parse_args()

    answers = [await synthesize(t, args.lang) for t in args.say]
    with SessionLocal() as db:
        i = Interview(form_version_id=args.form_version, language=args.lang, channel="phone",
                      participant_label="fake twilio", created_by="fake_twilio_call")
        db.add(i)
        db.commit()
        interview_id = i.id
    print(f"interview {interview_id}")

    received = bytearray()
    sid = "MZfake"
    async with websockets.connect(args.url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(json.dumps({"event": "start", "sequenceNumber": "1", "streamSid": sid, "start": {
            "streamSid": sid, "accountSid": "ACfake", "callSid": "CAfake", "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            "customParameters": {"interview_id": str(interview_id)}}}))

        state = {"agent_audio_at": 0.0, "queue": list(answers)}
        loop = asyncio.get_running_loop()
        start = loop.time()

        async def receive():
            try:
                async for msg in ws:
                    data = json.loads(msg)
                    if data.get("event") == "media":
                        received.extend(audioop.ulaw2lin(base64.b64decode(data["media"]["payload"]), 2))
                        state["agent_audio_at"] = loop.time()
            except websockets.ConnectionClosed:
                pass

        async def send():
            seq = 2
            pending = b""
            while loop.time() - start < args.seconds:
                # Once the agent has been quiet for 1.5 s, speak the next scripted answer.
                quiet = state["agent_audio_at"] and loop.time() - state["agent_audio_at"] > 1.5
                if not pending and quiet and state["queue"]:
                    pending = state["queue"].pop(0)
                    state["agent_audio_at"] = 0.0
                chunk, pending = (pending[:FRAME * 2], pending[FRAME * 2:]) if pending else (b"\x00" * FRAME * 2, b"")
                chunk = chunk.ljust(FRAME * 2, b"\x00")
                payload = base64.b64encode(audioop.lin2ulaw(chunk, 2)).decode()
                await ws.send(json.dumps({"event": "media", "streamSid": sid, "sequenceNumber": str(seq),
                                          "media": {"track": "inbound", "payload": payload}}))
                seq += 1
                await asyncio.sleep(FRAME / RATE)
            await ws.send(json.dumps({"event": "stop", "streamSid": sid}))

        recv_task = asyncio.create_task(receive())
        try:
            await send()
        except websockets.ConnectionClosed:
            print("server closed the stream (call ended)")
        await asyncio.sleep(1)
        recv_task.cancel()

    with wave.open(args.out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(bytes(received))
    print(f"agent audio: {len(received) / 2 / RATE:.1f}s -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
