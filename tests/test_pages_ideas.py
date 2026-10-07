from datetime import date, timedelta
from typing import Any, ClassVar

import pytest
from local_first_common.providers.base import BaseProvider

from calib import ideas, pages, panel, writing

NOTE = """---
date: 2026-09-30
---
## Tasks
- [ ] something

---

## ✍️ Morning Pages
> [!pencil]- Click to expand
> I want to write again. The starters were hard to parse.
> This is a beginning and I would like it to count for something real

---

## Notes
Not morning pages.
"""


def test_section_text_strips_callout_and_stops_at_next_section():
    text = pages.section_text(NOTE)
    assert text.startswith("I want to write again.")
    assert "[!pencil]" not in text and "Not morning pages" not in text and "Tasks" not in text


def test_prose_typed_onto_the_callout_line_counts():
    """2026-10-07: the first paragraph replaced the template title on the `[!pencil]-` line
    and 137 of 182 words went uncounted; only the template's own title is dropped."""
    note = "## ✍️ Morning Pages\n> [!pencil]- I started writing right here on the marker line.\n> Second paragraph.\n"
    assert pages.section_text(note) == "I started writing right here on the marker line.\nSecond paragraph."
    titled = "## ✍️ Morning Pages\n> [!pencil]- Click to expand stream-of-consciousness writing\n> Real words.\n"
    assert pages.section_text(titled) == "Real words."


def test_empty_callout_is_empty():
    assert pages.section_text("## ✍️ Morning Pages\n> [!pencil]- Click to expand\n> \n\n---\n") == ""


def test_by_day_reads_only_dated_notes_with_pages(tmp_path):
    (tmp_path / "2026-09-30.md").write_text(NOTE)
    (tmp_path / "2026-09-29.md").write_text("## ✍️ Morning Pages\n> [!pencil]-\n> \n")
    (tmp_path / "2026-W40.md").write_text(NOTE)
    assert list(pages.by_day(tmp_path)) == [date(2026, 9, 30)]
    assert pages.by_day(tmp_path / "missing") == {}


def test_last_thought_prefers_trailing_fragment_then_last_sentence():
    assert (
        pages.last_thought(pages.section_text(NOTE))
        == "This is a beginning and I would like it to count for something real"
    )
    assert pages.last_thought("Short one. This sentence has plenty of words in it to count.") == (
        "This sentence has plenty of words in it to count."
    )
    assert pages.last_thought("Too short. Also short.") is None


def test_recent_quote_only_looks_back_a_few_days():
    today = date(2026, 10, 1)
    text = {date(2026, 9, 30): "This is a sentence with more than eight words in it."}
    assert pages.recent_quote(text, today) == (
        date(2026, 9, 30),
        "This is a sentence with more than eight words in it.",
    )
    assert pages.recent_quote(text, date(2026, 10, 9)) is None
    assert pages.recent_quote({today: "Today's own words should not be quoted back as yesterday."}, today) is None


def test_pages_alone_make_a_day_and_extend_the_streak(conn):
    today = date(2026, 9, 30)
    words = {today: 106, today - timedelta(days=1): 49, today - timedelta(days=2): 300}
    assert writing.day_done(conn, today, 100, words, 50)
    assert not writing.day_done(conn, today - timedelta(days=1), 100, words, 50)
    assert writing.streak(conn, today, 100, words, 50) == 1


def test_pick_prompt_quotes_your_own_last_thought_first():
    prompt = writing.pick_prompt(date(2026, 10, 1), ["x"], [], own_words=(date(2026, 9, 30), "I want it to count."))
    assert prompt == "Yesterday you wrote: “I want it to count.” Keep going."
    assert writing.pick_prompt(date(2026, 10, 1), ["x"], [], own_words=(date(2026, 9, 28), "q")).startswith("On Monday")


def test_heatmap_starts_on_a_sunday_and_levels_words(conn):
    today = date(2026, 9, 30)  # a Wednesday
    heat = panel.heatmap(conn, today, 100, {today: 106, today - timedelta(days=1): 20}, 50, weeks=2)
    assert date.fromisoformat(heat[0]["day"]).weekday() == 6
    assert heat[-1] == {"day": "2026-09-30", "words": 106, "pages": 106, "done": True, "level": 2}
    assert heat[-2]["level"] == 1 and not heat[-2]["done"]
    assert heat[0]["level"] == 0
    assert len(heat) == 7 + 4


ENTRIES = [(date(2026, 9, 30), "I built tooling to make writing starters. None of them felt like mine to write.")]


def _idea(quote):
    return ideas.Idea(
        title="Starters That Weren't Mine",
        quote=quote,
        why="Generated prompts don't carry your own momentum.",
        sections=[ideas.Section(heading="What I built", prompt="What did you expect the starters to do?")],
    )


