"""Orchestration layer for the market-breadth signal -- % of S&P 500
constituents above their 20/50/200-day SMA and net new 52-week highs. Same
shape as data/sector_heatmap_data.py: resolve the anchor session, run the
pure math (scoring/market_breadth.py), gate on coverage, persist
(models.py::MarketBreadthSnapshot), and a read path that never computes
live. Independent of FMP and of Step 1-5/Overall Assessment scoring --
zero FMP calls, no data-group guard needed.

Bars come from SharedBarsCache via clients.shared_bars_cache.
get_or_fetch_bars_batch with the SAME call the 3:10 trend job makes
(1d, 730 days, auto_adjust=False), so a run after it is a warm-cache read
with zero incremental Yahoo requests; if the trend job failed or overran
this self-heals with one live fetch and writes through the shared cache
like any other consumer. Every metric is computed from those raw bars
directly, not from TrendAnalysis (latest-only, no 52-week fields, and a
failed fetch leaves an old row behind).

**Coverage gate.** Breadth is a ratio, so a partial Yahoo response would
still produce plausible-looking percentages over the survivors. A run whose
anchor session has bars for fewer than MIN_COVERAGE of the constituents
raises rather than saving a skewed row -- cron_heartbeat then records a
failed run, the same "raise only when the output can't be trusted" contract
nightly_sector_heatmap uses for total failure. Below the gate nothing is
written, so an older date stays the latest one and the page's own as-of
date shows the job has fallen behind. At or above it, `stale_excluded`
records the tickers that were dropped from every count.

**Sector breadth (2026-09-22).** The same 4 metrics, computed per GICS/SPDR
sector (universe "sector:<ETF>", e.g. "sector:XLK") by bucketing the SAME
503 S&P 500 tickers -- and reusing the SAME already-fetched bars/already-
computed per-ticker flags from the sp500 pass, never a second fetch or a
second per-ticker rolling computation -- via SECTOR_TO_ETF/load_sector_
buckets. A sector's own coverage gate (sector_coverage_ok) is deliberately
more permissive than the sp500-level one: it passes on EITHER >=97%
coverage OR at most 1 ticker missing, whichever is more permissive, so a
small sector (~20 names) isn't blocked by a single stale/missing ticker.
One sector failing its gate is isolated -- logged and skipped, never raised
-- so it doesn't block the other 10 sectors' rows that night. Every gate
check (sp500 and every sector, passed or refused) is additionally logged to
MarketBreadthGateLog so the sector gate's provisional policy can be
revisited from real data later -- see models.py::MarketBreadthGateLog."""

import json
import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import bindparam, func, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.daily_bar_sources import FallbackTickers, describe_fallback
from clients.shared_bars_cache import DAILY_INTERVAL, _load_frames, _most_recent_completed_trading_date, get_or_fetch_bars_batch
from core.db import engine
from core.models import IndexConstituent, MarketBreadthGateLog, MarketBreadthSnapshot
from core.schemas import MarketBreadthOut, MarketBreadthPointOut
from data.sector_heatmap_data import SECTOR_ETFS
from scoring.market_breadth import aggregate_flags, snapshot_frame, ticker_flags

logger = logging.getLogger(__name__)

UNIVERSE = "sp500"  # the same name IndexConstituent.index_name uses

# IndexConstituent.sector (scraped from Wikipedia) -> the SPDR ETF whose
# sector it belongs to. This text is verbatim-different from
# data/sector_heatmap_data.py::SECTOR_ETFS's own pretty display names (e.g.
# "Financial Services" here vs. "Financials" there) even though both cover
# the same 11 GICS sectors 1:1 -- confirmed via a full distinct-value scan
# of the real DB (2026-09-22): exactly 11 distinct sector strings for
# index_name="sp500", summing to exactly 503 constituents, matching the 11
# SPDR sectors one-to-one (Technology 85, Industrials 77, Financial
# Services 70, Healthcare 59, Consumer Cyclical 53, Consumer Defensive 33,
# Utilities 32, Real Estate 30, Communication Services 22, Energy 22, Basic
# Materials 20).
SECTOR_TO_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Industrials": "XLI",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
    "Energy": "XLE",
    "Basic Materials": "XLB",
}

