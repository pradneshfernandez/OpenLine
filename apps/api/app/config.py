from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FORMS_", extra="ignore")

    database_url: str = "postgresql+psycopg://forms:forms@localhost:5434/forms"
    storage_dir: Path = Path(__file__).resolve().parent.parent / "storage"
    max_upload_mb: int = 10
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Simulated respondents phone this server's own media stream.
    self_ws_url: str = "ws://127.0.0.1:8000/ws"
    # Campaign scheduler loop (off in tests, which call campaigns.tick() directly).
    scheduler: bool = True


settings = Settings()
