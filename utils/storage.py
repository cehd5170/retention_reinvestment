"""Shared helper for resolving storage_state.json path."""

import os
import tempfile
from pathlib import Path

STORAGE_STATE_PATH = Path(__file__).resolve().parents[1] / "storage_state.json"

_cached_tmp_path: str | None = None


def get_storage_state_path() -> str:
    """Return path to storage_state.json, creating from env var if needed."""
    global _cached_tmp_path
    if STORAGE_STATE_PATH.exists():
        return str(STORAGE_STATE_PATH)
    if _cached_tmp_path and os.path.exists(_cached_tmp_path):
        return _cached_tmp_path
    env_data = os.environ.get("STORAGE_STATE")
    if env_data:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(env_data)
        tmp.close()
        _cached_tmp_path = tmp.name
        return _cached_tmp_path
    return ""
