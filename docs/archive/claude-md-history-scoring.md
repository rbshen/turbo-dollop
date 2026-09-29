# CLAUDE.md history: scoring

Verbatim history moved out of the original CLAUDE.md (archived at docs/archive/CLAUDE.original.md). Text is unedited; line ranges refer to that file.

This file currently holds only the Valuation (Step 3) scoring-notes history (phase B4). The Financials/Growth/Debt/Profitability/Overall scoring-rubric history (original lines 446-1613) is appended in a later phase (B5).


## Valuation (Step 3) scoring notes: heading and intro (original lines 1945-1951)

## Valuation (Step 3) scoring notes

Three fixes shipped together 2026-08-08, all originating from an
investigation into what Discounted Net Income (Normalized) actually
computes — see `valuation.md` for the exact current formulas/mechanism;
these are the design decisions and fixes behind them.



## Valuation: RECOVERY_PATTERNS missing dip_durably_resolved (2026-08-08) -- fix and before/after scan (original lines 1952-1977)

- **`RECOVERY_PATTERNS` (`scoring/trend.py`) was missing
  `dip_durably_resolved`**, the age-aware recovery pattern added earlier
  the same day (see the Financials section above) — scored identically to
  `multiple_dips_resolved` in `classify_trend` (both 75) and documented
  there as meant to be treated the same by any caller, but the set itself
  was never updated. Three call sites gate on `pattern in
  RECOVERY_PATTERNS`: `scoring/step1.py`'s FCF cash-burn-recovery check
  (Revenue/NI/OI/CFO's own Step 1 scores read `classify_trend`'s score
  directly, not this set, so they already benefited immediately — only
  FCF's own recovery check had the gap), Step 3's method-selection tree
  (`_positive_and_increasing`/`_fcf_positive_and_consistent`), and Step
  4's ROE/ROIC min-year-consistency gate and negative-equity Net Income
  substitute. Fixed by adding the pattern to the set — one line, every
  call site already treats the set as the single source of truth.
  Confirmed via a full 503-ticker before/after scan: 0 Step 1 changes (no
  cached ticker happened to hit the FCF-specific gap), 17 Step 3
  method-selection changes, 1 Step 4 verdict flip. Every Step 3 change is
  an upgrade to a more direct method, never a regression: **AWK, CMS,
  EXC, LVS, PNR, PRU, TROW** (DNI_NORMALIZED → DNI); **DAL, MDT, NWS,
  NWSA, PFG** (DNI_NORMALIZED → DFCF); **IQV, T** (DNI → DFCF); **TER**
  (DNI → DCF); **KHC, SJM** (PASS → DFCF — Valuation was previously
  unavailable for these two entirely). **MCK**'s Step 4 ROE negative-
  equity substitute flips from `negative_equity_inconsistent_income` (60
  pts) to `positive_despite_negative_equity` (100 pts), score 90 → 100,
  Pass → Strong Pass.



## Valuation: DNI_NORMALIZED TTM double-count fix (2026-08-08) -- investigation, period-identity rationale, affected tickers (original lines 1978-2026)

- **DNI_NORMALIZED's 5-period smoothed average double-counted TTM when a
  fiscal year had just closed with no newer quarter reported since.** TTM
  is a genuine sum of the 4 most recent quarterly filings
  (`helpers/ttm.py::sum_last_four_quarters`), never a copy of the annual
  figure — but the smoothing average (`net_income_clean[-5:]`, all annual
  values + TTM appended unconditionally) has no way to tell "TTM is a
  distinct, more-current period" from "TTM's 4 quarters ARE the latest
  annual filing's own Q1–Q4, describing the identical period." In the
  latter case that one period counted twice in a 5-point average (2/5
  weight instead of the intended 1/5) while every other period counted
  once. Confirmed real case: **SNDK**'s FY2026 (a memory-pricing
  supercycle year, $11.4B Net Income — more than the prior 4 years
  combined) was being counted twice, inflating `net_income_smoothed` from
  a corrected $1.61B to $3.68B — directly undermining the metric's own
  purpose, since normalization exists specifically to dilute an anomalous
  year, not double-weight it.
  - **Detection is period-identity, not value-equality**
    (`helpers/ttm.py::is_ttm_period_duplicate_of_last_fy`): compares the 4
    most recent quarters' own `fiscalYear`/`period` labels against the
    latest annual filing's, not the resulting sums — a coincidental value
    match isn't the same condition (would false-clear on genuinely
    distinct periods), and a genuine period match can differ slightly in
    value after a restatement (would false-miss under a value check).
    Confirmed via a full-universe scan that both checks currently agree
    100% of the time on real cached data (30/503 tickers hit the NI
    condition, 28/503 the CFO condition) — but the period-based check is
    the structurally correct one regardless.
  - **Fix (Option B): when detected, TTM is excluded and the average is
    taken over the prior 5 *distinct* fiscal years instead of 4** — not
    just dropping to a 4-point average, which would work but shrink the
    window. `scoring/step3.py::trailing_smoothed_average` (shared by all
    three normalized methods — see below) falls back to including TTM if
    excluding it would leave fewer than 2 points, mirroring
    `step4.py::recovery_excluded_prefix_length`'s own "never make it less
    scoreable" guard — not reachable for any currently-tracked ticker
    (every ticker hitting the duplicate condition has 5+ years of
    history) but cheap insurance for a future thin-history ticker.
  - Of the 30 NI-affected tickers, 10 auto-selected DNI_NORMALIZED at the
    time of the fix (**CLX, FDX, MCHP, MDT, NKE, NWS, NWSA, SNDK, SYY,
    WDC**) — though after the `RECOVERY_PATTERNS` fix above lands first,
    **MDT/NWS/NWSA no longer auto-select DNI_NORMALIZED at all** (they
    flip to DFCF), leaving **CLX, FDX, MCHP, NKE, SNDK, SYY, WDC** as the
    tickers whose live Auto Calculation value this fix actually changes;
    the rest only affect what Manual Calculation's DNI_NORMALIZED
    pre-fill would show if a user switched to it. Confirmed real
    before/after (Option B, post-`RECOVERY_PATTERNS`-fix): SNDK
    $3.68B → $1.61B (−56%), WDC $3.65B → $2.07B (−43%), MCHP $0.91B →
    $1.13B (+24%), NKE $4.04B → $4.63B (+15%).



