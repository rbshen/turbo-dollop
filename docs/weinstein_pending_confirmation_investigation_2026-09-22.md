# Weinstein Stage Analysis: "pending confirmation" + ETA — design proposal (2026-09-22)

**Status: investigation + design proposal only. Nothing wired into production.**
`analysis/trend_structure/weinstein.py`'s `sState` transition logic, `TrendAnalysis`'s schema,
`pipeline/nightly_trend_calculation.py`, and the frontend are all untouched. The only artifacts
from this round are this document and `docs/weinstein_pending_confirmation_prototype.py`
(committed alongside it — see that script's own docstring for why it departs from the
`backend/scripts/` untracked convention this round, on explicit instruction).

## The problem

Weinstein Stage Analysis's live weekly `sState` machine is deliberately sticky — it requires a
30-week MA slope to genuinely turn, not just a price bounce, before it changes its mind (see
CLAUDE.md's "Weinstein Stage Analysis" section for why that design was chosen over the stateless
per-bar alternative). That's correct behavior, but it means a ticker can sit in a stage that
visibly disagrees with where price already is — the motivating case: **META has read "Decline"
since 2026-01-05, while price is currently 21.2% *above* its own 30-week MA**, because the slope
condition (MA needs to turn from falling to rising) hasn't confirmed yet even though the price
condition (clearing the +5% band) already has. Nothing about this is a bug in the state machine —
it's the sticky design working as intended — but the stage label alone hides *which* half of the
transition condition is still pending and how close it might be.

This round adds a purely additive read on top of the existing engine: flag when a ticker is
"pending" a stage-2/stage-4 transition (one condition met, one still open), and, only for those
flagged tickers, estimate how many more weeks the slope math would need under a few explicit,
clearly-labeled price assumptions — never a price prediction.

## Part A — which (stage, direction) combinations are genuinely "pending"

Confirmed against all 8 of `compute_stage_series`'s transition rules (`weinstein.py` lines
114–131) rather than assumed. Six of the eight are gated on **both** a slope condition and a
band condition holding **in the same week**:

| From stage | To stage | Requires |
|---|---|---|
| Top (3) | Advance (2) | rising **and** above +5% band |
| Decline (4) | Advance (2) | rising **and** above +5% band |
| Base (1) | Advance (2) | rising **and** above +5% band |
| Advance (2) | Decline (4) | falling **and** below −5% band |
| Top (3) | Decline (4) | falling **and** below −5% band |
| Base (1) | Decline (4) | falling **and** below −5% band |

The other two (Advance→Top on "not rising" alone, Decline→Base on "not falling" alone) need no
band condition, so there's no "one half met" state for them — confirming this mattered, since the
task's own framing led with Decline→Advance and it would have been easy to under-scope to just
that one direction.

**Result: a "pending Advance" flag is meaningful from any current stage other than Advance
(Base, Top, or Decline), and a "pending Decline" flag is meaningful from any stage other than
Decline (Base, Top, or Advance)** — not only the Decline→Advance direction. At most one of the
two can ever be true at once (the two bands are mutually exclusive), so a ticker has at most one
pending flag active at any time.

```python
above_band = valid & (close > ma * 1.05)
below_band = valid & (close < ma * 0.95)
rising     = valid & (slope > 0)
falling    = valid & (slope < 0)

pending_advance = valid & (stage != "advance") & above_band & (~rising)
pending_decline = valid & (stage != "decline") & below_band & (~falling)
```

