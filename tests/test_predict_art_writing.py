from datetime import date

import pytest

from calib import art, digest, funnel, predict, study, writing


def test_predictions_brier_and_buckets(conn):
    a = predict.add(conn, "ships", 0.8, date(2026, 10, 1))
    b = predict.add(conn, "slips", 0.3, date(2026, 10, 1))
    predict.resolve(conn, a, True)
    predict.resolve(conn, b, True)
    s = predict.score(conn)
    assert s["n"] == 2
    assert s["brier"] == round(((0.8 - 1) ** 2 + (0.3 - 1) ** 2) / 2, 3)
    assert {x["said"] for x in s["buckets"]} == {"80-100%", "20-40%"}
    with pytest.raises(ValueError):
        predict.add(conn, "bad", 1.5, date(2026, 10, 1))
    with pytest.raises(KeyError):
        predict.resolve(conn, 999, True)


def _post(dirpath, name, status, published=None):
    dirpath.mkdir(parents=True, exist_ok=True)
    fm = f"status: {status}\n" + (f"published_date: {published}\n" if published else "")
    (dirpath / f"{name}.md").write_text(f"---\n{fm}---\n# T\n")


def test_auto_resolve_post_predictions(conn, tmp_path):
    blog = tmp_path / "BrainSync" / "blog" / "series" / "s" / "posts"
    _post(blog, "03-csv", "published", "2026-10-02")
    _post(blog, "04-late", "outline")
    yes = predict.add(conn, "csv ships", 0.7, date(2026, 10, 3), post="03-csv")
    late = predict.add(conn, "late ships", 0.7, date(2026, 10, 3), post="04-late")
    waiting = predict.add(conn, "late ships soon", 0.7, date(2026, 10, 30), post="04-late")
    got = dict(predict.auto_resolve(conn, tmp_path / "BrainSync", date(2026, 10, 5)))
    assert got == {yes: True, late: False}
    assert [r["id"] for r in predict.open_predictions(conn)] == [waiting]


ITEM = """---
human_score: null
self_score: 0.35
status: new
title: A subway
interest: Synesthetic wireframe
---

![x](../images/2026-09-27-a-subway.png)

**Human notes:** _not yet reviewed_
"""


def test_art_rate_and_stats(tmp_path):
    items_dir = tmp_path / "items"
    items_dir.mkdir()
    for i, self_score in enumerate([0.35, 0.6, 0.1]):
        (items_dir / f"2026-09-2{i}-piece.md").write_text(ITEM.replace("0.35", str(self_score)))
    path = art.resolve_item(tmp_path, "2026-09-20")
    assert art.rate(path, 4, note="the colors") == 0.75
    text = path.read_text()
    assert "human_score: 0.75" in text and "status: reviewed" in text
    assert "**Human notes:** the colors (4/5)" in text
    art.rate(art.resolve_item(tmp_path, "2026-09-21"), 5)
    art.rate(art.resolve_item(tmp_path, "2026-09-22"), 1)
    s = art.stats(art.load_items(tmp_path))
    assert s["rated"] == 3 and s["unrated"] == 0
    assert s["correlation"] is not None
    legacy = items_dir / "2026-09-11-legacy.md"
    legacy.write_text(ITEM.replace("human_score: null", 'human_score: "7.5"'))
    assert next(i for i in art.load_items(tmp_path) if i.path == legacy).human_score == 0.75
    with pytest.raises(ValueError):
        art.stars_to_score(6)
    with pytest.raises(LookupError):
        art.resolve_item(tmp_path, "2026-09-2")


def test_writing_observe_streak_and_done(conn):
    d1, d2, d3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)
    assert writing.observe(conn, d1, 1000) == 0
    assert writing.observe(conn, d1, 1150) == 150
    assert writing.observe(conn, d2, 1200) == 50
    assert writing.streak(conn, d2, 100) == 1
    writing.mark_done(conn, d2, 1200)
    assert writing.streak(conn, d2, 100) == 2
    assert writing.observe(conn, d3, 1200) == 0
    assert writing.streak(conn, d3, 100) == 2


