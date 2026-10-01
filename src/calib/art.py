"""Human scores for artist-agent's daily pieces, against the agent's own self-score.

Ratings are 1-5 stars, stored as human_score on the item's 0-1 scale
((stars - 1) / 4) so they compare directly with self_score.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from local_first_common.obsidian import parse_frontmatter, split_frontmatter

_NOTES_RE = re.compile(r"^\*\*Human notes:\*\*.*$", re.MULTILINE)


@dataclass
class ArtItem:
    path: Path
    image: Path
    title: str
    interest: str
    self_score: float | None
    human_score: float | None
    artist: str = ""
    generated: str = ""


ArtDirs = Path | dict[str, Path]


def _dirs(art_dirs: ArtDirs) -> dict[str, Path]:
    """One folder (artist named after it) or {artist name: folder}, as of the 2026-10-01 two-artist experiment."""
    return art_dirs if isinstance(art_dirs, dict) else {art_dirs.name: art_dirs}


def load_items(art_dirs: ArtDirs) -> list[ArtItem]:
    items = []
    for name, art_dir in _dirs(art_dirs).items():
        for path in sorted((art_dir / "items").glob("*.md"), reverse=True):
            fm = parse_frontmatter(path)
            items.append(ArtItem(
                path=path,
                image=art_dir / "images" / f"{path.stem}.png",
                title=str(fm.get("title", path.stem)),
                interest=str(fm.get("interest", "")),
                self_score=_float(fm.get("self_score")),
                human_score=_legacy_scale(_float(fm.get("human_score"))),
                artist=str(fm.get("artist") or name),
                generated=str(fm.get("generated_at") or path.stem)[:10],
            ))
    items.sort(key=lambda i: (i.generated, i.path.name), reverse=True)
    return items


def blind_order(items: list[ArtItem]) -> list[ArtItem]:
    """Newest days first, but within a day the order comes from a hash of the filename,
    so a piece's position never says which artist made it."""
    return sorted(items, key=lambda i: (i.generated, hashlib.sha256(i.path.name.encode()).hexdigest()), reverse=True)


def by_artist(items: list[ArtItem], since: date | None = None) -> dict[str, dict]:
    """Per artist since the experiment started: pieces made, rated, and your mean stars."""
    out: dict[str, dict] = {}
    for i in items:
        if since and i.generated < since.isoformat():
            continue
        a = out.setdefault(i.artist, {"pieces": 0, "rated": 0, "_human": [], "_self": []})
        a["pieces"] += 1
        if i.self_score is not None:
            a["_self"].append(i.self_score)
        if i.human_score is not None:
            a["rated"] += 1
            a["_human"].append(i.human_score)
    for a in out.values():
        h, s = a.pop("_human"), a.pop("_self")
        a["mean_stars"] = round(1 + 4 * sum(h) / len(h), 2) if h else None
        a["mean_self_stars"] = round(1 + 4 * sum(s) / len(s), 2) if s else None
    return out


def _legacy_scale(value: float | None) -> float | None:
    """Scores typed by hand before `calib art rate` existed were out of 10 ("7.5")."""
    return value / 10 if value is not None and value > 1 else value


def _float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def stars_to_score(stars: int) -> float:
    if stars not in range(1, 6):
        raise ValueError("rating must be 1-5")
    return (stars - 1) / 4


def _set_field(frontmatter: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pattern.search(frontmatter):
        return pattern.sub(f"{key}: {value}", frontmatter, count=1)
    return frontmatter.rstrip("\n") + f"\n{key}: {value}\n"


def rate(path: Path, stars: int, note: str | None = None) -> float:
    score = stars_to_score(stars)
    text = path.read_text(encoding="utf-8")
    parts = split_frontmatter(text)
    if parts is None:
        raise ValueError(f"{path.name} has no frontmatter")
    frontmatter, body = parts
    frontmatter = _set_field(frontmatter, "human_score", f"{score:g}")
    frontmatter = _set_field(frontmatter, "status", "reviewed")
    if note:
        body = _NOTES_RE.sub(lambda _: f"**Human notes:** {note} ({stars}/5)", body, count=1)
    path.write_text(f"---\n{frontmatter.strip()}\n---\n{body}", encoding="utf-8")
    return score


def resolve_item(art_dirs: ArtDirs, ref: str) -> Path:
    """Accept a path, a filename, or a unique fragment of one, across every artist's folder."""
    p = Path(ref).expanduser()
    if p.is_file():
        return p
    matches = [i for d in _dirs(art_dirs).values() for i in (d / "items").glob("*.md") if ref in i.name]
    if len(matches) != 1:
        raise LookupError(f"{len(matches)} items match {ref!r}; be more specific")
    return matches[0]


def stats(items: list[ArtItem]) -> dict:
    both = [(i.self_score, i.human_score) for i in items if i.self_score is not None and i.human_score is not None]
    n = len(both)
    if n == 0:
        return {"rated": 0, "unrated": sum(i.human_score is None for i in items)}
    mean_gap = sum(s - h for s, h in both) / n
    return {
        "rated": n,
        "unrated": sum(i.human_score is None for i in items),
        "mean_self": round(sum(s for s, _ in both) / n, 2),
        "mean_human": round(sum(h for _, h in both) / n, 2),
        "mean_gap_self_minus_human": round(mean_gap, 2),
        "correlation": _pearson(both),
    }


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    n = len(pairs)
    if n < 3:
        return None
    xs, ys = zip(*pairs, strict=True)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy), 2)