Validated live against the full tracked universe (579 tickers, `docs/
weinstein_pending_confirmation_prototype.py`'s `full_universe_scan`): as of this investigation,
**38 tickers are currently pending**, split `{('advance','decline'): 24, ('decline','advance'): 8,
('top','advance'): 3, ('base','decline'): 2, ('base','advance'): 1}` — all five of the non-trivial
combinations above actually occur in real data (the sixth, top→decline, doesn't happen to have a
live example today but is exercised by the same code path).

## Part B — ETA estimate

**The question being answered is narrow and must stay narrow in the UI: "if price holds near a
stated level, how many more weeks until the slope math itself would confirm?"** It is never a
forecast of what price will do.

### Method

Since `slope = (MA_today - MA_5wks_ago) / MA_5wks_ago`, and `MA_5wks_ago`'s own inputs are already
fully known history, the projection walks forward week by week: extend the real weekly-close
series with `horizon_weeks` (104, matching `weinstein.py`'s own "2y" bootstrap-convergence
convention) of assumed future closes, re-run `compute_stage_series` **completely unmodified** on
the extended series, and find the first future week where slope *and* the band condition are true
**in the same week** — not slope alone.

That "in the same week" requirement is the one real bug this prototype caught and fixed while
building it (see the script's own comment on `project_confirmation_eta`): an earlier version
flagged confirmation the moment slope alone crossed zero, which for a ticker whose band-clearance
is fading as an old price spike rolls out of the 30-week window reports a "confirmation" date at
which the real state machine would actually land in Top or Base, not Advance/Decline, because the
band condition had already lapsed by then. The prototype's `band_lapsed_before_confirmation` flag
exists specifically to surface this.

### Three scenarios, not just flat

| Scenario | Meaning |
|---|---|
| `flat` | Price holds at today's close — the literal ask, and the one that must always be shown, explicitly labeled as an assumption, not a prediction. |
| `trend_5` | Price compounds forward at the trailing 5-week average weekly return — mirrors `SLOPE_LOOKBACK` itself, the most reactive/volatile read. |
| `trend_13` | Price compounds forward at the trailing 13-week (one-quarter) average weekly return — a steadier momentum read. |

These three were picked over a mean-reversion or linear-extrapolation scenario for a concrete
reason found during validation (see LYB below): the real risk isn't usually "price does something
exotic," it's "an old move rolls out of the 30-week window while price just sits still" — which
`flat` already exposes on its own once `band_lapsed_before_confirmation` is checked. Adding two
momentum scenarios on top brackets the flat case usefully without pretending to model reversal
risk explicitly.

### Supplementary diagnostic: band cushion vs. typical weekly move

Not a fourth scenario — a snapshot risk read shown alongside the ETA: how far past the band
threshold price closed today, versus the standard deviation of the last 13 weekly returns. A thin
cushion means one ordinary-sized move the other way could un-clear the band before slope ever
gets a chance to confirm — this is exactly the mechanism behind both of META's real false alarms
(see below). It's a heuristic, single-ticker-validated, not a rigorously back-tested predictor —
flagged as such in the caveats.

## Validation against META's real history

### The current live case

As of the last cached weekly bar (2026-09-21): stage `decline`, price **+21.2%** above the MA,
slope still slightly negative (**−0.39%/wk**, but rising fast from −1.48%/wk two weeks earlier) →
`pending_advance = True`, pending since **2026-09-07**. Band cushion: **+15.5pp** past the
threshold vs. a typical recent weekly move of ~7.1pp — comfortable, not fragile.

All three scenarios agree: **1 week away (week of 2026-09-28)** — matching the back-of-envelope
estimate from the prior investigation.

### The four named historical dates — checked, not assumed

| As of | Pending? | Band cushion | Flat ETA said | What actually happened |
|---|---|---:|---|---|
| 2026-04-13 | Yes | +0.6pp (thin) | 7wk away (~6/01) | **Resolved false the very next week** — price fell back under the band by 4/20 |
| 2026-07-06 | Yes | +1.8pp (thin) | 4wk away (~8/03) | **Resolved false the very next week** — price fell back under the band by 7/13 |
| 2026-09-07 | Yes | +1.5pp (thin) | 4wk away (~10/05) | **Stayed pending** — still pending 9/14 and 9/21, converging on the same ~9/28 target from every vantage point |
| 2026-09-14 | Yes | +4.2pp | 2wk away (~9/28) | **Stayed pending**, now the live case above |

**All four are correctly recognized as reaching the pending state** — the flag doesn't miss any
of them. But the honest answer to "does the ETA correctly identify the false alarms" is **no, not
on its own**: 4/13 and 7/6 each collapsed in a single week, far faster than the flat-scenario ETA
(4–7 weeks) suggested, while 9/7 and 9/14 turned out to be two snapshots of the *same* ongoing,
real episode that has stayed remarkably self-consistent (predicting ~9/28 from three different
vantage points, now down to 1 week away). **The band-cushion diagnostic does distinguish these
correctly in this sample** — both false alarms had a thin cushion (<2pp, well under the typical
weekly move), while the current live episode's cushion has grown to a comfortable 15.5pp — but
this is one ticker's history, not a validated predictor, and is reported as a caveat/diagnostic
for exactly that reason, not as a third gate on the flag itself.

### LYB — the "rolling off a spike" caveat, both real and transient

LYB ran up to ~$80 in March 2026; that move was still inside the trailing 30-week window as of
this investigation. At the snapshot where LYB's cache last updated 2026-09-14 (close $61.93,
stage Advance, price −6.1% below MA, slope still positive at +2.64%/wk → `pending_decline`), the
**flat** scenario reported **"does not confirm within 104 weeks"** — because under a frozen price,
the MA converges toward the flat price at roughly the same pace the band gap needs to close,
perpetually chasing zero without ever getting there, while the **trend_5** scenario (a mild
continued decline) confirmed in 3 weeks. This is precisely the "ticker right at the edge of
rolling off a big historical spike" case the investigation asked to check for, and it's real, not
constructed — no other ticker in the current 38-pending universe hit `horizon_exceeded`, so this
required the specific combination LYB happened to be in.

**It's also transient, and re-running the script a week later demonstrated why that matters as
much as the mechanism itself**: by the time this document was finalized, LYB's cache had
advanced one more week (close $60.24, continuing to fall rather than sitting flat) and the flat
scenario now confirms in 2 weeks with no band lapse — because price resuming its decline removed
the exact "flat while an old spike ages out" condition that caused the contradiction. The
takeaway for the caveat text isn't "distrust the flat case" so much as **"a flat-scenario ETA (or
non-answer) on a ticker with a large historical spike still inside the 30-week window is only a
snapshot — it can flip from 'never' to 'weeks' on a single week's real data, and that's expected
behavior, not noise to smooth over."**

