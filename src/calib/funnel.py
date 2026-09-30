"""Reading-to-writing yield: how much of what reaches Reader turns into notes, seeds, and posts.

Stages up to "noted" follow each item. Seeds and posts can't be traced to one
article, so they're counted per month beside it.
"""

from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

from local_first_common.obsidian import parse_frontmatter

from calib.study import StudyItem

STAGES = ["surfaced", "opened", "read", "highlighted", "noted"]
_DEPTH = {"pending": 0, "ignored": 0, "opened": 1, "read": 2, "highlighted": 3, "noted": 4}


def _month(value) -> str | None:
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m")
    s = str(value or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else None


def _created_month(path: Path) -> str | None:
    fm = parse_frontmatter(path)
    month = _month(fm.get("created") or fm.get("date"))
    if month:
        return month
    stat = path.stat()
    return datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_mtime), tz=UTC).astimezone().strftime("%Y-%m")


def build(items: list[StudyItem], seeds_dir: Path, blog_dir: Path) -> dict[str, dict[str, int]]:
    months: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in items:
        month = _month(item.saved_at)
        if not month:
            continue
        depth = _DEPTH[item.level]
        for i, stage in enumerate(STAGES):
            if i == 0 or depth >= i:
                months[month][stage] += 1
    for seed in seeds_dir.glob("*.md"):
        month = _created_month(seed)
        if month:
            months[month]["seeds"] += 1
    for note in blog_dir.rglob("*.md"):
        fm = parse_frontmatter(note)
        if str(fm.get("status", "")).lower() == "published":
            month = _month(fm.get("published_date") or fm.get("date"))
            if month:
                months[month]["posts"] += 1
    return {m: dict(v) for m, v in sorted(months.items())}
