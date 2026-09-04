import numpy as np
from sqlmodel import Session

from core.cache import get_or_fetch, get_or_fetch_earnings_aware, safe_fetch
from core.config import settings
from core.db import engine
from helpers.earnings import resolve_most_recent_earnings_date
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.schemas import OutlierWarning, Step4Out
from core.tickers import normalize_ticker
from scoring.classification import classify_company_type
from scoring.series_trend import robust_late_direction
from scoring.step4 import (
    AR_DSO_TREND_MATERIALITY_DAYS,
    AR_GAP_NOISE_FLOOR,
    ARResult,
    classify_ccc_trend,
    DIP_RECOVERY_RECENCY_YEARS,
    income_recovery_detail,
    RatioResult,
    recovery_excluded_prefix_length,
    score_revenue_vs_ar,
    score_roe,
    score_roic,
    score_step4,
)
from helpers.ttm import TOTAL_QUARTERS_NEEDED, sum_last_four_quarters

ROIC_EXEMPT_TYPES = {"Bank", "Insurance", "Utility", "REIT/Property Developer"}
# CCC (Cash Conversion Cycle) has no comparable inventory/receivables cash-
# conversion concept for these business models -- Banks/Insurance/Utilities/
# REITs don't sell goods on credit or carry inventory the way CCC assumes.
# This is now a hard gate on company_type, not left to the data-driven
# "inventory reads null/zero" heuristic below alone: that heuristic isn't
# reliable for every REIT (confirmed live -- Realty Income (O) reports a
# non-null/non-zero inventory-tagged figure despite CCC being conceptually
# meaningless for a rental-income business, which previously let CCC score
# 0 and drag Step 4 to a false Fail for a well-regarded REIT).
CCC_EXEMPT_TYPES = {"Bank", "Insurance", "REIT/Property Developer", "Utility"}
# Revenue-vs-Accounts-Receivable isn't a meaningful signal for these company
# types -- a rental-income business (REIT) has no comparable "selling on
# credit" concept, and Bank/Insurance/Utility's own revenue recognition
# doesn't map onto ordinary trade receivables the way a Standard operating
# company's does. Matches CCC_EXEMPT_TYPES exactly (2026-09-04 -- previously
# REIT-only, a deliberate design decision to extend it to the same 4 types
# ROIC/CCC already exempt; see CLAUDE.md's Step 4 deviations).
AR_EXEMPT_TYPES = {"Bank", "Insurance", "REIT/Property Developer", "Utility"}
# Both display AND scoring now use the same 10yr+TTM window, matching Step
# 1 -- a deliberate deviation beyond profitability.md's explicit "5 years"
# language (see CLAUDE.md's Step 4 deviations). There used to be a
# separate, narrower SCORING_ANNUAL_WINDOW
# (5) feeding only the score while display used the full 10 -- that
# decoupling has been removed; a single window now drives both.
ANNUAL_WINDOW = 10


def _annual_series(annual_rows: list[dict], field: str, count: int = ANNUAL_WINDOW) -> list[float | None]:
    # FMP returns annual rows most-recent-first; take the most recent
    # `count` and reverse to chronological (oldest fiscal year first).
    # Always padded to exactly `count` slots (None-padded at the oldest end)
    # so every metric series lines up index-for-index even if one FMP
    # endpoint returns fewer annual periods than another for the same
    # ticker.
    rows = list(reversed(annual_rows[:count]))
    pad = count - len(rows)
    return [None] * pad + [row.get(field) for row in rows]


def _annual_years(*row_sources: list[dict], count: int = ANNUAL_WINDOW) -> list[str]:
    for rows in row_sources:
        if rows:
            trimmed = list(reversed(rows[:count]))
            pad = count - len(trimmed)
            return ["—"] * pad + [row.get("fiscalYear", row.get("date", "")[:4]) for row in trimmed]
    return ["—"] * count


def _clean_aligned(*series: list) -> list[list]:
    """Keep only the index positions where every given series has a
    non-None value, preserving cross-series alignment (e.g. an ROE reading
    and the equity figure it depends on must come from the same period)."""
    n = len(series[0])
    keep = [i for i in range(n) if all(s[i] is not None for s in series)]
    return [[s[i] for i in keep] for s in series]


def _compute_ccc_series(
    revenue: list[float | None],
    cost_of_revenue: list[float | None],
    inventory: list[float | None],
    accounts_receivable: list[float | None],
    accounts_payable: list[float | None],
) -> list[float]:
    ccc = []
    for rev, cogs, inv, ar, ap in zip(revenue, cost_of_revenue, inventory, accounts_receivable, accounts_payable):
        if not rev or not cogs or inv is None or ar is None or ap is None:
            continue
        dio = inv / cogs * 365
        dso = ar / rev * 365
        dpo = ap / cogs * 365
        ccc.append(dio + dso - dpo)
    return ccc


