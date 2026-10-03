"""The opt-in universe API's data layer (step 3a): the status of a ticker, Add, Remove, and the best-effort immediate
ETF row for a watchlist add. Spec: docs/specs/tracked-universe.md ("The opt-in universe" and "API").

`state` is protected (any index, any watchlist, a seed / the benchmark / the live rs_benchmark, owner-entered data), added
(`TickerView.added_at` set) or browsed (neither). `in_universe` and `classification` come from
`data/tracked_universe.py::classify_one`, the single-ticker twin of the classification the universes use (since the flip,
2026-10-03), so the status cannot disagree with `load_tracked_universe` / `load_etf_universe`.

`get_universe_status` is cache-only: zero FMP calls, no write, no touch of `TickerView`.

`engine` is a module-level reference so tests can monkeypatch it (the per-module convention)."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.cache import get_or_fetch
from core.config import settings
from core.data_groups import group_live, job_skip_reason
from core.db import engine
from core.exceptions import TickerNotFoundError
from core.logging_config import redact_apikey
from core.models import EtfScreenerRow, FundamentalsCache, TickerScore, TickerView
from core.schemas import UniverseAddOut, UniverseRemoveOut, UniverseStatusOut
from core.tickers import is_us_listed, normalize_ticker
from data.etf_data import known_etf_tickers
from data.etf_screener_refresh import refresh_etf_screener
from data.ticker_score import compute_ticker_score
from data.tracked_universe import OUT_OF_UNIVERSE, classify_one, load_protection_reasons
from helpers.first import _first

logger = logging.getLogger(__name__)

# A bulk watchlist add may bring many ETFs without a row; only this many get the immediate write (the rest wait for
# the nightly job), so a paste can never turn into a long request.
MAX_IMMEDIATE_ETF_ROWS = 5


class UniverseRejectedError(Exception):
    """A request the universe API refuses; `status_code` is the HTTP status the route answers with."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _utc_now() -> datetime:
    """Naive UTC, the convention of the step-2 grandfather script (`added_at`)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cached_profile(session: Session, ticker: str) -> dict | None:
    """The cached profile as a dict, or None (nothing cached, or a cached empty answer). Never fetches."""
    row = session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker, FundamentalsCache.statement_type == "profile", FundamentalsCache.period == "latest"
        )
    ).first()
    if row is None:
        return None
    try:
        profile = _first(json.loads(row.raw_json))
    except (TypeError, ValueError):
        return None
    return profile or None


def get_universe_status(session: Session, ticker: str) -> UniverseStatusOut:
    """The design state of one ticker. Reads only (cache-only: no FMP, no write, no TickerView touch)."""
    ticker = normalize_ticker(ticker)
    profile = _cached_profile(session, ticker)
    score = session.get(TickerScore, ticker)
    if ticker in known_etf_tickers(session, [ticker]):
        kind = "etf"
    elif profile is not None or score is not None:
        kind = "stock"
    else:
        kind = None
    view = session.get(TickerView, ticker)
    added_at = view.added_at if view is not None else None
    reasons = load_protection_reasons(session, ticker)
    delisted = bool(score is not None and score.delisted_at is not None)

    if reasons:
        state = "protected"
    elif added_at is not None:
        state = "added"
    else:
        state = "browsed"
    exchange = profile.get("exchange") if profile else None
    classification = classify_one(session, ticker)  # the SAME rule the universes use: in_universe cannot disagree with them
    return UniverseStatusOut(
        ticker=ticker,
        kind=kind,
        in_universe=classification is not None and classification not in OUT_OF_UNIVERSE,
        classification=classification,
        state=state,
        reasons=reasons,
        can_add=state == "browsed" and not delisted and is_us_listed(ticker, exchange),
        can_remove=state == "added",
        added_at=added_at,
        added_source=view.added_source if view is not None and added_at is not None else None,
        delisted=delisted,
    )


async def _profile_for_add(session: Session, ticker: str) -> dict:
    """The profile the Add decision rests on, cached-first: a ticker the user just opened is cached already (zero
    calls); a never-seen ticker costs one live profile call. An empty answer raises TickerNotFoundError and writes
    nothing (the empty answer is not cached here); a transient FMP failure propagates as httpx.HTTPError."""
    cached = await get_or_fetch(
        session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), settings.profile_staleness_days, cache_only=True
    )
    if cached is not None:
        profile = _first(cached)
        if not profile:
            raise TickerNotFoundError(ticker)
        return profile
    if not group_live("profile_quote"):
        raise UniverseRejectedError(503, "Cannot check this ticker: the profile data group is not live and nothing is cached for it.")
    fetched = await fmp_client.get_profile(ticker)
    if isinstance(fetched, list) and not fetched:
        raise TickerNotFoundError(ticker)

    async def _already_fetched():
        return fetched

    await get_or_fetch(session, ticker, "profile", "latest", _already_fetched, settings.profile_staleness_days)  # caches it
    return _first(fetched)


async def add_to_universe(ticker: str) -> UniverseAddOut:
    """Idempotent Add. Order: profile check (404 empty, no write) -> non-US rejected (400) -> delisted rejected (409) ->
    protected or already added: no-op, the status is returned -> otherwise set `added_at` / `added_source='user'` and COMMIT
    -> only then the immediate compute (stock: a live `compute_ticker_score`, as POST /refresh does; ETF: the
    EtfScreenerRow through `refresh_etf_screener`). A failed compute never undoes the add: the nightly jobs pick the
    ticker up."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        profile = await _profile_for_add(session, ticker)
        is_etf = bool(profile.get("isEtf") or profile.get("isFund"))  # the app's one rule (data/ticker_summary.py)
        if not is_us_listed(ticker, profile.get("exchange")):
            raise UniverseRejectedError(400, f"{ticker} is not a US-listed ticker; Fathom supports US-listed tickers only.")
        status = get_universe_status(session, ticker)
        if status.delisted:
            raise UniverseRejectedError(409, f"{ticker} is flagged delisted and cannot be added.")
        if status.state == "protected":
            return UniverseAddOut(
                status=status, changed=False, message=f"{ticker} is already in the universe ({', '.join(status.reasons)}); nothing to add."
            )
        if status.state == "added":
            return UniverseAddOut(status=status, changed=False, message=f"{ticker} is already added.")
        # An existing TickerView row keeps its last_viewed_at; a missing one is created now.
        session.execute(sqlite_insert(TickerView).values(ticker=ticker, last_viewed_at=datetime.now()).on_conflict_do_nothing())
        session.execute(
            update(TickerView)
            .where(TickerView.ticker == ticker, TickerView.added_at.is_(None))
            .values(added_at=_utc_now(), added_source="user")
        )
        session.commit()  # durable before any compute
        status = get_universe_status(session, ticker)

    if is_etf:
        return await _add_etf(ticker, status)
    return await _add_stock(ticker, status)


