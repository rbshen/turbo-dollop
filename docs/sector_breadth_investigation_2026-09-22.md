# Sector-level market breadth — feasibility investigation (2026-09-22)

Investigation only. Nothing was implemented; no code, schema, or crontab was changed. All
queries were run read-only against the real `fathom.db` (`uv run python` one-liners, no
scratch files left behind).

Requested scope: extend the existing market-breadth feature (`docs/market_breadth_
investigation_2026-09-21.md`, shipped 2026-09-21 as `MarketBreadthSnapshot` / `scoring/
market_breadth.py` / `pipeline/nightly_market_breadth.py` / `/breadth`) down to the 11 SPDR
sector level — same four metrics (% above SMA20/50/200, net new 52-week highs − lows), one
breadth read per sector instead of one for the whole S&P 500.

## Summary

**Feasible, cheap, and almost entirely reuse.** Every piece this needs already exists:
per-stock sector membership is already a populated column, every sector's constituents are
already inside `SharedBarsCache` (they're a subset of the same 503 S&P 500 tickers the
existing job already fetches), and `MarketBreadthSnapshot`'s schema was explicitly designed
with a `universe` key for exactly this kind of extension — a sector breadth row needs
**zero schema change**. The right shape is to **extend the existing job and table**, not
build a parallel feature: reuse the one warm-cache bars fetch, partition it by sector, and
store each sector's row under its own `universe` value in the same table.

The one real risk is **cron-slot crowding**, not data or runtime: the 3:10–3:55 AM window is
already packed with 8 jobs and very little slack (Warren's own theoretical worst case, ~9
min, already eats nearly the whole gap before the 3:50 recompute). A new per-sector job
would need its own slot; folding sector computation into the existing 3:35
`nightly_market_breadth` job needs none.

The one real design question worth deciding before implementation is the **coverage-gate
threshold at small-sector sample sizes** (Basic Materials has 20 constituents; a 97% gate
tolerates *zero* missing tickers at that size) — see §5.

## 1. Sector-membership mapping: does it already exist?

