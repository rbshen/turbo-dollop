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

## Warren RSI/ADX/WVF entry signal (2h): 'Measured, not assumed' benchmark lesson (2026-09-12) (original lines 3196-3216)

- **Measured, not assumed -- but the FIRST measurement was itself wrong, and only a real run
  caught it (2026-09-12).** The original pre-shipping benchmark was synthetic: it fed
  `replay()` ALREADY-BUILT 2h candles directly, timing only the indicators + sequential
  state-machine loop (**2.3s at 98 tickers, 11.7s at the 500-ticker worst case**) and combined
  that with a separately-measured ~15s batch-fetch figure to conclude a comfortable ~15-30s
  worst-case total -- comfortably fits a 5-minute cron slot. That number was real for what it
  measured, but it never exercised `build_2h_session_candles`' own per-day resample loop over
  the FULL 2-year history this job actually feeds it (the synthetic benchmark's candles were
  already 2h-resampled) -- and that resample step, not the replay itself, turns out to
  dominate real per-ticker cost. A real run against the live 98-ticker W1-W5 union measured
  **98.9s total** (resample ~0.9-1.0s/ticker, replay itself still only ~30-40ms/ticker,
  confirming the synthetic replay-only number was accurate for what it covered) --
  extrapolating to roughly **9 minutes** at the 500-ticker worst case, genuinely at the edge
  of a 5-minute slot. Fixed by rescheduling (see the Cron entry below), not by touching the
  shared, already-tested `build_2h_session_candles` itself -- optimizing a function BB+RSI
  also depends on wasn't worth the regression risk for a cost that a wider cron window already
  fully absorbs. Recorded here as a real process lesson: a synthetic benchmark that bypasses a
  real pipeline STAGE (resampling) rather than just synthesizing its INPUT data (bar values)
  can look conclusive while missing the actual bottleneck -- the fix, going forward, is to
  benchmark through the same entry point the real nightly job calls, not a lower-level
  function that happens to be convenient to call directly.

