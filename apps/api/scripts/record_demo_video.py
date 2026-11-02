"""Record the demo video: a scripted mock phone call through the real pipeline, filmed on /demo.

    STT_AUTO_LANGUAGE=true uv run uvicorn app.main:app --port 8000      # no --reload while recording
    uv run --with playwright python scripts/record_demo_video.py --out demo_call.mp4

1. Starts a demo call (/api/demo/calls) and opens /demo?watch=<id> in headless Chrome, recording it.
2. Phones /ws like Twilio and answers as a scripted respondent voiced by Gnani Timbre. Like the
   simulated respondents, it waits for each agent turn and answers *that* question: a re-ask gets the
   next scripted line, a read-back ("5?") gets a yes.
3. After the call (and the second pass), muxes the call's stereo recording onto the page video.

Every answer, delay and badge on screen comes from the real call; only the respondent is scripted.
"""

import argparse
import asyncio
import audioop
import base64
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx  # noqa: E402
import websockets  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import storage  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Interview, TurnLog  # noqa: E402
from app.voice.session import FINAL_STATUSES  # noqa: E402
from scripts.codeswitch_check import tts  # noqa: E402

RATE, FRAME = 8000, 160
PAUSE = object()  # a thinking pause inside an answer

# The storyline: per question, what the respondent says on each ask. Each line is a list of
# (language, text) spans or PAUSE (1.5 s of silence mid-answer).
SCRIPT = {
    "consent": [[("en-IN", "Yes, go ahead.")]],
    "age": [[("en-IN", "Two hundred.")],                                        # range check → asked again
            [("en-IN", "Sorry, thirty-two.")]],
    "hh_size": [[("en-IN", "We are five."), ("hi-IN", "मैं, मेरी wife, और तीन बच्चे।")],  # Hinglish
                [("en-IN", "Five.")]],
    "children_school": [[("en-IN", "Yes, they do.")]],
    "num_children": [[("en-IN", "Three of them.")], [("en-IN", "Two of them.")]],
    "water_source": [[("en-IN", "Sorry, one change. Only two of the children go to school, not three.")],  # correction
                     [("hi-IN", "ज़्यादातर"), ("en-IN", "from a hand pump.")]],
    "main_problem": [[("hi-IN", "पानी की बहुत problem है,"), ("en-IN", "the tanker comes only twice a week.")]],  # Hinglish
}
CONFIRM = [("en-IN", "Yes, that's right.")]
READ_BACK = re.compile(r"^\s*\S{1,24}\?\s*$")


def speak(line) -> bytes:
    gap = b"\x00\x00" * int(RATE * 0.12)
    parts = [b"\x00\x00" * int(RATE * 1.5) if p is PAUSE else tts(p[1], p[0]) for p in line]
    return gap.join(parts)


async def respond(ws_url: str, interview_id: int, call_sid: str, max_seconds: float):
    sid = f"MZsim{interview_id}"
    loop = asyncio.get_running_loop()
    state = {"agent_at": 0.0, "last_turn": 0, "asked": {}}
    queue: list[bytes] = []

    def line_for(turn: TurnLog) -> bytes | None:
        if READ_BACK.match(turn.text or "") and turn.node_name in state["asked"]:
            return speak(CONFIRM)
        n = state["asked"].get(turn.node_name, 0)
        lines = SCRIPT.get(turn.node_name, [])
        state["asked"][turn.node_name] = n + 1
        return speak(lines[min(n, len(lines) - 1)]) if lines else None

    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(json.dumps({"event": "start", "sequenceNumber": "1", "streamSid": sid, "start": {
            "streamSid": sid, "accountSid": "ACsim", "callSid": call_sid, "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": RATE, "channels": 1},
            "customParameters": {"interview_id": str(interview_id)}}}))

        async def receive():
            try:
                async for msg in ws:
                    if json.loads(msg).get("event") == "media":
                        state["agent_at"] = loop.time()
            except websockets.ConnectionClosed:
                pass

        async def listen():
            while True:
                await asyncio.sleep(0.4)
                with SessionLocal() as db:
                    status = db.get(Interview, interview_id).status
                    turns = list(db.scalars(select(TurnLog).where(
                        TurnLog.interview_id == interview_id, TurnLog.id > state["last_turn"],
                        TurnLog.speaker == "agent").order_by(TurnLog.id)))
                if status in FINAL_STATUSES:
                    return
                for t in turns:
                    state["last_turn"] = t.id
                if turns and turns[-1].node_name not in ("", "end"):
                    audio = await asyncio.to_thread(line_for, turns[-1])
                    if audio:
                        queue.append(audio)

        recv, lsn = asyncio.create_task(receive()), asyncio.create_task(listen())
        started, pending, seq = loop.time(), b"", 2
        try:
            while loop.time() - started < max_seconds and not lsn.done():
                quiet = loop.time() - state["agent_at"] > 0.8
                if not pending and queue and quiet:
                    pending = queue.pop(0) + b"\x00\x00" * RATE
                chunk, pending = (pending[:FRAME * 2], pending[FRAME * 2:]) if pending else (b"", b"")
                payload = base64.b64encode(audioop.lin2ulaw(chunk.ljust(FRAME * 2, b"\x00"), 2)).decode()
                await ws.send(json.dumps({"event": "media", "streamSid": sid, "sequenceNumber": str(seq),
                                          "media": {"track": "inbound", "payload": payload}}))
                seq += 1
                await asyncio.sleep(FRAME / RATE)
            await ws.send(json.dumps({"event": "stop", "streamSid": sid}))
        except websockets.ConnectionClosed:
            pass
        finally:
            lsn.cancel()
            recv.cancel()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--language", default="en", choices=["en", "hi"])
    ap.add_argument("--max-seconds", type=float, default=240)
    ap.add_argument("--tail", type=float, default=25, help="seconds to keep filming after the call (second pass)")
    ap.add_argument("--out", default="demo_call.mp4")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    call = httpx.post(f"{args.base}/api/demo/calls", json={"language": args.language}).json()
    interview_id = call["interview_id"]
    print(f"interview {interview_id}")
    tmp = Path(args.out).with_suffix(".frames")
    tmp.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        exe = shutil.which("google-chrome") or shutil.which("chromium")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1600, "height": 900}, record_video_dir=str(tmp),
                                  record_video_size={"width": 1600, "height": 900})
        page = ctx.new_page()
        page_t0 = time.time()
        page.goto(f"{args.base}/demo?watch={interview_id}")
        # Playwright's sync API owns this thread's event loop, so the caller runs in its own thread.
        caller = threading.Thread(target=lambda: asyncio.run(respond(
            args.base.replace("http", "ws") + "/ws", interview_id, call["call_sid"], args.max_seconds)))
        caller.start()
        while caller.is_alive():
            page.wait_for_timeout(500)
        page.wait_for_timeout(args.tail * 1000)  # the second pass and recording land on the page
        video = page.video.path()
        ctx.close()
        browser.close()

    with SessionLocal() as db:
        i = db.get(Interview, interview_id)
        offset = i.started_at.replace(tzinfo=timezone.utc).timestamp() - page_t0 if i.started_at else 0
        wav = storage.path_of(i.recording_file) if i.recording_file else None
        print(f"status {i.status}; {len(i.answers)} answers; audio offset {offset:.2f}s")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
    if wav:
        # Both voices, centred: the recording is stereo (respondent left, agent right).
        cmd += ["-itsoffset", f"{max(offset, 0):.3f}", "-i", str(wav), "-map", "0:v", "-map", "1:a",
                "-af", "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,aresample=48000", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", args.out]
    subprocess.run(cmd, check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
