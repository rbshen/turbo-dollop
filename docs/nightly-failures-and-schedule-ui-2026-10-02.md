# Nightly failures, status honesty and the Scheduled Jobs layout (2026-10-02)

Report-only. No code, DB or crontab changes; no cron times touched (a separate reschedule task follows).
Evidence: `backend/logs/*.log`, `CronRunLog` and `fundamentalscache`/`tickerscore`/`watchlist*` (all read with
`mode=ro`), `crontab -l`, and the frontend source. No FMP call was made. Browser rendering was **not** verified:
the overlap in item 4 is derived from the CSS and the font's advance width, not seen.

"Most recent run" = the run that started 2026-10-01 02:00 UTC (it still used the 2:00-3:30 schedule; the 12:00-12:40
technical slots in `crontab.txt` and `crontab -l` have not fired yet). Times below are server time (UTC).

## Summary

1. **The 8 price-target "failures" are not failures.** All 8 got HTTP 200 with an empty list from FMP. Two are ETFs
   (SPY, TECL), six have no FMP analyst coverage (ERIE, EVVTY, L, NWS, SINGY, PARA). It is the same 8 every night
   (6 of 6 nightly runs since the daily cadence began). None is rate-limit related. The job treats an empty result as a
   failure by design and does not skip ETFs (the fundamentals job does).
2. **The count will rise to about 15 tonight.** Seven more ETFs (GLD, IBIT, QQQ, SMH, SOXX, XLK, XLV) were first opened on
   2026-10-01 after the last run, so they now have cached profiles and are already in the job's universe (589 tickers,
   up from 582; checked read-only).
3. **The page cannot show a failed price-target run unless all tickers fail.** There is no threshold. 8 failed reads
   "Success" in a grey message, and so would 570.
4. **Three jobs show "—" because they never set a message, and they also cannot fail on per-ticker errors.** Their logs
   are clean apart from the same recurring intraday-bar warnings (SNDK, CRWV, BE).
5. **"5 skipped as delisted" is TWTR, WBA, EA, AVB, EQR**, identical every night, by design.
6. **The Monthly overlap is a 3px spill**: the 16-character label is about 115px wide in a 96px content box. Only the
   monthly label is at risk. One-class fix.
7. **Side finding for the reschedule task:** on 10-01 the fundamentals fetch ran 44.5 minutes (2,626 FMP calls) instead of
   the planned ~15, and overlapped price-target, score recompute and the backup. No errors resulted, but the slot
   assumptions in `crontab.txt` do not hold on a cache-expiry-wave day.

---

## 1. Price-target snapshot failures

### Run history (log coverage: 7 days)

The daily log starts 2026-09-25. The earlier job (`monthly_price_target_snapshot`) has only two tiny runs, so a 21-day
window does not exist.

| Run (start) | Processed | Failed | Notes |
|---|---:|---:|---|
| 09-25 07:12 (518 tickers, old S&P+Dow scope) | 518 | 4 | BF-B, ERIE, L, NWS. BF-B was then fixed by `PRICE_TARGET_SYMBOL_OVERRIDES` |
| 09-25 07:54 (manual, 63 tickers) | 63 | 6 | EVVTY, PARA, SINGY, SPY, TECL, BF-B |
| 09-26 02:10 | 580 | 8 | Served from the 1-day cache: only 2 FMP calls (see 1.4) |
| 09-27, 09-28, 09-29 02:10 | 581 | 8 | same 8 |
| 09-30 02:10 | 581 | 9 | same 8 plus **ADP**: `502 Bad Gateway`, transient, passed the next night |
| 10-01 03:10 | 582 | 8 | same 8 |

### 1.1 The 8 failed tickers (every run 09-26 to 10-01 unless noted)

All eight: HTTP **200 OK**, body `[]`. The job raises `ValueError("no price-target consensus available")`. The empty
`[]` is also cached under `price_target_consensus/latest` (so the next night's fetch is a normal refetch, not a retry
storm). None has a `PriceTargetSnapshot` row.

