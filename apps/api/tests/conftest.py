import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="forms-test-"))
# Tests run against SQLite so they need no running Postgres; models use portable types.
os.environ.setdefault("FORMS_DATABASE_URL", f"sqlite:///{_tmp / 'test.db'}")
os.environ.setdefault("FORMS_STORAGE_DIR", str(_tmp / "storage"))
# Never use the real keys in apps/api/.env: environment variables override the .env file, so
# tests can't place calls, start simulations against the dev server, or spend API credit.
for _key in ("GNANI_API_KEY", "LLM_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
             "ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
             "PUBLIC_BASE_URL", "EXOTEL_ACCOUNT_SID", "EXOTEL_API_KEY", "EXOTEL_API_TOKEN"):
    os.environ[_key] = ""
os.environ["LLM_PROVIDER"] = "groq"
os.environ["FORMS_SELF_WS_URL"] = "ws://127.0.0.1:9/ws"  # nothing listens here

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "sample_forms"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app, headers={"X-User": "tester"})


@pytest.fixture(scope="session")
def project_id(client) -> int:
    return client.get("/api/projects").json()[0]["id"]


def upload(client, project_id, path: Path, **data):
    with path.open("rb") as fh:
        return client.post(f"/api/projects/{project_id}/forms/upload",
                           files={"file": (path.name, fh.read())}, data=data)