# A sector's coverage gate: passes on the sp500-level >=97% rule OR at most
# this many tickers missing, whichever is more permissive -- rescues a
# small sector (e.g. Basic Materials, 20 names, where 1/20 = 5% > 3%) from
# a single stale/missing ticker, while a large sector (e.g. Technology, 85
# names) is already permitted 1-2 missing under the percentage rule alone,
# so the floor is a no-op for it.
SECTOR_COVERAGE_FLOOR_MISSING = 1

# Same call the trend job makes, so this reads the cache it just warmed. 730
# days is the "2y" yfinance tier; "1y" would return 251 bars, one short of a
# 252-session window.
FETCH_LOOKBACK_DAYS = 730

# Fraction of constituents that must have a bar on the anchor session for a
# row to be saved. 0.97 tolerates 15 missing of 503 (488/503 = 97.02%).
MIN_COVERAGE = 0.97

# How many missing tickers an error/summary names -- enough to see a pattern
# (a renamed symbol vs. a wholesale Yahoo failure) without a 500-name message.
MISSING_SAMPLE = 25

_STORED_COLUMNS = (
    "computed_at",
    "constituents",
    "stale_excluded",
    "sma20_eligible",
    "sma20_above",
    "pct_above_sma20",
    "sma50_eligible",
    "sma50_above",
    "pct_above_sma50",
    "sma200_eligible",
    "sma200_above",
    "pct_above_sma200",
    "hl_eligible",
    "new_highs",
    "new_lows",
    "net_new_highs",
    "is_backfilled",
)


class InsufficientCoverageError(RuntimeError):
    """The anchor session has bars for too few constituents to trust."""


def coverage_ok(with_bar: int, constituents: int) -> bool:
    return constituents > 0 and with_bar / constituents >= MIN_COVERAGE


def sector_coverage_ok(with_bar: int, constituents: int) -> bool:
    """A sector's own gate: >=97% coverage (coverage_ok) OR at most
    SECTOR_COVERAGE_FLOOR_MISSING missing, whichever is more permissive."""
    if constituents <= 0:
        return False
    missing = constituents - with_bar
    return missing <= SECTOR_COVERAGE_FLOOR_MISSING or coverage_ok(with_bar, constituents)


def _gate_rule(with_bar: int, constituents: int, floor_missing: int | None) -> str | None:
    """Which rule a coverage check passes under -- "both" | "percentage" |
    "floor" | None (refused) -- used both to decide pass/fail and to record
    *why* in MarketBreadthGateLog. `floor_missing=None` means no floor rule
    applies at all (the sp500-level gate, unchanged from before this
    existed: only ever "percentage" or None)."""
    if constituents <= 0:
        return None
    missing = constituents - with_bar
    pct_ok = coverage_ok(with_bar, constituents)
    floor_ok = floor_missing is not None and missing <= floor_missing
    if pct_ok and floor_ok:
        return "both"
    if pct_ok:
        return "percentage"
    if floor_ok:
        return "floor"
    return None


def _log_gate_check(
    universe: str, as_of_date: date, constituents: int, with_bar: int, missing_tickers: list[str], passed: bool, passed_via: str | None
) -> None:
    """Writes one MarketBreadthGateLog row -- called for every universe
    checked each night (sp500 and every sector), whether it passed or was
    refused, so the sector gate's provisional policy has a real trace to be
    revisited from later. Own Session/commit, mirroring store_snapshots'
    style; deliberately never raises on its own (a logging failure must
    never mask or replace the actual gate outcome)."""
    with Session(engine) as session:
        session.add(
            MarketBreadthGateLog(
                universe=universe,
                as_of_date=as_of_date,
                checked_at=datetime.now(),
                constituents=constituents,
                with_bar=with_bar,
                missing_count=len(missing_tickers),
                missing_tickers_json=json.dumps(missing_tickers[:MISSING_SAMPLE]),
                passed=passed,
                passed_via=passed_via,
            )
        )
        session.commit()


