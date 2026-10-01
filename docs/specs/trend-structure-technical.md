# Trend structure analysis (Technical tab)

A read-only lens on price structure — swing highs/lows, break-of-structure (BOS) flips, and a
blended -10..+10 conviction score — computed from FMP daily bars via the shared bars cache, not
the fundamentals pipeline. Never touches Step 1-5/Overall Assessment scoring, the
`FundamentalsCache`, or any other lens — a second, parallel data path from ingestion through to
display. This document covers the swing/BOS engine, the A/D-divergence and SMA-position
layers, and the nightly job that feeds them, then the three later fields (`trend_started`,
`pullback_history`, `reversal_history`). The Weinstein weekly-stage lens, computed by the same
nightly job, has its own document: [Weinstein Stage](weinstein-stage.md).

## Engine (`backend/analysis/trend_structure/`, pure functions/dataclasses, no DB/HTTP)

- **Swings**: fractal swing detection on daily CLOSE only (`FRACTAL_N` = 5 bars each side). Each
  swing is classified against the highest/lowest of the **trailing 3** same-type swings
  (`TRAILING_WINDOW`, not just the single prior one) into HH/HL ("bullish") or LH/LL
  ("bearish"). Wilder's ATR(14) from real OHLC gates confirmation via `ratio = margin/ATR`.
- **Flip gate** (`state_machine.py`): `trend_state` only flips to uptrend on a confirmed
  (`ratio >= CONFIRMED_RATIO`, 1.0) HH, or to downtrend on a confirmed LL. A confirmed LH/HL
  (regardless of ratio) never flips state, only sets `warning_flag` + `warning_swing`, clearing
  on the next same-direction confirmed (>= `WEAK_RATIO`, 0.5) swing or converting into a real
  flip once the genuine opposite extreme eventually confirms.
- **`magnitude_tier`** (weak/confirmed/strong) only updates on weak-confirmed+ (>= 0.5)
  same-direction swings — a tentative (< 0.5) swing still bumps `persistence_count` but must not
  change the tier.
- **Regime** (`regime.py`): a 60-day Kaufman Efficiency Ratio; `"trending"` if ER >= 0.15, else
  `"range-bound"`.
- **Blended conviction score** (`conviction.py::compute_blended_score`): tier score (weak 0.33 /
  confirmed 0.67 / strong 1.0), persistence (`min(persistence_count, 10) / 10`) and recency
  (`max(0, 1 - bars_since_confirmation / 30)`) weighted 50/30/20%, discounted 0.7x for a
  non-trending regime and 0.7x again under an active warning, signed by trend direction and
  scaled to -10..+10. A thin-history ticker with no tier/recency scores those components as 0
  rather than raising.
- **`bar_level`** (1-5) is a **continuous rescale** of the blended score,
  `min(4, floor((score + 10) / 20 * 5)) + 1`, computed backend-only and never re-derived on the
  frontend: bands are 4 raw-score points wide (1: -10..-6 strong downtrend, 2: -6..-2 moderate
  downtrend, 3: -2..2 neutral, 4: 2..6 moderate uptrend, 5: 6..10 strong uptrend). *The original
  spec's literal formula `(score + 10) / 20 * 4` and its own reference band table disagreed (the
  formula gives width-5 bands, transitioning at -5/0/5, not the table's -6/-2/2/6); the user
  confirmed the table is authoritative, so the code uses `/20 * 5`, which reproduces it exactly.
  See `conviction.py`'s own comment for the derivation.*

## Storage, nightly job and API

- **Storage**: `TrendAnalysis` (`core/models.py`; ticker PK, `computed_at`, latest-only, upserted
  per run — the same convention as `TickerScore`). `last_confirmed_swing`/`warning_swing` are
  plain `str` JSON columns, this codebase's established convention for a JSON-shaped field (there
  is no native JSON column type anywhere in it). Bars come from `SharedBarsCache` (see
  `docs/specs/fmp-data-and-bar-cache.md`), deliberately not `core/cache.py`, which is hard-wired
  to `FundamentalsCache`'s (ticker, statement_type, period)+raw_json shape.
