"""Post starters: an outline skeleton per writing idea, so a 10-minute session starts from a section, not a blank page.

Each starter is `<starters>/<group>/<slug>/<slug>.md` with `status: outline`, which keeps it
out of blog-validate's executed drafts and puts its sections into `calib write` prompts.
"""

import re
from datetime import date
from pathlib import Path

from calib.study import StudyItem


def slugify(title: str, max_words: int = 8) -> str:
    words = re.sub(r"[^a-z0-9\s-]", "", title.lower()).split()
    return "-".join(words[:max_words]) or "untitled"


_SECTIONS = {
    "you-loved-it": [
        (
            "The hook",
            "The model scored this {score:.2f}. I {level} it anyway. Start with the moment you decided it was worth your time.",
        ),
        ("What the piece says", "Two sentences, in your words, plus the link."),
        (
            "Why it landed for me",
            "What in your work or head made this matter? Be specific: a project, a question you were already carrying.",
        ),
        (
            "What the model couldn't see",
            "Relevance to a profile is not the same as interest. Name the gap this item exposes.",
        ),
        ("Takeaway", "One line a reader can use, about the topic or about filtering what you read."),
    ],
    "model-loved-it": [
        (
            "The hook",
            "The model scored this {score:.2f} and I never opened it. Start with whether you'd have predicted that.",
        ),
        ("What the piece promised", "Title and summary, as the model saw them."),
        ("Why I skipped it", "Honest answer: wrong week, already knew it, looked like hype, or something else?"),
        ("Who was wrong", "Read it now. Was the model right and you were busy, or was the model wrong? Say which."),
        ("Takeaway", "One line about what a relevance score can and can't know about you."),
    ],
}


def disagreement_starter(kind: str, item: StudyItem, today: date) -> tuple[str, str]:
    """(slug, markdown) for one digest pick."""
    slug = slugify(item.title)
    year, week, _ = today.isocalendar()
    # Same fields and order as templates/Blog Post.md; no body H1 (Hugo prints the title).
    description = (item.description or "").strip().replace(chr(34), chr(39))
    lines = [
        "---",
        f'title: "{item.title.replace(chr(34), chr(39))}"',
        f'description: "{description}"',
        "author:",
        "- Jamal Hansen",
        "tags: []",
        "status: outline",
        f"created: {today.isoformat()}",
        "category: '[[Blog Post]]'",
        f"slug: {slug}",
        f"origin: calib digest {year}-W{week:02d} ({kind})",
        f"inspired_by: {item.url_norm}",
        "---",
        "",
        (
            f"> Starter from the calibration study. Model score {item.score:.2f}; you: {item.level}"
            f"{'; this was a blind probe the model had rejected' if item.probe else ''}. "
            "Retitle it once you know your angle."
        ),
        "",
    ]
    for heading, prompt in _SECTIONS[kind]:
        lines += [f"## {heading}", "", f"*{prompt.format(score=item.score, level=item.level)}*", ""]
    return slug, "\n".join(lines)


def write_starter(group_dir: Path, slug: str, text: str) -> Path | None:
    """Write a starter unless one with that slug exists (never overwrite his writing)."""
    path = group_dir / slug / f"{slug}.md"
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
