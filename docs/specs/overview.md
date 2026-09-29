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
elsewhere — see [Debt](debt.md) and `CLAUDE.md`'s scoring-rubric history for the investigation
behind that rebalance and its known, deliberate limits (it can't fix a per-step verdict gate
that masks a sub-70 score as "Pass" before the blend ever runs).

The weight table lives in two places that must never drift apart:
`backend/scoring/overall.py::STEP_WEIGHTS` and `frontend/lib/overallScore.ts::STEP_WEIGHTS`.

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
