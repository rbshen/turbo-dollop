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

**No-inventory detection** is data-driven, independent of company type: if inventory reads null
or zero across *every* one of the 10 annual filings (the TTM/latest-quarter figure is
deliberately excluded — it has proven unreliable for genuinely inventory-free companies), CCC is
skipped regardless of sector/industry.

### Blend weights

| Metric | Base weight (all 4 applicable) |
|---|---|
| ROIC | 35% |
| ROE | 25% |
| Revenue vs. AR | 20% |
| CCC | 20% |

When a metric is exempt, its weight is redistributed **proportionally** (not equally) across the
remaining applicable metrics. Worked examples: ROIC + CCC + AR exempt (Bank/Insurance/Utility) →
ROE alone at 100%. REIT (AR + ROIC + CCC all exempt) → ROE alone at 100%.

This is a deliberate design choice (2026-08-01), not a bug-driven fix: ROIC is weighted above ROE
since it's harder to game and reflects capital efficiency more directly; Revenue-vs-AR and CCC
are corroborating/contradicting supporting evidence, weighted lower and equal to each other.

### ROE and ROIC tiering

Both metrics share the same tiering logic, applied independently to each series (10yr+TTM):

1. **Spike-robust average**: the plain average of the series, except the series **maximum** is
   excluded if it's at least **2×** the median of the remaining points. The series **minimum** is
   never excluded.
2. **Minimum-year consistency check**: the single worst year must also clear the tier's own
   floor. A worst year at or above **8%** always satisfies this. A worst year below 8% still
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
comfortably strong. Before computing the average (spike-robust or otherwise), any **resolved dip
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
  classification).
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
   TRANSITION_RATIO`, generalizing the original "3 of 5" transitions rule to any window size),
   **or** any single transition's gap is "large" (> 50pp) — **and** at least one of the
   transitions driving that trigger falls within the most recent 3 → `outpacing_concerning`,
   **40**.
3. Zero outpacing transitions, or exactly one outpacing transition with a "small" gap →
   `healthy`, **100**.
4. Otherwise → `outpacing_isolated`, **70**.

Fewer than 1 transition, or mismatched Revenue/AR series lengths → `insufficient_data`, **0**.

Whenever Revenue-vs-AR lands in any non-healthy tier, a dynamically-computed manual-check note
(built from Operating Cash Flow, which isn't part of the AR score itself) states which
comparison actually drove the flag, plus whether OCF is tracking Net Income over the same window.

### Cash Conversion Cycle

```
DIO (Days Inventory Outstanding)   = Inventory / COGS × 365
DSO (Days Sales Outstanding)       = Accounts Receivable / Revenue × 365
DPO (Days Payable Outstanding)     = Accounts Payable / COGS × 365
CCC = DIO + DSO − DPO
```

A period is skipped entirely (not zero-filled) if Revenue or COGS is missing/zero, or if
Inventory, AR, or AP is missing.

Classification dispatches first on the **sign profile** of the full CCC series:

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
     (`CCC_NEAR_ZERO_AMPLITUDE_DAYS`) → `negligible_working_capital`, **85**. Otherwise →
     `mixed_unclear`, **40**.

**Windowed trend logic (consistently-positive case)**, applied so that a *declining* CCC (faster
cash conversion, desirable) reads as improvement:

- window = 3 periods; a real move is one larger than **3 days**; a "sustained worsening" is 2
  consecutive periods where CCC rises, totaling more than **5 days**.
- direction = (early-window average) − (late-window average); positive means CCC declined
  (improved).
- If sustained worsening occurred **and** the overall direction is still net negative (worse than
  **-1 day**) → `sustained_upward`, **graduated**.
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

- **Fail** if `hard_fail` is true — regardless of the blended score.
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