### Full-universe scan summary

579 tickers with cached weekly-eligible history; 38 currently pending. Flat-scenario ETA:
median 3 weeks, IQR 1–8 weeks, max 13 weeks. 5 of 38 (13%) show the three scenarios disagreeing
by 3+ weeks — real, not manufactured precision (e.g. MGM: flat 10wk vs trend_5 4wk vs trend_13
5wk). Runtime: the full scan (both `is_pending` checks plus, for the ~7% that are pending, all
three ETA projections) ran in **~12 seconds** for the whole universe — negligible against the
Weinstein/trend nightly job's already-quoted ~45s total, since the ETA projection only ever runs
for the small pending subset.

## Design proposal (for a later, separately-approved round)

### Where it lives

A new pure-function module, `analysis/trend_structure/weinstein_pending.py`, mirroring
`weinstein.py`'s own style (no DB/HTTP, dataclass output) and **importing `compute_stage_series`
unmodified** rather than duplicating or touching its transition loop — the same "reuse, don't
touch" approach the prototype already takes. This keeps the reviewed/tested sState logic
completely untouched while the new feature is purely a consumer of its output, run twice more
(once per scenario, extended into the future) on top of the same real data.

### Data model

Nullable, additive columns on `TrendAnalysis` (same `_add_missing_columns`-has-no-backfill
convention as every other Weinstein/technical field), computed once per ticker per nightly run
from data the job already has — no new fetch:

