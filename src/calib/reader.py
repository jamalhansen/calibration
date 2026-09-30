"""Mirror Reader's per-document state (opened, progress, tags, highlights) into the study DB.

The shared local_first_common.readwise client returns FeedItems, which drop the
fields this study is about, so this reads the list endpoint directly.
"""

import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import requests
from local_first_common.url import normalize_url

from calib.db import get_state, set_state

LIST_URL = "https://readwise.io/api/v3/list/"
_MAX_RETRIES = 5

Fetch = Callable[[dict], dict]


def http_fetch(token: str) -> Fetch:
    def fetch(params: dict) -> dict:
        for _ in range(_MAX_RETRIES):
            resp = requests.get(LIST_URL, headers={"Authorization": f"Token {token}"}, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(max(1, int(resp.headers.get("Retry-After", "15"))))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("Reader API kept rate-limiting; try again in a minute")

    return fetch


def iter_documents(fetch: Fetch, updated_after: str | None) -> Iterator[dict]:
    params: dict = {"page_size": 100}
    if updated_after:
        params["updatedAfter"] = updated_after
    while True:
        page = fetch(params)
        yield from page.get("results", [])
        cursor = page.get("nextPageCursor")
        if not cursor:
            return
        params = {**params, "pageCursor": cursor}


def _tag_names(doc: dict) -> list[str]:
    tags = doc.get("tags") or {}
    if isinstance(tags, dict):
        return sorted(str(v.get("name", k)) if isinstance(v, dict) else str(k) for k, v in tags.items())
    return sorted(str(t) for t in tags)


def sync(conn: sqlite3.Connection, fetch: Fetch, full: bool = False) -> int:
    """Pull every document changed since the last sync. Returns documents written."""
    since = None if full else get_state(conn, "reader_synced_at")
    started = datetime.now(UTC).isoformat()
    written = 0
    for doc in iter_documents(fetch, since):
        if doc.get("category") in ("highlight", "note"):
            if doc.get("parent_id"):
                conn.execute(
                    "INSERT OR REPLACE INTO highlights(highlight_id, parent_id) VALUES (?, ?)",
                    (doc["id"], doc["parent_id"]),
                )
            continue
        source_url = doc.get("source_url") or doc.get("url") or ""
        conn.execute(
            """INSERT INTO reader_docs(doc_id, url_norm, source_url, title, location, reading_progress,
                                       first_opened_at, saved_at, updated_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(doc_id) DO UPDATE SET
                 url_norm = excluded.url_norm, source_url = excluded.source_url, title = excluded.title,
                 location = excluded.location, reading_progress = excluded.reading_progress,
                 first_opened_at = excluded.first_opened_at, saved_at = excluded.saved_at,
                 updated_at = excluded.updated_at, tags = excluded.tags""",
            (
                doc["id"], normalize_url(source_url), source_url, doc.get("title") or "",
                doc.get("location") or "", float(doc.get("reading_progress") or 0),
                doc.get("first_opened_at"), doc.get("saved_at"), doc.get("updated_at"),
                json.dumps(_tag_names(doc)),
            ),
        )
        written += 1
    conn.execute(
        "UPDATE reader_docs SET highlights = "
        "(SELECT COUNT(*) FROM highlights h WHERE h.parent_id = reader_docs.doc_id)"
    )
    set_state(conn, "reader_synced_at", started)
    conn.commit()
    return written
