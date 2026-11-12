"""Central settings for ASHA VoiceMate.

All secrets are read from the ".env" file in the project root.
Nothing secret is ever sent to the browser.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains "backend", "frontend", "data".
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

_db_env = os.getenv("ASHA_DB_PATH")
DATABASE_PATH = Path(_db_env) if _db_env else DATA_DIR / "asha_voicemate.db"
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH

GNANI_API_KEY = os.getenv("GNANI_API_KEY", "").strip()
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))


def gnani_key_present() -> bool:
    """True when a real-looking key is set (not the placeholder)."""
    key = globals()["GNANI_API_KEY"]
    return bool(key) and not key.startswith("replace-with")
