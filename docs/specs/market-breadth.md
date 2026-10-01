# Market Breadth (`/breadth`, `/breadth/[sector]`)

S&P 500 breadth, one row per session: % of constituents closing above their own 20/50/200-day
SMA, and net new 52-week highs minus lows. Independent of Step 1-5/Overall Assessment scoring —
zero FMP fundamentals calls, no `FMP_ENABLED` guard needed. Bars come from FMP via
`SharedBarsCache` (split-adjusted close/high/low, no dividend adjustment — same basis and
rationale as [Sector Heatmap](sector-heatmap.md)).

## Methodology

Definitions live in `scoring/market_breadth.py` (pure). Every window is counted in each ticker's
**own** bars, never on a shared date index — a ticker with a real, isolated data gap inside its
trailing 252-bar window is correctly dropped from the 52-week count by rolling per-ticker,
rather than being disqualified by a `min_periods` check against a date-union frame (an early
implementation bug, caught and fixed before shipping: a strict `min_periods=252` on a date-union
frame silently shrinks the eligible denominator whenever even one ticker anywhere has a gap on a
date most tickers do have a bar for). The concrete case was FISV (500 real bars, one gap): the
date-union version dropped it from the 52-week count; rolling per ticker keeps it, so the live
52-week denominator is 500, not the investigation's 499.

- **SMA position** = `close > SMA` (strict, SMA includes today). The three windows
  (`SMA_WINDOWS = {"sma20": 20, "sma50": 50, "sma200": 200}`) drive the flags, counts, and
  snapshot columns from one shared definition.
- **52-week high/low = intraday High/Low** (a confirmed decision, not close-based) over the
  trailing **252 sessions including today, ties count, a full 252-bar window required**: new
  high = `high >= max(last 252 highs)`, new low = `low <= min(last 252 lows)`. Intraday was
  chosen over close-based as the common convention (charting platforms, FMP/other providers' own
  52-week figures) even though it's less internally consistent with the close-based SMA metrics.
- A ticker too young for a window is absent from that metric's `*_eligible` denominator, never
  counted as "below."
- Computed directly from `SharedBarsCache` raw bars, **not** `TrendAnalysis` — that table is
  latest-only, has no 52-week fields, and a failed fetch leaves an old row behind with no
  visibility into staleness at the per-ticker level this feature needs.

## Storage

`MarketBreadthSnapshot`: WIDE, PK `(universe, as_of_date)`, each metric its own column plus the
numerators/denominators (`sma20_above`/`sma20_eligible`, ... `hl_eligible`, `new_highs`,
`new_lows`, `net_new_highs`) and `stale_excluded` (constituents with no bar that session, in no
count). `universe` is in the key even though `"sp500"` was the only value for a while (the value is
`"sp500"`, matching `IndexConstituent.index_name`) — the
table's own docstring anticipated the sector extension below, since this app's migration tooling
(`_add_missing_columns`) is additive-only and can't widen a primary key later.

Percentages are percentage POINTS; NULL when eligible is 0. Never pruned for the `sp500` row
(~100 B/row, ~365 rows/year is trivial) — see "Sector breadth" below for the sector rows' own
retention. `is_backfilled` marks backfill rows.

**20-day SMA metric added the same day as the initial ship**, as a fast companion to the 50/200
pair — same per-ticker rolling math and strict `close > SMA` rule. Its three columns
(`sma20_above`/`sma20_eligible`/`pct_above_sma20`) are nullable via the standard additive-schema
convention, so a pre-existing row reads `NULL` (meaning "never computed," distinct from
`sma20_eligible = 0` / a NULL percentage on a session with no eligible tickers) until a backfill
fill-pass or the next live run rewrites it. This was an additive migration, not a rebuild:
`init_db()` is `create_all` (missing tables only) plus `_add_missing_columns` (adds any missing
nullable column to an existing table), so the three columns were ALTER-added to the live table —
a rebuild would have dropped the stored backfill rows and any live nightly row, which cannot be
recomputed. The API/TS types carry the same nullability and the UI renders it as a gap / "Not
computed yet", never 0. The 20-day window needs fewer bars than 50/200/252, so
`sma20_eligible` is always a superset of `sma50_eligible` (tested) and never the binding
constraint on the coverage gate below — the gate checks bar *presence* on the anchor session, not
per-metric eligibility, so it applies to the 20-day metric identically, and the backfill's
own keep-rule (>= 97% 252-bar eligible) already implies it, so the metric neither adds sessions
nor drops any.

