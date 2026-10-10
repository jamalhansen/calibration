"""Status file for the dashboard's Writing practice card: today's prompt, streak, starters, reminders.

The dashboard reads this JSON rather than importing calib, the same way it reads
repo-health-latest.json.
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from local_first_common.obsidian import parse_frontmatter

from calib import art, predict, writing


def obsidian_link(vault_root: Path, note: Path) -> str:
    rel = note.relative_to(vault_root).with_suffix("").as_posix()
    return f"obsidian://open?vault={quote(vault_root.name)}&file={quote(rel)}"


def list_starters(starters_dir: Path, vault_root: Path, today: date) -> list[dict]:
    out = []
    for note in sorted(starters_dir.glob("*/*/*.md")):
        fm = parse_frontmatter(note)
        if str(fm.get("status", "")).lower() != "outline":
            continue
        ready = str(fm.get("ready_after") or "")[:10]
        _, thin = writing.thin_sections(note.read_text(encoding="utf-8"))
        out.append(
            {
                "title": str(fm.get("title") or note.stem),
                "group": note.parent.parent.name,
                "created": str(fm.get("created") or "")[:10],
                "ready_after": ready or None,
                "held": bool(ready) and ready > today.isoformat(),
                "sections_left": len(thin),
                "link": obsidian_link(vault_root, note),
            }
        )
    out.sort(key=lambda s: (s["held"], s["group"] != "from-building", s["created"]), reverse=False)
    return out


def list_drafts(blog_dir: Path, vault_root: Path, today: date) -> list[dict]:
    """Posts in progress for the dashboard: what he drafted but hasn't finished or published."""
    return [
        {
            "title": d.title,
            "status": d.status,
            "path": d.note.relative_to(blog_dir).as_posix(),
            "prose_words": d.prose_words,
            "thin_sections": d.thin_sections,
            "markers": d.markers,
            "days_since_edit": d.days_since_edit,
            "link": obsidian_link(vault_root, d.note),
        }
        for d in writing.list_drafts(blog_dir, today)
    ]


def recent_days(
    conn: sqlite3.Connection,
    today: date,
    threshold: int,
    n: int = 14,
    pages_words: dict[date, int] | None = None,
    pages_min: int = 50,
) -> list[dict]:
    days = []
    for i in range(n - 1, -1, -1):
        d = today - timedelta(days=i)
        row = conn.execute("SELECT * FROM writing_days WHERE day = ?", (d.isoformat(),)).fetchone()
        tracked = row is not None or d in (pages_words or {})
        days.append(
            {
                "day": d.isoformat(),
                "done": writing.day_done(conn, d, threshold, pages_words, pages_min),
                "tracked": tracked,
            }
        )
    return days


HEAT_LEVELS = (1, 100, 250, 500)  # words for levels 1-4; 0 words is level 0


def heatmap(
    conn: sqlite3.Connection,
    today: date,
    threshold: int,
    pages_words: dict[date, int],
    pages_min: int,
    weeks: int = 53,
) -> list[dict]:
    """GitHub-style year: one entry per day from a Sunday `weeks` back through today.

    Words are morning pages plus vault prose on days the prose tracker was running;
    a day marked done with no counted words still shows as level 1.
    """
    start = today - timedelta(days=(today.weekday() + 1) % 7 + 7 * (weeks - 1))
    rows = {r["day"]: r for r in conn.execute("SELECT * FROM writing_days WHERE day >= ?", (start.isoformat(),))}
    out = []
    d = start
    while d <= today:
        row = rows.get(d.isoformat())
        prose = max(0, row["last_total"] - row["baseline"]) if row else 0
        pages = pages_words.get(d, 0)
        words = prose + pages
        done = writing.day_done(conn, d, threshold, pages_words, pages_min)
        level = sum(words >= cut for cut in HEAT_LEVELS) or (1 if done else 0)
        out.append({"day": d.isoformat(), "words": words, "pages": pages, "done": done, "level": level})
        d += timedelta(days=1)
    return out


def build(
    conn: sqlite3.Connection,
    today: date,
    *,
    words_today: int,
    done: bool,
    prompt: str,
    threshold: int,
    starters_dir: Path,
    vault_root: Path,
    art_dir: art.ArtDirs,
    pages_words: dict[date, int] | None = None,
    art_experiment_start: date | None = None,
    pages_min: int = 50,
) -> dict:
    pages_words = pages_words or {}
    due = [dict(r) for r in predict.open_predictions(conn) if r["due"] <= today.isoformat() and not r["post"]]
    return {
        "generated": datetime.now().astimezone().isoformat(timespec="minutes"),
        "today": {
            "done": done,
            "words": words_today,
            "threshold": threshold,
            "prompt": prompt,
            "pages_words": pages_words.get(today, 0),
            "pages_min": pages_min,
            "streak": writing.streak(conn, today, threshold, pages_words, pages_min),
        },
        "days": recent_days(conn, today, threshold, pages_words=pages_words, pages_min=pages_min),
        "heatmap": heatmap(conn, today, threshold, pages_words, pages_min),
        "starters": list_starters(starters_dir, vault_root, today),
        "drafts": list_drafts(vault_root / "blog", vault_root, today),
        "art_experiment": art.by_artist(art.load_items(art_dir), art_experiment_start) if art_experiment_start else {},
        "reminders": {
            "art_unrated": sum(i.human_score is None for i in art.load_items(art_dir)),
            "predictions_due": len(due),
        },
    }


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