- **Nightly job** (`pipeline/nightly_trend_calculation.py`, **12:05 AM**, after the 12:00 last-close
  snapshot and before the 3:30 AM backup; the 3:25 score recompute then copies its
  `weinstein_*` output onto `TickerScore`): sweeps the full tracked universe
  (`load_full_tracked_universe`, shared with the fundamentals/score-recompute jobs) via **one**
  batch read (`clients.shared_bars_cache.get_or_fetch_bars_batch`), runs the engine and upserts
  per ticker — never one live fetch per ticker. It is the one nightly job that actually fetches
  daily bars (Sunday UTC is a full resync); every later bar consumer reads its warm cache. The
  fetch is `WEINSTEIN_LOOKBACK_DAYS` = 5 years wide (the Weinstein replay needs the long run-in),
  and the swing/BOS engine still gets its own 730-day slice of it (`_trend_window`,
  `LOOKBACK_DAYS` = 730, cut exactly where the cache used to cut) — verified byte-identical
  `trend_state`/`blended_score`. Wired into `core/cron_health.py`'s `CRON_JOB_NAMES`/
  `_EXPECTED_CADENCE_HOURS`. Delisted-flagged tickers are skipped (see the FMP data spec).
- **On-demand freshness**: `data/trend_analysis_data.py::get_trend_analysis_data` compares
  `TrendAnalysis.bars_as_of` with the last completed session — see "Trend's computed row is
  close-aware too" in the FMP data spec.
- **API**: `GET /api/tickers/{ticker}/trend-analysis` (`TrendAnalysisOut`, carrying every field
  in this document) feeds the ticker page's Technical tab. The Watchlist no longer shows any of
  these fields: its TREND, A/D Div. and 20/50/200SMA columns (and the 5-bar `SignalBars`
  indicator) were removed 2026-09-06 as a display-layer change — `WatchlistRowOut` no longer
  carries `bar_level`/`blended_score`/`trend_state`/`ad_*`/`sma*` and `_compose_row` no longer
  calls `get_trend_analysis_data`. The `TrendAnalysis` model, the cron, the engine and this
  endpoint were untouched; `bar_level` is still computed and served but nothing on the frontend
  reads it now, and no `SignalBars` component remains in the frontend.

## A/D Bullish Divergence (2026-08-23)

A validated (ticker-clustered p<0.01, replicated on two separate backtest universes, ~+2pp hit
rate / ~+2% mean-median return to the eventual confirmed HH) **minor** conviction signal layered
on the swing engine — never a standalone entry trigger, never applied to bearish/HH-side swings
(tested, no edge, intentionally excluded), and a binary flag only, not a graduated score (never
validated at that granularity).

- **Signal** (`analysis/trend_structure/ad_line.py`): the Accumulation/Distribution line (Money
  Flow Multiplier × Volume, cumulative sum; the multiplier reads `0.0`, not NaN, on a zero-range
  high==low bar) and the Chaikin Oscillator, `EMA(3) - EMA(10)` of the A/D line (`AD_FAST_SPAN`/
  `AD_SLOW_SPAN`), standard non-Wilder EMA via `adjust=False` — a deliberate, documented formula
  choice, the same way `atr.py` calls out its own Wilder smoothing.
- **Divergence rule** (pinned down exactly after several rounds of clarification — easy to
  misremember or reimplement slightly wrong): at each LL swing (any ratio), take the literal
  minimum Chaikin Oscillator value within a **positional (trading-bar, not calendar-day) ±10-bar
  window centered on that swing's own date** (`AD_DIVERGENCE_MATCH_WINDOW` = 10) — naturally
  truncated/asymmetric near either end of the available history via plain slice bounds, never
  waiting on a future bar that doesn't exist yet (a newly-confirmed LL with only 3-4 forward
  trading days is evaluated on the truncated window immediately, not left pending). Call this the
  swing's "matched oscillator low". Bullish divergence fires when **this matched low is strictly
  greater than the MIN (floor) of the matched lows of the trailing 3 prior *CONFIRMED* LL swings**
  (ratio >= `CONFIRMED_RATIO`, 1.0 — the same threshold `state_machine.py` uses for a genuine
  flip) — an exact equal value does not count. This deliberately mirrors `classification.py`'s
  own price-swing convention (a new low that stays above the trailing-3 floor classifies as the
  non-confirming "HL", not a new "LL"), applied to the oscillator's values instead of price. A
  non-confirmed LL still gets its own divergence flag computed against whatever floor already
  exists, but is never itself added to the trailing-3 confirmed pool
  (`test_non_confirmed_ll_is_evaluated_but_excluded_from_the_confirmed_pool` is the regression
  test for that rule). Zero prior confirmed LLs to build a floor from reads as `False` (no
  baseline), the same "not classifiable without trailing history" convention `classify_swings`
  uses for HH/HL/LH/LL itself.
