# CLAUDE.md history: technical signals

Verbatim history moved out of the original CLAUDE.md (archived at docs/archive/CLAUDE.original.md). Text is unedited; line ranges refer to that file.

## Liquidity Zone (LP) detection: superseded Engine bullet (LOCKED later-swing breach semantics) (original lines 2696-2709)

- **Engine** (`backend/analysis/liquidity_zones/`, pure functions/dataclasses, no DB/HTTP):
  fractal swing-low/swing-high detection on Low/High (not Close -- unlike
  `trend_structure/swings.py`, which is Close-only and hardcoded to N=5; this feature needs
  Low/High with a caller-configurable window, so it's a small, independent implementation
  using the same vectorized shift technique). **Breach semantics are LOCKED and deliberately
  diverge from the Polygon-based reference script this was adapted from
  (`lp_detector_polygon_clustered.py`, provided only to show the algorithm shape, never
  wired in itself)**: a swing low becomes a support LP the moment it's confirmed and stays
  valid until a **LATER SWING LOW's** Low trades below it -- an ordinary non-swing bar
  breaching the level does NOT invalidate it. Symmetric for swing highs/resistance. The
  reference script's own `annotate_swing_lows` actually checks every later BAR, not just
  later swings -- this is the one specific place this build does NOT follow that reference
  implementation, confirmed via a dedicated regression test
  (`test_ordinary_bar_does_not_breach_a_level_only_a_later_swing_does`).

## Liquidity Zone (LP) detection: superseded Nearest-N filtering bullet (original lines 2719-2725)

- **Nearest-N filtering is a display refinement layered on top of the locked breach rule,
  not a change to it**: a currently-valid (unbreached) swing can, in principle, sit on the
  "wrong" side of the last price -- e.g. an old swing low that price has since fallen well
  below without a later swing low ever confirming that breach. Such zones are filtered out
  before taking the nearest `num_zones` per side, since a "support" level above today's
  price (or a "resistance" level below it) isn't a meaningful nearest-support/resistance
  reading for the card this feeds.

## Liquidity Zone (LP) detection: superseded per-timeframe Settings bullet (original lines 2744-2752)

- **Settings: a genuinely runtime-editable, DB-backed config** (`LiquidityZoneConfig`,
  singleton `key`-PK row, same lazy-seed get-or-create pattern as `DiscountRateConfig`/
  `MoatScoreConfig`/`ReitDividendYieldConfig`) -- independent `swing_bars`/`cluster_pct`/
  `num_zones` per timeframe, editable via a new `/settings` section
  (`LiquidityZoneSettingsForm.tsx`). This is the first Technical-tab feature to get this
  treatment -- BB+RSI's own thresholds (`RSI_LENGTH`, `BB_STD`, etc.) remain hardcoded
  constants with no settings-page UI, a pre-existing gap this build does not retroactively
  fix. A settings change only takes effect on the next nightly run, not retroactively --
  this feature has no live-recompute path the way Step 3's discount rate does.

## Liquidity Zone nightly job: market-close-aware fix (2026-09-18) (original lines 2869-2925)

### Liquidity Zone nightly job: confirmed live-exposed to the same bug, fixed with a market-close-aware check (2026-09-18)

Follow-up investigation into whether the gap the entry above left open was actually being hit,
or just theoretically possible given the job's schedule -- it was live, not theoretical.

