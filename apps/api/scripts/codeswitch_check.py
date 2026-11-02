"""Check Prisma v3.0 on answers that switch between English, Hindi and Tamil mid-sentence.

    uv run python scripts/codeswitch_check.py [--formats transcribe codemix] [--out-dir DIR]

Each answer is built from Gnani Timbre clips, one per language span, joined into one 8 kHz
utterance, then streamed in real time into Prisma realtime STT with language="indic-auto"
and the candidates in STT_LANGUAGES (default en-IN,hi-IN,ta-IN). Prints what was heard per format.
"""

import argparse
import asyncio
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipecat.frames.frames import InputAudioRawFrame, TranscriptionFrame  # noqa: E402

from app.voice.config import voice_settings  # noqa: E402
from scripts.gnani_smoke import RATE, Collect, run  # noqa: E402

VOICE = "Kaveri"
GAP = b"\x00\x00" * int(RATE * 0.12)  # a short breath between language spans

# The three answers on the code-switching slide: (language, text) spans, and what they mean.
ANSWERS = {
    "hh_size": ([("en-IN", "We are five,"), ("hi-IN", "मैं, मेरी wife, और"), ("ta-IN", "மூன்று பசங்க")],
                "me, my wife, and three kids → 5"),
    "ration_card": ([("ta-IN", "ஆமா, ration card இருக்கு,"), ("hi-IN", "लेकिन BPL नहीं")],
                    "yes, we have a ration card, but not BPL → yes"),
    "main_problem": ([("hi-IN", "पानी की problem,"), ("ta-IN", "தண்ணி வரவே இல்ல")],
                     "the water problem, water doesn't come at all → verbatim"),
}


def tts(text: str, lang: str) -> bytes:
    from gnani.tts.client import AudioConfig, GnaniTTSClient

    cfg = voice_settings()
    return GnaniTTSClient(api_key=cfg.gnani_api_key).synthesize(
        text, voice=VOICE, model=cfg.tts_model, language=lang, speed=1.0,
        audio_config=AudioConfig(sample_rate=RATE, container="raw"))


async def hear(audio: bytes, fmt: str) -> str:
    from pipecat_gnani import GnaniSTTService

    cfg = voice_settings()
    stt = GnaniSTTService(api_key=cfg.gnani_api_key, sample_rate=RATE, settings=GnaniSTTService.Settings(
        model="prisma-v3.0", language="indic-auto", format=fmt,
        language_candidates=[c.strip() for c in cfg.stt_languages.split(",") if c.strip()]))
    texts = Collect(TranscriptionFrame)

    async def feed(worker):
        chunk = 1024
        for i in range(0, len(audio) + RATE * 2, chunk):  # audio, then ~1 s of silence
            part = audio[i:i + chunk] or b"\x00" * chunk
            await worker.queue_frame(InputAudioRawFrame(audio=part.ljust(chunk, b"\x00"), sample_rate=RATE, num_channels=1))
            await asyncio.sleep(chunk / 2 / RATE)

    await run([stt, texts], feed, wait=4)
    return " ".join(f.text for f in texts.frames)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", nargs="+", default=["transcribe", "codemix"])
    ap.add_argument("--out-dir", default=None, help="also write each answer as a WAV")
    args = ap.parse_args()
    print(f"candidates: {voice_settings().stt_languages}")
    for name, (spans, meaning) in ANSWERS.items():
        audio = GAP.join(tts(text, lang) for lang, text in spans)
        if args.out_dir:
            Path(args.out_dir).mkdir(parents=True, exist_ok=True)
            with wave.open(str(Path(args.out_dir) / f"{name}.wav"), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(audio)
        print(f"\n[{name}] said : {' '.join(t for _, t in spans)}   ({meaning})")
        for fmt in args.formats:
            print(f"[{name}] {fmt:<10}: {await hear(audio, fmt) or '(nothing)'}")


if __name__ == "__main__":
    asyncio.run(main())
