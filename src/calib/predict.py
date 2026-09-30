"""Self-calibration: log probabilistic predictions, resolve them, and score them (Brier).

A prediction tied to a blog post (`post`) resolves itself: yes once the vault note
is published on or before the due date, no once the due date passes without it.
"""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from local_first_common.obsidian import parse_frontmatter


def add(conn: sqlite3.Connection, text: str, probability: float, due: date, post: str | None = None) -> int:
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1 (e.g. 0.7)")
    cur = conn.execute(
        "INSERT INTO predictions(text, probability, created_at, due, post) VALUES (?, ?, ?, ?, ?)",
        (text, probability, datetime.now(UTC).isoformat(), due.isoformat(), post),
    )
    conn.commit()
    return int(cur.lastrowid)


def resolve(conn: sqlite3.Connection, pid: int, outcome: bool) -> None:
    cur = conn.execute(
        "UPDATE predictions SET outcome = ?, resolved_at = ? WHERE id = ?",
        (int(outcome), datetime.now(UTC).isoformat(), pid),
    )
    if cur.rowcount == 0:
        raise KeyError(f"no prediction #{pid}")
    conn.commit()


def open_predictions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM predictions WHERE outcome IS NULL ORDER BY due").fetchall()


def find_post_note(brainsync: Path, post: str) -> Path | None:
    candidate = Path(post).expanduser()
    for p in (candidate, brainsync / post):
        if p.is_file():
            return p
    blog = brainsync / "blog"
    matches = sorted(p for p in blog.rglob("*.md") if post in p.stem or post in p.parent.name)
    return matches[0] if matches else None


def post_published_on(note: Path) -> date | None:
    fm = parse_frontmatter(note)
    if str(fm.get("status", "")).lower() != "published":
        return None
    raw = fm.get("published_date") or fm.get("date")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def auto_resolve(conn: sqlite3.Connection, brainsync: Path, today: date) -> list[tuple[int, bool]]:
    resolved = []
    for row in open_predictions(conn):
        if not row["post"]:
            continue
        due = date.fromisoformat(row["due"])
        note = find_post_note(brainsync, row["post"])
        published = post_published_on(note) if note else None
        if published and published <= due:
            outcome = True
        elif today > due:
            outcome = False
        else:
            continue
        resolve(conn, row["id"], outcome)
        resolved.append((row["id"], outcome))
    return resolved


def score(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT probability, outcome FROM predictions WHERE outcome IS NOT NULL").fetchall()
    if not rows:
        return {"n": 0, "brier": None, "buckets": []}
    brier = sum((r["probability"] - r["outcome"]) ** 2 for r in rows) / len(rows)
    buckets = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        hi = lo + 0.2
        group = [r for r in rows if lo <= r["probability"] < hi or (hi >= 1.0 and r["probability"] == 1.0)]
        if group:
            buckets.append({
                "said": f"{int(lo * 100)}-{int(hi * 100)}%",
                "n": len(group),
                "happened_pct": round(100 * sum(r["outcome"] for r in group) / len(group)),
            })
    return {"n": len(rows), "brier": round(brier, 3), "buckets": buckets}
