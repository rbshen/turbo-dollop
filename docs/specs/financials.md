# Financials

The Financials card (the "Financials" card on the Analysis tab) looks at whether a company's
core financial results — the money it brings in, keeps, and generates in cash — are growing in a
healthy, sustainable way. It scores five things together as a continuous weighted blend, not a
discrete pass/fail tally on each metric:

- **Revenue** — the total sales the company generates. If revenue isn't growing, the underlying
  business isn't growing either, no matter what else looks good.
- **Net Income** — the company's bottom-line profit after all expenses, taxes, and one-off
  items. This is the most commonly cited profit figure, but it's also the easiest to distort
  with one-time gains or charges, so it's checked alongside the other four rather than on its
  own.
- **Cash From Operations (CFO)** — the actual cash the business generated from running its
  operations, separate from accounting profit. A company can report a profit on paper while not
  generating real cash, so this is treated as more trustworthy than Net Income alone.
- **Margins** — gross margin and net margin, i.e. how much of each dollar of revenue the company
  actually keeps after costs. Stable or improving margins suggest pricing power and cost
  discipline; margins that are steadily eroding are a warning sign even if revenue is still
  growing.
- **Free Cash Flow (FCF)** — cash left over after the company pays for its own capital
  investments. This is checked mainly for whether it stays positive, since a sustained
  multi-year run of cash burn is a real bankruptcy-risk signal.

It's not enough for Revenue, Net Income, and CFO to be trending in the right direction — they're
also checked for whether they're currently positive. A company whose losses are merely getting
smaller year over year, but still hasn't turned a profit, is not treated the same as one that
has genuinely turned the corner into profitability. A temporary dip that has since fully
recovered is tolerated; a business that has never actually been profitable is not.

Cash From Operations and Free Cash Flow don't mean the same thing for every kind of business.
For **Banks, Insurance companies, Property Developers, and Commodity companies**, these two
checks are skipped, and the company is judged on Revenue, Net Income, and Margins instead (with
those three carrying proportionally more weight to make up for it). See
[Company type variations](company-type-variations.md) for the full picture, and the technical
reference below for exact weights and thresholds.

## Data window

10 most recent annual fiscal years, plus a TTM (trailing twelve months) column computed as the
sum of the 4 most recent reported quarters. All series are chronological, oldest fiscal year
first, ending with TTM.

## Weights

| Metric | Standard weight | CFO-exempt weight |
|---|---|---|
| Revenue | 35% | 46.67% |
| Net Income | 20% | 31.67% |
| CFO | 30% | 0% |
| Margins | 10% | 21.67% |
| FCF | 5% | 0% |

When a company is CFO-exempt, CFO's and FCF's combined 35% weight is redistributed in equal
thirds (+11.67 points each) across Revenue, Net Income, and Margins, rather than being dropped
from the denominator.

Final score = weighted sum of the 5 (or 3) component scores, rounded and clamped to [0, 100].

## Company-type exemption (CFO / FCF)

Cash From Operations and Free Cash Flow are skipped for:

- **Bank**
- **Insurance**
- **Property Developer** (the shared REIT/Property Developer classifier)
- **Commodity Company** — sector is `Basic Materials` or `Energy`. This is a category specific
  to this check; it has no equivalent in the shared company-type classifier used by
  Profitability, Debt, and Valuation.

Bank/Insurance/Property Developer are detected via the same shared sector/industry classifier
the other checks use. Commodity Company is detected locally by sector text alone.

