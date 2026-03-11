"""Shared helper for resolving storage_state.json path."""

import os
import tempfile
from pathlib import Path

STORAGE_STATE_PATH = Path(__file__).resolve().parents[1] / "storage_state.json"


def get_storage_state_path() -> str:
    """Return path to storage_state.json, creating from env var if needed."""
    if STORAGE_STATE_PATH.exists():
        return str(STORAGE_STATE_PATH)
    env_data = os.environ.get("STORAGE_STATE")
    if env_data:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(env_data)
        tmp.close()
        return tmp.name
    return ""
