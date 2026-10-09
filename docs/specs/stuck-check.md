# "Why might it be stuck?" card (stuck check)

An informational card at the bottom of the Analysis tab, for every stock (never an ETF/fund page): earnings quality, capital allocation,
price context and the fundamentals trend for a ticker that scores well and still does not move. **Context, not scored.** Built from
`docs/why-stuck-panel-investigation-2026-10-09.md` (its thresholds were simulated there); this spec is the rules as built.

Code: `scoring/stuck_check.py` (pure, no I/O: rows, labels, thresholds), `data/stuck_check_data.py` (assembles the inputs from cache),
`GET /api/tickers/{ticker}/stuck-check` (cache only), `data/stuck_check_settings.py` + `GET/PUT /api/config/stuck-check` +
`POST .../reset` (Settings), `components/stuck/StuckCheckCard.tsx`, `lib/stuckCheck.ts`, `lib/hooks/useStuckCheck.ts`. The daily log:
`core/models.py::TickerSignalSnapshot`, `data/signal_snapshot_data.py`, `pipeline/nightly_signal_snapshot.py`,
`scoring/good_undervalued.py`.

## Hard rules

- **The card feeds nothing**: not Overall, not any step or verdict, not `TickerScore`, not the Screener; no badge, no summary count, no
  header pill. Subtitle: "Context, not scored".
- **Labels only**, four of them: **OK**, **Flagged**, **Not applicable**, **Not reported**. Flagged is a plain amber tag (`Status`
  tone `warn`, compact); the other three are quiet neutral tags. No red, and no "May not pass" / "Review" / "Pass" wording as a label.
  A figures-only row has no label.
