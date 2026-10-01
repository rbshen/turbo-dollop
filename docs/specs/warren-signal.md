# Warren RSI/ADX/WVF entry signal (2h) (Technical)

A fifth, fully independent technical entry-signal lens. Alongside BB+RSI it is the second entry in the
technical-signal family, both scoped to the same W1-W5 watchlist union and running on the same 2h adapter
(FMP 60m bars, resampled into 2h session candles). It is ported from a reference Pine script ("ANY TICKER
Δ1,3,4"). Buy-side (Blue/Yellow/Gray Up), sell-side (Blue/Yellow/Gray Down), the trailing stop line and the
gray-suppression state machine are all in scope, not an entry-only subset. The code lives in
`backend/analysis/warren_signal/` (`indicators.py`, `state_machine.py`, `types.py`), and
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
W1-W5 union took 98.9s, which extrapolates to roughly 9 minutes at the 500-ticker worst case. That is why the
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
- **Not ported (dead code in the reference script).** `pivotLow` (plain, distinct from
  `pivotLowMajor`/`scanOverSold3`), `adxBetween`, `wvfBetween`, and `paraHighestHigh`/`paraDrop` are computed
  in the given spec but never gate any arrow or state transition, the same class of dead code as
  `scanOverSold1`/`scanOverSold2`. This was confirmed with the user before implementation (only the text
  description of the script was available, not the `.pine` file).

## Storage

- **Latest-state row: a shared table.** `TechnicalEntrySignal` (BB+RSI's own table) has 3 nullable columns,
  `signal_kind`, `gray_suppressed` and `stop_count`, always `NULL` for `signal_type="bb_rsi"` rows and
  populated only for `"warren"`. It reuses the table's composite PK `(ticker, signal_type, timeframe)`. For a
  `"warren"` row, `fired_at`/`rsi`/`close` describe the **latest event of EITHER direction** (buy or sell),
  not buy-only as BB+RSI's `fired_at` is. `stop_price` is the **live** `yellowStopPrice` as of the last
  replayed bar (`WarrenReplayResult.live_stop_price`), which can reflect an earlier-held yellow entry rather
  than the bar `signal_kind` fired on.
- **History: a dedicated table, `WarrenSignalEvent`,** not a reuse of `TechnicalEntrySignalEvent`. Warren's
  Blue-Up (`scanOverSold4`, `rsiValue[1] <= 12`) and Yellow-Up (`scanOverSold3`, a 3-bar oversold recovery
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

`pipeline.nightly_warren_signal_calculation`, scheduled **12:25 AM** server time (UTC), AFTER BB+RSI (12:20, which creates the 60d intraday row Warren widens) with its own
10-minute allocation (observed ~100s, theoretical worst ~9 min) before the sector heatmap at 12:35. `backup_db` runs at 3:30. It is a dedicated script rather than part of `nightly_entry_signal_calculation.py`, for the same "one
feature, one script" reasoning as the Liquidity Zone job (see `docs/specs/liquidity-zones.md`), doubly
justified since Warren's 2-year-lookback / full-replay shape is fundamentally different from BB+RSI's
60-day / latest-day-only one, even though both share the W1-W5 scope and the shared 60m bars cache. It reads
the cache at the full 730-day width rather than through `clients/technical_sources.py`'s BB+RSI-sized 60-day
reader. It is wired into `core/cron_health.py`'s `CRON_JOB_NAMES` / `_EXPECTED_CADENCE_HOURS`.

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
- **Technical tab:** `WarrenSignalCard`, structurally mirroring `BbRsiEntrySignalCard`, surfaces the last
  signal's kind and timestamp, the live stop line, and the gray-suppression latch with its stop count.
- **Test isolation:** any test that reaches `get_chart_data` must isolate a fresh engine for
  `data/warren_signal_data.py`'s own `engine` reference, because `get_chart_data` calls
  `get_warren_signal_data` unconditionally. `test_chart_endpoint.py` has a `_fresh_warren_signal_engine`
  helper and `test_chart_data.py` an autouse `_default_no_warren_signal` fixture, mirroring the other
  per-module engine-isolation helpers (see `CLAUDE.md`, "Ad-hoc reproduction scripts must not touch the
  real database").
