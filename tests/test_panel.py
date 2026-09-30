from datetime import date

from calib import panel


def _starter(root, group, slug, extra=""):
    d = root / "blog" / "starters" / group / slug
    d.mkdir(parents=True)
    (d / f"{slug}.md").write_text(f"---\ntitle: {slug}\nstatus: outline\ncreated: 2026-09-29\n{extra}---\n# T\n\n## A\n\n## B\n")


def test_starters_listed_with_links_and_holds(tmp_path):
    vault = tmp_path / "BrainSync"
    _starter(vault, "from-building", "art-static")
    _starter(vault, "from-reading", "open-models")
    _starter(vault, "from-building", "later-post", "ready_after: 2026-11-01\n")
    got = panel.list_starters(vault / "blog" / "starters", vault, date(2026, 9, 30))
    assert [s["title"] for s in got] == ["art-static", "open-models", "later-post"]
    assert got[0]["sections_left"] == 2 and not got[0]["held"]
    assert got[2]["held"] and got[2]["ready_after"] == "2026-11-01"
    assert got[0]["link"] == "obsidian://open?vault=BrainSync&file=blog/starters/from-building/art-static/art-static"


def test_recent_days_marks_untracked(conn):
    conn.execute("INSERT INTO writing_days(day, baseline, last_total) VALUES ('2026-09-30', 0, 150)")
    days = panel.recent_days(conn, date(2026, 9, 30), 100, n=2)
    assert days == [
        {"day": "2026-09-29", "done": False, "tracked": False},
        {"day": "2026-09-30", "done": True, "tracked": True},
    ]