# --- AR manual-check reasoning note (2026-08-01) ------------------------------
# Whenever Revenue-vs-AR lands in any non-healthy tier, attach a note with
# two dynamically-computed signals (which comparison actually drove the
# flag; whether Operating Cash Flow is tracking Net Income over the same
# window -- a lagging OCF alongside rising Net Income is the real red flag
# for revenue being recognized before cash arrives) plus one static prompt
# that can't be answered from FMP's structured data (a business-model shift
# toward longer-payment-term customers). Lives here, not in scoring/step4.py,
# since OCF isn't part of the AR score itself -- purely presentational
# context computed at the orchestration layer where OCF is fetched.
AR_NOTE_BUSINESS_SHIFT_TEXT = (
    "Has the business shifted toward longer-payment-term customers (e.g. moved from retail to "
    "enterprise/B2B, or entered new markets with different payment norms)? That can explain a "
    "genuine AR increase without indicating a collection problem."
)


def _full_period_growth(series: list[float | None]) -> float | None:
    """First-to-last % growth across the whole window -- None when there's
    too little data or the base period isn't meaningfully positive (a
    negative/near-zero OCF or Net Income base year makes a growth
    percentage undefined/misleading, same class of issue AR's own DSO fix
    was built to avoid -- see this module's docstring)."""
    valid = [v for v in series if v is not None]
    if len(valid) < 2 or not valid[0] or valid[0] <= 0:
        return None
    return (valid[-1] - valid[0]) / valid[0] * 100


def _build_ar_note(ar_result: ARResult | None, net_income: list[float | None], ocf: list[float | None]) -> str | None:
    if ar_result is None or ar_result.label in ("healthy", "insufficient_data"):
        return None

    dso_gap = None
    if ar_result.dso_early is not None and ar_result.dso_late_robust is not None:
        dso_gap = ar_result.dso_late_robust - ar_result.dso_early

    if dso_gap is not None and dso_gap > AR_DSO_TREND_MATERIALITY_DAYS:
        signal_sentence = (
            f"Days Sales Outstanding rose from ~{ar_result.dso_early:.0f} to ~{ar_result.dso_late_robust:.0f} "
            "days over the window -- Accounts Receivable has been growing faster than Revenue on a "
            "multi-year basis."
        )
    else:
        trend_clause = (
            f", though the multi-year DSO trend (~{ar_result.dso_early:.0f} -> ~{ar_result.dso_late_robust:.0f} "
            "days) is comparatively mild."
            if dso_gap is not None
            else "."
        )
        signal_sentence = (
            f"Accounts Receivable outpaced Revenue in {ar_result.num_outpacing} of the last "
            f"{ar_result.num_transitions} individual years{trend_clause}"
        )

    ocf_growth = _full_period_growth(ocf)
    ni_growth = _full_period_growth(net_income)
    if ocf_growth is None or ni_growth is None:
        ocf_sentence = "Operating Cash Flow data wasn't available to cross-check against Net Income over this window."
    elif ocf_growth < ni_growth - AR_GAP_NOISE_FLOOR:
        ocf_sentence = (
            f"Operating Cash Flow grew {ocf_growth:.0f}% over the same window while Net Income grew "
            f"{ni_growth:.0f}% -- worth double-checking whether revenue is being recognized before cash "
            "actually arrives."
        )
    else:
        ocf_sentence = (
            f"Operating Cash Flow grew {ocf_growth:.0f}% over the same window, roughly tracking Net "
            f"Income's {ni_growth:.0f}% -- less likely a pure recognition-timing issue."
        )

    return f"{signal_sentence} {ocf_sentence} {AR_NOTE_BUSINESS_SHIFT_TEXT}"


# --- ROE negative-equity reasoning note (2026-08-07) ---------------------------
# score_roe()'s negative-equity substitute stays a binary 100/60 -- a 3-tier
# redesign (buyback-driven vs. accumulated-deficit vs. unreliable-both) was
# investigated and rejected: a Retained-Earnings sign check alone
# misclassifies ~40-55% of real cases, since a company that retires
# repurchased shares (rather than holding treasury stock) routes the
# repurchase cost through Retained Earnings directly, making a healthy
# serial-repurchaser (e.g. FTNT: 10 straight years of positive, growing Net
# Income) read identically to a real accumulated-deficit company under a
# naive sign check. Instead, this note explains what actually happened --
# purely descriptive, never changes score/verdict -- and points the user at
# their own further research (the 10-K equity note, one-time items) rather
# than asserting a cause Fathom can't reliably determine. Lives here, not in
# scoring/step4.py, for the same reason _build_ar_note does: it needs data
# (Retained Earnings, buyback cash flow, ROIC's own result) that isn't part
# of score_roe()'s own scoring inputs.
NEGATIVE_EQUITY_LABELS = {"positive_despite_negative_equity", "negative_equity_inconsistent_income"}

