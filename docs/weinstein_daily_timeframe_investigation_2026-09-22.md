# Weinstein Stage Analysis: daily-timeframe variant — investigation (2026-09-22)

**Status: investigation only. No production code changed.** `analysis/trend_structure/weinstein.py`,
`TrendAnalysis`, and `pipeline/nightly_trend_calculation.py` are untouched. This document and the
comparison script that produced its numbers (`backend/scripts/weinstein_daily_variant_investigation.py`,
untracked per this codebase's `backend/scripts/` convention) are the only artifacts.

## Question

Fathom's live Weinstein Stage Analysis runs the sticky `sState` state machine (Base/Advance/
Top/Decline) on **weekly**-resampled bars: 30-week MA, 5-week slope lookback, ±5% band, 52-week
Mansfield RS. Does running the *identical* sticky machine directly on **daily** bars (30-day MA,
5-day slope, same ±5% band — per the reference Pine script's "Lock to weekly OFF" mode) react to
real regime changes meaningfully faster, without falling into the whipsaw trap a prior
investigation found in a *stateless* daily read (misclassifying META/COST/T/UPS/QCOM/GOOGL on
ordinary noise)?

## Step 1 — transition logic confirmed to match

All 8 `sState` transition rules in `weinstein.py::compute_stage_series` (lines 114-131) were
checked one-by-one against the reference table given for this investigation. **No discrepancy** —
the code already matches exactly (Advance→Decline on falling+below-band, Advance→Top on
slope-not-rising, Top→Advance on rising+above-band, Top→Decline on falling+below-band,
Decline→Advance on rising+above-band, Decline→Base on slope-not-falling, Base→Decline on
falling+below-band, Base→Advance on rising+above-band).

## Method

- **Daily variant**: a parameterized re-implementation of the same 25-line state-machine loop
  (production hardcodes `MA_LEN`/`SLOPE_LOOKBACK`/`WITHIN_RANGE_PCT` as module constants, so it
  can't be called with different windows without touching the module — duplicating the loop into
  the scratch script avoids any risk to production code). `MA_LEN=30` and `SLOPE_LOOKBACK=5` are
  used **unscaled** — the task's own spec — computed directly on daily closes, no resampling.
  `WITHIN_RANGE_PCT=5.0` reused unchanged. Validated byte-identical to the production function
  when called with the weekly constants on the same input (`verify_parity()` in the script).
- **RS lookback scaling** (the one open design question): weekly's `RS_SMOOTHING_LEN=52` weeks is
  the standard "52-week Mansfield RS" convention (~1 calendar year). Checked empirically rather
  than assumed — real cached daily bars for META/AAPL/JPM average **250.8 trading days per full
  calendar year** (2022-2025), confirming 252 (the standard trading-year figure) is the right
  daily-equivalent, not 260 (=52×5, which ignores holidays). **Not leaned on for any conclusion
  below** — `^GSPC` only has ~2y cached locally, too thin a benchmark history to trust RS/
  breakout-confirmation backtesting, so this investigation focuses entirely on the stage
  state-machine itself (lag and whipsaw), which needs no benchmark. `VOLUME_AVG_LEN` (only feeds
  `breakout_confirmed`, not the stage machine) got the same unscaled treatment as `MA_LEN` — a
  minor implementation choice, not a researched one.
- **Data**: read directly and read-only from `SharedBarsCache` in `backend/fathom.db` (raw SQL,
  `mode=ro`, zero writes, zero new Yahoo Finance calls — this is the exact data the production
  job already fetched). **Sanity-checked** the weekly path (production functions, unmodified,
  run against this loaded data) against the live `TrendAnalysis.weinstein_stage`/`_vs_ma_pct`
  columns for 5 tickers — matched exactly (e.g. META: computed 21.25% vs. live 21.248%).
- **Universe**: the task suggested a ~50-100 ticker sample; since this is a pure local read + pandas
  compute with zero network cost, I ran the **full tracked universe** instead (579 tickers with
  cached daily bars; 574 cleared the minimum-history floor — the 5 excluded, AVB/EA/EQR/FDXF/HONA,
  have only 1-80 cached daily bars, a pre-existing data-completeness gap unrelated to this
  investigation).
- **Lag**: for each ticker, extracted every stage transition on both engines over the ticker's
  full cached history, then greedily nearest-matched weekly transitions to daily transitions of
  the *same type* (e.g. decline→advance) within a 400-calendar-day window, one-to-one, and
  measured the lag in trading days off the ticker's own daily bar index.
- **Whipsaw**: (a) total transitions/ticker/year; (b) fraction of *completed* regimes (excluding
  the still-open current one) lasting under 10 / under 20 trading days — a matching-free, direct
  "flip-flopped on noise" measure; (c) the same read applied to the 6 named check tickers.
- **One real bug caught mid-investigation**: an early version of the transition extractor checked
  `stage is None` to skip the pre-bootstrap prefix — but pandas silently coerces that `None` to
  float `nan` once wrapped in a DataFrame column, and `nan != nan` is always `True` in Python, so
  every bootstrap week was miscounted as a spurious transition (a plainly-implausible ~17
  weekly transitions/ticker/year before the fix, using `pd.isna` — see the script's own comment
  on this exact trap).

## Results

### 1. Overall transition frequency (574 tickers, full cached history)

| | Weekly (production) | Daily (variant) |
|---|---:|---:|
| Transitions / ticker / year (mean) | **1.51** | **8.09** |
| Transitions / ticker / year (median) | 1.50 | 8.02 |
| Total transitions (all tickers, all history) | 2,209 | 11,718 |

The daily engine transitions **~5.4x more often** than weekly, even with the identical sticky
machine and band. This alone is the headline trade-off: reacting faster necessarily means
reacting more often.

### 2. Whipsaw — regime-duration read (matching-free, the most robust metric here)

| | Weekly | Daily |
|---|---:|---:|
| Completed regimes measured | 2,209 | 11,718 |
| Median regime length (trading days) | **57** | **24** |
| Mean fraction of regimes lasting <10 trading days | **9.7%** | **26.9%** |
| Mean fraction of regimes lasting <20 trading days | **21.1%** | **43.3%** |

The daily engine's median regime lasts less than half as long as weekly's, and roughly 1 in 4
daily regimes (vs. 1 in 10 weekly) is gone again within two trading weeks. The sticky machine
does *help* relative to a stateless per-bar read (it isn't flipping every single day — median
24-trading-day daily regimes, not 1-2-day ones) — but it does **not** eliminate the
whipsaw problem the task asked about, just dampen it.

### 3. Matched-transition lag ("how much faster, in trading days")

1,859 weekly transitions were matched to a same-type daily transition within the 400-day window
(84% of all 2,209 weekly transitions found a match; the rest either predate the daily engine's own
usable history or genuinely have no nearby daily counterpart of that type). Positive lag = daily
reached the stage first.

| Transition type | n matched | Median lag (trading days) | Mean lag |
|---|---:|---:|---:|
| decline → advance | 379 | **+17** | +18.6 |
| advance → decline | 337 | **+20** | +20.1 |
| advance → top | 281 | +10 | +14.4 |
| decline → base | 259 | +13 | +19.8 |
| base → advance | 177 | +20 | +27.0 |
| top → advance | 164 | −4 | −3.7 |
| top → decline | 145 | +38 | +29.7 |
| base → decline | 117 | +6 | +10.9 |
| **All matched pairs** | **1,859** | **+16** | +17.6 |

66% of matched pairs show daily leading (positive lag); 33% show daily actually lagging weekly
for that specific instance (negative); ~1% tie in the same week. So *on average*, when a daily
call turns out to be confirmed by weekly, it arrives about **16 trading days (~3.2 weeks) earlier**
— genuine, material for both Decline→Advance and Advance→Decline (the two directions the task
specifically asked about), at +17 and +20 trading days respectively.

*(Caveat, tested for robustness: the count of daily transitions that find **no** weekly match at
all within 400 days is large — ~46% of all daily transitions — but this figure is highly sensitive
to the matching window: widening it to 1,200 days drops that to ~11%, and an unlimited window
drops it to 0% (at which point the greedy matching becomes meaningless — with only 8 possible
transition types recurring over 5 years, everything eventually pairs with something, whether or
not the pairing is causally related). I'm not treating "unmatched daily transitions" as a clean
whipsaw number for this reason and lean on the regime-duration metric above instead, which needs
no window choice at all.)*

### 4. The 10 live "Decline, price >5% above MA" cases (today)

8 of 9 tickers with cached data (SNAP has no cached daily bars locally — a pre-existing gap, not
introduced here) have **already flipped off Decline on the daily engine**, a median of **32.5
trading days (~6.5 weeks) ago** — while every one of them is still reading "Decline" on the live
weekly engine today. This is the concrete, present-tense version of the lag story:

| Ticker | Weekly vs-MA | Daily current stage | Daily vs-MA | Trading days since daily's own flip |
|---|---:|---|---:|---:|
| ZS | +30.1% | advance | +9.9% | 45 |
| META | +21.2% | advance | +22.2% | 8 |
| MSTR | +18.6% | advance | +27.6% | 20 |
| DHR | +10.2% | advance | +1.4% | 70 |
| MTD | +9.6% | **decline (unchanged)** | +0.8% | — |
| CTSH | +8.6% | advance | −1.8% | 34 |
| EL | +8.3% | advance | −3.1% | 31 |
| MDT | +8.0% | advance | +0.4% | 54 |
| CDE | +6.0% | advance | −2.0% | 28 |

(MTD is the one holdout — its daily vs-MA is only +0.75%, essentially at the boundary, so neither
engine has triggered a real turn there; not a lag case.)

### 5. The 38 live "Advance, price >5% below MA" cases (today)

34 of 38 have **already been demoted off Advance on the daily engine** (mostly to Decline, one to
Top), a median of **18.5 trading days (~3.7 weeks) ago** — while all 38 are still "Advance" on the
live weekly engine today (that's how they were selected). Full list computed; worst cases: CASY
(weekly +/-23.0% below MA, daily already at −21.0% and in Decline for 15 trading days), AAOI
(weekly −19.4%, daily −9.3%, flipped only 2 trading days ago), ON (weekly −18.9%, daily −6.6%,
Decline for 57 trading days). 4 holdouts (HAL, 0883.HK, 0857.HK, LYB) — the daily engine hasn't
demoted them either; their daily vs-MA readings (−4.3% to −4.3%) sit closer to the ±5% band than
the others, consistent with these being genuinely more borderline rather than lag cases.

### 6. The 6 named whipsaw-check tickers (META, COST, T, UPS, QCOM, GOOGL)

| Ticker | Weekly trans/yr | Daily trans/yr | Weekly frac <10td | Daily frac <10td | Current: weekly / daily |
|---|---:|---:|---:|---:|---|
| META | 1.00 | 9.40 | 20.0% | 36.2% | decline / advance |
| COST | 2.60 | 7.61 | 15.4% | 26.3% | decline / base |
| T | 2.51 | 6.01 | 0.0% | 25.0% | base / advance |
| UPS | 1.50 | 9.02 | 0.0% | 38.9% | decline / decline (agree) |
| QCOM | 4.01 | 8.52 | 25.0% | 29.4% | advance / advance (agree) |
| GOOGL | 1.20 | 7.80 | 16.7% | 30.8% | advance / base |

**Verdict on the sticky-daily-avoids-the-trap question: partially, not fully.** The sticky machine
clearly dampens whipsawing relative to a stateless per-bar read (these aren't flipping every single
day), but every one of these 6 names still shows a materially higher whipsaw fraction on daily than
weekly, and 4 of 6 disagree with the weekly engine's *current* stage outright.

META's own last ~7 months of daily regimes make this concrete — 10 regime changes since
2026-02-13, several very short-lived:

```
top      2026-02-13 -> 2026-03-13  (19 trading days)
decline  2026-03-13 -> 2026-04-17  (24 trading days)
advance  2026-04-17 -> 2026-05-26  (26 trading days)
top      2026-05-26 -> 2026-06-08  ( 9 trading days)
decline  2026-06-08 -> 2026-07-10  (22 trading days)
advance  2026-07-10 -> 2026-07-31  (15 trading days)   <- an "advance" call that reversed 15 td later
decline  2026-07-31 -> 2026-08-06  ( 4 trading days)   <- gone in 4 trading days
base     2026-08-06 -> 2026-08-18  ( 8 trading days)
decline  2026-08-18 -> 2026-09-09  (15 trading days)
advance  2026-09-09 -> today       ( 8 trading days, ongoing)
```
Hand-verified the latest flip directly against raw closes/MA/slope: on 2026-09-09, close=$653.69
vs. 30-day MA=$581.17 (band ceiling $610.23, so 7.0pp clear of the band) with slope flipping from
−0.31 the prior day to +0.41 — a real, clean trigger of the Decline→Advance rule. But the *prior*
Decline→Advance call (2026-07-10) reversed just 15 trading days later — exactly the "flip-flopped
on noise" pattern the task asked whether the sticky machine would avoid. It reduces it; it doesn't
prevent it.

## Recommendation

**Not a replacement for the weekly engine — but worth shipping as a second, clearly-labeled
column, not worth it as-is on its own, and not something to build further on right now.**

- The lag reduction is real and material: median +16 to +20 trading days (3-4 weeks) earlier on
  the two directions the task cared about most, and concretely today, 34/38 and 8/9 live
  "obviously lagging" weekly cases are already caught by the daily variant, weeks ago.
- The whipsaw cost is also real and material: ~5.4x the transition rate, roughly 2-2.7x the
  short-regime rate by both thresholds, and the 6 specifically-flagged names (chosen because a
  *stateless* daily read broke on them) still show elevated — just not extreme — whipsaw rates
  on the *sticky* daily variant. META's own last 7 months is a clean illustration: a genuine
  early call sitting right next to two short-lived false ones in the same window.
- Given that combination, I would **not** replace weekly with daily, and I would **not** ship
  daily as a silent second input into any blended/derived signal (e.g. the Screener's
  `weinstein_stage` surfacing) without a very visible "early/noisy read" label distinguishing it
  from the weekly "Stage" reading users currently rely on for a multi-month regime call. A second
  UI column (e.g. "Stage (daily, early read)" next to the existing "Stage") sitting purely
  alongside the current weekly one, with no scoring/blend impact, is the shape I'd suggest if this
  gets built — but that's a follow-up product decision, not something this investigation should
  greenlight on its own.

## Reproducing this

`cd backend && uv run python scripts/weinstein_daily_variant_investigation.py` — read-only against
`fathom.db`, makes zero writes and zero live Yahoo Finance calls, safe to rerun any time to refresh
these numbers against the latest cached data. Intermediate JSON output used to build the tables
above was written to the session scratchpad and deleted after this report was written; rerunning
the script regenerates it.
