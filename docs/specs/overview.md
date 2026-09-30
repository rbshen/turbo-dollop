# How Fathom scores a company

Fathom runs a fundamentals screen on any US-listed ticker. When you open a ticker page, you'll
see several tabs: **Summary**, **Financials**, **Ratios**, **Analysis**, **Valuation**,
**Economic Moat**, **Analyst Ratings**, and **Technical**. This overview explains how the
**Analysis** tab's score is built and how it relates to the **Valuation** tab, which is
calculated completely separately.

## The Analysis tab: Overall Assessment

The Analysis tab blends four automated checks plus one manual rating into a single **Overall
Assessment**:

| Card | What it checks |
|---|---|
| **Financials** | Revenue, Net Income, Cash From Operations, Margins, and Free Cash Flow — see [Financials](financials.md) |
| **Growth Rate** | Forward analyst growth expectations — see [Growth Rate](growth-rate.md) |
| **Profitability** | Return on Equity, Return on Invested Capital, Accounts Receivable trend, and Cash Conversion Cycle — see [Profitability](profitability.md) |
| **Debt** | Short-term liquidity, leverage, and debt service burden — see [Debt](debt.md) |
| **Economic Moat** | A manual, judgment-based competitive-advantage rating you set yourself — see [Economic Moat](economic-moat.md) |

Each of the four automated cards produces its own score (0–100) and verdict (Fail / Pass /
Strong Pass, or occasionally "Pass with caution" — see the [Glossary](glossary.md)). The
Overall Assessment combines them into one number using these weights:

| Component | Weight |
|---|---|
| Financials | 24% |
| Growth Rate | 10% |
| Profitability | 20% |
| Debt | 15% |
| Economic Moat | 31% |

These weights reflect a deliberate design choice: Economic Moat — a qualitative read on
whether a company has a durable competitive advantage — carries the single largest weight, on
the view that a strong moat matters at least as much as any one quarter-to-quarter financial
metric. Among the four automated checks, Financials carries the most weight since it's the
most foundational read on the business, while Debt was deliberately weighted above Growth Rate
(2026-07-31 rebalance) so that a genuine debt problem can't be fully diluted away by strength
elsewhere — see [Debt](debt.md), and docs/archive/claude-md-history-scoring.md for the
investigation behind that rebalance. Its known, deliberate limits are described under "Overall
weighting rebalance" below.

The weight table lives in two places that must never drift apart:
`backend/scoring/overall.py::STEP_WEIGHTS` and `frontend/lib/overallScore.ts::STEP_WEIGHTS`.

## Overall weighting: how the weights are stored, and the 2026-07-31 rebalance

In code the four automated steps are stored as fractions of the 69% non-Moat portion:
`STEP_WEIGHTS = {"step1": 24/69, "step2": 10/69, "step4": 20/69, "step5": 15/69}` (Financials,
Growth Rate, Profitability, Debt), and `MOAT_WEIGHT = 0.31`. Multiplying the step fractions by
`1 − MOAT_WEIGHT` gives the percentages in the table above, which sum to exactly 100%. The
Financials/Growth/Debt/Profitability blend is a plain weighted average with **no hard-fail
override among the four automated steps** (Moat is the one deliberate exception, since it is
user-asserted rather than computed; a No Moat score of 0 can cap Overall below 70 regardless of
the steps). The Overall verdict bands are the shared ones used app-wide: Fail below 70, Pass 70-90,
Strong Pass above 90.

The 2026-07-31 rebalance moved the weights from Financials 24% (unchanged), Growth Rate 15%,
Debt 10%, Profitability ~19%, Moat 31% (unchanged) to today's Growth Rate 10%, Debt 15%,
Profitability 20%. (Profitability's old "~19%" was a rounding artifact of the former 0.28 × 0.69
arithmetic, not a bug — the old weights always summed to exactly 100%.) **Motivation**: Debt's
previously-lowest weight let a genuine per-step Fail be fully absorbed by strong scores
elsewhere. Worked examples: MA (Debt a genuine Fail at 67) blended to Overall 92 "Strong Pass"
before the rebalance, 90 "Pass" after; FICO (Debt Fail at 52) went from 89 to 87, still "Pass".

**Known limit — re-weighting is a limited lever.** A universe-wide check at the time found the
"Overall reads Pass while a contributing step scored below 70" pattern in about 25% of tickers
(125 of 493), in two roughly equal causes: about half (62) were genuine per-step Fails diluted by
blend weighting (what the rebalance targets), and about half (63) were cases where *no* step said
"Fail" at all because the sub-70 step's own verdict gate already masked it before blending.
Re-weighting cannot fix the masked half — sensitivity testing showed even raising Debt to 25%
flipped only 4 of 111 complete-data FICO-type tickers to Fail. The masked half was later
addressed inside the steps themselves rather than by weights: Debt and Profitability now fail
any blended score below 70 (see [Debt](debt.md) and [Profitability](profitability.md), "Verdict"),
and Growth Rate floors a non-negative-growth score at 70 so a Fail-range number never sits next
to "Pass" text (see [Growth Rate](growth-rate.md)).

