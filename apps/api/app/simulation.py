"""Simulated respondents (brief §5.10, build plan §5.6.5).

A simulated respondent is a caller with an answer key. It phones the real bot the way Twilio
does (the /ws media stream, 8 kHz mu-law), listens for each agent turn, and speaks its answer
with Gnani TTS in one of four personas:

- cooperative: says the answer plainly
- vague: hedges ("umm, I think it's ...")
- correcting: says a wrong answer first, then corrects it
- mixed: Hinglish (Hindi filler in an English call, English words in a Hindi call)

The answer key is made by walking the form runner with generated values, so it follows the
form's own skip logic, constraints and repeats. After the calls, each interview's saved answers
are compared with its key: accuracy overall, by question × language, and a list of misses.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.db import SessionLocal, get_session
from app.models import Form, FormVersion, Interview, SimulationRun, TurnLog
from app.voice.config import voice_settings
from app.voice.runner import ANOTHER, DK, FormRunner, Item, flat_name, runner_for_version
from app.voice.session import FINAL_STATUSES

router = APIRouter(prefix="/api")

PERSONAS = ["cooperative", "vague", "correcting", "mixed", "dont_know"]
DONT_KNOW_SHARE = 0.3  # the dont_know persona says "pata nahi" to about this share of questions
# Background noise in the caller's audio, as signal-to-noise ratio in dB (None = clean line).
NOISE_LEVELS = {"clean": None, "15db": 15.0, "5db": 5.0}
SPEECH_RMS = 3000.0  # typical RMS of the synthetic respondent's 16-bit speech; noise is set against it
RESPONDENT_VOICE = {"en": "Kaveri", "hi": "Kaveri"}
SPOKEN_TYPES = {"integer", "decimal", "select_one", "select_multiple", "text"}
YES = {"yes", "y", "1", "agree", "agreed", "haan", "ha"}
NAMES = {"en": ["Sunita", "Rohit", "Pooja", "Aman", "Kavya", "Arjun", "Meena", "Ravi"],
         "hi": ["सुनीता", "रोहित", "पूजा", "अमन", "काव्या", "अर्जुन", "मीना", "रवि"]}
PLACES = {"en": ["Varanasi", "Jaipur", "Nashik", "Gaya", "Mysore"], "hi": ["वाराणसी", "जयपुर", "नासिक", "गया", "मैसूर"]}
OPEN = {"en": ["Water supply", "Bad roads", "Power cuts", "No jobs"], "hi": ["पानी की कमी", "खराब सड़कें", "बिजली कटौती", "रोज़गार नहीं"]}
WORDS = {
    "en": {"dk": "I don't know", "vague": "Umm... I think it's {x}", "correct": "{w}... no sorry, {x}",
           "and": " and ", "mixed": "Haan ji, {x}", "again": "I said, my answer is {x}"},
    "hi": {"dk": "पता नहीं", "vague": "हम्म... शायद {x}", "correct": "{w}... नहीं नहीं, {x}",
           "and": " और ", "mixed": "Yes, {x}", "again": "मैंने कहा, मेरा जवाब है {x}"},
}
RATE, FRAME = 8000, 160  # Twilio sends 20 ms frames of 8 kHz mu-law

_tasks: set[asyncio.Task] = set()  # keep running simulations referenced


# ---------------------------------------------------------------------------
# Answer key


def _bounds(constraint: str) -> tuple[float | None, float | None]:
    lo = hi = None
    for op, num in re.findall(r"\.\s*(>=|>|<=|<)\s*(-?\d+(?:\.\d+)?)", constraint or ""):
        n = float(num)
        if op in (">=", ">"):
            lo = n + (1 if op == ">" else 0)
        else:
            hi = n - (1 if op == "<" else 0)
    return lo, hi


def _number(item: Item, q: dict, rnd: random.Random) -> int:
    lo, hi = _bounds(q.get("constraint", ""))
    name = item.name.lower()
    if "age" in name and "child" in name:
        lo, hi = max(lo or 3, 3), min(hi if hi is not None else 17, 17)
    elif "age" in name:
        lo, hi = max(lo or 18, 18), min(hi if hi is not None else 70, 70)
    else:  # counts: stay near the bottom of the range so households and repeats look real
        lo = 0 if lo is None else lo
        hi = lo + 6 if hi is None else min(hi, lo + 6)
    return int(rnd.uniform(lo, max(lo, hi) + 0.999))


def generate_value(runner: FormRunner, item: Item, lang: str, rnd: random.Random) -> tuple[Any, str]:
    """(value for the runner, what the respondent says)."""
    w = WORDS[lang]
    if item.name == ANOTHER:
        yes = item.index[-1] < 1  # two instances, then "no"
        return ("yes" if yes else "no"), (item.options[0 if yes else 1]["label"])
    q = runner.by_name[item.name]
    opts = [o for o in item.options if not runner.is_dk_code(o["name"])]
    if item.type == "select_one" and opts:
        if "consent" in item.name.lower():
            o = next((o for o in opts if o["name"].lower() in YES or o["label"].strip().lower() in YES | {"हाँ", "हां"}), opts[0])
        else:
            o = rnd.choice(opts)
        return o["name"], o["label"]
    if item.type == "select_multiple" and opts:
        picks = rnd.sample(opts, k=min(len(opts), rnd.choice([1, 2])))
        return [o["name"] for o in picks], w["and"].join(o["label"] for o in picks)
    if item.type in ("integer", "decimal"):
        n = _number(item, q, rnd)
        return n, str(n)
    if item.type == "text":
        low = item.name.lower()
        pool = (PLACES[lang] if any(k in low for k in ("village", "place", "town", "city", "district"))
                else NAMES[lang] if "name" in low else OPEN[lang])
        x = rnd.choice(pool)
        return x, x
    return DK, w["dk"]


def make_answer_key(version: FormVersion, lang: str, seed: int, persona: str = "cooperative") -> dict:
    """Walk the form with generated answers. Returns {"answers": flat dict, "script": [...]}.

    The script is what the respondent will say, per question name in the order asked.
    """
    runner = runner_for_version(version)
    rnd = random.Random(seed)
    script, item = [], runner.start(lang)
    for _ in range(2000):  # guard against a form that never ends
        if item is None:
            break
        if item.is_note:
            item = runner.next()
            continue
        for _try in range(8):  # constraints that refer to other answers are found by trying
            value, say = generate_value(runner, item, lang, rnd)
            if (persona == "dont_know" and item.name != ANOTHER and "consent" not in item.name.lower()
                    and rnd.random() < DONT_KNOW_SHARE):
                value, say = DK, WORDS[lang]["dk"]
            res = runner.code(item.name, DK) if value == DK else runner.answer(item.name, value)
            if res.ok:
                break
        if not res.ok:  # still no valid value: answer "don't know" instead
            runner.code(item.name, DK)
            value, say = DK, WORDS[lang]["dk"]
        if item.name != ANOTHER:
            script.append({"name": item.name, "key": flat_name(item.name, item.index),
                           "value": " ".join(value) if isinstance(value, list) else str(value), "say": say,
                           "type": item.type, "options": [o["label"] for o in item.options]})
        else:
            script.append({"name": ANOTHER, "key": None, "value": value, "say": say, "type": "another", "options": []})
        item = runner.next()
    return {"answers": {s["key"]: s["value"] for s in script if s["key"]}, "script": script}


def utterance(step: dict, persona: str, lang: str, rnd: random.Random) -> str:
    w, x = WORDS[lang], step["say"]
    if step["value"] == DK or step["type"] == "another":
        return x
    if persona == "vague":
        return w["vague"].format(x=x)
    if persona == "correcting":
        if step["type"] in ("integer", "decimal"):
            return w["correct"].format(w=int(float(step["value"])) + 2, x=x)
        others = [o for o in step["options"] if o != x]
        if step["type"] == "select_one" and others and "consent" not in step["name"].lower():
            return w["correct"].format(w=rnd.choice(others), x=x)
        return x
    if persona == "mixed":
        return w["mixed"].format(x=x)
    return x


# ---------------------------------------------------------------------------
# Scoring


def _norm(v: Any) -> str:
    s = "" if v is None else str(v).strip().lower()
    try:
        return str(float(s)).rstrip("0").rstrip(".")
    except ValueError:
        pass
    s = re.sub(r"[।॥.,!?;:'\"“”‘’()\-]+", " ", s)  # punctuation (incl. the Devanagari danda) isn't content
    return " ".join(sorted(s.split()))


def score(i: Interview) -> list[dict]:
    """One row per expected answer: expected, got, correct. Unreached questions of an
    unfinished call are left out."""
    got = i.final_answers or {}
    heard = {a.question_name + "".join(f"[{n + 1}]" for n in a.repeat_index): a for a in i.answers}
    rows = []
    for key, expected in (i.answer_key or {}).get("answers", {}).items():
        if key not in got and i.status != "completed":
            continue
        a = heard.get(key)
        rows.append({"key": key, "question": key.split("[")[0], "expected": expected, "got": got.get(key),
                     "correct": _norm(expected) == _norm(got.get(key)), "heard": a.heard_text if a else "",
                     "attempts": a.attempts if a else 0})
    return rows


def report(run: SimulationRun) -> dict:
    ints = run.interviews
    finished = [i for i in ints if i.status in FINAL_STATUSES]
    completed = [i for i in ints if i.status == "completed"]
    grid: dict[str, dict[str, list[int]]] = {}
    misses, total, correct, reasks, answered, seconds = [], 0, 0, 0, 0, 0.0
    per_interview = []
    by: dict[str, dict[str, list[int]]] = {"noise": {}, "persona": {}}
    delays = sorted(t.latency_ms for i in ints for t in i.turns if t.latency_ms is not None)
    for i in ints:
        rows = score(i)
        ok = sum(r["correct"] for r in rows)
        total += len(rows)
        correct += ok
        for dim, val in (("noise", (i.answer_key or {}).get("noise", "clean")), ("persona", i.persona)):
            cell = by[dim].setdefault(val, [0, 0])
            cell[0] += ok
            cell[1] += len(rows)
        for r in rows:
            cell = grid.setdefault(r["question"], {}).setdefault(i.language, [0, 0])
            cell[0] += r["correct"]
            cell[1] += 1
            if not r["correct"]:
                misses.append({**r, "interview_id": i.id, "persona": i.persona, "language": i.language})
        reasks += sum(max(0, a.attempts - 1) for a in i.answers if a.still_relevant)
        n = sum(1 for a in i.answers if a.still_relevant)
        answered += n
        if i.started_at and i.ended_at:
            seconds += (i.ended_at - i.started_at).total_seconds()
        per_interview.append({"id": i.id, "persona": i.persona, "language": i.language, "status": i.status,
                              "noise": (i.answer_key or {}).get("noise", "clean"),
                              "correct": ok, "total": len(rows), "error": i.error})
    order = {r["name"]: n for n, r in enumerate((ints[0].answer_key or {}).get("script", []))} if ints else {}
    return {
        "runs": len(ints), "finished": len(finished), "completed": len(completed),
        "completion_rate": len(completed) / len(ints) if ints else None,
        "accuracy": {"correct": correct, "total": total, "rate": correct / total if total else None},
        "reasks": reasks, "reasks_per_call": reasks / len(finished) if finished else None,
        "seconds_per_question": seconds / answered if answered else None,
        "grid": [{"question": q, **{lang: {"correct": c, "total": t} for lang, (c, t) in cells.items()},
                  "all": {"correct": sum(c for c, _ in cells.values()), "total": sum(t for _, t in cells.values())}}
                 for q, cells in sorted(grid.items(), key=lambda kv: order.get(kv[0], 1e9))],
        "by_noise": [{"noise": k, "correct": c, "total": t} for k, (c, t) in
                     sorted(by["noise"].items(), key=lambda kv: list(NOISE_LEVELS).index(kv[0]) if kv[0] in NOISE_LEVELS else 9)],
        "by_persona": [{"persona": k, "correct": c, "total": t} for k, (c, t) in by["persona"].items()],
        "reply_delay": {"avg": sum(delays) / len(delays) / 1000, "p90": delays[int(0.9 * (len(delays) - 1))] / 1000,
                        "turns": len(delays)} if delays else None,
        "misses": misses, "interviews": per_interview,
    }


# ---------------------------------------------------------------------------
# The simulated call


class NoiseBed:
    """Continuous background noise for the simulated line: low rumble (traffic, fans) plus hiss,
    at a fixed level relative to the respondent's speech. Clean lines pass audio through."""

    def __init__(self, snr_db: float | None, seed: int = 0):
        import numpy as np

        self.np = np
        self.level = None if snr_db is None else SPEECH_RMS / (10 ** (snr_db / 20))
        self.rng = np.random.default_rng(seed)
        self.brown = 0.0

    def mix(self, pcm: bytes) -> bytes:
        if self.level is None:
            return pcm
        np = self.np
        white = self.rng.standard_normal(len(pcm) // 2)
        brown = np.empty_like(white)
        b = self.brown
        for k, w in enumerate(white):  # leaky integrator: rumble that drifts like street noise
            b = 0.98 * b + w * 0.2
            brown[k] = b
        self.brown = b
        noise = 0.7 * brown / (np.std(brown) + 1e-9) + 0.3 * white
        noise *= self.level / (np.sqrt(np.mean(noise ** 2)) + 1e-9)
        out = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) + noise
        return np.clip(out, -32768, 32767).astype(np.int16).tobytes()