- **Folded into the existing single classification pass** (`classification.py::classify_swings`
  takes a third `chaikin_osc` parameter; the lookup/comparison happens inline exactly where a new
  "LL" is classified, reusing the OHLCV series `engine.py` already computes ATR from) — no second
  pass or second per-ticker fetch, and one extra O(n) EMA pass plus O(1)-ish per-LL window
  lookups.
- **Fields**: `TrendAnalysis.ad_bullish_divergence` (bool, nullable) / `ad_divergence_swing_date`
  (date, nullable) hold the ticker's **most recent confirmed LL's** own divergence result only
  (`engine.py` selects it from the full classified list; `classification.py` computes the flag for
  every LL inline). Nullable — unlike the pure engine's always-real `bool`/`date|None` output —
  because `core/db.py::_add_missing_columns` adds columns via a raw `ALTER TABLE` with no
  backfill: existing rows read `NULL` until the next nightly run rewrites every field, and every
  consumer already treats `None` as `False`, so this is a transient-read-safety concern only.
- **`blended_score` integration**: a flat `1.15x` multiplier (`AD_BULLISH_DIVERGENCE_MULTIPLIER`,
  `conviction.py`), applied as the literal last step — strictly after the regime/warning_flag
  dampeners — and gated on `trend_state == "uptrend"`. Deliberately retrospective, not a
  downtrend-name trigger: it only boosts names where the divergence-flagged LL has already played
  out into a confirmed uptrend. It can push `blended_score` slightly past the documented ±10
  ceiling (`10.0 * 1.15 = 11.5`), left unclamped because clamping would zero out the boost for
  exactly the highest-conviction names, and `compute_bar_level`'s own `min(4, ...)` clamp
  already tolerates it.
- **UI today**: the divergence is read on the Technical tab — `ReversalCard.tsx` uses
  `ad_bullish_divergence` for its checklist and each `reversal_history` dot carries its own
  per-swing flag (see below). The Watchlist "A/D Div." column that originally showed it was
  removed 2026-09-06.

## SMA (20/50/200) position tracking (2026-08-23)

A second, much simpler signal on the same nightly batch (no new fetch, pass or cron change): for
each ticker, how far the latest close sits above/below its 20/50/200-day SMA
(`position_pct = (close - SMA)/SMA*100`), plus whether it crossed the SMA today
(`cross: "up" | "down" | None`).

- **`analysis/trend_structure/sma_position.py::compute_sma_position(close, period)`**, a single
  pure function in `atr.py`'s one-file-per-concern style (deliberately not a reuse of
  `analysis/ma_magnet/indicators.py::compute_mas` — `ma_magnet` is unwired research code
  production never imports from). `position_pct` is `None` whenever fewer than `period` bars of
  history exist (`rolling(window=period).mean()`'s own `min_periods == window` produces NaN
  there), so a recent IPO degrades the way the rest of the engine does for thin history.
- **Crossing compares the PRIOR bar's own SMA against the PRIOR close**, not today's SMA reused
  against yesterday's close — `rolling().mean()` produces a distinct SMA per day, so reusing
  today's would false-positive or miss real crossings whenever the SMA itself moved meaningfully
  day over day. `cross` is `None` when there is no valid prior bar to compare (a ticker's first
  eligible bar, exactly `period` bars of history), even when `position_pct` is real.
- **A single tri-state `cross` field per SMA**, not two booleans (`crossed_up`/`crossed_down`) —
  they could never both be true, so one field is simpler and maps directly to a single tint
  decision.
