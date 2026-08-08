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

Each of these three series is run through a shared trend classifier
(`scoring/trend.py::classify_trend`) — not local to this check: the same
function backs Step 3's method-selection tree and Step 4's ROE/ROIC
recovery-aware exclusion. Given a chronological series of at least 2
points:

1. Compute period-over-period percent changes. A decline steeper than
   **-5%** counts as a "real" dip; anything shallower is noise.
2. **Severe TTM decline override**: if the final transition (into TTM) is
   a decline steeper than **-15%**, the result is **`declining`, score
   0**, unconditionally — this overrides everything else in the series'
   history. A milder TTM decline (between -5% and -15%) no longer
   triggers this override as of **2026-08-08** — it flows through as an
   ordinary dip transition, subject to the same merge/resolution logic as
   any other dip (steps 4-7 below), instead of a flat, age-blind cutoff.
   Before this change, any real TTM decline forced `declining`/0
   regardless of history; confirmed dragging ~12 tickers (APTV, PHM,
   FISV, HCA, PCG, TSCO, etc.) from Pass to Fail on a single mild (5-15%)
   TTM wobble after an otherwise long, clean growth run.
3. **Zero real dips** → `grows_every_year`, **100**.
4. **Flat-then-spike check** (2+ real dips only, checked before dip-event
   resolution): if the window before the final point is flat (the total
   move from the first point to the second-to-last point is under 10%)
   and the final transition is a jump greater than **25%**, this is
   narrowed by one more condition as of **2026-08-08** — it only fires if
   even the *robust* late-window average (the single most extreme point
   excluded before averaging, same convention as Margins/CCC) shows no
   more than **10%** improvement over the early window. If the robust
   average shows more improvement than that, the series falls through to
   ordinary dip-event resolution (steps 5-7) instead. Otherwise →
   `flat_then_spike`, **20**. (Before this change, the flat-vs-spike test
   was a bare 2-point comparison — `arr[0]` vs `arr[-2]` — that could miss
   a genuine multi-year improvement sitting just behind a terminal spike.)
5. **Contiguous real-dip transitions merge into one dip event** as of
   **2026-08-08**. A multi-year decline (e.g. HWM's 2018→2021 Revenue
   collapse — three consecutive declining transitions) is one real
   economic event needing one recovery, not three independent dips each
   needing their own. A non-declining (or sub-noise-floor) transition
   between two declines still keeps them as separate events. Each event's
   own baseline ("effective pre-dip value") is normally the value
   immediately before it, but if *that* value was itself produced by a
   single-year jump of **100% or more**, it's treated as an unreliable
   spike, and the value from before the jump is used instead — unchanged
   from before.
6. **Each event resolves either**:
   - **literally** — the current (TTM) value is at least as large as the
     event's own baseline; or
   - **durably**, as of **2026-08-08** — all three of: the event's trough
     is at least **4 periods** old; the trailing run of consecutive
     non-dip transitions counting back from TTM is at least **3
     periods**; and the recovery segment (trough through TTM) shows a
     non-negative robust late-window direction (same robust-average
     convention as step 4 above). Before this, only literal recovery
     counted, with no age-awareness at all — an old, since-recovered dip
     could permanently cap a series at `multiple_dips`/40 even after 5+
     clean recovery years, simply because TTM never re-cleared a
     possibly-structural old peak. Motivating case: HWM's Revenue has a
     2018 pre-Arconic-split peak of $14.02B, never re-cleared despite 6
     clean growth years since the 2021 trough.
   - If **any** event in the series resolves neither way → `multiple_dips`,
     **40**.
7. **Once every event has resolved**:
   - **Exactly one event, resolved literally**: graded by severity — a
     genuine single-transition event reads its severity directly off that
     transition's own percent change; a merged (multi-transition) event
     reads it off the aggregate baseline-vs-trough magnitude instead, since
     no single transition represents the whole run. **≤10%** →
     `small_dip_recovers`, **90**. **>10%** → `significant_dip_recovers`,
     **85**.
   - **Two or more events, all resolved literally** → `multiple_dips_resolved`,
     **75** — regardless of how recently the most recent one happened
     (unchanged from before).
   - **At least one event resolved only via the durable path** (new) →
     `dip_durably_resolved`, **75** — same score as
     `multiple_dips_resolved`, kept as a distinct pattern purely so the
     reasoning panel can say "durably improved, not yet a new high"
     rather than implying TTM reached a literal new peak.
8. Fewer than 2 data points → `insufficient_data`, score 0 (see the
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
  - If that run ended **within the last 3 periods**, check first (as of
    **2026-08-08**) whether it's **capex-driven, not distress**: CFO
    stayed positive throughout the entire run (every value, not just the
    endpoints) and non-declining (last ≥ first). If so →
    `capex_driven_negative_fcf`, **85** — there was never a cash crisis
    for the recency gate below to be protecting against. Confirmed real
    shape for regulated utilities (AEP, DUK, ED, ES, FE, SO): FCF negative
    for years on heavy rate-base capex while CFO stayed comfortably
    positive and growing the entire time. Otherwise → `sustained_cash_burn`,
    **0** — too recent to trust as resolved, fails outright. (This
    capex-driven check only applies to a run ending within the last 3
    periods — an older run that isn't capex-driven still falls through to
    the recovery check below, unchanged.)
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
