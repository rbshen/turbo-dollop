# Company type variations

Not every check applies the same way to every kind of company. A bank's balance sheet, an
insurer's income statement, and a REIT's cash flow don't work like a typical operating
company's — so Fathom automatically detects a company's type (from its sector and industry
classification, `backend/scoring/classification.py::classify_company_type`) and adjusts which
checks apply, always disclosing the detected type on the relevant tab rather than silently
changing the math behind the scenes.

This detection is a best-effort match on the company's reported sector and industry text, not a
certified classification — an occasional misclassified ticker is possible, which is exactly why
the app always shows you the detected type rather than hiding it. A small, manually-verified
list of ticker-level overrides (`NON_LENDER_TICKER_OVERRIDES` in the same module) exists for
companies whose sector/industry text alone would misclassify them as a Bank — see "Bank
detection and its ticker-level overrides" below for the full tables and reasoning (checked once
by hand against real NII-and-deposit-liability data, not derived from a rule, and does not
auto-generalize to a newly-listed ticker in the same sector).

## At a glance

| Company type | Financials | Growth Rate | Profitability | Debt | Valuation |
|---|---|---|---|---|---|
| **Standard** (typical operating company) | All 5 metrics checked | EPS preferred, revenue fallback | All 4 metrics checked | Standard 3-ratio check | Cash-flow or profit-based method |
| **Bank** | Revenue and Net Income only (CFO, FCF and Margins skipped; Revenue is the real revenue line) | EPS preferred, revenue fallback | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped) | Judged on capital adequacy (CET1, manual entry) + loan quality (NPL) | Price-to-Book |
| **Insurance** | Revenue and Net Income only (CFO, FCF and Margins skipped) | EPS preferred, revenue fallback | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped) | Not supported — no reliable substitute available | Profit-based method (cash flow skipped) |
| **REIT / Property Developer** | Revenue and Net Income only (CFO, FCF and Margins skipped) | Always revenue (rental income); EPS never used | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped) | Judged on a Gearing ratio (debt vs. total assets) instead of the standard 3 ratios; under 45% passes | Price-to-Book |
| **Utility** | All 5 metrics checked (not exempted here; its margin severity carve-out stays) | EPS preferred, revenue fallback | Only Return on Equity is checked (ROIC, Receivables trend, and Cash Conversion Cycle all skipped — extended 2026-09-04) | Standard 3-ratio check (not exempted here) | Cash-flow or profit-based method |
| **Commodity company** (price-taking producers and extractors only — Financials-local classification: sector `Basic Materials`/`Energy` **and** an industry on the producer allowlist, below) | Revenue and Net Income only (CFO, FCF and Margins skipped) | EPS preferred, revenue fallback | All 4 metrics checked (not exempted here) | Standard 3-ratio check (not exempted here) | Cash-flow or profit-based method |

Growth Rate reads the same way for every company type except REITs, which are scored on revenue
(rental income) growth instead of EPS — EPS is heavily distorted by non-cash real-estate
depreciation, and the data source has no forward-looking dividend/distribution estimate to
substitute instead. See [Growth Rate](growth-rate.md) for detail.

Note that "Commodity Company" is a classification local to the **Financials** check only
(`data/step1_data.py::_detect_exemption`) — it has no
equivalent branch in the shared classifier that Profitability, Debt, and Valuation all use, so a
commodity company still runs the *standard* Profitability/Debt/Valuation path unless some other
condition (e.g. REIT/Property Developer text) also applies.

### Commodity industry allowlist (2026-10-07)