def load_sector_buckets(session: Session) -> dict[str, list[str]]:
    """S&P 500 constituents bucketed by SPDR sector ETF (via SECTOR_TO_ETF),
    keyed and ordered per data/sector_heatmap_data.py::SECTOR_ETFS so sector
    processing order and the frontend's tab order agree. A constituent whose
    `sector` text isn't a recognized key is logged and skipped -- defensive;
    never hit against the real, fully-scanned DB (see SECTOR_TO_ETF)."""
    rows = session.exec(select(IndexConstituent).where(IndexConstituent.index_name == "sp500")).all()
    buckets: dict[str, list[str]] = {etf: [] for etf, _ in SECTOR_ETFS}
    unmapped: list[str] = []
    for row in rows:
        etf = SECTOR_TO_ETF.get(row.sector or "")
        if etf is None:
            unmapped.append(f"{row.ticker} ({row.sector!r})")
            continue
        buckets[etf].append(row.ticker)
    if unmapped:
        logger.warning("Market breadth: %d constituent(s) have an unrecognized sector, excluded from every sector bucket: %s", len(unmapped), unmapped[:MISSING_SAMPLE])
    return buckets


def sector_universe(etf: str) -> str:
    return f"sector:{etf}"


def _resolve_anchor(session_dates: pd.DatetimeIndex, completed_date: date) -> pd.Timestamp | None:
    """The latest session, across every fetched ticker, that is not after
    the last COMPLETED session -- the sector heatmap's rule: taking it from
    the data makes a market holiday anchor to the real last trading day, and
    the `<=` cap drops the in-progress bar yfinance returns during market
    hours (its "close" would be a live price)."""
    eligible = session_dates[session_dates <= pd.Timestamp(completed_date)]
    return eligible.max() if len(eligible) else None


def _row_values(snapshot: pd.Series, as_of: pd.Timestamp, computed_at: datetime, is_backfilled: bool, universe: str = UNIVERSE) -> dict:
    """One snapshot_frame row as plain-Python column values (numpy scalars
    cannot be bound by sqlite3; a NaN percentage becomes NULL). `universe`
    defaults to "sp500"; the sector path passes sector_universe(etf)."""

    def pct(name: str) -> float | None:
        value = snapshot[name]
        return None if pd.isna(value) else float(value)

    return {
        "universe": universe,
        "as_of_date": as_of.date(),
        "computed_at": computed_at,
        "constituents": int(snapshot["constituents"]),
        "stale_excluded": int(snapshot["stale_excluded"]),
        "sma20_eligible": int(snapshot["sma20_eligible"]),
        "sma20_above": int(snapshot["sma20_above"]),
        "pct_above_sma20": pct("pct_above_sma20"),
        "sma50_eligible": int(snapshot["sma50_eligible"]),
        "sma50_above": int(snapshot["sma50_above"]),
        "pct_above_sma50": pct("pct_above_sma50"),
        "sma200_eligible": int(snapshot["sma200_eligible"]),
        "sma200_above": int(snapshot["sma200_above"]),
        "pct_above_sma200": pct("pct_above_sma200"),
        "hl_eligible": int(snapshot["hl_eligible"]),
        "new_highs": int(snapshot["new_highs"]),
        "new_lows": int(snapshot["new_lows"]),
        "net_new_highs": int(snapshot["net_new_highs"]),
        "is_backfilled": is_backfilled,
    }


def store_snapshots(values: list[dict], overwrite: bool) -> int:
    """Upserts snapshot rows. overwrite=True (the nightly job) replaces any
    existing row for the same (universe, as_of_date) -- including a
    backfilled one, since a live row is point-in-time -- so a weekend/holiday
    re-run of the same anchor is idempotent. overwrite=False (the backfill)
    inserts only missing dates and never touches an existing row, so a
    backfill re-run can never clobber a live row. Returns the number of NEW
    rows inserted (an overwritten row counts 0) -- taken as a before/after row
    count, since an executemany upsert has no reliable rowcount."""
    if not values:
        return 0
    with Session(engine) as session:
        before = session.exec(select(func.count()).select_from(MarketBreadthSnapshot)).one()
        stmt = sqlite_insert(MarketBreadthSnapshot)
        if overwrite:
            stmt = stmt.on_conflict_do_update(
                index_elements=["universe", "as_of_date"],
                set_={c: getattr(stmt.excluded, c) for c in _STORED_COLUMNS},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=["universe", "as_of_date"])
        session.execute(stmt, values)
        session.commit()
        return session.exec(select(func.count()).select_from(MarketBreadthSnapshot)).one() - before


