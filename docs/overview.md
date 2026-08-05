# How Fathom scores a company

Fathom runs a fundamentals screen on any US-listed ticker. When you open a
ticker page, you'll see several tabs: **Summary**, **Financials**,
**Ratios**, **Analysis**, **Valuation**, **Economic Moat**, and **Analyst
Ratings**. This overview explains how the **Analysis** tab's score is built
and how it relates to the **Valuation** tab, which is calculated completely
separately.

## The Analysis tab: Overall Assessment

The Analysis tab blends four automated checks plus one manual rating into a
single **Overall Assessment**:

| Card | What it checks |
|---|---|
| **Financials** | Revenue, Net Income, Cash From Operations, Margins, and Free Cash Flow — see [Financials](financials.md) |
| **Growth Rate** | Forward analyst growth expectations — see [Growth Rate](growth-rate.md) |
| **Profitability** | Return on Equity, Return on Invested Capital, Accounts Receivable trend, and Cash Conversion Cycle — see [Profitability](profitability.md) |
| **Debt** | Short-term liquidity, leverage, and debt service burden — see [Debt](debt.md) |
| **Economic Moat** | A manual, judgment-based competitive-advantage rating you set yourself — see [Economic Moat](economic-moat.md) |

Each of the four automated cards produces its own score (0–100) and verdict
(Fail / Pass / Strong Pass, or occasionally "Pass with caution" — see the
[Glossary](glossary.md)). The Overall Assessment combines them into one
number using these weights:

| Component | Weight |
|---|---|
| Financials | 24% |
| Growth Rate | 10% |
| Profitability | 20% |
| Debt | 15% |
| Economic Moat | 31% |

These weights reflect a deliberate design choice: Economic Moat — a
qualitative read on whether a company has a durable competitive
advantage — carries the single largest weight, on the view that a strong
moat matters at least as much as any one quarter-to-quarter financial
metric. Among the four automated checks, Financials carries the most
weight since it's the most foundational read on the business, while Debt
was deliberately weighted above Growth Rate so that a genuine debt problem
can't be fully diluted away by strength elsewhere.

## What happens if Economic Moat isn't set

Economic Moat is the one manual, opt-in input in the whole blend. If you
haven't set a Moat rating for a ticker yet, Overall Assessment simply
reports the pure blend of the four automated checks (Financials, Growth
Rate, Profitability, Debt), reweighted to add up to 100% on their own.
**Leaving Moat unrated does not penalize the score or force a Fail** — it's
treated as "not yet part of the picture," not as a bad rating.

Once you do set a Moat rating, it's folded in at its full 31% weight. This
means a "No Moat" rating is itself a real, negative input — it's not a
neutral default, it's an explicit judgment that actively pulls the blended
score down. Only an explicit "No Moat" selection has this effect; the
unrated state does not.

## What happens if a check can't be completed

Occasionally, a required check can't be computed, and Fathom treats this
two different ways depending on why:

- If a check comes back **insufficient data** — the underlying figures
  genuinely weren't available for that company — Fathom does not guess or
  silently drop that check from the blend. Instead, the whole Overall
  Assessment is marked **incomplete** rather than computed, since a
  partial average built on missing data would be misleading.
- If a check comes back **not supported** — a structural exemption, such
  as a Bank ticker before its CET1 ratio has been entered — that one
  check is simply excluded from the blend and the remaining checks are
  reweighted to fill the gap, the same way an unset Economic Moat is
  handled. It does **not** block the rest of Overall Assessment from
  being computed.

See the [Glossary](glossary.md) for how both differ from a genuine Fail.

## Valuation is separate

The **Valuation** tab answers a different question — "is this stock
currently priced above or below what the business is actually worth?" —
using a completely different, price-based methodology (DCF-style models,
Price-to-Book, or other approaches depending on the company). **Valuation
is never blended into the Overall Assessment.** A company can score
strongly on Overall Assessment while its stock is expensive, or score
poorly while its stock looks cheap — these are intentionally independent
reads. See [Valuation](valuation.md) for details.

## Company type matters

Some of the checks above don't apply cleanly to every kind of company — a
bank's balance sheet doesn't work like a typical operating company's, and
neither does a REIT's or an insurer's. Fathom detects a company's type
automatically and adjusts which checks apply accordingly, always
disclosing this on the relevant tab rather than silently changing the
math. See [Company type variations](company-type-variations.md) for the
full picture.
