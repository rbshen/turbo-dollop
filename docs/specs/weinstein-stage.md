# Weinstein Stage Analysis — base engine, pending confirmation/ETA, and the daily-timeframe question

Stan Weinstein's classic 4-stage (Base / Advance / Top / Decline) methodology, ported from a
reviewed Pine Script v6 reference implementation ("Weinstein Stage Screener") and computed on
**weekly** bars. It is independent of the fundamentals scoring. This document covers the
storage/job/API plumbing, the shipped base engine (Part 0), then two rounds of design work
layered on top of it: the "pending confirmation" + ETA feature (Part 1) and the
daily-timeframe question (Part 2).

> **Historical names.** `TrendAnalysis` (table), `/api/tickers/{ticker}/trend-analysis`,
> `TrendAnalysisOut`, `useTrendAnalysis`, `data/trend_analysis_data.py`,
> `pipeline.nightly_trend_calculation` and the `analysis/trend_structure/` package are named for
> the swing/BOS trend-structure engine (swing highs/lows, BOS flips, blended conviction score,
> A/D divergence, SMA position, and the Near-term / Pullback recovery / Bullish reversal /
> Long-term cards and Screener Reversal/Pullback filters) that shared them until it was removed
> 2026-10-01. Weinstein is all they serve now; the names were deliberately kept. The package
> also still holds `stochastic.py` (the Chart tab's Stochastic).

## Storage, nightly job and API

- **Storage**: `TrendAnalysis` (`core/models.py`; ticker PK, `computed_at`, `bars_as_of`,
  latest-only, upserted per run — the same convention as `TickerScore`). Bars come from
  `SharedBarsCache` (see [FMP data and bar cache](fmp-data-and-bar-cache.md)), deliberately not
  `core/cache.py`, which is hard-wired to `FundamentalsCache`'s shape.
- **Nightly job** (`pipeline/nightly_trend_calculation.py`, **12:05 AM**, after the 12:00
  last-close snapshot; the 3:25 score recompute then copies its `weinstein_*` output onto
  `TickerScore`): sweeps the full tracked universe (`load_full_tracked_universe`) via **one**
  batch read (`clients.shared_bars_cache.get_or_fetch_bars_batch`), runs the Weinstein engines and
  upserts per ticker — never one live fetch per ticker. It is the one nightly job that actually
  fetches daily bars (Sunday UTC is a full resync); the LP, Sector Heatmap, Market Breadth and
  Momentum jobs read its warm cache, so this job cannot be removed or reordered after them. The
  fetch is `WEINSTEIN_LOOKBACK_DAYS` = 5 years wide. Wired into `core/cron_health.py`'s
  `CRON_JOB_NAMES`/`_EXPECTED_CADENCE_HOURS`. Delisted-flagged tickers are skipped (see the FMP
  data spec).
- **On-demand freshness**: `data/trend_analysis_data.py::get_trend_analysis_data` compares
  `TrendAnalysis.bars_as_of` with the last completed session — see "Trend's computed row is
  close-aware too" in the FMP data spec.
- **API**: `GET /api/tickers/{ticker}/trend-analysis` (`TrendAnalysisOut`, Weinstein + pending
  fields) feeds the ticker page's Technical tab and header pill.

## Part 0 — the base engine (`analysis/trend_structure/weinstein.py`)

The engine is the validated Pine `sState` port, fully driven by `WeinsteinParams`, whose defaults
are the Pine reference's own: `ma_length` 30, `ma_type` EMA (`ewm(span, adjust=False,
min_periods=length)`; SMA supported), `within_range_pct` 5.0, `slope_lookback` 5,
`breakout_volume_mult` 2.0, `volume_avg_length` 50, `rs_benchmark` SPY, `rs_smoothing_length` 52.
Volume and relative strength never gate the stage; they only feed
`weinstein_breakout_confirmed`.

### Engine choice: the sticky `sState` machine, not the stateless `sTS` quadrant read

The Pine source has two engines; the sticky `sState` state machine (not its own stateless
per-bar `sTS` quadrant read, `tsMode`'s actual default) was chosen from real evidence. Both were
run against 29 real tickers: full-history agreement was only 77.7% (~28,500 ticker-weeks), `sTS`
flipped 3-6x more often per year, and at the latest bar (what a header pill shows) the two
disagreed on 9/29 tickers. Qualitatively `sTS` flagged false "Top"/"Base" reclassifications on
ordinary single-week volatility inside an established trend, while `sState` requires clearing
a ±5% band AND genuine slope confirmation before it changes its mind — much closer to what
"stage analysis" means (a multi-month regime read, not a bar-by-bar indicator). The transition
rules themselves are tabulated in Part 1.

### Weekly resampling

Weekly bars are resampled from the SAME daily bars the nightly job reads from the shared cache
— no second fetch and no weekly interval on `SharedBarsCache` (its key holds only `1d`/`60m`).
Weeks must be labelled by their Monday to match a native weekly feed: a naive `resample("W-FRI")`
labels by the week's Friday, so the engine resamples `"W-FRI"` (which correctly bins Mon-Fri
trading days into one bucket) and shifts the index back 4 days, reproducing the Monday label
exactly (validated bit-identical across 15 real tickers against a native weekly reference).
`"W-MON"` is the wrong rule entirely (it bins Tue-through-Mon). See
`weinstein.py::resample_to_weekly`, also reused by the Chart tab's W_4Y range.

### Bootstrap and history depth

`sState` has memory from bar zero, so a run-in is needed before the bootstrap error washes out.
Measured at ~245 anchor points across 15 tickers (up to 64 years of history) on the original
engine: 1.6% of anchors still mismatched at 52 weeks, and 0/245 at 104 weeks. The replay
therefore gets ~5 years of dailies (`WEINSTEIN_LOOKBACK_DAYS` = 365 × 5 in
`data/trend_analysis_data.py`, the nightly job's fetch width), because an EMA/sticky machine needs
a long run-in and "since" dates otherwise depended on where the window started.
`WeinsteinParams.min_weeks_required` (`ma_length + slope_lookback + 5` = 40 at the defaults) is
the bare structural floor below which the engine returns a graceful `stage=None` / thin-history
result rather than an unreliable number; between that floor and a full run-in, a small residual
bootstrap-inaccuracy risk is an accepted, documented limitation.

### Settings

A singleton `WeinsteinSettings` table (`helpers/weinstein_config.py`, lazy-seeded, the
`LiquidityZoneSettings` pattern) holds the 8 parameters, editable via `GET/PUT
/api/config/weinstein` and Settings > Weinstein. They are read LIVE from the DB at compute time
(the nightly job once per run, the on-demand path per call), so a change applies on the next
recompute with no restart. It is not a `DataGroupSetting` (that is FMP on/off).
`TrendAnalysis.weinstein_params_json` records the params each row was computed with, and
`TrendAnalysisOut.weinstein_params` feeds the UI wording (no hard-coded "30-week"/"SMA"/"2x"; a
Screener card has no params, so its pill tooltip says "MA").

### Data model (on the existing `TrendAnalysis` table; nullable, no backfill)

`weinstein_stage` (`"base"|"advance"|"top"|"decline"`, a plain-str enum),
`weinstein_stage_since_date`, `weinstein_stage_since_is_lower_bound`, `weinstein_stage_changed`,
`weinstein_ma_slope_pct`, `weinstein_vs_ma_pct`, `weinstein_volume_ratio`,
`weinstein_mansfield_rs`, `weinstein_breakout_confirmed`, plus `weinstein_weeks_available`,
`weinstein_params_json` and the pending/ETA columns of Part 1.

- **Two flags that sound similar but are computed at different layers, on purpose.**
  `weinstein_breakout_confirmed` is a pure, single-run, week-over-week read off the freshly
  computed weekly stage series: a fresh transition INTO Advance in the latest week, volume ratio
  >= `breakout_volume_mult`, and RS unavailable or > 0 (the Pine source's own
  `na(mansfield)`-passes-through rule). It lives in the pure engine. `weinstein_stage_changed`
  means "today's freshly computed stage differs from what was stored **last night**" — an
  across-nightly-runs comparison that needs the previous row before overwriting it, so it is
  computed in `data/trend_analysis_data.py::_upsert`, not the engine. It is False (never an error)
  when there is no previous stored stage yet (a brand-new ticker's first compute).
- **`weinstein_stage_since_date` / `_is_lower_bound`**: walk the non-null (post-bootstrap)
  suffix of the weekly stage series backward from the latest week to the most recent week whose
  stage differs from the current one; the since-date is the week right after that (the most
  recent real transition of the replay). If the stage never differs anywhere in the available
  history, the since-date is the earliest available week and `_is_lower_bound=True` — rather than
  fabricating a precise transition date the fetch window can't see.
- **`weinstein_weeks_available`** is always a real count (unlike every other result field, which
  is `None` to mean "couldn't compute"), persisted so the two null states can be told apart:
  `NULL` alongside a `NULL` stage means never computed under this feature (a legacy,
  never-reprocessed row); a real (sub-floor) int means a compute ran and found too little history.
  `WeinsteinStageCard`'s null state shows one of two distinct messages accordingly
  (`lib/weinsteinStage.ts::weinsteinUnavailableReason`); the "Insufficient price history…"
  wording is reserved for the genuinely insufficient case.
- **RS benchmark**: SPY (`WEINSTEIN_BENCHMARK_TICKER`), not `^GSPC` — `^GSPC` was retired from
  this job 2026-09-23 when Massive, which had no Indices product, was removed. The benchmark rides
  along in the SAME nightly batch fetch as one more symbol (a benchmark is just another ticker
  string to the cache) but is deliberately never added to the per-ticker processing loop, so it
  never gets its own `TrendAnalysis` row or counts toward the job's `processed`/`failed` totals.
  A benchmark-fetch failure that run degrades every ticker's Mansfield RS/breakout fields to
  null/false (the same `na()`-passes-through convention) rather than counting as a per-ticker
  failure. The nightly job fetches whatever `rs_benchmark` names.
- **Cron**: the `pipeline/nightly_trend_calculation.py` run (12:05 AM) — no separate cron job.

### Surfacing

- **Ticker header**: `WeinsteinStagePill` in the chip row (the same flat-variant shape as
  `SpeculativeGrowthPill`/`MoatPill`; renders nothing when `weinstein_stage` is null, not a
  placeholder). **Technical tab**: `WeinsteinStageCard` (the `ChecklistCard` shell) renders alone
  at full row width at the top of the tab, above the BB+RSI/Warren grid and Liquidity Zones; the
  tab-level loading/error/empty states are unchanged.
  Colors: Stage 2/Advance = positive (green), Stage 4/Decline = negative (red), Stage 3/Top =
  `warn` (amber), Stage 1/Base = neutral. The card's disclaimer is deliberately NOT phrased as
  "Backtested: X%" — this lens has only been validated for state-machine correctness against its
  Pine source, not for predictive edge.
- **Chart tab W/4Y "Stage" toggle** (2026-09-26): on the weekly view only (hidden on D ranges,
  off by default, after SMA 200), draws the live-configured Weinstein MA (`WeinsteinSettings`
  type+length, labelled e.g. "EMA30", white) and colors each candle by its stage AT THAT WEEK
  (base #8FD99F / advance #1B9E3E / top #E8A020 / decline #E03A3A).
  `data/chart_data.py::_weinstein_overlay` calls the engine's own `compute_stage_series` over the
  FULL fetched weekly history (up to 10y, so the sticky machine is seeded long before the 4y
  visible window) and slices to the visible weeks — `ChartOut.weinstein_ma/_ma_label/_stages`,
  computed on-demand per weekly request with params read live. Weeks before the machine is
  seeded get no stage (default candle color). Caveat: the nightly job replays ~5y while the chart
  replays up to 10y; the sticky machine converges, so the current stage matches, but an old
  since-date could differ in rare cases.
- **Screener** (2026-09-07): `weinstein_stage` (+ `_since_date`/`_since_is_lower_bound`/
  `_ma_slope_pct`/`_vs_ma_pct`, needed for the pill's tooltip) are denormalized onto
  `TickerScore` inside `compute_ticker_score()` via a plain `session.get(TrendAnalysis, ticker)`
  read — not a new fetch or live recomputation. Filtering is 100% client-side
  (`lib/screenerFilters.ts::filterTickerScores`), like every other Screener multi-select: the
  Screener has never had server-side filtering for any criterion (`GET /api/screener` takes only
  `universe`), so a Weinstein query param would have been a new, inconsistent pattern rather than
  a mirror of `perf_5y_vs_spy_*`/`speculative_growth_qualifies`. It shows as a
  `WeinsteinStagePill` — the same pill, with the same full "Stage 2 · Advance" wording
  (`WEINSTEIN_STAGE_LABEL`), as the ticker header; there is no short "S1"–"S4" tier (removed
  2026-10-02) — and a "Weinstein
  stage" filter dropdown in the Screener sidebar's Technical section (label sentence-cased
  2026-09-30; the option labels "Stage 1 · Base" ... and the stored keys `base`/`advance`/`top`/
  `decline`/`pending` are unchanged)
  (`components/screener/TechnicalFilters.tsx`, which now holds other technical filters too). A
  "Weinstein: stage since" sort (label sentence-cased 2026-09-30; the option value `weinstein_stage_since` is unchanged) reads the persisted `TickerScore.weinstein_stage_since_date`
  (client-side, no new field).
- **Flip-ETA/pending** (`weinstein_pending.py`, Part 1) takes the same params, so its band, MA
  type and projection follow the live engine; `trend_5`/`trend_13` stay fixed-horizon scenario
  keys.

*History: the original 2026-09-06 engine was a fixed 30-week-SMA/±5%-band version with a 2y
run-in and a 30-week volume average; it was replaced outright (no toggle) by the configurable EMA
engine on 2026-09-26. The build-time measurements, the engine-swap recompute run and the
Screener relayout narrative are archived in
`docs/archive/claude-md-history-technical-signals.md`.*

## Part 1 — "pending confirmation" + ETA (shipped, `weinstein_pending.py`)

### The problem

The live weekly `sState` machine is deliberately sticky — it requires the moving-average slope
to genuinely turn, not just a price bounce, before it changes its mind. That's correct behavior,
but it means a ticker can sit in a stage that visibly disagrees with where price already is: the
motivating case was a name reading "Decline" for months while price sat >20% above its own
30-week MA, because the slope condition (MA needs to turn from falling to rising) hadn't
confirmed even though the price condition (clearing the +5% band) already had. Nothing about
this is a bug in the state machine — it's the sticky design working as intended — but the stage
label alone hides *which* half of the transition condition is still pending and how close it
might be.

This feature adds a purely additive read on top of the existing engine: flag when a ticker is
"pending" a stage-2/stage-4 transition (one condition met, one still open), and, only for those
flagged tickers, estimate how many more weeks the slope math would need under a few explicit,
clearly-labeled price assumptions — never a price prediction.

### Which (stage, direction) combinations are genuinely "pending"

Confirmed against all 8 of the state machine's transition rules rather than assumed. Six of the
eight are gated on **both** a slope condition and a band condition holding **in the same week**:

| From stage | To stage | Requires |
|---|---|---|
| Top | Advance | rising **and** above +5% band |
| Decline | Advance | rising **and** above +5% band |
| Base | Advance | rising **and** above +5% band |
| Advance | Decline | falling **and** below −5% band |
| Top | Decline | falling **and** below −5% band |
| Base | Decline | falling **and** below −5% band |

The other two (Advance→Top on "not rising" alone, Decline→Base on "not falling" alone) need no
band condition, so there's no "one half met" state for them.

A "pending Advance" flag is meaningful from any current stage other than Advance, and a "pending
Decline" flag is meaningful from any stage other than Decline — not only the Decline→Advance
direction a first pass might narrow to. At most one of the two can ever be true at once (the two
bands are mutually exclusive):

```python
above_band = valid & (close > ma * 1.05)
below_band = valid & (close < ma * 0.95)
rising     = valid & (slope > 0)
falling    = valid & (slope < 0)