def fill_missing_sma20(values: list[dict], dry_run: bool = False) -> int:
    """Fills the three sma20 columns on EXISTING backfilled rows that predate
    the 20-day metric (`sma20_eligible IS NULL`), from `values` (the
    backfill's own rows for the same dates). store_snapshots(overwrite=False)
    cannot do this -- on_conflict_do_nothing skips an existing row entirely,
    so those rows would stay NULL forever.

    The never-overwrite guarantee is kept in the UPDATE itself: it writes ONLY
    the three sma20 columns, ONLY where sma20_eligible is still NULL, and ONLY
    on `is_backfilled` rows. A row that already has a sma20 value is never
    touched (a re-run is a no-op), no other column is ever touched, and a
    LIVE nightly row is left alone even if it were NULL -- it is
    point-in-time, and filling it from today's constituents would put
    survivorship bias into a row that is otherwise free of it (in practice a
    live row always has sma20, since the nightly job writes it).

    Returns the number of rows filled (with dry_run: the number that would be)."""
    if not values:
        return 0
    with Session(engine) as session:
        pending = set(
            session.exec(
                select(MarketBreadthSnapshot.as_of_date).where(
                    MarketBreadthSnapshot.universe == UNIVERSE,
                    MarketBreadthSnapshot.is_backfilled == True,  # noqa: E712
                    MarketBreadthSnapshot.sma20_eligible.is_(None),  # type: ignore[union-attr]
                )
            ).all()
        )
        rows = [
            {"b_date": v["as_of_date"], "b_eligible": v["sma20_eligible"], "b_above": v["sma20_above"], "b_pct": v["pct_above_sma20"]}
            for v in values
            if v["as_of_date"] in pending
        ]
        if dry_run or not rows:
            return len(rows)
        table = MarketBreadthSnapshot.__table__
        stmt = (
            update(table)
            .where(
                table.c.universe == UNIVERSE,
                table.c.as_of_date == bindparam("b_date"),
                table.c.is_backfilled == True,  # noqa: E712
                table.c.sma20_eligible.is_(None),
            )
            .values(sma20_eligible=bindparam("b_eligible"), sma20_above=bindparam("b_above"), pct_above_sma20=bindparam("b_pct"))
        )
        session.connection().execute(stmt, rows)
        session.commit()
    return len(rows)


