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

**Also hosts the delisted-ticker flag, a second, independent check over the same
universe -- not a "profile" freshness thing at all.** sync_delisted_flags pages FMP's
`/delisted-companies` list (Phase 6a, 2026-09-26; replaced the earlier dual-provider
"last bar > 30 days old on both Massive and Yahoo" heuristic, which is gone) and sets
TickerScore.delisted_at for any tracked ticker that appears in it with a delisted date
on/before today -- genuinely delisted tickers (confirmed cases: TWTR, WBA, EA, AVB, EQR)
that the nightly Trend/Liquidity Zone/Momentum jobs would otherwise keep retrying
forever. **Absence is NOT evidence: a ticker the endpoint does not list is left exactly
as it is (no flag, and an existing flag is never cleared here).** The one guard on a hit:
a symbol whose cached profile `ipoDate` is AFTER the listed delisted date is a reused
symbol (a different, newer company) and is not flagged. Chosen as the host (over
audit_fixture_contamination.py, which is about test-fixture leakage, and
purge_invalid_tickers.py, which deletes rows -- the opposite of "never delete history")
because it already computes load_full_tracked_universe weekly. This is the one live-FMP
call this otherwise cache-only script makes (~160 sequential pages of 100 rows; the
endpoint's page size is capped at 100), under the `corporate_events` data group.

Run:
    uv run python -m pipeline.stale_data_health_check

Override the staleness threshold for one run:
    uv run python -m pipeline.stale_data_health_check --days 14
"""

import argparse
import asyncio
import json
import logging
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.cron_health import cron_heartbeat
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import FundamentalsCache, TickerScore
from core.data_groups import group_live
from core.tickers import normalize_ticker
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "stale_data_health_check.log"

# cache_staleness_days (7) is when a row becomes ELIGIBLE for refetch, not a
# guarantee it actually was -- this adds a buffer for one missed nightly run
# before flagging a ticker, so ordinary jitter doesn't read as a real outage.
DEFAULT_STALE_THRESHOLD_DAYS = 10

# FMP caps /delisted-companies at 100 rows per page (larger `limit`s are silently
# clamped); ~157 pages held the whole ~15.6k-row list on 2026-09-26. The cap only
# stops a runaway loop.
DELISTED_PAGE_SIZE = 100
DELISTED_MAX_PAGES = 400

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


async def _fetch_delisted_companies() -> tuple[list[dict], bool]:
    """Every page of FMP's /delisted-companies, (rows, complete). A page error
    stops paging and returns what was fetched so far with complete=False --
    harmless, since only hits ever flag anything and the weekly rerun retries."""
    rows: list[dict] = []
    for page in range(DELISTED_MAX_PAGES):
        try:
            batch = await fmp_client.get_delisted_companies(page, DELISTED_PAGE_SIZE)
        except httpx.HTTPError as exc:
            logger.warning("Delisted-companies fetch stopped at page %d (%s)", page, type(exc).__name__)
            return rows, False
        if not isinstance(batch, list) or not batch:
            return rows, True
        rows.extend(r for r in batch if isinstance(r, dict))
    return rows, False


def _profile_ipo_dates(tickers: list[str]) -> dict[str, date]:
    """{ticker: profile ipoDate} from the cached FMP profile rows (local read)."""
    out: dict[str, date] = {}
    with Session(engine) as session:
        stmt = select(FundamentalsCache.ticker, FundamentalsCache.raw_json).where(
            FundamentalsCache.statement_type == "profile", FundamentalsCache.period == "latest"
        )
        wanted = set(tickers)
        for ticker, raw in session.exec(stmt).all():
            if ticker not in wanted:
                continue
            try:
                payload = json.loads(raw)
                row = payload[0] if isinstance(payload, list) and payload else payload
                out[ticker] = date.fromisoformat(str(row["ipoDate"])[:10])
            except (TypeError, ValueError, KeyError, IndexError):
                continue
    return out


def find_delisted_hits(tickers: list[str], listed: list[dict], today: date | None = None) -> dict[str, date]:
    """{tracked ticker: delisted date} for every tracked ticker FMP lists as delisted
    on/before `today` (a future date is a scheduled delisting, not a delisting). A symbol
    whose cached profile ipoDate is after the delisted date is a reused symbol and is
    skipped. Several rows for one symbol: the latest qualifying date wins."""
    today = today or date.today()
    tracked = set(tickers)
    ipo_dates = _profile_ipo_dates(tickers)
    hits: dict[str, date] = {}
    for row in listed:
        ticker = normalize_ticker(str(row.get("symbol") or ""))
        if ticker not in tracked:
            continue
        try:
            delisted_on = date.fromisoformat(str(row.get("delistedDate"))[:10])
        except ValueError:
            continue
        if delisted_on > today:
            continue
        ipo = ipo_dates.get(ticker)
        if ipo is not None and ipo > delisted_on:
            continue
        if ticker not in hits or delisted_on > hits[ticker]:
            hits[ticker] = delisted_on
    return hits


def sync_delisted_flags(tickers: list[str]) -> dict:
    """Sets TickerScore.delisted_at for tracked tickers FMP lists as delisted. Returns
    {"newly_flagged": [...sorted], "skipped": bool, "complete": bool}. Never clears a
    flag and never acts on a ticker the endpoint does not list (see the module
    docstring). Skipped (nothing fetched) while the `corporate_events` group is not live."""
    if not tickers:
        return {"newly_flagged": [], "skipped": False, "complete": True}
    if not group_live("corporate_events"):
        logger.info("Delisted-flag sync skipped (group corporate_events is not live)")
        return {"newly_flagged": [], "skipped": True, "complete": False}
    listed, complete = asyncio.run(_fetch_delisted_companies())
    hits = find_delisted_hits(tickers, listed)
    newly_flagged: list[str] = []
    now = datetime.now()
    with Session(engine) as session:
        for row in session.exec(select(TickerScore).where(TickerScore.ticker.in_(list(hits)))).all():
            if row.delisted_at is None:
                row.delisted_at = now
                newly_flagged.append(row.ticker)
        if newly_flagged:
            session.commit()
    return {"newly_flagged": sorted(newly_flagged), "skipped": False, "complete": complete}


def load_delisted_tickers(session: Session) -> set[str]:
    """Tickers currently flagged via TickerScore.delisted_at (see
    sync_delisted_flags) -- imported by the nightly daily-bar jobs (Trend/
    Weinstein, Liquidity Zones, Momentum) to skip a flagged ticker's own
    fetch/compute entirely, rather than retrying a doomed provider
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
    if delisted.get("skipped"):
        lines.append("  Delisted-flag sync: skipped (corporate_events group not live)")
    elif delisted.get("newly_flagged"):
        lines.append(f"  Newly flagged delisted: {', '.join(delisted['newly_flagged'])}")
    return "\n".join(lines)


def _reprobe_restricted_groups() -> dict[str, str]:
    """Weekly re-probe of any FMP data group marked plan_restricted (canary
    AAPL call) so a plan upgrade self-heals without a manual step. Never
    fails the job: a probe error just leaves the group as it was."""
    try:
        return asyncio.run(fmp_client.reprobe_restricted_groups())
    except Exception:
        logger.warning("Restricted-group re-probe failed", exc_info=True)
        return {}


def main(threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS) -> dict:
    configure_logging(LOG_PATH)
    init_db()
    with Session(engine) as session:
        tickers = load_full_tracked_universe(session)
    result = check_staleness(tickers, threshold_days)
    result["delisted"] = sync_delisted_flags(tickers)
    result["reprobe"] = _reprobe_restricted_groups()
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
        delisted = result.get("delisted") or {"newly_flagged": []}
        message = f"{len(result['stale'])} stale, {len(result['never_fetched'])} never-fetched"
        if delisted["newly_flagged"]:
            message += f"; newly delisted: {', '.join(delisted['newly_flagged'])}"
        if delisted.get("skipped"):
            message += "; delisted sync skipped (corporate_events off)"
        elif not delisted.get("complete", True):
            message += "; delisted list incomplete"
        reprobe = result.get("reprobe") or {}
        if reprobe:
            message += "; FMP re-probe: " + ", ".join(f"{g}={v}" for g, v in reprobe.items())
        run.message = message
