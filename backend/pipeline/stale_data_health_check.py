"""Standalone script: reports how many tickers in the full tracked universe
(index constituents UNION cached UNION scored UNION watchlisted -- see
nightly_fundamentals_fetch.py::load_full_tracked_universe, reused here)
haven't had their FundamentalsCache "profile" row refreshed within the
staleness threshold -- a readable freshness report, not a silent check.
"profile" is fetched on every nightly refresh cycle (see
nightly_fundamentals_fetch.py::_refresh_one_ticker), so its fetched_at is a
reliable proxy for "did this ticker's nightly refresh actually happen
recently." Cache-only, zero FMP calls, safe to run anytime.

Widened from S&P 500 + Dow only to the full tracked universe (2026-09-11,
cron audit finding #6/B): nightly_fundamentals_fetch.py has refreshed the
full tracked universe (not just the index) since 2026-08-06, but this
report was never widened to match, so a watchlisted-only or ad-hoc-viewed
ticker whose nightly refresh silently broke would never have surfaced here
-- the same index-only-vs-full-universe blind-spot shape already fixed once
in nightly_score_recompute.py/recompute_ticker_scores.py (see CLAUDE.md's
Speculative Growth section). The report is expected to get noisier (~572
vs ~530 tickers) as a direct, intended consequence.

**Also hosts the delisted-ticker flag (2026-09-23), a second, independent
check over the same universe -- not a "profile" freshness thing at all.**
sync_delisted_flags reads clients/shared_bars_cache.py's SharedBarsCache
("1d" interval) instead of FundamentalsCache, and unlike the report above
it DOES write: it sets/clears TickerScore.delisted_at for any ticker whose
daily bars have gone stale on both Massive and Yahoo for
DELISTED_STALE_THRESHOLD_DAYS (30) straight days -- genuinely delisted
tickers (confirmed cases: TWTR, WBA, EA, AVB, EQR) that the nightly Trend/
Liquidity Zone/Momentum jobs would otherwise keep retrying forever. Chosen
as the host for this check (over audit_fixture_contamination.py, which is
about test-fixture leakage and unrelated, and purge_invalid_tickers.py,
which deletes rows -- the opposite of this feature's "never delete
history" requirement) specifically because it already computes
load_full_tracked_universe on a weekly cadence and was already the
"read-only-report-with-an-optional-write" shape closest to what this
needed -- see CLAUDE.md's "Delisted-ticker handling" section for the full
design.

**Live-probe revival check (2026-09-24), the one deliberate exception to
this script's otherwise cache-only convention.** The nightly Trend/
Liquidity Zone/Momentum jobs all SKIP a flagged ticker's own fetch
entirely (load_delisted_tickers), which was a real bug found before
shipping this: it means a flagged ticker's SharedBarsCache row can NEVER
refresh on its own again through the normal nightly path, so
sync_delisted_flags' own cache-based auto-clear (still checked first,
since it's free) was permanently starved for any ticker actually flagged
by this job -- a reused or relisted symbol would stay flagged forever.
Fixed by probing whatever's STILL flagged after the cheap cache check
directly and live: one short (~10-day) Massive range call per ticker,
Yahoo as a second opinion only when Massive returns nothing (mirrors the
manual dual-source verification the original 5 tickers were confirmed
with) -- see _probe_ticker_for_fresh_bar. Any ticker either source shows
a bar within DELISTED_STALE_THRESHOLD_DAYS for gets a full re-backfill,
through the NORMAL DailyBarSource path (get_or_fetch_bars_batch,
force=True) -- not just the probe's own narrow window, which would leave
a gap between the old cached history and today -- so SharedBarsCache
holds a clean, contiguous series again before the flag is cleared and the
nightly jobs pick the ticker back up.

Run:
    uv run python -m pipeline.stale_data_health_check

Override the staleness threshold for one run:
    uv run python -m pipeline.stale_data_health_check --days 14
"""

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlmodel import Session, select

from clients.massive_client import massive_client
from clients.shared_bars_cache import DAILY_INTERVAL, get_or_fetch_bars_batch, last_bar_ages_days
from clients.yahoo_client import yahoo_client
from core.config import settings
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import FundamentalsCache, TickerScore
from core.tickers import is_non_us_ticker, to_massive_symbol
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "stale_data_health_check.log"

