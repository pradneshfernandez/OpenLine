# Common tasks. Run from the repo root.
API := apps/api
WEB := apps/web

.PHONY: dev setup db migrate api web test test-api test-web build lint smoke

dev:            ## Start Postgres, API (:8000) and web (:5173); `make dev ARGS=--ngrok` for a tunnel
	./scripts/dev.sh $(ARGS)

setup:          ## Install all dependencies
	cd $(API) && uv sync
	cd $(WEB) && npm install
	@[ -f $(API)/.env ] || cp $(API)/.env.example $(API)/.env

db:             ## Start Postgres (localhost:5434)
	docker compose up -d --wait db

migrate: db     ## Apply database migrations
	cd $(API) && uv run alembic upgrade head

api:            ## API only, with reload
	cd $(API) && uv run uvicorn app.main:app --port 8000 --reload --reload-dir app

web:            ## Web only
	cd $(WEB) && npm run dev

test: test-api test-web

test-api:       ## Backend tests (SQLite, no Postgres needed)
	cd $(API) && uv run pytest -q

test-web:       ## Type-check the web app
	cd $(WEB) && npx tsc -b

build:          ## Production build of the web app
	cd $(WEB) && npm run build

lint:
	cd $(WEB) && npm run lint

smoke:          ## Live Gnani TTS→STT check at 8 kHz (needs GNANI_API_KEY)
	cd $(API) && uv run python scripts/gnani_smoke.py