## Valuation: CF_NORMALIZED/FCF_NORMALIZED manual-only methods (2026-08-08) -- rejected auto-trigger designs and sample values (original lines 2027-2060)

- **New `CF_NORMALIZED`/`FCF_NORMALIZED` methods — Manual Calculation /
  Custom Valuation-only, never auto-selected.** Motivated by a real gap:
  CFO/FCF growing very fast in the last 2-3 years, where the raw TTM
  figure would overstate a sustainable run-rate the way DNI_NORMALIZED
  already protects against for Net Income. Two candidate auto-trigger
  designs were tested against the live universe and both rejected in
  favor of a manual-only method: a 3-year CAGR threshold flagged 40-70+
  tickers even at 25%, essentially "most growth stocks"; a spike-ratio
  threshold (TTM ÷ avg of prior 3 years, reusing the
  `ROE_SPIKE_RATIO_THRESHOLD`/`DIP_BASELINE_SPIKE_RATIO` convention)
  still flagged NVDA/MU/PLTR/AMD even at 2.5x. Computed smoothed values
  for a sample of both groups show why: **NVDA** CFO $125.6B raw vs.
  $41.9B smoothed (+200%), **AMD** FCF $8.6B vs. $3.3B (+158%), **DASH**
  FCF $2.3B vs. $1.16B (+97%) — all durable, still-accelerating
  structural growth that a smoothing trigger would systematically
  under-value — statistically indistinguishable, on CFO/FCF magnitude
  alone, from **SNDK** CFO $11.7B vs. $2.4B (+391%) and **WDC** FCF
  $3.5B vs. $0.7B (+392%) — a genuine cyclical memory-pricing supercycle
  where smoothing is the right call. FMP has no industry-cyclicality
  signal that could tell these apart (the existing
  `NON_LENDER_TICKER_OVERRIDES` table above required manual per-ticker
  verification for a much narrower classification problem). Rather than
  risk auto-suppressing exactly the highest-quality compounders in the
  tracked universe, `select_method`'s tree is unchanged — CF_NORMALIZED/
  FCF_NORMALIZED exist purely as method choices a user can pick in Manual
  Calculation/Custom Valuation, pre-filled from `cfo_smoothed`/
  `fcf_smoothed` (computed unconditionally, same pattern as
  `net_income_smoothed`/`pb_mean_ratio`, and reusing the TTM-duplicate
  fix above), and behave identically to DNI_NORMALIZED once selected —
  same 20yr engine, same Custom Valuation pre-fill/freeze semantics, same
  FX handling (already-USD by the time smoothing runs, since every raw
  figure is converted immediately after each FMP pull, before any
  smoothing math).