async def compute_and_store_market_breadth(
    tickers: list[str], completed_date: date | None = None, sector_tickers: dict[str, list[str]] | None = None
) -> dict:
    """Computes the latest completed session's breadth row for `tickers`
    (the caller resolves the universe -- pipeline/nightly_market_breadth.py
    passes load_sp500_tickers) and upserts it. `completed_date` (default:
    derived from the clock) is a testing/manual-run seam.

    `sector_tickers` (default None -- every existing caller/test that omits
    it is unaffected) additionally computes and stores a "sector:<ETF>" row
    per entry, reusing the SAME bars/flags already fetched/computed for
    `tickers` above -- no second fetch, no second per-ticker rolling pass,
    see load_sector_buckets. Each sector is gated independently
    (sector_coverage_ok) and isolated: a refused sector is logged and
    skipped, never raised, so it can't block the other sectors' rows that
    night -- see _process_sectors.

    Raises RuntimeError when there are no tickers or no bars at all, and
    InsufficientCoverageError when fewer than MIN_COVERAGE of the tickers
    have a bar on the anchor session -- in both cases nothing is written,
    including no sector rows (the sp500-level gate runs first)."""
    if not tickers:
        raise RuntimeError("Market breadth: empty universe -- run scrapers.refresh_sp500_list first")
    completed = completed_date or _most_recent_completed_trading_date()

    fallback_tickers = FallbackTickers()
    bars = await get_or_fetch_bars_batch(
        tickers, DAILY_INTERVAL, FETCH_LOOKBACK_DAYS, auto_adjust=False, fallback_tickers=fallback_tickers
    )
    flags = ticker_flags(bars)
    counts = aggregate_flags(flags)

    anchor = _resolve_anchor(counts.index, completed) if len(counts) else None
    if anchor is None:
        raise RuntimeError(f"Market breadth: no usable bars for any of {len(tickers)} tickers on/before {completed}")

    missing = sorted(t for t in tickers if t not in flags or anchor not in flags[t].index)
    with_bar = len(tickers) - len(missing)
    rule = _gate_rule(with_bar, len(tickers), floor_missing=None)
    _log_gate_check(UNIVERSE, anchor.date(), len(tickers), with_bar, missing, passed=rule is not None, passed_via=rule)
    if rule is None:
        raise InsufficientCoverageError(
            f"Market breadth: only {with_bar}/{len(tickers)} constituents ({with_bar / len(tickers):.1%}) have a bar on "
            f"{anchor.date()}, below the {MIN_COVERAGE:.0%} coverage gate -- not saving a skewed row. "
            f"Missing: {missing[:MISSING_SAMPLE]}{' ...' if len(missing) > MISSING_SAMPLE else ''}"
        )

    computed_at = datetime.now()
    snapshot = snapshot_frame(counts.loc[[anchor]], len(tickers)).iloc[0]
    values = _row_values(snapshot, anchor, computed_at, is_backfilled=False)
    store_snapshots([values], overwrite=True)

    if missing:
        logger.warning("Market breadth: %d constituent(s) had no bar on %s and were excluded: %s", len(missing), anchor.date(), missing)
    summary = {
        "as_of_date": anchor.date().isoformat(),
        "constituents": len(tickers),
        "with_bar": with_bar,
        "stale_excluded": len(missing),
        "missing": missing[:MISSING_SAMPLE],
        "pct_above_sma20": values["pct_above_sma20"],
        "pct_above_sma50": values["pct_above_sma50"],
        "pct_above_sma200": values["pct_above_sma200"],
        "new_highs": values["new_highs"],
        "new_lows": values["new_lows"],
        "net_new_highs": values["net_new_highs"],
        "fallback_count": len(fallback_tickers), "fallback_yahoo_count": len(fallback_tickers.yahoo),
    }
    logger.info(
        "Market breadth complete for %s: %d/%d constituents, %%>SMA20 %s, %%>SMA50 %s, %%>SMA200 %s, net new highs %d.",
        anchor.date(), with_bar, len(tickers),
        None if values["pct_above_sma20"] is None else round(values["pct_above_sma20"], 1),
        None if values["pct_above_sma50"] is None else round(values["pct_above_sma50"], 1),
        None if values["pct_above_sma200"] is None else round(values["pct_above_sma200"], 1),
        values["net_new_highs"],
    )

    if sector_tickers:
        summary["sectors"] = _process_sectors(sector_tickers, flags, anchor, computed_at)
    return summary


def _process_sectors(sector_tickers: dict[str, list[str]], flags: dict[str, pd.DataFrame], anchor: pd.Timestamp, computed_at: datetime) -> dict:
    """One sector:<ETF> row per entry in `sector_tickers`, reusing the
    already-computed `flags` (sliced per sector, then aggregated -- cheap
    summation, no re-fetch/re-roll). Each sector is gated and logged
    independently; a refused sector is skipped (never raised) so it can't
    block the others. Returns {etf: {passed, constituents, with_bar,
    gate_rule|missing}}."""
    results: dict[str, dict] = {}
    for etf, tickers in sector_tickers.items():
        universe = sector_universe(etf)
        constituents = len(tickers)
        sub_flags = {t: flags[t] for t in tickers if t in flags}
        counts = aggregate_flags(sub_flags)
        with_bar = int(counts.loc[anchor, "with_bar"]) if anchor in counts.index else 0
        missing = sorted(t for t in tickers if t not in flags or anchor not in flags[t].index)

        rule = _gate_rule(with_bar, constituents, floor_missing=SECTOR_COVERAGE_FLOOR_MISSING)
        _log_gate_check(universe, anchor.date(), constituents, with_bar, missing, passed=rule is not None, passed_via=rule)

        if rule is None or anchor not in counts.index:
            results[etf] = {"passed": False, "constituents": constituents, "with_bar": with_bar, "missing": missing[:MISSING_SAMPLE]}
            logger.warning(
                "Market breadth (%s): refused -- %d/%d constituents have a bar on %s. Missing: %s",
                universe, with_bar, constituents, anchor.date(), missing[:MISSING_SAMPLE],
            )
            continue

        snapshot = snapshot_frame(counts.loc[[anchor]], constituents).iloc[0]
        values = _row_values(snapshot, anchor, computed_at, is_backfilled=False, universe=universe)
        store_snapshots([values], overwrite=True)
        results[etf] = {"passed": True, "constituents": constituents, "with_bar": with_bar, "gate_rule": rule, "pct_above_sma50": values["pct_above_sma50"]}

    refused = [etf for etf, r in results.items() if not r["passed"]]
    if refused:
        logger.warning("Market breadth: %d/%d sector(s) refused this run: %s", len(refused), len(results), refused)
    return results


