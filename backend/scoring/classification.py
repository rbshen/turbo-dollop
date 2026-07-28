# Brokers, asset managers, and credit-card/credit issuers are classified as
# Bank (not Insurance, not Standard) -- confirmed via live FMP profile data
# these use distinct industry strings that don't contain "bank" itself:
# capital-markets brokers (SCHW, MS, GS) -> "Financial - Capital Markets";
# asset managers (BLK, STT, TROW) -> "Asset Management"; credit-card/credit
# issuers (COF, V, MA, AXP, SYF, PYPL) -> "Financial - Credit Services".
# (Investment banks like IBKR -- "Investment - Banking & Investment
# Services" -- already match the plain "bank" substring via "banking", no
# extra keyword needed.) Grouped with Bank rather than Insurance since their
# balance-sheet/capital structure and ROE-driven assessment matches Bank's
# treatment throughout this app (Step 1 CFO de-emphasis, Step 4 ROIC
# exemption, Step 5 NPL-attempt-then-not_supported), not Insurance's.
_BANK_INDUSTRY_KEYWORDS = ("bank", "capital markets", "asset management", "credit services")

# "Asset Management" and "Financial - Credit Services" are shared verbatim by
# both genuine lenders and non-lenders -- e.g. BLK (no banking subsidiary,
# netInterestIncome -0.09% of revenue) and AMP (Ameriprise Bank FSB, 17.2%)
# report the identical industry string "Asset Management"; V and AXP both
# report "Financial - Credit Services" despite V having no lending operation
# (netInterestIncome -1.5% of revenue -- a small net expense, not income) vs.
# AXP's real cardmember-loan book (21.6%). Sector/industry text alone cannot
# separate these, so this ticker-level exception list exists specifically
# for that gap -- confirmed via live netInterestIncome-as-%-of-revenue for
# every ticker the keyword broadening above newly reclassified as Bank.
# Excluded here because applying Bank's Net-Interest-Income revenue swap
# (Step 1) and forced Price-to-Book valuation to a non-lender produces a
# nonsensical, near-zero-or-negative "revenue" series -- confirmed for V/MA/
# BLK, whose Step 1 scores dropped 30-50+ points purely from this swap, not
# from the intended CFO-de-emphasis effect. This is a narrower, more
# surgical exception than the keyword list itself and doesn't generalize
# automatically to new tickers -- a newly-listed asset manager or
# credit-services company will classify as Bank by default and needs this
# list updated manually if it turns out to be a non-lender too (same
# maintenance model as classify_company_type's whole best-effort approach,
# just at ticker granularity instead of sector/industry granularity). See
# CLAUDE.md ("Company classification: non-lender ticker overrides") for the
# full per-ticker table -- every entry here and every confirmed-lender
# ticker kept as Bank, with its NII/revenue % and one-line business-model
# reason.
NON_LENDER_TICKER_OVERRIDES = {
    "APO", "ARES", "BEN", "BLK", "BX", "GPN", "IVZ", "KKR", "MA", "PFG", "PYPL", "TROW", "V",
}


def classify_company_type(sector: str | None, industry: str | None, ticker: str | None = None) -> str:
    """Best-effort sector/industry text match, shared by Step 1/3/4/5 --
    not a certified determination. A misclassified ticker would silently
    apply the wrong ratio/exemption set, so this is always surfaced in the
    UI/API, never hidden (see CLAUDE.md).

    Insurance is checked before Bank: both sit in the "Financial Services"
    sector, so checking Bank first would misclassify insurers whose industry
    text doesn't happen to also match "bank". `ticker` is optional (defaults
    to no override applying) since most of this function's logic doesn't
    need it -- only NON_LENDER_TICKER_OVERRIDES does."""
    sector = (sector or "").strip()
    industry_lower = (industry or "").strip().lower()
    if sector == "Financial Services" and "insurance" in industry_lower:
        return "Insurance"
    if sector == "Financial Services" and any(kw in industry_lower for kw in _BANK_INDUSTRY_KEYWORDS):
        if ticker and ticker.upper() in NON_LENDER_TICKER_OVERRIDES:
            return "Standard"
        return "Bank"
    if sector == "Utilities":
        return "Utility"
    if sector == "Real Estate" or "reit" in industry_lower:
        return "REIT/Property Developer"
    return "Standard"
