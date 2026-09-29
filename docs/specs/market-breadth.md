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
date most tickers do have a bar for).

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
count). `universe` is in the key even though `"sp500"` was the only value for a while — the
table's own docstring anticipated the sector extension below, since this app's migration tooling
(`_add_missing_columns`) is additive-only and can't widen a primary key later.

Percentages are percentage POINTS; NULL when eligible is 0. Never pruned for the `sp500` row
(~100 B/row, ~365 rows/year is trivial) — see "Sector breadth" below for the sector rows' own
retention.

**20-day SMA metric added the same day as the initial ship**, as a fast companion to the 50/200
pair — same per-ticker rolling math and strict `close > SMA` rule. Its three columns
(`sma20_above`/`sma20_eligible`/`pct_above_sma20`) are nullable via the standard additive-schema
convention, so a pre-existing row reads `NULL` (meaning "never computed," distinct from
`sma20_eligible = 0`) until a backfill fill-pass or the next live run rewrites it. The 20-day
window needs fewer bars than 50/200/252, so it's always a superset of the other windows'
eligibility and never the binding constraint on the coverage gate below.

## Nightly job and coverage gate

`pipeline.nightly_market_breadth`, 3:35 AM (after the 3:10 trend job, which warms the shared
cache; before Warren's 3:40). Reuses the SAME `get_or_fetch_bars_batch` call the trend job
already made, so after it this is a warm-cache read (~3s, zero incremental FMP requests) — if
the trend job failed, this job self-heals with one live fetch. Universe = `load_sp500_tickers`
strictly (**not** the S&P 500 ∪ Dow union `load_universe_tickers` returns — the original
requested design named the latter, but since Dow ⊂ S&P 500 the two happen to be identical today;
the strict function was chosen anyway since it can't silently drift if a Dow-only name ever
appears).

**Coverage gate** (`MIN_COVERAGE = 0.97`): below it the job raises `InsufficientCoverageError`
(heartbeat failure) and **writes nothing**, so the page's own as-of date visibly falls behind
rather than showing plausible percentages over a shrunken universe. At/above it, missing tickers
are excluded from every count and recorded in `stale_excluded`.

**Live overwrites backfilled, never the reverse** (`store_snapshots(overwrite=True)` is a full
upsert; the backfill script uses `on_conflict_do_nothing`).

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
failures during the FMP daily-bar cutover (traced to the trend job's own cache not yet having
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

## UI

`app/breadth/page.tsx` / `app/breadth/[sector]/page.tsx`, `components/breadth/`: 4 latest-reading
stat tiles (20-day, 50-day, 200-day, net new highs, with denominators), then two synced recharts
panels (never combined into one dual-axis chart — a percentage series and a signed count series
would misread one as the other's scale on a shared axis) — a three-line 0-100% chart (20-day
`series-3`, 50-day `series-2`, 200-day `series-1`, drawn slowest-first so the most volatile line
sits on top, with a 50% reference line) and a diverging net-new-highs bar chart (`positive`/
`negative` by sign). Custom pan (drag, no `<Brush>` — tried and rejected for breaking `syncId`
alignment with the bar panel), no zoom.
