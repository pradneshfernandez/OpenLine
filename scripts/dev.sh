#!/usr/bin/env bash
# Start everything for local development: Postgres, migrations, API (:8000), UI (:5173).
# Add --ngrok to also open a public tunnel for Twilio/Exotel (set PUBLIC_BASE_URL to its URL).
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --wait db
[ -f apps/api/.env ] || { cp apps/api/.env.example apps/api/.env; echo "created apps/api/.env — fill in keys"; }

(cd apps/api && uv sync -q && uv run alembic upgrade head)
(cd apps/web && [ -d node_modules ] || npm install)

pids=()
trap 'kill "${pids[@]}" 2>/dev/null' EXIT
(cd apps/api && uv run uvicorn app.main:app --port 8000 --reload --reload-dir app) & pids+=($!)
(cd apps/web && npm run dev) & pids+=($!)
if [[ "${1:-}" == "--ngrok" ]]; then ngrok http 8000 --log stdout > /dev/null & pids+=($!); fi

sleep 3
curl -s localhost:8000/api/voice/status && echo
echo "UI: http://localhost:5173   API docs: http://localhost:8000/docs"
wait
