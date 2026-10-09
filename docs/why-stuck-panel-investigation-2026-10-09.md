# "Why might it be stuck?" panel: investigation (2026-10-09)

Report-only. No code, schema or DB change; nothing here feeds the Overall score, verdict or any weight. Cache only, zero FMP calls
(read-only SQLite handle on `fathom.db`, scratch scripts outside the repo, deleted afterwards). Universe: the 582 tracked stocks
(`load_tracked_universe`); "good" = stored Overall verdict Strong Pass / Pass / Pass with caution (19 / 100 / 79 = 198).

## Part A: earnings quality and capital allocation

**1. Fields and coverage.** Every field exists in the cached annual statements, all 10 completed fiscal years, no new fetch:
cash flow `stockBasedCompensation`, `commonStockRepurchased` (negative), `commonStockIssuance`, `netCommonStockIssuance`,
`netDividendsPaid` / `commonDividendsPaid`, `netCashProvidedByOperatingActivities`, `capitalExpenditure`, `freeCashFlow`; income
`netIncome`, `revenue`, `weightedAverageShsOutDil` / `weightedAverageShsOut`. The cleaned loader (`read_cached_inputs` +
`build_statement_view(use_balance_sheet=False)`) blanks placeholder / scale-broken cash-flow rows to None, so SBC and buybacks inherit
that cleaning; income rows (shares) are not cleaned by it. Last-5y row-level non-null: 99.7% for every cash-flow field, 100% for income.
Real gaps: (a) **SBC**: FMP serves `0` for "not reported" (`key_metrics.stockBasedCompensationToRevenue` is 0 too, no fallback). 101 of
573 tickers with 5+ years have fewer than 3 non-zero SBC years in the last 5 (46 Standard, 20 Utility, 13 Bank, 12 Insurance, 7 Commodity,
3 REIT), including WMT (7 of 10 years zero), GM, UAL, CNI, ASML, PCAR. (b) 9 tickers have under 5 fiscal years (ALAB, CRWV, FDXF, FLY,
HONA, PSKY, Q, SPCX, VYLR). (c) Shares are split-adjusted by FMP (AAPL 2016 = 22.0 bn, NVDA 2017 = 26.0 bn); a scan against the 62
recorded `CorporateEvent` splits found no unadjusted step in any cached series today.

