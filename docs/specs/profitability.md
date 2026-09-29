# Profitability

The Profitability card asks how efficiently a company turns the capital invested in it into
profit, and whether its day-to-day operations are run efficiently. It looks at up to four
things, depending on the company:

- **Return on Equity (ROE)** — how much profit the company generates for every dollar
  shareholders have invested in it. A consistently strong ROE suggests the business is a
  genuinely efficient user of shareholders' money.
- **Return on Invested Capital (ROIC)** — a broader version of the same idea, measuring profit
  generated against *all* the capital in the business (both shareholder equity and borrowed
  money), not just the equity portion. ROIC is harder to artificially inflate than ROE, since ROE
  alone can be flattered by taking on debt to fund share buybacks — Fathom weighs ROIC slightly
  more heavily than ROE for this reason, and will flag it as a note (not a score penalty) when
  ROE looks notably stronger than ROIC.
- **Accounts Receivable trend** — whether the money customers owe the company (but haven't paid
  yet) is growing faster than revenue itself. When receivables consistently outpace revenue, it
  can mean the company is recognizing sales before it's actually collecting cash for them —
  worth a closer look, though not automatically a sign of trouble.
- **Cash Conversion Cycle (CCC)** — roughly, how many days it takes the company to turn money
  spent running the business back into cash from customers. A shorter cycle is more efficient. A
  CCC that's actually *negative* is not a milder version of a positive one — it's the opposite,
  better, signal: it means the company collects cash from customers before it has to pay its own
  suppliers. Fathom treats a consistently negative CCC as a top-tier result, not a warning sign.

## A weak result on ROE or ROIC always fails the whole card

Revenue-vs-Receivables and CCC are treated as supporting evidence for what ROE and ROIC already
indicate, not independent headline signals. If either ROE or ROIC (when applicable) comes in
genuinely weak, the whole Profitability check fails outright, regardless of how the other two
metrics look.

ROE and ROIC are judged on multiple years, not a single snapshot — but a rough patch that's
genuinely behind the company (a real, multi-year rough stretch that's since given way to a
sustained, durable recovery) doesn't keep dragging the reading down forever once it's clearly
over. This cuts both ways: it's also possible for a company whose best years are behind it, with
a real rough stretch still ongoing today, to read weaker once those old strong years stop
counting.

## Some checks don't apply to every company type

- **ROIC** isn't meaningful for Banks, Insurance companies, Utilities, or REITs/Property
  Developers, and is skipped for those company types.
- **Cash Conversion Cycle** isn't meaningful for the same set of company types, and is also
  automatically skipped for any company that carries no physical inventory at all, since the
  underlying concept doesn't apply cleanly to a business that doesn't stock goods.
- **Accounts Receivable trend** isn't meaningful for **Banks, Insurance companies, Utilities, or
  REITs/Property Developers either** (extended from REIT-only to this full set on 2026-09-04) —
  REITs (rental income) have no comparable concept of receivables outpacing revenue, and
  Bank/Insurance/Utility revenue recognition doesn't map onto ordinary trade receivables the way
  a Standard operating company's does.

When a check is skipped, the remaining applicable checks are reweighted to make up the
difference, rather than penalizing the company for a metric that doesn't apply to its business
model. See [Company type variations](company-type-variations.md) for the full picture.

## What the verdict means

- **Fail** — ROE, or ROIC where applicable, comes in weak, regardless of how the other metrics
  look, **or** the blended score itself lands under 70 even without a hard breach (see "Verdict"
  below).
- **Pass** — returns on capital are solid overall.
- **Strong Pass** — returns on capital are excellent, with supporting metrics (receivables
  trend, cash cycle) also reading well.

See the [Glossary](glossary.md) for how every verdict label is defined.

---

## Technical reference

### Data window

10 most recent annual fiscal years, plus a TTM column, chronological order (oldest first). ROE
and ROIC are **sourced directly from FMP's own pre-computed ratio fields** (annual and TTM), not
recomputed locally — converted from a fraction to a percent. Revenue-vs-AR and CCC are computed
locally from raw balance sheet / income statement figures.