**Fill pass** (`data/market_breadth_data.py::fill_missing_sma20`). The insert-only
`on_conflict_do_nothing` backfill skips an existing date entirely, so it can never give existing
rows the new columns. A second pass UPDATEs ONLY the three sma20 columns, ONLY where
`sma20_eligible IS NULL`, ONLY on `is_backfilled` rows: no other column is touched, a row that
already has a 20-day value is never overwritten, and a live (point-in-time) row is never filled
from today's constituents. A re-run fills 0.

## Nightly job and coverage gate

`pipeline.nightly_market_breadth`, 12:40 AM (after the 12:05 bar-cache job, which warms the shared
cache; before corporate events at 2:45). Reuses the SAME `get_or_fetch_bars_batch` call the 12:05 job
already made, so after it this is a warm-cache read (~3s, zero incremental FMP requests) — if
the 12:05 job failed, this job self-heals with one live ~503-request fetch (30s-5min) that could
overlap the next job's start (writer-lock contention only). Universe = `load_sp500_tickers`
strictly (**not** the S&P 500 ∪ Dow union `load_universe_tickers` returns — the original
requested design named the latter, but since Dow ⊂ S&P 500 the two happen to be identical today;
the strict function was chosen anyway since it can't silently drift if a Dow-only name ever
appears). Anchor = the latest session across the fetched bars that is `<=` the last completed
session (the Sector Heatmap's rule); a weekend/holiday run upserts the same anchor idempotently.
The job is wired into `CRON_JOB_NAMES`/`_EXPECTED_CADENCE_HOURS`/`JOB_METADATA`/`crontab.txt`/
`OPS_RUNBOOK.md`, enforced by `test_cron_wiring.py`. A `crontab.txt` edit alone changes nothing on
the box (it must be reinstalled from `backend/`); the job's activation record is in
`docs/archive/claude-md-history-fmp-migration.md`.

**Coverage gate** (`MIN_COVERAGE = 0.97`): 97% of constituents must have a bar on the anchor
session — **488/503 passes (15 missing), 487 fails** (pinned by a boundary test, and also asserted
on `sma20_eligible`). Below it the job raises `InsufficientCoverageError` (heartbeat failure),
names the missing tickers, and **writes nothing**, so the page's own as-of date visibly falls
behind rather than showing plausible percentages over a shrunken universe. At/above it, missing
tickers are excluded from every count, recorded in `stale_excluded` and warned in the log. The
gate checks bar presence only — thin-history tickers are handled by the eligible counts, not the
gate.

**Live overwrites backfilled, never the reverse** (`store_snapshots(overwrite=True)` is a full
upsert — a live row is point-in-time; the backfill script uses `on_conflict_do_nothing`).

## Backfill

`pipeline/backfills/backfill_market_breadth.py` (one-time, `--dry-run` supported), deliberately
NOT part of the nightly job's fetch. **Read-only against `SharedBarsCache`** — no fetch, no
writes — because widening the shared cache (409 tickers 2y → 5y) would make every later nightly
refetch pull the wider window (~+300k rows, permanently). A session gets a row only if >= 97% of
constituents have a bar AND >= 97% are 252-bar eligible (which implies SMA eligibility), so it
never stitches a subset-universe curve onto the index curve. **Survivorship-biased**: today's 503
constituents applied to every past date (a recent joiner counts in earlier months; removals aren't
tracked anywhere) — hence `is_backfilled`, the tooltip tag, and the page footnote. `--rebuild`
deletes ONLY `is_backfilled` rows (never a live nightly row) and recomputes them. Since the shared
cache now holds 5y of daily bars, the backfilled history spans ~4y (2022-09-26..2026-09-23 at the
last rebuild) — kept uncapped by decision, still survivorship-biased. The original run and the
20-day fill-pass run records are archived in `docs/archive/claude-md-history-fmp-migration.md`.

## Sector-level breadth (2026-09-22, shipped)

The same 4 metrics, computed per GICS/SPDR sector (`universe = "sector:<ETF>"`, e.g.
`"sector:XLK"`) by bucketing the SAME 503 S&P 500 tickers already fetched for the `sp500` row —
never a second fetch or a second per-ticker rolling computation. A 2026-09-22 feasibility
investigation found this almost entirely reuse: `IndexConstituent.sector` is already fully
populated (FMP's own 11-sector taxonomy, the same field the Screener's Sector filter already
uses), every sector's constituent roster is a strict partition of the exact same 503-ticker
universe already in `SharedBarsCache`, and `MarketBreadthSnapshot`'s schema needed zero change.

**Coverage gate at small sector size — the one real design decision the extension needed**,
flagged explicitly by the feasibility investigation rather than defaulted. A flat 97% gate
applied per-sector would fail on literally any single ordinary transient miss for the six
smallest sectors (Basic Materials at 20 constituents tolerates *zero* missing tickers at 97%).
**Resolved by a floor-based OR-gate** (`sector_coverage_ok` / `SECTOR_COVERAGE_FLOOR_MISSING`,
the "Option B" the investigation itself proposed rather than plain 97%): a sector's gate passes
on EITHER ≥97% coverage OR at most `SECTOR_COVERAGE_FLOOR_MISSING` tickers missing, whichever is
more permissive — so a small sector (~20 names) isn't blocked by a single stale/missing ticker.
One sector failing its own gate is isolated (logged, skipped) and never blocks the other 10
sectors' rows that night, unlike the market-wide row's own gate, which is an all-or-nothing raise.
Every gate check (sp500 and every sector, passed or refused) is additionally logged to
`MarketBreadthGateLog` so this provisional policy can be revisited from real data later.

The sector rows reuse the existing pure math (`scoring/market_breadth.py` is fully generic over
any ticker→frame dict, confirmed to need no change) and the existing `SectorEtfReturn`-adjacent
naming convention (`sector_universe(etf)` builds the `"sector:<ETF>"` string). Backfill
(`backfill_market_breadth.py`) draws from the same `SharedBarsCache` window every other
consumer's backfill draws from — deliberately never fetches, to avoid permanently widening the
shared cache's window for every future nightly refetch — and applies the same survivorship-bias
caveat the market-wide backfill already carries (today's sector membership applied to past
dates).

**Nav/UI decision, also flagged and resolved rather than defaulted**: one page with a sector
selector (`/breadth/[sector]`, a dynamic route reusing the existing chart/stat components,
`/breadth` itself staying the S&P-500-wide default), not 11 new top-nav entries — following the
same "N things render as rows/cards on one page" pattern every other multi-entity feature in
this app already uses (the Sector Heatmap itself, most directly on point, already treats these
same 11 sectors as rows in one table rather than 11 pages).

## The "Live →" marker — a naming/UX gap, not a data bug (2026-09-27)

A user-reported concern that the nightly job was "stuck" turned out to be a labeling issue, not
a broken job. **The nightly job had run and saved a row every night, and the newest row was
current** — confirmed directly against `CronRunLog` and the live `MarketBreadthSnapshot` table.

The "Live →" marker (`frontend/lib/marketBreadth.ts::firstLiveIndex` =
`series.findIndex(p => !p.is_backfilled)`) is not a "latest data" marker at all — it marks the
**first non-backfilled session** in the series, the boundary between backfilled history and live
history. That boundary is fixed at whichever date the backfill script's own cutoff happened to
land on, and **stays there permanently**, since it's by definition the earliest live row and
never moves forward — it will keep reading as "days ago" indefinitely, even on a perfectly
healthy, currently-up-to-date job, which is exactly what looked wrong to the reporting user.

Root-caused via the real `CronRunLog`/`MarketBreadthSnapshot` history: a handful of coverage-gate
failures during the FMP daily-bar cutover (traced to the 12:05 job's own cache not yet having
caught up to a specific session) caused one date to be written only by a later `backfill_market_
breadth --rebuild` re-run, landing it with `is_backfilled=1` sandwiched between otherwise-live
rows — which is why the marker's date sits several days before "today" rather than at the
literal start of the backfilled history.

**No fix made — three decision points left open**, carried forward here as the record of what a
follow-up would need to resolve, not resolved by this documentation pass:

1. **Relabel or reposition the marker.** It currently means "live history begins here." Options:
   a clearer label ("Recorded live from ..."), or additionally showing the latest-session date
   somewhere (the stat tiles already show the as-of date, so this may already be enough context
   once the marker's own meaning is clarified).
2. **If the intent is a contiguous live boundary**, treat a rebuilt-backfill row sandwiched
   between live rows as a gap (use the first live row *after* the last backfilled row instead of
   the first live row overall), or flip that one row's flag semantics. Framed as a genuine
   judgment call, since that specific row is truthfully survivorship-biased backfill, not
   incorrectly labeled.
3. **A separate, unrelated finding from the same investigation**: one orphaned `CronRunLog` row
   (status `running`, no `finished_at`) was noticed but not investigated further for whether the
   health view treats it as stuck.

The sector view (`BreadthSectorView.tsx`) reuses the same marker helper and inherits the
identical labeling ambiguity — the investigation did not separately query each sector universe's
own boundary date.

*Code-vs-doc note (verified 2026-09-29):* the frontend has since changed the marker's source.
`frontend/lib/marketBreadth.ts` no longer has `firstLiveIndex`; the chart uses
`liveBoundaryIndex`, which returns the row right after the LAST backfilled row (so a
rebuilt-backfill row sandwiched between live rows pushes the boundary past it — decision point 2
above, the "contiguous live boundary" option), or -1 when no live row follows. Points 1 and 3
were not re-checked.

## API

`GET /api/market-breadth` (`core/main.py`, `data/market_breadth_data.py::get_market_breadth`,
`MarketBreadthOut`): the whole history oldest-first plus `latest`; before any row,
`as_of_date: null, latest: null, series: []` (never a 404, including for an unrecognized
universe string). Takes one query param, `universe` (default `sp500`, or `sector:<ETF>` — see
"Sector-level breadth"); the original ship had no query params at all (YAGNI until a second
universe existed). No range param: the whole series is returned (~250 rows/year, never pruned).

## UI

`app/breadth/page.tsx` / `app/breadth/[sector]/page.tsx`, `components/breadth/`,
`lib/marketBreadth.ts`; top-nav "Breadth" opens in a new tab, like Sectors/Momentum (except when clicked from Momentum, Sectors, Breadth or Settings, where nav links go same-tab): 4
latest-reading stat tiles (20-day, 50-day, 200-day, net new highs, with denominators;
`sm:grid-cols-2 lg:grid-cols-4`), then two synced recharts
panels (never combined into one dual-axis chart — a percentage series and a signed count series
would misread one as the other's scale on a shared axis) — a three-line 0-100% chart (20-day
`series-3`, 50-day `series-2`, 200-day `series-1`, drawn slowest-first so the most volatile line
sits on top, with a 50% reference line) and a diverging net-new-highs bar chart (`positive`/
`negative` by sign). Custom pan (drag, no `<Brush>` — tried and rejected for breaking `syncId`
alignment with the bar panel), no zoom. It opens on the trailing year (all history if shorter).
Unlike the app's usual hidden-Y convention the axes are visible (0/25/50/75/100%; nice ticks for
the count), since a breadth level is read in absolute terms. Bars' sign is also encoded by
position about the zero line, so it isn't color-only. The dashed "Live →" marker appears only
once there is a non-backfilled session. Layout, colors/contrast, label collisions, the hover
tooltip and cross-panel sync, and narrow widths were never verified on screen (no browser).

**Known limits**: not holiday-aware (a holiday costs one extra harmless refetch, as for every
`SharedBarsCache` consumer); `constituents` is today's count from the weekly Wikipedia scrape (a
same-week index change is picked up a week late); the job imports the private
`_load_frames`/`_most_recent_completed_trading_date` from `clients/shared_bars_cache.py`
(`sector_heatmap_data.py` already sets that precedent).