# REIT-only addition to the negative-equity ROE note (see
# _reit_leverage_note_sentence): early/late-window direction, matching the
# same window Margins/CCC/AR already use (scoring/step1.py's
# MARGIN_TREND_WINDOW, scoring/step4.py's CCC_TREND_WINDOW/
# AR_DSO_TREND_WINDOW) rather than inventing a new default. First-pass,
# informal signal based on only 3 REIT examples in the tracked universe
# (SBAC/CCI/IRM as of the 2026-08 REIT framework investigation) -- not a
# validated threshold-based check, so no epsilon/tolerance is applied
# beyond a plain sign read; a tuned tolerance on n=3 would be fabricated
# precision.
REIT_LEVERAGE_TREND_WINDOW = 3
REIT_LEVERAGE_MIN_POINTS = 4


def _fmt_money(value: float | None) -> str:
    """Compact, sign-preserving $ formatting for reasoning text, scaled to
    billions/millions -- callers never need to guard for None separately."""
    if value is None:
        return "not available"
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{sign}${abs_value / 1_000_000:.1f}M"
    return f"{sign}${abs_value:,.0f}"


def _equity_history_sentence(years: list[str], equity: list[float | None]) -> str:
    """Which fiscal year(s) equity was <=0, and whether it's since
    recovered -- from the same raw, 1:1 index-aligned years/equity arrays
    get_step4_data already builds (TTM included), so no realignment
    against the scoring-only _clean_aligned series is needed."""
    negative_idx = [i for i, e in enumerate(equity) if e is not None and e <= 0]
    if not negative_idx:
        return ""
    runs: list[list[int]] = []
    for i in negative_idx:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    period_text = ", ".join(years[run[0]] if len(run) == 1 else f"{years[run[0]]}–{years[run[-1]]}" for run in runs)
    latest_equity = _fmt_money(equity[-1])
    if negative_idx[-1] == len(equity) - 1:
        return f"Shareholders' equity was negative in {period_text} and remains negative as of the latest period (TTM: {latest_equity})."
    return f"Shareholders' equity was negative in {period_text} and has since recovered to positive (TTM: {latest_equity})."


def _income_shape_sentence(shape: str, first: str, last: str) -> str:
    """Names the actual driver of the 100/60 split (one of
    income_recovery_detail's 5 shapes) rather than just restating "equity
    was negative" -- built as a function, not a static dict, since some
    branches need DIP_RECOVERY_RECENCY_YEARS interpolated and others need
    first/last Net Income, and mixing f-string/`.format()` placeholders in
    one template invites exactly the kind of brace-escaping bug this
    avoids."""
    if shape == "always_positive_growing":
        return (
            f"Net Income has been positive throughout the window and grew from {first} to {last}, which is why "
            "this reads as a positive result despite the equity picture above."
        )
    if shape == "always_positive_but_declined":
        return (
            f"Net Income was positive throughout the window but declined from {first} to {last} rather than "
            "growing, which is why this doesn't clear the substitute check despite never posting a loss."
        )
    if shape == "recent_dip":
        return (
            f"Net Income posted a loss within the last {DIP_RECOVERY_RECENCY_YEARS} reported periods, so this "
            "hasn't had time to clear the recovery-recency check yet -- worth checking whether it was a one-off "
            "or the start of a pattern."
        )
    if shape == "old_dip_not_recovered":
        return (
            f"Net Income posted a loss more than {DIP_RECOVERY_RECENCY_YEARS} periods ago, but the trend since "
            f"then hasn't read as a durable recovery -- current (TTM) Net Income is {last}."
        )
    if shape == "old_dip_recovered":
        return (
            f"Net Income posted a loss more than {DIP_RECOVERY_RECENCY_YEARS} periods ago but has since shown a "
            f"durable recovery (TTM Net Income: {last}), which is why this reads as a positive result despite "
            "the equity picture above."
        )
    return ""


def _retained_earnings_and_buyback_sentence(
    retained_earnings: list[float | None], buybacks: list[float | None]
) -> str:
    """Informational only, never causal -- Retained Earnings' sign alone
    can't distinguish accumulated losses from buyback accounting (a
    company that retires repurchased shares routes the cost through
    Retained Earnings directly, confirmed via live data in the feasibility
    investigation this note's design followed from), so this states RE's
    level as context and the buyback cash-flow fact (reliable: 70/70
    tickers checked had this field populated for every period) as
    "consistent with," never "caused by.\""""
    clauses = []
    re_valid = [v for v in retained_earnings if v is not None]
    if re_valid:
        latest_re = re_valid[-1]
        re_state = "positive" if latest_re > 0 else "negative"
        clauses.append(
            f"Retained Earnings is currently {re_state} ({_fmt_money(latest_re)}) -- on its own this doesn't "
            "indicate whether the negative equity above reflects accumulated losses or an accounting effect of "
            "share buybacks (a company that retires repurchased shares routes the repurchase cost through "
            "Retained Earnings directly, which can push it negative even when the company is solidly profitable)."
        )
    # Only negative values are a real repurchase outflow -- a positive
    # value (rare; one such ticker-year was found in a live-data check,
    # likely a reissuance/ESPP-driven net figure) isn't a repurchase and
    # is deliberately excluded rather than misread as one.
    repurchase_periods = [v for v in buybacks if v is not None and v < 0]
    reported_periods = sum(1 for v in buybacks if v is not None)
    if repurchase_periods:
        clauses.append(
            f"The company recorded share repurchases in {len(repurchase_periods)} of the last {reported_periods} "
            f"reported periods, spending a cumulative {_fmt_money(sum(repurchase_periods))} -- consistent with an "
            "active repurchase program."
        )
    else:
        clauses.append("No material share repurchases were recorded over this window.")
    return " ".join(clauses)