- **`today_sma == 0` (and the prior day's SMA) is guarded, returning `None` rather than
  dividing.** Effectively impossible for a real equity close, but a `0/0`/`x/0` division would
  upsert `inf`/`nan` into SQLite, which Python's default JSON encoder serializes as the literal
  tokens `Infinity`/`NaN` — invalid strict JSON that would break the frontend's `JSON.parse` on
  that one row.
- **Six flat fields** (`sma20_position_pct`/`sma20_cross`, ×3 for 50/200) threaded through
  `TrendStructureResult` → `TrendAnalysis` (nullable, same no-backfill reasoning as
  `ad_bullish_divergence`) → `TrendAnalysisOut`. The Watchlist columns that displayed them were
  removed 2026-09-06 (see "Storage, nightly job and API").

## Why these three fields exist

Two review-flagged UX gaps on the Technical tab's Near-term/Pullback-recovery and Reversal cards
motivated a 2026-09-13 investigation, then a same-day build:

1. **"Turned up on" drifts away from the real flip date** as `persistence_count` accumulates —
   the card needed to show *when the current trend actually began*, not just the most recent
   re-confirming swing.
2. **No visibility into how many pullback-and-recovery cycles have already happened** within the
   current trend, or (for a downtrend) how many confirmed lower-low reversal candidates have
   occurred, each with its own A/D-divergence read.

Both investigations found the same shape of gap already solved once, for a different lens:
Weinstein Stage Analysis's `weinstein_stage_since_date`/`_is_lower_bound` (see
[Weinstein Stage](weinstein-stage.md)) already answers "when did the *current* state begin," and
that same lower-bound convention is reused here rather than reinvented.

## `trend_started` (the real flip date)

`state_machine.py::run_state_machine` already identifies the exact swing that triggers a genuine
flip at one call site. `state.flip_swing` is set there, reusing the existing `SwingDetail` type
verbatim — no new dataclass. Surfaced as `TrendAnalysisOut.trend_started`.

**Bootstrap semantics, a real design decision, not just plumbing.** The module's own docstring
is explicit that the very first classified swing bootstraps `trend_state` by assumption — "the
spec has no rule for 'what was the trend before any flip occurred.'" Concretely,
`run_state_machine`'s loop starts at `classified[0]` itself, and since `trend_state` was already
seeded to that swing's own direction, `classified[0]` always lands in the same-direction branch,
never the flip branch — so a naive implementation would show `trend_started: null` for exactly
the tickers with the longest cached runway (any ticker whose current trend has never flipped
since cached history began).

**Fixed the same way Weinstein Stage's own "since" field is**: `flip_swing` is populated from
`classified[0]` on bootstrap too, paired with `flip_swing_is_lower_bound: bool` (surfaced as
`TrendAnalysisOut.trend_started_is_lower_bound`) — rather than leaving it `null`, the field
reports the earliest available swing as a lower bound, honestly labeled as "predates tracked
history" rather than "never flipped."

Confirmed against real cached data (SNAP, SOFI, ZTS, XYL, WYNN — genuine-flip case,
`trend_started_is_lower_bound=0`; FDXF, HONA, PARA — bootstrap/lower-bound case). One subtlety
confirmed directly: the bootstrap sets `flip_swing = classified[0]` regardless of whether that
first-ever classified swing happens to be the *primary*-for-direction type or not (a downtrend's
bootstrap `trend_started` can correctly read `"classification": "LH"`, not `"LL"`, since the
direction itself is bootstrapped from `classified[0]`'s bullish/bearish grouping, which only
requires "LH or LL," not specifically the primary type).

## `pullback_history` (completed warning→resolution cycles within the current trend)

`run_state_machine` already visits every classified swing once and already distinguishes (a) a
swing that sets a warning, (b) a same-direction confirming swing that clears a pending warning,
and (c) a flip, which implicitly closes out any still-open warning as "invalidated" rather than
"resolved." A `PullbackCycle(warning_swing, resolving_swing)` is appended to a
`pullback_cycles: list[PullbackCycle]` accumulator at case (b), and the list is reset to `[]` at
every genuine flip (the same trigger `persistence_count` resets on).

**Storage shape, a real decision.** Two live precedents existed for "more than the single latest
state": a bounded JSON list on the existing `TrendAnalysis` row (mirroring
`LiquidityZoneAnalysis.support_zones_json`), or a real accumulating event table (mirroring
`WarrenSignalEvent`). The bounded-JSON-list option was chosen — the task ("within the current
trend," "mini-timeline") matches it exactly, at a fraction of the cost (no new table, no pruning
cron), and the list is naturally self-bounding since it resets on every flip. A real event table
across *every* trend a ticker has ever had would be a materially bigger feature, not a
refinement of this one. Confirmed via real cached history that "small" is genuinely small even
for an unusually persistent multi-year trend (one real 2.3-year uptrend contained 9 separate
warning→resolution cycles before eventually flipping without one final warning ever resolving).

Storage: `pullback_cycles_json` column on `TrendAnalysis` (nullable, `_add_missing_columns`),
reset to `"[]"` every genuine flip. Surfaced as `TrendAnalysisOut.pullback_history: list[
PullbackCycleOut]`, oldest first.

