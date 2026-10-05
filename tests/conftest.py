"""Shared fixtures."""

import sqlite3
from pathlib import Path

import pytest
from local_first_common.testing import isolate_tracking_db  # noqa: F401

from calib import db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "calibration.db")


@pytest.fixture
def discovery_store(tmp_path) -> Path:
    path = tmp_path / "store.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT, description TEXT, "
        "score REAL, status TEXT, probed_at TEXT)"
    )
    c.commit()
    c.close()
    return path


def add_item(store: Path, url: str, score: float, status: str = "kept", probed: bool = False, title: str = "T"):
    c = sqlite3.connect(store)
    c.execute(
        "INSERT INTO items(url, title, description, score, status, probed_at) VALUES (?, ?, '', ?, ?, ?)",
        (url, title, score, status, "2026-09-29T00:00:00+00:00" if probed else None),
    )
    c.commit()
    c.close()


def doc(doc_id, url, **kw):
    base = {
        "id": doc_id,
        "source_url": url,
        "title": doc_id,
        "category": "article",
        "location": "later",
        "reading_progress": 0,
        "first_opened_at": None,
        "saved_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "tags": {},
    }
    base.update(kw)
    return base


def fake_fetch(pages: list[list[dict]]):
    calls = []

    def fetch(params):
        calls.append(dict(params))
        i = len(calls) - 1
        return {"results": pages[i], "nextPageCursor": f"c{i + 1}" if i + 1 < len(pages) else None}

    fetch.calls = calls
    return fetch
