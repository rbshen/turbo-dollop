from datetime import date

from pydantic import BaseModel


class OutlierWarning(BaseModel):
    """A TTM-summed flow metric where one of the 4 summed quarters looked
    anomalous against its trailing history -- informational only, never
    changes the number it's attached to, a score, or a verdict (see
    ttm.py::sum_last_four_quarters)."""

    metric: str
    date: str | None = None
    value: float
    trailing_median: float


class RefreshResult(BaseModel):
    ticker: str
    cleared_entries: int
    statement_types: list[str]


class TickerSummaryOut(BaseModel):
    company_name: str | None = None
    ticker: str
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    market_cap: float | None = None
    beta: float | None = None
    perf_1m: float | None = None
    perf_6m: float | None = None
    eps_growth_3_5y: float | None = None
    pe_ratio: float | None = None
    next_earnings_date: date | None = None
    # Same figures Step 5's debt ratios are built from (backend/debt_metrics.py)
    # -- latest-quarter snapshot for total_debt, TTM for the other two.
    # Shown for every company type, including Bank/REIT: these are raw
    # figures, not Step 5's classified ratios, so there's no exemption here.
    total_debt: float | None = None
    ebitda_ttm: float | None = None
    # Gross figures, not netted against each other.
    interest_expense_ttm: float | None = None
    interest_income_ttm: float | None = None
    outlier_warnings: list[OutlierWarning] = []
    # Placeholder only — real fair value calculation is out of scope for this phase.
    fair_value_price: float | None = None
    fair_value_verdict: str | None = None


class Step1Out(BaseModel):
    ticker: str
    years: list[str]
    revenue: list[float | None]
    # "Revenue" for every company type except Bank, where it's "Net Interest
    # Income" (revenue's own field mixes interest and non-interest income in
    # a way that obscures the core lending-spread trend for banks). Never
    # silently substituted under the old label -- always shown alongside
    # this field.
    revenue_label: str = "Revenue"
    net_income: list[float | None]
    operating_income: list[float | None]
    # None (the whole field) when the ticker is CFO-exempt (bank / property
    # developer / commodity company) — not a list of nulls.
    cfo: list[float | None] | None = None
    # FCF = CFO - CapEx -- exempt under the exact same conditions as CFO
    # (derived from it, so the same "not a reliable trend signal for these
    # business models" reasoning applies). None (the whole field) whenever
    # cfo is None, never scored independently of CFO's exemption.
    fcf: list[float | None] | None = None
    gross_margin: list[float | None]
    net_margin: list[float | None]
    cfo_exempt_reason: str | None = None
    # Manually-flagged only for now; automated one-off detection is out of
    # scope for this phase (per spec).
    net_income_one_off: bool = False
    cfo_one_off: bool = False
    score: int
    verdict: str
    components: dict


class Step2EstimateRow(BaseModel):
    fiscal_year: str
    growth_avg: float
    growth_high: float
    growth_low: float


class Step2Out(BaseModel):
    ticker: str
    # Which FMP metric the projection is based on -- revenue is preferred,
    # EPS is a fallback when revenue estimates are unavailable (see
    # CLAUDE.md's "Scoring rubric deviations").
    basis: str | None = None
    estimates: list[Step2EstimateRow] = []
    base_fiscal_year: str | None = None
    target_fiscal_year: str | None = None
    growth_rate: float | None = None
    # High/low spread as a % of the average estimate for the target year --
    # labeled "analyst estimate range" in the UI, NOT "source consensus":
    # this is multiple analysts on one platform, not multiple platforms.
    estimate_spread: float | None = None
    # Informational only -- how many analysts the target year's spread is
    # built on; doesn't affect the score.
    target_analyst_count: int | None = None
    # Manually-curated free text; not factored into the score (see
    # CLAUDE.md). Null when nothing has been recorded yet.
    growth_catalysts: str | None = None
    score: int
    verdict: str
    components: dict


class Step5RatioResult(BaseModel):
    value: float
    label: str
    points: int


class Step5Out(BaseModel):
    ticker: str
    # "Standard" / "Bank" / "REIT/Property Developer" -- best-effort
    # sector/industry text match, not a certified determination (see
    # CLAUDE.md's "Scoring rubric deviations").
    company_type: str
    classification_note: str = "Best-effort classification from sector/industry text — not a certified determination."
    ratios: dict[str, Step5RatioResult] = {}
    # Set only when ratios["npl_ratio"] is present -- labels which filing the
    # NPL figure is actually as-of (e.g. "FY2025 annual filing" vs. "Q2
    # 2026"). A fallback to the annual filing (see npl.py) must never be
    # presented as equally current as a ticker where the quarterly figure
    # was available.
    npl_as_of: str | None = None
    # Informational only (deferred-revenue exception) -- not auto-applied to
    # the Current Ratio calculation, per the source doc's manual-review note.
    deferred_revenue_current: float | None = None
    # None for Bank (not yet supported) or when required raw data is
    # missing -- never a fabricated number.
    score: int | None = None
    # "Fail" / "Pass" / "Strong Pass" for scored tickers; "not_supported"
    # for Bank; "insufficient_data" when required figures are missing.
    verdict: str
    hard_fail: bool = False
    outlier_warnings: list[OutlierWarning] = []


class Step4Out(BaseModel):
    ticker: str
    years: list[str]
    # "Standard" / "Bank" / "Insurance" / "Utility" / "REIT/Property
    # Developer" -- best-effort sector/industry text match, shared with
    # Step 5 (see CLAUDE.md's "Scoring rubric deviations").
    company_type: str
    classification_note: str = "Best-effort classification from sector/industry text — not a certified determination."
    roe: list[float | None]
    # None (the whole field) when ROIC is exempt for this company type
    # (Bank / Insurance / Utility) -- not a list of nulls.
    roic: list[float | None] | None = None
    roic_exempt_reason: str | None = None
    revenue: list[float | None]
    accounts_receivable: list[float | None]
    # None (the whole field) when no physical inventory was detected across
    # the reporting window.
    ccc: list[float | None] | None = None
    ccc_exempt_reason: str | None = None
    # None when required raw data is missing -- never a fabricated number.
    score: int | None = None
    # "Fail" / "Pass" / "Strong Pass" for scored tickers; "insufficient_data"
    # when required figures are missing.
    verdict: str
    hard_fail: bool = False
    components: dict = {}
