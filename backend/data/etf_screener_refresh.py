"""The ETF screener refresh (docs/specs/etf-screener.md, step 4): for every ETF in the ETF universe
(data/tracked_universe.py::load_etf_universe) compute the fields of one models.py::EtfScreenerRow and write
them through data/etf_screener_data.py::upsert_etf_screener_row. Entry point: pipeline/nightly_etf_screener.py
(registered as a cron job, 1:45 AM, since 2026-10-03 -- step 6).

Where each field comes from (all existing paths, nothing reimplemented):
  * name, last_price, pct_change_1d, as_of_date, return_1y, vs_spy_1y -- the shared daily-bar cache
    (clients/shared_bars_cache.py, split-adjusted close, no dividend adjustment) read through
    read_cached_completed_daily_bars after one get_or_fetch_bars_batch; returns by
    scoring/etf_returns.py::compute_window_returns (the Sector Heatmap / ETF page math).
  * asset_class, expense_ratio, aum, info_updated_at -- /etf/info via data/etf_data.py::load_etf_info (1-day TTL).
  * name, beta -- the cached FMP profile (30-day TTL), beta stored RAW (the equity-only rule is applied on read).
  * Weinstein fields -- the pure engines analysis/trend_structure/weinstein*.py with the live Settings and the same
    benchmark behaviour as pipeline/nightly_trend_calculation.py, computed ONCE per ETF
    (data/trend_analysis_data.py::compute_weinstein_results): the one result feeds both the EtfScreenerRow fields and the
    ETF's TrendAnalysis row (cutover step 7: the stock job no longer refreshes ETFs, so this job owns that row).
  * TickerLastClose -- data/last_close_data.py::refresh_last_closes, the helper the stock-side last-close job uses (one
    /historical-price-eod/full call per ETF, same completed-session semantics), for the same reason.
  * Signal fields -- read from TechnicalEntrySignal / WarrenSignalEvent, the tables the monitored-watchlist jobs
    fill, through the same helpers data/ticker_score.py uses.

Partial-write rule: only fields computed successfully THIS run are passed to the upsert, so a transient failure of
one source never overwrites a good stored value with NULL. The same holds for the other two tables this job writes:
a TrendAnalysis row is written only when a stage was actually determined (the stock job writes a NULL stage; this
job leaves the previous row alone), and a failed last-close fetch keeps the stored close. The one exception is the three signal fields, a
deterministic local read where "no signal row" is the true answer. A source that has nothing (a fund younger than a
year has no 1Y return, a seed never opened has no cached info) contributes nothing.

`engine` is a module-level reference so tests can monkeypatch it (the per-module convention)."""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import delete
from sqlmodel import Session, select

from analysis.trend_structure.types import WeinsteinStageResult
from analysis.trend_structure.weinstein import WEINSTEIN_BENCHMARK_TICKER, WeinsteinParams
from analysis.trend_structure.weinstein_pending import WeinsteinPendingResult
from clients.daily_bar_sources import UnservedTickers
from clients.fmp_client import fmp_client
from clients.shared_bars_cache import (
    DAILY_INTERVAL,
    get_or_fetch_bars_batch,
    read_cached_completed_daily_bars,
    stale_ticker_count,
)
from core.cache import get_or_fetch
from core.config import settings
from core.cron_health import check_failure_threshold
from core.db import engine
from core.models import EtfScreenerRow, TechnicalEntrySignal
from core.tickers import normalize_ticker
from data.entry_signal_data import DEFAULT_SIGNAL_TYPE, DEFAULT_TIMEFRAME, is_entry_signal_active
from data.etf_data import _number, _overview_from_payload, _text, load_etf_info
from data.etf_screener_data import upsert_etf_screener_row
from data.tracked_universe import load_etf_universe
from data.last_close_data import refresh_last_closes
from data.trend_analysis_data import WEINSTEIN_LOOKBACK_DAYS, compute_weinstein_results, store_weinstein_results
from data.warren_signal_data import (
    DEFAULT_SIGNAL_TYPE as WARREN_SIGNAL_TYPE,
    DEFAULT_TIMEFRAME as WARREN_TIMEFRAME,
    last_buy_signal_fired_at,
    warren_active_up_kind,
)
from helpers.weinstein_config import load_weinstein_params
from scoring.etf_returns import compute_window_returns

logger = logging.getLogger(__name__)

