"""The daily 10 minutes: did Jamal write today, and if not, what's today's prompt.

"Wrote today" is a word-count delta over his own prose folders against a
baseline taken at the day's first check (the 03:30 `calib daily` snapshot, or
failing that the previous day's last reading), or an explicit `calib write done`.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from local_first_common.obsidian import parse_frontmatter_text

THIN_SECTION_WORDS = 40
# A post in progress: left `outline`, not yet `published`. `editing` is what Jamal
# typed on 2026-10-10; the README says `draft`, so both count.
DRAFT_STATUSES = ("draft", "editing")
# Open work left in a draft: HTML-comment TODOs, Obsidian todo callouts, bare TODOs.
OPEN_MARKER_RE = re.compile(r"<!--\s*TODO|\[!todo\]|\bTODO\b", re.IGNORECASE)


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
    # HTML comments are notes to self (the TODO blocks in drafts), not prose.
    if not line or line.startswith(("#", ">", "|", "<!--")):
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
    conn: sqlite3.Connection,
    day: date,
    threshold: int,
    pages_words: dict[date, int] | None = None,
    pages_min: int = 50,
) -> bool:
    """A day counts for vault prose over `threshold`, a manual mark, or `pages_min` words of morning pages."""
    return _done(_row(conn, day), threshold) or (pages_words or {}).get(day, 0) >= pages_min


def streak(
    conn: sqlite3.Connection,
    today: date,
    threshold: int,
    pages_words: dict[date, int] | None = None,
    pages_min: int = 50,
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
    words: int = 0


def section_words(text: str) -> tuple[str, list[tuple[str, int]]]:
    """(post title, [(heading, prose words)] for every '## ' section), ignoring fenced code.

    Bullets, italic prompts and quotes are notes, not prose: a section of bullets is still unwritten.
    The title comes from frontmatter; a body H1 is accepted for notes that still carry one.
    """
    fm, body = parse_frontmatter_text(text)
    title, sections, current, words, in_fence = str(fm.get("title") or ""), [], None, 0, False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            if current is not None:
                sections.append((current, words))
            current, words = line[3:].strip(), 0
        elif current is not None:
            words += _line_prose_words(line, include_bullets=False)
    if current is not None:
        sections.append((current, words))
    return title, sections


def thin_sections(text: str) -> tuple[str, list[str]]:
    """(post title, headings of '## ' sections with little prose)."""
    title, sections = section_words(text)
    return title, [h for h, w in sections if w < THIN_SECTION_WORDS]


def _is_blog_post(fm: dict) -> bool:
    return "blog post" in str(fm.get("category", "")).lower()


def _ready(fm: dict, today: date) -> bool:
    ready = fm.get("ready_after")
    return not (ready and str(ready)[:10] > today.isoformat())


def prompt_sections(blog_dir: Path, recent: int = 3, today: date | None = None) -> list[Section]:
    """Thin sections from the notes with the most momentum: drafts first, then outlines, newest edit first.

    Until 2026-10-10 only `status: outline` notes were offered, so a starter dropped out of the
    daily prompt the moment it became a draft -- with its empty sections still empty.
    Notes with a future `ready_after` date are waiting on data and are skipped.
    """
    today = today or date.today()  # noqa: DTZ011 - local calendar date is the intent
    drafts, outlines = [], []
    for path in blog_dir.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter_text(text)
        status = str(fm.get("status", "")).lower()
        if status in DRAFT_STATUSES:
            bucket = drafts
        elif status == "outline":
            bucket = outlines
        else:
            continue
        if not _ready(fm, today):
            continue
        bucket.append((path.stat().st_mtime, path, text))
    newest_first = sorted(drafts, key=lambda t: t[0], reverse=True) + sorted(outlines, key=lambda t: t[0], reverse=True)
    out = []
    for _, path, text in newest_first[:recent]:
        title, sections = section_words(text)
        out += [Section(path, title or path.stem, h, w) for h, w in sections if w < THIN_SECTION_WORDS]
    return out


@dataclass
class Draft:
    note: Path
    title: str
    status: str
    prose_words: int
    thin_sections: int
    markers: int
    days_since_edit: int


def list_drafts(blog_dir: Path, today: date | None = None) -> list[Draft]:
    """Posts in progress under blog/: drafts and editing posts, plus outlines he has started writing in.

    Answers "which starters did I draft but never finish or publish?" Published and reference
    notes are left out. Most recently touched first.
    """
    today = today or date.today()  # noqa: DTZ011 - local calendar date is the intent
    out = []
    for path in blog_dir.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = parse_frontmatter_text(text)
        if not _is_blog_post(fm):
            continue
        status = str(fm.get("status", "")).lower()
        words = prose_words(text, starter="starters" in path.relative_to(blog_dir).parts)
        if status not in DRAFT_STATUSES and not (status == "outline" and words > 0):
            continue
        title, sections = section_words(text)
        edited = datetime.fromtimestamp(path.stat().st_mtime).astimezone().date()
        out.append(
            Draft(
                note=path,
                title=title or path.stem,
                status=status,
                prose_words=words,
                thin_sections=sum(w < THIN_SECTION_WORDS for _, w in sections),
                markers=len(OPEN_MARKER_RE.findall(body)),
                days_since_edit=max(0, (today - edited).days),
            )
        )
    return sorted(out, key=lambda d: (d.days_since_edit, str(d.note)))


def pick_prompt(
    today: date,
    digest_prompts: list[str],
    sections: list[Section],
    own_words: tuple[date, str] | None = None,
    pages_done: bool = False,
) -> str:
    """Picking up your own last thought comes first: a sentence you already started is
    easier to continue than any skeleton. Once today's morning pages are done, the next
    step is the thinnest section of the newest draft -- that's the last mile nothing
    else nudges."""
    if pages_done and sections:
        newest = [s for s in sections if s.note == sections[0].note]
        s = min(newest, key=lambda x: x.words)
        return f"Pages done. One section: “{s.heading}” in {s.title} ({s.note.name})."
    if own_words and not pages_done:
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