async def _add_stock(ticker: str, status: UniverseStatusOut) -> UniverseAddOut:
    if not group_live("fundamentals"):
        # Live compute skipped; a cache-only compute (zero FMP calls) keeps the score row as fresh as the cache allows.
        try:
            await compute_ticker_score(ticker, cache_only=True)
        except Exception:  # noqa: BLE001 -- best effort
            logger.warning("Cache-only score compute failed for %s", ticker, exc_info=True)
        return UniverseAddOut(
            status=status, changed=True, score_computed=False, reason="fundamentals_group_off",
            message=f"Added {ticker}. The fundamentals data group is off, so the score was not refreshed live; the nightly recompute fills it.",
        )
    try:
        row = await compute_ticker_score(ticker, cache_only=False)
    except Exception as exc:  # noqa: BLE001 -- the add stands; the nightly recompute fills the score
        logger.warning("Score compute failed for %s after Add", ticker, exc_info=True)
        return UniverseAddOut(
            status=status, changed=True, score_computed=False, reason="failed", error=redact_apikey(f"{type(exc).__name__}: {exc}"),
            message=f"Added {ticker}, but computing its score failed; the nightly recompute fills it.",
        )
    if row is None:
        return UniverseAddOut(
            status=status, changed=True, score_computed=False, reason="no_data",
            message=f"Added {ticker}, but there was not enough data to compute a score yet; the nightly recompute fills it.",
        )
    return UniverseAddOut(status=status, changed=True, score_computed=True, message=f"Added {ticker} and computed its score.")


