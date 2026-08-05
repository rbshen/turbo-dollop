# Financials

Technical reference for the Financials check (the "Financials" card on the
Analysis tab). Scores whether Revenue, Net Income, Cash From Operations
(CFO), Margins, and Free Cash Flow (FCF) are growing and, where
applicable, currently positive. This is a continuous weighted blend, not
a discrete pass/fail tally on each metric.

## Data window

10 most recent annual fiscal years, plus a TTM (trailing twelve months)
column computed as the sum of the 4 most recent reported quarters. All
series are chronological, oldest fiscal year first, ending with TTM.

## Weights

| Metric | Standard weight | CFO-exempt weight |
|---|---|---|
| Revenue | 35% | 46.67% |
| Net Income | 20% | 31.67% |
| CFO | 30% | 0% |
| Margins | 10% | 21.67% |
| FCF | 5% | 0% |

When a company is CFO-exempt (see below), CFO's and FCF's combined 35%
weight is redistributed in equal thirds (+11.67 points each) across
Revenue, Net Income, and Margins, rather than being dropped from the
denominator.

Final score = weighted sum of the 5 (or 3) component scores, rounded and
clamped to [0, 100].

## Company-type exemption (CFO / FCF)

Cash From Operations and Free Cash Flow are skipped for:

- **Bank**
- **Insurance**
- **Property Developer** (the shared REIT/Property Developer classifier)
- **Commodity Company** — sector is `Basic Materials` or `Energy`. This is
  a category specific to this check; it has no equivalent in the shared
  company-type classifier used by Profitability, Debt, and Valuation.

Bank/Insurance/Property Developer are detected via the same shared
sector/industry classifier the other checks use. Commodity Company is
detected locally by sector text alone.

**Bank-only substitution:** the series scored and displayed as "Revenue"
for a Bank is actually **Net Interest Income** (FMP's `netInterestIncome`
field), not total revenue — FMP's raw Revenue field for banks mixes
interest and non-interest income in a way that obscures the core
lending-spread trend. This substitution affects only the Revenue metric.
Margins are always computed from real Revenue and Gross Profit, regardless
of company type, including for Banks.

## Trend classification (Revenue, Net Income, CFO)

Each of these three series is run through a shared trend classifier.
Given a chronological series of at least 2 points:

1. Compute period-over-period percent changes. A decline steeper than
   **-5%** counts as a "real" dip; anything shallower is noise.
2. If the **final** transition (into TTM) is a real decline (steeper than
   -5%), the result is **`declining`, score 0**, unconditionally — this
   overrides everything else in the series' history. TTM must confirm the
   trend, not undermine it.
3. **Zero real dips** → `grows_every_year`, **100**.
4. **Exactly one real dip**: compare the current (TTM) value against the
   dip's "effective pre-dip value" — normally the value immediately before
   the dip, but if *that* value was itself produced by a single-year jump
   of **100% or more**, it's treated as an unreliable spike rather than a
   genuine baseline, and the value from before the spike is used instead.
   - If TTM has not recovered to at least that baseline → `multiple_dips`,
     **40**.
   - If recovered, and the dip itself was **≤10%** → `small_dip_recovers`,
     **90**.
   - If recovered, and the dip was **>10%** → `significant_dip_recovers`,
     **85**.
5. **Two or more real dips**:
   - Special case first: if the window before the final point is flat
     (the total move from the first point to the second-to-last point is
     under 10%) and the final transition is a jump greater than **25%** →
     `flat_then_spike`, **20**.
   - Otherwise, check every real dip's own effective pre-dip value (same
     spike-aware baseline as step 4) against the current TTM value. If
     **any** dip hasn't recovered past its own baseline → `multiple_dips`,
     **40**. If **all** dips have recovered → `multiple_dips_resolved`,
     **75** — regardless of how recently the most recent dip occurred.
6. Fewer than 2 data points → `insufficient_data`, score 0 (see the
   insufficient-data section below for how this propagates).

## Positivity gate (Revenue, Net Income, CFO)

The trend classifier above is purely relative — it only asks whether a
series has grown or recovered relative to its own prior points, never
whether the values are actually positive. On top of it, Revenue, Net
Income, and CFO each require the **current (TTM) value to be positive**:

- If the trend classifier already returned `insufficient_data`, this gate
  is skipped (the insufficient-data result passes through unchanged).
- Otherwise, if the TTM value is **≤ 0**, the result is overridden to
  `not_yet_positive`, **score 0**, regardless of what the relative trend
  pattern says.
- Otherwise, the trend classifier's own tier (from the previous section)
  is used unchanged. A historical dip — even one that went negative
  mid-dip — is still tolerated as long as the series has since recovered
  and the current value clears zero.

## Net Income's Operating Income backup

If Net Income's positivity-gated score is **≤ 40**, Operating Income is
consulted as a backup signal — but only when the disqualifying dip is
recent enough to plausibly be a one-off:

- Compute the age (in periods before TTM, 0 = the TTM transition itself)
  of Net Income's most recent real dip (steeper than -5% YoY).
