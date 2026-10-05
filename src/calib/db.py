"""SQLite store for the study: synced Reader state, third-rater scores, predictions, writing days."""

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reader_docs (
    doc_id           TEXT PRIMARY KEY,
    url_norm         TEXT NOT NULL,
    source_url       TEXT NOT NULL DEFAULT '',
    title            TEXT NOT NULL DEFAULT '',
    location         TEXT NOT NULL DEFAULT '',
    reading_progress REAL NOT NULL DEFAULT 0,
    first_opened_at  TEXT,
    saved_at         TEXT,
    updated_at       TEXT,
    tags             TEXT NOT NULL DEFAULT '[]',
    highlights       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS reader_docs_url ON reader_docs(url_norm);
CREATE TABLE IF NOT EXISTS highlights (
    highlight_id TEXT PRIMARY KEY,
    parent_id    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rescores (
    url_norm  TEXT NOT NULL,
    rater     TEXT NOT NULL,
    score     REAL NOT NULL,
    scored_at TEXT NOT NULL,
    PRIMARY KEY (url_norm, rater)
);
CREATE TABLE IF NOT EXISTS predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    probability REAL NOT NULL CHECK (probability >= 0 AND probability <= 1),
    created_at  TEXT NOT NULL,
    due         TEXT NOT NULL,
    post        TEXT,
    outcome     INTEGER CHECK (outcome IN (0, 1)),
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS writing_days (
    day          TEXT PRIMARY KEY,
    baseline     INTEGER NOT NULL,
    last_total   INTEGER NOT NULL,
    marked_done  INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO sync_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
