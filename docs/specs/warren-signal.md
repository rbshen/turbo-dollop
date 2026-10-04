# Warren RSI/ADX/WVF entry signal (2h) (Technical)

A fifth, fully independent technical entry-signal lens. Alongside BB+RSI it is the second entry in the
technical-signal family, both scoped to the same monitored-watchlist union (lists named `E<number>` or `ETF`, `data/watchlists.py`) and running on the same 2h adapter
(FMP 60m bars, resampled into 2h session candles). It is ported from a reference Pine script ("ANY TICKER
Δ1,3,4"); SPY, QQQ, TQQQ and TECL additionally have their own Blue Up definition ported from their
ThinkorSwim scripts (see "Per-ticker Blue Up profiles"). Buy-side (Blue/Yellow/Gray Up), sell-side (Blue/Yellow/Gray Down), the trailing stop line and the
gray-suppression state machine are all in scope, not an entry-only subset. The code lives in
`backend/analysis/warren_signal/` (`indicators.py`, `state_machine.py`, `types.py`, `profiles.py`), and
`state_machine.py`'s module docstring is the source of truth for the arrow conditions.

The history behind these choices (benchmark mistake, warm-up-buffer measurements, the 2026-09-19 cleanup,
retention analysis) is kept in `docs/archive/claude-md-history-technical-signals.md`.

## State machine: full nightly replay

Unlike BB+RSI's stateless per-bar condition, this is a genuinely sequential state machine.
`yellowEntryHeld` / `barsSinceYellow` / `yellowCountSinceBlue` / `stopCount` / the gray-suppression latch all
carry state forward bar-to-bar, so it can't be evaluated against a single candle in isolation the way
`check_buy_signal` can. It is resolved by a **full nightly replay from scratch**
(`analysis/warren_signal/state_machine.py::replay`) over the full available 2-year 60m-interval history,
resampled into the same 2h session candles BB+RSI already uses (reusing
`analysis/entry_signal/resample.py::build_2h_session_candles` directly). Intermediate state is discarded
after each run; only the resulting events are persisted.

This is safe because every input the state machine reads (`rsiValue[1..3]`, the current bar's own
low/high/close, and the vectorized RSI/ADX/WVF series feeding those) only ever looks backward. It is a
strictly causal system, so replaying the same history twice reproduces identical events for the shared
prefix (`test_state_machine.py::test_replay_is_deterministic_and_causal_across_reruns`). A direct
consequence: **there is no separate one-time backfill script** for this signal. BB+RSI's nightly job only
evaluates the latest trading day (hence `pipeline/backfills/backfill_entry_signal_events.py` to populate
older history once), while Warren's nightly job replays everything every night, so its very first run
already backfills all available history.

**Cost.** The dominant per-ticker cost is `build_2h_session_candles`' own per-day resample loop over the full
2-year history (~0.9-1.0s/ticker), not the replay itself (~30-40ms/ticker). A real run on the live 98-ticker
union (then the lists `W1`-`W5`, now `E1`-`E5`) took 98.9s, which extrapolates to roughly 9 minutes at the 500-ticker worst case. That is why the
job has its own ~15-minute cron window rather than a slot in a 5-minute gap. The shared, already-tested
`build_2h_session_candles` was deliberately not optimized, since BB+RSI depends on it. Any future benchmark
should go through the same entry point the real nightly job calls, not a lower-level convenience function.

## Indicators

- **RSI is deliberately re-implemented, not reused from BB+RSI's `compute_rsi`.**
  `analysis/entry_signal/indicators.py::compute_rsi` is EWM-seeded (pandas' `ewm` default, seeded from the
  first observation), a working RSI but not the one Pine's built-in `RSI(14)` computes. Pine's `ta.rsi` uses
  `ta.rma` internally, which is Wilder-seeded (a plain SMA over the first `length` bars, then recursive
  `out[t] = (out[t-1] * (length-1) + src[t]) / length`), the standard Wilder ATR convention. Warren's state machine depends on
  exact-value threshold crossings (12, 30, 70, 80.81, 84.75), so this divergence is load-bearing, not
  cosmetic. `analysis/warren_signal/indicators.py::wilder_rma` is a shared Wilder-smoothing helper (RSI,
  DMI's DI-smoothing and ADX's DX-smoothing all use it identically), with its own `compute_rsi_wilder` kept
  fully separate from BB+RSI's `compute_rsi`.
- **Wilder seed uses `np.nanmean`, not `.mean()`.** `close.diff()`'s structurally-NaN first element would
  otherwise poison the gain/loss seed window and make RSI `NaN`
  (`test_compute_rsi_wilder_is_0_for_unbroken_downtrend`,
  `test_compute_dmi_adx_reads_strongly_bullish_for_a_clean_uptrend`).
- **Dead code in the ANY-TICKER reference script, live in the per-ticker profiles.** `pivotLow` (plain, distinct from
  `pivotLowMajor`/`scanOverSold3`), `ADX_Between`, `WVF_Between` and `paraHighestHigh`/`paraDrop` (and the script's
  `scanOverSold1`/`scanOverSold2`) gate nothing in the ANY-TICKER script, so a ticker without its own profile never
  reads them (confirmed with the user before the original implementation; only the text description of that script
  was available, not the `.pine` file). SPY, QQQ, TQQQ and TECL's ThinkScripts define Blue Up with exactly these
  (`analysis/warren_signal/indicators.py`: `compute_pivot_low`, `compute_para_drop`, `adx_between`, `wvf_between`,
  `compute_blue`), all inclusive/strict exactly as written. The per-ticker Blue is the only place they are used.

## Per-ticker Blue Up profiles (2026-10-04)

SPY, QQQ, TQQQ and TECL each have their own Blue Up definition, transcribed from the ThinkScripts in
`~/warren-thinkscripts/` (`rp_RSI_WVF_{SPY,QQQ,TQQQ}STUDY.ts`, `rp_RSI_Pivot_WVF_TECLSTUDY.ts`; **the ThinkScript is the source of
truth**, no number comes from anywhere else). Every other ticker keeps the ANY-TICKER rule (`scanOverSold4`, `RSI[1] <= 12`), and its
output is byte-identical to before (pinned in `test_state_machine.py`; also checked identical on 60 real cached tickers, 1,589 events).

- **Mechanism.** `WarrenProfile` / `TickerBlueRules` (`types.py`), `ANY_TICKER` (the default), and `compute_blue(candles, rsi, adx, wvf,
  profile)` (`indicators.py`) replace the old `compute_scan_blue` call; `replay` / `replay_with_series` take `profile` (default `ANY_TICKER`).
  The engine never sees a ticker symbol. The symbol lookup is `data/warren_signal_data.py::profile_for` (`TICKER_PROFILES`): the **only**
  place a symbol selects a profile, used by `compute_and_store_warren_signal` (nightly) and by the Chart tab's on-demand 2H range, so the
  stored signal and the chart cannot use different definitions. The profiles are in `profiles.py`; their volume terms read guarded volume (next bullets).
- **What a profile changes.** Only the Blue Up trigger (`blueUp = scanOverSold1 or scanOverSold2`), which feeds `yellowCountSinceBlue`,
  `stopCount`'s reset, `anyBuy` (the `seen*` resets) and the `blue_up` arrow exactly as `scanOverSold4` did. Yellow/Gray up, every down
  arrow, the stop line and gray suppression are identical across all five scripts (diffed line by line). SPY/QQQ's extra `RSI > 50` in
  `scanOverbought` is redundant with `pivotHigh` (RSI > 70) and has no field. A Blue changes yellow/gray labels downstream: it resets
  `stopCount`, which un-grays a later yellow.
- **Operator rules.** `and` binds tighter than `or` (the scripts have no parentheses; `compute_blue` spells every grouping out), `Between` is
  inclusive, `RSI_Num[1]` is the previous 2h candle's RSI, `RSI_Num` the current one, and `volume` is the 2h candle's summed volume.
- **The numbers** (`profiles.py` is authoritative): `ADX_Between` 43-46 (SPY, QQQ) / 39.2-46 (TQQQ, TECL); `Volume_Num` 70M / 70M / 300M / 4M;
  SOS1 caps 24M (SPY), 24M and 10M (QQQ), 692200 (TQQQ, TECL); SOS2 branch-b RSI cutoff 14 / 16.1 / 16.61 / 16.61.
- **Ported as written, do not "fix" without the owner's decision.** (1) TQQQ's SOS1 volume cap is 692200, TECL's number (TQQQ's median 2h
  bar is ~18.7M shares, only 0.1% of bars are at or under 692200), so TQQQ's scanOverSold1 can essentially never fire; the script is
  TECL's with only `Volume_Num` changed. (2) QQQ's scanOverSold2 ends in two ungated ORs, `RSI_Num[1] < 16.3` and `WVF_Buy >= 17` (no volume
  or ADX condition), and the latter makes QQQ's own branch c (`WVF_Between(25, 27)`) unreachable on its own. (3) For SPY, TQQQ and TECL,
  SOS1 branch a is a strict subset of branch b and never contributes (test-pinned).