def _roic_citation_sentence(
    roic_result: RatioResult | None, roic_exempt_reason: str | None, company_type: str
) -> str:
    """ROIC has no reliability guards today (per the feasibility
    investigation -- FMP's underlying invested-capital figure can be
    near-zero/negative, producing nonsensical ROIC values Fathom doesn't
    currently filter), so a real ROIC result is always cited with an
    explicit caveat, never silently. Company-type exemption is stated
    plainly instead of citing a number. Omitted entirely when ROIC is
    neither exempt nor scoreable (insufficient data) -- nothing to cite."""
    if roic_exempt_reason:
        return f"ROIC isn't computed for {company_type} companies, so it isn't available as a cross-check here."
    if roic_result is not None:
        return (
            f'For additional context, ROIC over the same window currently reads "{roic_result.label}" -- Fathom '
            "doesn't yet validate the reliability of FMP's underlying invested-capital figure, so treat this as "
            "a secondary data point, not confirmation."
        )
    return ""


def _roe_research_pointer(positive_outcome: bool) -> str:
    if positive_outcome:
        return (
            "See the shareholders'-equity note in the most recent 10-K for the specific mechanics behind the "
            "figure above."
        )
    return (
        "Worth reviewing whether the losses are structural/recurring versus a specific one-time item -- check "
        "the income statement's non-operating/one-time line items and the equity note's own explanation for the "
        "deficit."
    )


def _windowed_trend_average(values: list[float], window: int) -> tuple[float, float]:
    """Early-window average and a robust late-window average (single
    most-extreme point excluded) -- same convention scoring/step4.py's
    _dso_trend already uses for AR's own DSO note. Displaying these
    (rather than the raw first/last points) keeps the displayed numbers
    consistent with the direction verb they're paired with: a naive raw
    endpoint pair can read as declining even when the robust trend --
    which the verb is actually based on -- is genuinely improving, whenever
    a single anomalous year sits at either end."""
    arr = np.asarray(values, dtype=float)
    w = min(window, len(arr))
    early = float(arr[:w].mean())
    late_robust = robust_late_direction(arr, window) + early
    return early, late_robust


def _reit_leverage_note_sentence(
    net_income: list[float | None],
    total_assets: list[float | None],
    total_debt: list[float | None],
    years: list[str],
    positive_outcome: bool,
) -> str | None:
    """REIT-only addition to the negative-equity ROE note: Return on Assets
    and Gearing Ratio trends, since Total Assets stay positive even when
    equity goes negative, making ROA a more stable REIT-appropriate
    profitability proxy than the generic NI-consistency substitute above.
    Gearing reuses the exact formula data/step5_data.py's own REIT gearing
    check uses (total_debt/total_assets*100) -- not reimplemented
    differently.

    Purely informational, never touches score_roe()'s own output -- see
    REIT_LEVERAGE_TREND_WINDOW's comment on why no numeric threshold beyond
    a plain sign check is used. Motivating case: IRM's substitute reads
    positive_despite_negative_equity (100) despite a genuinely declining
    ROA and monotonically rising leverage over the same 10yr window -- a
    real gap the NI-only check above can't see on its own.

    Checked on the annual history only ([:-1], dropping the appended TTM
    point) -- same precaution CCC's own inventory-exemption check already
    takes for the same reason (see data_driven_ccc_exempt above): FMP's
    latest-quarter snapshot has proven unreliable for balance-sheet fields
    before (confirmed live for IRM's own totalDebt -- $3.9B in the latest
    quarterly snapshot vs. $19.1B in the FY2025 annual filing it's meant to
    roll forward from, an obvious data-provider artifact, not a real
    single-quarter debt paydown of that size)."""
    ni_aligned, assets_for_roa, _ = _clean_aligned(net_income[:-1], total_assets[:-1], years[:-1])
    debt_aligned, assets_for_gearing, _ = _clean_aligned(total_debt[:-1], total_assets[:-1], years[:-1])

    roa_series = [ni / a * 100 for ni, a in zip(ni_aligned, assets_for_roa) if a]
    gearing_series = [d / a * 100 for d, a in zip(debt_aligned, assets_for_gearing) if a]

    if len(roa_series) < REIT_LEVERAGE_MIN_POINTS or len(gearing_series) < REIT_LEVERAGE_MIN_POINTS:
        return None

    roa_early, roa_late = _windowed_trend_average(roa_series, REIT_LEVERAGE_TREND_WINDOW)
    gearing_early, gearing_late = _windowed_trend_average(gearing_series, REIT_LEVERAGE_TREND_WINDOW)
    roa_direction = roa_late - roa_early
    gearing_direction = gearing_late - gearing_early

    roa_verb = "improved" if roa_direction >= 0 else "declined"
    gearing_verb = "risen" if gearing_direction >= 0 else "fallen"
    sentence = (
        f"Return on Assets has {roa_verb} from ~{roa_early:.1f}% to ~{roa_late:.1f}% and Gearing has "
        f"{gearing_verb} from ~{gearing_early:.1f}% to ~{gearing_late:.1f}% over the trailing "
        f"{len(roa_series)} fiscal years."
    )

    if positive_outcome and roa_direction < 0 and gearing_direction > 0:
        sentence += (
            " Note: despite the negative-equity substitute reading positive here, this declining-ROA/"
            "rising-gearing combination may warrant a closer look -- an informal read based on a small "
            "sample of REITs, not a validated threshold."
        )
    return sentence