| Ticker | What it is (cached profile) | Why it is in the universe | FMP response | Class | Repeats nightly? |
|---|---|---|---|---|---|
| ERIE | Erie Indemnity, NASDAQ | S&P 500 member | 200 `[]` | No FMP coverage | Yes, 6/6 |
| L | Loews Corp, NYSE | S&P 500 member | 200 `[]` | No FMP coverage | Yes, 6/6 |
| NWS | News Corp class B, NASDAQ | S&P 500 member | 200 `[]` | No FMP coverage | Yes, 6/6 |
| EVVTY | Evolution AB ADR, OTC | has a TickerScore row | 200 `[]` | No FMP coverage (OTC ADR) | Yes, 6/6 |
| SINGY | Singapore Airlines ADR, OTC | has a TickerScore row | 200 `[]` | No FMP coverage (OTC ADR) | Yes, 6/6 |
| PARA | FMP's profile now says **Banzai International, Inc. Class A**, NASDAQ, market cap about $2.3M | has a TickerScore row (overall 30) | 200 `[]` | **Renamed/re-mapped symbol.** Paramount's successor, PSKY, is tracked separately and returns targets | Yes, 6/6 |
| SPY | State Street SPDR S&P 500 ETF, AMEX | has a TickerScore row (`is_etf`) | 200 `[]` | **ETF** (no analyst targets) | Yes, 6/6 |
| TECL | Direxion Daily Technology Bull 3X ETF, AMEX | has a TickerScore row (`is_etf`) | 200 `[]` | **ETF** | Yes, 6/6 |

Classification totals: ETF/fund 2; no coverage 5 (ERIE, L, NWS, EVVTY, SINGY); renamed/re-mapped 1 (PARA);
delisted 0 (delisted tickers are already excluded from this universe); FMP error 0 (the only error in 7 days was the
single ADP 502 on 09-30); timeout 0; code error 0.

PARA needs an owner decision, not a code fix: nothing in the DB says why it is tracked, and the app is scoring an
unrelated micro-cap under a symbol the user probably remembers as Paramount.

### 1.2 Rate limits: ruled out

- Every one of the 8 requests returned `200 OK` in all three most recent runs checked line by line. No 429 in the job's
  `_cron.log` (the 12 grep hits for "429" are ticker counters like `[429/580]` and millisecond timestamps).
- The overlap is real: on 10-01 the fundamentals fetch ran 02:55-03:39 and price-target ran 03:10-03:19, each pacing at
  220 req/min in its own process (about 440/min combined). Neither log has a single non-200 response in that window, and
  price-target took 581.8 s, in line with its 513-615 s range on nights with no overlap. The one 5xx (ADP, 09-30 02:10)
  happened when fundamentals had already finished (02:05).
- `FMPClient` retries only 429s, so the ADP 502 was not retried. One transient miss in 7 nights; not worth a change.

### 1.3 The 7 ETFs (and every other ETF in the tracked universe)

The profile cache has **9** ETFs: GLD, IBIT, QQQ, SMH, SOXX, SPY, TECL, XLK, XLV. `known_etf_tickers` finds the same 9.

- SPY and TECL were already in the universe (TickerScore rows), so they fail nightly (table above).
- The other 7 had their profiles first cached on 2026-10-01, 17:09-22:09, **after** the last price-target run (03:10), by
  the new ETF page. Not one appears in any price-target log. `load_us_price_target_universe` now returns **589**
  tickers including all 9 (read-only run). **Expect about 15 failures tonight** (8 + 7), assuming FMP answers `[]` for
  those 7 as it does for SPY and TECL. That is not verified (no live call was made) but is what the 9-of-9 `etf_info`
  and the spec's "ETFs have no analyst data" predict.
- The `ETF` watchlist is empty today, so it is not what feeds them; opening an ETF page is enough.
- Every future ETF opened, however briefly, will add one permanent nightly "failure".

### 1.4 How the job counts failed vs "no data expected"

`backend/pipeline/nightly_price_target_snapshot.py`:

