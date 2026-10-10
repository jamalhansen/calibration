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


OUTLINE = (
    """---
status: outline
---
# Why Your CSV Is Lying

## Question Hook

## The Problem
"""
    + " ".join(["word"] * 50)
    + """

## The Data
```python
# Convert the CSVs
## not a heading
```
"""
)


def test_thin_sections_skip_fences_and_full_sections():
    title, sections = writing.thin_sections(OUTLINE)
    assert title == "Why Your CSV Is Lying"
    assert sections == ["Question Hook", "The Data"]


def test_pick_prompt_alternates(tmp_path):
    sec = [writing.Section(tmp_path / "post.md", "Post", "Hook", 0)]
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
    assert path is not None
    path.write_text("my own words")
    assert starters.write_starter(tmp_path, slug, text) is None
    assert path.read_text() == "my own words"


def test_prompt_sections_skip_not_ready(tmp_path):
    (tmp_path / "a.md").write_text(OUTLINE)
    (tmp_path / "b.md").write_text(OUTLINE.replace("status: outline", "status: outline\nready_after: 2026-11-01"))
    notes = {s.note.name for s in writing.prompt_sections(tmp_path, today=date(2026, 10, 1))}
    assert notes == {"a.md"}
    notes = {s.note.name for s in writing.prompt_sections(tmp_path, today=date(2026, 11, 2))}
    assert notes == {"a.md", "b.md"}


def test_prompt_sections_put_drafts_before_outlines_even_when_older(tmp_path):
    import os

    draft = tmp_path / "draft.md"
    draft.write_text(OUTLINE.replace("status: outline", "status: draft"))
    (tmp_path / "editing.md").write_text(OUTLINE.replace("status: outline", "status: editing"))
    outline = tmp_path / "outline.md"
    outline.write_text(OUTLINE)
    os.utime(draft, (1_700_000_000, 1_700_000_000))  # oldest file on disk
    os.utime(outline, (1_900_000_000, 1_900_000_000))  # newest
    order = []
    for s in writing.prompt_sections(tmp_path, today=date(2026, 10, 10)):
        if s.note.name not in order:
            order.append(s.note.name)
    assert order == ["editing.md", "draft.md", "outline.md"]
    # a finished draft (no thin sections) doesn't use up one of the `recent` slots
    full = "---\nstatus: draft\n---\n## A\n\n" + "word " * 60 + "\n\n## B\n\n" + "word " * 60 + "\n"
    (tmp_path / "done.md").write_text(full)
    os.utime(tmp_path / "done.md", (1_950_000_000, 1_950_000_000))
    notes = [s.note.name for s in writing.prompt_sections(tmp_path, recent=3, today=date(2026, 10, 10))]
    assert "done.md" not in notes and "outline.md" in notes
    assert all(s.words < writing.THIN_SECTION_WORDS for s in writing.prompt_sections(tmp_path))


def test_pick_prompt_after_pages_offers_thinnest_section_of_newest_draft(tmp_path):
    newest, older = tmp_path / "new.md", tmp_path / "old.md"
    sections = [
        writing.Section(newest, "New", "Fuller", 30),
        writing.Section(newest, "New", "Empty", 0),
        writing.Section(older, "Old", "Emptier", 0),
    ]
    own = (date(2026, 10, 9), "a thought")
    today = date(2026, 10, 10)
    assert "Keep going" in writing.pick_prompt(today, [], sections, own_words=own)
    done = writing.pick_prompt(today, [], sections, own_words=own, pages_done=True)
    assert done.startswith("Pages done.") and "Empty" in done and "Emptier" not in done
    # pages done but nothing to write into: the usual rotation, never "keep going"
    assert "seed" in writing.pick_prompt(today, [], [], own_words=own, pages_done=True)


DRAFT = """---
title: {title}
category: '[[Blog Post]]'
status: {status}
---
## Hook

{body}

## Data

<!-- TODO Jamal: numbers -->
> [!todo] find the chart
"""


def test_list_drafts_finds_started_work_newest_first(tmp_path):
    import os

    blog = tmp_path / "blog"
    (blog / "posts").mkdir(parents=True)
    (blog / "starters" / "from-building" / "s").mkdir(parents=True)
    done = blog / "posts" / "live.md"
    done.write_text(DRAFT.format(title="Live", status="published", body="Prose."))
    draft = blog / "posts" / "draft.md"
    draft.write_text(DRAFT.format(title="Draft", status="draft", body="Some real prose here."))
    started = blog / "starters" / "from-building" / "s" / "s.md"
    started.write_text(DRAFT.format(title="Started", status="outline", body="I began writing this one."))
    untouched = blog / "starters" / "from-building" / "untouched.md"
    untouched.write_text(DRAFT.format(title="Untouched", status="outline", body="*prompt only*"))
    (blog / "note.md").write_text("---\ncategory: '[[Meta]]'\nstatus: draft\n---\nNot a post.")
    os.utime(draft, (1_700_000_000, 1_700_000_000))
    got = writing.list_drafts(blog, today=date(2026, 10, 10))
    assert [d.title for d in got] == ["Started", "Draft"]
    d = next(x for x in got if x.title == "Draft")
    assert (d.status, d.prose_words, d.thin_sections, d.markers) == ("draft", 4, 2, 2)
    assert d.days_since_edit > 1000 and got[0].days_since_edit == 0


def test_prose_words_ignores_skeletons():
    skeleton = "---\nstatus: outline\n---\n# T\n\n## Hook\n\n*Write about it.*\n\n- a fact\n\n> note\n\n| a | b |\n"
    assert writing.prose_words(skeleton, starter=True) == 0
    assert writing.prose_words(skeleton + "\nMy own three words.\n", starter=True) == 4
    assert writing.prose_words(skeleton, starter=False) == 3  # bullets (marker included) count outside starters
    assert writing.prose_words("---\nstatus: reference\n---\nLots of words here.") == 0
    assert writing.prose_words("```python\nx = 1\n```\nReal *emphasis* here.") == 3
    assert writing.prose_words("<!-- TODO Jamal: four words -->\n![[image.png|alt text]]\nOne.") == 1


def test_count_words_treats_starters_folder_as_skeletons(tmp_path):
    blog = tmp_path / "blog"
    (blog / "starters" / "from-building" / "s").mkdir(parents=True)
    (blog / "starters" / "from-building" / "s" / "s.md").write_text("- fact one\n\nMine.\n")
    (blog / "post.md").write_text("- a bullet\n\nProse words.\n")
    assert writing.count_words([blog]) == 1 + 5


def test_digest_starters_only_when_enabled(tmp_path, monkeypatch):
    from calib import cli, config

    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    item = study.StudyItem("https://x.com/a", "A great post", 0.2, True, "2026-09-28", "noted", 1.0)
    picks = [("you-loved-it", item)]
    assert config.DIGEST_STARTERS is False
    assert cli._digest_starters(picks, date(2026, 10, 11), enabled=False) == []
    assert not list(tmp_path.rglob("*.md"))
    written = cli._digest_starters(picks, date(2026, 10, 11), enabled=True)
    assert len(written) == 1 and written[0].exists()