## `reversal_history` (confirmed LL swings within the current downtrend, each with its own A/D-divergence read)

A structurally different shape than `pullback_history` — **single-point events**, not pairs:
every confirmed LL swing that has occurred *within the current downtrend*, each carrying its own
`ad_bullish_divergence`/`ad_divergence_swing_date` (both already computed per-swing by
`classify_swings`, just never retained past "most recent one" before this build). Feeds
`ReversalCard.tsx`'s own dot-timeline.

**Design decision: seed with the flip-triggering LL, unlike `pullback_history`'s exclusion.** A
flip event and a "pullback cycle" are categorically different things (a trend-state transition
vs. a completed pause-then-continue pair), so `pullback_history` correctly excludes the
flip-triggering swing. `reversal_history` has no such categorical distinction — the swing that
flips a trend into a downtrend *is itself* a confirmed LL, exactly the same kind of event every
later same-direction confirmed LL in that downtrend would also be. Mechanically resetting to
`[]` on flip and never appending the flip-triggering LL anywhere else would show an **empty**
`reversal_history` for a freshly-flipped downtrend even while `last_confirmed_swing`/
`ReversalCard`'s own "Confirmed" checklist item already shows that exact LL as satisfied — a
visible inconsistency between the card's headline status and its own history list. Fixed by
appending the flip-triggering LL as the list's first entry in the same flip branch that sets
`flip_swing`/`trend_started`, and only when flipping *into* a downtrend (flipping into an
uptrend resets to `[]` unconditionally — `reversal_history` has no meaning outside a downtrend).

**Which layer owns this — confirmed, not assumed.** `classify_swings()` (`classification.py`)
has no concept of `trend_state` or trend-segment boundaries at all; its own
`confirmed_ll_osc_lows` accumulator (the trailing-3 divergence floor) accumulates across *every*
confirmed LL in the ticker's entire classified history, unconditionally, and is deliberately
**not** scoped to "current downtrend" — that's validated backtest behavior for the divergence
rule itself, not something this feature should disturb. `run_state_machine` is the only layer
that knows what "current downtrend" means, and it already visits every classified swing once, in
order — so `reversal_history` accumulates there, in the same single pass as `pullback_history`,
with zero new iteration.

**One pre-existing quirk, not introduced by this feature and not fixed by it**: because
`classify_swings()`'s own divergence floor ignores trend-segment boundaries, an early confirmed
LL within a brand-new downtrend can have its `ad_bullish_divergence` computed against a
trailing-3 floor that reaches backward across the flip, into confirmed LLs from a *prior*
downtrend the ticker had before an intervening uptrend. This was already true of the single
`ad_bullish_divergence` value the engine surfaced before this feature existed (`engine.py`'s own
`confirmed_lls` selection scans the entire multi-trend `classified` list with no trend-boundary
filter either); scoping the *list* to the current downtrend is a state-machine-level
list-membership question and does not, and should not, require re-deriving each entry's own
already-computed divergence flag.

Storage: `reversal_history_json` column on `TrendAnalysis` (nullable, same convention as
`pullback_history_json`). Surfaced as `TrendAnalysisOut.reversal_history: list[
ReversalCandidateOut]`, oldest first.

## `trend_started` for downtrends — no separate work needed

Confirmed directly against real cached data (172 live `downtrend` rows) that `flip_swing`/
`trend_started` is written by exactly one field, set identically regardless of which direction
is flipping into — there is no uptrend-specific branch in `run_state_machine` that a downtrend
equivalent could be missing from. Both the genuine-flip and bootstrap/lower-bound branches are
exercised correctly by real downtrend rows in production.

## Backtest-compatibility

The two shipped fields above build on `bt_signal2_analyze.py`'s (Trend Continuation/Reversal
card) and `bt_signal1_analyze.py`'s (the same, an earlier round) already-completed, already-
shipped findings — neither script exists in this checkout (per `CLAUDE.md`'s documented
`backend/scripts/` convention: untracked, ad-hoc research tooling, never committed). Every new
field here is purely additive to `TrendStructureResult`/`TrendAnalysisOut`/`TrendAnalysis`
(dataclass/Pydantic fields accessed by name everywhere in this codebase, never positionally), so
this class of addition carries the same low, already-established risk to any local, uncommitted
copy of either script that might still exist.
