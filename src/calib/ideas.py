"""Post starters grown from Jamal's own morning pages.

A starter that begins from a sentence he already wrote is easier to continue than one
built from someone else's article, which is why the from-reading starters were hard to
start on (2026-09-30). The model only proposes; every idea must quote a sentence that
appears verbatim in the pages, so it can't put words in his mouth.
"""

import re
from datetime import date, timedelta
from pathlib import Path

import yaml
from local_first_common.providers.base import BaseProvider
from pydantic import BaseModel, Field

from calib.pages import word_count

MAX_IDEAS = 3


class Section(BaseModel):
    heading: str = Field(..., description="A section heading for the post")
    prompt: str = Field(..., description="One short question, in the writer's own terms, to write this section from")


class Idea(BaseModel):
    title: str = Field(..., description="Working post title")
    quote: str = Field(..., description="The single sentence from the pages this idea grows from, copied exactly")
    why: str = Field(..., description="One sentence: why this is worth a post")
    sections: list[Section] = Field(..., description="2 to 4 sections")


class PagesIdeas(BaseModel):
    ideas: list[Idea] = Field(..., description=f"At most {MAX_IDEAS}; empty if nothing is a real post idea")


SYSTEM = f"""You read a writer's private morning pages -- fast, unedited, stream-of-consciousness
journaling -- and find the ideas in them that could become blog posts.

Rules:
- Only ideas the writer actually expressed or circled around. Don't invent topics or
  import your own; the point is to hand his own thinking back to him.
- For each idea, `quote` must be one sentence copied character-for-character from the
  pages. Ideas without an exact quote are discarded.
- Sections are prompts, not prose: short questions he can answer in 10 minutes each,
  phrased the way he'd phrase them.
- At most {MAX_IDEAS} ideas, best first. Returning none is a normal, good outcome when
  the pages are venting, logistics, or too thin -- don't stretch.
- Never put private details about other people (names, family, health, work conflicts)
  into titles, reasons, or prompts."""


def gather(pages: dict[date, str], today: date, days: int = 7, min_words: int = 50) -> list[tuple[date, str]]:
    """The last `days` days of pages worth reading (a full-length session, not a stub)."""
    since = today - timedelta(days=days)
    return sorted((d, t) for d, t in pages.items() if since <= d <= today and word_count(t) >= min_words)


def build_user(entries: list[tuple[date, str]]) -> str:
    return "\n\n".join(f"## {d.isoformat()}\n{text}" for d, text in entries)


def _norm(s: str) -> str:
    return " ".join(s.split()).strip(" \"'“”‘’").rstrip(".!?").lower()


def source_day(quote: str, entries: list[tuple[date, str]]) -> date | None:
    """The day whose pages contain `quote` verbatim (whitespace/case-insensitive), else None."""
    q = _norm(quote)
    if len(q.split()) < 4:
        return None
    for d, text in entries:
        if q in _norm(text):
            return d
    return None


def extract(provider: BaseProvider, entries: list[tuple[date, str]]) -> list[tuple[Idea, date]]:
    if not entries:
        return []
    result = provider.complete(SYSTEM, build_user(entries), response_model=PagesIdeas)
    kept = []
    for idea in result.ideas[:MAX_IDEAS]:
        day = source_day(idea.quote, entries)
        if day is not None and idea.sections:
            kept.append((idea, day))
    return kept


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")


def render_starter(idea: Idea, day: date, today: date) -> str:
    slug = slugify(idea.title)
    # Same fields and order as templates/Blog Post.md; no body H1 (Hugo prints the title).
    fm = {
        "title": idea.title,
        "description": idea.why,
        "author": ["Jamal Hansen"],
        "tags": ["morning-pages"],
        "status": "outline",
        "created": today,
        "category": "[[Blog Post]]",
        "slug": slug,
        "source": f"morning pages {day.isoformat()}",
    }
    body = [f"> “{idea.quote.strip()}” (morning pages, {day.isoformat()})", ""]
    for s in idea.sections[:4]:
        body += [f"## {s.heading}", "", f"*{s.prompt}*", ""]
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + "\n".join(body)


def write_starter(idea: Idea, day: date, dest: Path, today: date) -> Path | None:
    """One folder per starter, like the other starter groups. Never overwrites."""
    slug = slugify(idea.title)
    if not slug:
        return None
    note = dest / slug / f"{slug}.md"
    if note.parent.exists():
        return None
    note.parent.mkdir(parents=True)
    note.write_text(render_starter(idea, day, today), encoding="utf-8")
    return note