**Yes, fully populated, no new source needed.** `IndexConstituent.sector` (`index_name=
"sp500"`) is set for all 503 rows, zero NULLs (checked live). It's FMP's own 11-sector
taxonomy (`sp500_scraper.py` fetches FMP's `/sp500-constituent` endpoint), the same field
`TickerScore.sector` already carries and the Screener's Sector filter already uses — not a
new fetch, not a new source, not Wikipedia-scraped GICS text.

Live distribution (2026-09-22):

| FMP sector | Count | SPDR ticker (proposed mapping) |
|---|---:|---|
| Technology | 85 | XLK |
| Industrials | 77 | XLI |
| Financial Services | 70 | XLF |
| Healthcare | 59 | XLV |
| Consumer Cyclical | 53 | XLY |
| Consumer Defensive | 33 | XLP |
| Utilities | 32 | XLU |
| Real Estate | 30 | XLRE |
| Communication Services | 22 | XLC |
| Energy | 22 | XLE |
| Basic Materials | 20 | XLB |
| **Total** | **503** | |

11 FMP sectors, 11 SPDR sector ETFs, one clean value each — the same 1:1 correspondence
`data/sector_heatmap_data.py::SECTOR_ETFS` already documents by name ("Technology",
"Financials", "Health Care", etc.), just keyed off FMP's label spelling instead of the
display name. A small hand-written dict (`FMP_SECTOR_TO_ETF`, 11 entries) is the only new
mapping needed — same style and size as the existing `SECTOR_ETFS` list, and it can live
right next to it.

**Caveat, not independently verified:** this is FMP's own sector classification applied to
our tracked S&P 500 list, not a live pull of each SPDR fund's actual current holdings —
State Street's real reconstitution can lag or occasionally disagree with FMP's sector text
for a specific reclassified name. No holdings diff was run (out of scope for a read-only
breadth signal, and the same class of approximation this codebase already accepts elsewhere
— `classify_company_type`'s sector/industry text matching has the identical shape and a much
higher bar, since it drives real scoring, not just a chart). Worth a one-line caveat on the
page itself, not worth deeper verification for this use case.

## 2. Coverage: does SharedBarsCache already have every sector constituent?

**Yes, by construction — no gap, no new tickers, no new fetch.** Every sector's roster is a
strict partition of the exact same 503-ticker S&P 500 universe `nightly_trend_calculation`
(3:10 AM) already fetches into `SharedBarsCache` every night, and the existing
`nightly_market_breadth` job already reads in full. A sector breadth computation is not a
new universe — it's the same 503 tickers, grouped. There is no case where a SPDR sector
ETF's real-world holding falls outside our tracked S&P 500 list to create a coverage gap,
because we aren't fetching the ETFs' real holdings at all — we're partitioning our own
already-covered universe by our own sector field (see the caveat in §1: this is the flip
side of that same approximation — it guarantees 100% coverage precisely because we never
try to reconcile against real fund holdings).

Confirmed live (from the market-breadth investigation, still current): `SharedBarsCache`
`1d` has 503/503 S&P 500 tickers, all with a bar on the last completed session; 409 back to
~2024-09 ("2y" tier), 89 (the Liquidity Zone tickers) back to ~2021-09 ("5y" tier), 5
shorter-history names (FDXF, HONA, Q, + 2 others). The three named thin-history tickers
checked here sit in Industrials (FDXF) and Technology (HONA, Q) — the two largest sectors,
so they don't concentrate disproportionately in any single small sector.

## 3. Runtime/cost: does grouping into 11 sectors cost more than one aggregate pass?

**Negligible incremental cost, and it can reuse the exact same fetch.** The existing job
already does, in order: (a) one `get_or_fetch_bars_batch` call for all 503 tickers (warm
read, ~1–3s per the 2026-09-21 measurement, since the 3:10 trend job already populated the
cache), (b) `ticker_flags()` — one 0/1 flag frame per ticker, computed once, and (c)
`aggregate_flags()` — a single `groupby(level=0).sum()` across all 503 tickers' flag frames.

Sector breadth needs no new fetch and no new per-ticker computation — `ticker_flags()` is
already ticker-scoped and already computed once for the S&P 500-wide row. The only new work
is partitioning that same dict of 503 already-computed flag frames by `IndexConstituent.
sector` and running `aggregate_flags()`/`snapshot_frame()` 11 more times, once per group of
20–85 tickers instead of once over 503. `aggregate_flags` is a single vectorized
`groupby+sum`; running it 11 times over the same total row count it already summed once adds
a small constant multiple of a sub-second operation, not a new order of magnitude — expect
low single-digit seconds added to a job that already runs in ~2–3s warm, nowhere near
Warren's multi-minute cost.

**Cron-slot recommendation: fold into the existing `nightly_market_breadth` job, don't add a
19th cron entry.** The 3:10–3:55 AM window has essentially no slack left: 3:10 trend → 3:20
BB+RSI → 3:25 Liquidity Zones → 3:30 sector heatmap → 3:35 market breadth → 3:40 Warren
(worst case ~9 min, i.e. could run until ~3:49) → 3:50 recompute → 3:55 backup. A brand-new
per-sector job would need a slot this schedule doesn't have to spare. Extending the existing
3:35 job costs nothing schedule-wise since it reuses the same bars already in memory for
that run.

## 4. Schema: what table design?

**Reuse `MarketBreadthSnapshot` as-is — zero schema change.** Its own docstring already
anticipated this: `universe` is part of the composite PK "even though only `sp500`… exists
today" specifically because `_add_missing_columns` is additive-only and can't widen a
primary key later — adding a second universe to a `(as_of_date)`-only-keyed table would have
meant a table recreate. That groundwork is already paid for. Recommend `universe` values of
the form `"sector:XLK"` (namespaced so it can never collide with a real `IndexConstituent.
index_name`, and self-documenting in raw SQL/admin queries) for the 11 sectors, alongside
the existing `"sp500"` row.

Trade-offs against the alternatives named in the prompt:
- **11 separate tables**: rejected. Duplicates every read/upsert/prune code path 11x for no
  benefit — the whole point of `universe` being in the PK was to avoid exactly this.
- **New dedicated long-format table** (mirroring `SectorEtfReturn`'s one-row-per-metric
  shape): rejected. `MarketBreadthSnapshot`'s WIDE design (one row per metric-set) was a
  deliberate choice over `SectorEtfReturn`'s long format specifically so "a row reads on its
  own and carries its own numerators/denominators" (its own docstring) — that reasoning
  applies identically per sector, and long format would make the coverage/eligibility counts
  (§5) awkward to read per session per sector.
- **Reusing `MarketBreadthSnapshot` with a `universe` value per sector** (recommended):
  matches the table's own designed extension point exactly. The only code changes are:
  parameterize `compute_and_store_market_breadth`/`get_market_breadth`
  (`data/market_breadth_data.py`) over `(universe, tickers)` instead of the hardcoded
  `UNIVERSE = "sp500"` module constant, and add a `universe` query param to
  `GET /api/market-breadth`.

## 5. Coverage-gate threshold: does small-sector size make it noisier?

**Yes — this is the one place the extension isn't a clean drop-in, and needs a real
decision, not a default.** The existing `MIN_COVERAGE = 0.97` was sized against 503
constituents (tolerates 15 missing). At sector scale:

| Sector | Constituents | Tickers tolerated missing at 97% |
|---|---:|---:|
| Basic Materials | 20 | **0** (19/20 = 95.0% < 97%) |
| Energy | 22 | **0** (21/22 = 95.5% < 97%) |
| Communication Services | 22 | **0** |
| Real Estate | 30 | **0** (29/30 = 96.7% < 97%) |
| Utilities | 32 | 0 (31/32 = 96.9% < 97%) |
| Consumer Defensive | 33 | 1 (32/33 = 97.0%) |
| Technology | 85 | 2 |
| S&P 500 (existing) | 503 | 15 |

A flat 97% applied per-sector means the six smallest sectors would fail the gate on
literally any single ordinary transient Yahoo miss for one constituent — a much more
failure-prone job than the market-wide row, which currently tolerates 15/503 missing
comfortably. This isn't a modeling error, it's an unavoidable consequence of a percentage
gate at small N, and it needs an explicit call before shipping:

- **Option A — keep 97% per sector as-is.** Simple, consistent with the existing job,
  defensible ("a skewed reading is worse than a missing night"). Accept that small sectors
  will legitimately show more gaps in their history than the S&P 500-wide series.
- **Option B — a floor-based rule for small sectors** (e.g. tolerate up to N missing
  regardless of percentage, for some small fixed N like 1–2), so a single stray Yahoo miss
  doesn't blank an entire night for the smallest sectors. Needs real failure-rate data (how
  often does an individual ticker actually miss on a given night?) before picking a number —
  not something to guess at investigation time.

