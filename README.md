# calibration (`calib`)

An N=1 calibration study, running all year:

1. **Model vs me.** Does content-discovery-agent's relevance score predict what I actually do with an article in Readwise Reader?
2. **Model vs model.** Is a local model closer to my behavior than Claude is? (the third rater)
3. **Me vs me.** When I say something is 70% likely, does it happen 70% of the time?
4. **Reading vs writing.** How much of what I read turns into notes, seeds and posts?

Plus the plumbing for a daily 10-minute writing habit.

## Ground truth

Discovery's own `kept`/`dismissed` history is the score threshold, not a human judgment, so it isn't used as ground truth. Engagement is read from Reader instead, strongest signal first:

| level | engagement | meaning |
|---|---|---|
| noted | 1.0 | a Contexta note cites it (`source_url`), or it's tagged `contexta` |
| highlighted | 0.75 | at least one highlight |
| read | 0.5 | reading progress ≥ 50% |
| opened | 0.25 | opened at all |
| ignored | 0 | none of the above, and archived or older than 14 days |
| pending | — | too young to judge; excluded |

"Engaged" means read or better. The headline number is AUC: the chance that an item you engaged with outscored one you didn't (0.5 means the score tells nothing).

**Probes.** Only items the model liked ever reach Reader, so its misses would be invisible. Discovery therefore sends up to 4 rejected items a week to Reader, chosen at random and marked only in its store (`probed_at`), never with a visible tag. Set `probe_weekly_cap = 0` in discovery's config to stop.

## Commands

```bash
calib report                 # model score vs your engagement, by score band, AUC per rater
calib digest                 # this week's sharpest disagreements -> BrainSync/blog/starters/from-reading/ (set digest_starters = true in calibration.toml to also get one outline starter per disagreement; off since 2026-10-10)
calib rescore -p ollama -m @fast --limit 50   # third rater; then `calib report --no-sync`
calib yield                  # monthly funnel: surfaced -> opened -> read -> highlighted -> noted, + seeds, posts
calib predict add "DuckDB post 3 ships" 70 --due 2026-10-05 --post 03-why-your-csv
calib predict list | resolve <id> yes|no | score
calib art pending | rate <item> <1-5> [--note ...] | stats
calib write status | done | prompt | drafts   # drafts: posts you started but haven't finished or published
calib daily                  # the scheduled job
```

Claude Code skills wrap the two interactive pieces: `/rate-art` (blind 1-5 ratings in one reply) and `/predict`.

## Wiring

- `com.localfirst.calibration` runs `calib daily` at 03:30: writing baseline, Reader sync, auto-resolving post predictions; on Sundays it also writes the digest. Log: `~/sync/local-first/calibration.log`.
- A Claude Code `SessionStart` hook runs `calib write status --hook`. Until you've written 100 words today in `BrainSync/blog` or `BrainSync/newsletter` (or run `calib write done`), each session opens with the day's 10-minute prompt: once today's morning pages are done, the thinnest section of your newest draft; before that, yesterday's last thought from the pages, or alternately a disagreement from the digest and a thin section of one of your three most recently touched drafts or outlines (drafts first).
- Dashboard: every writing command (and `com.localfirst.writing-status`, every 30 minutes) writes `~/sync/local-first/writing-practice-latest.json`, which fleet-dashboard-service shows as the **Writing practice** card at the top of the page (and in the phone snapshot): today's prompt, streak, posts in progress (`calib write drafts`: status, prose words, thin sections, open TODO markers, days since the last edit), starters as Obsidian links, and reminders for `/rate-art` and `/predict`.
- Post starters: `BrainSync/blog/starters/` (see its `_README.md`). Word counts ignore skeleton text, so generated starters never count as writing.
- Data: `~/sync/calibration/calibration.db` (picked up by `backup-local-first`). Paths are overridable in `~/.config/local-first/calibration.toml`.
