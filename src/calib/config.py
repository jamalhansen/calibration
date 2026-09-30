"""Paths and settings. Override any of them in ~/.config/local-first/calibration.toml."""

import os
from pathlib import Path

from local_first_common.config import get_setting

TOOL_NAME = "calibration"


def _path(key: str, default: str) -> Path:
    return Path(os.path.expanduser(str(get_setting(TOOL_NAME, key, default=default))))


DB_PATH = _path("db", "~/sync/calibration/calibration.db")
DISCOVERY_STORE = _path("discovery_store", "~/sync/content-discovery/store.db")
BRAINSYNC = _path("brainsync", "~/vaults/BrainSync")
CONTEXTA = _path("contexta", "~/vaults/Contexta")
ART_DIR = _path("art_dir", "~/iCloud/ai-artist")

# Where Jamal's own prose lives. Contexta notes are excluded: agents write there too.
WRITING_DIRS = [BRAINSYNC / "blog", BRAINSYNC / "newsletter"]
STARTERS_DIR = BRAINSYNC / "blog" / "starters"
PROMPTS_DIR = STARTERS_DIR / "from-reading"

STATUS_FILE = _path("status_file", "~/sync/local-first/writing-practice-latest.json")

READWISE_TOKEN =os.environ.get("READWISE_TOKEN", "")

# An item with no engagement stays "pending" this long before it counts as ignored.
RESOLVE_AFTER_DAYS = int(get_setting(TOOL_NAME, "resolve_after_days", default=14))
WRITING_DONE_WORDS = int(get_setting(TOOL_NAME, "writing_done_words", default=100))