Recommend deciding this with one week of real coverage data once Phase 1 (below) is live in
a monitoring-only mode, rather than picking a number now.

**A related, softer effect, not a gate issue but worth documenting on the page:** the
`*_eligible` denominators (thin-history tickers excluded from the SMA200/52-week windows)
are a larger fraction of a small sector's own count than of the full index — a couple of
recent-IPO names in a 20-22-name sector move the eligible base noticeably more than the same
names would in the 503-name whole. Similarly, `net_new_highs` (a raw integer count, not a
percentage) is inherently noisier at N=20-30 than at N=503 — one or two names flipping a new
high/low swings the reading by a visible fraction of the total. Neither is a bug (the
`*_eligible` design already handles it correctly — a thin-history name is excluded, never
misread as "below"), but the smallest sectors' breadth reads should carry a visible "based
on N of M constituents" caption so a reader doesn't over-interpret a small sector's swing the
same way they'd read the S&P 500-wide line.

## 6. Backfill: how far back, and does survivorship bias apply the same way?

**Same mechanism, same ~1-year practical depth, same survivorship-bias caveat — no new
issue introduced.** `backfill_market_breadth.py` is a read-only pass over whatever
`SharedBarsCache` already holds (deliberately never fetches, to avoid permanently widening
the shared cache's window for every future nightly refetch). Per §2, a sector's constituents
are the identical 503 tickers already in that cache, so a sector's backfill draws from
exactly the same depth: ~2024-09 for the 409 "2y"-tier tickers, ~2021-09 for the 89
Liquidity-Zone "5y"-tier tickers, whichever mix happens to fall in that sector.

The existing backfill's keep-rule (a session is kept only if ≥97% of constituents have a bar
**and** ≥97% are 252-bar-eligible) is exactly the mechanism flagged as noisier at small N in
§5 — applied per sector, it would need the same threshold decision as the nightly job (ideally
the same constant, for consistency between live and backfilled rows). A small sector whose
few thin-history members happen to still be inside the 252-bar warm-up window at the start of
the backfill range would see its own kept-session start later than the S&P 500-wide row's —
expected, not a bug, and the existing `is_backfilled` flag plus each sector page's own
"computed from N sessions starting X" framing already covers this.

