# Profitability

Technical reference for the Profitability check (the "Profitability" card
on the Analysis tab). Scores Return on Equity (ROE), Return on Invested
Capital (ROIC), Revenue vs. Accounts Receivable, and Cash Conversion
Cycle (CCC) as a weighted blend, with a hard-fail override on ROE/ROIC.

## Data window

10 most recent annual fiscal years, plus a TTM column, chronological
order (oldest first). ROE and ROIC are **sourced directly from the data
provider's own pre-computed ratio fields** (annual and TTM), not
recomputed locally from raw financial-statement figures — converted from
a fraction (e.g. `0.31`) to a percent (`31`) to match this check's
percentage-point thresholds. Revenue-vs-AR and CCC are computed locally
from raw balance sheet / income statement figures.

Conceptually, the two ratios the provider computes are:

```
ROE (%)  = Net Income / Shareholders' Equity × 100
ROIC (%) = EBIT × (1 − effective tax rate) / (Equity + Total Debt − Cash) × 100
```

## Company-type exemptions

| Metric | Exempt for |
|---|---|
| ROIC | Bank, Insurance, Utility, REIT/Property Developer |
| Cash Conversion Cycle | Bank, Insurance, Utility, REIT/Property Developer, **or** any company (of any type) with no physical inventory across the full annual window |
| Revenue vs. Accounts Receivable | REIT/Property Developer only |
| ROE | never exempt |

**No-inventory detection** is data-driven, independent of company type:
if inventory reads null or zero across *every* one of the 10 annual
filings (the TTM/latest-quarter inventory figure is deliberately excluded
from this check — it has proven unreliable for genuinely inventory-free
companies), CCC is skipped regardless of sector/industry.

## Blend weights

| Metric | Base weight (all 4 applicable) |
|---|---|
| ROIC | 35% |
| ROE | 25% |
| Revenue vs. AR | 20% |
| CCC | 20% |

When a metric is exempt, its weight is redistributed **proportionally**
(not equally) across the remaining applicable metrics — each remaining
metric's base weight is divided by the sum of the applicable metrics' base
weights. Worked examples: ROIC + CCC exempt (Bank/Insurance/Utility) →
ROE 25/45 = 55.6%, AR 20/45 = 44.4% (not a 50/50 split). REIT (AR + ROIC +
CCC all exempt) → ROE alone at 100%.

## ROE and ROIC tiering

Both metrics share the same tiering logic, applied independently to each
series (10yr+TTM):

1. **Spike-robust average**: the plain average of the series, except the
   series **maximum** is excluded from the average if it's at least **2×**
   the median of the remaining points — this stops a single anomalous high
   year (e.g. a one-time tax benefit) from single-handedly inflating the
   average into a higher tier. The series **minimum** is never excluded.
2. **Minimum-year consistency check**: the single worst year in the series
   must also clear the tier's own floor. A worst year at or above **8%**
   always satisfies this. A worst year below 8% still satisfies it if it's
   "old and resolved": find the **most recent** occurrence of that minimum
   value; if it landed more than **3 periods** before TTM, and the trend
   classifier reads the full series as a recovery pattern
   (`grows_every_year` / `small_dip_recovers` / `significant_dip_recovers`
   / `multiple_dips_resolved` — see the Financials reference for this
   classifier), the low year is excused. If the minimum landed within the
   last 3 periods, it is **not** excused.
3. **Tier**, using the spike-robust average and the consistency check
   above:

   | Average | Consistency required? | Tier | Points | Hard fail |
   |---|---|---|---|---|
   | > 15% | yes | excellent | 100 | no |
   | 12% – 15% | yes | good | 85 | no |
   | 8% – 12% | no | marginal | 60 | no |
   | < 8% | — | fail | 0 | **yes** |

   An average above 12% or 15% that fails the consistency check falls
   through to `marginal`, not straight to `fail`.
4. **Unrecovered-decline demotion**: independently of the tier above, a
   windowed direction analysis (3-period early/late window, a real
   period-over-period drop is one steeper than **5 percentage points**, a
   sustained decline is 2 consecutive down-periods totaling more than
   **15 percentage points**) is run on the series. If it detects a
   sustained decline **and** the current (TTM) value is still below the
   early-window average, the tier is demoted one notch: `excellent` →
   `good` (85), `good` → `marginal` (60). `marginal` is never demoted
   further — `fail` only ever comes from the absolute floor in step 3
   above, never manufactured by this trend check alone.

## Recovery-aware exclusion (2026-08-08)