- **Cache only, no FMP call, nothing written.** It reads `FundamentalsCache` (cleaned through the shared statement loader, completed
  fiscal years only), the stored `TickerScore` row and `SharedBarsCache`. Works with every FMP data group off; `GroupOffBadge` for
  `daily_prices` shows on the card when the bars are not refreshing (the Analysis tab's own badge covers `fundamentals`).
- **Price rows are read, never recomputed**: Overall verdict, Valuation verdict, Weinstein stage and its since-date, 5Y vs SPY come
  straight from the stored `TickerScore` row.
- Out, deliberately: segment revenue, the business-threat note, a Screener filter, a flag count on `TickerScore`, momentum rank, Mansfield
  RS (the investigation proposed some of these; later rounds).

## Rows

Statements are the cleaned annual rows (`helpers/statement_view.build_statement_view`): placeholder and scale-broken cash-flow rows are
blanked, so SBC, buybacks and FCF inherit that. FCF = cash from operations + capital expenditure (already negative). "Last N fiscal
years" means the N newest completed fiscal years the cache holds.

| # | Row | Figures | Label |
|---|---|---|---|
| 1 | Cash conversion | FCF / net income, cumulative over the last 3 and the last 10 fiscal years | **Flagged only when BOTH are below the line** (default 0.7), else OK. A window whose cumulative net income is under 2% of its revenue has no ratio ("n/m"); no 3-year ratio = Not applicable. Under 3 years = Not reported |
| 2 | Stock-based compensation | latest FY $ and % of revenue; the 5-year total % of revenue; 5-year total % of FCF ("n/m" when 5-year FCF is zero/negative or the share exceeds 100%) | Flagged if the 5-year % of revenue > SBC-revenue line (8) **or** the % of FCF > SBC-FCF line (30); n/m counts as over. Not reported when SBC is zero/missing in 3+ of the last 5 FYs |
| 3 | FCF after SBC | 5-year total and latest FY, in $ and % of revenue | Flagged if the 5-year total <= 0 or the latest FY < 0. Not reported follows row 2 |
| 4 | Buybacks vs SBC | gross buybacks as a multiple of SBC over the window, or "No buybacks" | figure only; the row is shown only when SBC >= 5% of revenue over the window (and the window has 3+ FYs) |
| 5 | Share count | change per year of diluted shares over the post-listing window (last 6 FYs at most, min 3) | Flagged if > share-growth line (2%/yr). If one FY carries >= the one-off line (60%) of the cumulative dilution: **OK** with the note "One-off issuance in FY20XX carries N% of the dilution". REIT/Utility: figure, no label |
| 6 | Shareholder yield | dividends + net buybacks, and that as % of 5-year FCF ("n/m" when FCF <= 0) | figure only |
| 7 | Price context | Overall verdict, Valuation verdict, Weinstein stage (+ since date, lower-bound caveat), 5Y vs SPY | figures only, neutral text |
| 8 | Relative strength | return minus the sector ETF over 6M and 12M (headline), 1M and 3M, plus 6M and 12M vs SPY | figures only; each figure carries "in line" (within the band, default +/-2 pp), "leads" or "trails". Note when the stock is over 10% of its sector's tracked market cap |
| 9 | Margins | operating margin first-3y average vs last-3y average over the last 5 FYs, and the slope per year; gross margin the same | figures only |
| 10 | Growth | 5-year revenue CAGR vs the sector median, and the percentile ("93rd percentile"); latest FY growth, and vs the stock's own CAGR | figures only. Note when the CAGR base year is a COVID trough |
| 12 | ROIC trend | earliest and latest of the last 5 FYs, slope per year | figures only; Standard types only |

(Row 11 was dropped.) **Footer:** "Nothing flagged (k of 4 labelled rows assessed)" when none of rows 1, 2, 3, 5 is Flagged; k counts
those four rows that are OK or Flagged (Not applicable, Not reported and an unlabelled row do not count). Nothing when any is Flagged.

### Details that are interpretations of the brief

These are the places the brief left a choice; each is one constant or function in `scoring/stuck_check.py` and is listed under the open
questions in the build report.

- Rows 2-3 flag on the **5-year totals** (the investigation's cumulative basis), not on the latest FY alone; the latest FY is shown.
- The **%-of-FCF half of row 2** is "not assessed" (a note, no flag) for Bank / Insurance / REIT / Utility, following the investigation's
  matrix ("% rev only"): their FCF is not comparable and a negative 5-year FCF would otherwise flag on n/m alone.
- **One-off share** is measured on the log change of the share count: the largest single-year step / the whole window's step.
- **Percentile** = share of the sector's tracked stocks with a strictly lower 5-year CAGR; the median and percentile need 5+ tracked
  sector stocks with 6 FYs of revenue.
- **Gross margin is not shown** when its last-3-year average is at or above 99% (FMP reports about 100%, `financials.md` "Known
  weaknesses"; there is no per-ticker "unreliable" list in that file) and for Banks (FMP's gross-profit break, Step 1's margin exemption).
- **Return windows** are calendar months back from the last bar on or before a common end date (the oldest of the stock's, the sector
  ETF's and SPY's last cached bar); a window the cache does not reach back to is blank.
- **Net buybacks** = minus FMP's `netCommonStockIssuance`; dividends = `netDividendsPaid` (else `commonDividendsPaid`).

## Exemptions

- **By company type** (`classify_company_type`): Bank, Insurance, REIT/Property Developer and Utility show **Not applicable** on rows 1
  and 3 ("Free cash flow is not comparable for a ..."): Step 1 already exempts CFO and FCF for Bank/Insurance/REIT, depreciation
  swamps a REIT's FCF, and a Utility's FCF is structurally negative (median FCF / net income -0.8). Row 5 is figure-only for REIT and
  Utility (issuance is the model: O +21%/yr). Row 12 is Standard only.
- **By ticker, hand-maintained** (Settings; ticker + reason + which rows). Seeded: **IBKR** (broker: customer cash and segregated funds
  distort cash flow; the Up-C structure's diluted count absorbs IBG Holdings unit conversions, 6.8%/yr that is not SBC creep) exempts
  rows 1, 2's %-of-FCF part, 3, 5 and 6; **GM** (captive finance: financing receivables run through operating cash flow) exempts rows 1, 3
  and 6. An exempt row shows Not applicable with the reason.
- **Post-listing window** (rows 2, 3, 4 and 5): only fiscal years that began on or after the profile's `ipoDate` (the first full FY after
  listing; IPO-year RSU spikes and preferred conversions are not creep). With fewer than 3 such FYs, row 5 is Not applicable and rows
  2-3 show the latest FY figure only, no label (RDDT: 1 FY, ARM: 2, HOOD: 4, FLY: 0 = Not reported). An unknown IPO date keeps every FY.

## Settings (Settings > Why might it be stuck?, directly after Score weighting)

`StuckCheckSettings` singleton row (lazy-seeded, 5 s in-process cache like the score weights), edited with one Save and a Reset to
defaults (no confirmation: nothing recomputes). Changes take effect on the next ticker-page load; there is no recompute and no
`weights_version`/`SCORE_FORMULA_VERSION` change.

| Setting | Default | Bounds |
|---|---|---|
| SBC limit, % of revenue | 8 | 1 - 50 |
| SBC limit, % of FCF | 30 | 5 - 100 |
| Cash conversion line | 0.7 | 0.1 - 1.5 |
| Share count growth per year | 2 (%) | 0.5 - 10 |
| One-off exception | 60 (%) | 30 - 95 |
| Sector in-line band | 2 (pp) | 0.5 - 10 |
| Time-stop smoothing | 5 (trading days) | 1 - 20, whole |
| Exemption list | IBKR, GM | up to 100 entries; ticker unique; reason 1-300 chars; at least one row |

The bounds are `scoring/stuck_check.py::STUCK_BOUNDS` (a test pins `StuckCheckSettingsIn` to them). Everything else stays in code: the
window lengths (3/10 years, 5-year SBC window, 6-year share window), the 5% buyback gate, the 10% weight note, the COVID rule (base FY
at least 15% below the prior FY, base FYE between 2020-03 and 2021-03) and the company-type exemptions.

## Daily snapshot log

`TickerSignalSnapshot`: append-only, unique `(ticker, snapshot_date)`: stored Overall verdict, Valuation verdict, Weinstein stage,
`good_and_undervalued` (Pass / Strong Pass / Pass with caution Overall **and** a stored Valuation verdict of undervalued) and the source
row's `computed_at`. Written by `pipeline.nightly_signal_snapshot` at **3:28 AM**, after the 3:25 recompute and before the 3:30 backup, for
every ticker in `load_tracked_universe` that has a `TickerScore` row; database only, zero FMP calls; a same-day re-run inserts nothing
and never updates a row. About 582 rows a day, **~25 MB a year** including both indexes (119 bytes a row, measured on the real universe).
No retention rule.

`scoring/good_undervalued.py::good_and_undervalued_since(days, smoothing_days, trading_days)` (and `data/signal_snapshot_data.py::
good_undervalued_since_for`) return the smoothed since-date: it starts on the first in-state trading day and resets only after
`smoothing_days` **consecutive trading-day** snapshots out of the state (weekend and holiday snapshots and missing snapshots count as
neither). No UI reads it yet. The log starts the day the job first runs, so an older state is reported from the first logged day.

## Open follow-ups

- **IBKR and GM in Step 1 (Financials).** The exemptions above stop the card from drawing a cash-flow conclusion for these two, but
  Step 1 still scores their CFO and FCF series as Standard companies (they are not Bank/Insurance/REIT/Commodity), so the customer-cash
  distortion (IBKR) and the financing-receivable flows (GM) still reach the Financials score. Not changed here: a Step 1 change moves
  `SCORE_FORMULA_VERSION`. Decide whether to treat them like the other CFO-exempt types in `data/step1_data.py::_detect_exemption`.
- The investigation's other ideas: sector-relative Mansfield RS stored on `TrendAnalysis`, a Screener filter and a `TickerScore` flag
  count, and a visible time-stop built on the log.