# cache_staleness_days (7) is when a row becomes ELIGIBLE for refetch, not a
# guarantee it actually was -- this adds a buffer for one missed nightly run
# before flagging a ticker, so ordinary jitter doesn't read as a real outage.
DEFAULT_STALE_THRESHOLD_DAYS = 10

# How stale a ticker's SharedBarsCache "1d" last bar must be, on BOTH
# Massive and Yahoo, before it's flagged as delisted (TickerScore.
# delisted_at) -- see sync_delisted_flags' own docstring for why this is a
# genuinely dual-provider signal despite being read from one cache table.
# 30 days comfortably clears the nightly Trend/Liquidity Zone/Momentum
# jobs' own routine retry cadence (every ticker in scope gets a fresh
# Massive+Yahoo attempt every single night regardless of staleness -- see
# clients/shared_bars_cache.py::get_or_fetch_bars_batch), so only a ticker
# that has failed BOTH providers on essentially every one of ~30
# consecutive nightly attempts qualifies -- a real, durable gap, not a
# transient outage or a single missed run.
DELISTED_STALE_THRESHOLD_DAYS = 30

# Live-probe revival check (see sync_delisted_flags): a short window is
# plenty to answer "has this ticker traded again recently at all" cheaply,
# one per-ticker Massive range call at a time -- not the full multi-year
# history a genuine backfill needs (that only happens, via the normal
# DailyBarSource path, for whichever tickers this probe actually revives).
PROBE_WINDOW_DAYS = 10

# Once a probe confirms a ticker is genuinely back, its full history is
# re-fetched through the normal get_or_fetch_bars_batch(force=True) path at
# this width -- wide enough to reconstruct a real, contiguous multi-year
# series (matching the LOOKBACK_DAYS territory the nightly Trend/Liquidity
# Zone jobs themselves request), not just the probe's own narrow window,
# which would leave a gap between the old cached history and today.
REVIVAL_BACKFILL_LOOKBACK_DAYS = 730

logger = logging.getLogger(__name__)


def check_staleness(tickers: list[str], threshold_days: int) -> dict:
    """Returns {"fresh": [...], "stale": [(ticker, days), ...], "never_fetched": [...]}."""
    fresh: list[str] = []
    stale: list[tuple[str, int]] = []
    never_fetched: list[str] = []
    now = datetime.now()
    with Session(engine) as session:
        for ticker in tickers:
            row = session.exec(
                select(FundamentalsCache).where(
                    FundamentalsCache.ticker == ticker, FundamentalsCache.statement_type == "profile"
                )
            ).first()
            if row is None:
                never_fetched.append(ticker)
                continue
            days = (now - row.fetched_at).days
            if days > threshold_days:
                stale.append((ticker, days))
            else:
                fresh.append(ticker)
    return {"fresh": fresh, "stale": stale, "never_fetched": never_fetched}


def _delisted_candidates_from_ages(ages: dict[str, int | None], threshold_days: int) -> dict[str, int]:
    return {t: age for t, age in ages.items() if age is not None and age > threshold_days}


def find_delisted_candidates(tickers: list[str], threshold_days: int = DELISTED_STALE_THRESHOLD_DAYS) -> dict[str, int]:
    """{ticker: age_days} for every ticker whose SharedBarsCache
    interval="1d" last bar is more than `threshold_days` old. Restricted to
    US-eligible tickers (core.tickers.is_non_us_ticker) -- a non-US ticker
    is routed to Yahoo alone by design (clients/daily_bar_sources.py::
    route_by_source), so its own staleness is never dual-provider evidence
    and must never flag it. A ticker with no cached bars at all (never
    fetched) is excluded -- ambiguous, not evidence of delisting."""
    us_tickers = [t for t in tickers if not is_non_us_ticker(t)]
    ages = last_bar_ages_days(us_tickers, DAILY_INTERVAL)
    return _delisted_candidates_from_ages(ages, threshold_days)