## Warren RSI/ADX/WVF entry signal (2h): Wilder-RSI seed bug found during build (original lines 3228-3235)

  - **One real bug found and fixed during this build**: a plain `.mean()` seed (matching
    `atr.py`'s own code literally) produced `NaN` for RSI specifically, because `close.diff()`'s
    structurally-NaN first element poisons a `gain`/`loss` series' seed window in a way
    `atr.py`'s own `true_range` never hits (its row-wise `max(axis=1)` already drops that same
    class of leading NaN before `atr.py`'s seed ever sees it). Fixed via `np.nanmean` for the
    seed instead -- confirmed via `test_compute_rsi_wilder_is_0_for_unbroken_downtrend` and
    `test_compute_dmi_adx_reads_strongly_bullish_for_a_clean_uptrend`, both of which failed
    with a `NaN` result before this fix.

## Warren RSI/ADX/WVF entry signal (2h): _upsert full-overwrite bullet, incl. development bug (original lines 3268-3278)

  - **`_upsert` always fully overwrites, unlike BB+RSI's conditional `should_advance` guard.**
    BB+RSI's nightly job only evaluates the latest day and must avoid erasing a still-relevant
    prior fire on a quiet night -- Warren's full-replay-every-run design has no such case: the
    replay result already IS the complete current truth every time, so every field
    (`fired_at`/`rsi`/`close`/`signal_kind`/`stop_price`/`gray_suppressed`/`stop_count`) is
    explicitly set every run, `None` when there's no last event. A real bug was caught here
    during development: an early version omitted the fired-fields from the `UPDATE`'s `SET`
    clause entirely when there was no last event (mirroring BB+RSI's own convention too
    closely), which silently retained a stale prior value instead of clearing it -- caught by
    `test_a_full_replay_always_overwrites_the_prior_state_never_conditionally_advances` before
    shipping.

## Warren RSI/ADX/WVF entry signal (2h): write-side warm-up buffer, measured error curve (original lines 3288-3293)

  - **Measured** (105 tickers; replay from a later start vs. a full-context replay; error =
    missed + phantom events as % of correct ones), by days from the replay's first candle:
    0-7d ~240%, 8-14d ~134%, 15-30d ~51%, 31-60d ~15-27%, 61-120d ~7-16%, 121-180d ~4-8%,
    181-300d ~2-4%, 300d+ ~0%. Live DB: 198 retroactive inserts in 5 nights for 98 established
    tickers, 96% within 60d of that night's window start; the earliest 30d of stored rows were
    ~half not reproduced by a fresh replay.

## Warren RSI/ADX/WVF entry signal (2h): retention-left-at-730 note, one-time cleanup (2026-09-19) (original lines 3310-3324)

  - **`EVENT_RETENTION_DAYS` was left at 730 in this pass and raised to 1460 right after** -- see
    "Signal-event retention raised" below. The buffer was the prerequisite: raising retention
    without it would have frozen phantom rows permanently (simulated: insert-only accumulates
    ~3.2x phantom rows vs. correct ones). 60m history beyond 730 days cannot be fetched, so the buffer
    can't come from fetching more.
  - **One-time cleanup, run 2026-09-19 against the real DB (script not kept -- see below):**
    deleted every `WarrenSignalEvent` row before tonight's cutoff (window start 2024-09-20
    10:30 + 180d = 2025-03-19 10:30): **2,870 -> 1,894 rows (976 deleted, across 103 tickers)**;
    by kind yellow_up 436, gray_down 212, blue_down 169, yellow_down 131, blue_up 18, gray_up 10.
    Latest-state rows and per-ticker last-buy timestamps confirmed identical before/after. (The
    investigation's ~939 estimate differs from the 976 actually found at this cutoff; the
    difference wasn't reconciled -- likely a different cutoff date or snapshot.) The script is deliberately not committed: it is **not safe to
    re-run later**, since rows that merely slid into the zone as the window advanced were
    written well past the buffer and are reliable. Today's `backups/fathom_20260919_*.db.gz`
    holds the deleted rows.

## Warren RSI/ADX/WVF entry signal (2h): warm-up buffer regression tests and spot check (original lines 3332-3338)

  - Regression tests (`tests/test_warren_signal_data.py`): in-buffer never written, edge
    inclusive, width driven by the constant, measured from the first candle, latest-state
    unaffected, and an end-to-end two-consecutive-nights replay through the real state machine
    (unbuffered control persists leading-edge events on both nights; buffered persists none).
    Real-data spot check on 6 tickers: 45 of 169 replayed events (27%) sit in the first 180d,
    all now unwritten; the old code also persisted 1 fresh leading-edge variant on the
    following week's replay (AMD).

## Warren RSI/ADX/WVF entry signal (2h): retention raise, BB+RSI confirmation and measured storage (original lines 3357-3375)

  - **BB+RSI: confirmed rather than assumed.** It has no sliding-window accumulation problem: the
    nightly job evaluates only the latest day over a 60-day window (RSI's EWM seed
    -- `compute_rsi` is EWM-seeded from the first bar, so not literally stateless -- has decayed to
    ~4e-6 by then: (13/14)^~170 candles), so nothing new is ever written near an unwarmed edge. The only exposure is the
    one-time 2026-09-11 backfill, whose replay started ~2024-09-12. Measured on 12 real tickers
    (full-window replay vs. replay started later, error = missed + phantom as % of true events),
    by days from replay start: 0-14d large (3 true, 8 phantom -- tiny sample), 15-30d ~6%, 31-60d
    ~5%, 61d+ 0%. Stored rows in the exposed slice: **0 in the 0-14d zone** (earliest stored event
    is day ~15), 13 in 15-30d, ~84 in 31-60d -- roughly 5 questionable rows of 2,195, comparable to
    Warren's accepted residual and a fixed slice (no accumulation). Left as is; they would have
    aged out within weeks under 730 and now persist. A one-time delete of BB+RSI events before
    ~2024-11-11 (97 rows) is the option if that ever matters.
  - **Storage, measured (dbstat, table + both indexes):** ~238 B/event row Warren, ~162 B/row
    BB+RSI. Steady rate over the last 12 full months: Warren ~1,222 events/yr (~11.6/ticker), BB+RSI
    ~1,029/yr (~10.5/ticker), at ~100 tickers. Warren goes 1,894 rows today to ~4,900 at full 4y
    depth; BB+RSI 2,195 to ~4,100-4,300. Versus 730 retention that is ~+2,450 and ~+2,060 rows,
    i.e. **~1.1 MB total** against a 1 GB DB (~5.5 MB if the W1-W5 union ever hit its 500-ticker
    cap). Chart cost: BB+RSI's own 2026-09-11 measurement put the marker query at 2.0 ms mean /
    6.2 ms max at 730 days; ~2x rows keeps it in the noise (~46 rows/ticker at steady state).

## Warren RSI/ADX/WVF entry signal (2h): chart_data docstring note and retention tests (original lines 3382-3386)

  - `data/chart_data.py`'s module docstring "known asymmetry" (W_4Y shows 4y of price but ~2y of
    markers) now describes it as closing over time rather than a permanent 2-year cap. Tests:
    `test_default_prune_keeps_events_past_the_old_730_day_mark_and_only_deletes_past_1460` in both
    `test_warren_signal_data.py` and `test_entry_signal_data.py` (default argument, so it is what
    the nightly job actually runs).