**Confirmed via the real `fundamentalscache` table**, grouping every `historical_price_eod`/`4y`
row (Liquidity Zone's own cache key) by `date(fetched_at)`: of 116 rows, only 42 had been
refreshed on the night being checked, 62 were still dated the PRIOR night's run, 11 were two
nights stale, and 1 was three nights stale -- a compounding version of the Chart tab's own "stuck
one day behind" symptom, not a milder one. Traced the exact mechanism via the job's own log
(`nightly_liquidity_zone_calculation_cron.log`): the cron entry (`crontab.txt`, `25 3 * * *`,
server timezone UTC per `timedatectl`) fires at a fixed wall-clock time every night, but
`FMPDailyBarSource.get_daily_bars` fetches tickers **sequentially** (no multi-ticker FMP
endpoint), so each ticker's own `fetched_at` lands at `job_start + cumulative_per_ticker_delay`
-- and real run durations vary a lot night to night (7.3s to 133.2s across nine consecutive
nights, driven by network/FMP latency jitter). Since the interval between two consecutive runs
is ~24h00m by the cron schedule itself, whether a given ticker's row reads as "stale" on the next
run reduces to whether *that run* processed the ticker slightly later in wall-clock terms than
the *previous* run did -- a coin flip decided by relative run-speed, not by anything related to
whether the cached data is actually current. A ticker can lose this coin flip several nights in a
row, which is why some rows were 2-3 nights stale, not just 1 -- worse than the Chart tab's bug
in practice, since that one only ever spanned a single day before self-healing.

**Fix**: added a market-close-aware freshness check on top of (not instead of) the existing
`daily_bar_staleness_days` TTL, scoped to `clients/daily_price_sources.py` only --
`_fetch_fmp_daily_bars` now also compares the cached series' own last bar date against a new
`_most_recent_completed_trading_date()` helper (US/Eastern, weekday-aware, deliberately NOT
holiday-aware -- flagged as a lower-value follow-up in
`docs/chart_tab_missing_bar_investigation_2026-09-18.md` (file not in repo)'s "Proposed fix" section, option 2,
which this implements) and forces a live refetch via `core/cache.py::force_fetch` (ignoring the
TTL entirely) whenever the two disagree -- i.e. whenever the cache is "fresh" per the flat window
but its content still predates the most recently completed session. Unlike the Chart tab, this
job's cache was kept rather than dropped: it only fetches once per ticker per night regardless,
so the cache is genuinely load-bearing here (a warm, genuinely-current row still means zero live
FMP calls), whereas the Chart tab's cache bought little against many same-day views. `get_or_fetch`
itself, `daily_bar_staleness_days`'s meaning, and every other potential consumer of
`FMPDailyBarSource` (there is currently none -- the Chart tab moved off this cache entirely, see
the entry above) are all unchanged -- this is an additive check at the one call site inside
`daily_price_sources.py`, not a change to the shared cache primitive.

Confirmed via `tests/test_daily_price_sources.py`: a new regression test
(`test_fresh_per_ttl_but_missing_latest_session_still_forces_a_refetch`) reproduces the exact
production shape (a row fetched 1 hour ago, comfortably inside the TTL, whose last bar is two
sessions behind) and confirms a live refetch still fires; the three pre-existing tests in that
file were updated to pin `_most_recent_completed_trading_date` to match their own fixture dates,
since they were written before this check existed and used a hardcoded historical bar date that
would otherwise always fail the new gate once run against a later real wall-clock date. Full
Liquidity Zone test surface (`test_daily_price_sources.py`, `test_liquidity_zone_data.py`,
`test_liquidity_zone_config_endpoints.py`, `test_liquidity_zone_endpoint.py`,
`test_nightly_liquidity_zone_calculation.py`, 35 tests total) and the Chart tab's own tests
(confirming zero cross-impact, since it no longer reads through this module) all pass.

**Manual verification checklist** (no browser available in this environment): after the next
nightly run, query `fundamentalscache` for `statement_type='historical_price_eod' AND
period='4y'`, group by `date(fetched_at)` -- every row should now date to that run's own night,
with no multi-night-stale residue accumulating the way it did before this fix.


## Main/Secondary watchlist rename + computed_at staleness sweep (2026-09-09) (original lines 2926-2982)

### Main/Secondary watchlist rename + computed_at staleness sweep (2026-09-09)

**Superseded 2026-09-11 (see the "Watchlists" section above for the current behavior):**
two further renames landed after this entry — `"Main"`/`"Secondary"` -> `"W1"`/`"W2"`
(`fcacfc0`), then generalized to a `^W[1-5]$` pattern match, any watchlist named W1 through
W5 (`0ef5e5b`) — so the fixed-two-name behavior this section describes is no longer current.
`list_tickers_across_watchlists`'s own signature changed in the same generalization, from
`names: list[str]` to `name_pattern: re.Pattern[str]`. Kept below as a historical record of
the original mechanism and the real-DB state at the time it shipped.

Both the BB+RSI entry-signal and Liquidity Zone (LP) nightly jobs were originally scoped
to a single hardcoded watchlist literally named `"Watchlist"`. Renamed to two named lists,
`"Main"` and `"Secondary"` -- both jobs now compute over the deduped union of the two (a
ticker on both lists is processed once, never twice) via the new
`data/watchlists.py::list_tickers_across_watchlists(session, names)` helper, shared by both
`pipeline/nightly_entry_signal_calculation.py` and `pipeline/nightly_liquidity_zone_calculation.py`.
If one of the two named watchlists doesn't exist, the job logs a warning and continues with
whichever does (a deliberate change from the old single-name behavior, where any missing
watchlist was an unconditional no-op) -- only an empty union (neither list exists, or both
exist with zero tickers combined) short-circuits to the existing "nothing to process"
summary.

**Real-DB note (2026-09-09):** at the time of this rename, no `"Watchlist"` row existed any
more (already renamed/deleted by an earlier, unrelated change) and a `"Main"` row already
existed (freshly created that same day, not a rename of the old row) -- kept as-is per
explicit direction rather than assumed; `"Secondary"` was created fresh via
`data/watchlists.py::create_watchlist`, the same helper the `/watchlist` UI itself uses.

**`computed_at: datetime` already existed on both `TechnicalEntrySignal` and
`LiquidityZoneAnalysis`** (set on every successful nightly compute, already threaded through
`TechnicalEntrySignalOut`/`LiquidityZoneOut` and the frontend TS types) -- this build didn't
add the field, only a staleness-sweep mechanism that uses it and card-level display that was
previously missing (`BbRsiEntrySignalCard`'s new "Data computed" row,
`LiquidityZonesCard`'s new per-timeframe "Computed [date]" caption).

**Staleness sweep**: each nightly job, after its per-ticker loop, calls a new sweep function
in its own data-layer module (`data/entry_signal_data.py::sweep_stale_entry_signals`,
`data/liquidity_zone_data.py::sweep_stale_liquidity_zones`) that clears any row whose
`computed_at` is more than `STALE_AFTER_DAYS` (7) old -- the case where a ticker has fallen
off both "Main" and "Secondary" and so is no longer reached by the per-ticker loop at all.
Folded into the existing jobs rather than a new cron entry/`cron_heartbeat` name, since it's
maintenance of the same feature, not a new one.

**Design decision: clear in place, never delete the row** (a deliberate choice between the
two options, not a default) -- `fired_at`/`pct_b`/`rsi`/`close`/`stop_price` (entry-signal,
all already-`Optional` fields, no schema change) and `support_zones_json`/
`resistance_zones_json` (liquidity-zone, set to `"[]"` rather than `NULL` since both are
`NOT NULL` columns and relaxing that would need a SQLite table recreate -- semantically "no
zones" either way, handled by the existing JSON-parsing code unchanged) are nulled/emptied,
while `source`/`as_of`/`computed_at` are left completely untouched as a "last known" marker.
Deleting the row would lose that marker -- the exact thing the ticker-page cards need to
show "computed as of X, no longer tracked" instead of the data just vanishing -- for no real
storage-cost benefit, since both tables are one row per ticker(/timeframe), not an
accumulating time series a delete would meaningfully shrink. Sweeping an already-cleared row
is a cheap no-op (both sweep functions only rewrite rows that still have something to
clear), so this runs safely every night indefinitely.


## Most-recently-breached LP level tracking (2026-09-17): superseded rule, tie-break and tests (original lines 2983-3028)

### Most-recently-breached LP level tracking (2026-09-17)

Previously, once a later confirmed swing breached a support/resistance zone, that zone
simply dropped out of the valid set forever -- `valid_prices_at` excludes it before
clustering, and nothing else ever surfaces it again. New requirement: keep track of the
single most recently breached zone per side (support/resistance) per timeframe
(Daily/Weekly), subject to two hard AND-ed filters, and plot it on the Technical tab
chart alongside the still-valid zones, in a distinct color.

- **No new replay/history mechanism needed.** The engine already recomputes from
  scratch on every nightly run (same shape as the Warren signal engine, not
  `trend_structure`'s incremental state machine), and `swings.py::annotate_swings`
  already computes `breach_pos` for every swing regardless of whether it's currently
  valid -- the full breach history (which swing, breached by which later swing, at
  which bar position) is already available in memory on every run, for free. This also
  means the "re-evaluate nightly, don't just flag once at breach time" requirement falls
  out for free: a previously-qualifying broken zone that no longer clears either filter
  today simply isn't selected this run, with no explicit clear/expire logic needed.
- **Two hard filters, both required (`analysis/liquidity_zones/engine.py::
  _select_broken_zone`)**: (1) recency -- `last_pos - pos <= breach_recency_bars`, counted
  from the ZONE'S OWN swing point (its original formation), not the later breach bar; a
  zone formed long ago is stale even if the swing that broke it just happened. **Caught
  and corrected same-day (2026-09-17) via a real MSFT trace**: the first version measured
  from the breach bar (`last_pos - breach_pos`) instead, which is strictly looser --
  breach_pos is always >= the zone's own pos, so the gap to last_pos measured from the
  breach bar can only be smaller (or equal). MSFT's daily support at $493.81 (formed
  2026-09-02, 9 bars back) incorrectly qualified under the old rule because its breach
  (2026-09-10, only 4 bars back) alone was recent, even though the zone itself wasn't --
  confirmed by re-deriving the actual `daily_df` bar positions the engine used, not just
  eyeballing calendar dates. (2) position -- a broken support only qualifies if its price
  sits ABOVE the highest currently-valid support zone (auto-satisfied if none exists),
  mirrored for resistance.
  **The positional check deliberately uses the FULL clustered valid-zone set, before the
  existing wrong-side-of-price display filter and before the `num_zones` display cap** --
  both of those are documented display-only refinements "on top of the locked breach
  rule, not a change to it" (confirmed with the user before implementing), so a zone
  that's valid but merely hidden from display still counts as a real obstacle here.
  `engine.py` computes the full clustered list once and derives both the display slice
  (unchanged) and this positional extreme from it -- no double computation.
- **Tie-breaking, found via testing rather than assumed away.** A single later, lower
  swing can breach several earlier, higher-priced swings simultaneously (e.g. two
  independent, non-breaching-each-other swings both later undercut by the same new low)
  -- an exact `breach_pos` tie the original design assumed couldn't happen. Resolved by
  preferring the candidate with the later original formation (`max(breach_pos, pos)`) --
  the more current of the tied levels. Never clustered with other breached candidates
  (out of scope per the request) -- at most one `BrokenZone` per side per timeframe.

## Most-recently-breached LP level tracking (2026-09-17): superseded per-timeframe recency setting (original lines 3035-3042)

- **Settings**: new `daily_breach_recency_bars`/`weekly_breach_recency_bars` fields on
  `LiquidityZoneConfig` (default 6, `DEFAULT_BREACH_RECENCY_BARS`), editable in the
  existing `/settings` Liquidity Zones section alongside `swing_bars`/`cluster_pct`/
  `num_zones` -- same "takes effect on the next nightly run, not retroactively"
  convention as every other field there. Nullable on the model (the usual
  `_add_missing_columns`-has-no-backfill reason) -- `get_liquidity_zone_config`
  coalesces a `NULL` read back to the default so a pre-existing on-disk row never
  silently passes `None` into the engine.

## Most-recently-breached LP level tracking (2026-09-17): test confirmation (original lines 3067-3073)

- Confirmed via new engine-level tests (recency-window exclusion measured off the zone's
  own formation -- including the dedicated old-formation/recent-breach regression case
  above --, positional exclusion, most-recent-of-several selection, a same-bar tie-break
  case reconstructed to still produce a genuine tie under the corrected, tighter recency
  rule) plus data-layer/config-endpoint/chart-data coverage; full backend suite (1481
  tests) and frontend `tsc --noEmit` both clean.


## Chart tab reverted to zero-cache on-demand fetch (2026-09-18) (original lines 2838-2868)

### Chart tab reverted to zero-cache on-demand fetch (2026-09-18)

**The fix directly above wasn't enough for the Chart tab** -- `daily_bar_staleness_days` being
a flat 24h TTL with no market-close awareness meant a row fetched any time before a trading
day's close still locked in the PRIOR close as "fresh" for up to the next 24 hours, regardless
of the colliding-cache-key fix. Confirmed live in production 2026-09-18
(`docs/chart_tab_missing_bar_investigation_2026-09-18.md` (file not in repo)): AAPL's Chart tab showed 2026-09-16
as its most recent bar on 2026-09-18, and a full-table scan found 34 cached rows across all
three FMP lookback keys (2y/3y/8y -- i.e. all 4 Chart-tab ranges, since D_6M/D_1Y share the 2y
key) exhibiting the identical failure shape, all from pre-close morning fetches. A live,
uncached FMP call proved the missing bar was already available upstream the whole time -- this
was never data lag, only the local cache serving a stale snapshot.

Rather than build market-close-aware staleness logic, the Chart tab's FMP branch was reverted
to what its own module docstring's "fully on-demand" framing always claimed but didn't fully
deliver: `data/chart_data.py::_fetch_fmp_bars` now calls `fmp_client.get_historical_price_eod`
directly, bypassing `daily_price_sources.py`'s `FMPDailyBarSource`/`get_or_fetch`-backed
`FundamentalsCache` entirely -- a genuinely live FMP call on every Chart tab request, the
same on-demand behavior the tab's other price source had.
**Scoped to the Chart tab only** -- `daily_price_sources.py` itself, and every other consumer of
it, are untouched. Liquidity Zone detection (`data/liquidity_zone_data.py`,
`pipeline/nightly_liquidity_zone_calculation.py`) still reads through the same
`FMPDailyBarSource`/`get_or_fetch` cached path documented in the fix above, and **at the time of
this revert** remained subject to the identical market-close-blind staleness bug -- a deliberate
scoping decision, not an oversight, left as a known, separate issue to revisit (Liquidity Zones
only runs once nightly rather than on every page view, so the cost/benefit of adding a
persistence layer there is genuinely different from the Chart tab's case). This also means the
"shared by the Chart tab's four ranges... and this feature's nightly job" framing in the fix
above is no longer accurate as of this revert -- `FMPDailyBarSource` is now only the nightly
job's own path. **See the next entry below: revisited and fixed the same day.**


## Chart tab earnings/dividend markers (2026-09-20): original design notes (intro, source, cached-never-live) (original lines 3074-3091)

### Chart tab earnings/dividend markers (2026-09-20)

Earnings-report dates ("E", cyan) and dividend ex-dates ("D", violet) on the Chart
tab's price pane, all 4 ranges, each with its own toggle (`ChartTab.tsx`) and a hover tooltip (EPS
actual/estimate/surprise; per-share amount). **Drawn on a fixed row along the price pane's floor,
independent of price (TradingView's convention) -- see "Fixed-row placement" below; originally
(same day) they sat above/below the candle at the bar's price level.**

- **Source is FMP (`data/chart_events_data.py`).** (Originally FMP-first with a second provider as fallback; since
  Phase 6b the nightly `CorporateEvent` cache is the sole source -- see "Phase 6a"/"Phase 6b".) FMP is deep for
  foreign issuers (HSBC: 39 quarters of earnings). `FMPClient.get_earnings_history` (limit 40) / `get_dividends`
  (limit 400) were added for this; the existing `get_earnings` (limit 8, cached under `earnings`/`latest`) is
  untouched and is not reused.
- **Cached, never live (Phase 6b).** `fetch_chart_events` reads the `CorporateEvent` cache only -- no FMP call
  per chart request, no timeout wrapper -- and never raises: an uncached ticker or a read error is
  `events_source=None` with empty lists and the chart just renders without markers. (The original design made two
  live FMP calls per request with a per-source fallback.) An empty stored list is a real answer (TSLA pays no
  dividend).

## Chart tab earnings/dividend markers (2026-09-20): first-version history and browserless verification notes (original lines 3143-3152)

  - **History**: the first version of this (same day, `776aa41`) kept the markers plugin and pinned
    circle/square markers to the floor via a hidden helper series on an overlay price scale (0..1
    range, zero margins) -- replaced because it couldn't drop the shapes or enlarge the letters.
  - Verified without a browser: unit tests (label builders, floor geometry, hit-testing, tooltip
    placement), tsc, eslint, plus a throwaway headless run of the real library with the real primitive
    confirming (at the then-15px size) the letters draw at exactly pane height - floor - font/2 (stacked +18px up), bold, centred,
    in the right colors, and that `hitTest` hits/misses/stacks correctly and stops hitting when toggled
    off. **Not verified on screen**: how the row looks at each zoom, the library's own hover delivery
    (jsdom can't dispatch its mouse events; the `hitTest` -> `hoveredInfo` step was verified by reading
    the library source, not by running it), and the tooltip flip.