async def _add_etf(ticker: str, status: UniverseStatusOut) -> UniverseAddOut:
    skip = job_skip_reason("daily_prices")
    if skip:
        return UniverseAddOut(
            status=status, changed=True, row_written=False, reason="daily_prices_group_off",
            message=f"Added {ticker}. The daily price data is paused ({skip}); its card appears after the next nightly run.",
        )
    try:
        summary = await refresh_etf_screener([ticker])
    except Exception as exc:  # noqa: BLE001 -- the add stands
        logger.warning("ETF row refresh failed for %s after Add", ticker, exc_info=True)
        return UniverseAddOut(
            status=status, changed=True, row_written=False, reason="failed", error=redact_apikey(f"{type(exc).__name__}: {exc}"),
            message=f"Added {ticker}, but writing its card failed; it appears after tonight's run.",
        )
    result = summary["results"].get(ticker)
    written = bool(result is not None and result.written)
    errors = "; ".join(result.errors) if result is not None and result.errors else None
    if written:
        return UniverseAddOut(status=status, changed=True, row_written=True, error=errors, message=f"Added {ticker}; its card is on the ETFs page.")
    return UniverseAddOut(
        status=status, changed=True, row_written=False, reason="failed" if errors else "no_data", error=errors,
        message=f"Added {ticker}. Nothing could be computed for its card yet; it appears after tonight's run.",
    )


def remove_from_universe(ticker: str) -> UniverseRemoveOut:
    """Remove: refused (409, with the reasons) while any protection applies; a no-op when not added; otherwise clears
    `added_at` / `added_source` (never `last_viewed_at`). An ETF's EtfScreenerRow is deleted with it; a stock's
    TickerScore and everything else stay (the wipe handles them later). Since the classification flip the ticker is
    out of the universe at once (it reads browsed, or expired when idle), and the 1:45 job prunes an ETF's row anyway."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        status = get_universe_status(session, ticker)
        if status.reasons:
            raise UniverseRejectedError(
                409, f"{ticker} cannot be removed: it is in the universe through {', '.join(status.reasons)}."
            )
        if status.state != "added":
            return UniverseRemoveOut(status=status, changed=False, message=f"{ticker} was not added; nothing to remove.")
        session.execute(update(TickerView).where(TickerView.ticker == ticker).values(added_at=None, added_source=None))
        if status.kind == "etf":
            session.execute(delete(EtfScreenerRow).where(EtfScreenerRow.ticker == ticker))
        session.commit()
        status = get_universe_status(session, ticker)
    return UniverseRemoveOut(status=status, changed=True, message=f"Removed {ticker} from the universe.")


async def ensure_etf_screener_rows(tickers: list[str], max_rows: int = MAX_IMMEDIATE_ETF_ROWS) -> list[str]:
    """Best effort, never raises: for the ETFs among `tickers` (per the cached profile / score row, `known_etf_tickers`)
    that have no EtfScreenerRow yet, writes the row now through ONE `refresh_etf_screener` call (at most `max_rows`
    tickers; the rest wait for the nightly job). Skipped while the `daily_prices` group is off. Used after a watchlist
    add, which must never fail or wait for more than this one call. Returns the tickers whose row was written."""
    try:
        names = sorted({normalize_ticker(t) for t in tickers})
        if not names:
            return []
        with Session(engine) as session:
            etfs = known_etf_tickers(session, names)
            have = set(session.exec(select(EtfScreenerRow.ticker).where(EtfScreenerRow.ticker.in_(names))).all())
        missing = sorted(etfs - have)[:max_rows]
        if not missing or job_skip_reason("daily_prices"):
            return []
        summary = await refresh_etf_screener(missing)
        return sorted(t for t, r in summary["results"].items() if r.written)
    except Exception:  # noqa: BLE001 -- a watchlist add must not fail because of this write
        logger.warning("Immediate ETF row write failed for %s", tickers, exc_info=True)
        return []