One constant, `ANNUAL_WINDOW` (10, `data/step4_data.py`), controls both what is fetched/shown and
what feeds the score, matching Financials. There is no separate, narrower scoring window (an
earlier design scored on the most recent 5 years while charting more; that decoupling was
removed), so a ticker's score reflects its full 10-year history — including years 6-10, which can
move scores versus the old 5-year behavior for tickers whose older years look materially
different. This is an intentional tradeoff for a longer, more complete read on ROE/ROIC/AR/CCC
trends.

```
ROE (%)  = Net Income / Shareholders' Equity × 100
ROIC (%) = EBIT × (1 − effective tax rate) / (Equity + Total Debt − Cash) × 100
```

### Company-type exemptions

| Metric | Exempt for |
|---|---|
| ROIC | Bank, Insurance, Utility, REIT/Property Developer |
| Cash Conversion Cycle | Bank, Insurance, Utility, REIT/Property Developer, **or** any company (of any type) with no physical inventory across the full annual window |
| Revenue vs. Accounts Receivable | **Bank, Insurance, Utility, REIT/Property Developer** (extended from REIT-only 2026-09-04) |
| ROE | never exempt |

The three exemption gates are the constants `ROIC_EXEMPT_TYPES`, `CCC_EXEMPT_TYPES` and
`AR_EXEMPT_TYPES` in `data/step4_data.py`; all three currently hold the identical set
`{"Bank", "Insurance", "REIT/Property Developer", "Utility"}`. `AR_EXEMPT_TYPES` was REIT-only
until 2026-09-04, when it was extended to match the other two — a deliberate design decision, not
a bug fix: Bank/Insurance/Utility revenue recognition doesn't map onto ordinary trade receivables
the way a Standard operating company's does, the same reasoning REIT's exemption already rested
on. `score_step4`'s weight renormalization is generic over whatever metrics are applicable, so
this needed no scoring-math change, only the gate itself.

**No-inventory detection** is data-driven, independent of company type: if inventory reads null
or zero across *every* one of the 10 annual filings (the TTM/latest-quarter figure is
deliberately excluded — it has proven unreliable for genuinely inventory-free companies: in
verification Mastercard's latest quarter showed +$2.06B inventory and ServiceNow's -$28M despite
straight clean-zero annual years, a provider classification artifact rather than a real change in
the business), CCC is skipped regardless of sector/industry.

### Blend weights

| Metric | Base weight (all 4 applicable) |
|---|---|
| ROIC | 35% |
| ROE | 25% |
| Revenue vs. AR | 20% |
| CCC | 20% |

When a metric is exempt, its weight is redistributed **proportionally** (not equally) across the
remaining applicable metrics — each remaining `BASE_WEIGHTS` entry is divided by the sum of the
applicable entries, preserving their relative ratio, and this is fully generic over whichever
metrics apply (no fixed reassignment table like Financials' single CFO on/off exemption). An
earlier design split the applicable metrics equally (1/N); it was replaced by these weights on
2026-08-01. Worked examples: no-inventory company (CCC exempt only) → ROE 25/80 = 31.25%, ROIC
35/80 = 43.75%, AR 20/80 = 25%. ROIC + CCC + AR exempt (Bank/Insurance/Utility) →
ROE alone at 100%. REIT (AR + ROIC + CCC all exempt) → ROE alone at 100%.

This is a deliberate design choice (2026-08-01), not a bug-driven fix: ROIC is weighted above ROE
since it's harder to game (unaffected by the leverage/buyback effects that inflate ROE — see
`check_roe_roic_divergence`) and reflects capital efficiency more directly; Revenue-vs-AR and CCC
are corroborating/contradicting supporting evidence for what ROE/ROIC already say, not
independent headline signals, weighted lower and equal to each other. Headline pair 60% (35/25)
versus supporting pair 40% (20/20) — a "moderate tilt". It is a pure re-weighting: no individual
metric's own tiering changed.

### ROE and ROIC tiering

Both metrics share the same tiering logic, applied independently to each series (10yr+TTM):

1. **Spike-robust average**: the plain average of the series, except the series **maximum** is
   excluded if it's at least **2×** the median of the remaining points. The series **minimum** is
   never excluded.
2. **Minimum-year consistency check** (a straight average alone would let one bad year hide
   behind several good ones — a high average diluted by one very weak year lands in `marginal`,
   not `excellent`): the single worst year must also clear the tier's own floor. A worst year at or above **8%** always satisfies this. A worst year below 8% still
   satisfies it if it's "old and resolved": find its most recent occurrence; if it landed more
   than **3 periods** before TTM, and the trend classifier reads the full series as a recovery
   pattern, the low year is excused.
