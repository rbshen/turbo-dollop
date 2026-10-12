# Opportunities (the weekly opportunity agent)

Built 2026-10-11 (phase 1b). Two frozen lists, **Momentum** and **Reversal**, built across the whole tracked universe from **stored data only** (no FMP call,
no LLM call, no live price), saved as a dated snapshot and shown on the read-only `/opportunities` page. Not part of the Overall score, the stage engine or any
nightly job: it only reads them. **Cron: enabled 2026-10-12** (Saturdays 4:00 AM server time, see "Cron status", below). Code: `scoring/opportunity_rules.py` (pure rules), `data/opportunity_data.py` (load, evaluate, persist, read),
`pipeline/weekly_opportunity_snapshot.py` (entry point), `GET /api/opportunities/*` in `core/main.py`, `frontend/app/opportunities/`.

## The rules (versioned: `RULES_VERSION = "2"`, rule ids end `.v2`)

`scoring/opportunity_rules.py::rules_hash()` is the sha256 of every id and threshold below (`rules_definition()`); each run stores it with `rules_version`.
**Change any threshold and bump `RULES_VERSION`**, so an old run is read against the rules it used.

**One list per ticker (rules v2, 2026-10-11).** The lists are opposite in nature, so they are mutually exclusive and **trend stage decides which one a ticker can be on**
(`scoring/opportunity_rules.py::assign_list`, the single router; `place()` returns the one placement). Established Advance (stage Advance for **more than**
`FRESH_ADVANCE_MAX_WEEKS` = 8 weeks) -> Momentum only. Decline, Base, a pending Advance (`pending_direction = advance`) or a **fresh** Advance (<= 8 weeks) -> Reversal only. Top
(unless it has a pending Advance), no fresh stage row, or an Advance of unknown age -> neither. An established Advance outranks a pending-Advance flag. Being assigned a
list is necessary, not sufficient: the list's own rules must still hit, and a ticker that fails them is NOT rerouted to the other list. A **Momentum** row whose chart would pass
the B2 price-structure test (the tier's own drawdown threshold) gets the **`deep_pullback` tag** instead of a Reversal listing (the case the later daily routine will use). The
"also on the other list" tag is gone. Enforced three ways: the router; `UNIQUE (run_id, ticker)` on `OpportunitySnapshotRow` (a ticker has one row per run, whichever list); and
`compute_run` refuses to write if a ticker ever lands on both, with tests over every stage x weeks x pending x tier combination.

**Gate, all tiers** (a ticker that fails it is on no list and not ranked): not delisted (`TickerScore.delisted_at`); the last daily bar is dated the as-of date
(and was written after that session's close, the bars cache's provisional-bar test); at least 12 months of bars; average daily dollar volume (close x volume,
last 50 sessions) at least **$25M**; SPY excluded. Reason codes: `excluded`, `delisted`, `no_bars`, `stale_bar`, `provisional_bar`, `short_history`, `illiquid`.

**Tiers.** *Quality* = stored Overall verdict **Pass or Strong Pass** (`QUALITY_VERDICTS`). *Momentum-only* = every other stock (Fail, incomplete, and **Pass with
caution**, which the preview also kept out of Quality although it is a label on a passing score: one constant to change). *ETF* = the ETF universe
(`load_etf_universe`). A leveraged fund (curated `LEVERAGED_ETF_FACTORS` plus a name test: "3X", "UltraPro") carries the `leveraged` tag and is ranked in its own
group.

**Ranked universe.** Momentum rank = `scoring/momentum.py::compute_momentum_ranking` (3, 6, 12 month composite) on the cached closes at the as-of date, over the
tickers that **pass the gate**, in three separate groups: the tracked stocks, the ordinary ETFs, the leveraged ETFs. The group sizes are stored (`ranked_universe`)
and drawn in the page footnote. (The preview ranked the 575 stocks before the liquidity floor; ranking after it moves each cut by a name or two.)

**List A, Momentum** (`A.momentum_trend.v2`): an **established** Advance (weeks in Advance > 8), MA slope > 0, Mansfield RS > 0 (the stored RS, vs SPY while `rs_benchmark` is SPY; the run stores the
benchmark), and `vs_ma_pct` strictly below the tier ceiling: **20** Quality and ETF, **15** Momentum-only. Momentum-only also needs weeks in Advance <= 52, 3 month
return <= 30%, 12 month return <= 150% and momentum rank in the **top quintile** (ceil(n/5) of the ranked stocks, exact integer arithmetic). ETFs also need the
**top third** of their own group (ceil(n/3)). Quality needs no rank. Any unknown input (no fresh stage row, no rank, no return) fails the rule it feeds.

**List B, Reversal.** `B2.price_structure.v2` (all tiers, **evaluated only for tickers whose stage puts them on Reversal**): drawdown from the 52-week high >= 20% (Quality, ETF) or >= 30% (Momentum-only); a higher low (the lowest
low of the last 126 sessions is at least 15 sessions old and the last 15 sessions' lowest low is above it); weekly close above its 10-week SMA; the 30-week EMA slope
above its value 4 weeks earlier and >= -2%. `B1.base_or_pending_advance.v2` (Quality only): stage Base, or a pending Advance. `B3.entry_signal.v2` (Quality only): a
Warren `blue_up`/`yellow_up` or a BB+RSI event dated in the last 10 sessions **and** stage Decline or Base. Each rule keeps its own id on the row (`rule_ids_json`).

**B3 coverage.** Warren, BB+RSI and Liquidity Zones run only for the monitored lists (`E<n>` and `ETF`). `signal_status` per ticker: `fired` (an event in the
window: a fact whether or not the ticker is still monitored), `no_signal` (monitored, nothing fired), **`not_covered`** (not monitored, nothing fired: the signal
jobs never looked, so it is never shown as "no signal"). Stored on every Quality row; the Reversal table shows a "Signals not covered" tag; the run summary stores
`quality_not_covered` of `quality_total`.

**Tags** (stored in `tags_json`, never filters): `late_trend` (weeks in Advance >= 52), `leveraged` (2 or 3), `held_back_by_moat` (blended Fundamentals >= 70, Overall
< 70: only the Moat multiplier does it), `why_not_quality` (Momentum-only stocks: the raw stored Overall verdict, the steps below the pass line, the incomplete
steps, the moat; the page draws "May not pass", never "Fail"), `deep_pullback` (a Momentum row that passes the B2 chart test), `signal_status` (Quality), `market` (the latest `MarketBreadthSnapshot`
on or before the as-of date: % above 50/200-day SMA, net new highs) and `sector` (the sector ETF's stage and momentum rank, the sector's breadth snapshot).

## Tables (new, insert-only; no existing table changed)

`OpportunityRun`: `kind` ("weekly"), `as_of_date`, `last_bar_date`, `universe_size`, `rules_hash`, `rules_version`, `score_formula_version`, `weights_version`,
`created_at`, `summary_json` (counts per list/tier/rule_id, ranked-universe sizes, gate drops, stale stage and score row counts, market context). Unique on
`(kind, as_of_date)`. `OpportunitySnapshotRow`: `run_id`, `list_name` (momentum/reversal), `ticker`, `tier`, `list_order`, `rule_ids_json`, `tags_json`, and a frozen copy
of the inputs (`overall_score`, `steps_score`, `overall_verdict`, `weinstein_stage`, `vs_ma_pct`, `ma_slope_pct`, `mansfield_rs`, `momentum_rank`, `close`, `atr`
(Wilder 14), `adv_usd`, `sector`, and `inputs_json` for the rest: step scores and verdicts, moat, weeks in Advance, 3/12 month returns, drawdown, B2 parts, signal
status, exchange). Unique on `(run_id, ticker)`: a ticker has one row per run, on one list. `TickerScore` and `TrendAnalysis` are overwritten nightly, which is why
the inputs are copied.

**Registry and backup.** Both are **KEEP** in `data/ticker_data_registry.py` (`opportunitysnapshotrow` in `REGISTRY`; `opportunityrun` has no ticker column, so it is in
`KEEP_NON_TICKER_TABLES`): the wipe never touches them. The nightly backup (`pipeline/backup_db.py`) copies the whole database with sqlite's backup API, so both tables
are in it with no change (checked: no table list anywhere in that script).

## The job

`uv run python -m pipeline.weekly_opportunity_snapshot [--as-of YYYY-MM-DD] [--force] [--dry-run]`, run from `backend/`. As-of defaults to the last completed XNYS
session. A rerun for an existing `(weekly, as_of)` is a no-op (and does not even compute); `--force` deletes that run and its rows and inserts the new ones in one
transaction (a failed insert leaves the old run intact); `--dry-run` computes and prints the counts, writes nothing. Bars are read in chunks of 60 tickers
(`CHUNK_SIZE`); only the closes of gate-passing tickers are kept for the ranking. First run on the live database: about 12 s, peak RSS about 173 MB (the bare interpreter
and pandas are about 115 MB of it). The run **refuses** (raises, writes nothing) when fewer than 90% of the gate-passing tickers have a Weinstein row computed from the
as-of bar (`MIN_FRESH_STAGE_SHARE`): the nightly stage job has not caught up and the lists would silently omit every stage-dependent name. A stage row not dated the
as-of date is treated as unknown for that ticker (it cannot be on a list), so an old as-of date cannot be rebuilt after the fact: `TrendAnalysis` holds the latest row only.

Registered in `core/cron_health.py` (`CRON_JOB_NAMES`, a weekly cadence of 8 days before it reads overdue, `JOB_METADATA`; it is no longer in `DISABLED_CRON_JOBS`) and scheduled in
`crontab.txt`. The default as-of is the last completed XNYS session at the moment it starts: on a normal Saturday that is Friday's close, in a week with a Friday holiday (Good Friday, the
observed Independence Day) it is Thursday's, and after a half-day Friday it is that Friday (`tests/test_weekly_opportunity_snapshot.py` pins the five cases with the real calendar).

**Tracked-universe protection.** A ticker on a list of a run whose as-of date is within `OPPORTUNITY_PROTECTION_DAYS` (180) is in the universe with reason `opportunity`
(order: after `added`, before `browsed`): it is not dropped by the 30-day view expiry, and the wipe sees it as protected (`PROTECTION_OPPORTUNITY`), so its bars keep
refreshing for outcome tracking. A delisted flag still wins. See [Tracked universe](tracked-universe.md).

## API (read-only)

`GET /api/opportunities/dates` (every run, newest first, with the two list sizes), `GET /api/opportunities/latest`, `GET /api/opportunities/{as_of_date}` (404 when none).
No POST/PUT/PATCH/DELETE exists (a test pins the route table). Rows come back exactly as stored (`OpportunityRowOut`), in list order: Momentum by composite momentum score,
Reversal by number of rules hit then composite.

## The page (`/opportunities`)

Header with a snapshot date picker (native Select over the stored runs), the Export menu (TradingView and thinkorswim; the multi-list item is not
offered) and **Add to watchlist** (the existing `AddToWatchlistButton`, manual only, with its bulk confirm; nothing is created or filled automatically). **Both act on the selected rows, see "Row selection" below** (before 2026-10-12 they acted on every row of the current tab and tier filter, with Add disabled when that was empty). Below it a hairline
market context strip (% above the 50 and 200-day SMA, net new highs, sectors in Advance), the Momentum / Reversal tabs with counts, an All / Quality / Momentum-only / ETF
segmented control with counts, and a hairline table (44px rows, soft tinted pills, sentence case): Ticker, Tier, Verdict, vs MA, Rank, Weeks in Advance (the Reversal tab
shows the rule that fired instead), ADV $M, Tags. The ticker opens its page in a new tab, as does the whole row (as in Momentum). **Tier wording per tab (display only, 2026-10-12):** on the Reversal tab the second tier is drawn "Technical only" (the segmented control, the tier pill and the Momentum-only stocks' why-not-Quality tag, which there reads "Fundamentals not passed" plus the first failed Overall step, "+n" for more, and the full verdict, steps and moat status in its tooltip); the Momentum tab keeps "Momentum-only" and "Not quality: ...". The stored tier is still `momentum_only` everywhere (`lib/opportunities.ts::tierLabel`, `tierFilterOptions`; the export files carry tickers only, so they have no tier wording). Verdict pills: Pass and Strong pass green,
Pass with caution amber, May not pass slate-blue. The footnote states the rules version and hash, the ranked universe, the not-covered count and any stale-score count.
The top nav has an "Opportunities" item (same-tab, like Momentum).

## Row selection (2026-10-12)

Each table row has a `Checkbox` (neutral checked style, `aria-label` "Select <ticker>"); the header checkbox ("Select all shown") selects exactly the rows shown (current tab plus tier filter) and shows the indeterminate dash when only some of them are selected; clicking it when all are selected deselects the shown rows only. **Selection is held by ticker** (`selected` in `app/opportunities/page.tsx`): it survives the tier filter and the Momentum / Reversal tabs (a ticker is on one list per run, so it names one row), and is cleared when the snapshot date changes and after a successful Add to watchlist. Shift-click selects the range of shown rows from the last one clicked (to the state the clicked row is moving to); space on a focused checkbox toggles it. A checkbox click (and the padding of its cell) never triggers the row click or the new-tab ticker open. A fixed-height status line above the table (`h-8`, so nothing shifts) reads "12 selected" with a "Clear" text action, or a transient notice (5 s). No control is disabled: a control with nothing to act on answers when used.

- **Add to watchlist** acts only on the selected rows (both tabs, any tier, in the run's order), labelled "Add 12 to watchlist". With nothing selected it opens nothing, sends nothing and shows "Select at least one ticker" in the status line. The watchlist menu, its bulk confirm ("Add 12 selected tickers to ...?") and the add calls are the existing ones. The ETF-only list is offered only when every selected row is an ETF. After a successful add the selection is cleared and the line reads "Added 12 to “Growth”" (with "(n already there)" when the bulk call reports some). A single selected ticker uses the single-add call, so the menu shows Remove for a list that already holds it (the existing control, unchanged).
- **Pick rows** are written exactly as before, server-side, in the same request: the page sends `opportunity_run_id` of the run shown (the latest, or the selected past snapshot), the backend stores `(as_of_date, ticker)` for each submitted ticker that is a row of that run. A bulk add records every submitted ticker (including any the list already held, as since Phase 2a); a single add records only when it succeeds (409 records nothing); a pick failure never fails the add. Adding from any other page sends no run id and records no pick. No backend change.
- **Export** acts on the selected rows when there are any, otherwise on everything in the current view (tab plus tier filter), never on the whole weekly run. The trigger says which: "Export 12 selected" or "Export 55 shown". The formats are the existing ones (`buildTradingViewText` grouped by sector, with the exchange prefix; thinkorswim bare symbols, one per line). The file name is `opportunities-<list>-<selection|view>-<as_of_date>[_thinkorswim].<ext>`; a selection that spans both lists names both (`momentum-reversal`). With nothing to export the status line says "Nothing to export" and no file is written. There is no "export the whole weekly run" option.

## Cron status

**Enabled 2026-10-12.** `0 4 * * 6` in `backend/crontab.txt`, installed with `crontab crontab.txt` from `backend/`. The server clock is UTC (`Etc/UTC`), so 04:00 Saturday is 00:00 Saturday in New York
(EDT; 23:00 Friday in winter) and **12:00 noon Saturday in Hong Kong** (UTC+8). It runs after the Friday-session nightly chain (1:00-3:25) and the 3:30 backup. The first scheduled run is
**Saturday 2026-10-17 04:00 UTC** (as-of Friday 2026-10-16); the 2026-10-09 run already exists from the manual run. The cadence slack is 8 days (a missed Saturday reads overdue the next Sunday
after a day of slack).

**Disable again:** comment the crontab line, add a `DISABLED_CRON_JOBS` entry for `pipeline.weekly_opportunity_snapshot` in `core/cron_health.py` (the wiring test requires a disabled job to be
absent from the crontab and every other job present), `crontab crontab.txt`, check `crontab -l`. **Check a run:** `SELECT as_of_date, created_at FROM opportunityrun ORDER BY as_of_date DESC LIMIT 2;`
and the Settings > Status page.

## Outcome tracking (phase 2a, built 2026-10-12)

Whether each listed name later beat the market. Stored data only, no FMP call, no LLM. Nothing here is shown on a page or served by the API yet (no Scorecard UI). **Conventions (agreed):**

- **Price-only returns**, never dividend-adjusted (the basis of the sector performance and momentum lenses).
- **Entry is the first session's OPEN after the as-of date.** SPY's bar dates are the session calendar (holidays and half-days need no calendar of their own). Horizon N is the Nth bar after the entry bar, N = 5, 10, 20, 60; the exit is that bar's CLOSE. The entry bar is bar 1 of the position for the stop, `worst_move`, `best_move` and `max_drawdown` windows (the window is the entry bar through the horizon bar).
- **Stop: intraday, 10% below entry.** A bar's low <= 0.9 x entry is a stop hit, the entry bar's own low included. A gap below the stop fills at the open: `stop_fill_return = min(-10%, open / entry - 1)`. `forward_return` is the buy-and-hold return; the stop never changes it, it is recorded beside it. A stop is path-dependent and final: it is written as soon as it occurs, on every horizon row whose window contains it, while the horizon is still `pending`.
- **Benchmarks:** SPY is the headline (`spy_return`, `excess_vs_spy`, entry open to the same exit date's close); the ticker's own sector ETF (`SECTOR_TO_ETF` on the stored `TickerScore.sector`) is the second. An ETF, or a stock with no mapped sector ETF, has `sector_etf = null` and null sector fields: it is compared with SPY only.
- **Censored rows are excluded from means.** A horizon is `censored` when the ticker is missing the entry or the horizon bar and SPY is already more than `CENSOR_GRACE_SESSIONS` = 3 sessions past the horizon date; `censor_reason` is `delisted` (flagged), `left_universe` (no longer tracked) or `stale` (neither). The row still stores the return to the last available bar (`exit_date`, `exit_close`, `forward_return`) as a sensitivity line. A `complete` row is frozen and never recomputed. **Grace period:** a censored row stays revivable for `CENSOR_REVIVE_DAYS` = 14 calendar days from `first_censored_at` (the day it was first censored; the clock never restarts): the updater re-evaluates it on every run, and if the missing bars have appeared it becomes `pending` or `complete` again with `censor_reason` and `first_censored_at` cleared. A temporary price-data gap looks exactly like a delisting, so freezing at once would freeze a hole for ever. After the 14 days the row is frozen like a `complete` one, even if the data returns. A real delisting simply stays censored (re-evaluated, unchanged) until it freezes. A censored row with no `first_censored_at` (written before the column) is stamped at its next evaluation. Readers are unaffected: censored rows are still excluded from means and keep the sensitivity return; a revived row is no longer censored.
- **`entry_gap_pct`** is the entry open against the frozen as-of close; `entry_gap_flag` is true beyond 25% (a gap that large means the list's price was not the price anyone could pay).
- **The pool is stored, hidden and unused.** `OpportunityPoolRow` keeps every gate-passing ticker of each run, whether it was listed or not, so a later step can compare the listed names with the ones the rules left out. Nothing reads it yet and no page shows it. Outcome rows exist for the listed snapshot rows only.
- **Picks.** `OpportunityPick` records the names the user chose with the manual Add to watchlist action on the Opportunities page (the run shown, latest unless a past snapshot is selected), so a later scorecard can compare the user's picks with the lists. The action itself is unchanged. **A pick is keyed by `(as_of_date, ticker)`, not by run id, and nothing ever deletes one** (see "Picks" below).

Tables (insert-only, KEEP in the data registry, in the nightly backup): `OpportunityPoolRow` unique on `(run_id, ticker)`; `OpportunityOutcome` unique on `(run_id, ticker, horizon)`; `OpportunityPick` unique on `(as_of_date, ticker)` (no run id, no watchlist id: join to the run, snapshot and outcome rows through `as_of_date` plus `OpportunityRun.kind = 'weekly'`); `OpportunityOutcomeRun` (one row per updater run: its heartbeat-style result, and the SPY bar date it saw). Pure engine: `scoring/opportunity_outcomes.py`. Updater: `pipeline/opportunity_outcome_update.py` (scheduled nightly at 03:40 UTC, see "Scheduled" below).

**The weekly job and the pool.** `persist_run` writes the run, its snapshot rows and the pool in ONE transaction (`ComputedRun.pool`, built in `compute_run` from the same features: exactly the gate-passing tickers, so `pool_rows` equals `gate_passed`). The rules and `RULES_VERSION` are unchanged (the pool is not a rule). A rerun for an existing date is still a no-op that does not compute. **`--force`** deletes that run's snapshot, pool and outcome rows and inserts the replacement in the same transaction (a failed insert leaves everything as it was); the counts come back as `deleted`. **It never touches picks** (they are keyed by `as_of_date`, so a rebuilt run, which takes over the old run's id because sqlite reuses the highest id, neither deletes nor re-attaches them; first built keyed by run id and fixed 2026-10-12). The pool needs the as-of stage rows (`TrendAnalysis` holds the latest row only), so it can only be captured while the nightly trend job has not moved past that session; if the stage rows are gone the run refuses as before (the existing run, pool or not, is left untouched).

**The updater.** `uv run python -m pipeline.opportunity_outcome_update --once | --dry-run | --run-id N | --as-of D` from `backend/` (one of the four is required). Orchestration `data/opportunity_outcome_data.py::update_outcomes`; zero FMP calls (cache read only). Every listed snapshot row gets four outcome rows on the first run (seeded `pending` when it cannot be priced yet); only `pending` rows are recomputed, a pending row is written only when a value changed, and `complete` / `censored` rows are never touched. Only completed bars are used (a bar after the last completed session, or a last bar written before its own session's close, is dropped, SPY's included). SPY and the sector ETFs are read once, every other ticker in chunks of 60. A ticker that fails to read or price keeps its rows as they were (a failed bar read skips the whole chunk the same way) and the run is `partial`. A normal run is a **no-op unless SPY has a bar newer than the last run's** or a listed row has no outcome rows yet; `--run-id` / `--as-of` skip that check; `--dry-run` writes nothing. **Result record:** one `OpportunityOutcomeRun` row per real run (`running` -> `success` / `noop` / `partial` / `failure`, the message, the SPY bar date it saw, a JSON summary), the next run's source for "SPY has a new bar"; a partial run stores no SPY date so the next run retries. It sits beside the `CronRunLog` heartbeat (which the Scheduled Jobs page reads) because it carries the SPY bar date the no-op rule needs.

**Scheduled (2026-10-12).** `40 3 * * *` in `backend/crontab.txt`: every night at **03:40 UTC (11:40 Hong Kong)**, `-m pipeline.opportunity_outcome_update --once`, log `backend/logs/opportunity_outcome_update_cron.log`. The server clock is UTC. Timing evidence (CronRunLog, 10 nights to 2026-10-12): price-target ended by 03:20:10 at the latest, the 03:25 score recompute by 03:26:22, the 03:30 backup by **03:35:10** at the latest (usually 03:33), so 03:40 starts at least 4m50s after the last job of the chain. The updater itself is seconds (1.7-5 s on the first 79 rows; chunked reads, about 130 MB peak), and the Saturday weekly job starts at 04:00, 20 minutes later, so the two never overlap. Registered in `core/cron_health.py` (`CRON_JOB_NAMES`, daily cadence 36 h, `JOB_METADATA` "Prices the weekly opportunity lists' outcomes ... no FMP calls", 3:40 AM) and wrapped in `cron_heartbeat` (`run_scheduled` in the job file). **Heartbeat rules:** a result or a normal "no-op: SPY has no bar newer than ..." (weekends, market holidays, a night the bars did not move) is **success**, with the one-line message; an exception (no SPY bars, a crash) is **failure**; ticker-level failures are a `partial` run that stays green unless they pass `check_failure_threshold` (all attempted failed, or at least the rate limit of 25 or more attempted), which is **failure**. A dry run writes no heartbeat. `tests/test_cron_wiring.py` pins the slot (after the backup by 8+ minutes, 15+ minutes before the Saturday job). *Caveat:* a SPY cache that stops moving for days reads as a green no-op here; the nightly bar-cache job (1:05) and the stale-data checks are what flag that.

**Picks.** The Opportunities page passes the id of the run it shows to the existing Add to watchlist call (`opportunity_run_id` on `POST /api/watchlists/{id}/tickers` and `/tickers/bulk`); the same request then calls `data/opportunity_data.py::record_picks`, which resolves the run to its `as_of_date` and stores the pick under `(as_of_date, ticker)` (`picked_at`, `source` = `opportunities_page`; no watchlist id). A bulk add records every ticker submitted that is a row of that run (whether or not the list already held it); a single add records the ticker only when the add succeeds (a 409 for a ticker already on the list records nothing); a refused add (the ETF-only list, the cap) records nothing. Picking the same ticker again for the same `as_of_date` is a no-op (the first `picked_at` stays); from two different dates it is two picks. A run id the run table does not know, a ticker the run never listed, or a failing pick write is ignored and never fails the add. The latest run is the one sent unless a past snapshot is selected. **Nothing deletes a pick:** not `--force`, not removing the ticker from a watchlist, not deleting the watchlist, not the ticker leaving the universe or being wiped (`opportunitypick` is KEEP in the registry), not a deleted run (a pick whose `as_of_date` has no run is kept as is). Migration (2026-10-12): the table was first keyed by `(run_id, ticker)`; `core/db.py::_migrate_opportunity_pick_key` rebuilds such a table once, copying every pick with its run's `as_of_date` (a pick whose run is gone keeps the old table as `opportunitypick_unmapped` rather than being dropped). The live table was empty, so it was simply re-created.

## First run (as of 2026-10-09), rules v2

Universe 608 (580 tracked stocks + 28 ETFs), 595 through the gate (dropped: 7 illiquid, 4 short history, SPY, 1 stale bar). Ranked: 569 stocks, 23 ETFs, 3 leveraged ETFs.
**Momentum 55** (Quality 25, Momentum-only 24, ETF 6); **Reversal 24** (Quality 18: B1 3, B2 5, B3 10; Momentum-only 5 B2; ETF 1 B2); overlap 0; 1 `deep_pullback` row (AMAT).
The v1 run (rules without the stage split) was Momentum 64 / Reversal 27 with 4 tickers on both (AMAT, CLS, KLAC, SOXL). Nine names left Momentum for Reversal or for neither because
they are fresh Advances (KLAC, CLS, SOXL moved to Reversal through B2; CRDO, META, MPWR, NEM, NOW, SWKS fell off for lack of a B2 pass), and ALAB and BB, which were Reversal only through
B2 in an established Advance, are on neither list (they fail the Momentum extension ceiling).

Against the 2026-10-11 preview (A: Quality 30, Momentum-only 93, ETF 7; B2 3 / 7 / 1; B1 3; B3 10), still on v1 rules: with the preview's settings the same code gave Momentum-only 93, ETF 7, Quality 29
(the one difference is the liquidity gate, which also applies to Quality: the OTC EVVTY, $1.9M a day, is out). Momentum-only 93 -> 92 (the $25M floor) -> 84 (ceiling 15) -> 64 (weeks in Advance <= 52) -> 63
(3 month <= 30%) -> 61 (12 month <= 150%) -> 28 (top quintile instead of top third); the v2 stage split then takes it to 24. Quality B2 uses a 20% drawdown threshold (the preview used 30%). 50 of
the 118 Quality stocks are not on a monitored list; 5 of the 10 B3 names fired in the window but have since left the monitored lists.

## First outcome run (2026-10-12)

The 2026-10-09 run was rebuilt with `--force` to capture its pool: 595 pool rows (equal to the 595 gate-passing tickers, 79 of them listed, the same Momentum 55 / Reversal 24), 12 s, peak RSS 174 MB. The updater then seeded 316 outcome rows (79 listed x 4 horizons), all `pending`: the first session after the as-of date (Monday 2026-10-12) had not traded yet, so there is no entry bar, no stop and no return. 1.7 s of work, peak RSS about 130 MB. A second `--once` was a no-op (SPY has no bar newer than 2026-10-09). The first real figures arrive after Monday's close.

## First scheduled run

The first run is **Tuesday 2026-10-13 03:40 UTC (11:40 Hong Kong)**. Monday's session (2026-10-12) will have closed and the 01:05 bar job will have stored its bar, so SPY is newer than 2026-10-09: a real run. It should give every listed row its entry bar (`entry_date` 2026-10-12, `entry_open`, `entry_gap_pct`, `entry_gap_flag`) and the path so far (`worst_move`, `best_move`, `max_drawdown`, and a `stop_*` record for any ticker whose Monday low reached 10% below its open), with all 316 rows still `pending` (horizon 5 needs the 2026-10-19 bar, so the first `complete` rows come with the 2026-10-20 03:40 run). Expected message: `success: 1 run(s), 79 listed rows; complete 0, pending 316, censored 0, stops N; 0 created, 316 updated (SPY bar 2026-10-12)`. Scheduled Jobs page: "Prices the weekly opportunity lists' outcomes ...", Daily, 3:40 AM, last run OK with that message.
