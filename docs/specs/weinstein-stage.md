# Weinstein Stage Analysis — pending confirmation/ETA, and the daily-timeframe question

This document covers two rounds of design work layered on top of the shipped Weinstein Stage
engine — it does **not** re-document the base engine (the sticky `sState` state machine, its
weekly resample, the 2026-09-26 configurable-EMA "Engine swap," Screener/Chart surfacing, or the
Flip-ETA card's own UI). That base mechanism is fully documented in `CLAUDE.md`'s "Weinstein
Stage Analysis" and "Engine swap" sections and hasn't yet been extracted into `docs/specs/` (see
that file's own follow-up list). Read that first if you need the state-machine transition rules
themselves — this document assumes them.

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
(the existing Weinstein columns there show only the stage itself); a symmetric "how many weeks
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