3. **Tier**, using the spike-robust average and the consistency check:

   | Average | Consistency required? | Tier | Points | Hard fail |
   |---|---|---|---|---|
   | > 15% | yes | excellent | 100 | no |
   | 12% – 15% | yes | good | 85 | no |
   | 8% – 12% | no | marginal | 60 | no |
   | 0% – 8% | no | weak_but_positive | graduated, 20–55 | no |
   | < 0% | — | fail | 0 | **yes** |

   An average above 12%/15% that fails the consistency check falls through to `marginal`, not
   straight to `fail`.

   **Below-floor graduated scale (2026-08-13)**: `< 8%` used to be a flat `fail`/0/hard-fail
   regardless of depth or sign — a company chronically mediocre-but-never-negative scored
   identically to one actively destroying capital. Now split by sign: `avg ≥ 0%` graduates
   linearly from **20** points (at 0%) to **55** points (just under 8%, deliberately below
   `marginal`'s 60) and is **not** a hard fail; `avg < 0%` is unchanged — flat 0, hard fail,
   unconditionally.
4. **Unrecovered-decline demotion**: independently of the tier above, a windowed direction
   analysis (3-period early/late window, a real drop is steeper than **5pp**, a sustained decline
   is 2 consecutive down-periods totaling more than **15pp**) is run on the series. If it detects
   a sustained decline **and** the current (TTM) value is still below the early-window average,
   the tier is demoted one notch: `excellent` → `good` (85), `good` → `marginal` (60). `marginal`
   is never demoted further.

### Recovery-aware exclusion (2026-08-08)

The avg/min-year tiering runs on the full 10yr+TTM window as a flat, unweighted average — an old,
already-resolved dip permanently drags the average down even when every recent year is
comfortably strong. This fixes a one-directional blind spot: the unrecovered-decline demotion
below can only ever *lower* the tier of a good-average ticker that has since slipped, never
*raise* one whose bad average predates a durable fix. Motivating case: HWM's ROE had two crash
years (2016-17) followed by 8 straight years of genuine improvement, yet scored `marginal`
because those two years never stopped counting — now `excellent`. Before computing the average (spike-robust or otherwise), any **resolved dip
event** is excluded from the series, reusing the dip-event/resolution machinery
[Financials](financials.md)'s "Trend classification" section documents in full:

1. Find every dip event in the series (`scoring/trend.py`'s `DipEvent`), then keep only the ones
   that resolved (`resolved_dip_events`).
2. An event counts as resolved if it recovered either literally (TTM ≥ the event's own pre-dip
   baseline) or durably (the same ≥4-periods-old / ≥3-clean-trailing-periods / non-negative
   robust late-window direction test `classify_trend` uses).
3. If any event resolved, exclude the **whole prefix** through the *last* resolved event's own
   trough (inclusive) — not just that event's own declining leg.
4. The exclusion never applies if it would leave fewer than 2 points to average.

Everything downstream (spike-robust averaging, min-year consistency, unrecovered-decline
demotion) runs unchanged on the reduced series. Applies identically to both ROE and ROIC; does
not apply to ROE's negative-equity substitute path below.

**Known tradeoff, accepted deliberately**: because exclusion fires whenever a dip resolves — not
gated on whether doing so actually helps — a company in genuine, still-ongoing structural
decline whose only strong years sit years in the past can score *worse* once those years are
excluded. Confirmed via a full-universe check against two alternative designs (narrower
declining-leg-only exclusion; recency-weighted average): this "broad" design resolves 68 of 90
hard-fails in the affected set while only regressing 13 of 894 ROE/ROIC rows.

Whenever exclusion fires, a descriptive note is attached to the ROE and/or ROIC component,
stating how many years were excluded and their fiscal-year span.

### ROE's negative-equity substitute

If shareholders' equity is **≤ 0 in any period**, raw ROE is unreliable for the entire metric,
and the normal avg/min-year tiering is replaced entirely:

- If Net Income has **no** non-positive periods at all → passes if the final (TTM) value is
  **≥** the first value in the window (a simple last-vs-first bar, not a full trend
  classification — "consistently maintained/growing" is inherently a qualitative judgment). The
  original design was only this branch (positive-and-non-declining Net Income); the
  recovery-aware branch below was added later.
- If Net Income **does** have a non-positive period → find its most recent occurrence. If within
  the last 3 periods, this substitute check fails. If older than 3 periods, it passes only if the
  trend classifier reads the full Net Income series as a recovery pattern.
- **Passes** → `positive_despite_negative_equity`, **100 points**.
- **Fails** → `negative_equity_inconsistent_income`, **60 points**.

Neither outcome is a hard fail — a negative-equity company can only hard-fail through the normal
(equity-positive) path's `< 8%` floor.

Whenever this substitute path fires, a descriptive note is attached (2026-08-07) stating which
fiscal year(s) equity was negative, whether it's since recovered, which of the branches actually
drove the 100/60 split, and citing Retained Earnings/cumulative buyback cash flow as
*informational* context only — never as an asserted cause (a company that retires repurchased
shares routes buyback cost through Retained Earnings directly, which can push it deeply negative
even in a highly profitable, serial-repurchasing company).

### ROE vs. ROIC divergence note

An informational-only note is attached when ROIC's tier is exactly `marginal` **and** ROE's tier
is `excellent` or `good` — a tier-relative comparison, not a fixed percentage-point gap. Does not
fire when ROIC is exempt, when ROIC's tier is `fail` or `excellent`/`good`, or when ROE used the
negative-equity substitute labels above.

### Revenue vs. Accounts Receivable

Computed from Revenue and Accounts Receivable across the same 10yr+TTM window (`n` = number of
year-over-year transitions).

For each transition: `revenue_yoy` and `ar_yoy` are the period-over-period percent changes
(skipped if the prior value is missing or zero); the `gap` is `ar_yoy − revenue_yoy`. A gap
greater than **2.0 percentage points** (the noise floor) counts as AR "outpacing" Revenue that
year. Gap magnitude bands: small ≤ 15pp, medium 15–50pp, large > 50pp.

A separate, scale-invariant **aggregate trend** signal is also computed: Days Sales Outstanding
(`DSO = AR / Revenue × 365`) for an early 3-period window vs. a **robust** late 3-period window
(the single most extreme point in the late window excluded before averaging). If the robust late
average exceeds the early average by more than **15 days** (`AR_DSO_TREND_MATERIALITY_DAYS`,
derived from the real distribution of DSO gaps among tickers in the worst tier at the time),
this reads as `aggregate_outpacing`.

Checked in this order (worst tier first):

1. `aggregate_outpacing` is true, **or** a `strong_red_flag` fired (Revenue declined by more than
   2pp while AR grew by more than 2pp in the *same* transition, within the most recent 3
   transitions) → `outpacing_majority_or_red_flag`, **0**.
2. The count of outpacing transitions is at least `max(3, round(0.6 × n))` (`AR_CONCERNING_
   TRANSITION_RATIO`, generalizing the original "3 of 5" transitions rule to any window size — it
   was originally a fixed count that was never rescaled when the window grew from 5 to 10
   transitions, so it fired at just 30% severity instead of 60%; the formula gives 3 at n=5 and 6
   at n=10),
   **or** any single transition's gap is "large" (> 50pp) — **and** at least one of the
   transitions driving that trigger falls within the most recent 3 → `outpacing_concerning`,
   **40**.
3. Zero outpacing transitions, or exactly one outpacing transition with a "small" gap →
   `healthy`, **100**.
4. Otherwise → `outpacing_isolated`, **70**.

Fewer than 1 transition, or mismatched Revenue/AR series lengths → `insufficient_data`, **0**.

**Why the worst tier looks like this (2026-08-01)**: two calibration bugs were fixed together.
(1) The `strong_red_flag` check (revenue declining while AR grows) was a bare sign comparison with
no materiality floor — CAT (revenue -3.4%, AR +0.14%) scored identically to BA (revenue -24.3%,
AR +217%); it is now gated on `AR_GAP_NOISE_FLOOR` (2pp) on both legs. (2) The tier's old trigger,
"a majority of individual years outpacing", mis-flagged companies with lumpy year-to-year timing
but a fine aggregate trend (AAPL outpaced in 6 of 10 individual years, yet AR grew slower than
revenue in aggregate: 93% vs 109%). A raw full-period growth-% comparison was tried first but is
fragile when a base year is small or anomalous — TER's cached TTM Accounts Receivable is $1.1
trillion against $3.8B revenue (almost certainly a raw provider data-quality issue, still worth a
manual check), which produced a 576,425pp "gap". DSO is scale-invariant and, with the robust
late-window average, resistant to one bad year. Only the worst tier's trigger changed; the
`outpacing_concerning` / `outpacing_isolated` / `healthy` tiers keep their individual-year-count
logic.

Whenever Revenue-vs-AR lands in any non-healthy tier, a dynamically-computed manual-check note
(`components.revenue_vs_ar.note`, built in `data/step4_data.py::_build_ar_note` — deliberately not
in the pure `scoring/step4.py`, since it needs Operating Cash Flow, which isn't part of the AR
score itself) states which comparison actually drove the flag (DSO trend vs. individual-year
count, with real numbers either way), whether OCF is tracking Net Income over the same window (a
lagging OCF alongside rising Net Income is the real red flag for revenue being recognized before
cash arrives), and a static business-model-shift prompt that can't be answered from structured
data.

### Cash Conversion Cycle

```
DIO (Days Inventory Outstanding)   = Inventory / COGS × 365
DSO (Days Sales Outstanding)       = Accounts Receivable / Revenue × 365
DPO (Days Payable Outstanding)     = Accounts Payable / COGS × 365
CCC = DIO + DSO − DPO
```

A period is skipped entirely (not zero-filled) if Revenue or COGS is missing/zero, or if
Inventory, AR, or AP is missing.

The windowed trend logic further down is the same early/late-direction + dip-count +
sustained-decline classifier Financials uses for margins (`scoring/series_trend.py::
analyze_series_direction`, shared), run on the *negated* series, since a declining CCC (faster
cash conversion) is the desirable direction while a declining margin is not. Its window/dip/
sustained-decline constants (`CCC_TREND_WINDOW`, `CCC_REAL_MOVE_DAYS`, `CCC_SUSTAINED_STEPS`,
`CCC_SUSTAINED_DAYS`) are first-pass judgment calls, not values validated against a prior
baseline (unlike the sign-aware constants below, derived from a real cache-only sweep).

Classification dispatches first on the **sign profile** of the full CCC series (2026-08-01). The
prior classifier ran every series through the same early/late-direction logic regardless of
sign, so AAPL — CCC negative throughout the whole window (-84 to -54 days), i.e. suppliers fund
the business — scored 0/`sustained_upward` and dragged an otherwise 100/100 ROE/ROIC company to
a Profitability score of 50. A negative CCC is the opposite signal from a positive one, not a
milder version. The consistently-positive path is the entire pre-existing logic moved verbatim
(the NVDA/IDXX shape: genuinely positive and rising, still scoring 0).

1. **Consistently negative** (every value ≤ **1.0 day**): always scores **100**. Sub-labeled
   `consistently_negative_strengthening`/`_weakening` by whether the late-window average is more
   or less negative than the early-window average — both score identically.
2. **Consistently positive** (every value ≥ **-1.0 day**): scored by the windowed trend logic
   below.
3. **Mixed** (crosses the sign boundary): first checked for an isolated outlier — if exactly one
   point sits alone on the minority side of zero and its magnitude is at least **3×** the typical
   (median) magnitude of the majority-side points (`CCC_SPIKE_ISOLATION_RATIO`), it's treated as
   a one-off event. If excluding that point leaves the rest entirely on the negative side, case 1
   applies (using the *full* series, spike included, for the direction reading). Otherwise the
   series is scored by the windowed trend logic below, using the full original series.

   If no isolated outlier rescues it, a genuine sign crossing is sub-classified by comparing an
   early 3-period average to a robust late 3-period average:
   - Started positive, settled negative (early > 1.0, robust late < -1.0) →
     `gained_bargaining_power`, **100**.
   - Started negative, settled positive (early < -1.0, robust late > 1.0) →
     `lost_bargaining_power`, **0**.
   - No clear settle: if the whole series' amplitude stays within **10 days**
     (`CCC_NEAR_ZERO_AMPLITUDE_DAYS`) → `negligible_working_capital`, **85** (COST, CASY, TGT:
     oscillates near zero, structurally low capital intensity, not noise to flag). Otherwise →
     `mixed_unclear`, **40** (CCL-shape: real, larger swings with no clear pattern — worth a
     manual look).

   The isolated-outlier rescue exists for cases like ABBV: ten years of 62-102 day positive CCC
   and one TTM value of -496.7, an evident one-time acquisition-related accounting event,
   rescued back to the unchanged positive path (score stays 70). The gained-bargaining-power
   shape is KR's (starts ~+8 days, ends ~-7.6). The three new constants (`CCC_SIGN_EPS_DAYS`
   = 1.0, `CCC_NEAR_ZERO_AMPLITUDE_DAYS` = 10.0, `CCC_SPIKE_ISOLATION_RATIO` = 3.0) were derived
   from a real, cache-only sweep of all 318 CCC-scorable tickers, not guessed.

**Windowed trend logic (consistently-positive case)**, applied so that a *declining* CCC (faster
cash conversion, desirable) reads as improvement:

- window = 3 periods; a real move is one larger than **3 days**; a "sustained worsening" is 2
  consecutive periods where CCC rises, totaling more than **5 days**.
- direction = (early-window average) − (late-window average); positive means CCC declined
  (improved).
- If sustained worsening occurred **and** the overall direction is still net negative (worse than
  **-1 day**, `CCC_STABLE_TOLERANCE_DAYS`) → `sustained_upward`, **graduated**. The direction gate
  matters because the sustained-worsening scan covers the *entire* window with no recency
  awareness: without it, an old, small, fully-reversed blip (MSFT's 2016-2018 uptick, since
  outweighed by a decade of improvement) could permanently cap the score at 0 while the
  early-vs-late direction was strongly positive. `analyze_series_direction` itself and Financials'
  margin classifier (which calls the same shared function) are unaffected by this gate.
- Else if 2 or more real rises occurred **and** the overall direction is close to flat (within
  **2 days**) → `volatile_no_trend`, **40**.
- Else if the overall direction is flat-or-improving (**≥ -1 day**):
  - Spike guard: if no sustained-worsening flag, but a *robust* late-window average shows the
    direction was actually worse than -1 day, the apparent improvement is discounted →
    `sustained_upward`, **graduated**.
  - Otherwise, if at least 1 real rise occurred → `volatile_but_net_declining`, **70**.
  - Otherwise → `declining_or_stable`, **100**.
- Otherwise → `sustained_upward`, **graduated**.

**`sustained_upward` graduated scale (2026-08-13)**: all three branches used to score a flat 0
regardless of how far CCC had actually worsened. Graduates linearly from **40** points (matching
`volatile_no_trend`'s own score) at **10 days** of worsening or less, down to **0** at **50
days** or more. The magnitude used is whichever number actually drove the classification in each
branch — the raw direction for the first/third branches, the *robust* late-window direction for
the spike-guard branch.

Fewer than 2 usable periods → `insufficient_data`, score 0.

### Verdict

```
score = round(Σ applicable_metric_points × its_renormalized_weight)   [0, 100]
hard_fail = ROE hard-failed, OR (ROIC applicable AND ROIC hard-failed)
```

- **Fail** if `hard_fail` is true — regardless of the blended score. `hard_fail` comes only from
  ROE and ROIC (mirroring Growth Rate's and Debt's hard-fail pattern: a hard rule is never
  diluted by averaging). Revenue-vs-AR and CCC landing in their own worst tier (0 points) drag
  the blended score down but **never** force a Fail on their own — a receivables/CCC red flag is
  worth investigating, not an automatic disqualifier the way persistently poor ROE/ROIC is. (The
  ROE/ROIC hard-fail trigger was originally any average `< 8%`; since 2026-08-13 it is only an
  average `< 0%` — see "ROE and ROIC tiering".)
- **Fail** if the blended score is **< 70** (`PASS_SCORE_THRESHOLD`, added 2026-08-13), even when
  `hard_fail` is false — a mandatory companion to the ROE/ROIC/CCC graduated-scale fixes: before
  this, there was **no** blended-score floor at all, so any non-hard-fail result displayed "Pass"
  regardless of how low the score was.
- **Strong Pass** if the blended score is **> 90**.
- **Pass** otherwise.

This floor is global, not scoped to the graduated-scale fix — confirmed via a full-universe
recompute: 189 Step 4 verdict changes, 7 flipping to a genuine Pass (the graduated fix's direct
effect) and 182 flipping from a previously-masked Pass to a correctly-computed Fail (most of
those already below 70 before this build, for unrelated reasons the flat floor was never there
to catch).

---

## Calibration notes

Validation facts behind the current numbers; the full investigation narratives are in
`docs/archive/claude-md-history-scoring.md`.

- **Recovery-aware exclusion (2026-08-08)**: 68 of 90 affected hard-fails resolved; 13 accepted
  regressions are structural decliners (e.g. LHX/LUV/MU) whose only strong years sit before a
  resolved-by-age dip. Two alternative designs (a narrower span-only exclusion; a recency-weighted
  average) were prototyped and rejected.
- **CCC sign-aware classification (2026-08-01)**: full-universe recompute — 78 of 318 tickers'
  CCC sub-score changed, propagating to 78 blended-score changes, 3 verdict flips (AZO/FDS/ORLY,
  Pass 85 → Strong Pass 92), and 13 tickers moving off a masked Pass (score < 70 shown as
  "Pass") to a genuinely-earned ≥ 70, AAPL 50 → 75. 194 tickers remained masked-Pass afterward
  (before the 2026-08-13 verdict floor closed that gap), since this fix only addressed CCC's own
  contribution.
- **Revenue-vs-AR noise floor and DSO trend (2026-08-01)**: `AR_DSO_TREND_MATERIALITY_DAYS` (15.0)
  was derived from the DSO gaps of the 163 tickers in the worst tier at the time — median gap only
  +2.3 days (most of the old tier was noise); 15.0 keeps the ~24% with a genuinely elevated
  multi-year DSO increase. Recompute: 122 of 504 tickers' Profitability score changed, 0 verdict
  flips (the verdict is `hard_fail`-gated, unaffected by AR's point contribution at that time);
  the worst tier dropped from 164 to 98 tickers (60% of the reduction from the noise floor
  alone). AAPL, ANET, ISRG, CVNA, IBKR, VRSN moved off the worst tier; PRU/TFC (genuine, material
  red flags) stayed at 0; TER stays flagged (real if smaller elevated DSO trend).
- **Weighted blend (2026-08-01)**: spot-checked on real cached data, not a full-universe recompute
  (a deliberate re-weighting, not a correctness fix): AAPL 85 → 88 (verdict unchanged), MA 90 → 92
  (Pass → Strong Pass, since ROE/ROIC were already both 100), FICO 67 → 75.
- **ROE/ROIC below-floor and CCC `sustained_upward` graduation (2026-08-13)**: scans behind the
  change — 142 of 170 (83.5%) ROIC hard-fails and 61 of 86 (71%) ROE hard-fails never had a
  negative average at all; CCC `sustained_upward` worsening had median 26.3 days, p75 51.8. The
  from-scratch GLW trace that motivated it: Step 4 scored 35/Fail purely from ROIC and CCC both
  flattening to 0 though ROIC never went negative in 11 years; now 58/Fail (ROIC avg 6.42%, CCC
  ~18 days worse than its 2016-19 baseline are genuinely weak, just not capital-destroying).
- **The companion `score < 70` verdict floor is non-negotiable**: stress-tested before shipping —
  graduating ROE/ROIC alone, without the floor, would have flipped 153 tickers to a false Pass
  (146 of them, 95%, still scoring under 70). Its blast radius (189 verdict changes, not the ~7
  estimated from an isolated simulation) was accepted deliberately: the 7 genuine new Passes are
  VZ, T, CFG, KR, EFX, WCN and CNSWF; of the 182 masked-Pass → Fail flips, 135 have an unchanged
  score and 47 an improved score still under 70. Overall Assessment ripple: 27 tickers' Overall
  verdicts flipped, all upward, 0 regressions (Profitability's ~20% weight can't newly fail
  anything on its own); GLW's Overall flips Fail (68) → Pass (72).
- **`AR_EXEMPT_TYPES` extension (2026-09-04)**, before/after on real cached tickers: JPM (Bank)
  65/Fail → 85/Pass; MET/PRU (Insurance) 33/Fail → 60/Fail; DUK (Utility) 51/Fail → 60/Fail; SO
  (Utility) 64/Fail → 60/Fail (AR was pulling its blend *up* — an expected consequence of the
  reweighting, not a regression). REITs (O, PLD) were already exempt and are unaffected.