## Warren RSI/ADX/WVF entry signal (2h): cron placement bullet incl. original 3:30 scheduling history (original lines 3393-3407)

- **Cron: a new dedicated job, `pipeline.nightly_warren_signal_calculation`**, scheduled 3:40
  AM -- placed AFTER Liquidity Zone's own full 3:25-3:35 window (not squeezed into a gap
  before it), with its own dedicated ~15-minute allocation ending by 3:55, when `backup_db`
  (moved from 3:35) now runs. **Originally scheduled 3:30 AM, in the gap between Liquidity
  Zone's 3:25 and the old `backup_db` 3:35**, based on the flawed ~15-30s worst-case estimate
  the "Measured, not assumed" bullet above documents getting corrected -- re-scheduled
  2026-09-12 once the real ~9-minute worst-case estimate was known, since the original 5-minute
  gap could no longer safely contain it. A dedicated script rather than folding into
  `nightly_entry_signal_calculation.py`, for the same "one feature, one script" reasoning the
  Liquidity Zone job's own entry above gives -- doubly justified here since Warren's
  2-year-lookback/full-replay shape is fundamentally different from BB+RSI's
  60-day/latest-day-only one, even though both share the same W1-W5 scope and shared
  60m bars cache. Reads the cache at the full 730-day width rather than through
  `clients/technical_sources.py`'s BB+RSI-sized 60-day reader. Wired into
  `core/cron_health.py`'s `CRON_JOB_NAMES`/`_EXPECTED_CADENCE_HOURS` as the 16th job.

