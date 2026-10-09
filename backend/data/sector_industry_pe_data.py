"""Sector / industry average P/E from FMP (data group `sector_industry_pe`; docs/specs/sector-industry-pe.md).

Phase 1, data layer only: the `SectorIndustryPe` table, the nightly snapshot refresh, the one-time 5-year backfill
and a series read. No chart or UI consumes it yet, and nothing here touches a ticker's own P/E.

FMP facts this module is built on (confirmed live 2026-10-09):
  * the snapshots (`/sector-pe-snapshot`, `/industry-pe-snapshot`) take a mandatory `date` and an `exchange`; the
    historical calls (`/historical-sector-pe`, `/historical-industry-pe`) take the sector / industry name and
    `exchange`. Omitting `exchange` silently defaults to NASDAQ, so every call passes it; the historical calls
    always pass explicit from/to (the default window ends 2024-03-01);
  * a snapshot dated on a weekend or in the future still answers, so the date used is the last COMPLETED trading day;
  * a name can have no series on an exchange (`[]`, e.g. "Asset Management" on some): nothing is stored for it.

Every write is an UPSERT on (kind, name, exchange, date) and nothing here deletes, so an empty or shorter answer can
never remove stored history (this table is deliberately outside FundamentalsCache / HISTORY_KEYS).

`engine` is a module-level reference so tests can monkeypatch it (the per-module engine-isolation convention)."""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.fmp_client import FMPGroupDisabledError, fmp_client
from clients.shared_bars_cache import _most_recent_completed_trading_date
from core.db import engine
from core.models import SectorIndustryPe

logger = logging.getLogger(__name__)

SECTOR = "sector"
INDUSTRY = "industry"
KINDS = (SECTOR, INDUSTRY)
# The exchanges the overlay serves. A ticker on any other listing (OTC, CBOE, ...) and every ETF gets no overlay.
EXCHANGES = ("NASDAQ", "NYSE", "AMEX")
HISTORY_YEARS = 5
# A stored series counts as fully backfilled when its oldest row is within this many days of the window start (the
# window start is a calendar date, so the first stored row can be a few days later).
BACKFILL_START_SLACK_DAYS = 14
# Paced under the Starter tier's 300 requests/minute.
BACKFILL_REQUEST_INTERVAL_SECONDS = 0.25
_UPSERT_CHUNK = 500

# The label the future UI must show; FMP averages the listed companies' P/E, which is not Fathom's ticker P/E basis.
LABEL = "average PE of listed companies (FMP)"


def window_start(today: date | None = None, years: int = HISTORY_YEARS) -> date:
    """`years` calendar years back from `today`."""
    anchor = today or date.today()
    try:
        return anchor.replace(year=anchor.year - years)
    except ValueError:  # Feb 29
        return anchor.replace(year=anchor.year - years, day=28)


def history_window(today: date | None = None, years: int = HISTORY_YEARS) -> tuple[date, date]:
    """(from, to) of the backfill: `years` back from `today`, ending on the last completed trading day."""
    return window_start(today, years), _most_recent_completed_trading_date()


def parse_rows(kind: str, exchange: str, body: object) -> list[dict]:
    """Valid rows of an FMP answer as table dicts. A non-list body, a row that is not a dict, lacks a date or a name,
    carries a non-numeric P/E or names another exchange is dropped (never raises)."""
    if not isinstance(body, list):
        return []
    key = SECTOR if kind == SECTOR else INDUSTRY
    out: list[dict] = []
    for row in body:
        if not isinstance(row, dict):
            continue
        name, raw_date, pe = row.get(key), row.get("date"), row.get("pe")
        if not isinstance(name, str) or not name or not isinstance(raw_date, str):
            continue
        if isinstance(pe, bool) or not isinstance(pe, (int, float)) or pe != pe:  # NaN
            continue
        row_exchange = row.get("exchange")
        if isinstance(row_exchange, str) and row_exchange.upper() != exchange:
            continue
        try:
            day = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        out.append({"kind": kind, "name": name, "exchange": exchange, "date": day, "pe": float(pe)})
    return out


def upsert_rows(rows: list[dict]) -> int:
    """Upsert-only write; returns the number of rows sent. A later value for the same key replaces the earlier one."""
    if not rows:
        return 0
    with Session(engine) as session:
        for i in range(0, len(rows), _UPSERT_CHUNK):
            stmt = sqlite_insert(SectorIndustryPe)
            stmt = stmt.on_conflict_do_update(
                index_elements=["kind", "name", "exchange", "date"], set_={"pe": stmt.excluded.pe}
            )
            session.execute(stmt, rows[i : i + _UPSERT_CHUNK])
        session.commit()
    return len(rows)


def get_series(kind: str, name: str, exchange: str, years: int = HISTORY_YEARS) -> list[tuple[date, float]]:
    """The stored (date, pe) series for one sector / industry on one exchange, oldest first, limited to the last
    `years` years. Empty when nothing is stored (no overlay)."""
    since = window_start(years=years)
    with Session(engine) as session:
        rows = session.exec(
            select(SectorIndustryPe.date, SectorIndustryPe.pe)
            .where(
                SectorIndustryPe.kind == kind,
                SectorIndustryPe.name == name,
                SectorIndustryPe.exchange == exchange,
                SectorIndustryPe.date >= since,
            )
            .order_by(SectorIndustryPe.date)
        ).all()
    return [(d, pe) for d, pe in rows]


def _oldest_stored(kind: str, name: str, exchange: str) -> date | None:
    with Session(engine) as session:
        return session.exec(
            select(func.min(SectorIndustryPe.date)).where(
                SectorIndustryPe.kind == kind, SectorIndustryPe.name == name, SectorIndustryPe.exchange == exchange
            )
        ).first()