- There is **no notion of "expected"**. Any exception in `_snapshot_one_ticker` increments `failed`.
- An empty or absent result **is explicitly a failure**: `raise ValueError("no price-target consensus available")` (the
  comment cites "FMP returned an empty body"). `docs/specs/price-target.md` repeats it ("counted as a failure").
- **ETFs are not skipped.** `load_us_price_target_universe` filters delisted tickers and non-US listings only. By
  contrast `nightly_fundamentals_fetch.load_fundamentals_fetch_universe` removes `known_etf_tickers`.
  `known_etf_tickers` is already shared (`data/etf_data.py`), so the filter is available.
- The spec already calls "about 8 failures" normal ("expected, not a regression"). So the number exists purely as noise.
- Cache side effect (relevant to the reschedule): `price_target_consensus` has a 1-day staleness window
  (`now - fetched_at < 1 day` in `core/cache.py`). On 09-26 the job started about 19 h after the previous fetch, so 578 of
  580 tickers were **served from cache with 2 FMP calls**, and "today's" snapshot rows were yesterday's values. A job
  moved earlier than 24 h after its previous fetch will do this again.

---

## 2. Status honesty

**How the page decides.** `core/cron_health.py::_job_health` reads only the latest `CronRunLog` row:

| Latest row | Health shown |
|---|---|
| no row | Unknown |
| `skipped` | Skipped |
| `failure` (an uncaught exception reached `cron_heartbeat`) | **Failed** (red message) |
| `success`, last success within cadence (36 h daily, 8 d weekly, 35 d monthly) | **Success** |
| otherwise | Overdue |

For `success` the `error_summary` (set via `run.message`) is shown **as plain tertiary-grey text**
(`ScheduledJobsSection.tsx`: only `failed` and `overdue` colour the message).

**What a run with 8 failed shows.** Green "Success" pill, grey "574 written, 8 failed". That is exactly the 10-01 row.

**Threshold.** None. `record_outcome` raises (heartbeat `failure`) only when `processed and failed == processed`. So
573 of 582 tickers failing would still read "Success". There is no "partial" state; the health model has five values
(`ok/failed/overdue/unknown/skipped`) mirrored in `CronJobHealthOut`, `STATUS_PILL` and the tests.

**Should the expected failures be excluded?** Yes. Right now a real regression (say 8 more tickers start failing with
502s) would be invisible against a standing "8 failed", and tonight's 15 will look like a regression when it is not.
Recommended shape, smallest first: (a) skip known ETFs in the universe (removes 2 now, 7+ tonight, all future ETFs);
(b) count "FMP answered 200 with nothing" separately from real errors, e.g. `"574 written, 6 no coverage, 0 failed"`;
(c) make `record_outcome` raise when *real* failures exceed a threshold (suggest 5% of processed), which reuses the
existing red "Failed" state and needs no new health value. A new "partial/warning" pill would be cleaner but touches
the type, the pill map, the tests and the design system's Status table, so it is not the smallest change.

---

## 3. Other messages

### 3.1 "5 skipped as delisted" (nightly_trend_calculation)

| Ticker | Name | Why flagged | `delisted_at` |
|---|---|---|---|
| TWTR | Twitter, Inc. (delisted) | delisted | 2026-09-24 10:17:02 |
| WBA | Walgreens Boots Alliance | delisted | 2026-09-24 10:17:02 |
| EA | Electronic Arts | delisted | 2026-09-24 10:17:02 |
| AVB | AvalonBay Communities | merged into Vivmark Residential (VMRK) | 2026-09-24 10:17:02 |
| EQR | Equity Residential | merged into Vivmark Residential (VMRK) | 2026-09-24 10:17:02 |

Same five in every run in the log (09-24 to 10-01), same timestamp (written once by a manual `stale_data_health_check`
under the old staleness heuristic; `docs/specs/fmp-data-and-bar-cache.md` "Delisted-ticker handling" says so). The reasons
in the third column are the spec's, not independently verified here.