def load_cached_daily_bars(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Every daily bar SharedBarsCache already holds for `tickers` -- a pure
    READ. Unlike get_or_fetch_bars_batch this never fetches and never
    writes, which is the point for the backfill: it must not widen or
    refresh the shared cache (widening 409 tickers from 2y to 5y would make
    every later nightly refetch pull 5y for them)."""
    with Session(engine) as session:
        return _load_frames(session, tickers, DAILY_INTERVAL, date(1970, 1, 1))


def build_backfill_rows(
    bars: dict[str, pd.DataFrame], constituents: int, completed_date: date, computed_at: datetime | None = None
) -> tuple[list[dict], dict]:
    """Snapshot rows for every historical session `bars` can support, plus a
    summary. A session is kept only if bars exist for >= MIN_COVERAGE of the
    constituents AND the same fraction is eligible for the 52-week window
    (the hardest to satisfy -- 252 own bars -- so it also implies SMA50/
    SMA200 eligibility): earlier sessions would be a subset of the universe,
    not the index, and a curve stitched across that boundary is misleading.
    The 20-day SMA needs fewer bars than the 52-week window, so this gate
    already implies sma20 eligibility -- it adds no constraint of its own.
    Sessions after `completed_date` (an in-progress bar) are dropped."""
    computed_at = computed_at or datetime.now()
    counts = aggregate_flags(ticker_flags(bars))
    counts = counts[counts.index <= pd.Timestamp(completed_date)]
    if counts.empty:
        return [], {"sessions_seen": 0, "kept": 0, "first_date": None, "last_date": None}

    snapshot = snapshot_frame(counts, constituents)
    keep = (counts["with_bar"] / constituents >= MIN_COVERAGE) & (counts["hl_eligible"] / constituents >= MIN_COVERAGE)
    kept = snapshot[keep]
    values = [_row_values(row, as_of, computed_at, is_backfilled=True) for as_of, row in kept.iterrows()]
    summary = {
        "sessions_seen": len(counts),
        "kept": len(values),
        "first_date": kept.index.min().date().isoformat() if len(kept) else None,
        "last_date": kept.index.max().date().isoformat() if len(kept) else None,
    }
    return values, summary


def _sector_keep_mask(present: pd.Series, constituents: int) -> pd.Series:
    """Vectorized counterpart to sector_coverage_ok, for the backfill's
    per-session keep mask: passes where at most SECTOR_COVERAGE_FLOOR_MISSING
    are missing OR coverage is >= MIN_COVERAGE, whichever is more permissive."""
    missing = constituents - present
    return (missing <= SECTOR_COVERAGE_FLOOR_MISSING) | (present / constituents >= MIN_COVERAGE)


def build_sector_backfill_rows(
    bars: dict[str, pd.DataFrame], sector_tickers: dict[str, list[str]], completed_date: date, computed_at: datetime | None = None
) -> tuple[list[dict], dict[str, dict]]:
    """Per-sector counterpart to build_backfill_rows, reusing the SAME
    already-loaded `bars` (no separate read -- bars is typically the full
    sp500 load_cached_daily_bars() result, sliced per sector here) and
    `sector_tickers` (load_sector_buckets). A session is kept only if it
    clears the sector's own more-permissive OR-gate (sector_coverage_ok) on
    BOTH legs build_backfill_rows already gates on: bar presence AND
    52-week eligibility -- the same AND-of-two-legs shape, just each leg is
    the sector's own OR condition instead of a flat percentage. Not logged
    to MarketBreadthGateLog -- that table tracks the nightly job's ongoing
    gate behavior, not this one-time historical backfill's own (already
    reported, in this summary) keep-mask.

    Returns (every kept row across every sector, combined into one list for
    store_snapshots), {etf: {sessions_seen, kept, first_date, last_date}})."""
    computed_at = computed_at or datetime.now()
    all_values: list[dict] = []
    summaries: dict[str, dict] = {}
    for etf, tickers in sector_tickers.items():
        constituents = len(tickers)
        if constituents == 0:
            summaries[etf] = {"sessions_seen": 0, "kept": 0, "first_date": None, "last_date": None}
            continue
        sub_bars = {t: bars[t] for t in tickers if t in bars}
        counts = aggregate_flags(ticker_flags(sub_bars))
        if counts.empty:  # no bars at all for this sector -- checked before the date filter, whose index dtype assumes a real DatetimeIndex
            summaries[etf] = {"sessions_seen": 0, "kept": 0, "first_date": None, "last_date": None}
            continue
        counts = counts[counts.index <= pd.Timestamp(completed_date)]
        if counts.empty:
            summaries[etf] = {"sessions_seen": 0, "kept": 0, "first_date": None, "last_date": None}
            continue

        snapshot = snapshot_frame(counts, constituents)
        keep = _sector_keep_mask(counts["with_bar"], constituents) & _sector_keep_mask(counts["hl_eligible"], constituents)
        kept = snapshot[keep]
        values = [_row_values(row, as_of, computed_at, is_backfilled=True, universe=sector_universe(etf)) for as_of, row in kept.iterrows()]
        all_values.extend(values)
        summaries[etf] = {
            "sessions_seen": len(counts),
            "kept": len(values),
            "first_date": kept.index.min().date().isoformat() if len(kept) else None,
            "last_date": kept.index.max().date().isoformat() if len(kept) else None,
        }
    return all_values, summaries


def _point(row: MarketBreadthSnapshot) -> MarketBreadthPointOut:
    return MarketBreadthPointOut(
        as_of_date=row.as_of_date,
        pct_above_sma20=row.pct_above_sma20,
        pct_above_sma50=row.pct_above_sma50,
        pct_above_sma200=row.pct_above_sma200,
        sma20_above=row.sma20_above,
        sma50_above=row.sma50_above,
        sma200_above=row.sma200_above,
        new_highs=row.new_highs,
        new_lows=row.new_lows,
        net_new_highs=row.net_new_highs,
        constituents=row.constituents,
        stale_excluded=row.stale_excluded,
        sma20_eligible=row.sma20_eligible,
        sma50_eligible=row.sma50_eligible,
        sma200_eligible=row.sma200_eligible,
        hl_eligible=row.hl_eligible,
        is_backfilled=row.is_backfilled,
    )


def get_market_breadth(universe: str = UNIVERSE) -> MarketBreadthOut:
    """Reads the persisted history for `universe` ("sp500" or a
    "sector:<ETF>" value) -- never computes live. Empty (latest/as_of_date/
    computed_at None, series []) before any row exists for that universe,
    never an error -- including an unrecognized universe string. The whole
    series is returned, oldest first: a row is ~100 bytes and the table is
    never pruned, so a few thousand points at most."""
    with Session(engine) as session:
        rows = session.exec(
            select(MarketBreadthSnapshot).where(MarketBreadthSnapshot.universe == universe).order_by(MarketBreadthSnapshot.as_of_date)
        ).all()
    if not rows:
        return MarketBreadthOut(universe=universe, as_of_date=None, computed_at=None, latest=None, series=[])
    series = [_point(row) for row in rows]
    return MarketBreadthOut(
        universe=universe, as_of_date=rows[-1].as_of_date, computed_at=rows[-1].computed_at, latest=series[-1], series=series
    )
