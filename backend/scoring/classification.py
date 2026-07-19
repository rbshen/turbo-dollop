def classify_company_type(sector: str | None, industry: str | None) -> str:
    """Best-effort sector/industry text match, shared by Step 4 and Step 5 --
    not a certified determination. A misclassified ticker would silently
    apply the wrong ratio/exemption set, so this is always surfaced in the
    UI/API, never hidden (see CLAUDE.md).

    Insurance is checked before Bank: both sit in the "Financial Services"
    sector, so checking Bank first would misclassify insurers whose industry
    text doesn't happen to also match "bank"."""
    sector = (sector or "").strip()
    industry_lower = (industry or "").strip().lower()
    if sector == "Financial Services" and "insurance" in industry_lower:
        return "Insurance"
    if sector == "Financial Services" and "bank" in industry_lower:
        return "Bank"
    if sector == "Utilities":
        return "Utility"
    if sector == "Real Estate" or "reit" in industry_lower:
        return "REIT/Property Developer"
    return "Standard"
