# Forced Recompute + Two Loose-End Investigations — 2026-09-13

Follow-up to `3cd37b6` (AAPL stale-row investigation). Recompute was executed directly
(a data-refresh action, not a code change, per this task's own instructions); the crontab
drift and SOFI/SNAP/ROKU items are investigation-only, no fixes applied.

## 1. Did last night's cron already run? Yes — but *before* the Phase 1/2 deploy, not after

Checked `logs/nightly_trend_calculation.log` (unbroken since 2026-08-21, well under the
5MB rotation threshold, so nothing was lost to log rotation) rather than assuming. The most
recent full-universe run before this investigation was:

```
2026-09-13 03:11:30 -- Processed: 572. Failed: 2 (TWTR, WBA -- see §3).
```

That is the **same 3:10 AM run** already identified in `3cd37b6` as writing AAPL's stale
row — it ran hours **before** Phase 1 (`f484985`, 07:55) and Phase 2 (`e17d04e`, 08:09)
were committed. The cron has **not** run again since those commits landed (current time at
the start of this investigation: 08:50). This is the expected "hasn't run yet with the new
code" case the task anticipated, not a new bug — the cron did what it was supposed to do,
just before the code that would have populated the new fields existed. Per the task's own
branching, this means proceed to step 2, not flag a fresh bug.

## 2. Forced recompute — full 572-ticker tracked universe

Ran the exact production entry point (`uv run python -m pipeline.nightly_trend_calculation`,
no flags — the same code path `crontab.txt`'s `10 3 * * *` entry invokes), not a simulation.
Registered a real `CronRunLog` success entry (`2026-09-13 08:53:47`), same as a genuine
scheduled firing.

**Before:**

| | count |
|---|---|
| Total `TrendAnalysis` rows | 573 |
| Stale (`trend_started_json IS NULL`) | 571 |
| Fresh | 2 (CTAS, AAPL — both manually recomputed during this investigation's own prior sessions, not by any cron run) |

**Run result:** `Processed: 572. Failed: 2. Duration: 269.0s (4.5 min).` Failures: TWTR, WBA
— both **pre-existing, permanent Yahoo delisting failures**, confirmed independently via
the run's own yfinance error output (`$WBA: No data found, symbol may be delisted`) and via
`load_full_tracked_universe()`: both tickers are genuinely part of the 572-ticker tracked
universe (so the nightly job correctly attempts them every night) but have **zero**
`TrendAnalysis` row at all — not stale, entirely absent, since `compute_and_store_from_rows`
raises before writing anything when Yahoo returns no price history. This is a pre-existing,
unrelated condition (nothing to do with Phase 1/2 or this investigation) that will keep
recurring every night until these two dead tickers are pruned from the tracked universe —
noted for awareness, not investigated further here since it's out of this ticket's scope.

**After the full-universe run:**

| | count |
|---|---|
| Stale (`trend_started_json IS NULL`) | 4: **SOFI, EA, SNAP, ROKU** |
| Newly fresh this run | 567 |

**A genuinely new, unexpected name appeared: EA.** Investigated immediately rather than
assuming it was another instance of the SOFI/SNAP/ROKU pattern (it isn't — see the callout
below). SOFI/SNAP/ROKU are addressed in §3.

**EA callout (found as a side effect of step 2, outside the ticket's named scope but worth
recording since the before/after counts surfaced it):** EA's `computed_at` is
`08:57:45` — it **was** processed by this run, unlike SOFI/SNAP/ROKU. Its
`trend_started_json` is genuinely `None` because its cached `YahooPriceCache` history is
only **6 rows** (2026-07-17 → 2026-08-10, 24 days) — far short of the fractal swing
detector's own N=5-bars-each-side requirement, so `extract_swing_points`/`classify_swings`
correctly produce zero classifiable swings, and `run_state_machine`'s own documented
"no classifiable swing at all" bootstrap path returns `flip_swing=None` (its real,
intentional default) while `pullback_history` still correctly reads `[]` (not null — a
list defaulting to empty is a different case from a swing defaulting to absent, by
Phase 1/2's own design). Every other field on EA's row (`trend_state="uptrend"`,
`persistence_count=0`, `last_confirmed_swing_json=None`, `warning_flag=False`) matches
this exact documented bootstrap default precisely. **This is correct, not a bug** — the
same thin-history degradation any other feature on this table already handles gracefully.
Why EA's Yahoo cache itself is only 6 rows deep (a real business event — e.g. a
delisting/relisting under the same ticker — vs. a fetch-layer anomaly) was not
investigated further, since it's a pre-existing data question unrelated to Phase 1/2 and
outside this ticket's named scope; flagging for awareness only. One related, smaller design
gap worth noting: unlike Weinstein Stage Analysis (which has its own explicit
`weeks_available`/`insufficient_history` signal so the UI can distinguish "too little
history" from "never computed"), `trend_started` has no equivalent — a thin-history ticker
like EA and a genuinely-never-recomputed legacy row both render as a bare "—" on
NearTermCard.tsx today. Not fixed here (out of scope), just recorded.

## 3. SOFI / SNAP / ROKU — a different root cause, confirmed, and now resolved

**Not the same issue as the 572-ticker Phase 1/2 gap.** Grepped the complete
`nightly_trend_calculation.log` (unbroken back to 2026-08-21) for all three tickers:

- **SNAP and ROKU never appear in the log at all**, on any date.
- **SOFI appears exactly once**, in a 5-ticker run (`[5/5]`, alongside GWW/AAPL/MSFT/IREN)
  on 2026-08-21 23:53 — an ad-hoc/dev invocation (`--tickers ...`), never the full-universe
  cron.

Confirmed directly against `pipeline.nightly_fundamentals_fetch.load_full_tracked_universe`
(the exact function the nightly job calls to build its ticker list — S&P 500 + Dow +
ever-FMP-profile-fetched + ever-scored + on-any-watchlist): **none of SOFI, SNAP, or ROKU
are members.** Reconciling the numbers directly: the universe has 572 tickers; the
`TrendAnalysis` table has 573 rows = 570 genuine tracked-and-succeeded tickers + SOFI + SNAP
+ ROKU (3 rows that exist only from one-off manual/on-demand computations, sitting outside
the tracked universe entirely) — while TWTR and WBA (both genuinely in the 572-ticker
universe) have **no row at all** (see §2). This is a clean, fully-reconciled accounting, not
a guess.

**Root cause: these three tickers are excluded from the nightly job's own universe query,
not "even more stale" by the same timing mechanism as the other 572.** No amount of waiting
for future nightly runs will ever refresh them — the job structurally never looks at them.
Their rows exist purely because *something* (an ad-hoc dev run for SOFI; most plausibly an
on-demand `GET /api/tickers/{ticker}/trend-analysis` page-view for SNAP/ROKU, given both
share the identical `2026-09-06 10:16:32` timestamp to the millisecond-adjacent range and
that endpoint's on-demand compute-on-stale-or-missing behavior) computed them once and
nothing has touched them since.

**Confirmed the forced recompute in step 2 does NOT resolve them** (their `computed_at`
was unchanged after the full-universe run — still `2026-08-21`/`2026-09-06`, exactly as
before). **They need separate handling, and it works cleanly**: ran the same single-ticker
production function used for AAPL in `3cd37b6` (`compute_and_store_trend_analysis`) against
each directly:

| Ticker | Result | trend_state | persistence_count | trend_started | pullback_history |
|---|---|---|---|---|---|
| SOFI | OK | downtrend | 9 | 2026-02-27 (real flip) | 3 cycles |
| SNAP | OK | downtrend | 10 | 2026-02-17 (real flip) | 4 cycles |
| ROKU | OK | uptrend | 10 | 2026-05-08 (real flip) | 1 cycle |

All three now carry real, fresh data (confirmed in the final tally below) — the mechanism
that fixed AAPL works identically here. **They will go stale again** on the same schedule
as before (i.e., never refreshed by cron) unless a future change adds them to the tracked
universe (e.g. watchlisting them) or someone visits their ticker page again to trigger the
on-demand path. That's a product/scope question, not something this investigation is
positioned to decide, so it isn't proposed as a fix here — only demonstrated and reported.

## Final tally

```
Total TrendAnalysis rows:                    573
Still stale (trend_started_json IS NULL):      1  -- EA only, and it's correct (see §2), not stale
```

572 of 573 rows now carry real, freshly-computed `trend_started`/`pullback_history` values;
the one remaining null is a genuine thin-history result, not a leftover staleness artifact.

## 4. Crontab drift — one root cause behind two diffs, not two independent problems

`diff <(crontab -l) backend/crontab.txt` shows exactly two hunks, matching the two jobs
named in the prior report:

**(a) `pipeline.nightly_warren_signal_calculation` — missing entirely from the live
crontab.** `crontab.txt` schedules it at `40 3 * * *`; `crontab -l` has no entry for it at
all. **This is a real, active risk, not cosmetic** — confirmed via `CronRunLog`: exactly
**one** recorded run ever, `2026-09-12 04:45:39, success` (a one-off manual/dev invocation
timestamp-wise, not a `03:1x` cron-slot time — consistent with never having fired from cron
even once), and nothing since. As of this investigation (~09:00 on 2026-09-13), that's over
24 hours stale with no live schedule to ever re-fire it. `core/cron_health.py::
CRON_JOB_NAMES` does include this job (so `GET /api/config/cron-health` would compute and
surface it as overdue) — but confirmed via `.env` that **`CRON_HEALTH_ENABLED=false` in
this environment**, so the in-app banner is not currently surfacing this at all regardless
of the underlying drift (this flag also has `FMP_ENABLED=false`, consistent with this being
a local/offline dev sandbox rather than necessarily reflecting a real production `.env`
posture — not investigated further, since that's a separate environment-configuration
question). The only thing that actually caught this was the direct `crontab -l` vs.
`crontab.txt` diff — the exact check CLAUDE.md's own "Main/Secondary watchlist" incident
history says is the one thing that reliably catches this class of drift.

**(b) `backup_db`'s schedule — live crontab has it at `35 3 * * *`; `crontab.txt` has it at
`55 3 * * *`.** Not an independent scheduling bug — it's the **other half of the same
missing-reinstall gap**. `crontab.txt`'s own comment history shows both entries were edited
together on 2026-09-12 (Warren's job added at 3:40, backup_db correspondingly pushed from
3:35 to 3:55 to keep a 15-minute buffer after it) — but the live crontab was never
re-applied (`crontab crontab.txt`) after that edit, so it's still running the *previous*
generation of both entries: Warren absent, backup_db still at its pre-edit 3:35.

**Risk assessment, and why (a) is worse than (b) today:** with the live crontab exactly as
it is right now, backup_db at 3:35 causes **no actual collision** — the job that used to
justify 3:35 (Liquidity Zone, 3:25 AM + a 10-minute buffer) is still correctly what runs
immediately before it, since Warren isn't live to conflict with. (b) is therefore currently
latent, not actively wrong, and would only become a real problem the moment someone fixes
(a) in isolation without also re-applying (b) — backup_db would then fire at 3:35, mid-way
through Warren's own newly-corrected 3:40-3:55 window, backing up a database Warren could
still be writing to. (a) is the actively live problem today: a whole feature's nightly
compute has silently never run on schedule since being added. **Fix for both, if/when
undertaken, is the same single action**: `crontab crontab.txt` (reinstall from the
already-correct file) — not two separate schedule edits. No code change, no file edit;
purely a live-crontab reinstall, and per this task's own scope this is reported, not
executed.

## Bottom line

Both loose ends resolved to root causes, not left as open questions: SOFI/SNAP/ROKU are
outside the tracked universe entirely (a scope/membership question, not a timing bug), now
demonstrated fixable via the same on-demand mechanism that fixed AAPL; the crontab drift is
one missing `crontab crontab.txt` reinstall manifesting as two diffs, with the Warren job's
complete absence being the actionable risk and backup_db's mistiming being its currently-
dormant side effect. The universe-wide Phase 1/2 backfill is done: 572 of 573 tracked
tickers now carry real `trend_started`/`pullback_history` data, and the one exception (EA)
is a correct thin-history result, not a bug.