- `weinstein_pending_direction` (`"advance" | "decline" | null`)
- `weinstein_pending_since_date`, `weinstein_pending_since_is_lower_bound` (mirrors
  `weinstein_stage_since_date`/`_is_lower_bound`'s own shape)
- `weinstein_pending_band_cushion_pct`, `weinstein_pending_typical_weekly_move_pct` (the
  fragility diagnostic)
- `weinstein_pending_eta_json` — a single JSON-blob column (this codebase's established
  convention for a small structured field, e.g. `last_confirmed_swing_json`,
  `broken_support_json`) holding all three scenarios: `{"flat": {"weeks_away": 1,
  "projected_date": "2026-09-28", "band_lapsed_before_confirmation": false, "growth_rate_pct":
  0.0}, "trend_5": {...}, "trend_13": {...}}` — one column rather than 12, since the whole object
  is always read/written together and never queried field-by-field.

All null when not currently pending — cheap to check (`weinstein_pending_direction IS NOT NULL`)
without touching the JSON blob.

### API

`TrendAnalysisOut` (the standalone `GET /api/tickers/{ticker}/trend-analysis` response) gains the
same fields, nested under an optional `pending` object so a non-pending ticker's payload is
unchanged. `WatchlistRowOut`/Screener are explicitly **out of scope** for this feature — the
existing Watchlist/Screener Weinstein columns already show only the stage itself (see CLAUDE.md's
"Watchlist UI columns removed" and "Screener surfacing" sections); adding a pending-ETA read there
would be a separate follow-up decision, not assumed here.

### UI sketch

**1. Ticker header pill (`WeinsteinStagePill`)** — no visual change to the pill itself (still
just the stage label + color), but when pending, its existing tooltip gains a line:

```
Decline · since 2026-01-05
⚠ Pending Advance — price is 21.2% above its 30-week MA (band clears at +5%),
  but the MA slope hasn't turned up yet (-0.4%/wk). ~1 week away if price holds
  near $741.24 (not a prediction).
```

**2. Technical tab — new sub-block inside the existing `WeinsteinStageCard`**, appearing only
when `pending` is non-null, styled like `TrendContinuationCard`'s existing amber "pullback
pending" state (the `warn` token):

```
┌─ Pending Stage 2 (Advance) ───────────────────────────────────────────┐
│ Price cleared the +5% band on 2026-09-07 (3 weeks ago) but the        │
│ 30-week MA slope hasn't turned up yet.                                │
│                                                                        │
│   If price holds near $741.24 (flat):        ~1 week  (wk of 9/28)    │
│   If price keeps its recent 5-week pace:      ~1 week  (wk of 9/28)   │
│   If price keeps its recent 13-week pace:     ~1 week  (wk of 9/28)   │
│                                                                        │
│ Band cushion: 15.5pp past threshold (typical weekly move: ~7.1pp)     │
│                                                                        │
│ These are not price forecasts — they show how long the slope math     │
│ would need under each stated assumption. A pullback under the band    │
│ before then cancels the countdown rather than pausing it (this has    │
│ happened twice already this year, on 4/13 and 7/6).                   │
└────────────────────────────────────────────────────────────────────────┘
```

For a `horizon_exceeded`/spike-rolloff case (LYB-shape), the flat row instead reads e.g. "Flat
price: doesn't confirm within 2 years — an older price move is still aging out of the 30-week
window" so the contradiction is explained, not just displayed as a scary "never."

### Caveats to carry into the next round, verbatim in the UI text where relevant

1. **The ETA is not a prediction** — it says how long the *math* needs under a *stated*
   assumption, nothing about whether price will behave that way.
2. **A pullback below the band cancels the pending state, it doesn't pause the countdown** —
   demonstrated twice in META's own recent history (4/13, 7/6), both resolving in a single week
   against 4–7 week ETAs. The band-cushion diagnostic is a useful (if unvalidated-at-scale) risk
   read for this specific failure mode.
3. **A ticker whose band clearance depends on a large, aging price move still inside the 30-week
   window can show a contradictory or unstable flat-price ETA** (LYB) — worth a distinct message
   rather than a bare "2 years+", and worth noting that this can flip week to week on ordinary new
   data, not just on a real change in the setup.
4. **The current week's bar is still forming.** Since the engine always treats the latest
   (possibly partial) week as "today," `weeks_away=1` means "the next full weekly close," not
   exactly 7 calendar days — a nuance already inherent to the underlying weekly engine, not new
   here, but worth keeping in mind if this is ever phrased as a calendar date without qualification.
5. **The `trend_5`/`trend_13` scenarios are not risk-symmetric** — both only ever assume the
   *existing* direction continues; genuine reversal risk is only visible via the band-cushion
   diagnostic and the flat scenario's own `band_lapsed_before_confirmation` flag, not a dedicated
   downside scenario. Worth a follow-up decision, not built here.

### Explicitly deferred, not part of this proposal

- Extending this to a symmetric "how many weeks until an *existing* stage would be at risk of
  reversing" read (i.e., for a ticker *already* in Advance/Decline, not just pending) — a
  different, larger question the task didn't ask for.
- Any Screener/Watchlist surfacing.
- Backtesting the band-cushion diagnostic beyond this single-ticker illustration.
- A dedicated mean-reversion/downside scenario.

## Reproducing this

`cd backend && uv run python ../docs/weinstein_pending_confirmation_prototype.py` — read-only
against `fathom.db`, zero writes, zero live Yahoo Finance calls. Safe to rerun any time; expect
the exact numbers above (especially LYB's) to drift as the underlying cache is refreshed by the
live nightly jobs — that drift is itself part of what this investigation found, not a
reproducibility failure.