async def _probe_ticker_for_fresh_bar(ticker: str, today: date, threshold_days: int) -> bool:
    """True if a direct live check finds a bar within `threshold_days` of
    `today` for `ticker` -- Massive first (skipped entirely when
    settings.massive_enabled is False, respecting the same kill switch
    get_daily_bar_source() honors elsewhere), Yahoo as a second opinion
    only when Massive was skipped or came back empty. The one deliberate
    live-call exception to this script's otherwise cache-only convention
    -- see sync_delisted_flags' own docstring for why it's needed."""
    start = today - timedelta(days=PROBE_WINDOW_DAYS)
    df: pd.DataFrame | None = None
    if settings.massive_enabled:
        try:
            df = await massive_client.get_daily_bars(to_massive_symbol(ticker), start, today, adjusted=True)
        except Exception:
            logger.warning("Delisted-flag revival probe: Massive lookup failed for %s", ticker)
            df = None
    if df is None or df.empty:
        try:
            batch = await yahoo_client.get_history([ticker], period="1mo", interval="1d", auto_adjust=False)
        except Exception:
            logger.warning("Delisted-flag revival probe: Yahoo lookup failed for %s", ticker)
            batch = {}
        df = batch.get(ticker)
    if df is None or df.empty:
        return False
    last_bar_date = pd.DatetimeIndex(df.index).max().date()
    return (today - last_bar_date).days <= threshold_days


async def _probe_and_revive(flagged_tickers: list[str], threshold_days: int) -> list[str]:
    """Probes every (US-eligible) currently-flagged ticker live and
    re-backfills whichever come back positive through the normal
    DailyBarSource path -- see this module's own docstring and
    sync_delisted_flags' for the full reasoning. Returns the revived
    tickers (unsorted)."""
    us_tickers = [t for t in flagged_tickers if not is_non_us_ticker(t)]
    if not us_tickers:
        return []
    today = date.today()
    results = await asyncio.gather(*(_probe_ticker_for_fresh_bar(t, today, threshold_days) for t in us_tickers))
    revived = [t for t, is_fresh in zip(us_tickers, results) if is_fresh]
    if revived:
        await get_or_fetch_bars_batch(revived, DAILY_INTERVAL, REVIVAL_BACKFILL_LOOKBACK_DAYS, auto_adjust=False, force=True)
    return revived


def sync_delisted_flags(tickers: list[str], threshold_days: int = DELISTED_STALE_THRESHOLD_DAYS) -> dict:
    """Sets/clears TickerScore.delisted_at from a fresh daily-bar staleness
    read. Returns {"newly_flagged": [...], "newly_cleared": [...]}
    (both sorted).

    Flagging requires settings.massive_enabled: with Massive off,
    clients/daily_bar_sources.py::get_daily_bar_source() returns a plain
    YahooDailySource, so every SharedBarsCache "1d" bar in the tracked
    universe would only ever reflect Yahoo's own attempts -- single-
    provider evidence, which must never flag a ticker (an existing flag is
    left untouched in that case too, not force-cleared, since this run
    genuinely didn't re-check both providers). With Massive on (the normal
    case, confirmed via clients/daily_bar_sources.py's own Phase-1 module
    docstring), every ticker in `tickers` gets a fresh Massive-then-
    Yahoo-fallback attempt from the nightly Trend/Liquidity Zone/Momentum
    jobs regardless of its current staleness (get_or_fetch_bars_batch
    always retries a stale row), so a last bar still >threshold_days old
    genuinely means neither provider has produced a newer bar across many
    consecutive dual-provider attempts -- the same real-world signal as the
    manual /v3/reference/tickers 404 + Yahoo "possibly delisted" check this
    mirrors.

    Auto-clearing is safe regardless of settings.massive_enabled -- a
    fresh bar from even a single provider (Yahoo-only mode included)
    already disproves "still delisted" outright, e.g. a symbol reuse or
    relisting under the same ticker (cf. the earlier PARA symbol-
    reassignment case).

    This cache-based clear is checked first because it's free, but it can
    only ever fire for a ticker some OTHER path happened to refresh (e.g.
    an on-demand ticker-page Technical-tab view) -- the nightly Trend/
    Liquidity Zone/Momentum jobs all SKIP a flagged ticker's own fetch
    entirely (see load_delisted_tickers), so relying on this alone would
    leave a reused/relisted symbol flagged forever. Whatever's still
    flagged after the cache check gets a direct live probe instead (see
    _probe_and_revive) -- the one live-call exception to this script's
    otherwise cache-only convention, and the reason this function makes
    network calls at all despite reading like a pure DB sync."""
    if not tickers:
        return {"newly_flagged": [], "newly_cleared": []}

    us_tickers = [t for t in tickers if not is_non_us_ticker(t)]
    ages = last_bar_ages_days(us_tickers, DAILY_INTERVAL)
    candidates = _delisted_candidates_from_ages(ages, threshold_days) if settings.massive_enabled else {}

    newly_flagged: list[str] = []
    newly_cleared: list[str] = []
    still_flagged: list[str] = []
    now = datetime.now()
    with Session(engine) as session:
        rows = session.exec(select(TickerScore).where(TickerScore.ticker.in_(tickers))).all()
        for row in rows:
            age = ages.get(row.ticker)
            if row.ticker in candidates and row.delisted_at is None:
                row.delisted_at = now
                newly_flagged.append(row.ticker)
            elif row.delisted_at is not None:
                if age is not None and age <= threshold_days:
                    row.delisted_at = None
                    newly_cleared.append(row.ticker)
                else:
                    still_flagged.append(row.ticker)
        if newly_flagged or newly_cleared:
            session.commit()

    revived = asyncio.run(_probe_and_revive(still_flagged, threshold_days)) if still_flagged else []
    if revived:
        with Session(engine) as session:
            rows = session.exec(select(TickerScore).where(TickerScore.ticker.in_(revived))).all()
            for row in rows:
                if row.delisted_at is not None:
                    row.delisted_at = None
                    newly_cleared.append(row.ticker)
            session.commit()

    return {"newly_flagged": sorted(newly_flagged), "newly_cleared": sorted(newly_cleared)}


