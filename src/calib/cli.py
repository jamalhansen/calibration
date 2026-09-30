"""calib: the N=1 calibration study."""

import json
import sys
from datetime import date, datetime
from typing import Annotated

import typer
from local_first_common.tracking import register_tool, timed_run
from rich.console import Console
from rich.table import Table

from calib import (
    art,
    config,
    db,
    digest,
    funnel,
    ideas,
    pages,
    panel,
    predict,
    reader,
    rescore,
    starters,
    study,
    writing,
)

_TOOL = register_tool(config.TOOL_NAME)

app = typer.Typer(help="N=1 calibration: model scores vs what you actually read, your own predictions, and writing.")
predict_app = typer.Typer(help="Log and score your own probabilistic predictions.")
art_app = typer.Typer(help="Rate artist-agent pieces against its self-scores.")
write_app = typer.Typer(help="The daily 10-minute writing habit.")
app.add_typer(predict_app, name="predict")
app.add_typer(art_app, name="art")
app.add_typer(write_app, name="write")

console = Console()
err = Console(stderr=True)
JsonOpt = Annotated[bool, typer.Option("--json", "-j", help="Machine-readable JSON on stdout.")]
DryRunOpt = Annotated[bool, typer.Option("--dry-run", "-n", help="Compute everything, write nothing.")]


def _conn():
    return db.connect(config.DB_PATH)


def _today() -> date:
    return datetime.now().astimezone().date()


def _sync(conn, full: bool = False) -> int:
    if not config.READWISE_TOKEN:
        err.print("[yellow]READWISE_TOKEN not set; using the last synced Reader state.[/yellow]")
        return 0
    return reader.sync(conn, reader.http_fetch(config.READWISE_TOKEN), full=full)


def _items(conn) -> list[study.StudyItem]:
    from discovery.reconcile import collect_note_source_urls

    noted = set(collect_note_source_urls(str(config.CONTEXTA / "notes")))
    return study.load_items(conn, str(config.DISCOVERY_STORE), noted, config.RESOLVE_AFTER_DAYS)


def _pct(v) -> str:
    return "—" if v is None else f"{v}%"


@app.command()
def sync(full: Annotated[bool, typer.Option(help="Re-read every Reader document, not just changes.")] = False):
    """Mirror Reader's per-document state into the study DB."""
    with timed_run(config.TOOL_NAME, None, source_location="readwise") as run:
        run.item_count = _sync(_conn(), full)
    typer.echo(f"Synced {run.item_count} Reader documents.")


@app.command()
def report(
    json_out: JsonOpt = False,
    no_sync: Annotated[bool, typer.Option("--no-sync", help="Skip the Reader sync.")] = False,
):
    """How well the model's scores predict what you actually do in Reader."""
    conn = _conn()
    with timed_run(config.TOOL_NAME, None, source_location="report") as run:
        if not no_sync:
            _sync(conn)
        items = _items(conn)
        summary = study.summarize(items, rescore.load(conn))
        run.item_count = len(items)
    if json_out:
        typer.echo(json.dumps(summary, indent=2))
        return
    console.print(f"[bold]{summary['items']}[/bold] items reached Reader; "
                  f"{summary['resolved']} resolved, {summary['pending']} still pending.")
    console.print(f"Engaged (read, highlighted, or noted): routed {_pct(summary['routed_engaged_pct'])}, "
                  f"probes {_pct(summary['probe_engaged_pct'])} of {summary['probes_resolved']}.")
    for rater, value in summary["auc"].items():
        if not rater.endswith("_n"):
            n = summary["auc"].get(f"{rater}_n")
            label = "—" if value is None else f"{value:.2f}"
            console.print(f"AUC {rater}: {label}" + (f" (n={n})" if n is not None else ""))
    table = Table("score band", "n", "engaged", "mean engagement")
    for b in summary["bands"]:
        table.add_row(b["band"], str(b["n"]), f"{b['engaged_pct']}%", f"{b['mean_engagement']:.2f}")
    console.print(table)
    console.print("[dim]AUC 0.5 = the score tells nothing about what you'll engage with; 1.0 = perfect.[/dim]")