def count_rows() -> dict[tuple[str, str], int]:
    """(kind, exchange) -> stored rows."""
    with Session(engine) as session:
        rows = session.exec(
            select(SectorIndustryPe.kind, SectorIndustryPe.exchange, func.count()).group_by(
                SectorIndustryPe.kind, SectorIndustryPe.exchange
            )
        ).all()
    return {(k, e): n for k, e, n in rows}


# ---------------------------------------------------------------------------
# Nightly snapshot
# ---------------------------------------------------------------------------


@dataclass
class SnapshotResult:
    as_of: date
    attempted: int = 0
    failed: int = 0
    no_data: int = 0
    written: int = 0
    failures: list[str] = field(default_factory=list)


async def _snapshot_call(kind: str, as_of: date, exchange: str):
    fetch = fmp_client.get_sector_pe_snapshot if kind == SECTOR else fmp_client.get_industry_pe_snapshot
    return await fetch(as_of.isoformat(), exchange)


async def refresh_snapshots(as_of: date | None = None) -> SnapshotResult:
    """2 snapshots x 3 exchanges for the last completed trading day, upserted. One failing call does not stop the
    others; a call that answers with no rows counts as `no_data`."""
    day = as_of or _most_recent_completed_trading_date()
    result = SnapshotResult(as_of=day)
    for exchange in EXCHANGES:
        for kind in KINDS:
            result.attempted += 1
            try:
                body = await _snapshot_call(kind, day, exchange)
            except Exception as exc:  # noqa: BLE001 -- per-call isolation, reported in the summary
                result.failed += 1
                result.failures.append(f"{kind}/{exchange}: {type(exc).__name__}")
                logger.error("Sector/industry P/E snapshot %s %s %s failed: %s", kind, exchange, day, exc)
                continue
            rows = parse_rows(kind, exchange, body)
            if not rows:
                result.no_data += 1
                logger.warning("Sector/industry P/E snapshot %s %s %s: no rows", kind, exchange, day)
                continue
            result.written += upsert_rows(rows)
    return result


# ---------------------------------------------------------------------------
# One-time backfill
# ---------------------------------------------------------------------------


@dataclass
class BackfillResult:
    start: date
    end: date
    series_total: int = 0
    series_fetched: int = 0
    series_skipped: int = 0
    rows: dict[tuple[str, str], int] = field(default_factory=dict)  # (kind, exchange) -> rows written this run
    empty: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, name, exchange) FMP answered with nothing
    failed: list[tuple[str, str, str, str]] = field(default_factory=list)  # (kind, name, exchange, error)


async def discover_names(end: date, exchange: str) -> dict[str, list[str]]:
    """kind -> sorted names present on the exchange's snapshots at `end`. A snapshot that fails or is empty gives an
    empty list for that kind (logged), never an exception, except a disabled group, which stops the run."""
    names: dict[str, list[str]] = {}
    for kind in KINDS:
        try:
            body = await _snapshot_call(kind, end, exchange)
        except FMPGroupDisabledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Backfill discovery %s %s failed: %s", kind, exchange, exc)
            names[kind] = []
            continue
        names[kind] = sorted({r["name"] for r in parse_rows(kind, exchange, body)})
        if not names[kind]:
            logger.warning("Backfill discovery %s %s %s: snapshot returned no names", kind, exchange, end)
    return names


async def backfill_history(
    start: date | None = None,
    end: date | None = None,
    *,
    exchanges: tuple[str, ...] = EXCHANGES,
    kinds: tuple[str, ...] = KINDS,
    force: bool = False,
) -> BackfillResult:
    """Fetch and upsert the last HISTORY_YEARS years of every sector and every industry on the snapshot, per
    exchange. Idempotent (upserts); resumable (a series whose oldest stored row already reaches the window start is
    skipped unless `force`; a series FMP answers empty stores nothing and is retried on the next run). Each series is
    one atomic write. Raises only when the data group is disabled mid-run."""
    default_start, default_end = history_window()
    start, end = start or default_start, end or default_end
    result = BackfillResult(start=start, end=end)
    for exchange in exchanges:
        names = await discover_names(end, exchange)
        for kind in kinds:
            for name in names.get(kind, []):
                result.series_total += 1
                if not force:
                    oldest = _oldest_stored(kind, name, exchange)
                    if oldest is not None and oldest <= start + timedelta(days=BACKFILL_START_SLACK_DAYS):
                        result.series_skipped += 1
                        continue
                try:
                    fetch = (
                        fmp_client.get_historical_sector_pe if kind == SECTOR else fmp_client.get_historical_industry_pe
                    )
                    body = await fetch(name, exchange, start.isoformat(), end.isoformat())
                except FMPGroupDisabledError:
                    raise
                except Exception as exc:  # noqa: BLE001 -- per-series isolation
                    result.failed.append((kind, name, exchange, f"{type(exc).__name__}: {exc}"))
                    logger.error("Backfill %s %r %s failed: %s", kind, name, exchange, exc)
                    continue
                rows = parse_rows(kind, exchange, body)
                if not rows:
                    result.empty.append((kind, name, exchange))
                    logger.warning("Backfill %s %r %s: FMP returned no series, nothing recorded", kind, name, exchange)
                    continue
                written = upsert_rows(rows)
                result.series_fetched += 1
                result.rows[(kind, exchange)] = result.rows.get((kind, exchange), 0) + written
    logger.info(
        "Sector/industry P/E backfill %s..%s: %d series, %d fetched, %d skipped, %d empty, %d failed",
        start, end, result.series_total, result.series_fetched, result.series_skipped, len(result.empty), len(result.failed),
    )
    return result