- If Net Income itself read `insufficient_data` (no notion of recency at
  all), the backup is always consulted.
- Otherwise, the backup is only consulted if that dip's age is **≤ 2
  periods**.
- When consulted: Operating Income is run through the same trend
  classifier + positivity gate as Net Income. The final Net Income score
  becomes `min(80, max(Net Income's own score, Operating Income's
  score))` — capped at 80 even if Operating Income alone would score
  higher, and never lower than Net Income's own unrescued score.
- If the dip is older than 2 periods, Operating Income is never consulted
  — Net Income's own (unrescued) score stands, regardless of how strong
  Operating Income looks.

## Margins classification

Inputs: the gross margin and net margin series (percentage-point values,
same 10yr+TTM window), plus a `revenue_growing` flag — TTM real Revenue
greater than the earliest real Revenue value in the window. This flag is
always computed from real Revenue, even for Banks (whose scored "Revenue"
metric is Net Interest Income) — margins are judged against the real
top-line trend regardless.

Each of gross margin and net margin is independently run through a
windowed direction analysis:

- **window** = min(3, series length) periods.
- **direction** = (average of the last `window` periods) − (average of the
  first `window` periods).
- **real dip count** = number of period-over-period drops steeper than
  **2.0 percentage points**.
- **sustained decline** = true if any run of **2 consecutive** down-periods
  sums to more than **5.0 percentage points** of total decline.

Classification (checked in this order):

1. **If gross OR net shows a sustained decline:**
   a. If net margin's direction is worse than **-5.0pp** and revenue is
      growing → `sharply_declining`, **20**. This check always runs
      first, regardless of recovery status — a currently sharply-negative
      net margin is never excused by an unrelated gross-margin recovery.
   b. Otherwise, check whether the decline has durably reversed on
      **both** series: a series counts as "recovered" if it has no
      sustained decline at all, or if its direction is non-negative
      (≥ -1.0pp) **and** its current (TTM) value has climbed back to at
      least its own early-window average. If **either** series hasn't
      recovered → `gradually_compressing`, **60**.
   c. If both have recovered: check whether both series are also
      "stable and spike-robust" — direction ≥ -1.0pp on both, **and** a
      robust late-window direction (the single most extreme late-window
      point excluded before averaging) is also ≥ -1.0pp on both. If so →
      `stable_or_expanding`, **100**. Otherwise → `gradually_compressing`,
      **60**.
2. **Otherwise (no sustained decline in either series):**
   a. If **both** gross and net show 2+ real dips **and** each series'
      direction is flatter than **1.0pp** in magnitude →
      `wildly_inconsistent`, **0**. (Requires both series to show the
      pattern — one choppy series can't veto an unambiguously improving
      other series.)
   b. Otherwise, if both series are "stable and spike-robust" (same test
      as 1c) → `stable_or_expanding`, **100**.
   c. Otherwise, if net margin's direction is worse than -5.0pp and
      revenue is growing → `sharply_declining`, **20**.
   d. Otherwise → `gradually_compressing`, **60**.

Fewer than 2 points in either series → `insufficient_data`, score 0.

## Free Cash Flow classification

FCF = CFO + `capitalExpenditure` (FMP reports capital expenditure as
already negative, so this adds a negative number rather than double-
subtracting it).

- Fewer than 2 points → `insufficient_data`, score 0.
- **Zero negative years** → `consistently_positive`, **100**.
- Otherwise, find every run of **2 or more consecutive** negative years
  and note where the most recent such run ends:
  - If that run ended **within the last 3 periods** → `sustained_cash_burn`,
    **0** — too recent to trust as resolved, fails outright.
  - If it ended more than 3 periods ago, the run is excused as resolved
    if **either**:
    - the full series (including TTM) reads as one of the trend
      classifier's own recovery patterns (`grows_every_year`,
      `small_dip_recovers`, `significant_dip_recovers`,
      `multiple_dips_resolved`); **or**
    - a separate durable-recovery check passes: every year after the run
      ended (including TTM) is non-negative, **and** dropping TTM from
      the series still reads as a recovery pattern on its own, **and**
      TTM is at least as large as the average of the (up to) 3 periods
      immediately following the burn.
  - If excused → `cash_burn_recovered`, **85**. If not → still
    `sustained_cash_burn`, **0**.
- If there's no qualifying 2+-year run at all: exactly one negative year
  → `isolated_dip`, **85**; two or more negative years that are never
  consecutive → `scattered_negative_years`, **60**.

## Verdict bands

| Score | Verdict |
|---|---|
| 91–100 | Strong Pass |
| 70–90 | Pass |
| 0–69 | Fail |

## Insufficient data

The whole check returns `score: null, verdict: "insufficient_data"` (not
a fabricated Fail) if any of the following read `insufficient_data`:
Revenue, Margins, CFO (when not exempt), FCF (when not exempt), or **both**
Net Income and its Operating Income backup. Net Income alone reading
`insufficient_data` is not a gap as long as Operating Income has real
data — the backup mechanism above already produces a legitimate score in
that case.
