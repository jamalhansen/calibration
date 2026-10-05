from datetime import UTC, datetime

from conftest import add_item, doc, fake_fetch

from calib import reader, study

NOW = datetime(2026, 9, 29, tzinfo=UTC)


def _sync(conn, docs):
    reader.sync(conn, fake_fetch([docs]))


def test_sync_paginates_counts_highlights_and_is_incremental(conn):
    fetch = fake_fetch(
        [
            [doc("a", "https://x.com/a"), doc("h1", "", category="highlight", parent_id="a")],
            [doc("b", "https://x.com/b"), doc("h2", "", category="highlight", parent_id="a")],
        ]
    )
    assert reader.sync(conn, fetch) == 2
    assert "pageCursor" in fetch.calls[1]
    row = conn.execute("SELECT highlights FROM reader_docs WHERE doc_id = 'a'").fetchone()
    assert row["highlights"] == 2

    second = fake_fetch([[doc("a", "https://x.com/a", reading_progress=0.9)]])
    reader.sync(conn, second)
    assert "updatedAfter" in second.calls[0]
    progress = conn.execute("SELECT reading_progress, highlights FROM reader_docs WHERE doc_id = 'a'").fetchone()
    assert progress["reading_progress"] == 0.9 and progress["highlights"] == 2


def test_classify_levels(conn):
    _sync(
        conn,
        [
            doc("noted", "https://x.com/n", tags={"contexta": {"name": "contexta"}}),
            doc("hl", "https://x.com/h"),
            doc("hl1", "", category="highlight", parent_id="hl"),
            doc("read", "https://x.com/r", reading_progress=0.6),
            doc("open", "https://x.com/o", first_opened_at="2026-09-02T00:00:00Z"),
            doc("old", "https://x.com/old"),
            doc("young", "https://x.com/y", saved_at="2026-09-28T00:00:00+00:00"),
            doc("arch", "https://x.com/arch", saved_at="2026-09-28T00:00:00+00:00", location="archive"),
        ],
    )
    got = {r["doc_id"]: study.classify(r, False, NOW, 14) for r in conn.execute("SELECT * FROM reader_docs")}
    assert got["noted"] == ("noted", 1.0)
    assert got["hl"] == ("highlighted", 0.75)
    assert got["read"] == ("read", 0.5)
    assert got["open"] == ("opened", 0.25)
    assert got["old"] == ("ignored", 0.0)
    assert got["young"] == ("pending", None)
    assert got["arch"] == ("ignored", 0.0)


def test_load_items_joins_routed_and_probes_only(conn, discovery_store):
    add_item(discovery_store, "https://x.com/kept", 0.9)
    add_item(discovery_store, "https://x.com/probe", 0.2, status="dismissed", probed=True)
    add_item(discovery_store, "https://x.com/dismissed", 0.1, status="dismissed")
    add_item(discovery_store, "https://x.com/not-in-reader", 0.9)
    _sync(
        conn,
        [
            doc("k", "https://x.com/kept/", reading_progress=0.7),
            doc("p", "https://x.com/probe"),
            doc("d", "https://x.com/dismissed"),
        ],
    )
    items = study.load_items(conn, str(discovery_store), {"https://x.com/probe"}, 14, now=NOW)
    by_url = {i.url_norm: i for i in items}
    assert set(by_url) == {"https://x.com/kept", "https://x.com/probe"}
    assert by_url["https://x.com/kept"].level == "read"
    assert by_url["https://x.com/probe"].probe and by_url["https://x.com/probe"].level == "noted"


def _item(score, engagement, probe=False, url=None, saved="2026-09-27T00:00:00+00:00"):
    level = {None: "pending", 0.0: "ignored", 0.5: "read", 1.0: "noted"}[engagement]
    return study.StudyItem(url or f"u{score}{engagement}", f"t{score}", score, probe, saved, level, engagement)


def test_auc():
    assert study.auc([(0.9, True), (0.1, False)]) == 1.0
    assert study.auc([(0.1, True), (0.9, False)]) == 0.0
    assert study.auc([(0.5, True), (0.5, False)]) == 0.5
    assert study.auc([(0.5, True)]) is None


def test_summarize_separates_probes_and_ignores_pending():
    items = [_item(0.9, 1.0), _item(0.85, 0.0), _item(0.2, 0.5, probe=True), _item(0.8, None)]
    s = study.summarize(items, {"ollama/x": {"u0.91.0": 0.3}})
    assert s["resolved"] == 3 and s["pending"] == 1
    assert s["routed_engaged_pct"] == 50
    assert s["probe_engaged_pct"] == 100
    assert s["auc"]["ollama/x_n"] == 1


def test_disagreements_alternate_and_stay_recent():
    items = [
        _item(0.2, 1.0, probe=True, url="loved-low"),
        _item(0.95, 0.0, url="ignored-high"),
        _item(0.9, 0.0, url="ignored-old", saved="2026-01-01T00:00:00+00:00"),
    ]
    picks = study.disagreements(items, study.week_ago(NOW))
    assert [(k, i.url_norm) for k, i in picks] == [("you-loved-it", "loved-low"), ("model-loved-it", "ignored-high")]