class FakeProvider(BaseProvider):
    """Returns a preset result as-is (no validation), recording each call."""

    provider_name = "fake"
    default_model = "fake"
    known_models: ClassVar[list[str]] = ["fake"]
    models_url = ""

    def __init__(self, result):
        super().__init__()
        self.result, self.calls = result, []

    def complete(self, system, user, response_model=None, images=None, max_retries=1, rate_limit_retries=3) -> Any:
        self.calls.append((system, user, response_model))
        return self.result

    def _complete(self, system, user, response_model=None, images=None):
        raise NotImplementedError

    async def _acomplete(self, system, user, response_model=None, images=None):
        raise NotImplementedError


def test_extract_keeps_only_verbatim_quotes():
    real = _idea("None of them felt like mine to write.")
    made_up = _idea("Generated starters are fundamentally flawed.")
    llm = FakeProvider(ideas.PagesIdeas(ideas=[real, made_up]))
    kept = ideas.extract(llm, ENTRIES)
    assert [(i.title, d) for i, d in kept] == [(real.title, date(2026, 9, 30))]
    assert "## 2026-09-30" in llm.calls[0][1]
    assert llm.calls[0][2] is ideas.PagesIdeas


def test_extract_with_no_pages_makes_no_call():
    llm = FakeProvider(None)
    assert ideas.extract(llm, []) == []
    assert llm.calls == []


def test_gather_skips_stubs_and_old_days():
    today = date(2026, 9, 30)
    text = {today: "word " * 60, today - timedelta(days=1): "too short", today - timedelta(days=10): "word " * 60}
    assert [d for d, _ in ideas.gather(text, today)] == [today]


def test_write_starter_is_an_outline_and_never_overwrites(tmp_path):
    note = ideas.write_starter(
        _idea("None of them felt like mine to write."), date(2026, 9, 30), tmp_path, date(2026, 10, 4)
    )
    assert note is not None
    text = note.read_text()
    assert note == tmp_path / "starters-that-weren-t-mine" / "starters-that-weren-t-mine.md"
    assert "status: outline" in text and "source: morning pages 2026-09-30" in text
    assert "## What I built" in text and "*What did you expect the starters to do?*" in text
    _, thin = writing.thin_sections(text)
    assert thin == ["What I built"]
    assert ideas.write_starter(_idea("x"), date(2026, 9, 30), tmp_path, date(2026, 10, 4)) is None


@pytest.mark.parametrize("quote", ["abc", ""])
def test_too_short_quotes_never_match(quote):
    assert ideas.source_day(quote, ENTRIES) is None


def _art(base, stem, day, self_score, human: float | str = "null", artist=None):
    from pathlib import Path  # noqa: F401

    (base / "items").mkdir(parents=True, exist_ok=True)
    who = f"artist: {artist}\n" if artist else ""
    (base / "items" / f"{stem}.md").write_text(
        f"---\ngenerated_at: '{day}T06:00:00'\n{who}interest: X\nself_score: {self_score}\nhuman_score: {human}\n---\n"
        "**Human notes:** _not yet reviewed_\n"
    )


def test_two_artists_load_rate_and_score(tmp_path):
    from calib import art

    a, m = tmp_path / "ai-artist", tmp_path / "ai-artist-mentored"
    _art(a, "2026-09-20-old", "2026-09-20", 0.9, human=0.0)  # before the experiment
    _art(a, "2026-10-02-sunrise", "2026-10-02", 0.5)
    _art(m, "2026-10-02-market", "2026-10-02", 0.4, artist="mentored")
    _art(m, "2026-10-01-orbs", "2026-10-01", 0.6, human=0.75)
    dirs = {"self-taught": a, "mentored": m}

    items = art.load_items(dirs)
    assert {(i.path.stem, i.artist) for i in items} >= {
        ("2026-10-02-sunrise", "self-taught"),
        ("2026-10-02-market", "mentored"),
    }
    order = [i.path.stem for i in art.blind_order(items)]
    assert order[:2] in (["2026-10-02-sunrise", "2026-10-02-market"], ["2026-10-02-market", "2026-10-02-sunrise"])
    assert order[2:] == ["2026-10-01-orbs", "2026-09-20-old"]

    art.rate(art.resolve_item(dirs, "sunrise"), 2)
    exp = art.by_artist(art.load_items(dirs), date(2026, 10, 1))
    assert exp["self-taught"] == {"pieces": 1, "rated": 1, "mean_stars": 2.0, "mean_self_stars": 3.0}
    assert exp["mentored"] == {"pieces": 2, "rated": 1, "mean_stars": 4.0, "mean_self_stars": 3.0}