def load_delisted_tickers(session: Session) -> set[str]:
    """Tickers currently flagged via TickerScore.delisted_at (see
    sync_delisted_flags) -- imported by the nightly daily-bar jobs (Trend/
    Weinstein, Liquidity Zones, Momentum) to skip a flagged ticker's own
    fetch/compute entirely, rather than retrying a doomed Massive+Yahoo
    lookup for it every night. Mirrors nightly_fundamentals_fetch.py::
    load_full_tracked_universe's own "defined once, imported everywhere"
    convention."""
    return set(session.exec(select(TickerScore.ticker).where(TickerScore.delisted_at.is_not(None))).all())


def _format_report(result: dict, total: int, threshold_days: int) -> str:
    lines = [
        f"Stale-data health check ({total} tickers, staleness threshold {threshold_days} days):",
        f"  Fresh:         {len(result['fresh'])}",
        f"  Stale:         {len(result['stale'])}",
        f"  Never fetched: {len(result['never_fetched'])}",
    ]
    if result["stale"]:
        lines.append("  Stale tickers (ticker: days since last fetch):")
        for ticker, days in sorted(result["stale"], key=lambda pair: -pair[1]):
            lines.append(f"    {ticker}: {days}d")
    if result["never_fetched"]:
        lines.append("  Never-fetched tickers: " + ", ".join(sorted(result["never_fetched"])))
    delisted = result.get("delisted") or {}
    if delisted.get("newly_flagged") or delisted.get("newly_cleared"):
        lines.append(f"  Newly flagged delisted: {', '.join(delisted.get('newly_flagged', [])) or 'none'}")
        lines.append(f"  Newly cleared delisted: {', '.join(delisted.get('newly_cleared', [])) or 'none'}")
    return "\n".join(lines)


def main(threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS) -> dict:
    configure_logging(LOG_PATH)
    init_db()
    with Session(engine) as session:
        tickers = load_full_tracked_universe(session)
    result = check_staleness(tickers, threshold_days)
    result["delisted"] = sync_delisted_flags(tickers)
    report = _format_report(result, len(tickers), threshold_days)
    logger.info("\n%s", report)
    print(report)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report tickers whose cached fundamentals haven't refreshed recently.")
    parser.add_argument("--days", type=int, default=DEFAULT_STALE_THRESHOLD_DAYS, help="Staleness threshold in days.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = _parse_args()
    with cron_heartbeat("pipeline.stale_data_health_check") as run:
        result = main(cli_args.days)
        delisted = result.get("delisted") or {"newly_flagged": [], "newly_cleared": []}
        message = f"{len(result['stale'])} stale, {len(result['never_fetched'])} never-fetched"
        if delisted["newly_flagged"]:
            message += f"; newly delisted: {', '.join(delisted['newly_flagged'])}"
        if delisted["newly_cleared"]:
            message += f"; delisted cleared: {', '.join(delisted['newly_cleared'])}"
        run.message = message
