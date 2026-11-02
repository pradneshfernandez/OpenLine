# API

FastAPI backend: XLSForm upload / versions / editor, phone check, and the Pipecat survey bot.

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000 --reload --reload-dir app   # http://localhost:8000/docs
uv run pytest
```

Config comes from `.env` (copy `.env.example`).