def _speech(text: str, lang: str) -> bytes:
    from app.voice.speech import synthesize

    return synthesize(text, lang, RESPONDENT_VOICE[lang], 1.0, sample_rate=RATE, container="raw")


async def simulate_call(interview_id: int, ws_url: str, max_seconds: float) -> None:
    """Phone the bot as Twilio would and answer each agent turn from the script."""
    import audioop  # deprecated in 3.13; the fake Twilio script uses it too

    import websockets

    with SessionLocal() as db:
        i = db.get(Interview, interview_id)
        lang, persona, script = i.language, i.persona, list((i.answer_key or {}).get("script", []))
        snr = NOISE_LEVELS.get((i.answer_key or {}).get("noise", "clean"))
    noise = NoiseBed(snr, seed=interview_id)
    rnd = random.Random(interview_id)
    queue: list[bytes] = []
    state = {"agent_at": 0.0, "last_turn": 0, "last_node": None, "pointer": {}, "last_say": b"", "last_text": ""}
    sid = f"MZsim{interview_id}"
    loop = asyncio.get_running_loop()
    started = loop.time()

    def next_line(node: str) -> bytes | None:
        """Audio for the answer to `node`; a re-ask of the same node repeats the last answer."""
        if node == state["last_node"] and state["last_say"]:
            # Asked again (not heard, or re-asked): say it again, more fully, like a person would.
            state["last_say"] = _speech(WORDS[lang]["again"].format(x=state["last_text"]), lang)
            return state["last_say"]
        n = state["pointer"].get(node, 0)
        steps = [s for s in script if s["name"] == node]
        if n >= len(steps):
            return None
        state["pointer"][node] = n + 1
        state["last_node"] = node
        state["last_text"] = steps[n]["say"]
        state["last_say"] = _speech(utterance(steps[n], persona, lang, rnd), lang)
        return state["last_say"]

    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(json.dumps({"event": "start", "sequenceNumber": "1", "streamSid": sid, "start": {
            "streamSid": sid, "accountSid": "ACsim", "callSid": f"CAsim{interview_id}", "tracks": ["inbound"],
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
            """New agent turns (logged when the agent stops speaking) decide what to say."""
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
                    audio = await asyncio.to_thread(next_line, turns[-1].node_name)
                    if audio:
                        queue.append(audio)

        recv, lsn = asyncio.create_task(receive()), asyncio.create_task(listen())
        pending, seq = b"", 2
        try:
            while loop.time() - started < max_seconds and not lsn.done():
                quiet = loop.time() - state["agent_at"] > 0.8
                if not pending and queue and quiet:
                    pending = queue.pop(0) + b"\x00" * RATE  # a second of silence after speaking
                chunk, pending = (pending[:FRAME * 2], pending[FRAME * 2:]) if pending else (b"\x00" * FRAME * 2, b"")
                chunk = noise.mix(chunk.ljust(FRAME * 2, b"\x00"))
                payload = base64.b64encode(audioop.lin2ulaw(chunk, 2)).decode()
                await ws.send(json.dumps({"event": "media", "streamSid": sid, "sequenceNumber": str(seq),
                                          "media": {"track": "inbound", "payload": payload}}))
                seq += 1
                await asyncio.sleep(FRAME / RATE)
            await ws.send(json.dumps({"event": "stop", "streamSid": sid}))
        except websockets.ConnectionClosed:
            pass  # the bot hung up
        finally:
            lsn.cancel()
            recv.cancel()


async def run_simulation(run_id: int) -> None:
    with SessionLocal() as db:
        run = db.get(SimulationRun, run_id)
        run.status = "running"
        db.commit()
        s = run.settings
        version = run.form_version
        est = (version.summary or {}).get("question_count", 20)
        ids = []
        noises = s.get("noise") or ["clean"]
        for n in range(s["runs"]):
            persona = s["personas"][n % len(s["personas"])]
            lang = s["languages"][(n // len(s["personas"])) % len(s["languages"])]
            level = noises[(n // (len(s["personas"]) * len(s["languages"]))) % len(noises)]
            key = make_answer_key(version, lang, seed=run_id * 1000 + n, persona=persona) | {"noise": level}
            i = Interview(form_version_id=version.id, language=lang, channel="simulated", persona=persona,
                          answer_key=key, simulation_run_id=run.id, created_by=run.created_by,
                          participant_label=f"Sim {n + 1} · {persona}{'' if level == 'clean' else f' · noise {level}'}")
            db.add(i)
            db.commit()
            ids.append(i.id)
    max_seconds = 120 + est * 25
    sem = asyncio.Semaphore(s.get("parallel", 2))

    async def one(interview_id: int):
        async with sem:
            try:
                await simulate_call(interview_id, app_settings.self_ws_url, max_seconds)
            except Exception as e:
                logger.exception(f"Simulated call {interview_id} failed: {e}")
                with SessionLocal() as db:
                    i = db.get(Interview, interview_id)
                    if i.status not in FINAL_STATUSES:
                        i.status, i.error = "failed", f"Simulated caller: {type(e).__name__}: {e}"[:2000]
                        db.commit()
            await asyncio.sleep(2)  # let the bot write its final status

    await asyncio.gather(*(one(i) for i in ids))
    with SessionLocal() as db:
        run = db.get(SimulationRun, run_id)
        for i in run.interviews:  # a call the bot never closed
            if i.status not in FINAL_STATUSES:
                i.status, i.error = "failed", i.error or "Simulated call timed out"
        run.status, run.finished_at = "finished", datetime.now(timezone.utc)
        db.commit()


# ---------------------------------------------------------------------------
# API


class SimulationIn(BaseModel):
    form_version_id: int
    runs: int = Field(20, ge=1, le=100)
    personas: list[str] = Field(default_factory=lambda: PERSONAS[:4], min_length=1)
    noise: list[str] = Field(default_factory=lambda: ["clean"], min_length=1)
    languages: list[str] = Field(default_factory=lambda: ["en", "hi"], min_length=1)
    parallel: int = Field(2, ge=1, le=4)


def ser_run(run: SimulationRun, full: bool = False) -> dict:
    r = report(run)
    out = {"id": run.id, "status": run.status, "error": run.error, "settings": run.settings,
           "form": {"id": run.form_version.form.id, "title": run.form_version.form.title,
                    "version_id": run.form_version_id, "version_no": run.form_version.version_no},
           "created_by": run.created_by, "created_at": run.created_at.isoformat(),
           "finished_at": run.finished_at.isoformat() if run.finished_at else None,
           "runs": r["runs"], "finished": r["finished"], "accuracy": r["accuracy"],
           "completion_rate": r["completion_rate"]}
    return out | {"report": r} if full else out


@router.get("/projects/{project_id}/simulations")
def list_runs(project_id: int, db: Session = Depends(get_session)):
    rows = db.scalars(select(SimulationRun).join(FormVersion).join(Form)
                      .where(Form.project_id == project_id).order_by(SimulationRun.id.desc()))
    return [ser_run(r) for r in rows]


@router.get("/simulations/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_session)):
    run = db.get(SimulationRun, run_id)
    if run is None:
        raise HTTPException(404)
    return ser_run(run, full=True)


@router.post("/projects/{project_id}/simulations")
async def start_run(project_id: int, body: SimulationIn, db: Session = Depends(get_session),
                    x_user: str | None = Header(None)):
    version = db.get(FormVersion, body.form_version_id)
    if version is None or version.xform_xml is None or version.form.project_id != project_id:
        raise HTTPException(404, "Form version not found")
    bad = ([p for p in body.personas if p not in PERSONAS] + [lng for lng in body.languages if lng not in ("en", "hi")]
           + [n for n in body.noise if n not in NOISE_LEVELS])
    if bad:
        raise HTTPException(422, f"Unknown persona or language: {', '.join(bad)}")
    missing = voice_settings().missing("gnani_api_key", "llm_api_key")
    if missing:
        raise HTTPException(503, f"Simulations run the real bot; set {', '.join(missing)} in apps/api/.env")
    run = SimulationRun(form_version_id=version.id, settings=body.model_dump(),
                        created_by=(x_user or "").strip() or "anonymous")
    db.add(run)
    db.commit()
    task = asyncio.create_task(run_simulation(run.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return ser_run(run)


@router.get("/form-versions/{version_id}/answer-key")
def preview_key(version_id: int, lang: str = "en", persona: str = "cooperative", seed: int = 1,
                db: Session = Depends(get_session)):
    """What a simulated respondent would answer and say — handy to check before a run."""
    version = db.get(FormVersion, version_id)
    if version is None or version.xform_xml is None:
        raise HTTPException(404)
    key = make_answer_key(version, lang, seed, persona=persona)
    rnd = random.Random(seed)
    return {"answers": key["answers"],
            "script": [{**s, "utterance": utterance(s, persona, lang, rnd)} for s in key["script"]]}


def fail_interrupted_runs() -> None:
    """At startup: runs that were in flight when the server stopped can't resume."""
    with SessionLocal() as db:
        for run in db.scalars(select(SimulationRun).where(SimulationRun.status.in_(("queued", "running")))):
            run.status, run.error = "failed", "The server restarted during the run"
            for i in run.interviews:
                if i.status not in FINAL_STATUSES:
                    i.status, i.error = "failed", "The server restarted during the run"
        db.commit()