# The relative-performance benchmark for vs_spy_1y. SPY itself, independent of the Weinstein RS benchmark setting.
VS_BENCHMARK_TICKER = WEINSTEIN_BENCHMARK_TICKER

_EMPTY_BARS = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


@dataclass
class EtfRefreshResult:
    """One ETF's outcome: the fields computed this run (what was / would be written), notes on what is missing and
    why, and the sources that raised (a raised source is a failure; a source with simply no data is not)."""

    ticker: str
    fields: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written: bool = False
    # /etf/info's name: used only when the profile gave none and did not fail (so a profile outage cannot swap a
    # stored name for the other source's wording).
    info_name: str | None = None
    # The one Weinstein computation (stage, pending, newest bar date), kept so the run can store the same result to
    # TrendAnalysis. None when no stage was determined.
    weinstein: tuple[WeinsteinStageResult, WeinsteinPendingResult, date] | None = None
    trend_analysis_written: bool = False


def _bar_fields(ticker: str, bars: pd.DataFrame, spy_bars: pd.DataFrame, result: EtfRefreshResult) -> None:
    """last_price / pct_change_1d / as_of_date from the last two completed bars, return_1y, vs_spy_1y."""
    close = bars["close"].dropna() if not bars.empty else pd.Series(dtype=float)
    if close.empty:
        result.notes.append("no cached daily bars: price, return and Weinstein fields not computed")
        return
    anchor = close.index.max().normalize()
    result.fields["last_price"] = float(close.iloc[-1])
    result.fields["as_of_date"] = anchor.date()
    if len(close) >= 2 and close.iloc[-2] > 0:
        result.fields["pct_change_1d"] = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1.0) * 100.0
    else:
        result.notes.append("fewer than two bars: pct_change_1d not computed")

    by_window = {r.window: r.return_pct for r in compute_window_returns(close, anchor)}
    return_1y = by_window.get("1y")
    if return_1y is None:
        result.notes.append("no 1Y return (young fund, shallow cache or newest bar stale): return_1y and vs_spy_1y not computed")
        return
    result.fields["return_1y"] = return_1y

    spy_close = spy_bars["close"].dropna() if not spy_bars.empty else pd.Series(dtype=float)
    spy_close = spy_close[~spy_close.index.duplicated()]
    if spy_close.empty:
        result.notes.append("SPY bars missing: vs_spy_1y not computed")
        logger.warning("%s: SPY bars missing, vs_spy_1y left unset", ticker)
        return
    # Same as_of window: SPY must have a bar on the ETF's own anchor date, or the two returns would end on
    # different sessions.
    if anchor not in spy_close.index.normalize():
        result.notes.append(f"SPY has no bar on {anchor.date()}: vs_spy_1y not computed")
        logger.warning("%s: SPY has no bar on %s, vs_spy_1y left unset", ticker, anchor.date())
        return
    spy_return = {r.window: r.return_pct for r in compute_window_returns(spy_close, anchor)}.get("1y")
    if spy_return is None:
        result.notes.append("SPY 1Y return unavailable: vs_spy_1y not computed")
        logger.warning("%s: SPY 1Y return unavailable, vs_spy_1y left unset", ticker)
        return
    result.fields["vs_spy_1y"] = return_1y - spy_return


def _weinstein_fields(bars: pd.DataFrame, benchmark_bars: pd.DataFrame, params: WeinsteinParams, result: EtfRefreshResult) -> None:
    """The Weinstein engines on the ETF's own bars, same params and benchmark handling as the stock job (a
    missing benchmark degrades the Mansfield RS fields inside the engine, never the stage). Written only when
    a stage was actually determined."""
    if bars.empty:
        return
    stage, pending = compute_weinstein_results(bars, benchmark_bars if not benchmark_bars.empty else _EMPTY_BARS, params)
    if stage.stage is None:
        result.notes.append("Weinstein stage not determined (too little weekly history): Weinstein fields not computed")
        return
    result.weinstein = (stage, pending, bars.index.max().date())
    result.fields.update(
        weinstein_stage=stage.stage,
        weinstein_stage_since_date=stage.stage_since_date,
        weinstein_stage_since_is_lower_bound=stage.stage_since_is_lower_bound,
        weinstein_ma_slope_pct=stage.ma_slope_pct,
        weinstein_vs_ma_pct=stage.vs_ma_pct,
        weinstein_pending_direction=pending.direction,
    )


