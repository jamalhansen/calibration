"""Join the model's scores to what Jamal did with each item, and measure the fit.

Engagement is read off Reader, strongest signal first:
  noted 1.0       a vault note cites it, or it's tagged for the vault (contexta)
  highlighted .75 at least one highlight
  read .5         reading progress >= 50%
  opened .25      opened at all
  ignored 0       none of the above, and archived or older than the resolve window
  pending         none of the above yet, still young: excluded from every metric
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import zip_longest

from local_first_common.url import normalize_url

ENGAGED = 0.5
VAULT_TAGS = {"contexta", "contexta-pulled"}


@dataclass
class StudyItem:
    url_norm: str
    title: str
    score: float
    probe: bool
    saved_at: str
    level: str
    engagement: float | None
    description: str = ""

    @property
    def resolved(self) -> bool:
        return self.engagement is not None


def classify(doc: sqlite3.Row, noted: bool, now: datetime, resolve_after_days: int) -> tuple[str, float | None]:
    tags = set(json.loads(doc["tags"] or "[]"))
    if noted or tags & VAULT_TAGS:
        return "noted", 1.0
    if doc["highlights"] > 0:
        return "highlighted", 0.75
    progress = doc["reading_progress"] or 0
    if progress >= 0.5:
        return "read", 0.5
    if doc["first_opened_at"] or progress > 0.02:
        return "opened", 0.25
    saved = _parse(doc["saved_at"]) or now
    if doc["location"] == "archive" or now - saved >= timedelta(days=resolve_after_days):
        return "ignored", 0.0
    return "pending", None


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def load_items(
    conn: sqlite3.Connection,
    discovery_store: str,
    noted_urls: set[str],
    resolve_after_days: int,
    now: datetime | None = None,
) -> list[StudyItem]:
    """Every discovery item that reached Reader (routed or probed), with its engagement."""
    now = now or datetime.now(UTC)
    disc = sqlite3.connect(f"file:{discovery_store}?mode=ro", uri=True)
    disc.row_factory = sqlite3.Row
    has_probe = any(r[1] == "probed_at" for r in disc.execute("PRAGMA table_info(items)"))
    if has_probe:
        query = (
            "SELECT url, title, description, score, probed_at FROM items WHERE status = 'kept' OR probed_at IS NOT NULL"
        )
    else:
        query = "SELECT url, title, description, score, NULL AS probed_at FROM items WHERE status = 'kept'"
    rows = disc.execute(query).fetchall()
    disc.close()

    docs: dict[str, sqlite3.Row] = {}
    for doc in conn.execute("SELECT * FROM reader_docs ORDER BY saved_at"):
        docs.setdefault(doc["url_norm"], doc)

    items = []
    for row in rows:
        key = normalize_url(row["url"])
        doc = docs.get(key)
        if doc is None:
            continue
        level, engagement = classify(doc, key in noted_urls, now, resolve_after_days)
        items.append(
            StudyItem(
                url_norm=key,
                title=row["title"],
                score=float(row["score"]),
                probe=row["probed_at"] is not None,
                saved_at=doc["saved_at"] or "",
                level=level,
                engagement=engagement,
                description=row["description"] or "",
            )
        )
    return items


def auc(pairs: list[tuple[float, bool]]) -> float | None:
    """Chance a random engaged item outscored a random unengaged one (ties count half)."""
    pos = [s for s, e in pairs if e]
    neg = [s for s, e in pairs if not e]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


BANDS = [(0.0, 0.4), (0.4, 0.6), (0.6, 0.75), (0.75, 0.85), (0.85, 1.01)]


def band_table(items: list[StudyItem]) -> list[dict]:
    out = []
    for lo, hi in BANDS:
        group = [i for i in items if i.resolved and lo <= i.score < hi]
        if not group:
            continue
        out.append(
            {
                "band": f"{lo:.2f}-{min(hi, 1.0):.2f}",
                "n": len(group),
                "engaged_pct": round(100 * sum(i.engagement >= ENGAGED for i in group) / len(group)),
                "mean_engagement": round(sum(i.engagement for i in group) / len(group), 2),
            }
        )
    return out


def summarize(items: list[StudyItem], rescores: dict[str, dict[str, float]] | None = None) -> dict:
    resolved = [i for i in items if i.resolved]
    routed = [i for i in resolved if not i.probe]
    probes = [i for i in resolved if i.probe]
    levels: dict[str, int] = {}
    for i in items:
        levels[i.level] = levels.get(i.level, 0) + 1

    def rate(group: list[StudyItem]) -> float | None:
        return round(100 * sum(i.engagement >= ENGAGED for i in group) / len(group)) if group else None

    raters = {"claude": auc([(i.score, i.engagement >= ENGAGED) for i in resolved])}
    for rater, scores in (rescores or {}).items():
        pairs = [(scores[i.url_norm], i.engagement >= ENGAGED) for i in resolved if i.url_norm in scores]
        raters[rater] = auc(pairs)
        raters[f"{rater}_n"] = len(pairs)

    return {
        "items": len(items),
        "resolved": len(resolved),
        "pending": levels.get("pending", 0),
        "levels": levels,
        "routed_engaged_pct": rate(routed),
        "probes_resolved": len(probes),
        "probe_engaged_pct": rate(probes),
        "auc": raters,
        "bands": band_table(resolved),
    }


def disagreements(items: list[StudyItem], since: datetime, limit: int = 3) -> list[tuple[str, StudyItem]]:
    """The week's sharpest splits between the model and Jamal, for writing prompts."""
    recent = [i for i in items if i.resolved and (_parse(i.saved_at) or since) >= since]
    loved_low = sorted((i for i in recent if i.engagement >= ENGAGED), key=lambda i: i.score)
    ignored_high = sorted((i for i in recent if i.engagement == 0), key=lambda i: -i.score)
    picks = []
    for a, b in zip_longest(loved_low, ignored_high):
        if a:
            picks.append(("you-loved-it", a))
        if b:
            picks.append(("model-loved-it", b))
    return picks[:limit]


def week_ago(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=7)
