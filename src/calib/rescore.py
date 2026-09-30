"""Third rater: score the study's resolved items with another model, using discovery's own scorer and prompt."""

import sqlite3
from datetime import UTC, datetime

from calib.study import StudyItem


def pending_for(conn: sqlite3.Connection, items: list[StudyItem], rater: str, limit: int) -> list[StudyItem]:
    done = {r["url_norm"] for r in conn.execute("SELECT url_norm FROM rescores WHERE rater = ?", (rater,))}
    return [i for i in items if i.resolved and i.url_norm not in done][:limit]


def score_items(provider, items: list[StudyItem], profile: str, exclusions: str) -> list[tuple[StudyItem, float | None]]:
    from discovery.scorer import ContentDiscoveryScorer, build_user_message

    scorer = ContentDiscoveryScorer()
    out = []
    for item in items:
        provider.source_location = item.url_norm
        provider.item_count = 1
        scored = scorer.score(provider, build_user_message(item.title, item.description, profile, exclusions))
        out.append((item, scored.score if scored else None))
    return out


def save(conn: sqlite3.Connection, rater: str, results: list[tuple[StudyItem, float | None]]) -> int:
    now = datetime.now(UTC).isoformat()
    rows = [(i.url_norm, rater, s, now) for i, s in results if s is not None]
    conn.executemany("INSERT OR REPLACE INTO rescores(url_norm, rater, score, scored_at) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    return len(rows)


def load(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in conn.execute("SELECT url_norm, rater, score FROM rescores"):
        out.setdefault(r["rater"], {})[r["url_norm"]] = r["score"]
    return out