The rule was sector text alone (`Basic Materials` or `Energy`) until 2026-10-07, which tagged businesses that are not price-taking
producers (industrial gases, coatings, oilfield services, pipelines, building products). It is now an allowlist: a ticker is a
Commodity Company only if its profile sector is `Basic Materials` or `Energy` **and** its FMP industry is one of
`COMMODITY_PRODUCER_INDUSTRIES` (`backend/data/step1_data.py`, matched exactly after stripping, FMP's own spelling):

| Group | Industries |
|---|---|
| Oil and gas | Oil & Gas Exploration & Production, Oil & Gas Integrated, Oil & Gas Refining & Marketing |
| Metals and mining | Copper, Gold, Steel, Aluminum, Silver, Other Industrial Metals & Mining, Other Precious Metals & Mining |
| Coal and uranium | Uranium, Coal, Thermal Coal, Coking Coal |
| Agriculture and forest | Agricultural Inputs, Paper, Lumber & Forest Products (the last is one FMP label, spelled exactly so in `COMMODITY_PRODUCER_INDUSTRIES`; IP carries it) |

(Aluminum, Silver, the two "Other ... Mining" labels and the three coal labels have no scored ticker today; they are listed so a future
ticker is handled.) Everything else in the two sectors is **Standard** in Step 1: Chemicals, Chemicals - Specialty, Construction
Materials, Oil & Gas Equipment & Services, Oil & Gas Midstream, Solar, and any industry not on the list. A ticker in the two sectors
whose cached profile has **no industry** stays Commodity (today's behaviour, so nothing changes silently). Of the 49 tickers that were
Commodity, 26 stay and 23 are Standard now: ACA, BLDR, MLM, CRH, VMC; DD, DOW, LYB, ALB, APD, ECL, IFF, LIN, PPG, SHW; BKR, HAL, SLB;
KMI, OKE, TRGP, WMB; FSLR. Known limits: FMP's industry labels are coarse (DOW, LYB and ALB are commodity producers filed under
"Chemicals" / "Chemicals - Specialty" and are Standard now; TPL, a royalty owner, and CTVA, a seed company, stay Commodity), and FCX,
MOS, NUE and STLD stay exempt although their cash flow is weak. No per-ticker overrides were added for these. Decision and evidence:
docs/decisions.md 2026-10-07.

### Commodity override list (2026-10-07)

A ticker that FMP files under the wrong sector used to inherit the CFO/FCF exemption. `COMMODITY_EXEMPTION_TICKER_OVERRIDES`
(`backend/data/step1_data.py`, the same pattern as `NON_LENDER_TICKER_OVERRIDES`) lists tickers that are scored as **Standard** in
Step 1 (CFO and FCF scored, standard weights) even though their profile says `Basic Materials` or `Energy`. It is keyed on the ticker,
not on the cached profile, so a profile refresh (the 30-day staleness window, the Refresh button, the nightly fetch) cannot undo it;
it changes neither the displayed sector nor `TickerScore.sector`. Since the industry allowlist both tickers are Standard on the
industry alone ("Construction Materials" is not on it), so the list is redundant; it is kept as a guard against FMP relabelling them
into a producer industry.

| Ticker | FMP profile | Why it is not a commodity company |
|---|---|---|
| JCI | Basic Materials / Construction Materials | Johnson Controls: building systems, HVAC and controls; S&P 500 sector Industrials |
| MAS | Basic Materials / Construction Materials | Masco: branded home-improvement and building products; S&P 500 sector Industrials |

Like the Bank list this does not generalize: a new mislabelled ticker needs a manual check and an entry. Only Step 1 reads the
Commodity label (and Speculative Growth, which treats any Step 1 exemption as not applicable, so the 23 tickers above are now
evaluated by its gate as Standard; none qualifies); `classify_company_type` already returned `Standard` for all of them, so Steps 3, 4
and 5 are unchanged. Decisions: docs/decisions.md 2026-10-07.

## Why cash-flow checks get skipped for some types

Banks and Insurance companies report "cash from operations" very differently from a typical
business — for a bank it's tangled up with customer deposits and loan originations, and for an
insurer it moves with claim timing, reserve changes, and investment portfolio swings rather than
the operating business itself. Property Developers and Commodity companies (price-taking producers) have their own
version of this problem tied to how their industries recognize revenue and capital spending. Since 2026-10-08 all four types are
judged on the same two series, Revenue and Net Income (with Operating Income as the Net Income backup), and Margins is skipped for
all of them too (it used to be skipped for Banks only: gross profit over revenue is not a coherent concept for a lender, and the owner
extended the same treatment to the other three). **Revenue is the real FMP revenue line for every type, Banks included**; the earlier
Net Interest Income substitution for Banks was removed. See [Financials](financials.md) for detail.

## Why some Profitability metrics get skipped

Return on Invested Capital and Cash Conversion Cycle assume a business model with clear "capital
invested" and "inventory-to-cash" cycles. Banks, Insurance companies, Utilities, and REITs don't
fit that mold cleanly, so those metrics are skipped for them. The Receivables-vs-Revenue check
is skipped for the same four types (extended from REIT-only on 2026-09-04) — REITs have no
comparable concept for a rental-income business, and Bank/Insurance/Utility revenue recognition
doesn't map onto ordinary trade receivables the way a Standard operating company's does —
leaving Return on Equity as the only Profitability check for these four company types. Any
company that carries no physical inventory at all — regardless of its official type — also has
Cash Conversion Cycle skipped automatically, since the metric assumes there's inventory to
convert into cash in the first place. See [Profitability](profitability.md) for detail.

## Why Debt uses different criteria for financial and real-estate companies

The standard three debt ratios (Current Ratio, Debt/EBITDA, Debt Servicing Ratio) assume a
typical operating-company balance sheet. Banks are instead judged on capital adequacy and loan
quality; Insurance companies currently have no reliable substitute measure available and show as
not supported; REITs and Property Developers are judged on a leverage-vs-assets ("Gearing")
ratio that better fits a real-estate-heavy balance sheet. See [Debt](debt.md) for detail.

## Why Valuation uses a different method for some types

A discounted-cash-flow-style valuation depends on projecting future cash flow — which doesn't
work well for asset-heavy, balance-sheet-driven businesses. Banks and REITs are valued using a
Price-to-Book approach instead, comparing price to net asset value rather than projected cash
flow — as of 2026-09-14, the *standard* (plain book value) variant is the auto-selected default
for these types, with the earlier tangible (intangibles-stripped) variant demoted to a
manual-only "Price to Book (custom)" choice. See [Valuation](valuation.md) for detail.

## How the type is detected (`classify_company_type`)

`backend/scoring/classification.py::classify_company_type(sector, industry, ticker, is_fund)`,
shared by Steps 1/3/4/5. Order matters:

1. **Funds first.** `is_fund` (the FMP profile's `isEtf`/`isFund` flag) returns `"ETF"` before any
   keyword is looked at — SPY and PTY both report sector "Financial Services" / industry "Asset
   Management" (the identical text real asset managers like BLK and AMP report), so text matching
   alone can never tell a fund product from the company that manages it. Being structural, this
   needs no per-ticker maintenance (unlike the override list below). *(The "At a glance" table
   above covers operating-company types only; ETFs are excluded from the Screener — see
   [Overview](overview.md).)*
2. **Insurance** (sector `Financial Services` and industry contains "insurance") is checked
   before Bank, since both sit in the same sector and Bank is matched more loosely.
3. **Bank**: sector `Financial Services` and the industry contains any of `bank`,
   `capital markets`, `asset management`, `credit services` (`_BANK_INDUSTRY_KEYWORDS`). The
   broadening beyond the literal "bank" substring catches brokers ("Financial - Capital
   Markets": SCHW, MS, GS), asset managers ("Asset Management": BLK, STT, TROW) and
   credit-card/credit issuers ("Financial - Credit Services": COF, V, MA, AXP, SYF, PYPL);
   investment banks like IBKR ("Investment - Banking & Investment Services") already match
   "bank" via "banking". A ticker in `NON_LENDER_TICKER_OVERRIDES` returns `"Standard"` instead.
4. **Utility** (sector `Utilities`), then **REIT/Property Developer** (sector `Real Estate` or
   industry contains "reit"); everything else is `"Standard"`.

## Bank detection and its ticker-level overrides

**Why an override list exists.** Sector/industry text alone cannot reliably separate a genuine
lender from a non-lender inside the broadened Bank buckets — companies with the *identical*
industry string can have completely different balance-sheet economics (a payment network vs. a
card issuer; a pure asset manager vs. one with a captive bank subsidiary). Confirmed live via FMP
profile plus income-statement data: BLK and AMP both report "Asset Management"; V and AXP both
report "Financial - Credit Services". Only a ticker-level check — of `netInterestIncome` as a
percentage of revenue, and (below) of genuine deposit-liability reporting — tells them apart.
Each ticker below was verified once, by hand, against real data; it is not derived from any rule.

**Why it matters.** Applying Bank's treatment (Financials' CFO/FCF/Margins exemption, Profitability's ROIC exemption, Valuation's
forced Price-to-Book method) to a genuine non-lender produces nonsensical output. The confirmed regression that motivated this list
was from the time Net Interest Income stood in for revenue (removed 2026-10-08): V/MA/BLK's Financials scores dropped 30-50+ points
purely from a near-zero/negative NII series standing in for real revenue, not from the intended CFO-de-emphasis effect.

NII/revenue below is each ticker's most recent annual FMP figure at the time of the 2026-07-28
investigation (`netInterestIncome / revenue`); it drifts year to year and is not re-verified
automatically. BNY's figures are from a separate later check (2026-08-05, FY2025 data).

**Excluded from Bank → classified `"Standard"`** (all 19 are in `NON_LENDER_TICKER_OVERRIDES`; the
19 in the code match the 13 + 6 listed here):

| Ticker | NII/revenue | Business model |
|---|---|---|
| V | -1.5% | Payment network (Visa) — no cardmember lending, small net interest *expense* |
| MA | -2.2% | Payment network (Mastercard) — no cardmember lending |
| PYPL | +0.2% | Payment processor/digital wallet — positive NII is float/interest on customer balances, not a loan book |
| GPN | -6.4% | Payment processor/merchant acquirer (Global Payments) — no lending |
| APO | -0.8% | Alternative asset manager/PE (Apollo) — no banking subsidiary |
| ARES | -1.5% | Alternative asset manager (Ares Management) — no banking subsidiary |
| BEN | -1.1% | Traditional asset manager (Franklin Resources/Templeton) — no banking subsidiary |
| BLK | -0.09% | Asset manager (BlackRock), the largest in the world — no banking subsidiary |
| BX | -0.7% | PE/alternative asset manager (Blackstone) — no banking subsidiary |
| IVZ | -0.5% | Asset manager (Invesco) — no banking subsidiary |
| KKR | +0.6% | PE/alternative asset manager — positive but negligible NII, not a real loan book |
| TROW | +6.8% | Traditional/mutual-fund asset manager (T. Rowe Price) — no banking subsidiary; NII is short-term investment income, not a retail/commercial loan book |
| PFG | -0.01% | Insurance and retirement-services company (Principal Financial Group) — not a lender at all; industry text alone puts it in the Bank-keyword branch |
| IBKR | n/a (see below) | Interactive Brokers — broker-dealer, large margin-lending book, no bank charter, no deposit-liability tag |
| HOOD | n/a (see below) | Robinhood — broker-dealer; a deposit-shaped tag is only 0.7% of assets (immaterial) |
| SEIC | n/a (see below) | SEI Investments — pure asset-management/investment-processing firm, no banking subsidiary |
| SEZL | n/a (see below) | Sezzle — BNPL/consumer-credit fintech, no bank charter |
| HUT | n/a (2026-09-30) | Hut 8 — bitcoin miner / energy & compute infrastructure; FMP files it under "Financial - Capital Markets". Zero interest income, negative NII, no deposit-liability tag in balance sheet or as-reported XBRL |
| CRCL | +1.7% | Circle — stablecoin issuer; NII is yield on USDC reserves, not a loan book; no deposit-liability tag. FMP industry "Financial - Capital Markets" |

**Confirmed lenders — kept as `"Bank"`** (not in the code; documented here so the reasoning
survives):

| Ticker | NII/revenue | Business model |
|---|---|---|
| SYF | 96.6% | Private-label/co-brand credit-card issuer (Synchrony) with Synchrony Bank — pure consumer lending business |
| COF | 61.9% | Credit-card issuer *and* retail bank (Capital One) — full consumer lending book |
| SCHW | 42.5% | Broker with Charles Schwab Bank — real deposit-taking/lending balance sheet |
| AXP | 21.6% | Card network *with* a real cardmember loan book (American Express), unlike V/MA |
| AMP | 17.2% | Ameriprise Financial — has Ameriprise Bank FSB subsidiary |
| NTRS | 16.9% | Northern Trust — custody bank with real lending/deposit operations |
| RJF | 13.5% | Raymond James — has Raymond James Bank subsidiary |
| STT | 13.1% | State Street — custody bank (State Street Bank and Trust) with real lending |
| BNY | 12.2% | The Bank of New York Mellon — chartered custody bank; deposits are 70.3% of total assets (FY2025, SEC EDGAR `Deposits`/`Assets` XBRL tags). Shares IBKR's exact "Investment - Banking & Investment Services" industry text, but unlike IBKR (no deposit tag filed) is a genuine, materially larger deposit-taking lender — confirmed explicitly here rather than left to be inferred from the shared industry string |
| GS | 10.8% | Goldman Sachs — investment bank with real deposit-taking/lending and trading-book NII |
| MS | 8.7% | Morgan Stanley — investment bank with Morgan Stanley Private Bank / wealth-management lending |

**This list does not auto-generalize.** A new ticker that lands in the same sector/industry
buckets (e.g. a newly-listed fintech IPO, a new asset manager) classifies as `"Bank"` by default
and needs the same manual check (NII/revenue, or the deposit-liability check below) before being
added to either side of this list — no automated signal catches a new non-lender or a new lender
on its own.

### The standard: genuine CET1/NPL-reporting capability, not just lending (2026-09-05)

Fathom's `"Bank"` treatment exists to run Step 5's CET1 (capital adequacy) and NPL (loan quality)
checks (`data/step5_data.py`), which only make sense for an institution that reports under
banking regulation — a genuine deposit-taking institution. Lending *shape* (margin loans,
credit-card loans, BNPL installment credit) is irrelevant to that question; regulatory reporting
shape is what matters. So NII-as-%-of-revenue answers "does this company lend?", not "does it
report under banking regulation?" — and the latter is the test for Bank. A company classified
`"Bank"` that doesn't report CET1/NPL shouldn't get Bank treatment *anywhere* (Step 1's CFO/FCF/Margins exemption,
Step 4's ROIC exemption, Step 3's forced Price-to-Book), not just skip the CET1/NPL check while
everything else stays Bank-shaped. (HOOD was originally listed as a confirmed lender at 33.9% NII
and was moved to the override list on this basis.)

**Evidence standard** (a manual check, not implemented as code): presence or absence of a genuine
deposit-liability figure in FMP's `financial_statement_full_as_reported` raw XBRL-tag dump
(quarterly, falling back to annual — the same fallback `helpers/npl.py::compute_npl_ratio` uses),
compared with total assets. Use the literal `deposits` tag if present and material, otherwise the
largest plausible deposit-liability-shaped tag — excluding tag names containing `interest`,
`fee`, `expense`, `income`, `increasedecrease`, `adjustmentsfor`, `paymentsfor`, `proceedsfrom`,
`acquisition`, `premium`, `fairvaluedisclosure`, or `reserve`. The `reserve` exclusion is
load-bearing: IBKR's largest `*deposit*`-named tag is `cashreservedepositrequiredandmade` (22.9%
of assets), an SEC Rule 15c3-3 customer segregated-cash reserve requirement, not a deposit
liability funding the balance sheet; without excluding it IBKR would wrongly clear the check. A
literal-`deposits`-only check gives false positives at universe scale — HSBC files under
IFRS-style names (`depositsfromcustomers` = 52.0% of assets) and MTB's literal `deposits` tag is
a mis-scoped small XBRL member (2.1% of assets; its real deposit-liability tags sum to ~77%).

**Result of the 2026-09-05 scan** (572 tracked tickers, 32 classified `"Bank"`): 28 are confirmed
genuine deposit-taking institutions (real deposits 15–81% of assets): AMP, AXP, BAC, BNY, C, CFG,
COF, FITB, GS, HBAN, JPM, KEY, MS, MTB, NBN, NTRS, PNC, RF, RJF, RY, SCHW, STT, SYF, TFC, TMP,
USB, WFC, HSBC. *(The original write-up said "26 of the 32" but listed these 28 names and
32 − 4 = 28; the 28 is the consistent figure.)* The 4 with no genuine deposit-liability tag at
any magnitude — IBKR, HOOD, SEIC, SEZL — went on `NON_LENDER_TICKER_OVERRIDES` (table above),
so all four gained a real Step 5 verdict for the first time (previously permanently
`not_supported`, since none could ever have CET1 entered).

`BANK_CET1_NPL_EXCLUDED_TICKERS` (`data/step5_data.py`) is now an empty set — verified in code —
because IBKR/HOOD never reach the Bank branch once they are `"Standard"`. The mechanism (constant
+ branch + classification note) is kept because `tests/test_step5_data.py`'s regression test
exercises it generically; a future CET1/NPL-non-reporting ticker should go on
`NON_LENDER_TICKER_OVERRIDES` rather than in this set. The investigation narrative and the
before/after score table are in `docs/archive/claude-md-history-features.md`.
