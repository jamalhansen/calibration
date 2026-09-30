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
        out.append({
            "title": str(fm.get("title") or note.stem),
            "group": note.parent.parent.name,
            "created": str(fm.get("created") or "")[:10],
            "ready_after": ready or None,
            "held": bool(ready) and ready > today.isoformat(),
            "sections_left": len(thin),
            "link": obsidian_link(vault_root, note),
        })
    out.sort(key=lambda s: (s["held"], s["group"] != "from-building", s["created"]), reverse=False)
    return out


def recent_days(conn: sqlite3.Connection, today: date, threshold: int, n: int = 14) -> list[dict]:
    days = []
    for i in range(n - 1, -1, -1):
        d = today - timedelta(days=i)
        row = conn.execute("SELECT * FROM writing_days WHERE day = ?", (d.isoformat(),)).fetchone()
        days.append({"day": d.isoformat(), "done": writing._done(row, threshold), "tracked": row is not None})
    return days


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
    art_dir: Path,
) -> dict:
    due = [dict(r) for r in predict.open_predictions(conn) if r["due"] <= today.isoformat() and not r["post"]]
    return {
        "generated": datetime.now().astimezone().isoformat(timespec="minutes"),
        "today": {
            "done": done,
            "words": words_today,
            "threshold": threshold,
            "prompt": prompt,
            "streak": writing.streak(conn, today, threshold),
        },
        "days": recent_days(conn, today, threshold),
        "starters": list_starters(starters_dir, vault_root, today),
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
