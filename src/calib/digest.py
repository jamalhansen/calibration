"""Weekly disagreement digest: the items where Jamal and the model split hardest, as writing prompts."""

from datetime import date
from pathlib import Path

from calib.starters import slugify
from calib.study import StudyItem

_QUESTION = {
    "you-loved-it": "The model scored this {score:.2f} and you {level} it. What did it miss about why this mattered to you?",
    "model-loved-it": "The model scored this {score:.2f} and you never opened it. Was the model wrong, or were you?",
}


def digest_path(prompts_dir: Path, today: date) -> Path:
    year, week, _ = today.isocalendar()
    return prompts_dir / f"{year}-W{week:02d}-disagreements.md"


def render(picks: list[tuple[str, StudyItem]], today: date) -> str:
    year, week, _ = today.isocalendar()
    lines = [
        "---",
        "category: '[[Meta]]'",
        "status: reference",
        "tags:",
        "- calibration",
        "- writing-prompt",
        "source: calib digest",
        f"week: {year}-W{week:02d}",
        f"created: {today.isoformat()}",
        "---",
        "",
        f"# Where the model and I disagreed ({year}-W{week:02d})",
        "",
    ]
    if not picks:
        lines.append("No sharp disagreements this week.")
    for kind, item in picks:
        slug = slugify(item.title)
        lines += [
            f"## {item.title}",
            "",
            f"- Starter: [[{slug}]]",
            f"- {'Probe (model rejected it)' if item.probe else 'Routed'}; model score {item.score:.2f}; you: {item.level}",
            f"- {item.url_norm}",
            "",
            _QUESTION[kind].format(score=item.score, level=item.level),
            "",
        ]
    return "\n".join(lines)


def prompts_from_digest(path: Path) -> list[str]:
    """The '## ' headings of a digest, one writing prompt each."""
    if not path.exists():
        return []
    return [line[3:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
