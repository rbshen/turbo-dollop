"""Per-data-group FMP toggles: the single source of truth for whether a
given FMP-backed feature area may make live calls.

Replaces the old process-start `FMP_ENABLED` / `INSIDER_ACTIVITY_ENABLED`
env flags. State lives in the DB (`DataGroupSetting` per group,
`DataGroupGlobal` singleton for the master switch and the user's FMP plan),
so a toggle applies live -- no restart -- and cron processes (separate
`uv run` processes) read the same truth as the API. A short in-process
cache (`CACHE_TTL_SECONDS`) keeps the per-call gate cheap; every write in
this module invalidates it.

Effective state of a group = master switch on AND group enabled AND
required tier <= my plan AND status != plan_restricted (see
`effective_state`). "Off" always means cache-only: the last cached row is
served, nothing is ever wiped.

Gate points (see CLAUDE.md "Data groups"):
  * clients.fmp_client.FMPClient.get -- ENDPOINT_GROUP (endpoint -> group),
    raises FMPGroupDisabledError (a FMPDisabledError subclass).
  * core.cache get_or_fetch / get_or_fetch_earnings_aware / force_fetch --
    STATEMENT_TYPE_GROUP (FundamentalsCache.statement_type -> group).
  * nightly jobs -- `job_skip_reason(group)`.
A test (tests/test_data_groups_registry.py) fails if any endpoint or cached
statement type used in the code is unmapped.

`engine` is a module-level reference so tests can monkeypatch it
independently (the per-module engine-isolation convention)."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from core.db import engine
from core.models import DataGroupGlobal, DataGroupSetting, FundamentalsCache

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 5.0
# Consecutive non-402 live failures before the chip reads "Failing".
FAILING_AFTER_CONSECUTIVE = 3
# Throttle for last_success_at writes -- FMPClient.get succeeds thousands of
# times a night; one write per group per interval is plenty for a chip.
SUCCESS_WRITE_INTERVAL_SECONDS = 60.0

TIERS = ("Starter", "Premium", "Ultimate")
DEFAULT_FMP_PLAN = "Ultimate"


@dataclass(frozen=True)
class GroupMeta:
    label: str
    default_tier: str
    default_enabled: bool
    # Wired to real FMP calls. The others are seeded rows only
    # (extended_hours lands in P5).
    live: bool
    feeds: tuple[str, ...]
    # A group with a non-FMP fallback provider still wired (daily_prices while
    # Yahoo exists, P2-P5): turning it off does NOT mean cache-only --
    # its consumers skip FMP and fall through to the fallback chain. Its chip
    # reads "Off -- using fallback" instead of "Cached only". Removed in P6.
    falls_back: bool = False


GROUPS: dict[str, GroupMeta] = {
    "fundamentals": GroupMeta(
        "Fundamentals", "Premium", True, True,
        ("Analysis tab (Steps 1-5)", "Valuation", "Screener scores", "Watchlist scores", "Nightly fundamentals fetch"),
    ),
    "profile_quote": GroupMeta(
        "Profile & quote", "Starter", True, True,
        ("Ticker header (price, change, market cap)", "Ticker search", "Refresh button"),
    ),
    "analyst_ratings": GroupMeta(
        "Analyst ratings", "Premium", True, True,
        ("Analyst Ratings tab", "Watchlist rating column", "Nightly price-target snapshot"),
    ),
    "segmentation": GroupMeta("Segmentation", "Premium", True, True, ("Segmentation card",)),
    "news": GroupMeta("News", "Starter", True, True, ("News tab",)),
    "insider": GroupMeta("Insider activity", "Premium", False, True, ("Insider Activity tab (shelved)",)),
    "index_membership": GroupMeta(
        "Index membership", "Starter", True, True,
        ("S&P 500 / Dow / Nasdaq constituent lists", "Screener universe", "Weekly index refresh jobs"),
    ),
    "corporate_events": GroupMeta("Corporate events", "Premium", True, True, ("Chart earnings/dividend markers", "Earnings / dividends / splits cache", "Delisted-ticker flags")),
    "daily_prices": GroupMeta(
        "Daily prices", "Premium", True, True,
        (
            "Trend / Weinstein stage", "Liquidity Zones", "Sector Heatmap", "Market Breadth", "Momentum",
            "Chart tab (daily ranges)", "Header avg-volume / dollar-volume",
        ),
        falls_back=True,
    ),
    # P3: US history beyond the nightly ~5y -- fetched on demand into the
    # dedicated long-history table (clients/long_history_bars.py).
    "daily_prices_long": GroupMeta(
        "Daily prices (long history)", "Premium", True, True,
        ("Chart tab (weekly 4y range)", "Analyst Ratings price overlay (10y)"),
        falls_back=True,
    ),
    # P3: every non-US listing (HKSE today): nightly bars, on-demand long
    # history, Chart and the analyst overlay. US tickers never consult it.
    "daily_prices_intl": GroupMeta(
        "Daily prices (international)", "Ultimate", True, True,
        (
            "Non-US tickers' Trend / Weinstein stage and Liquidity Zones", "Chart tab (non-US tickers)",
            "Analyst Ratings price overlay (non-US tickers)",
        ),
        falls_back=True,
    ),
    # P4 (2026-09-26): FMP `/historical-chart/1hour` (RTH-only, split- not dividend-adjusted)
    # feeds the shared "60m" bars behind Warren and BB+RSI for US-listed tickers. Off falls
    # through to Yahoo (NOT cache-only), like the daily groups.
    "intraday_bars": GroupMeta(
        "Intraday bars", "Premium", True, True,
        ("Warren RSI/ADX/WVF entry signal (2h)", "BB+RSI entry signal (2h)", "Chart tab entry-signal markers"),
        falls_back=True,
    ),
    "extended_hours": GroupMeta("Extended hours", "Premium", True, False, ("(not wired yet -- P5)",)),
}

# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

# FMP endpoint path -> group. A call may pass an explicit `group=` override to
# FMPClient.get when the same endpoint serves two features (see
# ENDPOINT_GROUP_OVERRIDES_USED below).
ENDPOINT_GROUP: dict[str, str] = {
    "/profile": "profile_quote",
    "/quote": "profile_quote",
    "/stock-price-change": "profile_quote",
    "/search-symbol": "profile_quote",
    "/search-name": "profile_quote",
    "/analyst-estimates": "fundamentals",
    "/ratios": "fundamentals",
    "/ratios-ttm": "fundamentals",
    "/key-metrics": "fundamentals",
    "/key-metrics-ttm": "fundamentals",
    "/income-statement": "fundamentals",
    "/cash-flow-statement": "fundamentals",
    "/balance-sheet-statement": "fundamentals",
    "/enterprise-values": "fundamentals",
    "/financial-growth": "fundamentals",
    "/financial-statement-full-as-reported": "fundamentals",
    "/earnings": "fundamentals",
    # P2: daily EOD (split- AND spin-off-adjusted, not dividend-adjusted) feeds the
    # shared bars cache, the Chart tab's daily ranges and the header's
    # avg-volume tiles (ticker_summary's `historical_price_eod` cache key).
    # P3: the same endpoint also serves `daily_prices_long` (US history beyond the
    # nightly window) and `daily_prices_intl` (non-US); each caller passes an
    # explicit `group=` (see ENDPOINT_GROUP_OVERRIDES_USED).
    "/historical-price-eod/full": "daily_prices",
    # P4: hourly RTH bars (naive ET timestamps, newest first) for the shared "60m" cache.
    "/historical-chart/1hour": "intraday_bars",
    "/dividends": "corporate_events",
    "/splits": "corporate_events",
    "/delisted-companies": "corporate_events",
    "/revenue-product-segmentation": "segmentation",
    "/revenue-geographic-segmentation": "segmentation",
    "/news/stock": "news",
    "/grades-consensus": "analyst_ratings",
    "/grades-historical": "analyst_ratings",
    "/price-target-consensus": "analyst_ratings",
    "/price-target-news": "analyst_ratings",
    "/price-target-summary": "analyst_ratings",
    "/insider-trading/search": "insider",
    "/insider-trading/statistics": "insider",
    "/sp500-constituent": "index_membership",
    "/dowjones-constituent": "index_membership",
    "/nasdaq-constituent": "index_membership",
}

# Endpoints reached by more than one group, and the group each caller passes
# explicitly. Documented (and asserted by the registry test) so the mixing is
# a decision, not an accident.
ENDPOINT_GROUP_OVERRIDES_USED: dict[str, dict[str, str]] = {
    # /earnings: FundamentalsCache `earnings` (staleness logic) vs the Chart tab's
    # 40-row history for E markers.
    "/earnings": {"get_earnings": "fundamentals", "get_earnings_history": "corporate_events"},
    # /quote: profile_quote's live quote vs the Valuation tab's `<CCY>USD` FX rate.
    "/quote": {"get_quote": "profile_quote", "get_forex_quote": "fundamentals"},
    # /historical-price-eod/full: `get_historical_price_eod` takes the group as a
    # parameter (default "daily_prices"; long-history and non-US callers pass
    # "daily_prices_long" / "daily_prices_intl") -- see FMPClient.
    "/historical-price-eod/full": {"get_historical_price_eod": "daily_prices"},
}

# Canary request per live group, used by FMPClient.probe_group (weekly and on
# plan edit) to see whether a plan_restricted group works again. Always AAPL
# and always a cheap single-row call.
PROBE_ENDPOINTS: dict[str, tuple[str, dict]] = {
    "fundamentals": ("/income-statement", {"symbol": "AAPL", "period": "annual", "limit": 1}),
    "profile_quote": ("/quote", {"symbol": "AAPL"}),
    "analyst_ratings": ("/grades-consensus", {"symbol": "AAPL"}),
    "segmentation": ("/revenue-product-segmentation", {"symbol": "AAPL"}),
    "news": ("/news/stock", {"symbols": "AAPL", "limit": 1}),
    "insider": ("/insider-trading/statistics", {"symbol": "AAPL"}),
    "index_membership": ("/dowjones-constituent", {}),
    "corporate_events": ("/dividends", {"symbol": "AAPL", "limit": 1}),
    "daily_prices": ("/historical-price-eod/full", {"symbol": "AAPL", "from": "2024-01-02", "to": "2024-01-05"}),
    # A long-history canary: a window older than the 5y Starter horizon.
    "daily_prices_long": ("/historical-price-eod/full", {"symbol": "AAPL", "from": "2016-01-04", "to": "2016-01-08"}),
    "intraday_bars": ("/historical-chart/1hour", {"symbol": "AAPL", "from": "2024-01-02", "to": "2024-01-03"}),
    # The one group whose canary is deliberately NOT AAPL: it must be a non-US symbol.
    "daily_prices_intl": ("/historical-price-eod/full", {"symbol": "0005.HK", "from": "2024-01-02", "to": "2024-01-05"}),
}

# Groups whose 402 canary is a non-US symbol (PROBE_ENDPOINTS) instead of AAPL.
NON_US_CANARY_GROUPS: frozenset[str] = frozenset({"daily_prices_intl"})

# Bulk/batch endpoints (none are used today -- Rule: never call them). If one
# is ever added it must be listed here AND be Ultimate; the registry test
# enforces that every listed path is in ENDPOINT_GROUP's Ultimate-tier group.
BULK_ENDPOINTS: frozenset[str] = frozenset()

# FundamentalsCache.statement_type -> group (the cache gate).
STATEMENT_TYPE_GROUP: dict[str, str] = {
    "profile": "profile_quote",
    "quote": "profile_quote",
    "price_change": "profile_quote",
    "forex_rate": "fundamentals",
    "income_statement": "fundamentals",
    "cash_flow_statement": "fundamentals",
    "balance_sheet_statement": "fundamentals",
    "key_metrics": "fundamentals",
    "ratios": "fundamentals",
    "enterprise_values": "fundamentals",
    "financial_growth": "fundamentals",
    "financial_statement_full_as_reported": "fundamentals",
    "analyst_estimates": "fundamentals",
    "earnings": "fundamentals",
    "historical_price_eod": "daily_prices",
    "revenue_product_segmentation": "segmentation",
    "revenue_geographic_segmentation": "segmentation",
    "grades_consensus": "analyst_ratings",
    "grades_historical": "analyst_ratings",
    "price_target_consensus": "analyst_ratings",
    "price_target_summary": "analyst_ratings",
    "price_target_news": "analyst_ratings",
    "insider_trading_search": "insider",
    "insider_trading_statistics": "insider",
    "news": "news",
    # Not an FMP call (SEC EDGAR), but cached through the same gate and feeds
    # the Debt/fundamentals cross-check; it was paused by the old global flag,
    # so it rides with `fundamentals` to keep that behaviour.
    "sec_company_facts": "fundamentals",
}


def group_for_endpoint(endpoint: str) -> str | None:
    return ENDPOINT_GROUP.get(endpoint)


def group_for_statement_type(statement_type: str) -> str | None:
    return STATEMENT_TYPE_GROUP.get(statement_type)


# ---------------------------------------------------------------------------
# State snapshot (cached)
# ---------------------------------------------------------------------------


@dataclass
class GroupState:
    enabled: bool
    required_tier: str
    tier_verified: bool
    status: str
    restricted_since: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    consecutive_failures: int


@dataclass
class Snapshot:
    master_on: bool
    fmp_plan: str
    key_problem_at: datetime | None
    key_problem_detail: str | None
    groups: dict[str, GroupState] = field(default_factory=dict)


_cache: tuple[int, float, Snapshot] | None = None  # (id(engine), loaded_at, snapshot)
_last_success_write: dict[str, float] = {}


def invalidate_cache() -> None:
    global _cache
    _cache = None


def _tier_rank(tier: str) -> int:
    try:
        return TIERS.index(tier)
    except ValueError:
        return len(TIERS)  # unknown tier is never satisfied


def _seed(session: Session) -> None:
    """Lazy seed: create any missing group row / the global row."""
    existing = {r.group_key for r in session.exec(select(DataGroupSetting)).all()}
    changed = False
    for key, meta in GROUPS.items():
        if key not in existing:
            session.add(
                DataGroupSetting(
                    group_key=key, enabled=meta.default_enabled, required_tier=meta.default_tier, tier_verified=False
                )
            )
            changed = True
    if session.get(DataGroupGlobal, "default") is None:
        session.add(DataGroupGlobal(key="default", master_on=True, fmp_plan=DEFAULT_FMP_PLAN))
        changed = True
    if changed:
        session.commit()


def _load() -> Snapshot:
    SQLModel.metadata.create_all(engine, tables=[DataGroupSetting.__table__, DataGroupGlobal.__table__])
    with Session(engine) as session:
        _seed(session)
        g = session.get(DataGroupGlobal, "default")
        rows = session.exec(select(DataGroupSetting)).all()
        return Snapshot(
            master_on=g.master_on,
            fmp_plan=g.fmp_plan,
            key_problem_at=g.key_problem_at,
            key_problem_detail=g.key_problem_detail,
            groups={
                r.group_key: GroupState(
                    r.enabled, r.required_tier, r.tier_verified, r.status, r.restricted_since,
                    r.last_success_at, r.last_error, r.consecutive_failures,
                )
                for r in rows
                if r.group_key in GROUPS
            },
        )


def _default_snapshot() -> Snapshot:
    return Snapshot(
        True, DEFAULT_FMP_PLAN, None, None,
        {k: GroupState(m.default_enabled, m.default_tier, False, "ok", None, None, None, 0) for k, m in GROUPS.items()},
    )


def get_snapshot() -> Snapshot:
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] == id(engine) and now - _cache[1] < CACHE_TTL_SECONDS:
        return _cache[2]
    try:
        snap = _load()
    except Exception:
        # Never let a config-read failure take the app down; fall back to the
        # seed defaults (and do not cache, so the next call retries).
        logger.warning("data_groups: could not read group settings; using defaults", exc_info=True)
        return _default_snapshot()
    _cache = (id(engine), now, snap)
    return snap


# ---------------------------------------------------------------------------
# Effective state
# ---------------------------------------------------------------------------


def effective_state_from(snap: Snapshot, group: str) -> tuple[bool, str]:
    """(is_live, reason). reason is one of: live, master_off, user_off,
    above_plan, restricted."""
    state = snap.groups.get(group)
    if state is None:
        return False, "user_off"
    if not snap.master_on:
        return False, "master_off"
    if not state.enabled:
        return False, "user_off"
    if _tier_rank(state.required_tier) > _tier_rank(snap.fmp_plan):
        return False, "above_plan"
    if state.status == "plan_restricted":
        return False, "restricted"
    return True, "live"


def effective_state(group: str) -> tuple[bool, str]:
    return effective_state_from(get_snapshot(), group)


def group_live(group: str) -> bool:
    return effective_state(group)[0]


def master_on() -> bool:
    return get_snapshot().master_on


def group_user_enabled(group: str) -> bool:
    """The user's own toggle only (ignores master/plan/restriction). For a
    feature that is *shelved* rather than merely paused: master-off or a
    restriction still serve cached rows, a user-off group serves nothing."""
    state = get_snapshot().groups.get(group)
    return bool(state and state.enabled)


def statement_type_live(statement_type: str) -> bool:
    """Cache-gate helper. An unmapped statement type is only subject to the
    master switch (the registry test keeps that set empty in practice)."""
    group = group_for_statement_type(statement_type)
    if group is None:
        return master_on()
    return group_live(group)


def describe_off(group: str) -> str:
    _, reason = effective_state(group)
    return {
        "live": "live",
        "master_off": "master switch off",
        "user_off": "disabled",
        "above_plan": "required tier above current plan",
        "restricted": "restricted by FMP (plan)",
    }[reason]


def job_skip_reason(*groups: str) -> str | None:
    """None if every group is live; otherwise the "skipped (...)" message a
    nightly job should log and report."""
    parts = []
    for g in groups:
        live, reason = effective_state(g)
        if reason == "master_off":
            return "skipped (FMP master switch off)"
        if not live:
            parts.append(f"group {g} {describe_off(g)}")
    if not parts:
        return None
    return "skipped (" + "; ".join(parts) + ")"


# ---------------------------------------------------------------------------
# Writes (each invalidates the cache)
# ---------------------------------------------------------------------------


def _write(fn) -> None:
    SQLModel.metadata.create_all(engine, tables=[DataGroupSetting.__table__, DataGroupGlobal.__table__])
    with Session(engine) as session:
        _seed(session)
        fn(session)
        session.commit()
    invalidate_cache()


def _row(session: Session, group: str) -> DataGroupSetting:
    if group not in GROUPS:
        raise ValueError(f"unknown data group: {group}")
    return session.get(DataGroupSetting, group)


def set_group_enabled(group: str, enabled: bool) -> None:
    def fn(s: Session) -> None:
        r = _row(s, group)
        r.enabled, r.updated_at = enabled, datetime.now()
        s.add(r)

    _write(fn)


def set_required_tier(group: str, tier: str, verified: bool | None = None) -> None:
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")

    def fn(s: Session) -> None:
        r = _row(s, group)
        if tier != r.required_tier:
            r.tier_verified = False  # a changed value is unverified until re-ticked
        r.required_tier = tier
        if verified is not None:
            r.tier_verified = verified
        r.updated_at = datetime.now()
        s.add(r)

    _write(fn)


def set_tier_verified(group: str, verified: bool) -> None:
    def fn(s: Session) -> None:
        r = _row(s, group)
        r.tier_verified, r.updated_at = verified, datetime.now()
        s.add(r)

    _write(fn)


def set_fmp_plan(plan: str) -> None:
    if plan not in TIERS:
        raise ValueError(f"unknown plan: {plan}")

    def fn(s: Session) -> None:
        g = s.get(DataGroupGlobal, "default")
        g.fmp_plan, g.updated_at = plan, datetime.now()
        s.add(g)

    _write(fn)


def set_master(on: bool) -> None:
    def fn(s: Session) -> None:
        g = s.get(DataGroupGlobal, "default")
        g.master_on, g.updated_at = on, datetime.now()
        s.add(g)

    _write(fn)


def mark_restricted(group: str, detail: str) -> None:
    def fn(s: Session) -> None:
        r = _row(s, group)
        r.status, r.restricted_since, r.last_error, r.updated_at = (
            "plan_restricted", r.restricted_since or datetime.now(), detail[:300], datetime.now(),
        )
        s.add(r)

    _write(fn)


def clear_restricted(group: str) -> None:
    def fn(s: Session) -> None:
        r = _row(s, group)
        if r.status == "plan_restricted":
            r.status, r.restricted_since, r.consecutive_failures, r.updated_at = "ok", None, 0, datetime.now()
            s.add(r)

    _write(fn)


def set_key_problem(detail: str | None) -> None:
    """detail=None clears the marker."""

    def fn(s: Session) -> None:
        g = s.get(DataGroupGlobal, "default")
        g.key_problem_at = datetime.now() if detail else None
        g.key_problem_detail = detail[:300] if detail else None
        s.add(g)

    _write(fn)


def record_group_success(group: str | None) -> None:
    """Best-effort, throttled; never raises (must not break the fetch it
    piggybacks on)."""
    if group is None or group not in GROUPS:
        return
    now = time.monotonic()
    snap_state = get_snapshot().groups.get(group)
    needs_reset = bool(snap_state and (snap_state.consecutive_failures or snap_state.status == "failing"))
    if not needs_reset and now - _last_success_write.get(group, -1e9) < SUCCESS_WRITE_INTERVAL_SECONDS:
        return
    _last_success_write[group] = now
    try:
        def fn(s: Session) -> None:
            r = _row(s, group)
            r.last_success_at, r.consecutive_failures = datetime.now(), 0
            if r.status == "failing":
                r.status = "ok"
            r.last_error = None if r.status != "plan_restricted" else r.last_error
            s.add(r)

        _write(fn)
    except Exception:
        logger.warning("data_groups: could not record success for %s", group, exc_info=True)


def record_group_failure(group: str | None, error: str) -> None:
    """A non-402, non-429 live failure (network/5xx). Flips the chip to
    "failing" after FAILING_AFTER_CONSECUTIVE in a row; never disables."""
    if group is None or group not in GROUPS:
        return
    try:
        def fn(s: Session) -> None:
            r = _row(s, group)
            r.consecutive_failures += 1
            r.last_error = error[:300]
            if r.status == "ok" and r.consecutive_failures >= FAILING_AFTER_CONSECUTIVE:
                r.status = "failing"
            r.updated_at = datetime.now()
            s.add(r)

        _write(fn)
    except Exception:
        logger.warning("data_groups: could not record failure for %s", group, exc_info=True)


def backfill_last_success_from_cache() -> dict[str, datetime | None]:
    """Idempotent one-time-style step: seed each group's last_success_at from
    the newest `fetched_at` among that group's FundamentalsCache rows (its
    statement types per STATEMENT_TYPE_GROUP). Never moves a value backwards
    (max of existing and cache), leaves a group with no cache rows untouched
    (still empty), and is safe to re-run. Returns {group: value written or
    None if nothing to write}. CLI: `pipeline.data_groups backfill-last-success`."""
    types_by_group: dict[str, list[str]] = {}
    for statement_type, group in STATEMENT_TYPE_GROUP.items():
        types_by_group.setdefault(group, []).append(statement_type)

    SQLModel.metadata.create_all(engine, tables=[DataGroupSetting.__table__, DataGroupGlobal.__table__])
    result: dict[str, datetime | None] = {}
    with Session(engine) as session:
        _seed(session)
        for group in GROUPS:
            types = types_by_group.get(group)
            newest = (
                session.exec(
                    select(func.max(FundamentalsCache.fetched_at)).where(FundamentalsCache.statement_type.in_(types))
                ).one()
                if types
                else None
            )
            row = session.get(DataGroupSetting, group)
            if newest is None or (row.last_success_at is not None and row.last_success_at >= newest):
                result[group] = None
                continue
            row.last_success_at = newest
            session.add(row)
            result[group] = newest
        session.commit()
    invalidate_cache()
    return result
