# OpenLine

Run a survey team's existing XLSForm (ODK / KoboToolbox / SurveyCTO) as an AI phone interview in
Indian languages. Gnani Prisma listens, an LLM interprets, Gnani Timbre speaks, on Pipecat.

1. Upload an XLSForm; the phone check flags questions that won't work by voice; fix them in the editor.
2. The bot calls respondents, asks each question in their language, follows the form's skip logic and
   validation, and saves every answer with transcript, audio and confidence.
3. Review answers; export CSV (KoboToolbox export planned).

**The form runner decides; the LLM interprets.** The runner picks the next question and validates;
the LLM only turns speech into a candidate value through tool calls.

## Repository layout

```
apps/
  api/            FastAPI backend: XLSForm module, phone check, Pipecat survey bot, telephony
    app/          api/ (routes), xlsform/, checks/, voice/ (runner, flow, bot, calls, second pass)
    migrations/   Alembic
    tests/        pytest (SQLite, no Postgres needed)
    scripts/      gnani_smoke, fake_twilio_call, browser_test
    sample_forms/ public XLSForms + test and trial forms
  web/            React + Mantine UI (forms, inspector/editor, report, history, interviews)
scripts/dev.sh    start everything locally
docker-compose.yml  Postgres on :5434
Makefile          common tasks
```

## Quick start

Needs: Docker, [uv](https://docs.astral.sh/uv/), Node 22+, and the `pipecat-gnani` fork checked out
next to this repo (`../pipecat-gnani`).

```bash
make setup                 # uv sync + npm install; creates apps/api/.env from .env.example
make migrate               # Postgres up + migrations
make dev                   # API http://localhost:8000/docs · UI http://localhost:5173
```

Keys go in `apps/api/.env` (see [`apps/api/.env.example`](apps/api/.env.example)); never commit them.
`GET /api/voice/status` lists what's missing. To test the phone path without a carrier, open http://localhost:8000/phone-sim
(8 kHz μ-law over the Twilio media-stream protocol). Real phone calls also need `ngrok http 8000`
(`make dev ARGS=--ngrok`) with `PUBLIC_BASE_URL` set to the tunnel URL.

| Command | |
| --- | --- |
| `make test` | Backend tests + web type-check |
| `make smoke` | Live Gnani TTS → STT at 8 kHz, English + Hindi |
| `make build` | Production build of the web app |

## Stack

FastAPI · SQLAlchemy 2 · Alembic · Postgres · pyxform · Pipecat 1.x + Flows · Gnani Prisma (STT) and
Timbre (TTS) · Groq (Gemini fallback) · Twilio / Exotel · React · Mantine · TanStack Query.
