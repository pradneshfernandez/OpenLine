"""Talk to the survey bot from the browser (no phone), using Pipecat's dev runner + WebRTC.

    uv run python scripts/browser_test.py --form-version 9 --lang hi
    # then open http://localhost:7860/client and press Connect

Each connection creates a new Interview (channel "browser"), so answers, the turn log and
the recording show up in the results screen just like a phone call.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipecat.runner.types import RunnerArguments  # noqa: E402
from pipecat.runner.utils import create_transport  # noqa: E402
from pipecat.transports.base_transport import TransportParams  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Interview  # noqa: E402
from app.voice.bot import run_interview  # noqa: E402

ours = argparse.ArgumentParser(add_help=False)
ours.add_argument("--form-version", type=int, required=True, help="FormVersion id to run")
ours.add_argument("--lang", choices=["en", "hi"], default="en")
ours.add_argument("--label", default="browser test")
OPTS, rest = ours.parse_known_args()
sys.argv = [sys.argv[0], *rest]

SAMPLE_RATE = 16000


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, {
        "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    })
    with SessionLocal() as db:
        interview = Interview(form_version_id=OPTS.form_version, language=OPTS.lang, channel="browser",
                              participant_label=OPTS.label, created_by="browser test")
        db.add(interview)
        db.commit()
        interview_id = interview.id
    await run_interview(transport, interview_id, sample_rate=SAMPLE_RATE,
                        handle_sigint=runner_args.handle_sigint)


if __name__ == "__main__":
    from pipecat.runner.run import main

    if "-t" not in sys.argv and "--transport" not in sys.argv:
        sys.argv += ["-t", "webrtc"]
    main()