**Why they stay:** `load_full_tracked_universe` unions in every ticker that ever had a `TickerScore` row, and "Nothing is
ever deleted" is a documented decision (history, Watchlist and ticker-page data stay). The flag only stops price-bar
fetching, so the bar jobs report the skip count. The price-target job also drops them, but silently. Side note:
`nightly_fundamentals_fetch` and the score recompute still process them (587 vs the 582 price-target universe).

Pure noise for the page: a constant "5" that carries no information; it only matters if the count changes.

### 3.2 Jobs showing "—"

`ScheduledJobsSection` prints `job.message ?? "—"`, and `message` is `CronRunLog.error_summary`, which is only set when a
script assigns `run.message`. These five never do:

| Job | `run.message` set? | Can per-ticker failures fail the run? | Latest log (7 days) |
|---|---|---|---|
| nightly_fundamentals_fetch | no | no (`Failed: 0` is logged, never read) | Clean. 10-01: 587 processed, 0 failed, **2,626 calls, 44.5 min** (vs 5-324 s on the previous four nights) |
| nightly_entry_signal_calculation (BB+RSI) | no | no | Clean: 105 processed, 0 failed. Recurring WARNING: FMP intraday short sessions for SNDK (2025-02-13, 6/7 bars), CRWV (2025-03-28, 4/7), BE (2024-11-14, 4/7) |
| nightly_warren_signal_calculation | no | no | Clean: 105 processed, 0 failed, same SNDK/CRWV warnings every night |
| nightly_score_recompute | no (no `as run` at all) | no | Clean: 587 processed, 0 skipped, 0 failed |
| backup_db | no | exceptions only | Clean: 145.9 MB, pruned 2 old backups |

No hidden failures. Two things worth knowing:

- **The fundamentals run on 10-01 was 8-57x longer than the previous four nights.** The cache-row dates show the cause is a weekly expiry wave:
  517 of 594 `profile` rows were refetched on 10-01 (61 the day before), seven days after the 09-24 bulk refresh. (That
  the wave is the cause is an inference from those dates; I did not trace each call.) It will recur and drift. The
  consequence: it overlapped price-target (03:10-03:19), the recompute (03:25) and the backup (03:30-03:33). The backup
  uses SQLite's backup API (consistent snapshot) and the fundamentals job recomputes each ticker's score inline, so
  nothing broke, but `crontab.txt`'s "15-minute window" is wrong on a wave day.
- If all tickers failed in fundamentals, BB+RSI or Warren, the page would still say Success with "—". Those three jobs are
  the blind spot; price-target is the only one with the all-failed guard.

---

## 4. Monthly tab text overlap

**Where the numbers come from** (`frontend/components/settings/ScheduledJobsSection.tsx`):

- `<Table className="table-fixed">` with `<colgroup>`: Description `w-[45%]`, **Time `w-28` (112px)**, Status `w-28`, Message auto.
- `TableCell` (`components/ui/table.tsx`) is `pl-0 pr-4 whitespace-nowrap`. Content box = 112 - 16 = **96px**.
- The Time cell is `font-mono text-xs` (12px). The mono face is IBM Plex Mono (`app/layout.tsx`), advance 0.6 em = 7.2px
  per character.
- The label comes from `JOB_METADATA["pipeline.monthly_momentum_snapshot"].time_label` = `"1st–5th, 2:50 AM"`
  (`core/cron_health.py:164`): 16 characters x 7.2 = **about 115px**.