def _recovery_exclusion_sentence(years_excluded: list[str]) -> str | None:
    """Descriptive-only, never causal -- fires whenever
    recovery_excluded_prefix_length() finds a resolved dip to exclude,
    regardless of whether the exclusion actually helped this ticker's
    score (it doesn't always -- a genuine long-term decliner whose only
    strong years sit before a resolved-by-age dip can score WORSE once
    those years are excluded, see profitability.md's documented
    LHX/LUV-shaped tradeoff). Deliberately mechanical/neutral wording, not
    "this improved the score," so the note reads honestly either way."""
    if not years_excluded:
        return None
    span = years_excluded[0] if len(years_excluded) == 1 else f"{years_excluded[0]}–{years_excluded[-1]}"
    return (
        f"{len(years_excluded)} early year(s) ({span}) excluded from this average — performance dipped "
        "during that stretch and has since durably recovered, so those years no longer represent current "
        "performance."
    )


def _build_roe_note(
    roe_result: RatioResult,
    years: list[str],
    equity: list[float | None],
    retained_earnings: list[float | None],
    buybacks: list[float | None],
    net_income_clean: list[float],
    roic_result: RatioResult | None,
    roic_exempt_reason: str | None,
    company_type: str,
    roe_clean: list[float],
    years_for_roe: list[str],
    net_income: list[float | None],
    total_assets: list[float | None],
    total_debt: list[float | None],
) -> str | None:
    """Only attaches when the negative-equity substitute actually fired
    (mirrors _build_ar_note's "only when there's something to explain"
    gating) -- applies to every company type that reaches this path,
    including REIT (REIT was only carved out of the *scoring* redesign
    investigated and rejected above, not this display-only change; REIT
    tickers still run through score_roe() unconditionally today, and this
    text makes no company-type-specific claims, so it's safe here).

    `net_income`/`total_assets`/`total_debt` (the raw, un-cleaned series --
    not net_income_clean) feed the REIT-only ROA/Gearing leverage sentence
    (_reit_leverage_note_sentence) appended below when company_type is
    REIT/Property Developer; unused otherwise.

    The negative-equity substitute takes priority: if it fired, ROE never
    reached the normal avg/min-year path at all, so recovery-aware
    exclusion is irrelevant and isn't checked. Otherwise, checks whether
    recovery_excluded_prefix_length() found a resolved dip to exclude --
    the same function score_roe() itself already called internally,
    re-derived here purely for the note text (mirrors how
    income_recovery_detail() is called independently by both score_roe()
    and this function, never threaded through RatioResult)."""
    if roe_result.label in NEGATIVE_EQUITY_LABELS:
        detail = income_recovery_detail(net_income_clean)
        first_ni, last_ni = _fmt_money(net_income_clean[0]), _fmt_money(net_income_clean[-1])

        sentences = [
            _equity_history_sentence(years, equity),
            _income_shape_sentence(detail.shape, first_ni, last_ni),
            _retained_earnings_and_buyback_sentence(retained_earnings, buybacks),
            _roic_citation_sentence(roic_result, roic_exempt_reason, company_type),
            _roe_research_pointer(roe_result.label == "positive_despite_negative_equity"),
        ]
        if company_type == "REIT/Property Developer":
            sentences.append(
                _reit_leverage_note_sentence(
                    net_income,
                    total_assets,
                    total_debt,
                    years,
                    roe_result.label == "positive_despite_negative_equity",
                )
            )
        return " ".join(s for s in sentences if s)

    excluded = recovery_excluded_prefix_length(roe_clean)
    return _recovery_exclusion_sentence(years_for_roe[:excluded])