- **Chart.** The RSI pane's 12 "Blue trigger" reference line exists only for the ANY-TICKER profile: `warren_reference_levels(profile)`
  omits it for the four (their Blue is not a single RSI level). The pane label and lines come from the response's `warren_levels`, so
  the frontend has no logic for it.
- **Scope and data state (checked 2026-10-04).** None of the four is on a monitored list, so the nightly job does not process them and
  there are no `TechnicalEntrySignal`/`WarrenSignalEvent` rows for them (so adopting the profiles left no stale rows). The Chart tab's
  2H range computes the profiled signal on demand for them anyway (live, uncached, nothing stored). FMP returns the full 730 days of
  `/historical-chart/1hour` for all four: 499 sessions, 494 with 7 bars and 5 half-days with 4, RTH only. **Events are insert-only, so
  there is no purge or profile-version mechanism: editing a profile's thresholds later (or adding a ticker to `TICKER_PROFILES` after it
  already has stored events) leaves the old Blue rows behind.** Not built; out of scope of the 2026-10-04 change.
- **Volume guard (2026-10-04).** FMP's intraday volume has episodes where a few single 1-minute prints carry more shares than the whole
  day's official volume, so the volume-gated Blue branches (SOS1 `volume <= cap`, SOS2 `volume > Volume_Num`) fired on bars TOS shows no
  arrow for (QQQ Nov 2025, Dec 2025, Feb 2026: TOS prints Blue Ups only on 2025-04-07 09:30 and 11:30). Before the replay, for a
  profiled ticker only, `analysis/warren_signal/volume_guard.py::guard_candle_volume` sets the volume of **every 2h candle of a day to
  NaN** when `sum(day's 2h-candle volume) / day's EOD volume > DAILY_VOLUME_RATIO_LIMIT` (**1.5**, a named constant; exactly 1.5 is kept),
  **or when the day's EOD volume is missing, zero or NaN** (fail-closed). NaN fails both `>` and `<=`, so every volume term in the Blue
  rules is off that day, while the branches with no volume term (SOS2-c, QQQ's `RSI[1] < 16.3` and `WVF_Buy >= 17` ORs) keep working.
  The guard can only remove a Blue, never add one, and changes no Yellow/Gray/down-arrow input (those arrows move only if a removed Blue
  had reset the stop counter; on the real data they were identical).
  - **Where it lives.** In the candle build, between the 2h build and the replay; the engine, profiles and `compute_blue` are unchanged.
    `data/warren_signal_data.py::signal_candles(ticker, candles, daily_volume)` is the one shared step: the nightly store
    (`compute_and_store_warren_signal`) and the Chart tab's 2H range (`_get_chart_data_2h`) both call it. It returns `candles` itself
    (the same object) for every ticker without volume rules, so ANY-TICKER output cannot change; those tickers never read daily volume.
    It feeds the replay only: the candles the chart builds everything else from (bars, BB+RSI, LP) are untouched, and the chart response
    carries no volume field at all.
  - **Daily volume source.** The cached 1d bars (`SharedBarsCache`, `read_cached_daily_volume`, a pure read: completed sessions only, so
    the in-progress session and a last bar written before its own close read as "no EOD volume"). The cached volume is FMP
    `historical-price-eod/full`'s own: checked equal, 1,255 of 1,255 rows for each of SPY, QQQ and TECL (2026-10-04); TQQQ had no cached
    daily bars at that time. A profiled ticker with no cached daily bars (an unlisted ticker opened on the chart) costs one uncached
    `historical-price-eod/full` call per chart view (`_fetch_daily_volume_uncached`, completed sessions only, never written); a failed
    fetch, or nothing cached for the nightly job, blanks every day (no volume-gated Blue at all; only SOS2-c and QQQ's ORs can fire).
  - **Calibration (730 days, four tickers).** Hourly-sum / EOD is mostly 0.6-1.3 on normal days (the highest unflagged day is 1.30) and 1.5-7 in
    the bad episodes: TECL Mar-Jul 2025, QQQ and TQQQ Sep 2025 - Mar 2026 (26 of QQQ's 36 days above 1.3 are also TQQQ's), SPY 8 isolated days.
    At 1.5 the guard blanks 5 / 28 / 47 / 28 days (SPY / QQQ / TQQQ / TECL). The cause is upstream in FMP's intraday feed: the hourly bars
    equal the 1-minute sums, with no duplicate bars, extended-hours volume or mis-ordering. IBKR's TECL day volume stays at 0.77-0.82 of EOD
    through the same days, so EOD is the trustworthy side. Rejected alternatives: rescaling every day to EOD (creates a false SPY Blue on
    2025-04-07: EOD includes extended hours, ratio 0.58 that day) and rebuilding volume from 1-minute bars (identical on QQQ, and it
    loses TECL's 2025-04-07 Blue: FMP's 1-minute series was missing 16 of 390 minutes that day).
  - **Result (2026-10-04, production candle path).** QQQ: exactly two Blue Ups, 2025-04-07 09:30 and 11:30 (the 11:30 one fires on the
    ungated `RSI[1] < 16.3`); TECL: one (2025-04-07 09:30); SPY and TQQQ: none. Yellow/Gray/stop arrows identical to the unguarded replay for
    all four. TECL's four IBKR-validated Blues (2022-11-04, 2024-04-22, 2024-08-05, 2025-04-07) still fire with the guard on (IBKR day sum
    / EOD 0.72-0.93 on those days).
  - **Known limits.** (1) The 1.5 limit was calibrated on four tickers over two years; other tickers or periods may show other ratios.
    (2) The guard only removes volume gates. (3) The **low side is not addressed**: in Mar-Sep 2026 intraday volume runs 25-35% below
    EOD on all four tickers (monthly median ratio 0.62-0.78), which makes `volume > Volume_Num` harder and `volume <= cap` easier to
    meet; TOS volumes for that period have not been compared. (4) A just-finished session has no EOD volume until the daily-bar job has
    run, so a volume-gated Blue on it only appears once the next replay sees its EOD (events are insert-if-absent, so a later night
    adds it); the chart for the current day fails closed the same way.
- **Other data caveats for the volume gates** (FMP `/historical-chart/1hour`, measured 2026-10-04). (a) Prices and volume are **split-adjusted,
  dividend-unadjusted**: TQQQ's 2-for-1 on 2025-11-20 shows pre-split bars halved in price and doubled in volume (2025-11-18 close 49.16 vs
  the non-split-adjusted EOD close 98.36), while SPY/QQQ closes match the non-dividend-adjusted EOD close (SPY 2026-09-17: 762.64 vs
  762.60; dividend-adjusted would be 760.71). RSI, ADX, WVF and paraDrop are scale-free, so only the volume thresholds feel it (TQQQ's
  pre-2025-11-20 volumes are on the post-split scale; FMP's EOD volume is split-adjusted the same way, so the guard's ratio is
  unaffected). TOS reports raw volume. (b) For TECL the FMP 2h volume runs about 1.25x IBKR's RTH TRADES volume (median over 1,746 bars,
  drifting 1.1-1.3x by quarter). No TOS volume reference exists in the repo beyond the user's own chart checks.
