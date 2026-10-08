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
- **Margins** — gross, operating and net margin, i.e. how much of each dollar of revenue the
  company actually keeps after costs. Stable or improving margins suggest pricing power and cost
  discipline; margins that are steadily eroding are a warning sign even if revenue is still
  growing. The Margins score is the lower of the gross margin score and the better of the net and
  operating margin scores.
- **Free Cash Flow (FCF)** — cash left over after the company pays for its own capital
  investments. This is checked mainly for whether it stays positive, since a sustained
  multi-year run of cash burn is a real bankruptcy-risk signal.

Every metric is scored by **one neutral engine** from its last 5–10 **completed fiscal years**
(never the trailing twelve months): which way the series is heading over the long run, how much
it dipped along the way and whether it recovered, and whether the last completed year was a fresh
collapse. A series that is growing with the odd dip scores above one that is flat, flat above
declining, and declining above one that zigzags. It's also not enough for Revenue, Net Income and
CFO to be trending the right way — they're checked for whether the latest completed year is
actually positive. A company whose losses are merely getting smaller, but still hasn't turned a
profit, is not treated the same as one that has genuinely turned the corner into profitability.

Cash From Operations and Free Cash Flow don't mean the same thing for every kind of business.
For **Banks, Insurance companies, Property Developers (REITs), and Commodity companies**, these two
checks are skipped, and so are Margins (since 2026-10-08): the company is judged on Revenue (the real
FMP revenue line, for Banks too) and Net Income alone, with Operating Income as the Net Income backup
(those two carrying proportionally more weight to make up for the three that are skipped). See
[Company type variations](company-type-variations.md) for the full picture, and the technical
reference below for exact weights and thresholds.


## Data window

The 10 most recent **completed annual fiscal years** of each metric, oldest first. **TTM is never part of
a Step 1 score** (it is still drawn on the Financials charts and tables as a display column): "latest
value", "last completed fiscal year" and every check below mean the last annual point, so what happened
after that year-end (0 / 3 / 6 / 9 months before the latest reported quarter for 44 / 26 / 472 / 45 tickers
of the 588 non-ETF tickers checked) does not move the score until the year closes (see "Known weaknesses").
Fewer than 5 completed years is scored as it is (a series needs 2 points; under 8 revenue points the
thin-history cap below applies): on that universe 9 tickers have fewer than 5 completed years, 30 fewer
than 8, 544 the full 10.