The avg/min-year tiering above runs on the full 10yr+TTM window as a flat,
unweighted average — this has a one-directional blind spot the
unrecovered-decline demotion (step 4 above) doesn't cover: demotion can
only ever *lower* a tier a good-average ticker has since let slip, never
*raise* one a bad-average ticker has since durably fixed. An old,
already-resolved dip (a real crash year, or a multi-year decline, that's
since been fully worked through) permanently drags the average down even
when every recent year is comfortably strong — confirmed real case: HWM's
ROE had two crash years (2016: -18.3%, 2017: -1.5%) immediately followed by
eight straight years of steady, genuine improvement (11.5% up to 34.4% by
TTM), yet the flat 10yr average still landed at `marginal` purely because
those two old years never stopped being counted.

Before computing the average (spike-robust or otherwise — this runs
*before* `_spike_robust_avg`, not instead of it), any **resolved dip
event** is excluded from the series. This reuses (not duplicates) the
dip-event/resolution machinery `financials.md`'s "Trend classification"
section documents in full for Step 1's own use — see that doc for the
complete mechanism and its own worked example (HWM's Revenue); summarized
here only as far as Step 4's exclusion behavior needs it:

1. Find every dip event in the series (`scoring/trend.py`'s `DipEvent` —
   the same contiguous-transition-merging machinery built for Step 1's
   dip-recovery fix; a multi-year decline is one event, not several), then
   keep only the ones that resolved (`resolved_dip_events`, also in
   `scoring/trend.py` — unlike `classify_trend`, this doesn't give up at
   the first *unresolved* event elsewhere in the same series; a resolved
   dip's stale years still get excluded even if a different, unrelated
   dip stays unresolved).
2. An event counts as **resolved** if it recovered either **literally**
   (TTM ≥ the event's own pre-dip baseline) or **durably** — the same
   age/recovery-run/direction test `classify_trend` uses (≥4 periods old,
   ≥3 clean trailing periods, non-negative robust late-window direction).
3. If any event resolved, exclude the **whole prefix** through the *last*
   resolved event's own trough (inclusive) — not just that event's own
   declining leg. A company whose only strong years sit before a resolved
   dip has, definitionally, already replaced that old high with a new,
   more current normal; the old high shouldn't get to anchor a tier the
   recent numbers no longer support either direction. This count is what
   `scoring/step4.py::recovery_excluded_prefix_length` computes — `0` if
   nothing resolved, otherwise how many leading values to drop before
   `score_roe`/`score_roic` average the rest.
4. The exclusion never applies if it would leave fewer than 2 points to
   average — this mechanism should never make a metric *less* scoreable
   than before.

Everything downstream (spike-robust averaging, min-year consistency,
unrecovered-decline demotion) runs unchanged on the reduced series — this
is purely a change to *which years* feed the existing tiering, not a new
tiering rule. Applies identically to both ROE and ROIC; does not apply to
ROE's negative-equity substitute path below (equity ≤ 0 bypasses the
normal averaging entirely, so there's nothing for this mechanism to act
on).

**Known tradeoff, accepted deliberately**: because exclusion fires
whenever a dip resolves — not gated on whether doing so actually helps —
a company in genuine, still-ongoing **structural decline** whose only
strong years sit years in the past can score *worse* once those years are
excluded, even though the underlying business hasn't newly deteriorated.
Confirmed real cases: **LHX** (strong ROE 7-10 years ago, weak and
still-weak since — Marginal→Fail once the old strong years are excluded)
and **MU**/**LVS** (similar shape on ROIC). This was evaluated directly
against two alternative designs — a narrower exclusion (only the dip's own
declining leg, not the whole prefix) and a recency-weighted average — both
prototyped and compared on real cached data (2026-08-08): the narrower
exclusion is safer but under-delivers (doesn't even fix HWM, since HWM's
worst years were never inside a detected declining *transition* — the
series was already rising through them); the recency-weighted average
doesn't beat this design on either fix-rate or regression count. This
"broad" design was chosen because it had the best resolve-to-regression
ratio of everything tested: across the full tracked universe, it resolves
**68 of 90** hard-fails in the affected set while only regressing **13
of 894** ROE/ROIC rows — 13 tickers is a small, known, named list, not an
open-ended risk.

### Reasoning note

Whenever exclusion fires, a descriptive note is attached to the ROE and/or
ROIC component — purely explanatory, mechanical/neutral wording (not "this
improved the score," since the mechanism applies unconditionally and
sometimes makes things worse — see the LHX/LUV/MU tradeoff above). This is
the first note ROIC has ever had: before this build, only ROE's
negative-equity substitute (below) carried any explanatory text at all —
`result["components"]["roic"]["note"]` didn't exist as a concept. States
how many years were excluded and their fiscal-year span, e.g. *"5 early
year(s) (2016–2020) excluded from this average — performance dipped during
that stretch and has since durably recovered, so those years no longer
represent current performance."* Re-derives the same exclusion the score
itself used (`recovery_excluded_prefix_length`, called independently by
the note builder, same pattern as the negative-equity substitute's own
note re-deriving `income_recovery_detail`) rather than threading it
through the scoring result.

## ROE's negative-equity substitute

If shareholders' equity is **≤ 0 in any period** of the window, raw ROE is
unreliable (sign-flipped) for the *entire* metric, and the normal
avg/min-year tiering above is replaced entirely:

- If Net Income has **no** non-positive periods at all → passes if the
  final (TTM) value is **≥** the first value in the window (a simple
  last-vs-first bar, not a full trend classification).
- If Net Income **does** have a non-positive period → find its most
  recent occurrence. If within the last 3 periods, this substitute check
  fails. If older than 3 periods, it passes only if the trend classifier
  reads the full Net Income series as a recovery pattern.
- **Passes** → `positive_despite_negative_equity`, **100 points**.
- **Fails** → `negative_equity_inconsistent_income`, **60 points**.

Neither outcome of this substitute path is a hard fail — a negative-equity
company can only hard-fail through the normal (equity-positive) path's
`< 8%` floor, never through this substitute.

### Reasoning note (2026-08-07)

Whenever this substitute path fires, a descriptive note is attached
alongside the 100/60 result — purely explanatory, never a score/verdict
input. It states which fiscal year(s) equity was negative and whether it's
since recovered, names which of the five branches above actually drove the
100/60 split (not just "equity was negative"), and cites Retained Earnings
and cumulative share-buyback cash flow as *informational* context only —
never as an asserted cause. This distinction matters in practice: a
company that retires repurchased shares (rather than holding treasury
stock) routes the buyback cost through Retained Earnings directly, which
can push Retained Earnings deeply negative even in a highly profitable,
serial-repurchasing company (confirmed real case: FTNT, 10 straight years
of positive, growing Net Income with Retained Earnings negative in 8 of
the last 9 years) — so Retained Earnings' sign alone can't distinguish
accumulated losses from buyback accounting, and the note is written to
never imply otherwise. If ROIC has a real result for this ticker, it's
cited too, always with an explicit reliability caveat (ROIC has no guard
against a near-zero/negative invested-capital denominator today). The note
closes by pointing at concrete further research — the 10-K equity note for
a positive result, one-time income-statement items for a negative one.

## ROE vs. ROIC divergence note

An informational-only note (never affects score or verdict) is attached
when ROIC's tier is exactly `marginal` **and** ROE's tier is `excellent`
or `good` — a tier-relative comparison (not a fixed percentage-point gap),
chosen because a fixed gap can't distinguish a genuine leverage story from
a naturally large gap between two otherwise-healthy numbers. Does not fire
when ROIC is exempt (`None`), when ROIC's tier is `fail` (already forces a
hard fail on its own) or `excellent`/`good`, or when ROE used the
negative-equity substitute labels above.

## Revenue vs. Accounts Receivable

Computed from Revenue and Accounts Receivable across the same 10yr+TTM
window (`n` = number of year-over-year transitions, i.e. window length
minus 1).

For each transition: `revenue_yoy` and `ar_yoy` are the period-over-period
percent changes (skipped if the prior value is missing or zero); the
`gap` is `ar_yoy − revenue_yoy`. A gap greater than **2.0 percentage
points** (the noise floor) counts as AR "outpacing" Revenue that year.
Gap magnitude bands: **small** ≤ 15pp, **medium** 15–50pp, **large** > 50pp.

A separate, scale-invariant **aggregate trend** signal is also computed:
Days Sales Outstanding (`DSO = AR / Revenue × 365`) for an early 3-period
window vs. a **robust** late 3-period window (the single most extreme
point in the late window excluded before averaging). If the robust late
average exceeds the early average by more than **15 days**, this reads as
`aggregate_outpacing`.

Checked in this order (worst tier first):

1. `aggregate_outpacing` is true, **or** a `strong_red_flag` fired
   (Revenue declined by more than 2pp while AR grew by more than 2pp in
   the *same* transition, and that transition falls within the most
   recent 3 transitions) → `outpacing_majority_or_red_flag`, **0**.
2. The count of outpacing transitions is at least
   `max(3, round(0.6 × n))`, **or** any single transition's gap is
   "large" (> 50pp) — **and** at least one of the transitions driving
   that trigger falls within the most recent 3 transitions → 
   `outpacing_concerning`, **40**. (If every qualifying transition is
   older than that, this tier is skipped and the checks below run
   instead, using the same full transition history.)
3. Zero outpacing transitions, or exactly one outpacing transition with a
   "small" gap → `healthy`, **100**.
4. Otherwise (one or two outpacing transitions not caught above) →
   `outpacing_isolated`, **70**.

Fewer than 1 transition, or mismatched Revenue/AR series lengths →
`insufficient_data`, **0**.

## Cash Conversion Cycle

Computed per period as:

```
DIO (Days Inventory Outstanding)   = Inventory / COGS × 365
DSO (Days Sales Outstanding)       = Accounts Receivable / Revenue × 365
DPO (Days Payable Outstanding)     = Accounts Payable / COGS × 365
CCC = DIO + DSO − DPO
```

A period is skipped entirely (not zero-filled) if Revenue or COGS is
missing/zero, or if Inventory, AR, or AP is missing.

Classification dispatches first on the **sign profile** of the full CCC
series — a negative CCC (the company collects from customers before
paying its own suppliers) is the *opposite* signal from a positive one,
not a milder version of it:

1. **Consistently negative** (every value ≤ **1.0 day**, the sign
   tolerance): always scores **100**. Sub-labeled
   `consistently_negative_strengthening` if the late-window average is
   more negative than the early-window average, or
   `consistently_negative_weakening` if it's less negative but still
   negative — both score identically; a still-deeply-negative CCC is never
   treated as a red flag just because it eased slightly.
2. **Consistently positive** (every value ≥ **-1.0 day**): scored by the
   windowed trend logic below.
3. **Mixed** (crosses the sign boundary): first checked for an isolated
   outlier — if exactly one point sits alone on the minority side of zero
   and its magnitude is at least **3×** the typical (median) magnitude of
   the majority-side points, it's treated as a one-off event, not a
   genuine sign change. If excluding that point leaves the rest of the
   series entirely on the negative side, case 1 applies (scored using the
   *full* series, spike included, for the direction reading). Otherwise —
   including when the lone outlier can't fully resolve the series to one
   side — the series is scored by the windowed trend logic below, using
   the full original series (the outlier is not stripped from the score
   itself, only from the rescue eligibility check).

   If no isolated outlier rescues it, a genuine sign crossing is
   sub-classified by comparing an early 3-period average to a robust late
   3-period average (single most extreme late point excluded):
   - Started positive, settled negative (early > 1.0, robust late < -1.0)
     → `gained_bargaining_power`, **100**.
   - Started negative, settled positive (early < -1.0, robust late > 1.0)
     → `lost_bargaining_power`, **0**.
   - No clear settle: if the whole series' amplitude (`max(|min|, |max|)`)
     stays within **10 days** → `negligible_working_capital`, **85**
     (structurally low working-capital intensity, not noise to flag).
     Otherwise → `mixed_unclear`, **40**.

**Windowed trend logic (consistently-positive case)** — the same style of
early/late-window direction analysis used elsewhere in this app, applied
so that a *declining* CCC (faster cash conversion, the desirable
direction) reads as improvement:

- window = 3 periods; a real period-over-period move is one larger than
  **3 days**; a "sustained worsening" is 2 consecutive periods where CCC
  rises, totaling more than **5 days** of increase.
- direction = (early-window average) − (late-window average); positive
  means CCC declined (improved) overall.
- If sustained worsening occurred **and** the overall direction is still
  net negative (worse than **-1 day**) → `sustained_upward`, **0**.
- Else if 2 or more real rises occurred **and** the overall direction is
  close to flat (within **2 days**) → `volatile_no_trend`, **40**.
- Else if the overall direction is flat-or-improving (**≥ -1 day**):
  - Spike guard: if there was no sustained-worsening flag, but a *robust*
    version of the late-window average (single most extreme late point
    excluded) shows the direction was actually worse than -1 day, the
    apparent improvement is discounted as a single anomalous good point →
    `sustained_upward`, **0**.
  - Otherwise, if at least 1 real rise occurred anywhere →
    `volatile_but_net_declining`, **70**.
  - Otherwise (no real rises at all) → `declining_or_stable`, **100**.
- Otherwise (net worsening direction, but not meeting the "sustained"
  bar — e.g. a slow multi-year creep) → `sustained_upward`, **0**.

Fewer than 2 usable periods → `insufficient_data`, score 0.

## Verdict

```
score = round(Σ applicable_metric_points × its_renormalized_weight)   [0, 100]
hard_fail = ROE hard-failed, OR (ROIC applicable AND ROIC hard-failed)
```

- **Fail** if `hard_fail` is true — regardless of the blended score.
  Revenue-vs-AR and CCC landing in their own worst tier drag the score
  down but never force a Fail on their own.
- **Strong Pass** if the blended score is **> 90**.
- **Pass** otherwise.

Unlike Debt's verdict logic, there is **no** blended-score floor beneath
which a non-hard-fail result is forced to Fail — a blended score under 70
that isn't a hard fail still displays as "Pass."