pending_advance = valid & (stage != "advance") & above_band & (~rising)
pending_decline = valid & (stage != "decline") & below_band & (~falling)
```

Validated against the full tracked universe at the time: a meaningful fraction of tickers sit
pending at any given moment, and all five of the non-trivial combinations above (excluding
top→decline, which simply had no live example that day but shares the identical code path)
occurred in real data.

### ETA estimate

**The question being answered is narrow and must stay narrow in the UI: "if price holds near a
stated level, how many more weeks until the slope math itself would confirm?"** It is never a
forecast of what price will do.

**Method**: since `slope = (MA_today − MA_N_weeks_ago) / MA_N_weeks_ago`, and the older MA's
inputs are already fully known history, the projection walks forward week by week: extend the
real weekly-close series with a multi-year horizon of assumed future closes, re-run the stage
computation **completely unmodified** on the extended series, and find the first future week
where slope *and* the band condition are true **in the same week** — not slope alone.

That "in the same week" requirement caught one real bug during development: an earlier version
flagged confirmation the moment slope alone crossed zero, which for a ticker whose band-clearance
is fading as an old price spike rolls out of the lookback window reports a "confirmation" date at
which the real state machine would actually land in Top or Base, not Advance/Decline, because the
band condition had already lapsed by then. A `band_lapsed_before_confirmation` flag exists
specifically to surface this.

**Three scenarios, not just flat:**

| Scenario | Meaning |
|---|---|
| `flat` | Price holds at today's close — the literal ask, and the one that must always be shown, explicitly labeled as an assumption, not a prediction. |
| `trend_5` | Price compounds forward at the trailing 5-week average weekly return — the most reactive/volatile read. |
| `trend_13` | Price compounds forward at the trailing 13-week (one-quarter) average weekly return — a steadier momentum read. |

These three were picked over a mean-reversion or linear-extrapolation scenario for a concrete
reason found during validation: the real risk isn't usually "price does something exotic," it's
"an old move rolls out of the moving-average window while price just sits still" — which `flat`
already exposes on its own once `band_lapsed_before_confirmation` is checked. Adding two momentum
scenarios on top brackets the flat case usefully without pretending to model reversal risk
explicitly.

**Supplementary diagnostic, not a fourth scenario**: how far past the band threshold price
closed today, versus the standard deviation of the last 13 weekly returns ("band cushion"). A
thin cushion means one ordinary-sized move the other way could un-clear the band before slope
ever gets a chance to confirm. This is a heuristic, validated against a small hand-checked
sample, not a rigorously back-tested predictor — flagged as such wherever it's shown.

### Validation findings, worth remembering precisely

- **The band-cushion diagnostic distinguished real false alarms from a real, ongoing episode in
  the validation sample** — two historical "pending" snapshots that had a thin cushion (<2
  percentage points, well under the typical weekly move) both resolved false within a single
  week, against 4-7-week flat-scenario ETAs; a later, comfortable-cushion (>15pp) snapshot of the
  same ticker stayed pending and converged on a consistent target date from three separate
  vantage points. This is one ticker's history, reported as a caveat/diagnostic, not a validated
  predictor at scale.
- **A "chase never converges" edge case is real, not hypothetical, and generalizes across every
  non-trivial transition pair.** When a large historical price move is still inside the
  moving-average lookback window, a scenario that holds price too close to flat can produce
  `horizon_exceeded` + `band_lapsed_before_confirmation` — the series converges to a fixed
  steady-state offset between close and MA once real history has fully rolled out of the
  lookback window, at which point slope locks onto the scenario's own constant growth rate and
  permanently keeps its sign. Confirmed via a full-pending-universe validation pass: this fires
  for a small handful of tickers, on different scenarios (not always `flat`) and on both
  transition directions (Advance→Decline and Decline→Advance) — the underlying check is
  scenario-agnostic, so this is a structural property of the projection, not a `flat`-specific
  quirk. Confirmed **transient**: a `horizon_exceeded` snapshot resolved to a normal, short ETA
  once real price data advanced even one more week (the exact "flat while an old spike ages out"
  condition that caused it no longer held).
- **Band cushion and ETA can point in different directions for the same ticker, and both should
  be shown, not reconciled into one.** A handful of tickers combine a razor-thin cushion with a
  long flat-scenario ETA — not a bug: cushion measures price-level fragility, ETA measures slope
  inertia (how long a currently strongly-trending MA slope takes to fully reverse under a frozen
  price), and a ticker whose price just barely cleared the band while its trailing slope is still
  running hard the *other* way genuinely has both properties at once.
- A full-pending-universe validation run (round 2, same day as the initial build) found the
  large majority of pending tickers produced a clean, fully self-consistent 3-scenario estimate,
  with the remainder all correctly caught by the two flags above rather than silently wrong.

### Where it lives / data model

A new pure-function module, `analysis/trend_structure/weinstein_pending.py`, mirroring the base
engine's own no-DB/no-HTTP, dataclass-output style and **importing the stage computation
unmodified** rather than duplicating or touching its transition loop — this keeps the
reviewed/tested state-machine logic completely untouched while the new feature is purely a
consumer of its output, run twice more (once per scenario, extended into the future) on top of
the same real data.

Nullable, additive columns on `TrendAnalysis` (same `_add_missing_columns`-has-no-backfill
convention as every other Weinstein/technical field), computed once per ticker per nightly run
from data the job already has:

- `weinstein_pending_direction` (`"advance" | "decline" | null`)
- `weinstein_pending_since_date`, `weinstein_pending_since_is_lower_bound` (mirrors
  `weinstein_stage_since_date`/`_is_lower_bound`'s own shape)
- `weinstein_pending_band_cushion_pct`, `weinstein_pending_typical_weekly_move_pct` (the
  fragility diagnostic)
- `weinstein_pending_eta_json` — a single JSON-blob column holding all three scenarios, since the
  whole object is always read/written together and never queried field-by-field.

All null when not currently pending. `TrendAnalysisOut` gains the same fields nested under an
optional `pending` object so a non-pending ticker's payload is unchanged.

**Deliberately out of scope for this round**: Watchlist/Screener surfacing of the pending state
(today only the Screener card's Weinstein pill shows the stage itself; the Watchlist has had no
Weinstein column since the Watchlist UI columns were removed on 2026-09-06); a symmetric "how many weeks
until an *existing* stage would be at risk of reversing" read; backtesting the band-cushion
diagnostic beyond the single-ticker illustration above; a dedicated mean-reversion/downside
scenario.

## Part 2 — daily-timeframe variant (investigated, **not built**)

**Status: investigation only, no production code changed.** This remains an open proposal, not
a stale one — kept here as the live reference if the daily variant is ever picked back up.

### Question

Fathom's live Weinstein Stage Analysis runs the sticky state machine on **weekly**-resampled
bars. Does running the *identical* sticky machine directly on **daily** bars react to real
regime changes meaningfully faster, without falling into the whipsaw trap a prior investigation
found in a *stateless* daily read?

### Findings

The daily variant's transition logic matches the weekly production code exactly (all 8 rules
checked one-by-one). Running it unscaled (same window lengths, just on daily bars instead of
weekly) against the full tracked universe:

- **The daily engine transitions ~5.4x more often** than weekly (mean 8.09 vs. 1.51
  transitions/ticker/year).
- **Whipsaw is real but dampened, not eliminated**: daily's median regime length is less than
  half of weekly's, and roughly 1 in 4 daily regimes is gone again within two trading weeks (vs.
  1 in 10 for weekly) — the sticky machine clearly helps relative to a stateless per-bar read (it
  isn't flipping every single day), but it does not prevent the "flip-flopped on noise" pattern
  the investigation set out to test.
- **The lag reduction is real and material**: of transitions that eventually got confirmed by
  weekly, the daily variant reached the same call a median of ~16 trading days (~3.2 weeks)
  earlier — and, concretely, on the day of the investigation, the large majority of live
  "obviously lagging weekly" cases in both directions had already been caught by the daily
  variant weeks earlier.
- **The same 6 whipsaw-check tickers used in the earlier stateless-read investigation still show
  materially higher whipsaw on the sticky daily variant than on weekly**, and several disagree
  with weekly's *current* stage outright — a clean illustration of a real early call sitting
  right next to short-lived false ones in the same multi-month window for one representative
  ticker.

### Recommendation

**Not a replacement for the weekly engine — worth shipping only as a second, clearly-labeled
column, and not worth building further right now.** The lag reduction is genuine and the whipsaw
cost is also genuine; given that combination, the investigation recommends against silently
feeding a daily read into any blended/derived signal (e.g. the Screener's `weinstein_stage`
surfacing) without a very visible "early/noisy read" label distinguishing it from the weekly
"Stage" reading. A second UI column sitting purely alongside the current weekly one, with no
scoring/blend impact, is the shape recommended if this ever gets built — a follow-up product
decision, not something the investigation itself greenlights.
