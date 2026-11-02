"""Local file storage for originals and per-version artefacts. Files are write-once."""

import hashlib
from pathlib import Path

from app.config import settings


def _root() -> Path:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings.storage_dir


def save_bytes(data: bytes, subdir: str, suffix: str) -> str:
    """Store bytes under a content hash and return the path relative to the storage root."""
    digest = hashlib.sha256(data).hexdigest()
    rel = Path(subdir) / f"{digest}{suffix}"
    path = _root() / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return str(rel)


def path_of(rel: str) -> Path:
    return _root() / rel


def read_bytes(rel: str) -> bytes:
    return path_of(rel).read_bytes()