## Warren RSI/ADX/WVF entry signal (2h): engine-isolation bug found while wiring API/UI (original lines 3427-3439)

  - **Found and fixed while wiring this in, not a pre-existing bug**: neither
    `test_chart_data.py` nor `test_chart_endpoint.py` isolated a fresh engine for
    `data/warren_signal_data.py`'s own `engine` reference before this feature existed to touch
    it -- once `get_chart_data` started calling `get_warren_signal_data` unconditionally,
    every test in both files would have silently read against the real, on-disk
    `core.db.engine` instead of a fixture value (harmless in practice here, since these tests
    use fake tickers like `"TEST"`/`"BADTICKER"` that have no real "warren" row either way, but
    a real violation of this codebase's own engine-isolation convention -- see "Ad-hoc
    reproduction scripts must not touch the real database" above). Fixed by adding a
    `_fresh_warren_signal_engine` helper (`test_chart_endpoint.py`) and an autouse
    `_default_no_warren_signal` fixture (`test_chart_data.py`), mirroring the existing
    per-module engine-isolation helpers exactly.



## Shared FMP daily-bar cache: wrong staleness window + colliding cache key (2026-09-16) (original lines 2780-2823)

### Shared FMP daily-bar cache: wrong staleness window + colliding cache key (2026-09-16)

`clients/daily_price_sources.py::FMPDailyBarSource` -- shared by the Chart tab's four ranges
(D_6M/D_1Y/D_2Y/W_4Y) and this feature's nightly job -- had two compounding bugs in how it
cached daily EOD bars through the general-purpose `FundamentalsCache`/`get_or_fetch`
machinery, both in `_fetch_fmp_daily_bars`:

1. **Wrong staleness window.** It reused `settings.cache_staleness_days` (7 days, meant for
   slow-changing fundamentals) instead of a window matched to daily-price data's actual
   change cadence (a new bar every trading day). A row fetched before that day's close read
   as "fresh" for up to a week, silently withholding newer closes.
2. **Cache key hardcoded to the module constant, not the caller's request.** The key was
   `f"{LOOKBACK_YEARS}y"` (always `"4y"`) regardless of the `lookback_years` argument actually
   passed to `get_daily_bars` -- so Chart's D_6M/D_1Y (`lookback_years=2`), D_2Y (`3`), W_4Y
   (`8`), and this feature's nightly job (`4`) all collided on one shared
   `(ticker, "historical_price_eod", "4y")` row, regardless of how much history each caller
   actually needed. Whichever caller fetched first each day "won"; everyone else silently read
   that one row.

**Confirmed live in production before fixing, not assumed**: a direct read-only query against
`backend/fathom.db` found **100 of 103** FMP-sourced `LiquidityZoneAnalysis` daily rows (and
all 103 weekly rows) stuck at `as_of` one full trading day behind the most recent close --
traced for `WDC` and others (AAPL, AMD, AMAT, AAOI) to the shared `"4y"` cache row having been
fetched by the *previous* night's run, under 24h old and so well inside the old 7-day window,
causing that night's run to skip a live re-fetch entirely and miss the newest close.

**Fix**: added `Settings.daily_bar_staleness_days` (`core/config.py`, default 1, a
day-scale window matched to daily-bar cadence), used in place of
`cache_staleness_days` at this one call site; threaded the caller's real `lookback_years` into
the cache key (`_fetch_fmp_daily_bars` gained a `lookback_years` parameter, used to build
`f"{lookback_years}y"`) instead of the `LOOKBACK_YEARS` constant -- `LOOKBACK_YEARS` itself is
unchanged and still what this feature's nightly job passes in, now genuinely isolated into its
own `"4y"` row rather than shared. Confirmed via a live re-run for `WDC` post-fix: Chart's
D_6M/D_1Y/D_2Y now each hold their own `"2y"`/`"3y"`/`"8y"` cache rows (previously all
would-be `"4y"` collisions) with a fresh `fetched_at` and the correct latest close
(2026-09-15); re-running this feature's own compute for `WDC` picked up the same fresh close
with zero code change needed here -- confirming the shared choke point in
`daily_price_sources.py` was sufficient and this feature's own files (`data/
liquidity_zone_data.py`, `pipeline/nightly_liquidity_zone_calculation.py`) needed none.
**No manual backfill was run** for the other stale rows identified above -- the next scheduled
3:25 AM nightly run self-heals every one of them (fresh cache key + 1-day staleness forces a
real re-fetch), so this was left to happen on its normal schedule rather than forced
out-of-band.



## Shared bars cache (2026-09-19): flat-timer audit and Screener technical-field ordering fix (score recompute 2:50 -> 3:50) (original lines 3500-3537)

- **Found while auditing for the same flat-timer pattern (2026-09-19):**
  (1) **FIXED, see "Screener's copy of technical fields" below.** `TickerScore.weinstein_*` was
  copied from `TrendAnalysis` at 2:00/2:50, before the 3:10 trend job, so the Screener showed the
  PREVIOUS night's stage. (2) (a flat-timer price fallback that no longer exists.) BB+RSI, Warren and Liquidity Zones have no
  read-time freshness gate at all (cache-only reads, unconditional nightly recompute); their only
  timers are the 7-day `STALE_AFTER_DAYS` abandonment sweeps, which are not freshness checks.
- **Screener's copy of technical fields was a night behind; score recompute moved 2:50 -> 3:50
  (2026-09-19).** `compute_ticker_score` copies `weinstein_*` (+ `reversal_status`/
  `pullback_status`) from `TrendAnalysis` (written by the 3:10 trend job), `bb_rsi_entry_signal`
  from the 3:20 BB+RSI job's row, and `warren_active_signal_kind`/`warren_last_buy_fired_at` from
  the 3:40 Warren job's rows. The full-universe recompute (`nightly_score_recompute`) ran at 2:50,
  and the 2:00 fundamentals fetch also scores each ticker inline -- both before any of those
  three jobs, so every one of those Screener fields was structurally a night behind. Confirmed
  live: 36 of 579 tickers' Screener Weinstein stage disagreed with their own `TrendAnalysis` row,
  all 36 copied before that row was written and all 36 exactly the tickers whose stage the trend
  job changed that night (the other 543 agreed only because their stage didn't change). Warren
  and BB+RSI showed ~0 disagreements the same night only because no ticker's latest signal
  changed -- the exposure was identical. **Fix: reorder, not a second copy** -- the recompute now
  runs at **3:50 AM**, after Warren (3:40, ~2 min today, ~9 min theoretical worst case) and
  before the 3:55 backup (recompute is ~30s, cache-only). Nothing depended on the old order:
  the trend job reads only the shared bars cache and its own universe, and `crontab.txt` already said it
  "doesn't need to wait on" the FMP jobs. Moving the trend job earlier instead would have fixed
  only `weinstein_*`/`reversal_status`/`pullback_status` and left BB+RSI/Warren a night behind
  (they can't all fit before 2:00 next to the Sunday maintenance window). The 2:00 fundamentals
  fetch's inline scoring is unchanged (its fundamentals-derived fields are fresh from 2:00; its
  technical fields are overwritten by the 3:50 sweep). Pinned by `tests/test_cron_wiring.py::
  test_score_recompute_runs_after_every_job_it_copies_from` (and `JOB_METADATA`'s time label by
  `test_job_metadata_sort_minutes_match_crontab`, which would have caught that display metadata
  going stale). Verified on a lean copy of the live DB (36 disagreeing + 24 agreeing tickers, real
  `recompute_all` code path, FMP disabled): 36 -> 0 stage disagreements, 56 -> 0 rows with any
  other mismatched `weinstein_*` field. **Deployed 2026-09-19** (`crontab crontab.txt` from
  `backend/`; `crontab -l` confirmed byte-identical to the committed file afterward -- editing
  the file alone changes nothing on this box). Baseline immediately before the deploy: still 36
  of 579 tickers' stage mismatched, and 173 on `weinstein_stage_since_date` (the more sensitive
  check -- the trend replay can revise a since-date without changing the stage). The first real-night confirmation is the run after the deploy
  (2026-09-20, 3:50 UTC); the read-only check is in `backend/OPS_RUNBOOK.md`'s
  `nightly_score_recompute` entry. After any night the trend/BB+RSI/Warren job overruns 3:50, the
  affected tickers just read a night behind as before.


## Sector Heatmap (/sectors, 2026-09-20): original heading and intro (7-window wording, superseded by 8 windows) (original lines 3704-3710)

## Sector Heatmap (`/sectors`, 2026-09-20)

The 11 SPDR sector ETFs (XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC) x 7 trailing
trailing-return windows (1w/1m/3m/6m/9m/YTD/1y). Round 1 of the ETF work in
`docs/etf_heatmap_momentum_investigation_2026-09-20.md` (file not in repo); the ETF momentum ranking is a separate,
later round and is **not** built. Price-only, zero FMP *fundamentals* calls, independent of Step 1-5
scoring. Bars come from FMP, through `SharedBarsCache` (`get_or_fetch_bars_batch`; see "Daily prices: FMP").


## Sector Heatmap (/sectors): job activation record (crontab install 2026-09-21) (original lines 3735-3739)

  **Active**: installed in the live crontab 2026-09-21 (`crontab crontab.txt` from `backend/`;
  `crontab -l` confirmed byte-identical to the file, and the only diff beforehand was this entry, so
  nothing outside the file was dropped). The first cron-triggered run was due 03:30 UTC (server
  time) that night -- check `CronRunLog`/`nightly_sector_heatmap.log` for it. Any later
  `crontab.txt` edit still needs the same reinstall; editing the file alone changes nothing.


## Sector Heatmap (/sectors): 'not verified on screen' and return-math verification note (original lines 3763-3766)

- **Not verified on screen** (no browser): layout, tint legibility, narrow-width behavior. The
  return math was checked against an independent calculation on live bar data (max difference
  1.5e-5pp) and the endpoint against the real DB.