def _parse_updated_at(value) -> datetime | None:
    """/etf/info `updatedAt` ("2026-10-01T00:48:40.039Z") as a naive UTC datetime."""
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


async def _info_fields(ticker: str, cache_only: bool, result: EtfRefreshResult) -> None:
    loaded = await load_etf_info(ticker, cache_only=cache_only)
    if loaded.failed:
        result.errors.append("etf_info fetch failed" + (" (stale cached row used)" if loaded.payload is not None else ""))
    if loaded.payload is None:
        if not loaded.failed:
            result.notes.append("no /etf/info cached" + ("" if cache_only else " (group off or not on plan)"))
        return
    overview = _overview_from_payload(ticker, loaded.payload, loaded.fetched_at)
    if overview.status != "ok":
        result.notes.append("/etf/info has no fund record for this ticker")
        return
    if overview.name is not None:
        result.info_name = overview.name  # only a fallback for the profile's name, see _refresh_one
    for column, value in (
        ("asset_class", overview.asset_class),
        ("expense_ratio", overview.expense_ratio),
        ("aum", overview.assets_under_management),
    ):
        if value is not None:
            result.fields[column] = value
    row = loaded.payload[0] if isinstance(loaded.payload, list) and loaded.payload else {}
    updated = _parse_updated_at(row.get("updatedAt")) if isinstance(row, dict) else None
    if updated is not None:
        result.fields["info_updated_at"] = updated


async def _profile_fields(ticker: str, cache_only: bool, result: EtfRefreshResult) -> None:
    """name (preferred over /etf/info's) and the RAW beta from the cached profile. A beta of 0 / NaN is FMP's "unknown", not
    a beta, so it is not stored. The equity-only rule is NOT applied here (it is applied when the row is read)."""
    with Session(engine) as session:
        payload = await get_or_fetch(
            session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker),
            settings.profile_staleness_days, cache_only=cache_only,
        )
    profile = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else None
    if profile is None:
        result.notes.append("no profile cached")
        return
    name = _text(profile.get("companyName"))
    if name is not None:
        result.fields["name"] = name
    beta = _number(profile.get("beta"))
    if beta is not None and not math.isnan(beta) and beta != 0:
        result.fields["beta"] = beta


def _signal_fields(ticker: str, result: EtfRefreshResult) -> None:
    """The BB+RSI / Warren fields, from the tables the monitored-watchlist jobs fill (an ETF on the `ETF` list or an
    E<number> list has them; any other ETF has no row, so these come out None). Same helpers as
    data/ticker_score.py. Deterministic local reads, so None is a real answer and is written."""
    with Session(engine) as session:
        entry = session.get(TechnicalEntrySignal, (ticker, DEFAULT_SIGNAL_TYPE, DEFAULT_TIMEFRAME))
        warren = session.get(TechnicalEntrySignal, (ticker, WARREN_SIGNAL_TYPE, WARREN_TIMEFRAME))
        last_buy = last_buy_signal_fired_at(session, ticker)
    result.fields.update(
        bb_rsi_entry_signal=is_entry_signal_active(entry.fired_at) if entry else None,
        warren_active_signal_kind=warren_active_up_kind(warren.signal_kind) if warren else None,
        warren_last_buy_fired_at=last_buy,
    )


def _record_source_error(result: EtfRefreshResult, source: str, exc: Exception) -> None:
    logger.error("%s: %s failed - %s", result.ticker, source, exc)
    result.errors.append(f"{source}: {exc}")


async def _refresh_one(
    ticker: str,
    bars: pd.DataFrame,
    spy_bars: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    params: WeinsteinParams,
    cache_only: bool,
) -> EtfRefreshResult:
    """Every source is tried on its own: one raising only costs its own fields."""
    result = EtfRefreshResult(ticker)
    try:
        _bar_fields(ticker, bars, spy_bars, result)
    except Exception as exc:  # noqa: BLE001 -- one source must not cost the others
        _record_source_error(result, "bars", exc)
    try:
        _weinstein_fields(bars, benchmark_bars, params, result)
    except Exception as exc:  # noqa: BLE001
        _record_source_error(result, "weinstein", exc)
    try:
        _signal_fields(ticker, result)
    except Exception as exc:  # noqa: BLE001
        _record_source_error(result, "signals", exc)
    try:
        await _info_fields(ticker, cache_only, result)
    except Exception as exc:  # noqa: BLE001
        _record_source_error(result, "etf_info", exc)
    try:
        await _profile_fields(ticker, cache_only, result)
    except Exception as exc:  # noqa: BLE001
        _record_source_error(result, "profile", exc)
    if "name" not in result.fields and result.info_name and not any(e.startswith("profile:") for e in result.errors):
        result.fields["name"] = result.info_name
    return result


