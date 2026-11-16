"""Where uploaded CSV bytes live. A download is served only from the uploads directory."""

from pathlib import Path

from app.core.config import Settings
from app.core.errors import ApiError


def uploads_root(settings: Settings) -> Path:
    """The only directory a stored CSV is allowed to occupy."""
    root = (settings.data_dir / "uploads").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def stored_file(settings: Settings, relative: str) -> Path:
    """Resolve a stored path and refuse anything outside the uploads directory.

    The parent check is what stops a task row from pointing at an arbitrary file.
    """
    root = uploads_root(settings)
    candidate = Path(relative)
    if not candidate.is_absolute():
        candidate = (settings.data_dir / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if candidate.parent != root or not candidate.is_file():
        raise ApiError(404, "File not found")
    return candidate