OUTLINE = """---
status: outline
---
# Why Your CSV Is Lying

## Question Hook

## The Problem
""" + " ".join(["word"] * 50) + """

## The Data
```python
# Convert the CSVs
## not a heading
```
"""


def test_thin_sections_skip_fences_and_full_sections():
    title, sections = writing.thin_sections(OUTLINE)
    assert title == "Why Your CSV Is Lying"
    assert sections == ["Question Hook", "The Data"]


def test_pick_prompt_alternates(tmp_path):
    sec = [writing.Section(tmp_path / "post.md", "Post", "Hook")]
    even, odd = date(2026, 10, 3), date(2026, 10, 2)
    assert even.toordinal() % 2 == 0
    assert "disagreement" in writing.pick_prompt(even, ["A title"], sec)
    assert "Hook" in writing.pick_prompt(odd, ["A title"], sec)
    assert "Hook" in writing.pick_prompt(even, [], sec)
    assert "seed" in writing.pick_prompt(even, [], [])


def test_digest_round_trip(tmp_path):
    item = study.StudyItem("https://x.com/a", "A great post", 0.2, True, "2026-09-28", "noted", 1.0)
    text = digest.render([("you-loved-it", item)], date(2026, 9, 29))
    path = digest.digest_path(tmp_path, date(2026, 9, 29))
    assert path.name == "2026-W40-disagreements.md"
    path.write_text(text)
    assert digest.prompts_from_digest(path) == ["A great post"]
    assert "Probe (model rejected it)" in text


def test_funnel_counts_stages_seeds_posts(tmp_path):
    items = [
        study.StudyItem("a", "a", 0.9, False, "2026-09-03", "noted", 1.0),
        study.StudyItem("b", "b", 0.9, False, "2026-09-04", "opened", 0.25),
        study.StudyItem("c", "c", 0.9, False, "2026-09-05", "ignored", 0.0),
    ]
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "s.md").write_text("---\ncreated: 2026-09-10\n---\nx")
    blog = tmp_path / "blog"
    _post(blog, "p", "published", "2026-09-12")
    got = funnel.build(items, seeds, blog)["2026-09"]
    assert got == {"surfaced": 3, "opened": 2, "read": 1, "highlighted": 1, "noted": 1, "seeds": 1, "posts": 1}


def test_disagreement_starter_is_an_outline_and_never_overwrites(tmp_path):
    from calib import starters

    item = study.StudyItem("https://x.com/a", 'How to "Write" with an LLM', 0.75, False, "2026-09-28", "noted", 1.0)
    slug, text = starters.disagreement_starter("you-loved-it", item, date(2026, 9, 29))
    assert slug == "how-to-write-with-an-llm"
    assert "status: outline" in text and "inspired_by: https://x.com/a" in text
    _, sections = writing.thin_sections(text)
    assert sections[0] == "The hook" and len(sections) == 5
    path = starters.write_starter(tmp_path, slug, text)
    assert path == tmp_path / slug / f"{slug}.md"
    path.write_text("my own words")
    assert starters.write_starter(tmp_path, slug, text) is None
    assert path.read_text() == "my own words"


def test_outline_sections_skip_not_ready(tmp_path):
    (tmp_path / "a.md").write_text(OUTLINE)
    (tmp_path / "b.md").write_text(OUTLINE.replace("status: outline", "status: outline\nready_after: 2026-11-01"))
    notes = {s.note.name for s in writing.outline_sections(tmp_path, today=date(2026, 10, 1))}
    assert notes == {"a.md"}
    notes = {s.note.name for s in writing.outline_sections(tmp_path, today=date(2026, 11, 2))}
    assert notes == {"a.md", "b.md"}