## Valuation: item 4 fx_rate doc fix and unused fx_rate_staleness_days finding (2026-08-08) (original lines 2061-2096)

- **Item 4 (2026-08-08, docs-only): `valuation.md`'s `fx_rate` section was
  stale**, still describing it as "always 1.0, no conversion performed" —
  true before non-USD reported-currency conversion shipped (`dd5045f`),
  false since. Rewrote `valuation.md` §2.1 (inputs table) and added a new
  §2.1b covering the real mechanism: per-ticker `reportedCurrency` →
  `<CCY>USD` spot-rate resolution, cached via the same
  `FundamentalsCache`/`get_or_fetch` machinery every other fetch uses,
  applied once upfront to every monetary figure before any scoring/
  smoothing math runs, never silently falling back to 1.0 (an
  unresolvable rate reads `insufficient_data`/PASS instead), and shown in
  the UI as a caption under Fair Value ("Converted from `<CCY>` @
  `<rate>` (as of `<date>`)"). `docs/valuation.md` (file not in repo) was checked too (per
  this fix's own instructions) but has no FX-related content at all, stale
  or otherwise — no change needed there.
  - **Found, then resolved (2026-08-08, follow-up cleanup):**
    `backend/core/config.py` defined `fx_rate_staleness_days = 1`, with a
    comment explaining it was intended to be tighter than
    `cache_staleness_days` (7 days) since "a forex spot rate moves daily"
    — and `dd5045f`'s own commit message claimed the FX cache used this
    1-day setting. It never did: `data/step3_data.py::get_step3_data`
    always passed the general `cache_staleness_days` (not
    `fx_rate_staleness_days`) into `_resolve_fx_rate` at its only call
    site, and `fx_rate_staleness_days` was otherwise unreferenced anywhere
    in the codebase — confirmed via project-wide grep. Rather than wire
    the unused setting in (which would have changed live FX-refresh
    behavior from 7 days to 1), the user's call was to keep FX rate
    refresh aligned with the same `cache_staleness_days` window as
    fundamentals — this is a genuine choice, not just accepting the
    accidental status quo: a spot rate moving daily doesn't necessarily
    need a tighter cache than fundamentals if the intrinsic-value
    calculation it feeds is itself only meaningfully updated on a similar
    cadence. `fx_rate_staleness_days` was deleted (not wired in) as a
    result; `valuation.md` §2.1b no longer mentions a separate FX
    staleness setting at all, describing the single shared 7-day window
    only.



## Valuation: book_value_per_share formula and anchor fixed (2026-08-13) (original lines 2097-2116)

- **`book_value_per_share`'s formula and anchor fixed (2026-08-13)**, following a fuller
  Price-to-Book methodology spec review. Previously sourced from FMP's own `bookValuePerShare`
  ratio field (raw stockholders' equity per share -- confirmed identical to FMP's own
  `shareholdersEquityPerShare`, i.e. **not** intangibles-stripped) off the **latest annual**
  `ratios` row, up to ~12 months stale versus the quarterly balance-sheet data this same
  calculation already used for `total_debt`/`cash_and_st_investments` (a self-inconsistency,
  not just a spec mismatch -- a comment elsewhere in the same function already cites the
  original source spec's own "latest instant, not FY-end" rule for those other two fields).
  Now computed directly from the latest quarter's balance sheet
  (`totalAssets − goodwillAndIntangibleAssets − totalLiabilities`, divided by shares
  outstanding) -- no new FMP fetch, every field was already being pulled for `debt_metrics`.
  Confirmed via real cached data: JPM $129.97 (FY2025 annual, raw equity) → $115.80 (Q2 2026
  quarter, tangible); O (Realty Income) $44.35 → $39.52 -- both moves reflect the anchor
  advancing ~2 quarters *and* intangibles being stripped, not either alone. At the time, the
  *historical* P/B ratio series feeding the mean/SD bands (`valuation.md` §3.2) was left on
  FMP's own `priceToBookRatio` (non-tangible, annual-lagged) -- documented as a deliberate,
  accepted approximation rather than a fix, since rebuilding it would need a new annual
  balance-sheet fetch this calculation didn't otherwise require. See the next entry for why
  that approximation was revisited and fixed two days later.



## Valuation: historical P/B series rebuilt onto tangible/quarterly basis (2026-08-15) (original lines 2117-2148)

- **Historical P/B series rebuilt onto the same tangible/quarterly-consistent basis as the
  point estimate above (2026-08-15)**, closing the gap the prior entry left open. Averaging a
  series computed under one book-value definition (FMP's raw `priceToBookRatio`) and
  multiplying it by a point value computed under a different one (the corrected tangible
  `book_value_per_share`) produces a number that isn't internally consistent -- this was worth
  fixing outright, not leaving as a documented approximation, once actually checked against
  real data (see below). Implementation: `step3_data.py` now also fetches
  `balance_sheet_statement`/`annual` (10yr) -- the same cache key Step 4/Step 5 already
  populate, so a cache hit with zero new FMP calls for any ticker already scored elsewhere in
  the app, not a new per-ticker cost. Each year's `historical_pb_ratios` entry is rescaled
  algebraically rather than refetched from a separate price series: FMP's own
  `priceToBookRatio = price / bookValuePerShare` for that fiscal year, so multiplying by
  `(totalStockholdersEquity / tangible_book_value)` for the same year converts it to
  `price / tangible_book_value_per_share` exactly -- the share-count term FMP's own
  `bookValuePerShare` embeds cancels out of the algebra, so no separate historical price fetch
  or reconstructed share count is needed. A year is dropped (not fabricated as zero) if its
  balance sheet can't be matched by fiscal year, a required field is missing, or the resulting
  tangible book value is non-positive -- the same "don't fabricate a meaningless multiple"
  convention `book_value_per_share` itself already uses; `pb_lookback`'s 10yr/5yr threshold is
  based on the count of years that clear these guards, not the raw FMP series length (confirmed
  the 5yr fallback still engages correctly for a thinner-history ticker, HOOD, which had only 5
  of its 7 raw years survive the guards).

  Confirmed via real cached data this was a genuine, material inconsistency, not a rounding
  concern: **JPM**'s mean P/B moved 1.61x → 2.01x, intrinsic value $186.75 → $232.75 (+24.6%,
  verdict unchanged, still overvalued); **BAC** +33.5%; **WFC** +23.3%; **O** (REIT) +25.2%,
  with its verdict flipping **fair → undervalued**; **AVB** moved essentially not at all
  (−0.2%) -- its goodwill/intangibles load is small relative to its equity, so the tangible and
  raw bases were already nearly identical for that specific ticker. This is the expected shape
  of the fix (it corrects for how much goodwill/intangibles a company carries, not a uniform
  shift applied to every ticker alike), not evidence the fix is inconsistent.



## Valuation: standard P/B method added as default, tangible demoted to custom (2026-09-14) (original lines 2149-2197)

- **New standard P/B method added, now the Bank/REIT/Property Developer default; the tangible
  method renamed to "(custom)" and demoted to manual-only (2026-09-14).** The tangible P/B
  calc above (`totalAssets - goodwillAndIntangibleAssets - totalLiabilities`) has always been
  the only P/B method, auto-selected for Bank/REIT/Property Developer. A new **standard** P/B
  method -- plain book value, `totalAssets - totalLiabilities`, no intangibles/goodwill
  subtraction -- is now the auto-selected default in that role instead; the tangible method,
  relabeled **"Price to Book (custom)"** in the UI (was "Price to Book"), is demoted to
  manual-only (Manual Calculation/Custom Valuation, new method string
  `PRICE_TO_BOOK_STANDARD` for the new default, existing `PRICE_TO_BOOK` string unchanged for
  the tangible one). An existing saved `TickerCustomValuation` row with `method="PRICE_TO_BOOK"`
  is unaffected -- `get_active_valuation` resolves purely off the stored method string,
  independent of `select_method`'s own tree, so only the *auto-selected* default changed, never
  an explicit prior manual choice.
  - **Needs no historical rescale at all, unlike the tangible series** -- confirmed empirically
    against real cached balance-sheet + shares data (JPM/O/PLD/WFC/C): FMP's own
    `priceToBookRatio`/`bookValuePerShare` ratio fields are computed off `totalEquity` (which
    already equals `totalAssets - totalLiabilities`, i.e. includes minority/non-controlling
    interest), not the parent-only `totalStockholdersEquity` -- `totalEquity/shares` matches
    FMP's reported `bookValuePerShare` exactly (to the last digit) for O and PLD. So the
    standard historical series is just `pb_raw` used directly, no rescale multiply needed.
  - **Same finding surfaced and fixed a latent bug in the existing tangible rescale**: it
    multiplied by `(totalStockholdersEquity / tangible_book_value)`, but since `pb_raw` is
    actually on the `totalEquity` basis, this understated the tangible historical P/B series
    for any NCI-bearing company -- confirmed material for **PLD** (~7.9% understatement,
    `minorityInterest` is ~7.9% of its `totalEquity`), smaller for **O**/**WFC**/**C** (~1-2%),
    zero effect for a company with no minority interest (e.g. **JPM**, `minorityInterest == 0`).
    Fixed to `(totalEquity / tangible_book_value)`, in the same change that added the standard
    method (the two are directly adjacent code).
  - **The Bank/REIT informational fields (`historical_pb_buy_signal`, `benchmark_pb_*`) now
    read off the standard basis**, not tangible -- matching what's actually displayed by
    default. The REIT dividend-yield/DPU-growth note and the Standard-company-only
    loss-making-PB liquidation reference are both unaffected (orthogonal to this change).
  - **No new engine type** -- `bands_from_mean_sd`/`run_price_to_book`
    (`scoring/step3.py`) were already fully generic over their inputs, called a second time
    with the standard-basis book-value-per-share/historical-ratios/mean/SD; only
    `data/step3_data.py` needed a parallel computation block. `Step3Inputs`/`Step3ManualParams`
    gained 5/3 new `_standard`-suffixed fields respectively, exactly parallel to the existing
    tangible ones -- no field was renamed, so every existing test/saved-parameter shape stayed
    valid. No DB migration -- `TickerCustomValuation.method`/`parameters_json` are plain `str`
    columns.
  - **Confirmed via real cached data (JPM, O, PLD -- `cache_only=True`, zero live FMP calls)**:
    intrinsic value (mean band) moves from the old tangible default to the new standard one --
    **JPM** $232.75 → $225.45 (still overvalued, 55.9% → 60.9% premium); **O** $70.94 → $75.35
    (still undervalued, −11.6% → −16.7% discount); **PLD** $141.55 → $139.58 (still fair, −0.7%
    → +0.7%). **0 verdict flips** among these three -- PLD's own *point* tangible/standard book
    values happen to be numerically identical (its latest-quarter `goodwillAndIntangibleAssets`
    is genuinely 0), so only its *historical* rescaled series differs (mean P/B 2.272x → 2.241x,
    the ~7.9% NCI effect from the bug fix above, not the method change itself).



## Valuation: full-universe verdict-flip audit (2026-09-15) (original lines 2198-2209)

- **Full-universe verdict-flip audit run before pushing the above (2026-09-15)**, since the
  3-ticker JPM/O/PLD spot-check wasn't representative on its own. Scanned all 572 tracked
  tickers (`load_full_tracked_universe`, cache-only, zero live FMP calls); 59 classify Bank
  (28) or REIT/Property Developer (31). **54 tickers behaved cleanly** (both bases produce a
  real result): 5 verdict flips (**EQIX** undervalued→overvalued -- its tangible historical
  P/B series has two ~600x outlier years from a near-zero tangible book value in that period,
  a data artifact the standard basis's smooth ~5-7x series doesn't share, so this flip is very
  likely a quality improvement, not a regression; **DLR** undervalued→fair; **KIM** fair→
  overvalued, a razor-thin ±0.4pp boundary case; **SYF**/**TFC** undervalued→fair, both Banks).
  Median |% change| in intrinsic value across the 54: **2.8%** (JPM/O/PLD's own 0-6% moves
  were on the calm end, not unrepresentative); 90th percentile 23.4%; max **CSGP** 117.8%
  (goodwill is 83.7% of its standard book value, no verdict flip either way).


## Valuation: non-positive book value bug found in 5 tickers (2026-09-15) (original lines 2210-2221)

- **5 tickers surfaced a separate, pre-existing bug: no guard anywhere in the P/B calc
  against a non-positive book value per share.** `AMT`/`CBRE`/`CCI`/`IRM`/`SBAC` -- all
  heavy-goodwill/negative-equity REITs -- have negative book value on at least one basis.
  Confirmed **CBRE was already live in production with this bug** under the old (tangible)
  default before any of this build's commits: `P/B multiple x book value` produced a negative
  "intrinsic value" (~$45.72 for CBRE) that `classify_valuation_verdict` still confidently
  called "undervalued" rather than flagging as invalid. The default-switch changed *which*
  tickers hit it (CBRE/AMT happen to have positive *standard* book value, so the switch
  accidentally fixes them; **CCI**/**IRM** have negative *standard* book value too, newly
  exposing the same bug there; **SBAC** stays a genuine "no result" on both bases either way)
  -- confirmed real, not a regression introduced by the switch itself, and fixed the same day
  (see below).


## Valuation: bands_from_mean_sd non-positive book-value guard fix (2026-09-15) (original lines 2222-2237)

- **Fixed 2026-09-15: `bands_from_mean_sd` (`scoring/step3.py`) now returns `None` when
  `book_value_per_share <= 0`**, instead of computing a negative/zero "intrinsic value" that
  the caller's own verdict logic would then mislabel. One shared choke point covers every P/B
  call path -- `run_price_to_book` (Auto Calculation, both tangible and standard bases) just
  inherits the `None` via its own delegation, and `run_manual_calculation`'s two PB branches
  (Manual Calculation/Custom Valuation, also both bases) gained an explicit null-check
  returning a distinct `"Book value per share must be positive for PRICE_TO_BOOK[_STANDARD]"`
  error rather than crashing on `None.bands`. Every existing consumer of `pb_result`/
  `pb_result_standard` in `step3_data.py` was already null-safe (written for the "too little
  historical data" case), so this collapses into that same existing "no result" shape for
  free -- zero changes needed there. `book_value_per_share`/`book_value_per_share_standard`
  themselves (the raw point figures) are untouched -- a real negative book value is still
  shown as-is, only the derived P/B multiple is blocked. Confirmed via a full-universe
  cache-only re-sweep: **CCI/IRM now correctly read `None`/`None`/`None`** (previously a
  fabricated −$58.96/−$96.75 "undervalued"); **CBRE/AMT unchanged** (their standard-basis
  result was already valid); **SBAC unchanged** (`None` on both bases, as before).


## Valuation: 9 more negative-intrinsic-value tickers, 20-year engine and PSG guards (2026-09-15) (original lines 2238-2272)

- **Same broader sweep found 9 more tickers with the same class of bug via a different
  mechanism -- investigated and fixed 2026-09-15.** Re-scanning all 572 tickers for *any*
  negative `intrinsic_value_per_share` (any method, not just P/B) found **D, DLTR, ES, ETSY,
  FE, GM, HOOD, URI** (DNI_NORMALIZED/DFCF) and **ECHO** (PSG), each showing a fabricated
  negative-dollar "undervalued" verdict. Per-ticker investigation found two distinct root
  causes, not the "negative growth/current-value inputs" originally guessed:
  1. **`run_20yr_engine`** (shared by DCF/DFCF/DNI/DNI_NORMALIZED/CF_NORMALIZED/
     FCF_NORMALIZED) subtracts gross `total_debt/shares_outstanding` with no floor. In all 8
     affected cases, `current_value` and every growth rate were genuinely positive and the
     pre-debt-adjustment value (`intrinsic_value_pre_adj`) was real and healthy -- e.g. **D**
     (Dominion Energy): $53.13/share pre-adjustment, swamped to -$7.27 purely by
     `total_debt` ($53.4B) / `shares_outstanding` (879.5M shares) = $60.74/share of gross
     debt, exceeding it. Same shape for **ES**/**FE** (regulated-utility infrastructure
     debt), **GM** (captive-finance-arm debt), **HOOD** (margin-lending debt), and
     **DLTR**/**ETSY**/**URI** (moderate debt combined with a currently-depressed
     current_value). Every debt figure is a real balance-sheet fact, not a data artifact --
     a genuine methodology gap, not a data-quality issue.
  2. **`run_psg`**: `fair_psg_ratio * sales_per_share * projected_growth_rate * 100` has no
     guard on `projected_growth_rate`'s sign. **ECHO**'s real Step 2 growth rate is -13.07%
     (its historical revenue CAGR is a healthy +17% over 10y, clearing the aggressive-growth
     threshold that gets it *into* PSG in the first place, but its *forward* analyst-estimated
     growth is negative) -- multiplies straight through into -$136.34.
  - **Fix, same pattern as the P/B guard above**: `run_20yr_engine` returns `None` when the
    *final* per-share value (after the debt/cash adjustment) is `<= 0` -- an output check,
    since no single input is invalid on its own, only the combination. `run_psg` returns
    `None` when `projected_growth_rate < 0` -- an input check, since growth's sign alone
    determines the formula's sign (an input check and an output check are equivalent here,
    unlike the engine). Every call site (`data/step3_data.py`'s Auto Calculation dispatch,
    `run_manual_calculation`'s two corresponding branches) needed an explicit null-check
    added -- unlike the P/B fix, these dispatch sites were NOT already null-safe, since
    `run_20yr_engine`/`run_psg` had never been able to return `None` before. Confirmed via a
    full-universe cache-only re-sweep: **all 9 named tickers now read `None`/`None`/`None`**;
    zero negative `intrinsic_value_per_share` remain anywhere in the 572-ticker universe
    (any method, any company type); zero exceptions.