**Survivorship bias applies identically, one level down**: the backfill applies *today's*
sector membership to past dates, same as it already applies today's S&P 500 membership to
past dates. A ticker that moved sectors, or joined the S&P 500 partway through the lookback
window, is counted in its *current* sector for every backfilled date — no worse than the
existing single-universe caveat, just now also true per sector. No new caveat category, same
`is_backfilled` labeling convention carries it.

## 7. UI/nav: 11 new pages, or one page with a selector?

**Recommend one page with a sector selector (tabs, or a dynamic route like
`/breadth/[sector]` sharing one page shell) — not 11 new top-nav entries.**

Reasoning:
- **Nav clutter is real and immediate.** `TopNav.tsx` currently has 6 top-level links
  (Screener, Watchlist, Momentum, Sectors, Breadth, Settings) plus the always-on "Ticker
  Analysis" indicator. Adding 11 more would roughly triple the nav bar's width for a single
  feature — no other feature in this app has ever added more than one nav entry.
- **No precedent for "N pages, one per entity"** anywhere else in this app. Every other
  multi-entity feature already renders "N things" as rows/cards on ONE page: the Screener
  (hundreds of tickers, one page with filters), the Watchlist, and — most directly on point —
  the sector heatmap itself (`/sectors`), which already shows all 11 SPDR sectors as rows in
  one table rather than 11 separate pages. A "one page per sector" breadth feature would be
  the first thing in the app to break that pattern, for the same 11 sectors the heatmap
  already treats as one page's worth of content.
- **Discoverability is actually better with a selector**, not worse: one bookmarkable/
  linkable URL family (`/breadth` for the market-wide read, a sector control for each of the
  11), reachable from the existing single "Breadth" nav entry, versus asking a user to find
  11 new links or memorize which one is Energy vs Materials.
- **Implementation size is far smaller.** A selector reuses the existing
  `MarketBreadthCharts`/`MarketBreadthStats` components almost entirely (parameterized by a
  `universe` prop/query param) instead of either duplicating them 11 times or building a
  generalized multi-instance page from scratch.

Recommend a dynamic route (`/breadth/[sector]`, with `/breadth` itself staying the S&P
500-wide default) over a client-side-only tab state, so each sector is independently
linkable/shareable — consistent with how `/tickers/[ticker]` already works elsewhere in this
app, and a closer fit to "one page per sector" in spirit (a real, bookmarkable page per
sector) while keeping it to one shared component tree and one nav entry.

## 8. Rough implementation size

Because this reuses the existing feature's schema, persistence, API shape, and chart
components almost entirely, it's substantially smaller than the original market-breadth
build (which was itself ~5 commits / ~25 files across two investigation-to-ship rounds: core
job [9 files, 756 lines], backfill, the 20-day-SMA follow-on, the API endpoint [4 files, 143
lines], and the frontend page [10 files, 495 lines]).

**Backend — schema-free extension of the existing feature:**
- `scoring/market_breadth.py`: no change needed — already generic over any ticker→frame
  dict, agnostic to what the tickers represent.
- `data/market_breadth_data.py`: parameterize the module's `UNIVERSE`/ticker-list assumption
  into a `(universe, tickers)` pair; add the `FMP_SECTOR_TO_ETF` mapping and a helper to
  build the 11 sector ticker groups from `IndexConstituent`; loop over them after the
  existing S&P 500-wide computation (same bars, no new fetch).
- `pipeline/nightly_market_breadth.py`: extend the single run to also compute+store the 11
  sector rows; decide and apply the coverage-gate policy from §5.
- `pipeline/backfills/backfill_market_breadth.py`: extend the same way for historical rows.
- `core/schemas.py` / `core/main.py`: add a `universe` query param to
  `GET /api/market-breadth` (defaulting to `"sp500"`) and adjust `MarketBreadthOut`/
  `get_market_breadth()` accordingly.
- Tests: extend `test_market_breadth_data.py`, `test_nightly_market_breadth.py`,
  `test_backfill_market_breadth.py`, `test_market_breadth_endpoint.py`; `test_market_breadth_
  scoring.py` likely needs no change (already generic). Existing suite is ~730 lines across
  6 files — expect proportionally smaller additions than a from-scratch build, since the
  math/model itself isn't new.