Company-type matrix I would use (kind = shared classifier; Commodity = Step 1's local rule):

| Check | Standard | Commodity | Bank / Insurance | REIT | Utility |
|---|---|---|---|---|---|
| Cash conversion (FCF / NI) | yes | yes (10y averages the cycle) | exempt (CFO exempt in Step 1) | exempt (depreciation) | exempt (FCF structurally negative: median FCF/NI -0.8) |
| SBC burden | yes (% rev and % FCF) | % rev only | % rev only | % rev only | % rev only |
| Share-count trend | yes (2% / 5%) | yes | yes (banks buy back: median -1.5 to -2.3%/yr) | raised bars 4% / 8% or neutral (issuance is the model: median +1.8%/yr, O +21%, VICI +16%) | raised bars 4% / 8% |
| Payout vs FCF | neutral figure only | neutral figure | vs NI, neutral | n/a | n/a |

Assessed counts: cash conversion 392 (369 Standard + 23 Commodity; 67 of the 468 eligible are skipped for NI cumulative under 2% of
revenue, 9 for under 5 years), SBC 472, share count 573.

**2. Candidate metrics (5-10y, completed fiscal years, cumulative sums not means of ratios).**

| Metric | Percentiles (all assessed) | Verdict |
|---|---|---|
| FCF / net income, cumulative | p5 -0.79, p25 0.81, p50 1.07, p75 1.37, p90 2.20 | Useful; needs NI floor (cum NI >= 2% of cum revenue) or DDOG reads 14.7, WDAY 32.3 |
| SBC % revenue, last 5y | p50 1.1, p75 2.9, p90 8.9, p95 17.2 | Useful, robust |
| SBC % FCF, last 5y | p50 7.6, p75 15.9, p90 41, p95 92 | Useful but unstable when 5y FCF is near zero (ORCL 1,602%, AMZN 238%); sign of SBC-adjusted FCF is the sturdier read |
| SBC-adjusted FCF (5y FCF minus SBC) | n/a | Use as a sign test only |
| Buyback cover of SBC (gross buyback / SBC) | p25 0.94, p50 3.9 | Good companion: <=1.0 on a heavy-SBC name means the buyback only neutralizes SBC (TTD 1.0, CRWD 0.0, DDOG 0.0); 50 of 81 names with SBC >= 5% of revenue |
| Diluted share count, 5y CAGR (jumps beyond +-60%/yr neutralized) | p5 -5.5, p25 -2.2, p50 -0.6, p75 1.0, p90 5.4, p95 9.4 | Best single signal |
| Shareholder yield (dividends + net buyback) / FCF, 5y | p25 48%, p50 74%, p75 100%, p90 132% | **Weak**: over 120% flags 24 good names that are healthy (LMT, UNP, TXN, LOW, VRSK, ZTS, TSCO); drop as a state, show as a figure |
| Buybacks while Undervalued vs Overvalued | not derivable | No historical Valuation verdict is stored. Cheap proxy: buyback-weighted FY-end earnings yield / own median (`key_metrics.earningsYield`): p5 0.86, p50 1.06, p95 1.84, only 13 of 461 under 0.8, 3 good names (CLS 0.71, MELI 0.52, PTC 0.70). Too flat to be worth a state. Revisit once the history table in item 7 has a year of data |

**3. Can the Step 1 engine score share count?** It runs (`assess_series(shares, "dollar")`, direction inverted by feeding `1/shares`)
and the ordering is sensible: AAPL 90, BKNG 97, GM 87, WMT 77, MSFT 71, NVDA 70, COST 68, TEAM 60, ABNB 47, ADI 31, CRWD 28, TSLA 29,
UBER 39, PLTR 24, AMD 10 (raw shares with the dollar kind gives the wrong direction). But the semantics do not fit: a dollar series is
supposed to grow (flat = 68, full score at 6%/yr), so a stable share count, which is fine, lands just under the Pass line; a one-off
stock deal (AMD +28% in one year) scores like ten years of SBC creep because both are "dips"; the output is a 0-100 score that invites a
weight. **Recommendation: the simple rule**, 5y CAGR of diluted shares with structural jumps neutralized, three bands (shrinking <= -1.5%,
neutral, dilution >= 2% / >= 5%), plus a steady-vs-one-off split: if one year carries 60% or more of the 5y dilution it is "one large issuance
in FY20XX (offering or stock deal)" and stays neutral. That removes 39 of 99 dilution flags (ADI, SCHW, SPGI, STE, AMD, AVGO, TDY) and keeps
CRWD, UBER, PLTR, DDOG, RDDT.

**4. Simulation, proposed thresholds** (states: ok / caution / concern):
cash conversion < 0.7 / < 0.4; SBC: caution at >= 8% of revenue or >= 30% of FCF, concern at >= 15% of revenue, >= 60% of FCF, or
SBC-adjusted 5y FCF <= 0; steady dilution >= 2% / >= 5% (REIT, Utility 4% / 8%).

- Whole universe: 157 of 582 caution or worse, 89 concern.
- **Good set (198): 35 flagged caution or worse (17.7%), 8 concern, 5 with two or more checks.** By verdict: Pass 17 of 100, Pass with
  caution 13 of 79, Strong Pass 5 of 19. Good and Undervalued (95): 18 flagged.
- With the payout check added the good-set count would be 61 (31%): that is why it is demoted.

Flagged good-set samples, with sanity check:

| Ticker | Verdict | What trips | Sanity |
|---|---|---|---|
| CRWD | PWC | SBC 22% rev / 78% FCF, 3.5%/yr steady dilution | True positive |
| DDOG | PWC | SBC 21% rev / 76% FCF, 3.9%/yr, buyback cover 0.0 | True positive (its FCF/NI of 14.7 is a NI-near-zero artifact; the floor suppresses it) |
| TTD | PWC | SBC 23% rev / 84% FCF, buyback = SBC, shares flat | True positive: buybacks only offset SBC |
| ARM | PWC | SBC 17% rev / 96% FCF | True positive (IPO RSUs) |
| RDDT | Pass | SBC 26% rev, dilution 4.4% | Partly artifact: IPO-year RSU spike and preferred conversion; needs a recent-IPO guard |
| META, GOOG/GOOGL | Pass / Strong | SBC 30-36% of FCF | Correct "review", informational |
| AMZN | Pass | SBC-adjusted 5y FCF <= 0 | Capex-cycle artifact: 5y FCF is thin because of capex, SBC is 3.4% of revenue; should read caution at most |
| PODD, LLY, NFLX, JBHT | Pass | FCF/NI 0.2-0.5 | Real but transient capex build-outs; caution is right, concern (PODD 0.2) is arguable |
| IBKR | PWC | dilution 6.8%/yr | **Artifact**: Up-C structure, the diluted count absorbs IBG Holdings unit conversions; not SBC creep |
| ADI, SCHW, SPGI, AVGO | mixed | 4-6%/yr dilution | One-off stock deals (Maxim, TD Ameritrade, IHS Markit, VMware); neutral under the steady-vs-one-off rule |

Clean good-set samples (all assessed checks ok): PH, AMAT, AME, HLT, TPL (Commodity), TJX, HD, COST, ZTS, TT, QCOM, TME, WM, TMO, CME;
negative-equity serial buyers MCD, HD, BKNG, AZO, LMT, UNP, LOW come out clean (their only trip was payout over 120%, now dropped).
Data-artifact cases: TEAM (Fail, outside the set) shows the pattern well: NI negative so FCF/NI is n/a, SBC $1.6 bn against FCF $1.35 bn so
SBC-adjusted FCF is negative, buyback $1.8 bn but shares only -3% in the latest year; FLY (3 fiscal years, SBC jumps 10x in the IPO year)
is excluded by the 5-year minimum; MSTR, HUT, IONQ, ASTS, PARA have de-SPAC / recap jumps (up to +148,000% a year), 42 tickers have at
least one jump neutralized.

## Part B: "stuck check"

**5. Counts** (Overall Pass or Pass with caution, Valuation Undervalued, Weinstein stage x 5Y vs SPY). Total 89 (Strong Pass adds 6).

| Stage | Outperform | Underperform |
|---|---|---|
| 1 Base | 0 | 2 |
| 2 Advance | 7 | 22 |
| 3 Top | 4 | 7 |
| 4 Decline | 8 | 39 |

Strong Pass + Undervalued (6): Advance 2 / 3, Decline 0 / 1. Stage 4 + underperform (39) is the core "stuck" bucket. Mansfield RS
(vs SPY) is below 0 for 76 of the 89; the monthly momentum rank (snapshot 2026-09-30, 410 ranked) covers 84 of 89.
Top-10 per bucket by Overall score: Base: RSG, BF-B (only two). Advance: ALLE, AMZN, JNJ, IBKR, ICE, WAB, USB, RMD, VRSN, SEIC.
Top: AVGO, SHW, WRB, ACGL, MO, WTW, JBL, AVY, EW, CINF. Decline: CMG, JKHY, BKNG, ZTS, TSCO, ADSK, VRSK, TYL, TJX, GD.

**6. Relative strength vs own sector ETF: feasible, cache only.** The Weinstein engine's `weinstein_mansfield_rs` is one number against the
single global `rs_benchmark` (SPY); my recompute of it from cached bars matches the stored value exactly (corr 1.0, max diff 0.0). It is
not per sector. Present: all 11 SPDR sector ETFs plus SPY have 1,259 daily bars (2021-10-04 to 2026-10-08) in `SharedBarsCache`, kept warm by
the nightly Sector Heatmap and Trend jobs; FMP's 11 sector labels map one-to-one to the 11 SPDRs. Missing: the sector-to-ETF map, a
sector-relative Mansfield call (the engine's ratio math with another benchmark: ~10 lines on `resample_to_weekly`), one nullable column
(`TrendAnalysis.weinstein_mansfield_rs_sector`) written by `nightly_trend_calculation` (the batch already reads these symbols), and a UI
slot (Mansfield is drawn only in `WeinsteinStageCard`). Dry run on the 95 good + Undervalued names: 60 lag both SPY and their sector (stock
specific), 18 lag SPY but lead their sector (a sector-wide drag, e.g. AMZN, MA, CB, CNI, MO, PYPL), 4 lead SPY but lag their sector, 13 lead
both. So it separates "the stock" from "the sector" for about a fifth of the set. Caveats: FMP sector is not exactly GICS, the sector ETF
contains the stock (self-comparison bias for mega caps in XLK), SPDRs are cap-weighted.

**7. Date a ticker first became Pass + Undervalued.** Nothing historical exists: `TickerScore` is latest-only (upserted; `computed_at`
only), `ScoreRecomputeRun` is run status, and `backups/` keeps 5 files (newest 7 daily + 4 weekly), so at most the last ~6 days can be
rebuilt. Those backups show the state is **very flappy**: `valuation_verdict` changes for 65-84 of 611 tickers per day (11-14%), and the
Pass + Undervalued set went 146 (10-04), 139 (10-07), 92 (10-08), 98, 95 (10-09), the 10-08 drop partly the Overall redesign. A naive
"first became" would reset constantly, so any since-date needs hysteresis (for example 5 consecutive daily recomputes to enter, 5 to leave).
Options: (a) two nullable `TickerScore` columns (`pass_uv_since`, `pass_uv_last_seen`) set in `compute_ticker_score` from the previous row, a
few hours, clock starts at deploy; (b) **recommended**: an append-only daily `TickerSignalHistory(ticker, as_of_date, overall_verdict,
valuation_verdict, weinstein_stage, perf_5y_vs_spy_status)` written by the 3:25 recompute, about 580 rows a day (~15 MB a year), which also
gives the flip rate and a way to validate every threshold in this document; about half a day with tests and a retention rule. Start (b)
first because its value only accrues with time.

## Design output

**8. Panel.** One card at the bottom of the **Analysis tab**, below Debt, titled "Why might it be stuck?" with a muted "Context, not
scored" subtitle, for every stock (ETFs excluded). Analysis is where users already read verdict reasoning, and the card carries both
halves (price context from the Technical data, fundamentals quality from the statements), which neither the Technical tab nor the header
can hold. It follows the `ChecklistCard` / `AnalysisSectionCard` shell (collapsible rows, expanded when any row is amber), never a score
number, never in `OverallAssessmentCard`, no weight, no `STEP_WEIGHTS` entry. The speculative-growth precedent (a pill that appears only
when meaningful, a tooltip listing the figures, a denormalized boolean for the Screener) maps to: each row = label, one figure in mono, one
pill; the card header pill summarizes ("2 to review" amber, or "Nothing to flag" neutral).

Rows and states (two states plus not-applicable; the pill carries the tone, the figure stays neutral):

| Group | Row | OK | Review (amber, `caution` tone) | Not applicable (`missing` Badge) |
|---|---|---|---|---|
| Price | Weinstein stage (+ since date) | Stage 1 / 2 | Stage 3 / 4 | no stage yet |
| Price | RS vs SPY (Mansfield) | >= 0 | < 0 | no benchmark |
| Price | RS vs own sector (new) | >= 0 | < 0 | no sector map |
| Price | 5Y vs SPY | outperform | underperform | no data |
| Price | Momentum rank | top half | bottom half | not Moat-rated / not ranked |
| Quality | Cash conversion | >= 0.7 | < 0.7 | exempt type, loss-making, < 5 years |
| Quality | SBC burden | under thresholds | over thresholds | "Not reported" (FMP gap) |
| Quality | Share count | shrinking or flat | steady dilution; a one-off issuance shows as a neutral note | < 5 years |

Wording: never "Fail" / "May not pass" (the slate `not-pass` token is reserved for that), no red (red is Stage 4 / No moat / Overvalued
verdicts); amber is the existing "Review" family. I would collapse caution and concern into one amber state with the figure beside it:
two cut-offs are two cliffs and the philosophy is graduated, so the figure does the grading. Open decision below.

**Denormalize onto `TickerScore`?** Yes, but small and later: `quality_review_count` (0-3) and optionally `stuck_price_count`, computed in
`compute_ticker_score` from the cached rows already loaded (my full-universe pass takes seconds), added through `_add_missing_columns` (no
backfill), exposed on the API schema and `lib/api/types.ts`, one client-side `MultiSelectDropdown` in the Screener (`filtersFromSaved`
already drops unknown keys, so saved views stay safe). No `SCORE_FORMULA_VERSION` bump because no Overall arithmetic changes; rows refresh
on the next full recompute. Cost: roughly a day with tests; the risk is Screener clutter, not performance. Sector RS would add one more
column on `TrendAnalysis` (copied to `TickerScore` only if filtered on).

**9. Risks and conflicts.**

- **FMP gaps look like "clean".** SBC = 0 for 17.6% of eligible tickers; must render "Not reported", never OK.
- **Ratio blow-ups**: FCF/NI with NI near zero (DDOG 14.7, WDAY 32.3), SBC/FCF with near-zero 5y FCF (ORCL, AMZN). Needs the NI floor and the sign-based SBC-adjusted test.
- **Capex cycles** (AMZN, LLY, PODD, NFLX) read as poor cash conversion; compare the last 3y with the 10y and prefer "caution" over "concern".
- **M&A and offering dilution is not SBC creep** (ADI, SCHW, SPGI, AMD, SW, EQT); the steady-vs-one-off split handles most, the cached statements cannot separate a stock deal from an offering.
- **Share-count structure artifacts**: Up-C / dual-class (IBKR), de-SPAC and IPO conversions (RDDT, HUT, IONQ, ASTS, PARA, MSTR), splits not yet reflected in older cached years. History protection keeps older cached periods when FMP answers shorter, so a mixed adjusted / unadjusted series is possible in future; the scan found none now. A 3:2 split (+50%) would sit under the +-60% neutralization, so use the `CorporateEvent` split rows to catch it rather than the threshold alone.
- **REIT / Utility issuance** is the model; thresholds or neutral display needed.
- **Philosophy.** The scoring principle is trend shape, graduated, no cliffs; bands on ratios are cliffs. Mitigated by showing the figure, two states only, no score, no sort and no Overall effect. The Step 1 engine on shares would honour the philosophy but fails on semantics (item 3).
- **Overlap, not conflict**: FCF/NI overlaps Step 1 CFO / FCF / Net Income (which score level and trend, not the ratio) and Step 4's cash-conversion cycle; share count overlaps Growth Rate's EPS-versus-revenue basis note (`growth-rate.md`); payout vs FCF overlaps Debt. Another reason to keep it informational.
- **Spec check.** No spec describes SBC, dilution or buyback metrics, so nothing conflicts. Code and specs agree on everything I relied on (Step 1 reads cleaned completed fiscal years, FCF = CFO + capex, Weinstein RS is one global SPY benchmark, `TickerScore` carries `valuation_verdict`, `weinstein_stage`, `perf_5y_vs_spy_status` but not Mansfield). Only drift is counts: `financials.md` calibrates on 588 tickers, `TickerScore` comments say "580 other cached profiles"; the live tracked stock universe is 582.
- **Daily churn** (item 7) means any "time-stop" counter must be hysteresis-based.

## Recommended build order

1. `TickerSignalHistory` daily snapshot (starts the clock, no UI, no risk).
2. Pure `scoring/quality_review.py` + cache-only `data/quality_review_data.py` (cash conversion, SBC, share count, with the guards above) and an endpoint; unit tests with the sample tickers.
3. Sector-relative Mansfield on `TrendAnalysis` (nightly job, one column).
4. The Analysis-tab card.
5. `TickerScore` denormalization + Screener filter, only if the card proves useful.
6. A time-stop / since-date, once the history table has weeks of data.

## Open decisions for you

1. Drop shareholder yield vs FCF as a state (show the figure only)? Recommended yes.
2. One amber "Review" state (figure carries the grade), or caution and concern as two levels?
3. Thresholds: cash conversion 0.7, SBC 8% revenue / 30% FCF, dilution 2% (REIT and Utility 4%), steady-vs-one-off at 60%, 5-year minimum.
4. REIT and Utility share count: raised bars, or shown neutral?
5. Location: Analysis tab card (recommended) versus Technical tab or a header pill; show for every stock or only Pass-or-better?
6. History: append-only table (recommended) versus two `TickerScore` columns; hysteresis length.
7. Sector RS: accept FMP-sector-to-SPDR mapping and the self-inclusion bias?
8. SBC "Not reported" blind spot (17.6%): accept, or cross-check against SEC EDGAR (`sec_company_facts` exists for 214 tickers)?
9. Denormalize and add a Screener filter now or after the card has been used for a while?