def _build_roic_note(roic_result: RatioResult, roic_clean: list[float], years_for_roic: list[str]) -> str | None:
    """ROIC has no negative-equity-substitute-equivalent path -- the only
    note-worthy mechanism today is recovery-aware exclusion, re-derived
    here the same way _build_roe_note re-derives it for ROE."""
    excluded = recovery_excluded_prefix_length(roic_clean)
    return _recovery_exclusion_sentence(years_for_roic[:excluded])


async def get_step4_data(ticker: str, cache_only: bool = False) -> Step4Out:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        most_recent_earnings_date = await resolve_most_recent_earnings_date(session, ticker, staleness_days, cache_only)
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session,
                    ticker,
                    "profile",
                    "latest",
                    lambda: fmp_client.get_profile(ticker),
                    settings.profile_staleness_days,
                    cache_only,
                ),
            )
        )
        company_type = classify_company_type(
            profile.get("sector"), profile.get("industry"), ticker, is_fund=bool(profile.get("isEtf") or profile.get("isFund"))
        )

        # Same cache key + limit Step 1 already populates ("income_statement"
        # / "annual", limit 10) -- requesting a different limit here would
        # fight over the same cache row (see CLAUDE.md's caching policy).
        income_annual = await safe_fetch(
            "income_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "income_statement",
                "annual",
                lambda: fmp_client.get_income_statement(ticker, "annual", 10),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        income_quarterly = await safe_fetch(
            "income_statement_quarterly",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "income_statement",
                "quarterly",
                lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        balance_sheet_annual = await safe_fetch(
            "balance_sheet_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "balance_sheet_statement",
                "annual",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        # Same cache key Step 5 and the Financials tab (financials_data.py)
        # also populate ("balance_sheet_statement"/"quarterly") -- limit is
        # TOTAL_QUARTERS_NEEDED so the Financials tab has real quarterly
        # history; this call site still only reads row 0 (the latest
        # quarter, used as the "TTM" column stand-in below), so the deeper
        # fetch doesn't change anything here.
        balance_sheet_quarterly = await safe_fetch(
            "balance_sheet_statement_quarterly",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "balance_sheet_statement",
                "quarterly",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        key_metrics_annual = await safe_fetch(
            "key_metrics_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "key_metrics",
                "annual",
                lambda: fmp_client.get_key_metrics(ticker, "annual", ANNUAL_WINDOW),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        key_metrics_ttm = _first(
            await safe_fetch(
                "key_metrics_ttm",
                get_or_fetch_earnings_aware(
                    session,
                    ticker,
                    "key_metrics",
                    "ttm",
                    lambda: fmp_client.get_key_metrics_ttm(ticker),
                    staleness_days,
                    most_recent_earnings_date,
                    cache_only,
                ),
            )
        )
        # Same cache key + limit Step 1 already populates ("cash_flow_
        # statement"/"annual" and "/quarterly") -- only used here for the
        # AR manual-check note's OCF-vs-Net-Income cross-check, so for any
        # ticker Step 1 has already scored this is a pure cache hit, zero
        # new FMP calls.
        cash_flow_annual = await safe_fetch(
            "cash_flow_statement_annual",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "cash_flow_statement",
                "annual",
                lambda: fmp_client.get_cash_flow_statement(ticker, "annual", 10),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        cash_flow_quarterly = await safe_fetch(
            "cash_flow_statement_quarterly",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "cash_flow_statement",
                "quarterly",
                lambda: fmp_client.get_cash_flow_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )

    income_annual = income_annual if isinstance(income_annual, list) else []
    income_quarterly = income_quarterly if isinstance(income_quarterly, list) else []
    balance_sheet_annual = balance_sheet_annual if isinstance(balance_sheet_annual, list) else []
    key_metrics_annual = key_metrics_annual if isinstance(key_metrics_annual, list) else []
    cash_flow_annual = cash_flow_annual if isinstance(cash_flow_annual, list) else []
    cash_flow_quarterly = cash_flow_quarterly if isinstance(cash_flow_quarterly, list) else []
    balance_sheet_latest = _first(balance_sheet_quarterly)

    years = _annual_years(income_annual, balance_sheet_annual, key_metrics_annual)
    revenue = _annual_series(income_annual, "revenue")
    net_income = _annual_series(income_annual, "netIncome")
    cost_of_revenue = _annual_series(income_annual, "costOfRevenue")
    equity = _annual_series(balance_sheet_annual, "totalStockholdersEquity")
    accounts_receivable = _annual_series(balance_sheet_annual, "accountsReceivables")
    inventory = _annual_series(balance_sheet_annual, "inventory")
    accounts_payable = _annual_series(balance_sheet_annual, "accountPayables")
    long_term_debt = _annual_series(balance_sheet_annual, "longTermDebt")
    short_term_debt = _annual_series(balance_sheet_annual, "shortTermDebt")
    # Both feed the REIT negative-equity ROE note only (_reit_leverage_note_
    # sentence) -- same already-fetched balance_sheet_annual rows Step 5
    # reads totalDebt/totalAssets from for its own gearing_ratio, so this is
    # a field-read, not a new fetch.
    total_assets = _annual_series(balance_sheet_annual, "totalAssets")
    total_debt = _annual_series(balance_sheet_annual, "totalDebt")
    roe = _annual_series(key_metrics_annual, "returnOnEquity")
    roic = _annual_series(key_metrics_annual, "returnOnInvestedCapital")
    ocf = _annual_series(cash_flow_annual, "netCashProvidedByOperatingActivities")
    # Both feed the ROE reasoning-text builder (_build_roe_note) only --
    # neither is part of score_roe()'s own scoring inputs. Already on
    # statements this function fetches in full for other reasons (balance
    # sheet for equity, cash flow for the AR note's OCF cross-check), so
    # this is a field-read, not a new fetch.
    retained_earnings = _annual_series(balance_sheet_annual, "retainedEarnings")
    buybacks = _annual_series(cash_flow_annual, "commonStockRepurchased")
    # FMP's returnOnEquity/returnOnInvestedCapital are fractions (e.g. 0.31
    # for 31%) -- convert to percent to match the doc's 8/12/15% thresholds.
    roe = [v * 100 if v is not None else None for v in roe]
    roic = [v * 100 if v is not None else None for v in roic]

    years = years + ["TTM"]
    revenue_result = sum_last_four_quarters(income_quarterly, "revenue", income_annual)
    net_income_result = sum_last_four_quarters(income_quarterly, "netIncome", income_annual)
    cost_of_revenue_result = sum_last_four_quarters(income_quarterly, "costOfRevenue", income_annual)
    ocf_result = sum_last_four_quarters(cash_flow_quarterly, "netCashProvidedByOperatingActivities", cash_flow_annual)
    buybacks_result = sum_last_four_quarters(cash_flow_quarterly, "commonStockRepurchased", cash_flow_annual)

    revenue = revenue + [revenue_result.total]
    net_income = net_income + [net_income_result.total]
    cost_of_revenue = cost_of_revenue + [cost_of_revenue_result.total]
    ocf = ocf + [ocf_result.total]
    equity = equity + [balance_sheet_latest.get("totalStockholdersEquity")]
    accounts_receivable = accounts_receivable + [balance_sheet_latest.get("accountsReceivables")]
    inventory = inventory + [balance_sheet_latest.get("inventory")]
    accounts_payable = accounts_payable + [balance_sheet_latest.get("accountPayables")]
    long_term_debt = long_term_debt + [balance_sheet_latest.get("longTermDebt")]
    short_term_debt = short_term_debt + [balance_sheet_latest.get("shortTermDebt")]
    total_assets = total_assets + [balance_sheet_latest.get("totalAssets")]
    total_debt = total_debt + [balance_sheet_latest.get("totalDebt")]
    retained_earnings = retained_earnings + [balance_sheet_latest.get("retainedEarnings")]
    buybacks = buybacks + [buybacks_result.total]

    # Informational only -- never changes revenue/net_income/ocf or the
    # score/verdict below (see ttm.py::sum_last_four_quarters). Same
    # convention as Step 1/Step 5/the ticker header; Step 4 previously
    # computed these flags via sum_last_four_quarters and silently
    # discarded them.
    outlier_warnings = [
        OutlierWarning(metric=metric, date=fq.date, value=fq.value, trailing_median=fq.trailing_median)
        for metric, result in [
            ("revenue", revenue_result),
            ("net_income", net_income_result),
            ("cost_of_revenue", cost_of_revenue_result),
            ("ocf", ocf_result),
            ("buybacks", buybacks_result),
        ]
        for fq in result.flagged
    ]

    roe_ttm = key_metrics_ttm.get("returnOnEquityTTM")
    roic_ttm = key_metrics_ttm.get("returnOnInvestedCapitalTTM")
    roe = roe + [roe_ttm * 100 if roe_ttm is not None else None]
    roic = roic + [roic_ttm * 100 if roic_ttm is not None else None]

    roic_exempt = company_type in ROIC_EXEMPT_TYPES
    roic_exempt_reason = (
        f"ROIC not applicable for {company_type} — structurally high leverage is core to the business "
        "model, not mismanagement (assessed on ROE only)."
        if roic_exempt
        else None
    )

    # Data-driven detection (unchanged for Standard/other company types): no
    # physical inventory across all 10 annual filings reads as inventory
    # being 0 or null in every year (confirmed reliable for CRM, ADBE; MSFT
    # is a notable false-negative risk since it carries real hardware
    # inventory despite being thought of as "pure software"). Checked
    # against the full annual history now that scoring itself uses the full
    # 10yr window -- deliberately still checked on the annual history only,
    # not the latest-quarter snapshot appended below: FMP's quarterly
    # inventory figure has proven unreliable for inventory-free companies
    # (e.g. MA shows +$2.06B, NOW shows -$28M in their latest quarter
    # despite straight clean-zero annual years) -- a likely data-provider
    # classification artifact, not a real change in the business.
    #
    # Bank/Insurance/REIT/Utility are exempted unconditionally via
    # CCC_EXEMPT_TYPES above regardless of what this heuristic finds -- see
    # that constant's comment for why the heuristic alone isn't trustworthy
    # for these types.
    company_type_ccc_exempt = company_type in CCC_EXEMPT_TYPES
    data_driven_ccc_exempt = all(v is None or v == 0 for v in inventory[:-1])
    ccc_exempt = company_type_ccc_exempt or data_driven_ccc_exempt
    if company_type_ccc_exempt:
        ccc_exempt_reason = f"CCC not applicable for {company_type} — no comparable inventory/receivables cash-conversion cycle for this business model."
    elif data_driven_ccc_exempt:
        ccc_exempt_reason = "No physical inventory detected across the reporting window — CCC not applicable."
    else:
        ccc_exempt_reason = None

    ar_exempt = company_type in AR_EXEMPT_TYPES
    ar_exempt_reason = (
        f"Revenue vs. Accounts Receivable not applicable for {company_type} — no comparable "
        "\"selling on credit\" concept for this business model."
        if ar_exempt
        else None
    )

    roe_clean, equity_clean, net_income_clean, years_for_roe = _clean_aligned(roe, equity, net_income, years)
    revenue_clean, ar_clean = _clean_aligned(revenue, accounts_receivable)

    # revenue_clean/ar_clean only feed the AR check -- when it's exempt
    # (REIT), a data gap there shouldn't block the rest of Step 4 from
    # scoring, since nothing downstream still needs those series.
    if len(roe_clean) < 2 or (not ar_exempt and len(revenue_clean) < 2):
        return Step4Out(
            ticker=ticker,
            years=years,
            company_type=company_type,
            roe=roe,
            roic=None if roic_exempt else roic,
            roic_exempt_reason=roic_exempt_reason,
            revenue=revenue,
            accounts_receivable=accounts_receivable,
            long_term_debt=long_term_debt,
            short_term_debt=short_term_debt,
            ccc=None,
            ccc_exempt_reason=ccc_exempt_reason,
            revenue_vs_ar_exempt_reason=ar_exempt_reason,
            score=None,
            verdict="insufficient_data",
            outlier_warnings=outlier_warnings,
        )

    roe_result = score_roe(roe_clean, equity_clean, net_income_clean)
    ar_result = None if ar_exempt else score_revenue_vs_ar(revenue_clean, ar_clean)

    roic_result = None
    roic_clean: list[float] = []
    years_for_roic: list[str] = []
    if not roic_exempt:
        roic_clean, years_for_roic = _clean_aligned(roic, years)
        roic_result = score_roic(roic_clean) if len(roic_clean) >= 2 else None

    # ccc_series now feeds both display (Step4Out.ccc) and scoring directly
    # -- no separate scoring-window recomputation needed now that the two
    # windows are the same.
    ccc_series: list[float] | None = None
    ccc_result = None
    if not ccc_exempt:
        ccc_series = _compute_ccc_series(revenue, cost_of_revenue, inventory, accounts_receivable, accounts_payable)
        if len(ccc_series) >= 2:
            ccc_result = classify_ccc_trend(ccc_series)

    result = score_step4(roe_result, ar_result, roic_result, ccc_result)
    if result["components"]["revenue_vs_ar"] is not None:
        result["components"]["revenue_vs_ar"]["note"] = _build_ar_note(ar_result, net_income, ocf)
    result["components"]["roe"]["note"] = _build_roe_note(
        roe_result,
        years,
        equity,
        retained_earnings,
        buybacks,
        net_income_clean,
        roic_result,
        roic_exempt_reason,
        company_type,
        roe_clean,
        years_for_roe,
        net_income,
        total_assets,
        total_debt,
    )
    if result["components"]["roic"] is not None:
        result["components"]["roic"]["note"] = _build_roic_note(roic_result, roic_clean, years_for_roic)

    return Step4Out(
        ticker=ticker,
        years=years,
        company_type=company_type,
        roe=roe,
        roic=None if roic_exempt else roic,
        roic_exempt_reason=roic_exempt_reason,
        revenue=revenue,
        accounts_receivable=accounts_receivable,
        long_term_debt=long_term_debt,
        short_term_debt=short_term_debt,
        ccc=None if ccc_exempt else ccc_series,
        ccc_exempt_reason=ccc_exempt_reason,
        revenue_vs_ar_exempt_reason=ar_exempt_reason,
        score=result["score"],
        verdict=result["verdict"],
        hard_fail=result["hard_fail"],
        components=result["components"],
        roe_roic_divergence_note=result["roe_roic_divergence_note"],
        outlier_warnings=outlier_warnings,
    )