**Why it overflows.** Nowrap text has no wrap point, a fixed-layout cell does not grow, and `overflow` is visible, so the
text runs 19px past the content box. The cell's own padding absorbs 16px; the last ~3px land in the Status column, whose
pill starts at the cell edge (`pl-0`). That is the "overlap" with the Success badge (the pill paints over the final
glyph's edge).

**At narrower widths.** The Time column is a fixed 112px at any viewport, so the overlap is identical at every width.
Narrowing only changes Description (45%) and Message, which already use `whitespace-normal` and wrap. The `Table`
container is `overflow-x-auto`, so a very narrow screen scrolls instead.

**Other tabs.** Safe. Longest Daily label `12:05 AM` (8 chars, 58px); longest Weekly `Sun 1:35 AM` (11 chars, 79px). The
limit is 13 characters (94px). Only the monthly label exceeds it, and any future "1st-5th"-style label would too.

**Do tests or specs pin the label?** No literal. `test_cron_health_endpoint.py` compares the API to `JOB_METADATA`
dynamically; `test_cron_wiring.py` pins `sort_minutes` (not `time_label`) to the crontab; the frontend test uses
`"2:00 AM"` only; `docs/decisions.md` mentions "1st-5th" in prose only. `docs/design-system.md` has no rule on
table-cell wrapping, but the same table already uses `whitespace-normal` on its Description and Message cells, which is
the precedent.

**Smallest fix (recommended):** add `whitespace-normal` to the Time `TableCell` so the label wraps to
"1st–5th," / "2:50 AM". Two 16px lines fit the 44px row. One class; immune to any future long label; no label or backend
change. Alternatives: widen the Time column `w-28` to `w-36` (one class, but it takes 32px from Message and leaves the
fragility), or change the label (it cannot get shorter than 16 characters without losing "1st-5th"). Optional: one
frontend test asserting the Time cell wraps.

---

## 5. Proposal

| # | Change | Type | Size | Risk | Conflicts with docs |
|---|---|---|---|---|---|
| 1 | Skip known ETFs in `load_us_price_target_universe` (reuse `known_etf_tickers`, as the fundamentals job does) | Code | about 5 lines + 1 test | Low. An ETF never opened has no profile, so is not yet "known" and still fails once; ETF page has no analyst tab, so no consumer loses data | `price-target.md` "Universe" paragraph and its "~8 failures normal" sentence need updating |
| 2 | Count "FMP answered 200 / empty" as `no_coverage`, not `failed`; message becomes e.g. "574 written, 6 no coverage, 0 failed" | Code (+ tests) | about 20 lines | Low-medium: group-off mid-run also yields an empty result, so only a *cached empty row after a live 200* should count as no coverage | Contradicts `price-target.md` "An empty/absent FMP response raises per ticker (counted as a failure)" and the `test_nightly_price_target_snapshot.py` assertions on the message |
| 3 | `record_outcome`: raise when real failures exceed about 5% of processed (reuses the red Failed state) | Code | about 5 lines + 1 test | Low. Threshold is a judgment call; a bad FMP night would flip the run to Failed even though most rows were written | Extends the "all-failed" rule in `price-target.md` "Skip/failure status" |
| 4 | Set `run.message` in fundamentals, BB+RSI, Warren, score recompute, backup (e.g. "587 processed, 0 failed, 2,626 calls, 44.5 min"; backup "145.9 MB") and raise on all-failed like price-target | Code | about 10 lines per job | Low; additive. `recompute_all` already returns the counts | None found; `OPS_RUNBOOK.md` heartbeat section should gain a line |
| 5 | Monthly label: add `whitespace-normal` to the Time `TableCell` | UI only | 1 class (+ optional test) | None | None |
| 6 | Quiet the "5 skipped as delisted" suffix when the count is unchanged or move it to the log | Code (message text) | about 3 lines | Low; hides the count | None. Optional: it is noise, not wrong |
| 7 | Decide what to do with PARA (now Banzai): remove from tracking or leave | DB or owner decision | n/a | Do not auto-purge; "Nothing is ever deleted" is the documented rule | None |
| 8 | Reschedule inputs (not done here): (a) fundamentals needs a real window of up to about 45 min on a wave day (spec says up to ~65 min cold); (b) price-target must stay at least 24 h after its previous fetch or it serves cached values | Docs / reschedule task | n/a | Moving price-target earlier silently turns it into a cache read | `crontab.txt` and `decisions.md` "Known exposure" notes already half-flag this |

Suggested order: 1 + 2 + 3 together (one commit, price-target only; makes tonight's count honest), 4 as a second commit,
5 as a third (frontend only). 6 and 7 are optional. Nothing here needs a DB migration or a crontab change.

Also noticed, not in scope: `backend/OPS_RUNBOOK.md` still says the heartbeat wraps "15" jobs; `CRON_JOB_NAMES` has 21.