## What happens if Economic Moat isn't set

Economic Moat is the one manual, opt-in input in the whole blend. If you haven't set a Moat
rating for a ticker yet, Overall Assessment simply reports the pure blend of the four automated
checks (Financials, Growth Rate, Profitability, Debt), reweighted to add up to 100% on their
own. **Leaving Moat unrated does not penalize the score or force a Fail** — it's treated as
"not yet part of the picture," not as a bad rating.

Once you do set a Moat rating, it's folded in at its full 31% weight. This means a "No Moat"
rating is itself a real, negative input — it's not a neutral default, it's an explicit judgment
that actively pulls the blended score down. Only an explicit "No Moat" selection has this
effect; the unrated state does not. See [Economic Moat](economic-moat.md) for the two-stage
formula this actually uses.

## What happens if a check can't be completed

Occasionally, a required check can't be computed, and Fathom treats this two different ways
depending on why:

- If a check comes back **insufficient data** — the underlying figures genuinely weren't
  available for that company — Fathom does not guess or silently drop that check from the
  blend. Instead, the whole Overall Assessment is marked **incomplete** rather than computed,
  since a partial average built on missing data would be misleading.
- If a check comes back **not supported** — a structural exemption, such as a Bank ticker
  before its CET1 ratio has been entered, or Insurance for Debt — that one check is simply
  excluded from the blend and the remaining checks are reweighted to fill the gap, the same way
  an unset Economic Moat is handled. It does **not** block the rest of Overall Assessment from
  being computed.

See the [Glossary](glossary.md) for how both differ from a genuine Fail, and for the additional
rule that a **Pass with caution** on any one check carries up into Overall Assessment's own
displayed verdict even when the blended number alone would read as a plain Pass or Strong Pass.

## Valuation is separate

The **Valuation** tab answers a different question — "is this stock currently priced above or
below what the business is actually worth?" — using a completely different, price-based
methodology (DCF-style models, Price-to-Book, or Price-to-Sales-Growth depending on the
company). **Valuation is never blended into the Overall Assessment.** A company can score
strongly on Overall Assessment while its stock is expensive, or score poorly while its stock
looks cheap — these are intentionally independent reads. See [Valuation](valuation.md) for
details.

## Company type matters

Some of the checks above don't apply cleanly to every kind of company — a bank's balance sheet
doesn't work like a typical operating company's, and neither does a REIT's or an insurer's.
Fathom detects a company's type automatically (from sector/industry text, with a short list of
manually-verified ticker-level overrides for companies the text alone misclassifies) and
adjusts which checks apply accordingly, always disclosing this on the relevant tab rather than
silently changing the math. See [Company type variations](company-type-variations.md) for the
full picture.

## Screener excludes ETFs (2026-09-20)

The Screener shows stock equities only — the 5-step fundamentals framework doesn't apply to a
fund. The exclusion is unconditional, **not** a toggle, and Screener-only: the Watchlist reads
its own rows and still shows an ETF a user explicitly added.

- **How ETFs got in**: nothing ever filtered them. FMP's search returns ETFs; viewing one
  (`GET /api/tickers/{t}/score`'s fallback, or the Watchlist's `compute_ticker_score`) writes a
  `TickerScore` row, and `load_full_tracked_universe` then keeps it in every nightly sweep
  (profile cached ⇒ "ever-viewed"). The Screener's default universe, `all`, returns every
  `TickerScore` row; an ETF is never an index constituent, so `sp500`/`dow`/`nasdaq` never held
  one. At the time of the fix the real DB had 1 ETF among 581 rows (SPY, viewed via search only).
- **Detector**: FMP `/profile`'s `isEtf`/`isFund` — the same flag
  `classify_company_type(is_fund=...)` reads (returning company type `"ETF"`; see
  [Company type variations](company-type-variations.md)). Checked against all 581 cached
  profiles at the time: SPY `isEtf=true`; the other 580 (9 ADRs included) `false/false`.
  Sector/industry text can't do this (SPY reads "Financial Services"/"Asset Management", the
  same as BLK). Already cached — no new FMP field or fetch.
- **Mechanism**: `TickerSummaryOut.is_etf` (from the profile, `data/ticker_summary.py`) →
  `TickerScore.is_etf` (nullable, `_add_missing_columns`, no backfill) → `TickerScoreOut.is_etf`.
  The Screener page applies `frontend/lib/screenerFilters.ts::excludeEtfs` to the fetched rows
  once, *before* counts, Sector/Company-type options and filters derive from them, so "ETF" isn't
  even a selectable Company type. `core/main.py::screener_meta` for `universe=all` excludes them
  too, so the "X of Y" note doesn't show an ETF as a missing ticker.