def _store_trend_analysis(ticker: str, params: WeinsteinParams, result: EtfRefreshResult) -> None:
    """Writes the ETF's TrendAnalysis row from the Weinstein result already computed for its EtfScreenerRow fields.
    Its own failure costs only this table (recorded in the ETF's `errors`)."""
    stage, pending, bars_as_of = result.weinstein
    try:
        store_weinstein_results(ticker, stage, pending, bars_as_of, params)
        result.trend_analysis_written = True
    except Exception as exc:  # noqa: BLE001 -- must not cost the EtfScreenerRow write
        _record_source_error(result, "trend_analysis", exc)


async def _refresh_last_closes(targets: list[str]) -> dict[str, str]:
    """TickerLastClose for every target through the stock-side helper (it writes the rows itself, one per ticker, and
    leaves a failing ticker's stored close alone). Returns {ticker: reason} for the ones it could not write. The
    helper raising outright counts as a failure of every target."""
    try:
        summary = await refresh_last_closes(targets)
    except Exception as exc:  # noqa: BLE001 -- the other sources still run
        logger.error("ETF screener: last-close refresh failed - %s", exc)
        return {ticker: type(exc).__name__ for ticker in targets}
    return dict(summary["failures"])


def prune_etf_screener_rows(keep: list[str], dry_run: bool = False) -> int:
    """Deletes EtfScreenerRow rows whose ticker is not in `keep` (the ETF universe: an expired or delisted ETF).
    Returns the number deleted (or that would be). Genuinely deleted, like the other retention prunes."""
    with Session(engine) as session:
        stale = [t for t in session.exec(select(EtfScreenerRow.ticker)).all() if t not in set(keep)]
        if dry_run or not stale:
            return len(stale)
        session.execute(delete(EtfScreenerRow).where(EtfScreenerRow.ticker.in_(stale)))
        session.commit()
    return len(stale)


SIGNAL_FIELDS = frozenset({"bb_rsi_entry_signal", "warren_active_signal_kind", "warren_last_buy_fired_at"})


def _worth_writing(session: Session, ticker: str, fields: dict) -> bool:
    """A run that computed nothing but the (often None) signal fields must not create an all-NULL row for an ETF
    that has nothing yet (a seed with no cached data); it may still update a row that already exists, so a signal
    that ended is cleared."""
    if any(value is not None for key, value in fields.items() if key not in SIGNAL_FIELDS):
        return True
    return bool(fields) and session.get(EtfScreenerRow, ticker) is not None


def _breaches_failure_threshold(attempted: int, failed: int) -> bool:
    try:
        check_failure_threshold(attempted, failed, "")
    except RuntimeError:
        return True
    return False


