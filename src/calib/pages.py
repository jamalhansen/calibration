"""Morning pages: read from the `## ✍️ Morning Pages` callout in BrainSync's daily notes.

The daily notes are the record, so there's nothing to store: a day's word count is
recomputed from its note, and history back to the first note is available for free.
"""

import re
from datetime import date
from pathlib import Path

_HEADING_RE = re.compile(r"^##\s.*morning pages", re.IGNORECASE)
_DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")


def section_text(note_text: str) -> str:
    """The Morning Pages section's prose, with callout markers stripped."""
    lines, inside = [], False
    for raw in note_text.splitlines():
        if _HEADING_RE.match(raw):
            inside = True
            continue
        if inside and (raw.startswith("## ") or raw.strip() == "---"):
            break
        if inside:
            line = raw.lstrip()
            line = line[1:].lstrip() if line.startswith(">") else line
            if not line.startswith("[!"):
                lines.append(line)
    return "\n".join(lines).strip()


def word_count(text: str) -> int:
    return len(text.split())


def by_day(timeline_dir: Path) -> dict[date, str]:
    """Morning pages text for every daily note that has any."""
    out = {}
    if not timeline_dir.is_dir():
        return out
    for note in timeline_dir.iterdir():
        m = _DAY_RE.match(note.name)
        if not m:
            continue
        text = section_text(note.read_text(encoding="utf-8", errors="ignore"))
        if text:
            out[date.fromisoformat(m.group(1))] = text
    return out


def last_thought(text: str, min_words: int = 8, max_chars: int = 220) -> str | None:
    """Where the writer left off: the last complete sentence with some substance,
    or the trailing fragment if the pages stop mid-sentence."""
    flat = " ".join(text.split())
    sentences = [s.strip() for s in _SENTENCE_RE.findall(flat)]
    tail = flat[sum(len(s) for s in _SENTENCE_RE.findall(flat)) :].strip()
    candidates = ([tail] if word_count(tail) >= min_words else []) + sentences[::-1]
    for s in candidates:
        if word_count(s) >= min_words:
            return s if len(s) <= max_chars else s[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return None


def recent_quote(pages: dict[date, str], today: date, within_days: int = 3) -> tuple[date, str] | None:
    """The most recent earlier day's last thought, if it's recent enough to pick back up."""
    for day in sorted((d for d in pages if d < today), reverse=True):
        if (today - day).days > within_days:
            return None
        quote = last_thought(pages[day])
        if quote:
            return day, quote
    return None
