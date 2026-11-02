"""Check Gnani TTS and STT at telephone quality (8 kHz) before calling anyone.

    uv run python scripts/gnani_smoke.py

For English and Hindi: Timbre speaks a sentence at 8 kHz, then the audio is streamed in real
time into Prisma realtime STT (format="transcribe"), and the transcript is printed. Numbers
should come back as digits.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipecat.frames.frames import (  # noqa: E402
    EndFrame,
    Frame,
    InputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline  # noqa: E402
from pipecat.pipeline.worker import PipelineParams, PipelineWorker  # noqa: E402
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor  # noqa: E402
from pipecat.workers.runner import WorkerRunner  # noqa: E402

from app.voice.services import make_stt, make_tts  # noqa: E402

RATE = 8000
SENTENCES = {
    "en": "I am thirty four years old and there are five people in my house.",
    "hi": "मेरी उम्र पैंतालीस साल है और मेरे घर में छह लोग रहते हैं।",
}


class Collect(FrameProcessor):
    def __init__(self, kinds):
        super().__init__()
        self.kinds = kinds
        self.frames: list[Frame] = []

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, self.kinds):
            self.frames.append(frame)
        await self.push_frame(frame, direction)


async def run(pipeline_items, frames, wait: float):
    worker = PipelineWorker(Pipeline(pipeline_items), params=PipelineParams(
        audio_in_sample_rate=RATE, audio_out_sample_rate=RATE))
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.5)
    if callable(frames):
        await frames(worker)
    else:
        await worker.queue_frames(frames)
    await asyncio.sleep(wait)
    await worker.queue_frame(EndFrame())
    await asyncio.wait_for(task, 20)


async def check(lang: str) -> None:
    sink = Collect(TTSAudioRawFrame)
    t0 = time.monotonic()
    await run([make_tts(lang, sample_rate=RATE), sink], [TTSSpeakFrame(SENTENCES[lang])], wait=6)
    audio = b"".join(f.audio for f in sink.frames)
    print(f"[{lang}] TTS: {len(audio) / 2 / RATE:.1f}s of audio at {sink.frames[0].sample_rate if sink.frames else '?'} Hz"
          f" (first call took {time.monotonic() - t0:.1f}s)")
    if not audio:
        print(f"[{lang}] TTS returned no audio")
        return

    texts = Collect(TranscriptionFrame)

    async def feed(worker):
        chunk = 1024  # bytes = 64 ms of 16-bit audio at 8 kHz
        for i in range(0, len(audio), chunk):
            await worker.queue_frame(InputAudioRawFrame(audio=audio[i:i + chunk], sample_rate=RATE, num_channels=1))
            await asyncio.sleep(chunk / 2 / RATE)
        silence = b"\x00" * chunk
        for _ in range(30):
            await worker.queue_frame(InputAudioRawFrame(audio=silence, sample_rate=RATE, num_channels=1))
            await asyncio.sleep(chunk / 2 / RATE)

    await run([make_stt(lang, sample_rate=RATE), texts], feed, wait=4)
    heard = " ".join(f.text for f in texts.frames)
    print(f"[{lang}] said : {SENTENCES[lang]}\n[{lang}] heard: {heard or '(nothing)'}")


async def main():
    for lang in ("en", "hi"):
        await check(lang)


if __name__ == "__main__":
    asyncio.run(main())