async def refresh_etf_screener(
    tickers: list[str] | None = None,
    *,
    cache_only: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
    force_resync: bool = False,
) -> dict:
    """Refreshes the EtfScreenerRow of each ticker (default: the whole ETF universe).

    cache_only: computes from already-cached data only -- no bar fetch, no /etf/info or profile call (a stale cached
        row is used as is); makes no network call at all.
    dry_run: computes and returns everything but writes no EtfScreenerRow and prunes nothing. It does NOT stop the normal
        read-through caches (FMP responses, bars) from filling when it is not also cache_only: for a run that writes
        nothing at all, pass both.
    A LIVE run (neither cache_only nor dry_run) also writes each ETF's TrendAnalysis row (from the one Weinstein
    computation above) and its TickerLastClose row; cache_only and dry_run write neither (and cache_only has no
    network to fetch a last close with).
    force_resync: the weekly full resync the stock-side bar job does (every ticker's whole window refetched, so a small
    provider restatement cannot leave a permanent basis offset); the pipeline passes it on the same weekday.
    Retention: after a LIVE run that is not cache_only / dry_run and whose fetch phase succeeded (the batch bar
    fetch did not raise and the failure threshold was not breached), rows for tickers no longer in the ETF universe
    are deleted. `tickers=` (an explicit list) never prunes.

    Returns the summary dict: counts, per-ETF `results` (ticker -> fields/notes/errors), `failures`, `pruned`."""
    start = time.monotonic()
    with Session(engine) as session:
        universe = load_etf_universe(session, now)
        params = load_weinstein_params(session)
    explicit = tickers is not None
    targets = sorted({normalize_ticker(t) for t in tickers}) if explicit else universe
    benchmark = params.rs_benchmark
    wanted = sorted(set(targets) | {VS_BENCHMARK_TICKER, benchmark})

    batch_failed = False
    unserved = UnservedTickers()
    if not cache_only and targets:
        try:
            await get_or_fetch_bars_batch(
                wanted, DAILY_INTERVAL, WEINSTEIN_LOOKBACK_DAYS, auto_adjust=False, unserved_tickers=unserved,
                force=force_resync,
            )
        except Exception as exc:  # noqa: BLE001 -- bars missing for everyone; the other sources still run
            batch_failed = True
            logger.error("ETF screener: batch daily-bar fetch failed - %s", exc)

    def read_bars(symbol: str) -> pd.DataFrame:
        return read_cached_completed_daily_bars(symbol, WEINSTEIN_LOOKBACK_DAYS, reference=now)

    spy_bars = read_bars(VS_BENCHMARK_TICKER)
    benchmark_bars = spy_bars if benchmark == VS_BENCHMARK_TICKER else read_bars(benchmark)

    live = not cache_only and not dry_run
    last_close_failures = await _refresh_last_closes(targets) if live and targets else {}

    results: dict[str, EtfRefreshResult] = {}
    for index, ticker in enumerate(targets, start=1):
        result = EtfRefreshResult(ticker)
        try:
            result = await _refresh_one(ticker, read_bars(ticker), spy_bars, benchmark_bars, params, cache_only)
            if ticker in last_close_failures:
                result.errors.append(f"last_close: {last_close_failures[ticker]}")
            if live and result.weinstein is not None:
                _store_trend_analysis(ticker, params, result)
            if not dry_run:
                with Session(engine) as session:
                    if _worth_writing(session, ticker, result.fields):
                        upsert_etf_screener_row(session, ticker, now, **result.fields)
                        result.written = True
        except Exception as exc:  # noqa: BLE001 -- one ETF must never abort the run
            logger.error("[%d/%d] %s: FAILED - %s", index, len(targets), ticker, exc)
            result.errors.append(str(exc))
        results[ticker] = result
        logger.info(
            "[%d/%d] %s: %d field(s)%s%s", index, len(targets), ticker, len(result.fields),
            " written" if result.written else "", f", errors: {'; '.join(result.errors)}" if result.errors else "",
        )

    failures = [(t, "; ".join(r.errors)) for t, r in results.items() if r.errors]
    attempted = len(results)
    fetch_ok = not batch_failed and not _breaches_failure_threshold(attempted, len(failures))
    pruned = 0
    would_prune = 0
    if not explicit:
        if not cache_only and not dry_run and fetch_ok:
            pruned = prune_etf_screener_rows(universe)
        elif dry_run:
            would_prune = prune_etf_screener_rows(universe, dry_run=True)

    stale_count = 0
    if not cache_only:
        stale_count, _ = stale_ticker_count(targets, DAILY_INTERVAL)
    summary = {
        "processed": attempted,
        "written": sum(1 for r in results.values() if r.written),
        "trend_written": sum(1 for r in results.values() if r.trend_analysis_written),
        "last_close_written": (len(targets) - len(last_close_failures)) if live else 0,
        "failed": len(failures),
        "failures": failures,
        "pruned": pruned,
        "would_prune": would_prune,
        "fetch_ok": fetch_ok,
        "batch_failed": batch_failed,
        "stale_count": stale_count,
        "unserved_count": len(unserved),
        "cache_only": cache_only,
        "dry_run": dry_run,
        "results": results,
        "duration_seconds": time.monotonic() - start,
    }
    logger.info(
        "ETF screener refresh complete. Processed: %d. Written: %d. Failed: %d. Pruned: %d. Stale: %d. Duration: %.1fs.",
        attempted, summary["written"], len(failures), pruned, stale_count, summary["duration_seconds"],
    )
    return summary