- **Null handling**: `is_etf` wins when set; a row with no `is_etf` yet (every row until its next
  recompute) falls back to `company_type == "ETF"` — derived from the same profile flag — rather
  than "not an ETF", so an ETF is excluded immediately, not after the next recompute. The nightly
  3:50 `nightly_score_recompute` backfills the column (or run
  `uv run python -m pipeline.recompute_ticker_scores`, cache-only). The SQL in `screener_meta` and
  `isEtfRow` in TypeScript must stay in sync.
- **No Country filter any more**: the original write-up noted that the Screener's Country=US
  option was exchange-based and still included NYSE/NASDAQ-listed ADRs and OTC names once ETFs
  were gone. That is moot now — the Country filter (`TickerScore.country`,
  `SavedScreenerFilter.country`) was removed 2026-09-26 with non-US ticker support (see
  `docs/specs/fmp-data-and-bar-cache.md`, "US-listed tickers only"); Fathom supports US-listed
  tickers only, decided by listing venue rather than domicile, so ADRs and OTC names are
  in-universe by design. The original wording is archived in
  `docs/archive/claude-md-history-features.md`.
- **Not done (flagged)**: `nightly_fundamentals_fetch` still spends FMP calls fetching/scoring an
  ETF's statements (SPY: ~20 cache rows); nothing in that script skips ETFs.

## Screener excludes delisted tickers (2026-09-30)

A ticker flagged delisted (`TickerScore.delisted_at` set; see the delisted-ticker section of
[FMP data and bar cache](fmp-data-and-bar-cache.md)) appears in **no** Screener universe.
`core/main.py::screener_list` and `screener_meta` both add `delisted_at IS NULL` in every branch
(`all`, `sp500`, `dow`, `nasdaq`), so the "X of Y" count matches the rows returned. The page's
Watchlist scope is applied client-side over the `all` response and inherits the exclusion. The flag
is not exposed to the frontend and nothing here clears it. The Watchlist is unaffected: it reads its
own rows, so a delisted ticker a user explicitly watchlisted still shows there. The nightly
fundamentals fetch and score recompute still process a flagged ticker.

## P/E basis (2026-09-30)

The Screener's P/E, the ticker header's and Summary tab's **P/E Ratio**, and the Watchlist's P/E
column all read one value, `TickerScore.pe_ratio` (`TickerSummaryOut.pe_ratio`,
`data/ticker_summary.py`), and it is **trailing**:

- **Standard rule:** current price ÷ FMP TTM EPS, where EPS is `netIncomePerShareTTM` from the
  already-cached `ratios/ttm` row and the price is the nightly `TickerLastClose` close (falling
  back to the quote price when a ticker has no `TickerLastClose` row).
- **NULL** when TTM EPS is zero, negative or missing (or no price exists at all). A NULL renders as
  "—" and is excluded by any active P/E range, so loss-makers never pass a max-only filter.
- **ADRs** (reported currency ≠ quote currency, both known — detected from the two fields, not a
  list): use FMP's own `priceToEarningsRatioTTM` instead, because price (quote currency) over EPS
  (reporting currency) would need FX. NULL if that value is zero, negative or missing. If either
  currency is unknown the standard rule is used.
- Nothing new is fetched: the nightly cache-only recompute fills it from cached rows.

Before 2026-09-30 this was FMP's annual `priceToEarningsRatio` (fiscal-year-end price over
fiscal-year EPS), which sat next to a TTM PEG on the header — a mixed basis. The **Ratios tab is
deliberately unchanged**: it shows FMP's annual P/E history plus FMP's TTM P/E column, so its
figures can differ from the header's. No ratios spec exists yet; one is warranted.

## Beyond the Analysis and Valuation tabs

Two further, fully independent lenses exist elsewhere in the app and never feed into Overall
Assessment or Valuation in either direction:

- **Speculative Growth** — a separate classification (not a score) layered on top of the same
  fundamentals data, gated on company type, Moat, and forward growth. See
  [Speculative Growth](speculative-growth.md).
- **Technical tab** — a family of independent, price-structure-only signals (swing/BOS trend
  state, Weinstein Stage Analysis, Liquidity Zones, BB+RSI and Warren entry signals, Sector
  Heatmap, Market Breadth) computed from price bars, never from the fundamentals pipeline. See
  [Trend structure (Technical)](trend-structure-technical.md), [Weinstein Stage](weinstein-stage.md),
  [Sector Heatmap](sector-heatmap.md), and [Market Breadth](market-breadth.md).