**Bank-only substitution:** the series scored and displayed as "Revenue" for a Bank is actually
**Net Interest Income** (FMP's `netInterestIncome` field), not total revenue — FMP's raw Revenue
field for banks mixes interest and non-interest income in a way that obscures the core
lending-spread trend. This substitution affects only the Revenue metric. Margins are always
computed from real Revenue and Gross Profit, regardless of company type, including for Banks.

## Trend classification (Revenue, Net Income, CFO)

Each of these three series is run through a shared trend classifier
(`scoring/trend.py::classify_trend`) — not local to this check: the same function backs Step 3's
method-selection tree and Step 4's ROE/ROIC recovery-aware exclusion. Given a chronological
series of at least 2 points:

1. Compute period-over-period percent changes. A decline steeper than **-5%** counts as a "real"
   dip; anything shallower is noise.
2. **Severe TTM decline override**: if the final transition (into TTM) is a decline steeper than
   **-15%**, the result is **`declining`**, unconditionally — this overrides everything else in
   the series' history. A milder TTM decline (between -5% and -15%) flows through as an ordinary
   dip transition, subject to the same merge/resolution logic as any other dip (steps 4-7 below)
   instead of a flat, age-blind cutoff.
   **`declining`'s own score is graduated (2026-08-13)**: it scales linearly from **15** points
   (just past -15%) down to **0** (at a **-50%** decline or worse) — a company down 15.2% no
   longer reads identically to one down 92%. This graduated score only affects Step 1's own
   Revenue/Net Income/Operating Income/CFO scoring (via `_classify_positive_trend` below); every
   other consumer of this shared function only tests pattern membership in the recovery-patterns
   set, never the raw score, and `declining` was never in that set either way.
3. **Zero real dips** → `grows_every_year`, **100**.
4. **Flat-then-spike check** (2+ real dips only, checked before dip-event resolution): if the
   window before the final point is flat (the total move from the first point to the
   second-to-last point is under 10%) and the final transition is a jump greater than **25%**,
   this is narrowed by one more condition: it only fires if even the *robust* late-window average
   (the single most extreme point excluded before averaging, same convention as Margins/CCC)
   shows no more than **10%** improvement over the early window. If the robust average shows
   more improvement than that, the series falls through to ordinary dip-event resolution (steps
   5-7) instead. Otherwise → `flat_then_spike`, **20**.
   **The robust-average computation is jump-magnitude-gated**: TTM is only *protected* from being
   excluded as the late window's own outlier (`protect_terminal=True`) when the jump into it is
   **100% or less** (`DIP_BASELINE_SPIKE_RATIO`) — a modest, plausible jump gets trusted; a jump
   with no precedent anywhere in the series' history still doesn't.
5. **Contiguous real-dip transitions merge into one dip event.** A multi-year decline (e.g. a
   3-year revenue collapse) is one real economic event needing one recovery, not three
   independent dips each needing their own. A non-declining (or sub-noise-floor) transition
   between two declines still keeps them as separate events. Each event's own baseline ("effective
   pre-dip value") is normally the value immediately before it, but if *that* value was itself
   produced by a single-year jump of **100% or more**, the value from before the jump is used
   instead.
6. **Each event resolves either**:
   - **literally** — the current (TTM) value is at least as large as the event's own baseline; or
   - **durably** — all three of: the event's trough is at least **4 periods** old; the trailing
     run of consecutive non-dip transitions counting back from TTM is at least **3 periods**; and
     the recovery segment (trough through TTM) shows a non-negative robust late-window direction.
   - If **any** event in the series resolves neither way → `multiple_dips`, **graduated
     (2026-09-10)**, see below.
7. **Once every event has resolved**:
   - **Exactly one event, resolved literally**: graded by severity — **≤10%** →
     `small_dip_recovers`, **90**; **>10%** → `significant_dip_recovers`, **85**.
   - **Two or more events, all resolved literally** → `multiple_dips_resolved`, **graduated
     75 → 65** (see "`multiple_dips_resolved` / `dip_durably_resolved` graduated" below; 75 is
     the ceiling).
   - **At least one event resolved only via the durable path** → `dip_durably_resolved`,
     **graduated 75 → 65**, scored by the identical formula as `multiple_dips_resolved` — kept
     distinct purely so the reasoning panel can say "durably improved, not yet a new high" rather
     than implying a literal new peak.
8. Fewer than 2 data points → `insufficient_data`, score 0 (see "Insufficient data" below).

**`multiple_dips` graduated (2026-09-10).** A flat 40 for ANY unresolved dip event regardless of
how close to recovery TTM actually is used to conflate a dip 0.1% from its own baseline with one
thousands of percent below it. Now graduates linearly between `MULTIPLE_DIPS_FLOOR` (40, the old
flat value, preserved as the worst-case floor) and `MULTIPLE_DIPS_CEILING` (70) as `shortfall_frac`
— `(baseline − TTM) / abs(baseline)` — moves from 0% to `MULTIPLE_DIPS_SEVERE_FRAC` (30%). A
mandatory companion fix raised `NET_INCOME_BACKUP_THRESHOLD` from 40 to 70 (see "Net Income's
Operating Income backup" below) so a mildly-graduated NI score doesn't silently fall outside the
backup's own trigger range.

**`multiple_dips_resolved` / `dip_durably_resolved` graduated (2026-09-10, "bucket b").** Both
patterns used to score a flat 75 however severe the historical, now-recovered dip was. They now
graduate linearly from `RESOLVED_CEILING` (**75**, the old flat value — this bucket has no upward
headroom, so graduation can only ever lower a score) down to `RESOLVED_FLOOR` (**65**) as the
worst event's severity approaches `RESOLVED_SEVERE_FRAC` (**1.0**, i.e. 100% of current scale).
Severity is dip **depth relative to the series' current (TTM) scale**, not peak-relative percent:
`max over events of |baseline − trough| / |TTM|`, clipped to `RESOLVED_SEVERE_FRAC`
(`_graduated_resolved_score`; `RESOLVED_FLOOR` if TTM is 0 or there are no events). Peak-relative
% is meaningless when a dip's baseline is a tiny or negative pre-scale number, whereas depth
against today's scale stays well-behaved for a near-zero baseline. Every `RECOVERY_PATTERNS`
membership test (Step 1's FCF recovery check, Step 3's method-selection tree ×2, Step 4's
ROE/ROIC recovery checks ×2 — 6 call sites) tests `.pattern` only and is unaffected by the
score-value change. Note that a resolved score of 65–70 now falls at or under
`NET_INCOME_BACKUP_THRESHOLD`, so a Net Income read of that shape can consult the Operating
Income backup (subject to its recency gate).

## Positivity gate (Revenue, Net Income, CFO)

The trend classifier above is purely relative — it only asks whether a series has grown or
recovered relative to its own prior points, never whether the values are actually positive. On
top of it, Revenue, Net Income, and CFO each require the **current (TTM) value to be positive**:

- If the trend classifier already returned `insufficient_data`, this gate is skipped.
- Otherwise, if the TTM value is **≤ 0**, the result is overridden to `not_yet_positive`,
  regardless of what the relative trend pattern says. **The score is graduated (2026-08-13)**:
  measured as a margin (`value ÷ real revenue × 100`, using real revenue even for Banks), scaled
  linearly from **15** points (at 0% margin) down to **0** (at **-20%** margin or worse). Falls
  back to a flat 0 if no revenue figure is available to normalize against.
- Otherwise, the trend classifier's own tier is used unchanged. A historical dip — even one that
  went negative mid-dip — is still tolerated as long as the series has since recovered and the
  current value clears zero.

The gate lives in `scoring/step1.py::_classify_positive_trend` (with `_not_yet_positive_result`
doing the graduated score; the real-revenue series is passed in as `revenue_for_scale`). It is
deliberately a **Financials-local wrapper, not a change to the shared primitive**:
`classify_trend`, `RECOVERY_PATTERNS`, and every other consumer (Valuation's method-selection tree,
Profitability's ROE negative-equity substitute, `_classify_fcf`'s own cash-burn-recovery logic) are
untouched, and no other step calls `_classify_positive_trend`. It deliberately does **not**
tighten `classify_trend`'s recovery math — only the current value's sign is new. A
currently-positive but historically sign-flipping series (e.g. a CFO that flipped sign several
times before settling positive for the last two periods) still scores
`multiple_dips_resolved`, unchanged.

## Net Income's Operating Income backup

If Net Income's positivity-gated score is **≤ `NET_INCOME_BACKUP_THRESHOLD` (70, raised from 40
on 2026-09-10 as a companion to the `multiple_dips` graduation above)**, Operating Income is
consulted as a backup signal — but only when the disqualifying dip is recent enough to plausibly
be a one-off:

- Compute the age (in periods before TTM, 0 = the TTM transition itself) of Net Income's most
  recent real dip (steeper than -5% YoY).
- If Net Income itself read `insufficient_data`, the backup is always consulted.
- Otherwise, the backup is only consulted if that dip's age is **≤ 2 periods**
  (`NET_INCOME_BACKUP_RECENCY_YEARS`).
- When consulted: Operating Income is run through the same trend classifier + positivity gate as
  Net Income. The final Net Income score becomes `min(80, max(Net Income's own score, Operating
  Income's score))` — capped at 80 even if Operating Income alone would score higher, and never
  lower than Net Income's own unrescued score.
- If the dip is older than 2 periods, Operating Income is never consulted.

Why it is recency-gated: the backup exists for a plausible one-off (a charge that hit 1–2 periods
ago), not for a chronic, long-unresolved Net Income problem. The age is computed by
`scoring/trend.py::most_recent_real_dip_age`, and the window deliberately **includes age 0** (the
dip landing in the TTM transition itself) — excluding it would mean the most common one-off shape,
a charge in the latest reported period, could never qualify. Net Income having too few points for
any notion of recency (`insufficient_data`) still unconditionally consults Operating Income.

`NET_INCOME_BACKUP_THRESHOLD` must equal `trend.MULTIPLE_DIPS_CEILING` (enforced by
`scoring/test_step1.py::test_net_income_backup_threshold_matches_multiple_dips_ceiling`). The
backup gate is an exact-value comparison against `classify_trend`'s own output — unlike the
`RECOVERY_PATTERNS` consumers, which test pattern membership and are immune to score-value
changes — so a graduated `multiple_dips` score above the threshold would silently lose an
Operating-Income rescue it would otherwise still get.

## Margins classification

Inputs: the gross margin and net margin series (percentage-point values, same 10yr+TTM window),
plus a `revenue_growing` flag — TTM real Revenue greater than the earliest real Revenue value in
the window. This flag is always computed from real Revenue, even for Banks (whose scored
"Revenue" metric is Net Interest Income).

Each of gross margin and net margin is independently run through a windowed direction analysis.
This deliberately uses windowed early-vs-late direction plus explicit dip-count and
sustained-decline checks, **not** a raw standard-deviation-of-differences volatility check — a
single big dip-and-full-recovery year produces high variance but must not read as "wildly
inconsistent":

- **window** = min(3, series length) periods.
- **direction** = (average of the last `window` periods) − (average of the first `window`
  periods).
- **real dip count** = number of period-over-period drops steeper than **2.0 percentage points**.
- **sustained decline** = true if any run of **2 consecutive** down-periods sums to more than
  **5.0 percentage points** of total decline.

Classification (checked in this order):

1. **If gross OR net shows a sustained decline:**
   a. If net margin's direction is worse than **-5.0pp** and revenue is growing →
      `sharply_declining`, **20** — checked first, regardless of recovery status. "Net margin's
      direction" here means `max(direction, robust_early_direction)`, not the raw windowed
      direction alone — `robust_early_direction` excludes the single most extreme early-window
      point (vs. that window's own median) before averaging, guarding against a single anomalous
      early-window spike making a genuinely-recovered series read as sharply declining. `max()`
      is load-bearing: the exclusion is symmetric by construction, so it could otherwise rescue a
      genuine low early trough, which would make the reading *more* negative — `max()` makes the
      fix strictly one-directional. `robust_early_direction`
      (`scoring/series_trend.py`) mirrors `robust_late_direction`, applied to the early window,
      and is used at **this one call site only**: `direction` itself, `_series_recovered`,
      `_stable_and_spike_robust`, Rule 2, and Rule 2's own separate `sharply_declining` check
      (2c) are untouched. It is never a drop-in replacement for `direction` — an unguarded
      version wrongly collapsed genuine low-early-trough cases (an oil-crash-year trough excluded
      → `stable_or_expanding`/100 read as `sharply_declining`/20).
   b. Otherwise, a series counts as "recovered" if it has no sustained decline at all, or if its
      direction is non-negative (≥ -1.0pp) **and** its current (TTM) value has climbed back to at
      least its own early-window average. (The baseline is deliberately the early-window
      *average* `direction` itself is measured against, not the single pre-decline value, which is
      frequently an anomalous spike — requiring re-exceedance of a spike would leave genuine
      recoveries capped forever. Without this gate, a sustained decline occurring once anywhere in
      the 10yr+TTM window, e.g. FY2020, permanently capped a fully-recovered company.) If
      **either** series hasn't recovered → `gradually_compressing`, **60** (graduated, see below).
   c. If both have recovered: check whether both are also "stable and spike-robust" — direction
      ≥ -1.0pp on both, **and** a robust late-window direction is also ≥ -1.0pp on both. If so →
      `stable_or_expanding`, **100**. Otherwise → `gradually_compressing`, **60** (graduated,
      see below). This branch reads straight off the stable/expanding check and deliberately does
      **not** fall through to Rule 2 — Rule 2's per-series dip-count logic has its own known
      issues (below) and would turn a confirmed recovery into the worst tier for a
      near-flat-but-positive ticker.
2. **Otherwise (no sustained decline in either series):**
   a. If **both** gross and net show 2+ real dips **and** each series' direction is flatter than
      **1.0pp** in magnitude → `wildly_inconsistent`, **0**.
   b. Otherwise, if both series are "stable and spike-robust" (same test as 1c) →
      `stable_or_expanding`, **100**.
   c. Otherwise, if net margin's direction is worse than -5.0pp and revenue is growing →
      `sharply_declining`, **20**.
   d. Otherwise → `gradually_compressing`, **60**.

Fewer than 2 points in either series → `insufficient_data`, score 0.

**Known, unfixed issues (Rule 2's `wildly_inconsistent` trigger):** Rule 2 fires independently
per-series (gross OR net), so a company with one genuinely choppy series and one clearly,
strongly improving series can still land on the worst possible score. Separately, the 2-point
absolute dip threshold isn't scaled to a company's margin level, so naturally low-margin
businesses can trip it on ordinary noise. Both deferred pending a follow-up investigation.

**Bank Margins exemption (2026-09-10).** A Bank's `gross_margin`/`net_margin` is computed from
the same raw `grossProfit`/`revenue` GAAP line already swapped out for Net Interest Income
elsewhere in Step 1 — it isn't a coherent concept for a lending institution, confirmed via a
full-universe scan showing all 28 Bank-classified tickers hitting an FMP data-methodology
artifact (an implausible ≥100% "gross margin" spike around FY2021, then a permanent plateau
drop). `MARGINS_EXEMPT_TYPES = {"Bank"}`: `Step1Out.components.margins = None`, and Margins'
`WEIGHTS_CFO_EXEMPT`-stage weight (13/60, ~21.67%) is redistributed **proportionally** across
Revenue and Net Income (new weight table `WEIGHTS_CFO_MARGINS_EXEMPT`, `scoring/step1.py`),
preserving their existing 28:19 ratio — Revenue 28/47 (~59.57%), Net Income 19/47 (~40.43%) —
rather than a flat 50/50 split. `MARGINS_EXEMPT_TYPES` lives in `data/step1_data.py`; the mechanism
is the same as the CFO/FCF exemption. Deliberately scoped to Bank only — Insurance and Commodity Company margins were
found mostly working, and REIT/Property Developer's own margin noise is a differently-shaped
(terminal-period collapse, not universal mid-history spike) issue not fixed here.
`MARGINS_SEVERITY_CARVEOUT_TYPES = {"Insurance", "REIT/Property Developer", "Utility"}` keeps
`gradually_compressing` at a flat 60 regardless of severity for those three types (see
`gradually_compressing` severity graduation below) — Bank is not in this set since it never
reaches `_classify_margins` at all once excluded above (`carveout=True` is accepted there as a
defensive no-op, not expected to gate a Bank in practice). The carve-out flag is computed in
`data/step1_data.py` from `classify_company_type`'s own **raw** return value, not
`_detect_exemption`'s remapped one — `_detect_exemption` renames "REIT/Property Developer" to
"Property Developer" for Step 1's display and never surfaces "Utility" at all (Utility was never
CFO-exempt in Step 1, but does need this Margins-only carve-out independently).

**Reasoning text.** The Financials card's verdict sentence is fully dynamic (it filters on
whichever component keys are non-null), so a Bank's blurb automatically stops mentioning Margins
once `components.margins` is `None`. The exemption note is built by
`exemptionNote()` (`frontend/components/step1/Step1Card.tsx`) from whichever of `{cfo, fcf,
margins}` are actually null, with `isn't`/`aren't` agreement — a Bank reads "Cash Flow, Margins,
and Free Cash Flow aren't scored for this company — classified as a Bank."; every other exempt
type reads "Cash Flow and Free Cash Flow aren't scored…".

**`gradually_compressing` severity graduation (2026-09-10), gentle by design.** `MARGINS_CEILING`
= 60 (matches the old flat value, no upward headroom — this bucket can only ever lower some
tickers' scores), graduating down to `MARGINS_FLOOR` = 45 as the worse of gross/net `direction`
passes `MARGINS_SEVERE_PP` (12.0 points) beyond the stable-tolerance band. Deliberately gentle:
a more aggressive version regressed a real, modest semiconductor-cycle compression case combined
with other resolved-bucket components. The three carve-out types above are exempt from this
graduation entirely — the carve-out is load-bearing, not redundant (e.g. two REITs with a mild
and a severe compression both stay at the identical flat 60).

## Free Cash Flow classification

FCF = CFO + `capitalExpenditure` (FMP reports capital expenditure as already negative).

- Fewer than 2 points → `insufficient_data`, score 0.
- **Zero negative years** → `consistently_positive`, **100**.
- Otherwise, find every run of **2 or more consecutive** negative years and note where the most
  recent such run ends:
  - If that run ended **within the last 3 periods**, check first whether it's **capex-driven, not
    distress**: CFO stayed positive throughout the entire run (every value) and non-declining
    (last ≥ first). If so → `capex_driven_negative_fcf`, **85** — confirmed real shape for
    regulated utilities (heavy rate-base capex while CFO stayed comfortably positive and growing
    the entire time). Otherwise → `sustained_cash_burn`, **0**.
  - If it ended more than 3 periods ago, the run is excused as resolved if **either**: the full
    series (including TTM) reads as one of the trend classifier's own recovery patterns
    (`grows_every_year`, `small_dip_recovers`, `significant_dip_recovers`,
    `multiple_dips_resolved`, `dip_durably_resolved`); **or** a separate durable-recovery check
    passes — every year after the run ended (including TTM) is non-negative, dropping TTM from
    the series still reads as a recovery pattern on its own, and TTM is at least as large as the
    average of the (up to) 3 periods immediately following the burn.
  - If excused → `cash_burn_recovered`, **85**. If not → still `sustained_cash_burn`, **0**.
- If there's no qualifying 2+-year run at all: exactly one negative year → `isolated_dip`, **85**;
  two or more negative years that are never consecutive → `scattered_negative_years`, **60**.

## Verdict bands

| Score | Verdict |
|---|---|
| 91–100 | Strong Pass |
| 70–90 | Pass |
| 0–69 | Fail |

The verdict is purely these bands applied to the final blended score (`_verdict_for` over
`VERDICT_BANDS`) — no per-component gate on any individual pattern or score exists, so graduated
component scores cannot interact with a hidden floor. Growth Rate uses the same bands, but its
Fail is gated on the sign of projected growth instead (see [Growth Rate](growth-rate.md)).

**Badge shading.** The score badge splits the 70–90 "Pass" band into two color shades without a
text distinction: 70–74 amber (`warn` tone), 75–90 green (`positive`); 91+ is a deeper green
(`positive-strong`), and Fail / "Pass with caution" override the score tiers. The tiering is
shared by every step's badge and chip via `frontend/lib/tierColor.ts` (`toneFor`, `classFor`),
so color can't be chosen from verdict text alone.

## Insufficient data

The whole check returns `score: null, verdict: "insufficient_data"` (not a fabricated Fail) if
any of the following read `insufficient_data`: Revenue, Margins, CFO (when not exempt), FCF
(when not exempt), or **both** Net Income and its Operating Income backup. Net Income alone
reading `insufficient_data` is not a gap as long as Operating Income has real data.

A prior version folded these gaps into the weighted sum as ordinary scored zeros, so a single
failed upstream fetch (e.g. the cash-flow statement) on an otherwise-strong ticker dragged its
score into Fail. `cache.py::safe_fetch` swallows `httpx.HTTPError` to `{}`, which is
indistinguishable downstream from a genuinely thin response, so a fetch failure also reads as
`insufficient_data`. CFO-exempt companies are unaffected (CFO/FCF simply aren't required for
them), and Net Income's Operating-Income backup only counts as a genuine gap when Operating
Income's own classification also reads `insufficient_data`.

If the underlying figures simply aren't available for a company — a data gap, not a real
weakness — Financials reports as having insufficient data rather than fabricating a Fail. See
the [Glossary](glossary.md) for how every verdict label is defined.

## Calibration notes

Why the graduated/gated thresholds sit where they do. These are the distributions each value was
chosen from at the time (cache-only scans of the tracked universe, 2026-08 / 2026-09); they are
context for revisiting a threshold, not live invariants — re-scan before relying on the counts.

- **`declining` floor at -50% (`DECLINING_FLOOR_DECLINE`).** A scan found 141 tickers hitting the
  severe-TTM-decline branch, from barely past -15% to absurd near-zero-prior-year-base artifacts
  (a net income read as a -4128% "decline"); -50% was chosen because it covers 101/141 (72%) of
  real hits. The ceiling of 15 sits below `flat_then_spike`'s 20, the next-lowest pattern score,
  so a graduated `declining` can never outrank a different, milder worst-tier pattern.
- **`not_yet_positive` floor at -20% margin (`NOT_YET_POSITIVE_FLOOR_MARGIN`).** 45 hits, margin
  (value ÷ real revenue) ranging from about -149% (a real structural loss) to -0.1% (effectively
  breakeven); -20% covers 34/45 (76%) of hits, and 44% sat under -5%.
- **`multiple_dips` `MULTIPLE_DIPS_SEVERE_FRAC` = 30%.** Of 381 tickers hitting the old flat 40,
  hits cluster either near zero or far beyond 30% (the mildest 20 all sat within ~1.7% of their
  own baseline). `MULTIPLE_DIPS_FLOOR` stays at the old flat 40 so a genuinely severe,
  still-unresolved dip never scores better than before.
- **Resolved-dip floor 65 and Margins-compression floor 45.** Both are deliberately gentle: a
  lower resolved floor produced multi-component regressions for a modest, genuine
  semiconductor-cycle compression case, and both graduations can only lower scores (their
  ceilings equal the old flat values), unlike `multiple_dips`, which graduates upward from its
  old value.
- **`flat_then_spike` terminal protection is magnitude-gated on purpose.** A stress test showed
  that simply always protecting TTM would wrongly rescue jumps with no precedent in the series'
  history (a +683% CFO jump, a +207% second commodity-margin spike); gating on the ≤100% jump
  size trusts modest, plausible jumps (+45%, +42% cases that also cleared their own prior peak)
  while leaving those unrescued.
- **Bank Margins artifact.** All 28 Bank-classified tickers with margin data showed
  `grossProfit/revenue` at or above 100% around FY2021 followed by a permanent drop to a 42–77%
  plateau from FY2022 — an FMP data-methodology break specific to financial-services reporting,
  universal across the Bank population rather than a few outliers.