- **No new table, no schema migration, no new cron job, no new `CRON_JOB_NAMES`/
  `_EXPECTED_CADENCE_HOURS` entry** — the existing `nightly_market_breadth` entry in
  `cron_health.py`/`crontab.txt`/`OPS_RUNBOOK.md` just gains a note that it now also computes
  11 sector rows.

Estimated: ~6-7 backend files touched (5 code + ~4-5 test files), **1 commit** (this is a
genuinely additive, self-contained change to one existing feature, not a new one needing its
own investigation→schema→job→backfill sequence of commits the way the original build did).

**Frontend — new sector-selector page shell, reusing existing chart components:**
- `app/breadth/[sector]/page.tsx` (new dynamic route) or equivalent selector state on the
  existing `app/breadth/page.tsx`.
- `components/breadth/MarketBreadthCharts.tsx` / `MarketBreadthStats.tsx`: parameterize by a
  `universe`/`sector` prop instead of assuming S&P 500 — largely reuse, not rewrite.
- `lib/marketBreadth.ts`, `lib/hooks/useMarketBreadth.ts`, `lib/api/types.ts`: thread the
  `universe` param through the fetch hook and wire types.
- New small `SectorSelector`/tab component (11 options + the S&P 500-wide default);
  `SECTOR_ETFS`-equivalent list (already exists in `sector_heatmap_data.py`'s shape, needs a
  frontend-side twin or a shared constant if one doesn't already exist there).
- Existing `app/breadth/page.test.tsx`, `components/breadth/*.test.tsx`: extend for the
  parameterized props; add a new page test for the selector/route.

Estimated: ~6-8 frontend files touched, **1 commit**.

**Total estimate: 2 commits, ~13-15 files touched, no schema migration, no new cron job** —
small enough to ship as one round rather than split into phases for size reasons alone.
Recommend splitting into two phases anyway (below), not because either is individually large,
but because §5's coverage-gate threshold is a real open decision worth resolving with a few
days of real data before the frontend commits to a page shape around it.

## Recommendation

**Worth building**, and cheaply, because it's overwhelmingly reuse of a feature that was
already designed with this extension in mind (`universe` in the PK, generic pure-math
functions, an already-warm shared bars cache covering exactly the same tickers). The two
things that keep this from being a pure copy-paste are genuine, not busywork: the coverage
gate needs a small-N-aware policy decision (§5), and the nav/page shape needs to avoid an
11-page sprawl that has no precedent anywhere else in this app (§7).

**Phased plan:**

- **Phase 1 (backend only):** extend `data/market_breadth_data.py`/`pipeline/
  nightly_market_breadth.py`/`pipeline/backfills/backfill_market_breadth.py` to compute and
  store the 11 sector rows under `universe = "sector:<ETF>"` in the existing
  `MarketBreadthSnapshot` table, add the `universe` query param to `GET /api/market-breadth`,
  and run it live for a week or two in "backend only" mode (no frontend surface yet) —
  specifically to gather real per-sector coverage-gate failure-rate data before locking in a
  threshold policy for the six smallest sectors (§5). Ships as the one backend commit
  estimated above.
- **Phase 2 (frontend):** once Phase 1's coverage behavior is confirmed acceptable (or the
  threshold policy adjusted from real data), build the sector-selector page
  (`/breadth/[sector]`) reusing the existing chart/stat components. Ships as the one frontend
  commit estimated above.

This phasing mirrors how several other technical-lens features in this codebase already
shipped (data layer live and verified against real data first, UI catching up once the
numbers are trusted) rather than being a size-driven split.

## Not verified

- No browser/UI checks (none available).
- No live diff against the SPDR sector ETFs' actual current holdings — the FMP-sector-to-ETF
  mapping in §1 is a reasonable, precedented approximation, not independently confirmed
  ticker-by-ticker against State Street's own published holdings.
- No measurement of the *actual* per-ticker nightly miss rate needed to size §5's
  coverage-gate policy with real data (recommended as Phase 1's own live-data-gathering
  purpose, not resolved here).
- Runtime estimate in §3 is derived from the existing job's own 2026-09-21 measurements plus
  reasoning about the added `groupby` cost, not a fresh timed run of the 11-way partition
  itself.