@app.command("digest")
def digest_cmd(dry_run: DryRunOpt = False, no_sync: Annotated[bool, typer.Option("--no-sync")] = False):
    """Write this week's disagreement digest (writing prompts) to the vault."""
    conn = _conn()
    today = _today()
    with timed_run(config.TOOL_NAME, None, source_location="digest") as run:
        if not no_sync:
            _sync(conn)
        picks = study.disagreements(_items(conn), study.week_ago())
        text = digest.render(picks, today)
        run.item_count = len(picks)
    path = digest.digest_path(config.PROMPTS_DIR, today)
    if dry_run:
        typer.echo(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    typer.echo(f"Wrote {len(picks)} disagreements to {path}")
    for kind, item in picks:
        slug, starter = starters.disagreement_starter(kind, item, today)
        written = starters.write_starter(config.PROMPTS_DIR, slug, starter)
        if written:
            typer.echo(f"  starter: {written}")


@app.command("rescore")
def rescore_cmd(
    provider: Annotated[str, typer.Option("--provider", "-p")] = "ollama",
    model: Annotated[str | None, typer.Option("--model", "-m")] = None,
    limit: Annotated[int, typer.Option(help="Most items to score this run.")] = 50,
    dry_run: DryRunOpt = False,
):
    """Third rater: score resolved items with another model and compare it against you in `report`."""
    from discovery.config import INTEREST_EXCLUSIONS, INTEREST_PROFILE
    from local_first_common.cli import resolve_provider
    from local_first_common.providers import PROVIDERS

    conn = _conn()
    llm = resolve_provider(PROVIDERS, provider, model, fallback=False, tool_name=config.TOOL_NAME)
    rater = f"{provider}/{getattr(llm, 'model', None) or model or 'default'}"
    todo = rescore.pending_for(conn, _items(conn), rater, limit)
    typer.echo(f"Scoring {len(todo)} items with {rater}...")
    results = rescore.score_items(llm, todo, INTEREST_PROFILE, INTEREST_EXCLUSIONS)
    if dry_run:
        for item, s in results:
            typer.echo(f"  {s if s is not None else '—'}  (claude {item.score:.2f})  {item.title[:70]}")
        return
    typer.echo(f"Saved {rescore.save(conn, rater, results)} scores. Run `calib report --no-sync` to compare.")


@app.command("yield")
def yield_cmd(json_out: JsonOpt = False, months: Annotated[int, typer.Option()] = 6):
    """Reading-to-writing funnel by month: surfaced → opened → read → highlighted → noted, plus seeds and posts."""
    conn = _conn()
    with timed_run(config.TOOL_NAME, None, source_location="yield") as run:
        table_data = funnel.build(_items(conn), config.CONTEXTA / "seeds", config.BRAINSYNC / "blog")
        run.item_count = len(table_data)
    recent = dict(list(table_data.items())[-months:])
    if json_out:
        typer.echo(json.dumps(recent, indent=2))
        return
    cols = [*funnel.STAGES, "seeds", "posts"]
    table = Table("month", *cols)
    for month, row in recent.items():
        table.add_row(month, *(str(row.get(c, 0)) for c in cols))
    console.print(table)


@app.command()
def daily(dry_run: DryRunOpt = False):
    """Scheduled job: writing baseline, Reader sync, auto-resolve predictions; Sundays also write the digest."""
    conn = _conn()
    today = _today()
    with timed_run(config.TOOL_NAME, None, source_location="daily") as run:
        if not dry_run:
            writing.observe(conn, today, writing.count_words(config.WRITING_DIRS))
            run.item_count = _sync(conn)
            resolved = predict.auto_resolve(conn, config.BRAINSYNC, today)
            typer.echo(f"Synced {run.item_count} docs; auto-resolved {len(resolved)} predictions.")
    if today.weekday() == 6:
        digest_cmd(dry_run=dry_run, no_sync=True)
        write_ideas(days=7, dry_run=dry_run)
    if not dry_run:
        _refresh(conn)


# --- predictions -----------------------------------------------------------

@predict_app.command("add")
def predict_add(
    text: str,
    probability: Annotated[float, typer.Argument(help="0-1, or a percentage like 70")],
    due: Annotated[str, typer.Option(help="YYYY-MM-DD")],
    post: Annotated[str | None, typer.Option(help="Blog note path or slug; resolves itself when published")] = None,
):
    """Log a prediction, e.g. calib predict add "DuckDB post 3 ships" 70 --due 2026-10-05 --post 03-why-your-csv"""
    p = probability / 100 if probability > 1 else probability
    pid = predict.add(_conn(), text, p, date.fromisoformat(due), post)
    typer.echo(f"#{pid}: {text} — {p:.0%} by {due}")
    _refresh(_conn())


@predict_app.command("list")
def predict_list(json_out: JsonOpt = False):
    """Open predictions, soonest due first."""
    rows = [dict(r) for r in predict.open_predictions(_conn())]
    if json_out:
        typer.echo(json.dumps(rows, indent=2))
        return
    for r in rows:
        overdue = " [red]overdue[/red]" if r["due"] < _today().isoformat() else ""
        console.print(f"#{r['id']} {r['probability']:.0%} by {r['due']}{overdue}: {r['text']}")
    if not rows:
        typer.echo("No open predictions.")


@predict_app.command("resolve")
def predict_resolve(pid: int, outcome: Annotated[str, typer.Argument(help="yes or no")]):
    """Record whether a prediction came true."""
    if outcome.lower() not in ("yes", "no", "y", "n"):
        raise typer.BadParameter("outcome must be yes or no")
    try:
        predict.resolve(_conn(), pid, outcome.lower().startswith("y"))
    except KeyError as e:
        err.print(str(e))
        raise typer.Exit(1) from e
    typer.echo(f"#{pid} resolved: {outcome}")
    _refresh(_conn())


@predict_app.command("score")
def predict_score(json_out: JsonOpt = False):
    """Brier score and calibration: of the things you said were 70% likely, how many happened?"""
    conn = _conn()
    predict.auto_resolve(conn, config.BRAINSYNC, _today())
    s = predict.score(conn)
    if json_out:
        typer.echo(json.dumps(s, indent=2))
        return
    if not s["n"]:
        typer.echo("Nothing resolved yet.")
        return
    console.print(f"{s['n']} resolved; Brier {s['brier']} (0 = perfect, 0.25 = coin-flip guessing).")
    table = Table("you said", "n", "happened")
    for b in s["buckets"]:
        table.add_row(b["said"], str(b["n"]), f"{b['happened_pct']}%")
    console.print(table)


# --- art -------------------------------------------------------------------

@art_app.command("pending")
def art_pending(json_out: JsonOpt = False, limit: Annotated[int, typer.Option()] = 7):
    """Unrated pieces, newest first."""
    items = [i for i in art.load_items(config.ART_DIR) if i.human_score is None][:limit]
    rows = [{"item": i.path.name, "image": str(i.image), "title": i.title, "interest": i.interest,
             "self_score": i.self_score} for i in items]
    if json_out:
        typer.echo(json.dumps(rows, indent=2))
        return
    for r in rows:
        typer.echo(f"{r['item']}  self={r['self_score']}  [{r['interest']}]")


@art_app.command("rate")
def art_rate(
    item: Annotated[str, typer.Argument(help="Item filename or a unique fragment of it")],
    stars: Annotated[int, typer.Argument(help="1-5")],
    note: Annotated[str | None, typer.Option(help="One line on why")] = None,
):
    """Rate a piece 1-5; stored as human_score on the 0-1 scale self_score uses."""
    try:
        path = art.resolve_item(config.ART_DIR, item)
        score = art.rate(path, stars, note)
    except (LookupError, ValueError) as e:
        err.print(str(e))
        raise typer.Exit(1) from e
    typer.echo(f"{path.name}: {stars}/5 (human_score {score:g})")
    _refresh(_conn())


@art_app.command("stats")
def art_stats(json_out: JsonOpt = False):
    """Your scores against the agent's self-scores."""
    s = art.stats(art.load_items(config.ART_DIR))
    typer.echo(json.dumps(s, indent=2) if json_out else "\n".join(f"{k}: {v}" for k, v in s.items()))


# --- writing ---------------------------------------------------------------

def _pages_words() -> tuple[dict[date, str], dict[date, int]]:
    text = pages.by_day(config.TIMELINE_DIR)
    return text, {d: pages.word_count(t) for d, t in text.items()}


def _prompt_today(today: date, pages_text: dict[date, str] | None = None) -> str:
    if pages_text is None:
        pages_text, _ = _pages_words()
    prompts = digest.prompts_from_digest(digest.digest_path(config.PROMPTS_DIR, today))
    return writing.pick_prompt(
        today, prompts, writing.outline_sections(config.BRAINSYNC / "blog"),
        own_words=pages.recent_quote(pages_text, today),
    )


def _refresh(conn) -> tuple[int, bool, str, dict[date, int]]:
    """Observe today's writing, rewrite the dashboard status file.

    Returns (words today incl. morning pages, done, prompt, morning-pages words by day).
    """
    today = _today()
    prose = writing.observe(conn, today, writing.count_words(config.WRITING_DIRS))
    pages_text, pages_words = _pages_words()
    words = prose + pages_words.get(today, 0)
    done = writing.day_done(conn, today, config.WRITING_DONE_WORDS, pages_words, config.MORNING_PAGES_MIN_WORDS)
    prompt = _prompt_today(today, pages_text)
    panel.write(config.STATUS_FILE, panel.build(
        conn, today, words_today=words, done=done, prompt=prompt, threshold=config.WRITING_DONE_WORDS,
        starters_dir=config.STARTERS_DIR, vault_root=config.BRAINSYNC, art_dir=config.ART_DIR,
        pages_words=pages_words, pages_min=config.MORNING_PAGES_MIN_WORDS,
    ))
    return words, done, prompt, pages_words


@write_app.command("status")
def write_status(hook: Annotated[bool, typer.Option("--hook", help="Output for a Claude Code SessionStart hook.")] = False):
    """Words written today, the streak, and today's 10-minute prompt if you haven't written yet."""
    conn = _conn()
    today = _today()
    words, done, prompt, pages_words = _refresh(conn)
    days = writing.streak(conn, today, config.WRITING_DONE_WORDS, pages_words, config.MORNING_PAGES_MIN_WORDS)
    if done:
        msg = f"Wrote today ({words} words). Streak: {days} day{'s' if days != 1 else ''}."
    else:
        msg = f"Write first, then code. 10 minutes: {prompt}"
        if days:
            msg += f" (Streak: {days}.)"
    if hook:
        if not done:
            sys.stdout.write(json.dumps({"systemMessage": msg}))
        return
    typer.echo(msg)


@write_app.command("done")
def write_done():
    """Count today as written (for writing that happened outside the vault)."""
    conn = _conn()
    writing.mark_done(conn, _today(), writing.count_words(config.WRITING_DIRS))
    *_, pages_words = _refresh(conn)
    days = writing.streak(conn, _today(), config.WRITING_DONE_WORDS, pages_words, config.MORNING_PAGES_MIN_WORDS)
    typer.echo(f"Marked. Streak: {days}.")


@write_app.command("prompt")
def write_prompt():
    """Just today's prompt."""
    typer.echo(_prompt_today(_today()))


@write_app.command("ideas")
def write_ideas(
    days: Annotated[int, typer.Option(help="How many days of morning pages to read.")] = 7,
    dry_run: DryRunOpt = False,
):
    """Turn recent morning pages into post starters in blog/starters/from-pages/ (runs Sundays)."""
    from local_first_common.cli import resolve_provider
    from local_first_common.providers import PROVIDERS

    today = _today()
    pages_text, _ = _pages_words()
    entries = ideas.gather(pages_text, today, days, config.MORNING_PAGES_MIN_WORDS)
    if not entries:
        typer.echo(f"No morning pages of {config.MORNING_PAGES_MIN_WORDS}+ words in the last {days} days.")
        return
    llm = resolve_provider(PROVIDERS, config.IDEAS_PROVIDER, config.IDEAS_MODEL, fallback=False, tool_name=config.TOOL_NAME)
    found = ideas.extract(llm, entries)
    if not found:
        typer.echo(f"Read {len(entries)} day(s) of pages; nothing that's a post yet.")
        return
    for idea, day in found:
        if dry_run:
            typer.echo(f"[dry run] {idea.title}  <- “{idea.quote}” ({day})")
            continue
        note = ideas.write_starter(idea, day, config.PAGES_STARTERS_DIR, today)
        typer.echo(f"{'Wrote' if note else 'Already have'}: {idea.title}  <- “{idea.quote}” ({day})")