**Cleaned statements (2026-10-06).** Step 1 reads its income and cash-flow rows through the shared loader ([Statement data
quality](statement-data-quality.md), "The shared loader"): placeholder and scale-broken cash-flow rows are treated as missing, so
the annual CFO and FCF series cover real years. (The Financials *tab* is a separate raw viewer; it shows FMP's rows as served
and only adds warning markers, see the same document's "Display markers".)

**Series preparation.** FCF = CFO + `capitalExpenditure` (FMP reports it as already negative). Gross margin =
gross profit ÷ revenue × 100, **operating margin = operating income ÷ revenue × 100**, net margin = net income ÷
revenue × 100, all on real revenue (percent, 18.4 for 18.4%). A missing year is skipped, not counted as zero.

## Weights

These are the **defaults in the code** (`scoring/weights.py::DEFAULT_WEIGHTS.step1` = 35 / 20 / 30 / 10 / 5). The five base weights are
adjustable (Settings > Score weighting; Revenue 20-50, Net Income 10-40, CFO 10-40, Margins 0-25, FCF 0-15, adding up to 100) and **the
saved set can differ from the defaults**: scoring always uses the saved set, and the exempt tables below are derived from whatever base is
saved, so the percentages in this section move with it (on 2026-10-08 the live database held 30 / 20 / 25 / 10 / 15, which gives
56.52 / 43.48 for the exempt types; the Settings page is the authority for what is in force). The tables are derived by the same two rules
as always (CFO's and FCF's weight split equally over Revenue, Net Income and Margins, a component weighted 0 getting no share; then
Margins' weight spread proportionally over Revenue and Net Income). A weight of 0 leaves a component out of the blend only: its
data-gap check (a missing series still makes the step insufficient data) is unchanged.

| Metric | Standard / Utility weight | Exempt types (Bank, Insurance, REIT / Property Developer, Commodity Company) |
|---|---|---|
| Revenue | 35% | 59.57% (28/47) |
| Net Income | 20% | 40.43% (19/47) |
| CFO | 30% | 0% |
| Margins | 10% | 0% |
| FCF | 5% | 0% |

For an exempt company CFO's, FCF's and Margins' combined 45% weight is redistributed over Revenue and Net Income in proportion to their
own base weights (35 : 20), reached in two steps that give the same answer (CFO's and FCF's 35% split in equal thirds over Revenue, Net
Income and Margins, then Margins' resulting 21.67% spread proportionally over the other two), rather than being dropped from the
denominator. Before 2026-10-08 only Banks used this two-component table; Insurance, REITs and Commodity companies kept Margins
(46.67 / 31.67 / 21.67 at the defaults). `scoring/weights.py::step1_tables` still builds that middle table, but no company type reaches it.

Final score = weighted sum of the 5 (or 2) component scores, rounded and clamped to [0, 100].

## Company-type exemption (CFO / FCF / Margins)

Cash From Operations, Free Cash Flow and Margins are skipped for (since 2026-10-08; before it Margins was skipped for Banks only):

- **Bank**
- **Insurance**
- **Property Developer** (the shared REIT/Property Developer classifier)
- **Commodity Company** — a price-taking producer or extractor: the profile sector is `Basic Materials` or `Energy` **and**
  the FMP industry is on the producer allowlist (`COMMODITY_PRODUCER_INDUSTRIES`, since 2026-10-07): Oil & Gas Exploration & Production, Oil & Gas Integrated, Oil & Gas Refining & Marketing, Agricultural Inputs, Uranium, Copper, Gold, Steel, Paper, Lumber & Forest Products, Aluminum, Silver, Other Industrial Metals & Mining, Other Precious Metals & Mining, Coal, Thermal Coal, Coking Coal.
  Every other industry in those two sectors (Chemicals, Chemicals - Specialty, Construction Materials, Oil & Gas Equipment & Services,
  Oil & Gas Midstream, Solar, ...) is scored as **Standard**, CFO and FCF included. A ticker in the two sectors with no cached industry
  stays Commodity (the earlier behaviour). This is a category specific to this check; it has no equivalent in the shared company-type
  classifier used by Profitability, Debt, and Valuation.

Bank/Insurance/Property Developer are detected via the same shared sector/industry classifier
the other checks use. Commodity Company is detected locally by sector plus industry text. A small hand-verified list of tickers FMP files under the wrong sector (JCI, MAS) is excluded from the Commodity branch and scored as Standard
(`COMMODITY_EXEMPTION_TICKER_OVERRIDES`; redundant since the allowlist, kept as a guard, [Company type variations](company-type-variations.md)).

These four types are scored on **Revenue and Net Income only**, with Operating Income as the Net Income backup (below, unchanged).
**Revenue is the real FMP revenue line for every company type, Banks included.** Until 2026-10-08 a Bank's "Revenue" was FMP's
`netInterestIncome` (scored, labelled "Net Interest Income" on the Step 1 card and the Historical Trends grid, and drawn in the Watchlist
Trend column); that substitution is removed everywhere (scoring, `Step1Out.revenue`, the card and grid labels, the Watchlist trend and the
Review evidence, which divides Operating Income by the same revenue the scoring gate uses). The Financials *tab* still lists Net Interest
Income as its own row. The margin series (gross, operating, net) are still computed from real revenue and shown, they are just not scored
for these four types.


## The engine

`scoring/step1_engine.py::assess_series(values, kind) -> (pattern, score 0-100)`. The caller passes the series
(finite numbers, oldest first, completed fiscal years only) and its **kind**, never inferred from a name: `"dollar"`
for Revenue, Net Income, Operating Income, CFO and FCF, `"ratio"` for gross, operating and net margin. Nothing else
enters: no company type, no second series. `classify_trend` (`scoring/trend.py`) is **not** used by Step 1 any more;
Steps 3 and 4 still use it, untouched.

**Principles (fixed).** (1) Dollar-series ordering: growing with occasional dips > flat > declining > zigzag; a recovered
dip in a clear uptrend scores above flat; flat is "not growing" and sits well below Strong Pass. (2) The 5-10 year shape
comes first, not year-by-year steps. (3) Dips are a graduated penalty on smooth ramps (zero dips best; more, longer and
unrecovered dips cost more), with no hard cutoff (the old "4 or more dips caps at 50" rule is gone). (4) A fresh collapse in
the last completed fiscal year lowers the score. (5) Dollar series must grow, so flat scores low, and are judged in
fractions of their own size (scale-invariant); ratio series may be flat and still score well, and are judged in
**percentage points**. (6) Near-identical shapes score near-identically (no 4.9% vs 5.1% cliff). (7) One engine for every
metric: a negative value is just a dip; no separate rules for negatives, short history or explosive growers.

**Units.** DOLLAR: `S` = median of `|x|`, `y = x / S`; `n < 2` or `S = 0` (a pre-revenue series) is `insufficient_data`,
score 0. RATIO: `y = x` in points; `n < 2` is `insufficient_data`. Change `c[t]`: DOLLAR `(x[t] - x[t-1]) /
max(|x[t-1]|, 0.25 * S)`; RATIO `x[t] - x[t-1]`. All sizes below are "units": fractions of own size (dollar) or points (ratio).

**Part 1: long-term direction.** `g` (units per year) is the mean of two robust whole-window estimates of `y`: the Theil-Sen
slope (median of all pairwise slopes) and the window drift `(median of last w - median of first w) / (n - w)`, `w =
min(3, floor(n/2))`. The trend score `T(g)` is piecewise linear:

| kind | `g >= full` (100) | `g = 0` (flat) | `g <= floor` (30) |
|---|---|---|---|
| DOLLAR | +6% of own size per year | **68** | -15% per year |
| RATIO | +1.0 point per year | **88** | -3.0 points per year |

**Part 2: dip penalty.**

- Excess drop `e[t] = max(0, -c[t] - max(0, -g))`: a fall counts only beyond the series' own typical decline.
- Dip weight `a[t] = clamp((e[t] - lo) / (hi - lo), 0, 3)`, `(lo, hi)` DOLLAR 2% / 20%, RATIO 1 / 6 points; capped at 3.
- **Peak candidates** (the one reference for both quantities below): a year counts toward a peak only up to the highest of
  its up-to-2 neighbours each side plus one year of the series' own growth, `x~[s] = min(x[s], max(x[s-2..s+2] without s) +
  max(0, g))`. The first and last year are never capped. A one-year spike is clipped to its neighbours; a repeated high, a
  plateau of 2+ years and a high before a recovered dip stay peaks.
- Unresolved fraction `u[t] = 1 - clamp((x[last] - x[t]) / (p[t] - x[t]), 0, 1)`, `p[t]` the highest peak candidate before
  `t` (0 when `x[t] >= p[t]`): 0 fully recovered, 1 not recovered at all.
- Years underwater `W`: each point counts `clamp((dd - lo) / (hi - lo), 0, 1)` of a year, `(lo, hi)` DOLLAR 2% / 12%, RATIO 1 / 6
  points; `dd` is the depth below a peak that itself decays at the series' own decline (`pk[t] = max over s <= t of
  x~[s] * (1 + min(0, g))^(t-s)` in own-size units for DOLLAR, positive candidates only; `x~[s] + min(0, g) * (t-s)` in points
  for RATIO).
- **Age-decayed dip costs (2026-10-07).** A dip or underwater year long ago costs less once the series has clearly grown since. With
  `age` = completed fiscal years before the last one (the last year = 0; a dip's age is the year it falls *into*) and
  `d[age] = 1 - (1 - 0.5^(age / H)) * s`, `H = DECAY_HALF_LIFE_YEARS = 4` (a constant, not a setting) and
  `s = clamp(min(g, g') / T_full, 0, 1)` (`g` the Part 1 trend, `g'` the same trend computed with the last completed year dropped,
  `T_full` the trend that already earns 100: +6% of own size per year DOLLAR, +1.0 point RATIO), the burden is
  `K = sum a[t] * (d[age(t)] + u[t]) + sum d[age(t)] * w[t]` where `w[t]` is year `t`'s underwater fraction (`W = sum w[t]`
  before). So `s = 1` halves a cost every 4 years (age 4: 0.5, age 8: 0.25); `s = 0` (no real, lasting uptrend) leaves `d = 1` and the
  score exactly as it was. Using `g'` is deliberate: a series whose uptrend is one final-year spike gets no forgiveness. The unrecovered
  extra `a[t] * u[t]` is **never decayed**. Only dip weights and underwater years decay: the direction measure, the last-year cut,
  the ceiling, the positivity gate, Margins `min(G, max(N, O))` and the company-type exemptions are untouched, and the same code path
  serves every metric and both kinds (no per-metric branch). Series of 3 points or fewer have no `g'` to judge and are never forgiven.
- Burden `K = sum a[t] * (d[age(t)] + u[t]) + sum d[age(t)] * w[t]` (`d = 1` without a real uptrend, so `K = sum a[t] * (1 + u[t]) + W`). Discount `D(K) = 80 * (1 - exp(-(K / 12)^1.5))` points (K 1/2/3/5/8/10/20: 1.9 / 5.3
  / 9.4 / 18.9 / 33.6 / 42.6 / 70.7 points off), strictly increasing, saturating at 80, same for both kinds.

**Part 3: last completed fiscal year.** `s = clamp((e[last] - lo) / (hi - lo), 0, 1)`, `(lo, hi)` DOLLAR 10% / 50%, RATIO 2 / 12
points; the score is multiplied by `1 - 0.6 * s`. There is no rule for quarters after the last fiscal year.

**Part 4: series kind.** Enters through `T` and through the units of every size above; the formulas are otherwise identical.
A fall through zero is a (large) dip; a flat ratio series with one negative year counts as one dip (flat 20 with one year at
-5 scores 74).

**Part 5: positivity ceiling (RATIO only).** If the latest completed-year value is **at or below zero**, the series' score is
capped at `C = 40 * max(0, 1 + x[last] / 10)`: 40 at a zero margin, falling 4 points per point of loss, 0 at a loss of 10
points or more. A positive latest value is not capped. Earlier negative years are ordinary dips. The cap is applied to each of
gross, operating and net margin separately, before the combination and before the carve-out; dollar series are untouched.

**Score and labels.** (K above includes the age decay.) `score = round(min(clamp(max(0, T(g) - D(K)) * (1 - 0.6 * s), 0, 100), C))` (the ceiling only for
RATIO). Labels (information, and the Margins carve-out only; they never change a score): `uptrend` if `g >= +2%` per year
(DOLLAR) or `+0.25` point per year (RATIO), `decline` if `g` is at or below the negative of that, else `flat`; `_dips` is
appended when `K >= 0.25`. The six labels plus `insufficient_data` are the only patterns the engine emits (`not_yet_positive`
comes from the positivity gate below).

**Every threshold is a named constant in one place** (`step1_engine.py`: `DOLLAR_PARAMS`, `RATIO_PARAMS` and the shared
constants above them). They are starting values chosen by prototype, not fitted; the principles are the fixed part.

**Guarantees pinned by tests** (`scoring/test_step1_engine.py`): DOLLAR scores do not change when the series is multiplied by
any positive constant (RATIO is in points by design and is not scale-invariant); the synthetic ordering suite (dip count
strictly lowering the score at growth 3/5/8/12/20%, 1-3 dips above flat at growth of 5% or more, flat > slow > moderate >
steep decline > every zigzag, the penalty never rising with dip depth, strictly falling with dip length, an open dip below the
same dip recovered, a flat series with one spike year above a steady decline and never above the same series without the
spike, no cliff in a 0.1%-step sweep of one fall); the ratio ceiling (the score never above `C`, strictly falling below zero,
an improving-but-still-negative series below a flat positive one). For RATIO, "growers with 2-3 dips above flat" is **not**
guaranteed (a flat margin scores 88 by design; that ordering is stated for dollar series only). Not guaranteed either: adding
a dip almost always lowers a real series' score, not always. With the age decay, more dips score strictly lower only while the dips are
young (within about 6 years of the last completed year); for older dips the score only falls or ties (integer rounding), and a recovered
old dip in a growing series never scores below flat.

Reference scores (11 points; dollar growth 8% a year, a dip is a 15% fall that returns to the path; dips at indices 3 / 3,6 /
2,5,8 / 2,4,6,8): clean grower 100, one dip 99, two 97, three 93, four 90 (before the age decay: 96 / 89 / 80 / 72); flat 68; decline at 3% / 6% / 12% a year 60 / 52 / 35; zigzag 100/85 32, 100/70 15; flat
with one +75% year 62; that spike followed by a -6% a year decline 25. Ratio: flat positive 88 at any level, clean grower
(+0.8 a year) 98, steady declines of 0.6 / 1.2 points a year 76 / 65, zigzags 20/15 and 20/10 54 / 31.

## Positivity gate (Revenue, Net Income, CFO)

The engine is purely relative: it never asks whether the values are actually positive. On top of it, Revenue, Net Income and
CFO each require the **latest completed fiscal year to be positive**:

- If the engine returned `insufficient_data`, this gate is skipped.
- Otherwise, if the last annual value is **≤ 0**, the result is `not_yet_positive`, whatever the shape. **The score is
  graduated (2026-08-13)**: measured as a margin (`value ÷ revenue × 100`), scaled
  linearly from **15** points (at 0% margin) down to **0** (at **-20%** margin or worse); a flat 0 if no revenue figure is available.
- Otherwise the engine's own score is used. An earlier negative year is just a dip.

The gate lives in `scoring/step1.py::_classify_positive_trend`. It is **not applied to Free Cash Flow**: FCF is the engine
alone and a negative value is a dip (60 non-exempt tickers have a latest FCF at or below zero; the engine alone scores them
a mean of 1.4).

## Net Income's Operating Income backup

If Net Income's positivity-gated score is **≤ `NET_INCOME_BACKUP_THRESHOLD` (79 = the cap minus 1)**, Operating Income is
consulted as a backup signal, but only when the disqualifying dip is recent enough to plausibly be a one-off:

- Compute the age (in fiscal years before the latest one, 0 = the transition into the latest completed year) of Net Income's most
  recent real dip, with the existing helper `scoring/trend.py::most_recent_real_dip_age` (its own -5% line; a hard cutoff kept
  inside a wrapper on purpose).
- If Net Income itself read `insufficient_data`, the backup is always consulted.
- Otherwise it is consulted only if that dip's age is **≤ 2** (`NET_INCOME_BACKUP_RECENCY_YEARS`).
- When consulted, Operating Income goes through the same engine + positivity gate. The final Net Income score is
  `min(80, max(Net Income's own score, Operating Income's score))`: capped at 80, never lower than Net Income's own.

**Quality gates on the lift, on completed fiscal years, no TTM.** The backup may only *lift* if **all** hold, otherwise Net Income
keeps its own score:

1. **Operating Income of the latest completed fiscal year > 0.**
2. That Operating Income is **≥ 5%** of that year's real revenue (`NET_INCOME_BACKUP_MIN_OI_MARGIN`; exactly 5% passes).
3. Operating Income is **positive in at least 4 of the last 5 completed fiscal years** (`NET_INCOME_BACKUP_OI_WINDOW` = 5,
   `NET_INCOME_BACKUP_MIN_POSITIVE_PERIODS` = 4; a missing year is skipped; a shorter series is judged on what it has).

A missing latest-year Operating Income or revenue fails its gate. `data/step1_data.py` passes the raw last-annual-row values
(`latest_revenue`, `latest_operating_income`) to `score_step1` because the None-filtered series can't tell a missing year from a
present one; direct callers that omit them get the last point of the series. (This replaces the earlier TTM-based health check:
Step 1 reads no TTM anywhere. The two former TTM gates moved to the latest completed fiscal year with the same 5% and 4-of-5
bars.) The gates only govern the lift: Operating Income is still scored whenever consulted, so the "genuine data gap" rule is
unchanged, and `components.net_income.used_operating_income_backup` is true only when the backup actually changed the score.

**"Backup used" note.** When that flag is true the card shows a muted line under the Net Income bullet, "Score lifted using
Operating Income (backup)", with a tooltip quoting the score before and after and the two measured gates (latest fiscal year
Operating Income margin against 5%, positive years against 4 of 5). `score_step1` adds `score_before_backup` and `backup_gates`
(`oi_margin_pct`, `min_oi_margin_pct`, `positive_periods`, `min_positive_periods`, `window`) **only** when the flag is true.

**Applies to every company type.** The backup was never exempted by type, and the gates are not either. The threshold 79 is
`NET_INCOME_BACKUP_CAP - 1`: every score the backup could still improve is eligible, 80+ is left alone.

## Margins

Three series go through the RATIO engine separately: **G** gross margin, **O** operating margin, **N** net margin (each
including the positivity ceiling of Part 5). Then

**Margins = min(G, max(N, O))**

with no averaging and no threshold. A weak G keeps the score low (gross margin is a hard cap); if G is healthy and N bad, O
stands in for N (a one-off below the operating line); if both N and O are bad the score is low. **A series with fewer than 2
years is missing and drops out:** no gross margin gives `max(N, O)`; no operating margin gives `min(G, N)`; no net margin gives
`min(G, O)`; **N and O both missing makes Margins `insufficient_data`** (and the step), whatever G is. The Margins pattern is the
deciding input's (a tie between N and O goes to net margin; G wins a tie with `max(N, O)`); the component also carries the three
input scores (`inputs`) and which one decides (`binding`) as additive display fields.

**Exemption.** Bank, Insurance, Property Developer and Commodity Company skip Margins entirely (`MARGINS_EXEMPT_TYPES` in
`data/step1_data.py`, extended from `{"Bank"}` on 2026-10-08): nothing is computed in its place, and Step 1 scores no ROE or ROIC (ROE is
checked for Banks in Step 4 only). Standard and Utility score Margins as described here.

**Severity carve-out (Utility only).** A margin series (each of G, O and N) labelled `decline` /
`decline_dips` is never scored below **60**, per series, **after** the positivity ceiling and before the combination. The carve-out can
therefore lift a loss-making declining series from under its ceiling to 60; the wrappers are unchanged and this is accepted. Insurance and
REIT / Property Developer had the carve-out until 2026-10-08 and lost it when they stopped scoring Margins (`MARGINS_SEVERITY_CARVEOUT_TYPES`
is `{"Utility"}`; the ARE, CSGP and VTR cases the old text cited no longer arise).

## Free Cash Flow

FCF is the DOLLAR engine alone on the annual FCF series (`_classify_fcf`): no positivity gate, no cash-burn tiers, no capex-driven
softening (utilities lose it). A negative year is a dip; whether it recovered is `u` / `W`. Fewer than 2 points → `insufficient_data`.
CFO and FCF are skipped for the company types in "Company-type exemption" above.

## Verdict bands

| Score | Verdict |
|---|---|
| 91–100 | Strong Pass |
| 70–90 | Pass |
| 0–69 | Fail |

**Thin-history cap (2026-10-06, "H1").** A step cannot be a Strong Pass on fewer than **8 data
points**: when the count is below `THIN_HISTORY_MIN_POINTS` (8, `scoring/trend.py`) the blended score
is capped at `THIN_HISTORY_SCORE_CAP` (90, the line below the Strong Pass band), so the verdict reads
Pass. For Financials the count is the length of the cleaned Revenue series handed to `score_step1`,
completed fiscal years only. The cap sits where the score is finalized, so the stored score, the verdict
and the card agree; no caution flag is added. A score already at or below 90 is untouched. Profitability
has its own count (see [Profitability](profitability.md)).

The verdict is purely these bands applied to the final blended score (`_verdict_for` over
`VERDICT_BANDS`) — no per-component gate on any individual pattern or score exists, so graduated
component scores cannot interact with a hidden floor (the one exception is the thin-history cap above, which only ever holds a score at 90). Growth Rate uses the same bands, but its
Fail is gated on the sign of projected growth instead (see [Growth Rate](growth-rate.md)).

**Badge shading.** The score badge draws the 70–90 "Pass" band in one green (`positive`; the 70–74 band was amber until
2026-10-08); 91+ is a deeper green (`positive-strong`), and Fail (displayed "May not pass", slate
`not-pass`) / "Pass with caution" (amber) override the score tiers. The tiering is
shared by every step's badge and chip via `frontend/lib/tierColor.ts` (`toneFor`, `classFor`),
so color can't be chosen from verdict text alone.

## Insufficient data

The whole check returns `score: null, verdict: "insufficient_data"` (not a fabricated Fail) if
any of the following read `insufficient_data`: Revenue, Margins (net **and** operating margin both missing; a missing gross
margin alone is not a gap; not checked for the exempt types), CFO (when not exempt), FCF (when not exempt), or **both** Net Income and its Operating Income backup. Net Income alone
reading `insufficient_data` is not a gap as long as Operating Income has real data.

A prior version folded these gaps into the weighted sum as ordinary scored zeros, so a single
failed upstream fetch (e.g. the cash-flow statement) on an otherwise-strong ticker dragged its
score into Fail. `cache.py::safe_fetch` swallows `httpx.HTTPError` to `{}`, which is
indistinguishable downstream from a genuinely thin response, so a fetch failure also reads as
`insufficient_data`. CFO-exempt companies are unaffected (CFO/FCF simply aren't required for
them, and neither are Margins), and Net Income's Operating-Income backup only counts as a genuine gap when Operating
Income's own classification also reads `insufficient_data`.

If the underlying figures simply aren't available for a company — a data gap, not a real
weakness — Financials reports as having insufficient data rather than fabricating a Fail. See
the [Glossary](glossary.md) for how every verdict label is defined.


## Known weaknesses (not fixed here)

- **A collapse in the latest quarters is invisible until the fiscal year closes.** The series ends at the last completed fiscal year,
  so whatever happened after that year-end (a drop, a recovery, a new loss) does not move any score and no rule is added for it.
- **Gross margin is a hard cap, and FMP gross profit is not a real goods margin for some sectors.** G is the binding input for
  about half the scored tickers. 43 tickers have G more than 20 points under both N and O (utilities, REITs, hospitals, telecom,
  pharma services, media: e.g. HCA, whose G is 0 against an O of 89 and an N of 88), and six report a gross margin of about
  100%. This is **accepted as a limitation**: no gross-margin exception exists (the owner asked for none). A gross margin that
  moves 5-10 points a year at a 60-80% level is priced as a string of dips in points (ABBV, AMGN, BMY).
- **The positivity ceiling steps at zero, and thin positive margins sit just above it.** A latest margin of +0.01 is not capped, one
  of 0.0 is capped at 40: on a flat 3% margin the score goes 82 (last year +0.3), 80 (+0.01), 40 (0.0), 36 (-1), 24 (-4), 0 (-10).
  Thin-margin businesses (COR net margin 0.48, CVS 0.44, GPC 0.27) score high today and would be capped at 40 or below by a fall
  of half a point; an improving series crossing zero in its last year scores about 100 against about 39 a year earlier.
- **Ratio scoring is level-dependent by design (a point is a point).** The same wobble in points costs a 3%-margin business
  less, relative to its margin, than a 40%-margin one: the median net-margin score falls with the margin level (83 / 70 / 59 / 45 / 0
  for medians under 3% / 3-10% / 10-25% / 25-50% / 50%+). Measuring ratios relative to their own size gives the opposite slope;
  neither is flat.
- **Explosive growers** (AMD cash flow, CRDO and MRVL earnings) are judged against their own median size, which is small beside
  the latest value, so early wiggles read as large dips (157 dollar series that grew more than 6x from first to last point still
  score under 85).
- **Zigzag versus decline is thin for dollar series by design:** a mild 100/85 zigzag ends only 3 points under a steep -12% a
  year decline (32 vs 35); the ordering holds only because the decline floor is 30.
- **A spike is still charged once or twice.** The peak is robust to a one-year spike, but its snap-back fall is still a dip and it
  bends the trend a little (a flat series with one +75% year scores 62, six under the same series without it). A spike in the
  **first or last** year is not capped, and two spike years within two years of each other are a plateau.
- **Real one-year peaks are discounted** (JBHT net income, CLX CFO, EXR net margin: a real boom-year peak followed by a real fall
  is measured from a lower peak).
- **Trend estimates are sensitive in noisy series:** pulling one interior point down (a genuine new fall) raised a real series'
  score in about 4% of trials (median +0.6 points, max about +17); the recovered test is ill-conditioned next to a capped peak
  (no tolerance is added).
- **Overlap with Growth Rate:** trend strength in Step 1 rewards growth that Growth Rate also scores.
- **Pre-revenue series** (median 0, e.g. ACHR, VYLR) are `insufficient_data`.

## Calibration notes

Prototype figures on the 588 non-ETF tickers (cached data, 2026-10-07, completed fiscal years only; saved weights 30/20/25/10/15,
defaults 35/20/30/10/5): component means / medians (applicable tickers) Revenue 83 / 93, Net Income (with backup) 55 / 64, CFO
60 / 66, Margins 60 / 66 (G 70 / 79, O 65 / 73, N 57 / 62), FCF 48 / 51. Financials at the saved weights: mean 65.3, median 69,
Fail / Pass / Strong 51% / 37% / 12% (defaults: mean 67.3, 46% / 39% / 14%). Margins applies to 559 tickers (29 Banks skip it), 556
scored (ACHR, HONA, VYLR `insufficient_data`); binding input G 282, O 148, N 84, N = O 42; O lifts Margins above `min(G, N)` for 225
tickers and a sub-70 Margins to 70+ for 65. 60 tickers have a latest N or O at or below zero (38 both): RIVN and SNOW score Margins 0.
The ranges are context for revisiting a threshold, not live invariants: re-scan before relying on the counts.

**Calibration shift from the age decay (2026-10-07; 579 scored tickers, saved weights 30/20/25/10/15):** Financials mean 65.7 -> 70.5, Fail /
Pass / Strong Pass 288 / 221 / 70 (50% / 38% / 12%) -> 228 / 222 / 129 (39% / 38% / 22%); 215 tickers up by more than 5 points, none down
(the decay only ever lowers a burden); 60 cross 70 upward, 59 cross 91 upward. CLS (recovered early weakness, then growth): Net Income 64 -> 91,
CFO 52 -> 85, FCF 38 -> 74, Financials 68 -> 89. The Strong Pass share nearly doubled, so "Strong Pass" now means a clearly growing series with
a long recovered history, not a clean record. Rationale and rejected options: docs/decisions.md 2026-10-07 (age decay).

- **`not_yet_positive` floor at -20% margin (`NOT_YET_POSITIVE_FLOOR_MARGIN`).** 45 hits, margin (value ÷ revenue) from about
  -149% (a real structural loss) to -0.1% (effectively breakeven); -20% covers 34/45 (76%) of hits.
**Calibration shift from the exempt-type change (2026-10-08; 582 tracked tickers, saved weights 30/20/25/10/15, read-only simulation then the
real recompute):** 0 of the 499 Standard and Utility tickers move. Of the 109 exempt tickers (29 Bank, 24 Insurance, 30 REIT, 26 Commodity) the
Step 1 score changes for 99; Step 1 verdict flips Fail to Pass for SYF, TMP (Banks), EG (Insurance), CCJ, COP, DVN, EQT, FANG (Commodity), FRT, UDR
(REIT) and Pass to Fail for SPG (73 to 69). Overall verdict: WFC, CINF and HSBC Fail to Pass, AXP Strong Pass to Pass, no Pass to Fail
(Debt's REIT change, [Debt](debt.md), moves five REITs to a Step 5 Pass without changing any REIT's Overall verdict). The two-component
blend is more sensitive to a single weak series: a Net Income score of 0 now costs 43% (saved weights) of the whole step.

- **Bank Margins artifact (historical).** All 28 Bank-classified tickers with margin data showed `grossProfit/revenue` at or above 100% around
  FY2021 followed by a permanent drop to a 42-77% plateau from FY2022: an FMP data-methodology break specific to financial-services
  reporting, universal across the Bank population.
