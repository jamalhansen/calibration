"""The daily 10 minutes: did Jamal write today, and if not, what's today's prompt.

"Wrote today" is a word-count delta over his own prose folders against a
baseline taken at the day's first check (the 03:30 `calib daily` snapshot, or
failing that the previous day's last reading), or an explicit `calib write done`.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from local_first_common.obsidian import parse_frontmatter_text

THIN_SECTION_WORDS = 40


def prose_words(text: str, starter: bool = False) -> int:
    """Words of prose only: generated skeletons (headings, italic prompts, fact bullets) don't count as writing.

    Reference notes (the weekly digest, READMEs) count as zero.
    """
    fm, body = parse_frontmatter_text(text)
    if str(fm.get("status", "")).lower() == "reference":
        return 0
    words, in_fence = 0, False
    for raw in body.splitlines():
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            words += _line_prose_words(raw, include_bullets=not starter)
    return words


def _line_prose_words(raw: str, include_bullets: bool) -> int:
    line = raw.strip()
    if not line or line.startswith(("#", ">", "|")):
        return 0
    if line.startswith("*") and line.endswith("*") and not line.startswith("* "):
        return 0
    if not include_bullets and line.startswith(("- ", "* ", "1. ")):
        return 0
    return len(line.split())


def count_words(dirs: list[Path]) -> int:
    total = 0
    for d in dirs:
        for path in d.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            total += prose_words(text, starter="starters" in path.relative_to(d).parts)
    return total


def _row(conn: sqlite3.Connection, day: date) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM writing_days WHERE day = ?", (day.isoformat(),)).fetchone()


def observe(conn: sqlite3.Connection, day: date, total: int) -> int:
    """Record today's reading and return words written today."""
    row = _row(conn, day)
    if row is None:
        prev = conn.execute(
            "SELECT last_total FROM writing_days WHERE day < ? ORDER BY day DESC LIMIT 1", (day.isoformat(),)
        ).fetchone()
        baseline = prev["last_total"] if prev else total
        conn.execute(
            "INSERT INTO writing_days(day, baseline, last_total) VALUES (?, ?, ?)",
            (day.isoformat(), baseline, total),
        )
    else:
        baseline = row["baseline"]
        conn.execute("UPDATE writing_days SET last_total = ? WHERE day = ?", (total, day.isoformat()))
    conn.commit()
    return max(0, total - baseline)


def mark_done(conn: sqlite3.Connection, day: date, total: int) -> None:
    observe(conn, day, total)
    conn.execute("UPDATE writing_days SET marked_done = 1 WHERE day = ?", (day.isoformat(),))
    conn.commit()


def _done(row: sqlite3.Row | None, threshold: int) -> bool:
    return bool(row) and (row["marked_done"] or row["last_total"] - row["baseline"] >= threshold)


def day_done(
    conn: sqlite3.Connection, day: date, threshold: int,
    pages_words: dict[date, int] | None = None, pages_min: int = 50,
) -> bool:
    """A day counts for vault prose over `threshold`, a manual mark, or `pages_min` words of morning pages."""
    return _done(_row(conn, day), threshold) or (pages_words or {}).get(day, 0) >= pages_min


def streak(
    conn: sqlite3.Connection, today: date, threshold: int,
    pages_words: dict[date, int] | None = None, pages_min: int = 50,
) -> int:
    def done(d: date) -> bool:
        return day_done(conn, d, threshold, pages_words, pages_min)

    day = today if done(today) else today - timedelta(days=1)
    n = 0
    while done(day):
        n += 1
        day -= timedelta(days=1)
    return n


@dataclass
class Section:
    note: Path
    title: str
    heading: str


def thin_sections(text: str) -> tuple[str, list[str]]:
    """(post title, headings of '## ' sections with little prose), ignoring fenced code.

    Bullets, italic prompts and quotes are notes, not prose: a section of bullets is still unwritten.
    """
    _, body = parse_frontmatter_text(text)
    title, sections, current, words, in_fence = "", [], None, 0, False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            if current is not None and words < THIN_SECTION_WORDS:
                sections.append(current)
            current, words = line[3:].strip(), 0
        elif current is not None:
            words += _line_prose_words(line, include_bullets=False)
    if current is not None and words < THIN_SECTION_WORDS:
        sections.append(current)
    return title, sections


def outline_sections(blog_dir: Path, recent: int = 3, today: date | None = None) -> list[Section]:
    """Thin sections from the most recently touched outlines: that's where the momentum is.

    Outlines with a future `ready_after` date are waiting on data and are skipped.
    """
    today = today or date.today()  # noqa: DTZ011 - local calendar date is the intent
    outlines = []
    for path in blog_dir.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter_text(text)
        if str(fm.get("status", "")).lower() != "outline":
            continue
        ready = fm.get("ready_after")
        if ready and str(ready)[:10] > today.isoformat():
            continue
        outlines.append((path.stat().st_mtime, path, text))
    out = []
    for _, path, text in sorted(outlines, key=lambda t: t[0], reverse=True)[:recent]:
        title, headings = thin_sections(text)
        out += [Section(path, title or path.stem, h) for h in headings]
    return out


def pick_prompt(
    today: date, digest_prompts: list[str], sections: list[Section],
    own_words: tuple[date, str] | None = None,
) -> str:
    """Picking up your own last thought comes first: a sentence you already started is
    easier to continue than any skeleton."""
    if own_words:
        day, quote = own_words
        when = "Yesterday" if (today - day).days == 1 else day.strftime("On %A")
        return f"{when} you wrote: “{quote}” Keep going."
    n = today.toordinal()
    if digest_prompts and (n % 2 == 0 or not sections):
        title = digest_prompts[(n // 2) % len(digest_prompts)]
        return f"150 words on why you and the model split on “{title}” (this week's disagreement digest)."
    if sections:
        s = sections[n % len(sections)]
        return f"One section: “{s.heading}” in {s.title} ({s.note.name})."
    return "150 words on any seed in Contexta/seeds."