- **Fire rates over the 2-year FMP window** (1,986 candles per ticker, 2024-10 to 2026-10): ANY-TICKER Blue fires 0 times for all four.
  With the volume guard the profiles fire 0 (SPY), 2 (QQQ, 2025-04-07 09:30 and 11:30), 0 (TQQQ), 1 (TECL, 2025-04-07 09:30); without it QQQ
  had 6. The branch code reproduces TECL's four known Blue Ups from 2022-2026 (`~/ubiquitous-fiesta/full_history_signals.csv`, IBKR bars)
  exactly. Tests: `analysis/warren_signal/test_profiles.py` (per-branch edges, and-before-or pin, QQQ ungated ORs),
  `analysis/warren_signal/test_volume_guard.py` (the guard: limit edges, missing/zero EOD, half-days, partial days, NaN through
  `compute_blue`, non-profiled untouched), `test_state_machine.py` (ANY-TICKER identical to the pre-profile pipeline),
  `tests/test_warren_signal_data.py` (profile selection, nightly routing and guard), `tests/test_chart_2h.py` (chart-vs-nightly
  consistency with and without a flagged day, fail-closed cases, displayed candles unchanged).

## Storage

- **Latest-state row: a shared table.** `TechnicalEntrySignal` (BB+RSI's own table) has 3 nullable columns,
  `signal_kind`, `gray_suppressed` and `stop_count`, always `NULL` for `signal_type="bb_rsi"` rows and
  populated only for `"warren"`. It reuses the table's composite PK `(ticker, signal_type, timeframe)`. For a
  `"warren"` row, `fired_at`/`rsi`/`close` describe the **latest event of EITHER direction** (buy or sell),
  not buy-only as BB+RSI's `fired_at` is. `stop_price` is the **live** `yellowStopPrice` as of the last
  replayed bar (`WarrenReplayResult.live_stop_price`), which can reflect an earlier-held yellow entry rather
  than the bar `signal_kind` fired on.
- **History: a dedicated table, `WarrenSignalEvent`,** not a reuse of `TechnicalEntrySignalEvent`. Warren's
  Blue-Up (`scanOverSold4`, `rsiValue[1] <= 12`; the four profiled tickers' own definition is in "Per-ticker Blue Up profiles") and Yellow-Up (`scanOverSold3`, a 3-bar oversold recovery
  pattern) conditions reference different bars' RSI values and can genuinely both be true on the same bar
  (a sharp V-shaped RSI spike from deeply oversold straight through 30). That would collide with
  `TechnicalEntrySignalEvent`'s `UniqueConstraint` on `(ticker, signal_type, timeframe, fired_at)`, which
  has no `signal_kind` to disambiguate. `core/db.py`'s `_add_missing_columns` is additive-column-only and
  cannot alter a constraint, and the app has no table-recreate tooling, so a brand-new table sidesteps
  this. `WarrenSignalEvent`'s `UniqueConstraint` is `(ticker, timeframe, fired_at, signal_kind)` from
  creation (pinned by `test_warren_signal_data.py::test_same_bar_co_firing_events_produce_two_distinct_rows`
  and the equivalent Chart-tab test).
- **`_upsert` always fully overwrites, unlike BB+RSI's conditional `should_advance` guard.** BB+RSI's job only
  evaluates the latest day and must avoid erasing a still-relevant prior fire on a quiet night. Warren's
  replay result already IS the complete current truth every run, so every field (`fired_at`, `rsi`,
  `close`, `signal_kind`, `stop_price`, `gray_suppressed`, `stop_count`) is set explicitly every run, `None`
  when there is no last event. Omitting the fired-fields from the `UPDATE`'s `SET` clause would silently keep
  a stale value (pinned by
  `test_a_full_replay_always_overwrites_the_prior_state_never_conditionally_advances`).
- **`active` is the literal `inTrade` mapping,** not a time window:
  `data/warren_signal_data.py::is_warren_signal_active(signal_kind)` returns whether the latest recorded
  event (of either direction) was a buy-side arrow (`blue_up`/`yellow_up`/`gray_up`), i.e. no sell arrow has
  fired since. Unlike BB+RSI's `is_entry_signal_active`, it never "expires" on its own; it only changes when
  a newer event of either direction is recorded.

## Write-side warm-up buffer

The full-replay design has one cost that BB+RSI doesn't share. The state machine starts blank at the
window's first candle, so events computed near that left edge are unreliable. RSI/ADX seeds settle in ~2
weeks, but the gray-suppression memory (`yellow_armed`/`stop_count`, mostly seen as gray_up <-> yellow_up
mislabels) takes months. Events are written insert-if-absent and never revised, and the window's start slides
forward a day every night, so without a buffer every night would persist a fresh crop of leading-edge
variants that no earlier (longer-context) night had produced. Right-edge (new) events have the whole window
as context and are ~0% wrong.

- **Rule** (`data/warren_signal_data.py::EVENT_WRITE_WARMUP_DAYS`, **180**): the nightly job still REPLAYS the
  whole window (that is what builds the state), but `_upsert` only inserts events with
  `fired_at >= first replayed candle + 180d`. The edge is inclusive and measured from the first candle of the
  data actually handed in, not a fixed date. 180d is where the measured error curve flattens (events past it
  sit at ~2-4% error falling to ~0%, ~1.3-1.6% averaged over everything written; 90d would keep ~7-16%, and a
  longer buffer buys little and costs stored history). It is a named constant, retunable in one place.
- **Only event writes are gated.** The latest-state row (`TechnicalEntrySignal`: `signal_kind`, `fired_at`,
  `stop_price`, `gray_suppressed`, `stop_count`, which the Technical card and Screener's
  `warren_active_signal_kind`/`warren_entry_signal` read) is still derived from the full, unfiltered replay,
  whose tail sits at the right edge. Pinned by `test_latest_state_row_is_identical_with_and_without_the_buffer`,
  which asserts it is byte-identical with the buffer on and off even when the last event itself falls inside
  the buffer. `warren_last_buy_fired_at` is read off the event table, so it does follow the buffer
  (`test_last_buy_signal_fired_at_reads_the_events_that_were_written`).
- **Why the buffer can't come from fetching more:** 60m history beyond ~730 days cannot be fetched. The
  buffer was also the prerequisite for raising retention (below): raising retention without it would have
  frozen phantom rows permanently (simulated: insert-only accumulates ~3.2x phantom rows vs. correct ones).
- **Known edge, left for a decision: recently-listed tickers.** A ticker with less history than the window
  (CRWV, SNDK at the time) replays from its own first candle, and its start is fixed rather than sliding, so
  its early events are reproducible night to night; that is not the accumulation problem this fixes. The
  literal rule still withholds its first 180 days, so a ticker under ~6 months old gets no chart markers or
  `last_buy` (its latest-state row still shows the signal). Exempting non-truncated windows is a small change
  if wanted. Regression tests are in `tests/test_warren_signal_data.py`.

## Event retention

`warren_signal_data.EVENT_RETENTION_DAYS` and `entry_signal_data.EVENT_RETENTION_DAYS` are both **1460 days
(4 years)**. They are the ceiling that `prune_warren_signal_events` / `prune_entry_signal_events` use, called
with no argument by both nightly jobs (no call site hardcodes a number).

- **It is a ceiling on stored history, not a fetch limit, and does NOT backfill.** Only ~730 days of 60m/2h
  bars are fetchable, so nothing older can be computed. The raise just stops deleting events once they pass 2
  years old, and depth then grows a day per day. Timeline (oldest stored event + 1460d): BB+RSI (oldest
  2024-09-27) reaches a full 4 years around **2028-09-26**; Warren (oldest 2025-03-24, because the
  2026-09-19 cleanup removed the earlier rows) around **2029-03-23**. Depth is also per ticker: a ticker
  added to a watchlist later only has whatever accrued since (for Warren, at most the ~550 days past the
  buffer at first compute).
- **Safe for Warren** because, with the write-side buffer, what is stored is ~2-4% error falling to ~0%, so
  keeping it longer preserves signal rather than noise. Pinned by
  `test_default_retention_is_four_years_and_comfortably_exceeds_the_warmup_buffer` (retention > 2x the
  buffer).
- **BB+RSI has no sliding-window accumulation problem:** its nightly job evaluates only the latest day over a
  60-day window (RSI's EWM seed has decayed to ~4e-6 by then), so nothing new is ever written near an
  unwarmed edge.
- **`SharedBarsCache` pruning (6y `1d` / 3y `60m`) is independent of event retention** and needs no change:
  events live in their own tables and no consumer recomputes events beyond the 730-day fetch window, so bar
  retention never gates event retention. (The 60m window, 3y, is shorter than 4y; that is fine for exactly
  this reason.) `tests/test_shared_bars_cache_prune.py` pins the bar windows against the consumers' fetch
  tiers, not against event retention.

## Nightly job

`pipeline.nightly_warren_signal_calculation`, scheduled **1:25 AM** server time (UTC), after BB+RSI (1:20) by convention - the shared 60m row is already ~2y wide, so the order only decides which job does the night's fetch with its own
10-minute allocation (observed ~100s, theoretical worst ~9 min) before the sector heatmap at 1:35. `backup_db` runs at 3:30. It is a dedicated script rather than part of `nightly_entry_signal_calculation.py`, for the same "one
feature, one script" reasoning as the Liquidity Zone job (see `docs/specs/liquidity-zones.md`), doubly
justified since Warren's 2-year-lookback / full-replay shape is fundamentally different from BB+RSI's
60-day / latest-day-only one, even though both share the monitored-watchlist scope and the shared 60m bars cache. It reads
the cache at the full 730-day width rather than through `clients/technical_sources.py`'s BB+RSI-sized 60-day
reader. It is wired into `core/cron_health.py`'s `CRON_JOB_NAMES` / `_EXPECTED_CADENCE_HOURS`. After its bars read it reports how many tickers' cached 60m bars are still stale (`stale_ticker_count`, same guard and "K still stale after fetch" message as BB+RSI and the daily-bar jobs); informational only, so it neither fails the run nor skips a ticker.

## API and UI

- `GET /api/tickers/{ticker}/entry-signal` takes a `signal_type` query param (`"bb_rsi"` default, or
  `"warren"`) branching to the matching backing read: one endpoint, two backing reads, matching how the DB
  itself discriminates by `signal_type`.
- **Chart tab:** `ChartMarkerOut` has a `kind` discriminator (`"bb_rsi"`, or one of Warren's 6 arrow kinds)
  driving frontend marker styling. `ChartOut` has a parallel `warren_signal_markers` /
  `warren_signal_available` pair alongside the existing `entry_signal_markers` / `entry_signal_available` one,
  rather than merging into it, keeping BB+RSI's wire shape untouched (the same "add a new pair alongside the
  old one" convention as Liquidity Zones' `zones` / `zones_available`). Warren's marker grouping keys on
  **(bucket, signal_kind)** rather than bucket alone, since two different arrows can genuinely fire on the
  same bar and must both render as distinct markers, while multiple fires of the SAME kind in one bucket
  collapse to the first (mirroring BB+RSI's tie-break reasoning). `TickerChart.tsx` renders Warren's markers
  via a second `createSeriesMarkers` call on the same candle series, styled by a
  `kind -> {color, shape, position}` lookup (Blue/Yellow/Gray x Up/Down; Up arrows below the bar, Down arrows
  above).
- **2H·90D Chart range (2026-10-02): computed on demand, not read from `WarrenSignalEvent`.** For any ticker the Chart tab
  replays the state machine over the same window as the nightly job (`today-729d`, 730 days of 60m bars resampled with the vectorised
  `build_2h_session_candles_fast`), drops the forming candle first, then slices the arrows to the last 90 days. Markers are **per candle**
  (one per (candle, kind)), time-stamped by the candle's window start, not bucketed per day/week as the daily ranges' stored-event markers are.
  `replay_with_series` additionally returns the RSI, +DI, -DI, ADX and WVF(`wvfBuy`) series the machine used (the existing `replay()` and its outputs
  are unchanged) and `warren_reference_levels()` reads the thresholds from the same constants (RSI 12/30/70/80.81/84.75, ADX 40, WVF 0.40; the RSI 12 line is omitted for the four tickers with their own Blue profile), so the three panes
  always match the arrows. Warm-up matters: a 90-day-only replay gives different arrows, and the Wilder RSI differs from the chart's EWM RSI by up to ~19
  points on 90 days of data (it converges to ~1e-14 with 730 days). **Consistency with stored data (checked 2026-10-02, 108 monitored tickers, last 90 days):**
  the Technical tab's latest-state row matched the on-demand replay for 105 of 105 tickers; of 346 stored arrows, 330 reproduced and 16 (14 tickers) did not, none
  the other way round. 14 of the 16 were written before the FMP bar switch (2026-09-26); the other two (CRM, NTAP) sit at borderline RSI thresholds (e.g. 84.32 against 84.75). Every
  one of the 16 is at a threshold margin, and stored events are insert-only, so on-demand is the truth for the current bars and stored history can contain a few such stragglers. For BB+RSI the stored events mix
  the backfill's first-fire-of-day with the nightly job's last-fire-of-day, which is why the 2H range shows every firing candle instead.
- **Technical tab:** `WarrenSignalCard`, structurally mirroring `BbRsiEntrySignalCard`, surfaces the last
  signal's kind and timestamp, the live stop line, and the gray-suppression latch with its stop count.
- **Test isolation:** any test that reaches `get_chart_data` must isolate a fresh engine for
  `data/warren_signal_data.py`'s own `engine` reference, because `get_chart_data` calls
  `get_warren_signal_data` unconditionally. `test_chart_endpoint.py` has a `_fresh_warren_signal_engine`
  helper and `test_chart_data.py` an autouse `_default_no_warren_signal` fixture, mirroring the other
  per-module engine-isolation helpers (see `CLAUDE.md`, "Ad-hoc reproduction scripts must not touch the
  real database").
