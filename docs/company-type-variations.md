# Company type variations

Not every check applies the same way to every kind of company. A bank's
balance sheet, an insurer's income statement, and a REIT's cash flow don't
work like a typical operating company's — so Fathom automatically detects
a company's type (from its sector and industry classification) and adjusts
which checks apply, always disclosing the detected type on the relevant
tab rather than silently changing the math behind the scenes.

This detection is a best-effort match on the company's reported sector and
industry text, not a certified classification — an occasional
misclassified ticker is possible, which is exactly why the app always
shows you the detected type rather than hiding it.

## At a glance

| Company type | Financials | Growth Rate | Profitability | Debt | Valuation |
|---|---|---|---|---|---|
| **Standard** (typical operating company) | All 5 metrics checked | EPS preferred, revenue fallback | All 4 metrics checked | Standard 3-ratio check | Cash-flow or profit-based method |
| **Bank** | Cash-flow checks skipped | EPS preferred, revenue fallback | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped) | Judged on capital adequacy (CET1, manual entry) + loan quality (NPL) | Price-to-Book |
| **Insurance** | Cash-flow checks skipped | EPS preferred, revenue fallback | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped) | Not supported — no reliable substitute available | Profit-based method (cash flow skipped) |
| **REIT / Property Developer** | Cash-flow checks skipped | Always revenue (rental income); EPS never used | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped) | Judged on a Gearing ratio (debt vs. total assets) instead of the standard 3 ratios | Price-to-Book |
| **Utility** | All 5 metrics checked (not exempted here) | EPS preferred, revenue fallback | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped) | Standard 3-ratio check (not exempted here) | Cash-flow or profit-based method |
| **Commodity company** (e.g. mining, energy) | Cash-flow checks skipped | EPS preferred, revenue fallback | All 4 metrics checked (not exempted here) | Standard 3-ratio check (not exempted here) | Cash-flow or profit-based method |

Growth Rate reads the same way for every company type except REITs, which
are scored on revenue (rental income) growth instead of EPS — EPS is
heavily distorted by non-cash real-estate depreciation, and the data
source has no forward-looking dividend/distribution estimate to substitute
instead. See [Growth Rate](growth-rate.md) for detail.

## Why cash-flow checks get skipped for some types

Banks and Insurance companies report "cash from operations" very
differently from a typical business — for a bank it's tangled up with
customer deposits and loan originations, and for an insurer it moves with
claim timing, reserve changes, and investment portfolio swings rather than
the operating business itself. Property Developers and Commodity companies
have their own version of this problem tied to how their industries
recognize revenue and capital spending. In all of these cases, Financials
leans more heavily on Revenue, Net Income, and Margins instead. See
[Financials](financials.md) for detail.

## Why some Profitability metrics get skipped

Return on Invested Capital and Cash Conversion Cycle assume a business
model with clear "capital invested" and "inventory-to-cash" cycles.
Banks, Insurance companies, Utilities, and REITs don't fit that mold
cleanly, so those metrics are skipped for them. The Receivables-vs-Revenue
check is skipped for the same four types too — REITs have no comparable
concept for a rental-income business, and Bank/Insurance/Utility revenue
recognition doesn't map onto ordinary trade receivables the way a Standard
operating company's does — leaving Return on Equity as the only Profitability
check for these four company types. Any company that carries no physical
inventory at all — regardless of its official type — also has Cash
Conversion Cycle skipped automatically, since the metric assumes there's
inventory to convert into cash in the first place. See
[Profitability](profitability.md) for detail.

## Why Debt uses different criteria for financial and real-estate companies

The standard three debt ratios (Current Ratio, Debt/EBITDA, Debt
Servicing Ratio) assume a typical operating-company balance sheet. Banks
are instead judged on capital adequacy and loan quality; Insurance
companies currently have no reliable substitute measure available and
show as not supported; REITs and Property Developers are judged on a
leverage-vs-assets ("Gearing") ratio that better fits a real-estate-heavy
balance sheet. See [Debt](debt.md) for detail.

## Why Valuation uses a different method for some types

A discounted-cash-flow-style valuation depends on projecting future cash
flow — which doesn't work well for asset-heavy, balance-sheet-driven
businesses. Banks and REITs are valued using a Price-to-Book approach
instead, comparing price to net asset value rather than projected cash
flow. See [Valuation](valuation.md) for detail.
